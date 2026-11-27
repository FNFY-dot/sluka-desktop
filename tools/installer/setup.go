// SPDX-License-Identifier: LicenseRef-Sluka
// Copyright (c) 2026 Sluka. Part of Sluka Desktop Setup; see LICENSE.txt.
package main

import (
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strings"
)

// Platform: what the setup asks of the computer.  Windows' (platform_windows.go) is the real one; elsewhere one for
// the tests and for trying the setup's work without its window (platform_other.go).
type Platform interface {
	DefaultFolder() string
	ProgramFiles() []string
	ShellFolder(which string) string // "desktop", "programs"; "" where there is none
	Downloads() string
	LocalFolder() string // the app's folder for what need not last (%LOCALAPPDATA%\sluka-desktop)
	Registered() string
	Register(i Install, size int64) error
	Unregister(i Install)
	AnkiHere() bool
	FindPython() (*Python, error)
	// RunApp: one of the app's own commands (app\run.py ...), what it says going to each.
	RunApp(py *Python, i Install, each func(string), args ...string) (int, error)
	MakeSetupLink(i Install, link string) error
	RemoveLater(path string)
	Launch(py *Python, i Install, links []string) error
	Separator() string
}

// Python: the Python the app runs with.
type Python struct {
	Exe        string // python.exe
	Windowless string // pythonw.exe
	Version    string
	Bits       int
	Store      bool // (the Microsoft Store's: what it writes under AppData mpv and Anki do not see)
}

var ErrNoPython = errors.New("Sluka Desktop needs Python 3.9 or newer, and none was found on this computer")

// Reporter: what the setup is doing, for its window (or for a terminal).
type Reporter interface {
	Status(text string)
	Progress(done, total int64)
	Log(line string)
}

// Choices: what was asked for.
type Choices struct {
	Desktop, StartMenu bool
	Anki               bool
	Extension          string // a zip ("" for none, or later)
}

// Result: what came of it.
type Result struct {
	Install  Install
	Lines    []string // said on the last page
	Warnings []string
	CanStart bool
}

func (r *Result) say(format string, args ...any) {
	r.Lines = append(r.Lines, fmt.Sprintf(format, args...))
}
func (r *Result) warn(format string, args ...any) {
	r.Warnings = append(r.Warnings, fmt.Sprintf(format, args...))
}

// Setup: the setup's work.
type Setup struct {
	P       Platform
	Payload *Payload // what this setup installs (none in the copy of the setup in the app's folder)
	Self    string   // this program (its program part is copied into the app's folder)
	Python  *Python
}

// ------------------------------------------------------------------------------------------------ what is there

// Candidates: the copies of the app this computer has, the likeliest first: the one this setup is in, the one in
// Windows' list of apps, the one running, the ones the shortcuts start, the one in the usual folder.
func (s *Setup) Candidates() []Install {
	var roots []string
	if s.Self != "" {
		roots = append(roots, filepath.Dir(s.Self))
	}
	roots = append(roots, s.P.Registered(), RunningRoot())
	for _, which := range []string{"desktop", "programs"} {
		if folder := s.P.ShellFolder(which); folder != "" {
			if data, err := os.ReadFile(filepath.Join(folder, "Sluka.lnk")); err == nil {
				roots = append(roots, LinkRoots(data)...)
			}
		}
	}
	roots = append(roots, s.P.DefaultFolder())
	var found []Install
	for _, root := range roots {
		i := Install{root}
		if root == "" || !i.Exists() {
			continue
		}
		dup := false
		for _, f := range found {
			if f.Same(i) {
				dup = true
			}
		}
		if !dup {
			found = append(found, i)
		}
	}
	return found
}

