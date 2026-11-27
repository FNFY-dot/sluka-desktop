// SPDX-License-Identifier: LicenseRef-Sluka
// Copyright (c) 2026 Sluka. Part of Sluka Desktop Setup; see LICENSE.txt.
package main

import (
	"fmt"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"time"
)

// What Python says of itself: where it is, its version, 32 or 64 bits.
const probeScript = "import sys, struct; print(sys.executable); print(sys.hexversion); print(struct.calcsize('P') * 8)"

func parseProbe(out string) (*Python, error) {
	lines := strings.Split(strings.ReplaceAll(strings.TrimSpace(out), "\r", ""), "\n")
	if len(lines) < 3 {
		return nil, ErrNoPython
	}
	hex, err := strconv.ParseInt(strings.TrimSpace(lines[1]), 10, 64)
	if err != nil || hex < 0x03090000 {
		return nil, ErrNoPython
	}
	bits, _ := strconv.Atoi(strings.TrimSpace(lines[2]))
	exe := strings.TrimSpace(lines[0])
	py := &Python{Exe: exe, Windowless: exe, Bits: bits,
		Version: fmt.Sprintf("%d.%d.%d", hex>>24, (hex>>16)&0xFF, (hex>>8)&0xFF)}
	for _, name := range []string{"pythonw.exe", "pythonw"} {
		if w := filepath.Join(filepath.Dir(exe), name); isFile(w) && !strings.EqualFold(w, exe) {
			py.Windowless = w
			break
		}
	}
	py.Store = strings.Contains(strings.ToLower(exe), `\windowsapps\`)
	return py, nil
}

// runLines: a program run, what it writes (both streams) going to each, line by line; its exit code.
func runLines(cmd *exec.Cmd, each func(string)) (int, error) {
	out, err := cmd.StdoutPipe()
	if err != nil {
		return -1, err
	}
	cmd.Stderr = cmd.Stdout
	if err := cmd.Start(); err != nil {
		return -1, err
	}
	done := make(chan struct{})
	go func() {
		Lines(out, func(line string) {
			if each != nil {
				each(line)
			}
		})
		close(done)
	}()
	select {
	case <-done:
	case <-time.After(10 * time.Minute):
	}
	err = cmd.Wait()
	if exit, ok := err.(*exec.ExitError); ok {
		return exit.ExitCode(), nil
	}
	if err != nil {
		return -1, err
	}
	return 0, nil
}

// registryValues: what Windows' list of apps says of Sluka Desktop (Settings > Apps).
func registryValues(i Install, size int64) map[string]any {
	setup := filepath.Join(i.Root, SetupExe)
	icon := filepath.Join(i.Root, "data", "sluka.ico")
	if !isFile(icon) {
		icon = setup + ",0"
	}
	return map[string]any{
		"DisplayName":     AppName,
		"DisplayVersion":  i.Version(),
		"Publisher":       "Sluka",
		"InstallLocation": i.Root,
		"InstallDate":     time.Now().Format("20060102"),
		"DisplayIcon":     icon,
		"UninstallString": fmt.Sprintf(`"%s" /uninstall`, setup),
		"ModifyPath":      fmt.Sprintf(`"%s"`, setup),
		"Comments":        "Sluka, the language-learning extension, as a program of its own",
		"EstimatedSize":   uint32(max(1, min(size/1024, 0x7FFFFFFF))),
		"NoRepair":        uint32(1),
	}
}

// Zoom is how much larger than Windows' own size for the screen's scale Setup's window and its text are drawn, for
// reading ease.
const Zoom = 1.25

// FitZoom is the zoom Setup's window is drawn at: Zoom, less (by twentieths) where the window, its frame included
// (outer, in pixels, at a scale), would not fit in the screen's work area -- never less than 1, Windows' own size.  A
// work area of no size (not known) takes Zoom as it is.
func FitZoom(dpi int, workW, workH int, outer func(scale float64) (w, h int)) float64 {
	zoom := Zoom
	for ; zoom > 1; zoom -= 0.05 {
		w, h := outer(float64(dpi) / 96 * zoom)
		if workW <= 0 || workH <= 0 || (w <= workW && h <= workH) {
			return zoom
		}
	}
	return 1
}
