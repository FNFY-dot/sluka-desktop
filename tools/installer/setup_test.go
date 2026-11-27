// SPDX-License-Identifier: LicenseRef-Sluka
// Copyright (c) 2026 Sluka. Part of Sluka Desktop Setup; see LICENSE.txt.
package main

import (
	"archive/zip"
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"net"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"testing"
	"time"
)

// ------------------------------------------------------------------------------------------------ stand-ins

func writeZip(t *testing.T, path string, files map[string]string, before []byte) string {
	t.Helper()
	var buf bytes.Buffer
	w := zip.NewWriter(&buf)
	names := make([]string, 0, len(files))
	for name := range files {
		names = append(names, name)
	}
	sort.Strings(names)
	for _, name := range names {
		f, err := w.Create(name)
		if err != nil {
			t.Fatal(err)
		}
		f.Write([]byte(files[name]))
	}
	if err := w.Close(); err != nil {
		t.Fatal(err)
	}
	os.MkdirAll(filepath.Dir(path), 0o755)
	if err := os.WriteFile(path, append(append([]byte{}, before...), buf.Bytes()...), 0o644); err != nil {
		t.Fatal(err)
	}
	return path
}

func appFiles(version string, extra map[string]string, leaveOut ...string) map[string]string {
	files := map[string]string{
		"app/run.py":                     "print('run')\n",
		"app/sluka_desktop/__init__.py":  fmt.Sprintf("__version__ = \"%s\"\n", version),
		"engine/LunaHost64.dll":          "dll",
		"engine/ocr/model.onnx":          "model",
		"anki/sluka_desktop/__init__.py": "# Sluka Desktop's add-on\n",
		"mpv/sluka.lua":                  "-- lua\n",
		"README.txt":                     "Sluka Desktop " + version + "\n",
		"Sluka.cmd":                      "@echo off\r\n",
	}
	for k, v := range extra {
		files[k] = v
	}
	for _, name := range leaveOut {
		delete(files, name)
	}
	return files
}

func makePayload(t *testing.T, path, version, prefix string, extra map[string]string, leaveOut ...string) string {
	files := map[string]string{}
	for name, text := range appFiles(version, extra, leaveOut...) {
		files[prefix+name] = text
	}
	return writeZip(t, path, files, nil)
}

func makeExtension(t *testing.T, path, version string, background bool) string {
	manifest := map[string]any{"manifest_version": 3, "name": "Sluka", "version": version}
	if background {
		manifest["background"] = map[string]any{"service_worker": "background.js"}
	}
	data, _ := json.Marshal(manifest)
	return writeZip(t, path, map[string]string{"sluka-extension/manifest.json": string(data),
		"sluka-extension/background.js": "// worker\n"}, nil)
}

// unpacked: a copy of the app unpacked by hand, with an extension, data and config.ini.
func unpacked(t *testing.T, root, version, ext string, extra map[string]string, leaveOut ...string) Install {
	t.Helper()
	for name, text := range appFiles(version, extra, leaveOut...) {
		path := filepath.Join(root, filepath.FromSlash(name))
		os.MkdirAll(filepath.Dir(path), 0o755)
		os.WriteFile(path, []byte(text), 0o644)
	}
	if ext != "" {
		os.MkdirAll(filepath.Join(root, "extension"), 0o755)
		os.WriteFile(filepath.Join(root, "extension", "manifest.json"), []byte(`{"manifest_version": 3, "version": "`+ext+`"}`), 0o644)
	}
	os.MkdirAll(filepath.Join(root, "data"), 0o755)
	os.WriteFile(filepath.Join(root, "data", "storage.sqlite"), []byte("your words"), 0o644)
	os.WriteFile(filepath.Join(root, "config.ini"), []byte("[app]\nport = 47999\n"), 0o644)
	return Install{root}
}

func link(root string) []byte {
	return utf16le("L\x00pythonw.exe\x00-I \"" + root + "/app/run.py\"\x00" + root)
}

func tree(t *testing.T, root string) map[string]string {
	t.Helper()
	out := map[string]string{}
	filepath.Walk(root, func(path string, info os.FileInfo, err error) error {
		if err == nil && info.Mode().IsRegular() {
			rel, _ := filepath.Rel(root, path)
			data, _ := os.ReadFile(path)
			out[filepath.ToSlash(rel)] = string(data)
		}
		return nil
	})
	return out
}

type fakePlatform struct {
	base     string
	reg      map[string]any
	python   *Python
	anki     bool
	calls    [][]string
	later    []string
	launched []string
	fail     map[string]bool
	windows  bool
}

