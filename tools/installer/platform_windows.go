// SPDX-License-Identifier: LicenseRef-Sluka
// Copyright (c) 2026 Sluka. Part of Sluka Desktop Setup; see LICENSE.txt.
package main

// Windows: its folders, its list of apps (the registry), Python, the app's commands, shortcuts.

import (
	"context"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"sort"
	"strings"
	"syscall"
	"time"
	"unsafe"
)

const (
	uninstallKey = `Software\Microsoft\Windows\CurrentVersion\Uninstall\SlukaDesktop`
	appKey       = `Software\Sluka Desktop`
	downloadsID  = "{374DE290-123F-4565-9164-39C4925E467B}"
	regExpandSZ  = 2
	keyWow64_64  = 0x0100
	keyWow64_32  = 0x0200
)

type winPlatform struct{}

func newPlatform() Platform { return winPlatform{} }

func hidden() *syscall.SysProcAttr {
	return &syscall.SysProcAttr{HideWindow: true, CreationFlags: CREATE_NO_WINDOW}
}

func (winPlatform) DefaultFolder() string {
	base := os.Getenv("LOCALAPPDATA")
	if base == "" {
		base = filepath.Join(os.Getenv("USERPROFILE"), "AppData", "Local")
	}
	return filepath.Join(base, "Programs", AppName)
}

func (winPlatform) ProgramFiles() []string {
	var out []string
	for _, name := range []string{"ProgramFiles", "ProgramFiles(x86)", "ProgramW6432"} {
		if v := os.Getenv(name); v != "" {
			out = append(out, v)
		}
	}
	return out
}

func shellFolder(csidl int) string {
	buf := make([]uint16, 261)
	r, _, _ := pSHGetFolderPathW.Call(0, uintptr(csidl), 0, 0, uintptr(unsafe.Pointer(&buf[0])))
	if r != 0 {
		return ""
	}
	return syscall.UTF16ToString(buf)
}

func (winPlatform) ShellFolder(which string) string {
	if which == "desktop" {
		return shellFolder(CSIDL_DESKTOPDIRECTORY)
	}
	return shellFolder(CSIDL_PROGRAMS)
}

func expandEnv(text string) string {
	buf := make([]uint16, 32768)
	n, _, _ := pExpandEnvStrings.Call(uintptr(unsafe.Pointer(wstr(text))), uintptr(unsafe.Pointer(&buf[0])), uintptr(len(buf)))
	if n == 0 || int(n) > len(buf) {
		return text
	}
	return syscall.UTF16ToString(buf)
}

func (winPlatform) Downloads() string {
	if v := regString(syscall.HKEY_CURRENT_USER, `Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders`, downloadsID, 0); v != "" {
		if folder := expandEnv(v); isDir(folder) {
			return folder
		}
	}
	return filepath.Join(os.Getenv("USERPROFILE"), "Downloads")
}

func (winPlatform) LocalFolder() string {
	if base := os.Getenv("LOCALAPPDATA"); base != "" {
		return filepath.Join(base, "sluka-desktop")
	}
	return ""
}

// ------------------------------------------------------------------------------------------------ the registry

func regString(root syscall.Handle, path, name string, view uint32) string {
	var key syscall.Handle
	p, err := syscall.UTF16PtrFromString(path)
	if err != nil || syscall.RegOpenKeyEx(root, p, 0, syscall.KEY_READ|view, &key) != nil {
		return ""
	}
	defer syscall.RegCloseKey(key)
	n, err := syscall.UTF16PtrFromString(name)
	if err != nil {
		return ""
	}
	var typ, size uint32
	if syscall.RegQueryValueEx(key, n, nil, &typ, nil, &size) != nil || size < 2 || size > 1<<20 {
		return ""
	}
	if typ != syscall.REG_SZ && typ != regExpandSZ {
		return ""
	}
	buf := make([]uint16, size/2+1)
	if syscall.RegQueryValueEx(key, n, nil, &typ, (*byte)(unsafe.Pointer(&buf[0])), &size) != nil {
		return ""
	}
	return syscall.UTF16ToString(buf)
}

func regSubkeys(root syscall.Handle, path string, view uint32) []string {
	var key syscall.Handle
	p, err := syscall.UTF16PtrFromString(path)
	if err != nil || syscall.RegOpenKeyEx(root, p, 0, syscall.KEY_READ|view, &key) != nil {
		return nil
	}
	defer syscall.RegCloseKey(key)
	var out []string
	for i := uint32(0); i < 1000; i++ {
		buf := make([]uint16, 256)
		size := uint32(len(buf))
		if syscall.RegEnumKeyEx(key, i, &buf[0], &size, nil, nil, nil, nil) != nil {
			break
		}
		out = append(out, syscall.UTF16ToString(buf[:size]))
	}
	return out
}

