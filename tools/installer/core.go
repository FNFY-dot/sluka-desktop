// SPDX-License-Identifier: LicenseRef-Sluka
// Copyright (c) 2026 Sluka. Part of Sluka Desktop Setup; see LICENSE.txt.
// Sluka Desktop's setup: what it knows of Sluka Desktop's files, wherever it runs.
//
// The setup is one program: the window and Windows' parts in the *_windows.go files, the rest here.  What
// Sluka Desktop does itself -- unpacking its extension, its shortcuts, its add-on in Anki, what it put outside its
// folder -- the app installed is asked to do, with its own commands (app\run.py install-extension, ...), run by
// the Python it runs with.
package main

import (
	"archive/zip"
	"bufio"
	"bytes"
	"debug/pe"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net"
	"os"
	"path/filepath"
	"regexp"
	"runtime"
	"sort"
	"strconv"
	"strings"
	"time"
	"unicode/utf16"
)

const (
	AppName = "Sluka Desktop"
	// The setup itself, in the app's folder: what Settings > Apps runs to change or uninstall Sluka Desktop.
	SetupExe = "Sluka Desktop Setup.exe"
	// The setup in the Start menu, beside Sluka.
	SetupLink   = "Sluka Desktop Setup.lnk"
	DefaultPort = 47821
	Staging     = ".setup-new"
	OldDir      = ".setup-old"
)

// The app's own files, which an update replaces (with whatever else the new version brings) and an uninstall takes
// away.  ("Sluka Setup.cmd" was 0.10.0's setup; the licence files came with 0.12.4, THIRD-PARTY-NOTICES.txt became
// NOTICES.txt in 0.12.5.)
var Managed = []string{"app", "engine", "mpv", "anki", "README.txt", "Sluka.cmd", "Sluka Setup.cmd", "LICENSE.txt",
	"NOTICES.txt", "THIRD-PARTY-NOTICES.txt", "LICENSES"}

// Yours, which an update leaves as they are: your data (words, books, settings, what the web view keeps), the Sluka
// extension, config.ini.
var Kept = []string{"data", "extension", "config.ini"}

var versionRe = regexp.MustCompile(`__version__\s*=\s*"([^"]+)"`)

// ------------------------------------------------------------------------------------------------ versions

// VersionTuple: "0.10.2" as [0 10 2].
func VersionTuple(text string) []int {
	var out []int
	for _, part := range regexp.MustCompile(`\d+`).FindAllString(text, 4) {
		n, _ := strconv.Atoi(part)
		out = append(out, n)
	}
	if len(out) == 0 {
		out = []int{0}
	}
	return out
}

// CompareVersions: -1, 0 or 1.
func CompareVersions(a, b string) int {
	x, y := VersionTuple(a), VersionTuple(b)
	for i := 0; i < len(x) || i < len(y); i++ {
		var p, q int
		if i < len(x) {
			p = x[i]
		}
		if i < len(y) {
			q = y[i]
		}
		if p != q {
			if p < q {
				return -1
			}
			return 1
		}
	}
	return 0
}

// ------------------------------------------------------------------------------------------------ paths

// SamePath: two paths for one place (Windows ignores the case of letters).
func SamePath(a, b string) bool {
	if a == "" || b == "" {
		return false
	}
	x, y := filepath.Clean(a), filepath.Clean(b)
	if abs, err := filepath.Abs(x); err == nil {
		x = abs
	}
	if abs, err := filepath.Abs(y); err == nil {
		y = abs
	}
	if runtime.GOOS == "windows" {
		return strings.EqualFold(x, y)
	}
	return x == y
}

// Inside: whether path is in folder (or is it).
func Inside(path, folder string) bool {
	p, f := filepath.Clean(path), filepath.Clean(folder)
	if runtime.GOOS == "windows" {
		p, f = strings.ToLower(p), strings.ToLower(f)
	}
	return p == f || strings.HasPrefix(p, strings.TrimRight(f, `\/`)+string(filepath.Separator))
}

func exists(path string) bool {
	_, err := os.Lstat(path)
	return err == nil
}

func isFile(path string) bool {
	info, err := os.Stat(path)
	return err == nil && info.Mode().IsRegular()
}

func isDir(path string) bool {
	info, err := os.Stat(path)
	return err == nil && info.IsDir()
}