// FolderProblem: why the app cannot go into a folder ("" where it can).  (Tried by writing there; folders made for
// the try are taken away again.)
func (s *Setup) FolderProblem(folder string) string {
	if folder == "" {
		return "Choose a folder."
	}
	if !filepath.IsAbs(folder) {
		return "The whole path, please (C:\\Users\\you\\..., say)."
	}
	for _, place := range s.P.ProgramFiles() {
		if place != "" && Inside(folder, place) {
			return fmt.Sprintf("Not under %s: a program there may write nothing into its own folder without asking "+
				"Windows each time, and Sluka keeps its data in its own. Choose another folder.", place)
		}
	}
	if isFile(folder) {
		return folder + " is a file."
	}
	var made []string
	for step := folder; !exists(step) && filepath.Dir(step) != step; step = filepath.Dir(step) {
		made = append(made, step)
	}
	defer func() {
		for _, path := range made {
			if os.Remove(path) != nil {
				break
			}
		}
	}()
	if err := os.MkdirAll(folder, 0o755); err != nil {
		return fmt.Sprintf("%s cannot be made (%v). Choose another folder.", folder, err)
	}
	probe := filepath.Join(folder, ".sluka-setup-probe")
	if err := os.WriteFile(probe, nil, 0o644); err != nil {
		return fmt.Sprintf("%s cannot be written to. Choose another folder.", folder)
	}
	os.Remove(probe)
	return ""
}

// InstallIn: where a folder chosen for the app leads -- an install there already (or in its sluka-desktop folder),
// or the folder itself.
func InstallIn(folder string) Install {
	for _, there := range []string{folder, filepath.Join(folder, "sluka-desktop"), filepath.Join(folder, AppName)} {
		if i := (Install{there}); i.Exists() {
			return i
		}
	}
	return Install{folder}
}

// ------------------------------------------------------------------------------------------------ the work

func (s *Setup) run(i Install, r Reporter, args ...string) error {
	if s.Python == nil {
		return ErrNoPython
	}
	r.Log("> " + strings.Join(args, " "))
	code, err := s.P.RunApp(s.Python, i, r.Log, args...)
	if err != nil {
		return err
	}
	if code != 0 {
		return fmt.Errorf("%s ended with code %d (said above)", args[0], code)
	}
	return nil
}

// Put: a payload's files into a folder -- a new install, or in place of the version there (data, extension and
// config.ini as they are) -- and the setup beside them.  Part of Install and Update.
func (s *Setup) put(payload *Payload, i Install, r Reporter, res *Result, from string, share float64) error {
	fresh := !i.Exists()
	staging := filepath.Join(i.Root, Staging)
	os.RemoveAll(staging)
	os.RemoveAll(filepath.Join(i.Root, OldDir))
	madeRoot := !exists(i.Root)
	fail := func(err error) error {
		os.RemoveAll(staging)
		if madeRoot {
			os.RemoveAll(i.Root)
		}
		return err
	}
	r.Status(fmt.Sprintf("Unpacking %s %s…", AppName, payload.Version))
	r.Log(fmt.Sprintf("%s %s from %s, into %s", AppName, payload.Version, filepath.Base(payload.Path), i.Root))
	written, err := payload.Extract(staging, func(done, total int64) {
		if total > 0 {
			r.Progress(int64(float64(done)/float64(total)*share*1000), 1000)
		}
	})
	if err != nil {
		return fail(fmt.Errorf("%s's files could not be unpacked: %v", AppName, err))
	}
	r.Status("Putting the files in place…")
	if err := PutInPlace(staging, i.Root); err != nil {
		return fail(fmt.Errorf("%s's files could not be put in place (%v): a program has one of them open. Close %s, "+
			"any game it read text from, Anki and mpv, then try again: nothing was changed", AppName, err, AppName))
	}
	os.RemoveAll(staging)
	r.Log(fmt.Sprintf("%d files", len(written)))
	if from == "" {
		from = s.Self
	}
	if err := WriteStub(from, filepath.Join(i.Root, SetupExe)); err != nil {
		if errStub := WriteStub(s.Self, filepath.Join(i.Root, SetupExe)); errStub != nil {
			r.Log(fmt.Sprintf("(the setup could not be put beside it: %v)", errStub))
		}
	}
	var missing []string
	for _, rel := range written {
		if strings.HasPrefix(rel, "engine/") && !isFile(filepath.Join(i.Root, filepath.FromSlash(rel))) {
			missing = append(missing, filepath.Base(rel))
		}
	}
	if len(missing) > 0 {
		res.warn("Of the engine's files, %s went missing as they were written: Windows Security may have taken them "+
			"away (a text hooker reaches into games, as some viruses do). Game text needs them: README.txt, section 7.",
			strings.Join(missing, ", "))
	}
	if fresh {
		res.say("%s %s is in %s.", AppName, payload.Version, i.Root)
	} else {
		res.say("%s is updated to %s, in %s. Your data and settings are as they were.", AppName, payload.Version, i.Root)
	}
	return nil
}

