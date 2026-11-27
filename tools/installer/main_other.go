// SPDX-License-Identifier: LicenseRef-Sluka
// Copyright (c) 2026 Sluka. Part of Sluka Desktop Setup; see LICENSE.txt.
//go:build !windows

package main

import "os"

func main() {
	args := os.Args[1:]
	if len(args) > 0 && args[0] == "--headless" {
		args = args[1:]
	}
	os.Exit(headless(newPlatform(), selfPath(), args, os.Stdout))
}