// FolderHasThings: whether a folder holds anything but the setup's own scratch folders.
func FolderHasThings(folder string) bool {
	entries, err := os.ReadDir(folder)
	if err != nil {
		return false
	}
	for _, e := range entries {
		if e.Name() != Staging && e.Name() != OldDir {
			return true
		}
	}
	return false
}

// ------------------------------------------------------------------------------------------------ an install

// Install: a Sluka Desktop in a folder.
type Install struct{ Root string }

func (i Install) Exists() bool {
	return i.Root != "" && isFile(filepath.Join(i.Root, "app", "run.py")) &&
		isFile(filepath.Join(i.Root, "app", "sluka_desktop", "__init__.py"))
}

func (i Install) Version() string {
	data, err := os.ReadFile(filepath.Join(i.Root, "app", "sluka_desktop", "__init__.py"))
	if err != nil {
		return ""
	}
	if m := versionRe.FindSubmatch(data); m != nil {
		return string(m[1])
	}
	return "?"
}

func (i Install) ExtensionVersion() string {
	data, err := os.ReadFile(filepath.Join(i.Root, "extension", "manifest.json"))
	if err != nil {
		return ""
	}
	var manifest map[string]any
	if json.Unmarshal(trimBOM(data), &manifest) != nil {
		return ""
	}
	if v, ok := manifest["version"].(string); ok && v != "" {
		return v
	}
	return "?"
}

// Port: the app's address on this computer (config.ini, [app] port), where it answers when it runs.
func (i Install) Port() int {
	data, err := os.ReadFile(filepath.Join(i.Root, "config.ini"))
	if err != nil {
		return DefaultPort
	}
	for _, section := range []string{"app", "browser"} {
		if v := iniValue(string(trimBOM(data)), section, "port"); v != "" {
			if n, err := strconv.Atoi(v); err == nil && n >= 1024 && n <= 65535 {
				return n
			}
		}
	}
	return DefaultPort
}

func (i Install) Same(o Install) bool { return SamePath(i.Root, o.Root) }

func (i Install) Describe() string {
	text := fmt.Sprintf("%s %s, in %s", AppName, i.Version(), i.Root)
	if ext := i.ExtensionVersion(); ext != "" {
		return text + ", with the Sluka extension " + ext
	}
	return text + ", with no Sluka extension yet"
}

func trimBOM(data []byte) []byte {
	if len(data) >= 3 && data[0] == 0xEF && data[1] == 0xBB && data[2] == 0xBF {
		return data[3:]
	}
	return data
}

// iniValue: one value of an .ini file ("" where it has none).
func iniValue(text, section, key string) string {
	current := ""
	for _, line := range strings.Split(text, "\n") {
		line = strings.TrimSpace(line)
		if line == "" || line[0] == ';' || line[0] == '#' {
			continue
		}
		if line[0] == '[' && strings.HasSuffix(line, "]") {
			current = strings.ToLower(strings.TrimSpace(line[1 : len(line)-1]))
			continue
		}
		if current != strings.ToLower(section) {
			continue
		}
		name, value, ok := strings.Cut(line, "=")
		if !ok {
			name, value, ok = strings.Cut(line, ":")
		}
		if ok && strings.EqualFold(strings.TrimSpace(name), key) {
			return strings.TrimSpace(value)
		}
	}
	return ""
}

// ------------------------------------------------------------------------------------------------ the payload

// Payload: Sluka Desktop's files, in a zip -- this setup's own (after the program), a sluka-desktop zip, or another
// setup's.
type Payload struct {
	Path    string
	Prefix  string
	Version string
	Size    int64
	Files   int
	Windows bool // (the Windows edition: Sluka.cmd in it)
}

var ErrNotSluka = errors.New("no Sluka Desktop in it")

const payloadHead = "app/sluka_desktop/__init__.py"