func (s *Setup) register(i Install, r Reporter) {
	var size int64
	filepath.Walk(i.Root, func(path string, info os.FileInfo, err error) error {
		if err != nil {
			return nil
		}
		if info.IsDir() && SamePath(path, filepath.Join(i.Root, "data")) {
			return filepath.SkipDir
		}
		if info.Mode().IsRegular() {
			size += info.Size()
		}
		return nil
	})
	if err := s.P.Register(i, size); err != nil {
		r.Log(fmt.Sprintf("(not in Windows' list of apps: %v)", err))
	}
}

// Install: Sluka Desktop into a folder (new, or one with a Sluka Desktop of its own unpacked by hand), as chosen.
func (s *Setup) Install(i Install, c Choices, r Reporter) (Result, error) {
	res := Result{Install: i}
	if s.Payload == nil {
		return res, fmt.Errorf("this setup has no %s in it to install", AppName)
	}
	if free, ok := freeSpace(i.Root); ok && free < s.Payload.Size+s.Payload.Size/3 {
		return res, fmt.Errorf("there is not room for %s there: it needs %d MB, and %d MB are free", AppName,
			(s.Payload.Size+s.Payload.Size/3)>>20, free>>20)
	}
	if err := s.put(s.Payload, i, r, &res, "", 0.7); err != nil {
		return res, err
	}
	if c.Extension != "" {
		r.Status("Putting in your Sluka extension…")
		r.Progress(750, 1000)
		if err := s.run(i, r, "install-extension", c.Extension); err != nil {
			res.warn("Your Sluka extension could not be put in (%v). Run Setup again, and \"Update from a zip\" with it.", err)
		} else {
			res.say("The Sluka extension %s is in it.", i.ExtensionVersion())
		}
	} else if i.ExtensionVersion() == "" {
		res.warn("%s has no Sluka extension yet, and opens once it has: run Setup again, and \"Update from a zip\" "+
			"with your extension's zip.", AppName)
	}
	r.Status("Adding it to Windows' list of apps…")
	r.Progress(820, 1000)
	s.register(i, r)
	r.Status("Making the shortcuts…")
	r.Progress(850, 1000)
	s.shortcuts(i, c.Desktop, c.StartMenu, r, &res)
	if c.Anki {
		r.Status("Putting Sluka's add-on into Anki…")
		r.Progress(920, 1000)
		if err := s.run(i, r, "install-anki"); err != nil {
			res.warn("Sluka's add-on could not be put into Anki (%v).", err)
		} else {
			res.say("Sluka's add-on is in Anki: restart Anki.")
		}
	}
	s.register(i, r) // (again: with the icon the shortcuts brought)
	r.Progress(1000, 1000)
	r.Status("Done.")
	res.CanStart = i.ExtensionVersion() != ""
	return res, nil
}

