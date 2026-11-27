// SPDX-License-Identifier: LicenseRef-Sluka
// Copyright (c) 2026 Sluka. Part of Sluka Desktop Setup; see LICENSE.txt.
package main

import (
	"fmt"
	"os"
	"path/filepath"
	"runtime"
	"runtime/debug"
	"strings"
)

func init() {
	// Windows' windows belong to the thread that made them: the setup's stay on this one.
	runtime.LockOSThread()
}

func parseOptions(args []string) options {
	var o options
	for i := 0; i < len(args); i++ {
		a := args[i]
		switch strings.ToLower(strings.TrimLeft(a, "/-")) {
		case "uninstall":
			o.uninstall = true
			if i+1 < len(args) && !strings.HasPrefix(args[i+1], "/") {
				o.root = args[i+1]
				i++
			}
		case "temp-copy":
			o.tempCopy = true
		case "keep":
			o.keep = true
		default:
			if isFile(a) {
				o.zip = a // (dragged onto the setup)
			}
		}
	}
	return o
}

func main() {
	defer func() {
		if p := recover(); p != nil {
			messageBox(0, fmt.Sprintf("%s Setup stopped on an error it did not expect:\n\n%v\n\n%s", AppName, p, debug.Stack()),
				AppName+" Setup", MB_OK|MB_ICONERROR)
			os.Exit(1)
		}
	}()
	p := newPlatform()
	self := selfPath()
	args := os.Args[1:]
	if len(args) > 0 && args[0] == "--headless" {
		// In a terminal: what it does, said there.
		pAttachConsole.Call(ATTACH_PARENT_PROCESS)
		out := os.Stdout
		if f, err := os.OpenFile("CONOUT$", os.O_WRONLY, 0); err == nil {
			out = f
		}
		os.Exit(headless(p, self, args[1:], out))
	}
	os.Remove(filepath.Join(filepath.Dir(self), SetupExe+".old")) // (put aside by an update the last time)
	opts := parseOptions(args)
	if opts.uninstall && !opts.tempCopy {
		root := opts.root
		if root == "" {
			root = filepath.Dir(self)
		}
		if (Install{root}).Exists() && Inside(self, root) && relaunchUninstall(self, root, true) {
			return // (the copy out of the app's folder does it)
		}
	}
	w := newWizard(p, self, opts)
	w.run()
	if opts.tempCopy {
		p.RemoveLater(self)
	}
}