func FindPayload(path string) (*Payload, error) {
	r, err := zip.OpenReader(path)
	if err != nil {
		return nil, err
	}
	defer r.Close()
	names := map[string]*zip.File{}
	for _, f := range r.File {
		names[f.Name] = f
	}
	var prefixes []string
	for name := range names {
		if !strings.HasSuffix(name, payloadHead) {
			continue
		}
		p := name[:len(name)-len(payloadHead)]
		if (p != "" && !strings.HasSuffix(p, "/")) || strings.Count(p, "/") > 2 {
			continue
		}
		if _, ok := names[p+"app/run.py"]; !ok {
			continue
		}
		prefixes = append(prefixes, p)
	}
	if len(prefixes) == 0 {
		return nil, ErrNotSluka
	}
	sort.Slice(prefixes, func(i, j int) bool { return len(prefixes[i]) < len(prefixes[j]) })
	prefix := prefixes[0]
	p := &Payload{Path: path, Prefix: prefix, Version: "?"}
	if rc, err := names[prefix+payloadHead].Open(); err == nil {
		data, _ := io.ReadAll(io.LimitReader(rc, 1<<20))
		rc.Close()
		if m := versionRe.FindSubmatch(data); m != nil {
			p.Version = string(m[1])
		}
	}
	for _, f := range r.File {
		if strings.HasPrefix(f.Name, prefix) && !strings.HasSuffix(f.Name, "/") {
			p.Size += int64(f.UncompressedSize64)
			p.Files++
		}
	}
	_, p.Windows = names[prefix+"Sluka.cmd"]
	return p, nil
}

func checkRel(rel string) error {
	if rel == "" || strings.HasPrefix(rel, "/") || strings.Contains(rel, ":") {
		return errors.New("not allowed")
	}
	for _, part := range strings.Split(rel, "/") {
		if part == "" || part == "." || part == ".." {
			return errors.New("not allowed")
		}
	}
	return nil
}