// Update: a payload in place of the version installed: the files only (shortcuts, extension and data as they are).
func (s *Setup) Update(payload *Payload, i Install, r Reporter, from string) (Result, error) {
	res := Result{Install: i}
	before := i.Version()
	if err := s.put(payload, i, r, &res, from, 0.85); err != nil {
		return res, err
	}
	switch {
	case before != "" && CompareVersions(before, payload.Version) == 0:
		res.Lines[len(res.Lines)-1] = fmt.Sprintf("%s %s is installed again, in %s. Your data and settings are as they "+
			"were.", AppName, payload.Version, i.Root)
	case before != "":
		res.Lines[len(res.Lines)-1] = fmt.Sprintf("%s is updated from %s to %s, in %s. Your data and settings are as "+
			"they were.", AppName, before, payload.Version, i.Root)
	}
	r.Status("Adding it to Windows' list of apps…")
	r.Progress(900, 1000)
	s.register(i, r)
	// The setup in the Start menu, beside Sluka (0.10.0's was another, now gone).
	if s.hasLink("programs", i) {
		if folder := s.P.ShellFolder("programs"); folder != "" {
			if err := s.P.MakeSetupLink(i, filepath.Join(folder, SetupLink)); err != nil {
				r.Log(fmt.Sprintf("(the setup's shortcut could not be made: %v)", err))
			}
		}
	}
	res.say("If Sluka is in Anki: restart Anki once, after %s's first start.", AppName)
	r.Progress(1000, 1000)
	r.Status("Done.")
	res.CanStart = i.ExtensionVersion() != ""
	return res, nil
}