func regCreate(path string) (syscall.Handle, error) {
	var key syscall.Handle
	var disposition uint32
	r, _, _ := pRegCreateKeyExW.Call(uintptr(HKEY_CURRENT_USER), uintptr(unsafe.Pointer(wstr(path))), 0, 0, 0, KEY_WRITE, 0,
		uintptr(unsafe.Pointer(&key)), uintptr(unsafe.Pointer(&disposition)))
	if r != ERROR_SUCCESS {
		return 0, syscall.Errno(r)
	}
	return key, nil
}

func regSet(key syscall.Handle, name string, value any) error {
	var r uintptr
	switch v := value.(type) {
	case string:
		data, _ := syscall.UTF16FromString(v)
		r, _, _ = pRegSetValueExW.Call(uintptr(key), uintptr(unsafe.Pointer(wstr(name))), 0, REG_SZ,
			uintptr(unsafe.Pointer(&data[0])), uintptr(len(data)*2))
	case uint32:
		r, _, _ = pRegSetValueExW.Call(uintptr(key), uintptr(unsafe.Pointer(wstr(name))), 0, REG_DWORD,
			uintptr(unsafe.Pointer(&v)), 4)
	default:
		return fmt.Errorf("no such value: %T", value)
	}
	if r != ERROR_SUCCESS {
		return syscall.Errno(r)
	}
	return nil
}

func (winPlatform) Registered() string {
	return regString(syscall.HKEY_CURRENT_USER, appKey, "InstallLocation", 0)
}

func (winPlatform) Register(i Install, size int64) error {
	key, err := regCreate(uninstallKey)
	if err != nil {
		return err
	}
	values := registryValues(i, size)
	names := make([]string, 0, len(values))
	for name := range values {
		names = append(names, name)
	}
	sort.Strings(names)
	for _, name := range names {
		if err := regSet(key, name, values[name]); err != nil {
			syscall.RegCloseKey(key)
			return err
		}
	}
	syscall.RegCloseKey(key)
	key, err = regCreate(appKey)
	if err != nil {
		return err
	}
	defer syscall.RegCloseKey(key)
	regSet(key, "InstallLocation", i.Root)
	return regSet(key, "Version", i.Version())
}

func (p winPlatform) Unregister(i Install) {
	if known := p.Registered(); known != "" && !SamePath(known, i.Root) {
		return // (the one in Windows' list is another copy)
	}
	for _, path := range []string{uninstallKey, appKey} {
		pRegDeleteKeyW.Call(uintptr(HKEY_CURRENT_USER), uintptr(unsafe.Pointer(wstr(path))))
	}
}

func (winPlatform) AnkiHere() bool {
	base := os.Getenv("APPDATA")
	return base != "" && isDir(filepath.Join(base, "Anki2"))
}

// ------------------------------------------------------------------------------------------------ Python

func outputWithin(cmd *exec.Cmd, limit time.Duration) ([]byte, error) {
	ctx, cancel := context.WithTimeout(context.Background(), limit)
	defer cancel()
	run := exec.CommandContext(ctx, cmd.Path, cmd.Args[1:]...)
	run.SysProcAttr = cmd.SysProcAttr
	run.Dir = cmd.Dir
	return run.Output()
}

func probePython(exe string, before ...string) *Python {
	args := append(append([]string{}, before...), "-I", "-c", probeScript)
	cmd := exec.Command(exe, args...)
	cmd.SysProcAttr = hidden()
	out, err := outputWithin(cmd, 30*time.Second)
	if err != nil {
		return nil
	}
	py, err := parseProbe(string(out))
	if err != nil {
		return nil
	}
	return py
}

