// SPDX-License-Identifier: LicenseRef-Sluka
// Copyright (c) 2026 Sluka. Part of Sluka Desktop's Setup; see LICENSE.txt.

package main

// The licence agreement Setup shows before it puts anything on the computer, and that --headless needs accepted
// (--accept-license) before it installs or updates: Sluka Desktop's LICENSE.txt, and the licence of Go, which Setup
// itself is built with.  build_installer.py writes terms.txt from those before it builds Setup.

import (
	_ "embed"
	"strings"
)

//go:embed terms.txt
var termsFile string

// TermsURL: Sluka's own terms of use, which Sluka Desktop is used under.
const TermsURL = "https://sluka.app/terms"

// licenseText: the agreement, with Windows' line ends (as its text boxes want them).
func licenseText() string {
	text := strings.ReplaceAll(termsFile, "\r\n", "\n")
	return strings.ReplaceAll(strings.TrimRight(text, "\n")+"\n", "\n", "\r\n")
}
