// SPDX-License-Identifier: LicenseRef-Sluka
// Copyright (c) 2026 Sluka. Part of Sluka Desktop's Setup; see LICENSE.txt.

package main

// The setup's work without its window: "--headless COMMAND [options]", saying what it does line by line.  How the
// tests drive it (and a way to see what it would do).

import (
	"flag"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"
)

type lineReporter struct {
	out  io.Writer
	last int64
}

func (r *lineReporter) Status(text string) { fmt.Fprintln(r.out, "status:", text) }
func (r *lineReporter) Log(line string)    { fmt.Fprintln(r.out, "log:", line) }
func (r *lineReporter) Progress(done, total int64) {
	if total <= 0 {
		return
	}
	step := done * 10 / total
	if step != r.last {
		r.last = step
		fmt.Fprintf(r.out, "progress: %d%%\n", step*10)
	}
}

func headless(p Platform, self string, args []string, out io.Writer) int {
	if len(args) == 0 {
		fmt.Fprintln(out, "usage: --headless find|license|install|update|zip|shortcuts|uninstall [options]")
		return 2
	}
	if args[0] == "license" {
		// (the agreement Setup's window shows first, which install, update and zip need accepted)
		fmt.Fprint(out, strings.ReplaceAll(licenseText(), "\r\n", "\n"))
		return 0
	}
	command := args[0]
	fs := flag.NewFlagSet(command, flag.ContinueOnError)
	fs.SetOutput(out)
	folder := fs.String("folder", "", "the app's folder (default: the one found, or the usual one)")
	payloadPath := fs.String("payload", "", "Sluka Desktop's files: a zip or a setup (default: this program's own)")
	noDesktop := fs.Bool("no-desktop", false, "no shortcut on the desktop")
	noMenu := fs.Bool("no-start-menu", false, "none in the Start menu")
	anki := fs.Bool("anki", false, "Sluka's add-on into Anki")
	extension := fs.String("extension", "", "the Sluka extension's zip")
	keep := fs.Bool("keep-data", false, "uninstall: keep the data folder and config.ini")
	accept := fs.Bool("accept-license", false, "install, update, zip: you have read the licence agreement (--headless license) and accept it")
	if err := fs.Parse(args[1:]); err != nil {
		return 2
	}
	switch command {
	case "install", "update", "zip":
		if !*accept {
			fmt.Fprintln(out, "error: read the licence agreement (--headless license), and accept it with --accept-license")
			return 2
		}
	}
	s := &Setup{P: p, Self: self}
	if path := *payloadPath; path != "" {
		payload, err := FindPayload(path)
		if err != nil {
			fmt.Fprintln(out, "error:", path, err)
			return 2
		}
		s.Payload = payload
	} else if payload, err := FindPayload(self); err == nil {
		s.Payload = payload
	}
	if py, err := p.FindPython(); err == nil {
		s.Python = py
	}
	r := &lineReporter{out: out, last: -1}
	var target Install
	if *folder != "" {
		target = InstallIn(*folder)
	} else if found := s.Candidates(); len(found) > 0 {
		target = found[0]
	} else {
		target = Install{p.DefaultFolder()}
	}
	var res Result
	var err error
	switch command {
	case "find":
		if s.Python != nil {
			fmt.Fprintf(out, "python: %s %s (%d-bit)\n", s.Python.Exe, s.Python.Version, s.Python.Bits)
		} else {
			fmt.Fprintln(out, "python: none")
		}
		if s.Payload != nil {
			fmt.Fprintf(out, "payload: %s %s, %d files\n", AppName, s.Payload.Version, s.Payload.Files)
		}
		for _, i := range s.Candidates() {
			fmt.Fprintln(out, "install:", i.Describe())
		}
		return 0
	case "install":
		if problem := s.FolderProblem(target.Root); problem != "" && !target.Exists() {
			fmt.Fprintln(out, "error:", problem)
			return 1
		}
		res, err = s.Install(target, Choices{Desktop: !*noDesktop, StartMenu: !*noMenu, Anki: *anki, Extension: *extension}, r)
	case "update":
		if s.Payload == nil {
			fmt.Fprintln(out, "error: no Sluka Desktop to update to (--payload)")
			return 2
		}
		res, err = s.Update(s.Payload, target, r, "")
	case "zip":
		if fs.NArg() != 1 {
			fmt.Fprintln(out, "error: which zip?")
			return 2
		}
		zip, _ := filepath.Abs(fs.Arg(0))
		res, err = s.UpdateFromZip(zip, target, r)
	case "shortcuts":
		res, err = s.Shortcuts(target, !*noDesktop, !*noMenu, r)
	case "uninstall":
		res, err = s.Uninstall(target, *keep, r)
	default:
		fmt.Fprintln(out, "error: no such command:", command)
		return 2
	}
	for _, line := range res.Lines {
		fmt.Fprintln(out, "done:", line)
	}
	for _, line := range res.Warnings {
		fmt.Fprintln(out, "warning:", line)
	}
	if err != nil {
		fmt.Fprintln(out, "error:", err)
		return 1
	}
	return 0
}

func selfPath() string {
	self, err := os.Executable()
	if err != nil {
		return os.Args[0]
	}
	if resolved, err := filepath.EvalSymlinks(self); err == nil {
		return resolved
	}
	return self
}