// Extract: the payload's files into a new folder -- none outside it, whatever the zip names them.  What was written
// (as the zip names them, under its prefix).
func (p *Payload) Extract(target string, progress func(done, total int64)) ([]string, error) {
	r, err := zip.OpenReader(p.Path)
	if err != nil {
		return nil, err
	}
	defer r.Close()
	if err := os.MkdirAll(target, 0o755); err != nil {
		return nil, err
	}
	root, err := filepath.Abs(target)
	if err != nil {
		return nil, err
	}
	var written []string
	var done int64
	for _, f := range r.File {
		if !strings.HasPrefix(f.Name, p.Prefix) || strings.HasSuffix(f.Name, "/") || f.FileInfo().IsDir() {
			continue
		}
		rel := strings.ReplaceAll(f.Name[len(p.Prefix):], `\`, "/")
		if checkRel(rel) != nil {
			return written, fmt.Errorf("the zip holds a path that is not allowed: %s", f.Name)
		}
		if f.Mode()&os.ModeSymlink != 0 {
			return written, fmt.Errorf("the zip holds a link: %s", f.Name)
		}
		dest := filepath.Join(root, filepath.FromSlash(rel))
		if !Inside(dest, root) || SamePath(dest, root) {
			return written, fmt.Errorf("the zip holds a path that is not allowed: %s", f.Name)
		}
		if err := os.MkdirAll(filepath.Dir(dest), 0o755); err != nil {
			return written, err
		}
		if err := writeZipFile(f, dest); err != nil {
			return written, err
		}
		written = append(written, rel)
		done += int64(f.UncompressedSize64)
		if progress != nil {
			progress(done, p.Size)
		}
	}
	return written, nil
}

func writeZipFile(f *zip.File, dest string) error {
	src, err := f.Open()
	if err != nil {
		return err
	}
	defer src.Close()
	out, err := os.OpenFile(dest, os.O_CREATE|os.O_WRONLY|os.O_TRUNC, 0o644)
	if err != nil {
		return err
	}
	if _, err := io.Copy(out, src); err != nil {
		out.Close()
		return err
	}
	return out.Close()
}

// rename: os.Rename (the tests put one that fails here).
var rename = os.Rename

// PutInPlace: the new files moved into the app's folder in place of the old, all or none: where one cannot be moved
// (a program has a file in it open), everything is put back as it was, and the error returned.  Data, extension
// and config.ini are never touched (nor the setup itself, which is put apart); what of the app's own the new
// version no longer has goes.
func PutInPlace(staging, root string) error {
	old := filepath.Join(root, OldDir)
	os.RemoveAll(old)
	if err := os.MkdirAll(old, 0o755); err != nil {
		return err
	}
	set := map[string]bool{}
	if entries, err := os.ReadDir(staging); err == nil {
		for _, e := range entries {
			set[e.Name()] = true
		}
	}
	for _, name := range Managed {
		set[name] = true
	}
	skip := map[string]bool{Staging: true, OldDir: true, strings.ToLower(SetupExe): true}
	for _, name := range Kept {
		skip[name] = true
	}
	var names []string
	for name := range set {
		if !skip[name] && !skip[strings.ToLower(name)] {
			names = append(names, name)
		}
	}
	sort.Strings(names)
	type step struct {
		name      string
		aside, in bool
	}
	var steps []*step
	undo := func() {
		for i := len(steps) - 1; i >= 0; i-- {
			s := steps[i]
			if s.in {
				rename(filepath.Join(root, s.name), filepath.Join(staging, s.name))
			}
			if s.aside {
				rename(filepath.Join(old, s.name), filepath.Join(root, s.name))
			}
		}
		os.RemoveAll(old)
	}
	for _, name := range names {
		newPath, target := filepath.Join(staging, name), filepath.Join(root, name)
		if !exists(newPath) && !exists(target) {
			continue
		}
		s := &step{name: name}
		steps = append(steps, s)
		if exists(target) {
			if err := rename(target, filepath.Join(old, name)); err != nil {
				undo()
				return err
			}
			s.aside = true
		}
		if exists(newPath) {
			if err := rename(newPath, target); err != nil {
				undo()
				return err
			}
			s.in = true
		}
	}
	os.RemoveAll(old)
	return nil
}

// RemoveInstall: the app's files taken away (yours too, unless kept); what could not be (in use).
func RemoveInstall(root string, keep bool) []string {
	names := append(append([]string{}, Managed...), "extension", Staging, OldDir, SetupExe, SetupExe+".old")
	if !keep {
		names = append(names, "data", "config.ini")
	}
	var left []string
	for _, name := range names {
		path := filepath.Join(root, name)
		if !exists(path) {
			continue
		}
		if err := os.RemoveAll(path); err != nil || exists(path) {
			left = append(left, path)
		}
	}
	return left
}

// StubSize: how much of a program is the program (a Windows .exe: up to the end of its last section; what follows
// is its payload).
func StubSize(path string) (int64, error) {
	f, err := pe.Open(path)
	if err != nil {
		return 0, err
	}
	defer f.Close()
	var end int64
	for _, s := range f.Sections {
		if e := int64(s.Offset) + int64(s.Size); e > end {
			end = e
		}
	}
	if end == 0 {
		return 0, errors.New("no sections")
	}
	return end, nil
}

// WriteStub: the program part of src (no payload) written as dst; one there in use (the setup that runs) is put
// aside as dst.old rather than written over.
func WriteStub(src, dst string) error {
	size, err := StubSize(src)
	if err != nil {
		return err
	}
	in, err := os.Open(src)
	if err != nil {
		return err
	}
	defer in.Close()
	part := dst + ".part"
	out, err := os.OpenFile(part, os.O_CREATE|os.O_WRONLY|os.O_TRUNC, 0o755)
	if err != nil {
		return err
	}
	if _, err := io.CopyN(out, in, size); err != nil {
		out.Close()
		os.Remove(part)
		return err
	}
	if err := out.Close(); err != nil {
		os.Remove(part)
		return err
	}
	if exists(dst) {
		if os.Remove(dst) != nil {
			os.Remove(dst + ".old")
			if err := os.Rename(dst, dst+".old"); err != nil {
				os.Remove(part)
				return err
			}
		}
	}
	return os.Rename(part, dst)
}

// ------------------------------------------------------------------------------------------------ zips

// Extension: the browser extension in a zip (or folder), as the app's install-extension finds it.
type Extension struct {
	Name, Version string
	Sluka         bool // (manifest version 3, with a background worker: the Chrome edition)
}

func ExtensionIn(path string) (*Extension, error) {
	var data []byte
	if isDir(path) {
		folders := []string{path}
		if entries, err := os.ReadDir(path); err == nil {
			for _, e := range entries {
				if e.IsDir() {
					folders = append(folders, filepath.Join(path, e.Name()))
				}
			}
		}
		for _, folder := range folders {
			if d, err := os.ReadFile(filepath.Join(folder, "manifest.json")); err == nil {
				data = d
				break
			}
		}
	} else {
		r, err := zip.OpenReader(path)
		if err != nil {
			return nil, err
		}
		defer r.Close()
		byName := map[string]*zip.File{}
		var tops []string
		for _, f := range r.File {
			byName[f.Name] = f
			if top, _, ok := strings.Cut(f.Name, "/"); ok {
				tops = append(tops, top)
			}
		}
		sort.Strings(tops)
		head := ""
		if _, ok := byName["manifest.json"]; ok {
			head = "manifest.json"
		} else {
			for _, top := range tops {
				if _, ok := byName[top+"/manifest.json"]; ok {
					head = top + "/manifest.json"
					break
				}
			}
		}
		if head == "" {
			return nil, errors.New("no manifest.json in it")
		}
		rc, err := byName[head].Open()
		if err != nil {
			return nil, err
		}
		data, _ = io.ReadAll(io.LimitReader(rc, 4<<20))
		rc.Close()
	}
	if data == nil {
		return nil, errors.New("no manifest.json in it")
	}
	var manifest map[string]any
	if err := json.Unmarshal(trimBOM(data), &manifest); err != nil {
		return nil, err
	}
	ext := &Extension{Version: "?"}
	if v, ok := manifest["version"].(string); ok && v != "" {
		ext.Version = v
	}
	if n, ok := manifest["name"].(string); ok && !strings.HasPrefix(n, "__MSG_") {
		ext.Name = n
	}
	mv, _ := manifest["manifest_version"].(float64)
	bg, hasBg := manifest["background"]
	ext.Sluka = mv == 3 && hasBg && bg != nil
	return ext, nil
}

// Found: a zip of Sluka's.
type Found struct {
	Path    string
	Kind    string // "desktop" or "extension"
	Version string
	Words   string
}

// Describe: what a file is -- Sluka Desktop (a zip, or a setup with it inside), a browser extension, or neither.
func Describe(path string) (Found, error) {
	if isFile(path) {
		if p, err := FindPayload(path); err == nil {
			return Found{path, "desktop", p.Version, fmt.Sprintf("%s %s", AppName, p.Version)}, nil
		}
	}
	ext, err := ExtensionIn(path)
	if err != nil {
		return Found{}, fmt.Errorf("%s is neither %s nor a browser extension", filepath.Base(path), AppName)
	}
	name := ext.Name
	if name == "" {
		name = "an extension"
	}
	return Found{path, "extension", ext.Version, fmt.Sprintf("%s %s, the extension", name, ext.Version)}, nil
}

// FindZips: Sluka's zips (and setups) in these folders, the newest first; not the one named.
func FindZips(folders []string, not string, kinds ...string) []Found {
	type file struct {
		path string
		when time.Time
	}
	var files []file
	seen := map[string]bool{}
	for _, folder := range folders {
		entries, err := os.ReadDir(folder)
		if err != nil {
			continue
		}
		for _, e := range entries {
			name := strings.ToLower(e.Name())
			ext := filepath.Ext(name)
			if e.IsDir() || !strings.Contains(name, "sluka") || (ext != ".zip" && ext != ".exe" && ext != ".cmd") {
				continue
			}
			path := filepath.Join(folder, e.Name())
			key := strings.ToLower(path)
			if seen[key] || (not != "" && SamePath(path, not)) {
				continue
			}
			seen[key] = true
			if info, err := e.Info(); err == nil {
				files = append(files, file{path, info.ModTime()})
			}
		}
	}
	sort.SliceStable(files, func(i, j int) bool { return files[i].when.After(files[j].when) })
	var found []Found
	for n, f := range files {
		if n >= 30 || len(found) >= 6 {
			break
		}
		d, err := Describe(f.path)
		if err != nil {
			continue
		}
		for _, k := range kinds {
			if d.Kind == k {
				found = append(found, d)
				break
			}
		}
	}
	return found
}

// NewestExtension: the Sluka extension zip of the highest version among these folders' ("" if none).
func NewestExtension(folders []string) Found {
	var best Found
	for _, f := range FindZips(folders, "", "extension") {
		ext, err := ExtensionIn(f.Path)
		if err != nil || !ext.Sluka {
			continue
		}
		if best.Path == "" || CompareVersions(f.Version, best.Version) > 0 {
			best = f
		}
	}
	return best
}

// ------------------------------------------------------------------------------------------------ shortcuts

// asciiLower: the ASCII letters of these bytes made lower case (in UTF-16 too: the case Windows ignores).
func asciiLower(data []byte) []byte {
	out := make([]byte, len(data))
	for i, b := range data {
		if b >= 'A' && b <= 'Z' {
			b += 'a' - 'A'
		}
		out[i] = b
	}
	return out
}

func utf16le(text string) []byte {
	units := utf16.Encode([]rune(text))
	out := make([]byte, 0, 2*len(units))
	for _, u := range units {
		out = append(out, byte(u), byte(u>>8))
	}
	return out
}

// LinkLeadsTo: whether a shortcut (.lnk) starts the app in this folder: the folder is in it (Windows writes a
// shortcut's paths and arguments in UTF-16).
func LinkLeadsTo(data []byte, root string, sep string) bool {
	want := strings.TrimRight(root, `\/`) + sep // ("Sluka Desktop 2" is another folder)
	folded := asciiLower(data)
	for _, text := range []string{want, strings.ToLower(want)} {
		wide := utf16le(text)
		if bytes.Contains(data, wide) || bytes.Contains(folded, wide) {
			return true
		}
	}
	return false
}

var linkRootRes = []*regexp.Regexp{
	regexp.MustCompile(`([A-Za-z]:\\[^"<>|\x00-\x1f]*?)\\(?:app\\run\.py|Sluka\.cmd)`),
	regexp.MustCompile(`(/[^"<>|\x00-\x1f]*?)/(?:app/run\.py|Sluka\.cmd)`), // (elsewhere than Windows: the tests')
}

// LinkRoots: the app folders a shortcut starts.
func LinkRoots(data []byte) []string {
	var found []string
	for start := 0; start < 2 && start < len(data); start++ {
		units := make([]uint16, 0, len(data)/2)
		for i := start; i+1 < len(data); i += 2 {
			units = append(units, uint16(data[i])|uint16(data[i+1])<<8)
		}
		text := string(utf16.Decode(units))
		for _, re := range linkRootRes {
			for _, m := range re.FindAllStringSubmatch(text, -1) {
				found = append(found, m[1])
			}
		}
	}
	return found
}

// ------------------------------------------------------------------------------------------------ the app running

type appInfo struct {
	App struct {
		Name    string `json:"name"`
		Version string `json:"version"`
	} `json:"app"`
	Data      string `json:"data"`
	Extension struct {
		Folder string `json:"folder"`
	} `json:"extension"`
}

func askApp(port int, timeout time.Duration) *appInfo {
	// (HTTP spoken plainly, to this computer only: no proxy can come between)
	conn, err := net.DialTimeout("tcp", fmt.Sprintf("127.0.0.1:%d", port), timeout)
	if err != nil {
		return nil
	}
	defer conn.Close()
	conn.SetDeadline(time.Now().Add(timeout + time.Second))
	if _, err := conn.Write([]byte("GET /__sluka__/api/info HTTP/1.0\r\nHost: 127.0.0.1\r\nAccept: application/json\r\n\r\n")); err != nil {
		return nil
	}
	data, _ := io.ReadAll(io.LimitReader(conn, 1<<20))
	head, body, ok := bytes.Cut(data, []byte("\r\n\r\n"))
	if !ok || !bytes.HasPrefix(head, []byte("HTTP/1.")) || !bytes.Contains(bytes.SplitN(head, []byte("\r\n"), 2)[0], []byte(" 200")) {
		return nil
	}
	var info appInfo
	if json.Unmarshal(body, &info) != nil || info.App.Name != AppName {
		return nil
	}
	return &info
}

// Running: whether this copy of the app is running (it answers on its address, and says it is in this folder).
func Running(i Install) bool {
	info := askApp(i.Port(), 1500*time.Millisecond)
	if info == nil {
		return false
	}
	for _, said := range []string{info.Data, info.Extension.Folder} {
		for _, mine := range []string{filepath.Join(i.Root, "data"), filepath.Join(i.Root, "extension")} {
			if SamePath(said, mine) {
				return true
			}
		}
	}
	return false
}

// RunningRoot: the folder of a Sluka Desktop running on the usual address ("" if none).
func RunningRoot() string {
	info := askApp(DefaultPort, time.Second)
	if info == nil || info.Extension.Folder == "" {
		return ""
	}
	return filepath.Dir(info.Extension.Folder)
}

// ------------------------------------------------------------------------------------------------ lines

// Lines: what a program writes, line by line, to a function.
func Lines(r io.Reader, each func(string)) {
	scanner := bufio.NewScanner(r)
	scanner.Buffer(make([]byte, 64*1024), 1<<20)
	for scanner.Scan() {
		each(strings.TrimRight(scanner.Text(), "\r"))
	}
}
