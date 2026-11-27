// SPDX-License-Identifier: LicenseRef-Sluka
// Copyright (c) 2026 Sluka. Part of Sluka Desktop Setup; see LICENSE.txt.
//go:build !windows

package main

// Elsewhere than Windows: the setup's work without its window, for the tests (and to try it), with the places
// Windows has named by the environment.

import (
	"encoding/json"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"syscall"
	"unicode/utf16"
)

type otherPlatform struct{}

func newPlatform() Platform { return otherPlatform{} }

func envOr(name, fallback string) string {
	if v := os.Getenv(name); v != "" {
		return v
	}
	return fallback
}

func home() string {
	h, _ := os.UserHomeDir()
	return h
}

func (otherPlatform) DefaultFolder() string {
	return envOr("SLUKA_SETUP_DEFAULT", filepath.Join(home(), "sluka-desktop"))
}

func (otherPlatform) ProgramFiles() []string {
	if v := os.Getenv("SLUKA_SETUP_PROGRAM_FILES"); v != "" {
		return filepath.SplitList(v)
	}
	return nil
}

func (otherPlatform) ShellFolder(which string) string {
	if which == "desktop" {
		return os.Getenv("SLUKA_SETUP_DESKTOP")
	}
	return os.Getenv("SLUKA_SETUP_PROGRAMS")
}

func (otherPlatform) Downloads() string {
	return envOr("SLUKA_SETUP_DOWNLOADS", filepath.Join(home(), "Downloads"))
}

func (otherPlatform) LocalFolder() string { return os.Getenv("SLUKA_SETUP_LOCAL") }

// Windows' list of apps, as a file.
func stateFile() string { return os.Getenv("SLUKA_SETUP_STATE") }

func (otherPlatform) Registered() string {
	data, err := os.ReadFile(stateFile())
	if err != nil {
		return ""
	}
	var values map[string]any
	if json.Unmarshal(data, &values) != nil {
		return ""
	}
	location, _ := values["InstallLocation"].(string)
	return location
}

func (otherPlatform) Register(i Install, size int64) error {
	if stateFile() == "" {
		return nil
	}
	values := registryValues(i, size)
	data, _ := json.MarshalIndent(values, "", "  ")
	return os.WriteFile(stateFile(), data, 0o644)
}

func (p otherPlatform) Unregister(i Install) {
	if known := p.Registered(); known == "" || SamePath(known, i.Root) {
		os.Remove(stateFile())
	}
}

func (otherPlatform) AnkiHere() bool {
	if v := os.Getenv("SLUKA_SETUP_ANKI"); v != "" {
		return v == "1"
	}
	return isDir(filepath.Join(home(), ".local", "share", "Anki2"))
}

func (otherPlatform) FindPython() (*Python, error) {
	exe := envOr("SLUKA_SETUP_PYTHON", "python3")
	if found, err := exec.LookPath(exe); err == nil {
		exe = found
	} else {
		return nil, ErrNoPython
	}
	out, err := exec.Command(exe, "-I", "-c", probeScript).Output()
	if err != nil {
		return nil, ErrNoPython
	}
	return parseProbe(string(out))
}

func (otherPlatform) RunApp(py *Python, i Install, each func(string), args ...string) (int, error) {
	cmd := exec.Command(py.Exe, append([]string{"-I", filepath.Join(i.Root, "app", "run.py")}, args...)...)
	cmd.Dir = i.Root
	cmd.Env = append(os.Environ(), "SLUKA_OUTPUT=utf-8")
	return runLines(cmd, each)
}

// MakeSetupLink: a stand-in for Windows' shortcut, holding (in UTF-16, as Windows writes them) the setup's path.
func (otherPlatform) MakeSetupLink(i Install, link string) error {
	text := "L\x00" + filepath.Join(i.Root, SetupExe) + "\x00" + i.Root
	units := utf16.Encode([]rune(text))
	data := make([]byte, 0, 2*len(units))
	for _, u := range units {
		data = append(data, byte(u), byte(u>>8))
	}
	return os.WriteFile(link, data, 0o644)
}

func (otherPlatform) RemoveLater(path string) {
	if f := os.Getenv("SLUKA_SETUP_LATER"); f != "" {
		out, err := os.OpenFile(f, os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0o644)
		if err == nil {
			fmt.Fprintln(out, path)
			out.Close()
		}
	}
}

func (otherPlatform) Launch(py *Python, i Install, links []string) error {
	if f := os.Getenv("SLUKA_SETUP_LAUNCHED"); f != "" {
		return os.WriteFile(f, []byte(strings.Join(append([]string{i.Root}, links...), "\n")), 0o644)
	}
	return nil
}

func (otherPlatform) Separator() string { return "/" }

func freeSpace(path string) (int64, bool) {
	for !exists(path) && filepath.Dir(path) != path {
		path = filepath.Dir(path)
	}
	var st syscall.Statfs_t
	if syscall.Statfs(path, &st) != nil {
		return 0, false
	}
	return int64(st.Bavail) * int64(st.Bsize), true
}

var _ = strconv.Itoa