// registeredPythons: the Pythons Windows' registry lists (python.org's installers write themselves there), the
// newest first.
func registeredPythons() []string {
	type entry struct {
		version []int
		exe     string
	}
	var found []entry
	for _, root := range []syscall.Handle{syscall.HKEY_CURRENT_USER, syscall.HKEY_LOCAL_MACHINE} {
		for _, view := range []uint32{keyWow64_64, keyWow64_32} {
			base := `Software\Python\PythonCore`
			for _, tag := range regSubkeys(root, base, view) {
				exe := regString(root, base+`\`+tag+`\InstallPath`, "ExecutablePath", view)
				if exe == "" {
					if folder := regString(root, base+`\`+tag+`\InstallPath`, "", view); folder != "" {
						exe = filepath.Join(folder, "python.exe")
					}
				}
				if exe != "" && isFile(exe) {
					found = append(found, entry{VersionTuple(tag), exe})
				}
			}
		}
	}
	sort.SliceStable(found, func(i, j int) bool {
		a, b := found[i].version, found[j].version
		for k := 0; k < len(a) && k < len(b); k++ {
			if a[k] != b[k] {
				return a[k] > b[k]
			}
		}
		return len(a) > len(b)
	})
	var out []string
	for _, f := range found {
		out = append(out, f.exe)
	}
	return out
}

// FindPython: the Python that Sluka.cmd would take (the py launcher's "py -3" first), else one Windows lists, else
// one on the PATH -- never the Microsoft Store's stand-in, which opens the Store.
func (winPlatform) FindPython() (*Python, error) {
	var launchers []string
	if py, err := exec.LookPath("py.exe"); err == nil {
		launchers = append(launchers, py)
	}
	launchers = append(launchers, filepath.Join(os.Getenv("WINDIR"), "py.exe"),
		filepath.Join(os.Getenv("LOCALAPPDATA"), "Programs", "Python", "Launcher", "py.exe"))
	seen := map[string]bool{}
	for _, py := range launchers {
		if py == "" || seen[strings.ToLower(py)] || !isFile(py) {
			continue
		}
		seen[strings.ToLower(py)] = true
		if p := probePython(py, "-3"); p != nil {
			return p, nil
		}
	}
	for _, exe := range registeredPythons() {
		if p := probePython(exe); p != nil {
			return p, nil
		}
	}
	for _, name := range []string{"python.exe", "python3.exe"} {
		if exe, err := exec.LookPath(name); err == nil && !strings.Contains(strings.ToLower(exe), `\windowsapps\`) {
			if p := probePython(exe); p != nil {
				return p, nil
			}
		}
	}
	return nil, ErrNoPython
}

// ------------------------------------------------------------------------------------------------ the app

func (winPlatform) RunApp(py *Python, i Install, each func(string), args ...string) (int, error) {
	cmd := exec.Command(py.Exe, append([]string{"-I", filepath.Join(i.Root, "app", "run.py")}, args...)...)
	cmd.Dir = i.Root
	cmd.Env = append(os.Environ(), "SLUKA_OUTPUT=utf-8")
	cmd.SysProcAttr = hidden()
	return runLines(cmd, each)
}

func psQuote(text string) string { return "'" + strings.ReplaceAll(text, "'", "''") + "'" }

// MakeSetupLink: the setup's shortcut, made by Windows' own script host (as the app makes its own).
func (winPlatform) MakeSetupLink(i Install, link string) error {
	script := "$s = (New-Object -ComObject WScript.Shell).CreateShortcut(" + psQuote(link) + "); " +
		"$s.TargetPath = " + psQuote(filepath.Join(i.Root, SetupExe)) + "; " +
		"$s.WorkingDirectory = " + psQuote(i.Root) + "; " +
		"$s.Description = 'Update Sluka Desktop from a zip, change its shortcuts, or uninstall it'; $s.Save()"
	cmd := exec.Command("powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", script)
	cmd.SysProcAttr = hidden()
	out, err := outputWithin(cmd, 60*time.Second)
	if err != nil && !isFile(link) {
		return fmt.Errorf("%v %s", err, strings.TrimSpace(string(out)))
	}
	return nil
}

// RemoveLater: a file or folder in use (by this program, say), taken away once it is not: tried again every few
// seconds for two minutes, by a program of its own with no window.
func (winPlatform) RemoveLater(path string) {
	if strings.ContainsAny(path, `"%`) {
		return
	}
	remove := `del /f /q "` + path + `"`
	if isDir(path) {
		remove = `rmdir /s /q "` + path + `"`
	}
	inner := `for /l %i in (1,1,40) do @if exist "` + path + `" (ping -n 4 127.0.0.1 >nul & ` + remove + ` >nul 2>nul)`
	comspec := os.Getenv("ComSpec")
	if comspec == "" {
		comspec = filepath.Join(os.Getenv("WINDIR"), "System32", "cmd.exe")
	}
	cmd := exec.Command(comspec)
	cmd.Dir = os.TempDir()
	cmd.SysProcAttr = &syscall.SysProcAttr{CmdLine: `cmd /d /c "` + inner + `"`, HideWindow: true,
		CreationFlags: CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP}
	cmd.Start()
}

// Launch: the app started as a click on its shortcut starts it (the shortcut itself, where there is one).
func (winPlatform) Launch(py *Python, i Install, links []string) error {
	for _, link := range links {
		if isFile(link) {
			r, _, _ := pShellExecuteW.Call(0, uintptr(unsafe.Pointer(wstr("open"))), uintptr(unsafe.Pointer(wstr(link))), 0,
				uintptr(unsafe.Pointer(wstr(i.Root))), SW_SHOWNORMAL)
			if r > 32 {
				return nil
			}
		}
	}
	if py == nil {
		return ErrNoPython
	}
	cmd := exec.Command(py.Windowless, "-I", filepath.Join(i.Root, "app", "run.py"))
	cmd.Dir = i.Root
	cmd.SysProcAttr = &syscall.SysProcAttr{CreationFlags: CREATE_NEW_PROCESS_GROUP}
	return cmd.Start()
}

func (winPlatform) Separator() string { return `\` }

func freeSpace(path string) (int64, bool) {
	for !exists(path) && filepath.Dir(path) != path {
		path = filepath.Dir(path)
	}
	var free, total, all uint64
	r, _, _ := pGetDiskFreeSpaceEx.Call(uintptr(unsafe.Pointer(wstr(path))), uintptr(unsafe.Pointer(&free)),
		uintptr(unsafe.Pointer(&total)), uintptr(unsafe.Pointer(&all)))
	if r == 0 {
		return 0, false
	}
	return int64(free), true
}