func newFake(t *testing.T) *fakePlatform {
	base := t.TempDir()
	for _, f := range []string{"Desktop", "Start Menu", "Downloads"} {
		os.MkdirAll(filepath.Join(base, f), 0o755)
	}
	return &fakePlatform{base: base, python: &Python{Exe: "python.exe", Windowless: "pythonw.exe", Version: "3.13.1", Bits: 64},
		fail: map[string]bool{}}
}

func (f *fakePlatform) DefaultFolder() string { return filepath.Join(f.base, "Programs", AppName) }
func (f *fakePlatform) ProgramFiles() []string {
	return []string{filepath.Join(f.base, "Program Files")}
}
func (f *fakePlatform) ShellFolder(which string) string {
	if which == "desktop" {
		return filepath.Join(f.base, "Desktop")
	}
	return filepath.Join(f.base, "Start Menu")
}
func (f *fakePlatform) Downloads() string   { return filepath.Join(f.base, "Downloads") }
func (f *fakePlatform) LocalFolder() string { return filepath.Join(f.base, "Local", "sluka-desktop") }
func (f *fakePlatform) Registered() string {
	if f.reg == nil {
		return ""
	}
	return f.reg["InstallLocation"].(string)
}
func (f *fakePlatform) Register(i Install, size int64) error {
	f.reg = registryValues(i, size)
	return nil
}
func (f *fakePlatform) Unregister(i Install) {
	if f.reg != nil && SamePath(f.Registered(), i.Root) {
		f.reg = nil
	}
}
func (f *fakePlatform) AnkiHere() bool { return f.anki }
func (f *fakePlatform) FindPython() (*Python, error) {
	if f.python == nil {
		return nil, ErrNoPython
	}
	return f.python, nil
}
func (f *fakePlatform) RunApp(py *Python, i Install, each func(string), args ...string) (int, error) {
	f.calls = append(f.calls, args)
	if f.fail[args[0]] {
		each("sluka: it went wrong")
		return 1, nil
	}
	switch args[0] {
	case "install-extension":
		ext, err := ExtensionIn(args[1])
		if err != nil || !ext.Sluka {
			each("sluka: This does not look like the Sluka extension")
			return 1, nil
		}
		r, _ := zip.OpenReader(args[1])
		defer r.Close()
		os.RemoveAll(filepath.Join(i.Root, "extension"))
		for _, zf := range r.File {
			_, rel, _ := strings.Cut(zf.Name, "/")
			dest := filepath.Join(i.Root, "extension", rel)
			os.MkdirAll(filepath.Dir(dest), 0o755)
			writeZipFile(zf, dest)
		}
		each("Sluka " + ext.Version + " is in " + filepath.Join(i.Root, "extension"))
	case "install-menu":
		for _, which := range []string{"desktop", "programs"} {
			flag := map[string]string{"desktop": "--no-desktop", "programs": "--no-start-menu"}[which]
			path := filepath.Join(f.ShellFolder(which), "Sluka.lnk")
			wanted := true
			for _, a := range args {
				if a == flag {
					wanted = false
				}
			}
			if wanted {
				os.WriteFile(path, link(i.Root), 0o644)
			} else if data, err := os.ReadFile(path); err == nil && LinkLeadsTo(data, i.Root, "/") {
				os.Remove(path)
			}
		}
		os.MkdirAll(filepath.Join(i.Root, "data"), 0o755)
		os.WriteFile(filepath.Join(i.Root, "data", "sluka.ico"), []byte("icon"), 0o644)
	case "remove-from-pc":
		for _, which := range []string{"desktop", "programs"} {
			path := filepath.Join(f.ShellFolder(which), "Sluka.lnk")
			if data, err := os.ReadFile(path); err == nil && LinkLeadsTo(data, i.Root, "/") {
				os.Remove(path)
			}
		}
	}
	return 0, nil
}
func (f *fakePlatform) MakeSetupLink(i Install, path string) error {
	return os.WriteFile(path, utf16le(filepath.Join(i.Root, SetupExe)), 0o644)
}
func (f *fakePlatform) RemoveLater(path string) { f.later = append(f.later, path) }
func (f *fakePlatform) Launch(py *Python, i Install, links []string) error {
	f.launched = append(f.launched, i.Root)
	return nil
}
func (f *fakePlatform) Separator() string {
	if f.windows {
		return `\`
	}
	return "/"
}

type quietReporter struct{ lines []string }

func (q *quietReporter) Status(text string)         { q.lines = append(q.lines, "status: "+text) }
func (q *quietReporter) Progress(done, total int64) {}
func (q *quietReporter) Log(line string)            { q.lines = append(q.lines, line) }

func setupFor(t *testing.T, f *fakePlatform, payload string) *Setup {
	s := &Setup{P: f, Self: filepath.Join(f.base, "Downloads", "Sluka-Desktop-Setup.exe"), Python: f.python}
	if payload != "" {
		p, err := FindPayload(payload)
		if err != nil {
			t.Fatal(err)
		}
		s.Payload = p
	}
	return s
}

// ------------------------------------------------------------------------------------------------ the files

func TestVersions(t *testing.T) {
	cases := []struct {
		a, b string
		want int
	}{{"0.10.0", "0.9.0", 1}, {"0.9.0", "0.10.0", -1}, {"0.10.0", "0.10", 0}, {"1.0", "0.99.9", 1}, {"", "0.1", -1}}
	for _, c := range cases {
		if got := CompareVersions(c.a, c.b); got != c.want {
			t.Errorf("CompareVersions(%q, %q) = %d, want %d", c.a, c.b, got, c.want)
		}
	}
}

func TestPayloads(t *testing.T) {
	dir := t.TempDir()
	stub := bytes.Repeat([]byte("MZ program part "), 4096)
	for _, prefix := range []string{"payload/sluka-desktop/", "sluka-desktop/", ""} {
		files := map[string]string{}
		for name, text := range appFiles("0.11.0", nil) {
			files[prefix+name] = text
		}
		files["other/thing.txt"] = "not the app's"
		path := writeZip(t, filepath.Join(dir, "p"+fmt.Sprint(len(prefix))+".exe"), files, stub)
		p, err := FindPayload(path)
		if err != nil {
			t.Fatalf("%q: %v", prefix, err)
		}
		want := 8
		if prefix == "" {
			want = 9 // (with no folder of its own, all of the zip is the app's)
		}
		if p.Prefix != prefix || p.Version != "0.11.0" || !p.Windows || p.Files != want {
			t.Errorf("%q: %+v", prefix, p)
		}
		written, err := p.Extract(filepath.Join(dir, "out"+fmt.Sprint(len(prefix))), nil)
		if err != nil || len(written) != want {
			t.Fatalf("%q: %v %v", prefix, written, err)
		}
		got := tree(t, filepath.Join(dir, "out"+fmt.Sprint(len(prefix))))
		if got["app/sluka_desktop/__init__.py"] == "" || (prefix != "" && got["other/thing.txt"] != "") {
			t.Errorf("%q: %v", prefix, got)
		}
	}
	tails := makePayload(t, filepath.Join(dir, "tails.zip"), "0.11.0", "sluka-desktop/", nil, "Sluka.cmd")
	if p, _ := FindPayload(tails); p.Windows {
		t.Error("a Linux edition taken for Windows'")
	}
	ext := makeExtension(t, filepath.Join(dir, "ext.zip"), "0.7.4", true)
	if _, err := FindPayload(ext); !errors.Is(err, ErrNotSluka) {
		t.Errorf("an extension taken for the app: %v", err)
	}
}

func TestUnsafeZips(t *testing.T) {
	dir := t.TempDir()
	for _, bad := range []string{"sluka-desktop/../../evil.txt", "sluka-desktop/app/../../evil.txt", "sluka-desktop/C:/evil.txt"} {
		files := appFiles("0.11.0", nil)
		withPrefix := map[string]string{}
		for k, v := range files {
			withPrefix["sluka-desktop/"+k] = v
		}
		withPrefix[bad] = "evil"
		path := writeZip(t, filepath.Join(dir, "bad.zip"), withPrefix, nil)
		p, err := FindPayload(path)
		if err != nil {
			t.Fatal(err)
		}
		if _, err := p.Extract(filepath.Join(dir, "out", "x"), nil); err == nil || !strings.Contains(err.Error(), "not allowed") {
			t.Errorf("%s: %v", bad, err)
		}
		filepath.Walk(dir, func(path string, info os.FileInfo, err error) error {
			if err == nil && info.Name() == "evil.txt" {
				t.Errorf("written outside: %s", path)
			}
			return nil
		})
	}
}

func TestPutInPlace(t *testing.T) {
	dir := t.TempDir()
	root := filepath.Join(dir, "Sluka Desktop")
	unpacked(t, root, "0.10.0", "0.7.4", map[string]string{"app/gone.py": "old", "Sluka Setup.cmd": "old setup"})
	os.WriteFile(filepath.Join(root, SetupExe), []byte("the setup"), 0o644)
	os.WriteFile(filepath.Join(root, "my notes.txt"), []byte("mine"), 0o644)
	staging := filepath.Join(root, Staging)
	p, _ := FindPayload(makePayload(t, filepath.Join(dir, "new.zip"), "0.11.0", "sluka-desktop/", map[string]string{"tools/new.txt": "new"}))
	if _, err := p.Extract(staging, nil); err != nil {
		t.Fatal(err)
	}
	before := tree(t, root)
	// Where a file is in use: everything as it was.
	for fail := 1; fail <= 7; fail++ {
		n := 0
		rename = func(a, b string) error {
			n++
			if n == fail {
				return errors.New("in use")
			}
			return os.Rename(a, b)
		}
		if err := PutInPlace(staging, root); err == nil {
			t.Fatalf("failure %d: no error", fail)
		}
		rename = os.Rename
		if got := tree(t, root); !equalTrees(got, before) {
			t.Fatalf("failure %d: the folder changed:\n%v", fail, diffTrees(before, got))
		}
	}
	if err := PutInPlace(staging, root); err != nil {
		t.Fatal(err)
	}
	after := tree(t, root)
	if (Install{root}).Version() != "0.11.0" || after["tools/new.txt"] != "new" {
		t.Errorf("not put in place: %v", after)
	}
	for _, gone := range []string{"app/gone.py", "Sluka Setup.cmd"} {
		if _, ok := after[gone]; ok {
			t.Errorf("%s is left", gone)
		}
	}
	for _, kept := range []string{"data/storage.sqlite", "extension/manifest.json", "config.ini", "my notes.txt", SetupExe} {
		if after[kept] != before[kept] {
			t.Errorf("%s changed", kept)
		}
	}
	if exists(filepath.Join(root, OldDir)) || FolderHasThings(staging) {
		t.Error("scratch folders left")
	}
}

func equalTrees(a, b map[string]string) bool {
	if len(a) != len(b) {
		return false
	}
	for k, v := range a {
		if b[k] != v {
			return false
		}
	}
	return true
}

func diffTrees(a, b map[string]string) string {
	var out []string
	for k := range a {
		if b[k] != a[k] {
			out = append(out, "- "+k)
		}
	}
	for k := range b {
		if _, ok := a[k]; !ok {
			out = append(out, "+ "+k)
		}
	}
	sort.Strings(out)
	return strings.Join(out, "\n")
}

func TestExtensions(t *testing.T) {
	dir := t.TempDir()
	ext, err := ExtensionIn(makeExtension(t, filepath.Join(dir, "a.zip"), "0.7.4", true))
	if err != nil || ext.Version != "0.7.4" || ext.Name != "Sluka" || !ext.Sluka {
		t.Errorf("%+v %v", ext, err)
	}
	ext, _ = ExtensionIn(makeExtension(t, filepath.Join(dir, "b.zip"), "0.7.5", false))
	if ext.Sluka {
		t.Error("no background worker, yet taken for the Chrome edition")
	}
	writeZip(t, filepath.Join(dir, "c.zip"), map[string]string{"manifest.json": `{"name": "__MSG_name__", "version": "1.2"}`}, nil)
	if ext, _ := ExtensionIn(filepath.Join(dir, "c.zip")); ext.Name != "" || ext.Version != "1.2" {
		t.Errorf("%+v", ext)
	}
	os.MkdirAll(filepath.Join(dir, "folder", "inner"), 0o755)
	os.WriteFile(filepath.Join(dir, "folder", "inner", "manifest.json"), []byte(`{"version": "2.0", "manifest_version": 3, "background": {}}`), 0o644)
	if ext, err := ExtensionIn(filepath.Join(dir, "folder")); err != nil || ext.Version != "2.0" {
		t.Errorf("%+v %v", ext, err)
	}
	writeZip(t, filepath.Join(dir, "d.zip"), map[string]string{"photo.jpg": "x"}, nil)
	if _, err := Describe(filepath.Join(dir, "d.zip")); err == nil {
		t.Error("a holiday's photos taken for Sluka")
	}
}

func TestFindingZips(t *testing.T) {
	dir := t.TempDir()
	old := makeExtension(t, filepath.Join(dir, "sluka-extension-0_7_4.zip"), "0.7.4", true)
	newer := makeExtension(t, filepath.Join(dir, "Sluka-Extension-0_7_6.zip"), "0.7.6", true)
	app := makePayload(t, filepath.Join(dir, "sluka-desktop-0.12.0-windows.zip"), "0.12.0", "sluka-desktop/", nil)
	makeExtension(t, filepath.Join(dir, "other-extension.zip"), "9.0", true)
	writeZip(t, filepath.Join(dir, "sluka-photos.zip"), map[string]string{"photo.jpg": "x"}, nil)
	now := time.Now()
	os.Chtimes(old, now, now.Add(-3*time.Hour))
	os.Chtimes(newer, now, now.Add(-2*time.Hour))
	os.Chtimes(app, now, now.Add(-1*time.Hour))
	found := FindZips([]string{dir, dir}, "", "desktop", "extension")
	var names []string
	for _, f := range found {
		names = append(names, filepath.Base(f.Path)+" "+f.Kind+" "+f.Version)
	}
	want := "sluka-desktop-0.12.0-windows.zip desktop 0.12.0|Sluka-Extension-0_7_6.zip extension 0.7.6|sluka-extension-0_7_4.zip extension 0.7.4"
	if strings.Join(names, "|") != want {
		t.Errorf("%v", names)
	}
	if best := NewestExtension([]string{dir}); best.Path != newer {
		t.Errorf("%+v", best)
	}
	if len(FindZips([]string{dir}, app, "desktop")) != 0 {
		t.Error("the setup's own file offered to itself")
	}
}

func TestShortcutsKnown(t *testing.T) {
	root := `C:\Users\Ana\AppData\Local\Programs\Sluka Desktop`
	data := utf16le("L\x00\x00junk" + `pythonw.exe` + "\x00" + `-I "` + root + `\app\run.py"` + "\x00" + root)
	if !LinkLeadsTo(data, root, `\`) || !LinkLeadsTo(data, strings.ToUpper(root), `\`) {
		t.Error("its own folder not seen")
	}
	if LinkLeadsTo(data, `C:\Users\Ana\AppData\Local\Programs\Sluka`, `\`) || LinkLeadsTo(data, root+" 2", `\`) {
		t.Error("another folder taken for it")
	}
	if got := LinkRoots(append([]byte{0}, data...)); len(got) == 0 || got[0] != root {
		t.Errorf("%v", got)
	}
	old := utf16le(`C:\sluka-desktop\Sluka.cmd`)
	if got := LinkRoots(old); len(got) != 1 || got[0] != `C:\sluka-desktop` {
		t.Errorf("%v", got)
	}
}

func TestConfigPort(t *testing.T) {
	dir := t.TempDir()
	for text, want := range map[string]int{
		"[app]\nport = 47999\n":                     47999,
		"\ufeff[App]\r\nPort=48000\r\n":             48000,
		"[browser]\nport = 47900\n":                 47900,
		"[app]\n; port = 1\nshell = auto\n":         DefaultPort,
		"[mpv]\nport = 5000\n[app]\nport = 80\n":    DefaultPort,
		"[app]\nport = 47999 \n[browser]\nport=1\n": 47999,
	} {
		os.WriteFile(filepath.Join(dir, "config.ini"), []byte(text), 0o644)
		if got := (Install{dir}).Port(); got != want {
			t.Errorf("%q: %d, want %d", text, got, want)
		}
	}
}

// ------------------------------------------------------------------------------------------------ the work

func TestInstall(t *testing.T) {
	f := newFake(t)
	f.anki = true
	payload := makePayload(t, filepath.Join(f.base, "Downloads", "Sluka-Desktop-Setup-0.11.0.exe"), "0.11.0", "payload/sluka-desktop/", nil)
	ext := makeExtension(t, filepath.Join(f.base, "Downloads", "sluka-extension-0_7_4.zip"), "0.7.4", true)
	s := setupFor(t, f, payload)
	s.Self = payload
	if got := s.FolderProblem(filepath.Join(f.base, "Program Files", "Sluka")); !strings.Contains(got, "Not under") {
		t.Errorf("Program Files: %q", got)
	}
	if got := s.FolderProblem("relative"); !strings.Contains(got, "whole path") {
		t.Errorf("relative: %q", got)
	}
	target := InstallIn(f.DefaultFolder())
	if got := s.FolderProblem(target.Root); got != "" || exists(target.Root) {
		t.Errorf("the usual folder: %q (made: %v)", got, exists(target.Root))
	}
	if best := NewestExtension([]string{f.Downloads()}); best.Path != ext {
		t.Errorf("the extension in Downloads not found: %+v", best)
	}
	r := &quietReporter{}
	res, err := s.Install(target, Choices{Desktop: true, StartMenu: false, Anki: true, Extension: ext}, r)
	if err != nil {
		t.Fatal(err, r.lines)
	}
	if target.Version() != "0.11.0" || target.ExtensionVersion() != "0.7.4" || !res.CanStart {
		t.Errorf("%s %s %v", target.Version(), target.ExtensionVersion(), res)
	}
	calls := fmt.Sprint(f.calls)
	if calls != fmt.Sprintf("[[install-extension %s] [install-menu --no-start-menu] [install-anki]]", ext) {
		t.Errorf("%s", calls)
	}
	if f.Registered() != target.Root || f.reg["DisplayVersion"] != "0.11.0" ||
		f.reg["UninstallString"] != fmt.Sprintf(`"%s" /uninstall`, filepath.Join(target.Root, SetupExe)) ||
		f.reg["DisplayIcon"] != filepath.Join(target.Root, "data", "sluka.ico") {
		t.Errorf("%v", f.reg)
	}
	if !isFile(filepath.Join(f.base, "Desktop", "Sluka.lnk")) || exists(filepath.Join(f.base, "Start Menu", "Sluka.lnk")) ||
		exists(filepath.Join(f.base, "Start Menu", SetupLink)) {
		t.Error("the shortcuts are not as chosen")
	}
	if strings.Join(res.Lines, "|") != fmt.Sprintf("Sluka Desktop 0.11.0 is in %s.|The Sluka extension 0.7.4 is in it.|"+
		"Sluka is on the desktop.|Sluka's add-on is in Anki: restart Anki.", target.Root) || len(res.Warnings) != 0 {
		t.Errorf("%q %q", res.Lines, res.Warnings)
	}
	// The setup is beside the app (here no Windows program: what it could not, it says).
	if !strings.Contains(strings.Join(r.lines, "\n"), "the setup could not be put beside it") {
		t.Errorf("%v", r.lines)
	}
	if got := s.Candidates(); len(got) == 0 || !got[0].Same(target) {
		t.Errorf("not found again: %v", got)
	}
}

func TestInstallWithoutExtensionOrPython(t *testing.T) {
	f := newFake(t)
	payload := makePayload(t, filepath.Join(f.base, "Downloads", "setup.exe"), "0.11.0", "payload/sluka-desktop/", nil)
	s := setupFor(t, f, payload)
	target := Install{filepath.Join(f.base, "Games", AppName)}
	res, err := s.Install(target, Choices{Desktop: true, StartMenu: true}, &quietReporter{})
	if err != nil {
		t.Fatal(err)
	}
	if res.CanStart || len(res.Warnings) != 1 || !strings.Contains(res.Warnings[0], "no Sluka extension yet") {
		t.Errorf("%v", res)
	}
	if !isFile(filepath.Join(f.base, "Start Menu", SetupLink)) || !isFile(filepath.Join(f.base, "Start Menu", "Sluka.lnk")) {
		t.Error("no setup in the Start menu")
	}
	// Without Python nothing of the app's can be run: said.
	s.Python = nil
	res, _ = s.Shortcuts(target, false, false, &quietReporter{})
	if len(res.Warnings) == 0 || !strings.Contains(res.Warnings[0], "Python") {
		t.Errorf("%v", res)
	}
}

func TestUpdateKeepsYourThings(t *testing.T) {
	f := newFake(t)
	root := filepath.Join(f.base, "Downloads", "sluka-desktop")
	old := unpacked(t, root, "0.10.0", "0.7.4", map[string]string{"Sluka Setup.cmd": "0.10.0's setup", "app/sluka_setup.py": "#"})
	os.WriteFile(filepath.Join(f.base, "Start Menu", "Sluka.lnk"), link(root), 0o644)
	os.WriteFile(filepath.Join(root, "my notes.txt"), []byte("mine"), 0o644)
	before := tree(t, root)
	payload := makePayload(t, filepath.Join(f.base, "Downloads", "setup.exe"), "0.11.0", "payload/sluka-desktop/", nil)
	s := setupFor(t, f, payload)
	// The folder it was unpacked into (or the one that holds it) leads to it.
	if got := InstallIn(filepath.Join(f.base, "Downloads")); !got.Same(old) {
		t.Errorf("%v", got)
	}
	if got := s.Candidates(); len(got) != 1 || !got[0].Same(old) {
		t.Errorf("found: %v", got)
	}
	res, err := s.Update(s.Payload, old, &quietReporter{}, "")
	if err != nil {
		t.Fatal(err)
	}
	after := tree(t, root)
	for _, kept := range []string{"data/storage.sqlite", "extension/manifest.json", "config.ini", "my notes.txt"} {
		if after[kept] != before[kept] {
			t.Errorf("%s changed", kept)
		}
	}
	for _, gone := range []string{"Sluka Setup.cmd", "app/sluka_setup.py"} {
		if _, ok := after[gone]; ok {
			t.Errorf("%s left", gone)
		}
	}
	if old.Version() != "0.11.0" || !strings.Contains(res.Lines[0], "updated from 0.10.0 to 0.11.0") || f.calls != nil {
		t.Errorf("%v %v", res.Lines, f.calls)
	}
	if !isFile(filepath.Join(f.base, "Start Menu", SetupLink)) || f.Registered() != root {
		t.Error("the setup is not in the Start menu, or the app not in Windows' list")
	}
}

func TestUpdateFromZips(t *testing.T) {
	f := newFake(t)
	cur := unpacked(t, f.DefaultFolder(), "0.11.0", "0.7.4", nil)
	s := setupFor(t, f, "")
	ext := makeExtension(t, filepath.Join(f.base, "Downloads", "sluka-extension-0_7_6.zip"), "0.7.6", true)
	res, err := s.UpdateFromZip(ext, cur, &quietReporter{})
	if err != nil || cur.ExtensionVersion() != "0.7.6" || res.Lines[0] != "The Sluka extension is updated from 0.7.4 to 0.7.6." {
		t.Errorf("%v %v", res.Lines, err)
	}
	firefox := makeExtension(t, filepath.Join(f.base, "Downloads", "other.zip"), "1.0", false)
	if _, err := s.UpdateFromZip(firefox, cur, &quietReporter{}); err == nil || cur.ExtensionVersion() != "0.7.6" {
		t.Errorf("a wrong extension put in: %v", err)
	}
	app := makePayload(t, filepath.Join(f.base, "Downloads", "sluka-desktop-0.12.0-windows.zip"), "0.12.0", "sluka-desktop/", nil)
	if res, err := s.UpdateFromZip(app, cur, &quietReporter{}); err != nil || cur.Version() != "0.12.0" || !res.CanStart {
		t.Errorf("%v %v", res, err)
	}
	photos := writeZip(t, filepath.Join(f.base, "photos.zip"), map[string]string{"photo.jpg": "x"}, nil)
	if _, err := s.UpdateFromZip(photos, cur, &quietReporter{}); err == nil || !strings.Contains(err.Error(), "neither") {
		t.Errorf("%v", err)
	}
	f.windows = true
	tails := makePayload(t, filepath.Join(f.base, "tails.zip"), "0.13.0", "sluka-desktop/", nil, "Sluka.cmd")
	if _, err := s.UpdateFromZip(tails, cur, &quietReporter{}); err == nil || !strings.Contains(err.Error(), "Linux") || cur.Version() != "0.12.0" {
		t.Errorf("%v", err)
	}
}

func TestShortcutsChanged(t *testing.T) {
	f := newFake(t)
	cur := unpacked(t, f.DefaultFolder(), "0.11.0", "0.7.4", nil)
	s := setupFor(t, f, "")
	s.Shortcuts(cur, true, true, &quietReporter{})
	if d, m := s.HasLinks(cur); !d || !m || !isFile(filepath.Join(f.base, "Start Menu", SetupLink)) {
		t.Error("not made")
	}
	res, _ := s.Shortcuts(cur, false, true, &quietReporter{})
	if d, m := s.HasLinks(cur); d || !m || res.Lines[0] != "Sluka is in the Start menu." {
		t.Errorf("%v", res.Lines)
	}
	// Another copy's shortcut is left alone.
	os.WriteFile(filepath.Join(f.base, "Desktop", "Sluka.lnk"), link(filepath.Join(f.base, "other")), 0o644)
	s.Shortcuts(cur, false, false, &quietReporter{})
	if !isFile(filepath.Join(f.base, "Desktop", "Sluka.lnk")) || exists(filepath.Join(f.base, "Start Menu", "Sluka.lnk")) ||
		exists(filepath.Join(f.base, "Start Menu", SetupLink)) {
		t.Error("wrong shortcuts taken away")
	}
}

func TestUninstall(t *testing.T) {
	f := newFake(t)
	cur := unpacked(t, f.DefaultFolder(), "0.11.0", "0.7.4", nil)
	s := setupFor(t, f, "")
	s.Shortcuts(cur, true, true, &quietReporter{})
	f.Register(cur, 1)
	os.WriteFile(filepath.Join(cur.Root, SetupExe), []byte("setup"), 0o644)
	os.MkdirAll(f.LocalFolder(), 0o755)
	res, err := s.Uninstall(cur, true, &quietReporter{})
	if err != nil {
		t.Fatal(err)
	}
	got := tree(t, cur.Root)
	for name := range got {
		if name != "config.ini" && !strings.HasPrefix(name, "data/") {
			t.Errorf("%s left", name)
		}
	}
	if got["config.ini"] == "" || got["data/storage.sqlite"] != "your words" {
		t.Errorf("%v", got)
	}
	if f.reg != nil || exists(filepath.Join(f.base, "Desktop", "Sluka.lnk")) || exists(filepath.Join(f.base, "Start Menu", SetupLink)) {
		t.Error("left in Windows")
	}
	if !strings.Contains(res.Lines[0], "Your words, books and settings stay") || !isDir(f.LocalFolder()) {
		t.Errorf("%v", res.Lines)
	}
	// Everything, and an older app's (no remove-from-pc): its shortcuts by the setup itself.
	cur = unpacked(t, f.DefaultFolder(), "0.9.0", "0.7.4", nil)
	os.WriteFile(filepath.Join(f.base, "Desktop", "Sluka.lnk"), link(cur.Root), 0o644)
	f.calls = nil
	if _, err := s.Uninstall(cur, false, &quietReporter{}); err != nil {
		t.Fatal(err)
	}
	if exists(cur.Root) || exists(filepath.Join(f.base, "Desktop", "Sluka.lnk")) || f.calls != nil || exists(f.LocalFolder()) {
		t.Errorf("left: %v %v", tree(t, cur.Root), f.calls)
	}
}

func TestUninstallWhatIsInUse(t *testing.T) {
	f := newFake(t)
	cur := unpacked(t, f.DefaultFolder(), "0.11.0", "0.7.4", nil)
	s := setupFor(t, f, "")
	engine := filepath.Join(cur.Root, "engine")
	os.Chmod(engine, 0o500) // (its files cannot be taken away)
	defer os.Chmod(engine, 0o755)
	if os.Getuid() == 0 {
		t.Skip("root may take away anything")
	}
	s.Uninstall(cur, false, &quietReporter{})
	if len(f.later) != 1 || f.later[0] != cur.Root {
		t.Errorf("%v", f.later)
	}
}

func TestTheAppRunning(t *testing.T) {
	root := t.TempDir()
	ln, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Skip(err)
	}
	defer ln.Close()
	port := ln.Addr().(*net.TCPAddr).Port
	os.WriteFile(filepath.Join(root, "config.ini"), []byte(fmt.Sprintf("[app]\nport = %d\n", port)), 0o644)
	body := fmt.Sprintf(`{"app": {"name": "Sluka Desktop", "version": "0.11.0"}, "data": %q, "extension": {"folder": %q}}`,
		filepath.Join(root, "data"), filepath.Join(root, "extension"))
	go func() {
		for {
			c, err := ln.Accept()
			if err != nil {
				return
			}
			buf := make([]byte, 4096)
			n, _ := c.Read(buf)
			if strings.HasPrefix(string(buf[:n]), "GET /__sluka__/api/info ") {
				fmt.Fprintf(c, "HTTP/1.0 200 OK\r\nContent-Type: application/json\r\n\r\n%s", body)
			} else {
				fmt.Fprint(c, "HTTP/1.0 404 Not Found\r\n\r\n")
			}
			c.Close()
		}
	}()
	if !Running(Install{root}) {
		t.Error("the app running here not seen")
	}
	if Running(Install{t.TempDir()}) {
		t.Error("another copy taken for this one")
	}
}

func TestZoom(t *testing.T) {
	// The window at 100 %: 560 by 420 inside, with a frame of 16 by 39 pixels round it.
	outer := func(scale float64) (int, int) {
		return int(560*scale+0.5) + 16, int(420*scale+0.5) + 39
	}
	for _, c := range []struct {
		dpi, workW, workH int
		want              float64
	}{
		{96, 1920, 1040, 1.25},  // full HD at 100 %: a quarter larger
		{144, 1920, 1040, 1.25}, // at 150 %: 1066 by 826, fits
		{192, 1920, 1040, 1.15}, // at 200 %: a quarter larger would not fit; the most that does
		{240, 1280, 680, 1},     // far too small: Windows' own size, never less
		{96, 0, 0, 1.25},        // the work area not known
	} {
		got := FitZoom(c.dpi, c.workW, c.workH, outer)
		if diff := got - c.want; diff > 0.001 || diff < -0.001 {
			t.Errorf("FitZoom(%d, %d, %d) = %.2f, want %.2f", c.dpi, c.workW, c.workH, got, c.want)
		}
		if w, h := outer(float64(c.dpi) / 96 * got); got > 1 && c.workW > 0 && (w > c.workW || h > c.workH) {
			t.Errorf("at %d dpi the window (%d by %d) does not fit in %d by %d", c.dpi, w, h, c.workW, c.workH)
		}
	}
}