// UpdateFromZip: Sluka Desktop or the Sluka extension, from a zip (or a newer setup).
func (s *Setup) UpdateFromZip(path string, i Install, r Reporter) (Result, error) {
	if payload, err := FindPayload(path); err == nil {
		if s.P.Separator() == `\` && !payload.Windows {
			return Result{Install: i}, fmt.Errorf("%s is %s for Linux (Tails), not for Windows", filepath.Base(path), AppName)
		}
		from := ""
		if _, err := StubSize(path); err == nil {
			from = path // (a newer setup: it goes beside the app, in place of this one)
		}
		return s.Update(payload, i, r, from)
	}
	res := Result{Install: i}
	ext, err := ExtensionIn(path)
	if err != nil {
		return res, fmt.Errorf("%s is neither %s nor a browser extension (no manifest.json in it)", filepath.Base(path), AppName)
	}
	before := i.ExtensionVersion()
	r.Status(fmt.Sprintf("Putting in the Sluka extension %s…", ext.Version))
	r.Progress(200, 1000)
	if err := s.run(i, r, "install-extension", path); err != nil {
		return res, fmt.Errorf("the extension was not changed: %v", err)
	}
	if before != "" {
		res.say("The Sluka extension is updated from %s to %s.", before, i.ExtensionVersion())
	} else {
		res.say("The Sluka extension %s is in %s.", i.ExtensionVersion(), AppName)
	}
	res.say("If Sluka is in Anki: restart Anki once.")
	s.register(i, r)
	r.Progress(1000, 1000)
	r.Status("Done.")
	res.CanStart = true
	return res, nil
}

func (s *Setup) hasLink(which string, i Install) bool {
	folder := s.P.ShellFolder(which)
	if folder == "" {
		return false
	}
	data, err := os.ReadFile(filepath.Join(folder, "Sluka.lnk"))
	return err == nil && LinkLeadsTo(data, i.Root, s.P.Separator())
}

// HasLinks: whether the desktop and the Start menu have this copy's shortcut.
func (s *Setup) HasLinks(i Install) (desktop, startMenu bool) {
	return s.hasLink("desktop", i), s.hasLink("programs", i)
}

// shortcuts: the app's (install-menu, with what is not wanted taken away), and the setup's in the Start menu.
func (s *Setup) shortcuts(i Install, desktop, startMenu bool, r Reporter, res *Result) {
	hadDesktop, hadMenu := s.HasLinks(i)
	if desktop || startMenu || hadDesktop || hadMenu {
		args := []string{"install-menu"}
		if !desktop {
			args = append(args, "--no-desktop")
		}
		if !startMenu {
			args = append(args, "--no-start-menu")
		}
		if err := s.run(i, r, args...); err != nil {
			res.warn("The shortcuts could not all be made (%v).", err)
		}
	}
	if folder := s.P.ShellFolder("programs"); folder != "" {
		link := filepath.Join(folder, SetupLink)
		if startMenu {
			if err := s.P.MakeSetupLink(i, link); err != nil {
				r.Log(fmt.Sprintf("(the setup's shortcut could not be made: %v)", err))
			}
		} else {
			os.Remove(link)
		}
	}
	nowDesktop, nowMenu := s.HasLinks(i)
	switch {
	case nowDesktop && nowMenu:
		res.say("Sluka is on the desktop and in the Start menu.")
	case nowDesktop:
		res.say("Sluka is on the desktop.")
	case nowMenu:
		res.say("Sluka is in the Start menu.")
	case desktop || startMenu:
	default:
		res.say("No shortcuts: Sluka.cmd in %s starts it.", i.Root)
	}
}

// Shortcuts: the shortcuts as chosen.
func (s *Setup) Shortcuts(i Install, desktop, startMenu bool, r Reporter) (Result, error) {
	res := Result{Install: i}
	r.Status("Making the shortcuts…")
	r.Progress(300, 1000)
	s.shortcuts(i, desktop, startMenu, r, &res)
	r.Progress(1000, 1000)
	r.Status("Done.")
	return res, nil
}

// Uninstall: Sluka Desktop taken away -- what it put outside its folder, then its files (yours too, unless kept).
func (s *Setup) Uninstall(i Install, keep bool, r Reporter) (Result, error) {
	res := Result{Install: i}
	version := i.Version()
	r.Status("Taking away its shortcuts, and Sluka from Anki and mpv…")
	r.Progress(100, 1000)
	removed := false
	if s.Python != nil && CompareVersions(version, "0.10") >= 0 {
		if err := s.run(i, r, "remove-from-pc"); err == nil {
			removed = true
		} else {
			r.Log(fmt.Sprintf("(%v)", err))
		}
	}
	if !removed {
		// (No Python, or an app from before remove-from-pc: its shortcuts at least.)
		for _, which := range []string{"desktop", "programs"} {
			if s.hasLink(which, i) {
				os.Remove(filepath.Join(s.P.ShellFolder(which), "Sluka.lnk"))
			}
		}
		if s.Python == nil {
			res.warn("Without Python, Sluka's add-on in Anki and its script in mpv were left where they are.")
		}
	}
	if folder := s.P.ShellFolder("programs"); folder != "" {
		os.Remove(filepath.Join(folder, SetupLink))
	}
	s.P.Unregister(i)
	r.Status("Taking away its files…")
	r.Progress(400, 1000)
	left := RemoveInstall(i.Root, keep)
	if !keep {
		if local := s.P.LocalFolder(); local != "" {
			others := false
			for _, o := range s.Candidates() {
				if !o.Same(i) {
					others = true
				}
			}
			if !others {
				os.RemoveAll(local)
			}
		}
	}
	if !FolderHasThings(i.Root) {
		os.RemoveAll(i.Root)
	}
	if exists(i.Root) && !keep {
		left = []string{i.Root}
	}
	for _, path := range left {
		r.Log("(in use: taken away in a moment) " + path)
		s.P.RemoveLater(path)
	}
	if keep && exists(filepath.Join(i.Root, "data")) {
		res.say("%s is uninstalled. Your words, books and settings stay in %s, for a %s installed there again.",
			AppName, i.Root, AppName)
	} else {
		res.say("%s is uninstalled.", AppName)
	}
	r.Progress(1000, 1000)
	r.Status("Done.")
	return res, nil
}
