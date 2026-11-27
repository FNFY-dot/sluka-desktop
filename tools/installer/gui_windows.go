// SPDX-License-Identifier: LicenseRef-Sluka
// Copyright (c) 2026 Sluka. Part of Sluka Desktop's Setup; see LICENSE.txt.

package main

// The setup's window: a classic Windows wizard -- a page at a time, Back / Next / Cancel -- with Windows' own
// controls (Common Controls 6, from the program's manifest), drawn in Sluka's dark colours (theme_windows.go).

import (
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"sync"
	"syscall"
	"time"
	"unsafe"
)

type page int

const (
	pageLicense page = iota
	pageWelcome
	pageFolder
	pageOptions
	pageMaintain
	pageUninstall
	pageProgress
	pageFinish
	pageNothing
	pageFooter // (the buttons, on every page)
)

const (
	idNext = IDOK
	idBack = 3

	wmWorkProgress = WM_APP + 1
	wmWorkDone     = WM_APP + 2
	wmPython       = WM_APP + 3

	// The window's inside, in pixels at 100 %.
	winW    = 560
	winH    = 420
	headerH = 72
	footerH = 54
	margin  = 24
)

type options struct {
	uninstall bool
	root      string
	zip       string
	tempCopy  bool
	keep      bool
}

type wizard struct {
	p     Platform
	s     *Setup
	opts  options
	hwnd  uintptr
	hinst uintptr
	scale float64

	font, title, mono                           uintptr
	bgBrush, footerBrush, lineBrush, fieldBrush uintptr
	icon, bigIcon, smIcon                       uintptr

	page     page
	pages    map[page][]uintptr
	off      map[uintptr]bool // (on its page, but not shown)
	footer   map[uintptr]bool
	mine     map[uintptr]bool // (the setup's buttons, drawn in its colours)
	progress int              // (the progress bar's, in thousandths)
	fields   map[uintptr]bool // (its text boxes)
	colors   map[uintptr]uint32
	nextID   int
	radios   []uintptr
	head     [2]string
	mode     string // "fresh", "maintain", "uninstall", "nothing"
	previous page   // (the page before the work, for Back after a failure)

	back, next, cancel                                                  uintptr
	terms, accept, termsLink                                            uintptr
	welcomeText, pythonText, getPython, lookAgain                       uintptr
	folderLabel, folderEdit, folderBrowse, folderInfo                   uintptr
	optDesktop, optMenu, optAnki, extLabel, extEdit, extBrowse, extInfo uintptr
	maintInfo, maintPath, otherFolder, radUpdate, radZip, zipEdit       uintptr
	zipBrowse                                                           uintptr
	zipInfo, radLinks, linkDesktop, linkMenu, radRemove, keepData       uintptr
	unText, unKeep, unNote                                              uintptr
	status, bar, logBox                                                 uintptr
	finText, finStart                                                   uintptr
	nothingText                                                         uintptr

	current Install // the copy of the app this setup looks after
	target  Install // where a new one goes
	working bool
	failed  bool
	action  string

	mu      sync.Mutex
	pending struct {
		status      string
		done, total int64
		log         []string
		posted      bool
	}
	result      Result
	err         error
	logLines    []string
	pythonFound bool
	pythonReady chan struct{} // (closed once the first look for Python is done)
	browseStart *uint16
	callbacks   struct{ wnd, browse uintptr }
}

func (w *wizard) px(v int) int { return int(float64(v)*w.scale + 0.5) }

// ------------------------------------------------------------------------------------------------ Reporter

func (w *wizard) wake() {
	if !w.pending.posted {
		w.pending.posted = true
		post(w.hwnd, wmWorkProgress, 0, 0)
	}
}

func (w *wizard) Status(text string) {
	w.mu.Lock()
	w.pending.status = text
	w.wake()
	w.mu.Unlock()
}

func (w *wizard) Progress(done, total int64) {
	w.mu.Lock()
	w.pending.done, w.pending.total = done, total
	w.wake()
	w.mu.Unlock()
}

func (w *wizard) Log(line string) {
	w.mu.Lock()
	w.pending.log = append(w.pending.log, line)
	w.wake()
	w.mu.Unlock()
}

// ------------------------------------------------------------------------------------------------ making the window

func newWizard(p Platform, self string, opts options) *wizard {
	w := &wizard{p: p, opts: opts, pages: map[page][]uintptr{}, off: map[uintptr]bool{}, footer: map[uintptr]bool{},
		mine: map[uintptr]bool{}, fields: map[uintptr]bool{}, colors: map[uintptr]uint32{}, nextID: 100,
		pythonReady: make(chan struct{})}
	w.s = &Setup{P: p, Self: self}
	if payload, err := FindPayload(self); err == nil {
		w.s.Payload = payload
	}
	return w
}

func (w *wizard) run() {
	pCoInitializeEx.Call(0, COINIT_APARTMENTTHREADED|COINIT_DISABLE_OLE1DDE)
	icc := initCommonControlsEx{Size: uint32(unsafe.Sizeof(initCommonControlsEx{})), ICC: ICC_PROGRESS_CLASS | ICC_STANDARD}
	pInitCommonControlsEx.Call(uintptr(unsafe.Pointer(&icc)))
	w.hinst, _, _ = pGetModuleHandleW.Call(0)

	dpi := uintptr(96)
	if pGetDpiForSystem.Find() == nil {
		dpi, _, _ = pGetDpiForSystem.Call()
	} else {
		dc, _, _ := pGetDC.Call(0)
		dpi, _, _ = pGetDeviceCaps.Call(dc, LOGPIXELSY)
		pReleaseDC.Call(0, dc)
	}
	if dpi == 0 {
		dpi = 96
	}
	style := uintptr(WS_OVERLAPPED | WS_CAPTION | WS_SYSMENU | WS_MINIMIZEBOX | WS_CLIPCHILDREN)
	ex := uintptr(WS_EX_CONTROLPAR | WS_EX_APPWINDOW)
	var work rect
	pSystemParametersInfo.Call(SPI_GETWORKAREA, 0, uintptr(unsafe.Pointer(&work)), 0)
	// Everything a quarter larger than Windows' own size for the screen's scale, for reading ease -- less where the
	// window would not fit on the screen so (a small screen at a large scale), never smaller than Windows' own.
	zoom := FitZoom(int(dpi), int(work.Right-work.Left), int(work.Bottom-work.Top), func(scale float64) (int, int) {
		w.scale = scale
		frame := rect{0, 0, int32(w.px(winW)), int32(w.px(winH))}
		pAdjustWindowRectEx.Call(uintptr(unsafe.Pointer(&frame)), style, 0, ex)
		return int(frame.Right - frame.Left), int(frame.Bottom - frame.Top)
	})
	w.scale = float64(dpi) / 96 * zoom
	zoomed := int(float64(dpi)*zoom + 0.5) // (the fonts, as for a screen of that scale)
	w.font = makeFont(9, FW_NORMAL, zoomed)
	w.title = makeFont(12, FW_SEMIBOLD, zoomed)
	w.mono = makeFace("Consolas", 9, FW_NORMAL, zoomed) // (the licence agreement, whose lists line up in columns)
	w.bgBrush, _, _ = pCreateSolidBrush.Call(colorBg)
	w.footerBrush, _, _ = pCreateSolidBrush.Call(colorFooter)
	w.lineBrush, _, _ = pCreateSolidBrush.Call(colorLine)
	w.fieldBrush, _, _ = pCreateSolidBrush.Call(colorField)
	w.bigIcon = loadIcon(w.hinst, 32, 32)
	w.smIcon = loadIcon(w.hinst, 16, 16)
	w.icon = loadIcon(w.hinst, w.px(40), w.px(40))

	w.callbacks.wnd = syscall.NewCallback(w.wndProc)
	w.callbacks.browse = syscall.NewCallback(w.browseProc)
	class := wndClassEx{Size: uint32(unsafe.Sizeof(wndClassEx{})), WndProc: w.callbacks.wnd, Instance: w.hinst,
		Icon: w.bigIcon, IconSm: w.smIcon, ClassName: wstr("SlukaDesktopSetup"), Background: w.bgBrush}
	class.Cursor, _, _ = pLoadCursorW.Call(0, IDC_ARROW)
	pRegisterClassExW.Call(uintptr(unsafe.Pointer(&class)))

	frame := rect{0, 0, int32(w.px(winW)), int32(w.px(winH))}
	pAdjustWindowRectEx.Call(uintptr(unsafe.Pointer(&frame)), style, 0, ex)
	width, height := frame.Right-frame.Left, frame.Bottom-frame.Top
	x, y := work.Left+(work.Right-work.Left-width)/2, work.Top+(work.Bottom-work.Top-height)/2
	if x < work.Left {
		x = work.Left
	}
	if y < work.Top {
		y = work.Top
	}
	title := AppName + " Setup"
	w.hwnd, _, _ = pCreateWindowExW.Call(ex, uintptr(unsafe.Pointer(wstr("SlukaDesktopSetup"))), uintptr(unsafe.Pointer(wstr(title))),
		style, uintptr(x), uintptr(y), uintptr(width), uintptr(height), 0, 0, w.hinst, 0)
	if w.hwnd == 0 {
		messageBox(0, "Windows would not make Setup's window.", title, MB_OK|MB_ICONERROR)
		return
	}
	send(w.hwnd, WM_SETICON, ICON_BIG, w.bigIcon)
	send(w.hwnd, WM_SETICON, ICON_SMALL, w.smIcon)
	darkTitleBar(w.hwnd)
	w.makeControls()
	w.begin()
	pShowWindow.Call(w.hwnd, SW_SHOWNORMAL)
	pUpdateWindow.Call(w.hwnd)
	pSetForegroundWindow.Call(w.hwnd)
	w.focusFirst() // (now that its controls can be seen)

	var m msgT
	for {
		r, _, _ := pGetMessageW.Call(uintptr(unsafe.Pointer(&m)), 0, 0, 0)
		if int32(r) <= 0 {
			break
		}
		if dlg, _, _ := pIsDialogMessageW.Call(w.hwnd, uintptr(unsafe.Pointer(&m))); dlg != 0 {
			continue
		}
		pTranslateMessage.Call(uintptr(unsafe.Pointer(&m)))
		pDispatchMessageW.Call(uintptr(unsafe.Pointer(&m)))
	}
}

func makeFont(points, weight, dpi int) uintptr {
	return makeFace("Segoe UI", points, weight, dpi)
}

func makeFace(face string, points, weight, dpi int) uintptr {
	height := -(points*dpi + 36) / 72
	f, _, _ := pCreateFontW.Call(uintptr(height), 0, 0, 0, uintptr(weight), 0, 0, 0, DEFAULT_CHARSET, 0, 0, CLEARTYPE_QUALITY, 0,
		uintptr(unsafe.Pointer(wstr(face))))
	return f
}

func loadIcon(hinst uintptr, cx, cy int) uintptr {
	h, _, _ := pLoadImageW.Call(hinst, 1, IMAGE_ICON, uintptr(cx), uintptr(cy), LR_DEFAULTCOLOR)
	return h
}

func (w *wizard) add(pg page, class, text string, style, ex uint32, x, y, cw, ch int) uintptr {
	w.nextID++
	id := w.nextID
	switch {
	case class == "BUTTON" && text == "< &Back":
		id = idBack
	case class == "BUTTON" && text == "&Next >":
		id = idNext
	case class == "BUTTON" && text == "Cancel":
		id = IDCANCEL
	}
	h, _, _ := pCreateWindowExW.Call(uintptr(ex), uintptr(unsafe.Pointer(wstr(class))), uintptr(unsafe.Pointer(wstr(text))),
		uintptr(WS_CHILD|style), uintptr(w.px(x)), uintptr(w.px(y)), uintptr(w.px(cw)), uintptr(w.px(ch)), w.hwnd, uintptr(id),
		w.hinst, 0)
	send(h, WM_SETFONT, w.font, 1)
	w.pages[pg] = append(w.pages[pg], h)
	if pg == pageFooter {
		w.footer[h] = true
	}
	switch class {
	case "BUTTON":
		w.mine[h] = true
	case "EDIT":
		w.fields[h] = true
		// (Windows' own dark edge for a text box, and its dark scroll bar for one of many lines, where Windows has them)
		if style&ES_MULTILINE != 0 {
			darkControl(h, "DarkMode_Explorer")
		} else {
			darkControl(h, "DarkMode_CFD")
		}
	}
	return h
}

func (w *wizard) label(pg page, text string, x, y, cw, ch int) uintptr {
	return w.add(pg, "STATIC", text, SS_LEFT|SS_NOPREFIX, 0, x, y, cw, ch)
}

func (w *wizard) button(pg page, text string, x, y, cw int) uintptr {
	return w.add(pg, "BUTTON", text, BS_PUSHBUTTON|WS_TABSTOP, 0, x, y, cw, 28)
}

func (w *wizard) check(pg page, text string, x, y, cw int) uintptr {
	return w.add(pg, "BUTTON", text, BS_AUTOCHECKBOX|WS_TABSTOP, 0, x, y, cw, 22)
}

func (w *wizard) radio(pg page, text string, x, y, cw int) uintptr {
	h := w.add(pg, "BUTTON", text, BS_RADIOBUTTON|WS_TABSTOP, 0, x, y, cw, 22)
	w.radios = append(w.radios, h)
	return h
}

func (w *wizard) edit(pg page, x, y, cw int) uintptr {
	return w.add(pg, "EDIT", "", ES_AUTOHSCROLL|WS_TABSTOP, WS_EX_CLIENTEDGE, x, y, cw, 26)
}

func (w *wizard) makeControls() {
	const full = winW - 2*margin
	const field = full - 100
	const right = winW - margin - 92

	// The licence: read, and accepted, before anything is put on the computer.
	w.terms = w.add(pageLicense, "EDIT", "", ES_MULTILINE|ES_READONLY|ES_AUTOVSCROLL|WS_VSCROLL|WS_TABSTOP, WS_EX_CLIENTEDGE,
		margin, 84, full, 240)
	send(w.terms, EM_SETLIMITTEXT, 1<<20, 0)
	send(w.terms, WM_SETFONT, w.mono, 1)
	setText(w.terms, licenseText())
	w.accept = w.check(pageLicense, "I &accept the licence agreement", margin, 334, full)
	w.termsLink = w.add(pageLicense, "STATIC", "Sluka's terms: sluka.app/terms", SS_LEFT|SS_NOPREFIX|SS_NOTIFY, 0,
		margin, winH-footerH+(footerH-18)/2, 240, 18)
	w.footer[w.termsLink] = true
	w.colors[w.termsLink] = colorLink

	w.welcomeText = w.label(pageWelcome, "", margin, 88, full, 120)
	w.pythonText = w.label(pageWelcome, "Looking for Python…", margin, 216, full, 58)
	w.getPython = w.button(pageWelcome, "&Get Python…", margin, 282, 130)
	w.lookAgain = w.button(pageWelcome, "&Look again", margin+138, 282, 110)

	w.folderLabel = w.label(pageFolder, "Install Sluka Desktop in this folder:", margin, 88, full, 20)
	w.folderEdit = w.edit(pageFolder, margin, 112, field)
	w.folderBrowse = w.button(pageFolder, "B&rowse…", right, 111, 92)
	w.folderInfo = w.label(pageFolder, "", margin, 150, full, 140)

	w.optDesktop = w.check(pageOptions, "Create a shortcut on the &desktop", margin, 88, full)
	w.optMenu = w.check(pageOptions, "Add Sluka Desktop to the &Start menu (with this setup beside it)", margin, 114, full)
	w.optAnki = w.check(pageOptions, "Put Sluka's add-on into &Anki (Anki was found on this computer)", margin, 140, full)
	w.extLabel = w.label(pageOptions, "Your Sluka extension: its zip, the Chrome edition", margin, 178, full, 20)
	w.extEdit = w.edit(pageOptions, margin, 202, field)
	w.extBrowse = w.button(pageOptions, "B&rowse…", right, 201, 92)
	w.extInfo = w.label(pageOptions, "", margin, 236, full, 64)

	w.maintInfo = w.label(pageMaintain, "", margin, 84, full-112, 20)
	w.maintPath = w.add(pageMaintain, "STATIC", "", SS_LEFT|SS_NOPREFIX|SS_PATHELLIPSIS, 0, margin, 104, full-112, 18)
	w.otherFolder = w.button(pageMaintain, "Another &folder…", winW-margin-104, 86, 104)
	w.radUpdate = w.radio(pageMaintain, "", margin, 126, full)
	w.radZip = w.radio(pageMaintain, "Update from a &zip: a newer Sluka extension, or a newer Sluka Desktop", margin, 152, full)
	w.zipEdit = w.edit(pageMaintain, margin+20, 176, field-20)
	w.zipBrowse = w.button(pageMaintain, "B&rowse…", right, 175, 92)
	w.zipInfo = w.label(pageMaintain, "", margin+20, 206, full-20, 20)
	w.radLinks = w.radio(pageMaintain, "&Shortcuts:", margin, 230, full)
	w.linkDesktop = w.check(pageMaintain, "On the &desktop", margin+20, 254, 200)
	w.linkMenu = w.check(pageMaintain, "In the Start &menu", margin+230, 254, full-230)
	w.radRemove = w.radio(pageMaintain, "&Uninstall Sluka Desktop", margin, 282, full)
	w.keepData = w.check(pageMaintain, "&Keep my words, books and settings (the data folder)", margin+20, 306, full-20)

	w.unText = w.label(pageUninstall, "", margin, 88, full, 72)
	w.unKeep = w.check(pageUninstall, "&Keep my words, books and settings (the data folder and config.ini)", margin, 166, full)
	w.unNote = w.label(pageUninstall, "Kept, they are there again for a Sluka Desktop installed in the same folder.", margin, 194, full, 40)

	w.status = w.label(pageProgress, "", margin, 88, full, 20)
	w.bar = w.add(pageProgress, "STATIC", "", SS_OWNERDRAW, 0, margin, 114, full, 12) // (drawn here: drawProgress)
	w.logBox = w.add(pageProgress, "EDIT", "", ES_MULTILINE|ES_READONLY|ES_AUTOVSCROLL|WS_VSCROLL|WS_TABSTOP, WS_EX_CLIENTEDGE,
		margin, 144, full, winH-footerH-144-12)
	send(w.logBox, EM_SETLIMITTEXT, 4<<20, 0)

	w.finText = w.label(pageFinish, "", margin, 88, full, 228)
	w.finStart = w.check(pageFinish, "&Start Sluka Desktop now", margin, 324, full)

	w.nothingText = w.label(pageNothing, "", margin, 88, full, 120)

	y := winH - footerH + (footerH-28)/2
	w.back = w.add(pageFooter, "BUTTON", "< &Back", BS_PUSHBUTTON|WS_TABSTOP, 0, winW-margin-88*3-12, y, 88, 28)
	w.next = w.add(pageFooter, "BUTTON", "&Next >", BS_DEFPUSHBUTTON|WS_TABSTOP, 0, winW-margin-88*2-8, y, 88, 28)
	w.cancel = w.add(pageFooter, "BUTTON", "Cancel", BS_PUSHBUTTON|WS_TABSTOP, 0, winW-margin-88, y, 88, 28)
	for _, h := range w.pages[pageFooter] {
		show(h, true)
	}
}

// ------------------------------------------------------------------------------------------------ what to do

func (w *wizard) begin() {
	if found := w.s.Candidates(); len(found) > 0 {
		w.current = found[0]
	}
	go func() {
		py, _ := w.p.FindPython()
		w.mu.Lock()
		w.s.Python = py
		w.mu.Unlock()
		close(w.pythonReady)
		post(w.hwnd, wmPython, 0, 0)
	}()
	switch {
	case w.opts.uninstall:
		root := w.opts.root
		if root == "" && w.current.Root != "" {
			root = w.current.Root
		}
		w.current = Install{root}
		if !w.current.Exists() {
			w.mode = "nothing"
			setText(w.nothingText, fmt.Sprintf("There is no %s in %s to uninstall.", AppName, root))
			w.showPage(pageNothing)
			return
		}
		w.mode = "uninstall"
		w.prepareUninstall()
		w.showPage(pageUninstall)
	case w.current.Root != "":
		w.mode = "maintain"
		w.prepareMaintain()
		if w.opts.zip != "" {
			setText(w.zipEdit, w.opts.zip)
			w.pick(w.radZip)
		}
		w.showPage(pageLicense)
	case w.s.Payload != nil:
		w.mode = "fresh"
		w.prepareFresh()
		w.showPage(pageLicense)
	default:
		w.mode = "nothing"
		setText(w.nothingText, fmt.Sprintf("%s is not installed on this computer, and this copy of Setup has nothing to "+
			"install.\r\n\r\nRun Sluka-Desktop-Setup-<version>.exe to install it.", AppName))
		w.showPage(pageNothing)
	}
}

func (w *wizard) python() *Python {
	w.mu.Lock()
	defer w.mu.Unlock()
	return w.s.Python
}

// waitPython: Python, once the look for it is done (a moment after the start).
func (w *wizard) waitPython() *Python {
	select {
	case <-w.pythonReady:
	case <-time.After(60 * time.Second):
	}
	return w.python()
}

func (w *wizard) prepareFresh() {
	setText(w.welcomeText, fmt.Sprintf("Setup puts Sluka Desktop %s on this computer: Sluka, the language-learning extension, "+
		"as a program of its own -- its dashboard, books and videos in windows of their own, its subtitles in mpv, its "+
		"words in Anki's review screen, and its floating subtitles over games.\r\n\r\nClick Next to go on, or Cancel to "+
		"leave Setup.", w.s.Payload.Version))
	show(w.getPython, false)
	show(w.lookAgain, false)
	w.off[w.getPython], w.off[w.lookAgain] = true, true
	setText(w.folderEdit, w.p.DefaultFolder())
	setChecked(w.optDesktop, true)
	setChecked(w.optMenu, true)
	anki := w.p.AnkiHere()
	setChecked(w.optAnki, anki)
	w.off[w.optAnki] = !anki
	if best := NewestExtension([]string{w.p.Downloads(), filepath.Dir(w.s.Self)}); best.Path != "" {
		setText(w.extEdit, best.Path)
	}
	w.describeExtension()
}

func (w *wizard) showPython() {
	py := w.python()
	w.pythonFound = py != nil
	if w.mode != "fresh" {
		return
	}
	if py == nil {
		setText(w.pythonText, "Sluka Desktop runs with Python 3.9 or newer, and none was found on this computer. "+
			"Get it from python.org (not the \"Python 3.x\" apps of the Microsoft Store), then click Look again.")
		w.colors[w.pythonText] = colorError
	} else {
		text := fmt.Sprintf("Python %s (%d-bit) is here: Sluka Desktop runs with it.\r\n%s", py.Version, py.Bits, py.Exe)
		if py.Store {
			text = fmt.Sprintf("Python %s is the Microsoft Store's: what it writes for mpv and Anki, Windows keeps "+
				"where they do not look. Python from python.org is better.", py.Version)
		} else if py.Bits != 64 {
			text += "\r\n(32-bit: game text needs a 64-bit Python.)"
		}
		setText(w.pythonText, text)
		delete(w.colors, w.pythonText)
	}
	w.off[w.getPython], w.off[w.lookAgain] = py != nil, py != nil
	if w.page == pageWelcome {
		show(w.getPython, py == nil)
		show(w.lookAgain, py == nil)
		w.buttons()
	}
	pInvalidateRect.Call(w.pythonText, 0, 1)
}

func (w *wizard) prepareMaintain() {
	cur := w.current
	info := fmt.Sprintf("%s %s, with the Sluka extension %s", AppName, cur.Version(), cur.ExtensionVersion())
	if cur.ExtensionVersion() == "" {
		info = fmt.Sprintf("%s %s, with no Sluka extension yet", AppName, cur.Version())
	}
	setText(w.maintInfo, info)
	setText(w.maintPath, cur.Root)
	w.colors[w.maintPath] = colorDim
	if w.s.Payload != nil {
		v, old := w.s.Payload.Version, cur.Version()
		text := fmt.Sprintf("&Update Sluka Desktop to %s", v)
		switch c := CompareVersions(v, old); {
		case c == 0:
			text = fmt.Sprintf("Install Sluka Desktop %s again, to mend it (&update)", v)
		case c < 0:
			text = fmt.Sprintf("Put Sluka Desktop %s in place of the newer %s (&update)", v, old)
		}
		setText(w.radUpdate, text)
		w.off[w.radUpdate] = false
		w.pick(w.radUpdate)
	} else {
		w.off[w.radUpdate] = true
		w.pick(w.radZip)
	}
	if found := FindZips([]string{w.p.Downloads()}, w.s.Self, "desktop", "extension"); len(found) > 0 && windowText(w.zipEdit) == "" {
		for _, f := range found {
			have := cur.Version()
			if f.Kind == "extension" {
				have = cur.ExtensionVersion()
			}
			if CompareVersions(f.Version, have) > 0 {
				setText(w.zipEdit, f.Path)
				break
			}
		}
	}
	desktop, menu := w.s.HasLinks(cur)
	setChecked(w.linkDesktop, desktop)
	setChecked(w.linkMenu, menu)
	setChecked(w.keepData, true)
	w.describeZip()
	w.setHeaderIcon()
}

func (w *wizard) prepareUninstall() {
	cur := w.current
	setText(w.unText, fmt.Sprintf("Sluka Desktop %s will be taken away from %s: its program and the Sluka extension, its "+
		"shortcuts, its add-on in Anki, its script in mpv, and its line in Windows' list of apps.", cur.Version(), cur.Root))
	setChecked(w.unKeep, w.opts.keep || !w.opts.tempCopy)
	w.setHeaderIcon()
}

// setHeaderIcon: Sluka's own icon (the one the app made from your extension's) in the header, where there is one.
func (w *wizard) setHeaderIcon() {
	ico := filepath.Join(w.current.Root, "data", "sluka.ico")
	if !isFile(ico) {
		return
	}
	h, _, _ := pLoadImageW.Call(0, uintptr(unsafe.Pointer(wstr(ico))), IMAGE_ICON, uintptr(w.px(40)), uintptr(w.px(40)), LR_LOADFROMFILE)
	if h != 0 {
		w.icon = h
	}
}

// ------------------------------------------------------------------------------------------------ the pages

var headers = map[page][2]string{
	pageLicense:   {"Licence agreement", "Read it, and accept it to go on."},
	pageWelcome:   {"Welcome to Sluka Desktop Setup", ""},
	pageFolder:    {"Where should Sluka Desktop go?", "Its program, your data and the Sluka extension stay together in one folder."},
	pageOptions:   {"Shortcuts, your extension, Anki", "What Setup does besides putting the files in place."},
	pageMaintain:  {"Sluka Desktop is installed", "Update it, change its shortcuts, or uninstall it."},
	pageUninstall: {"Uninstall Sluka Desktop", ""},
	pageProgress:  {"Working…", "This takes a moment."},
	pageFinish:    {"Done", ""},
	pageNothing:   {"Nothing to do here", ""},
}

func (w *wizard) showPage(pg page) {
	w.page = pg
	for p, list := range w.pages {
		if p == pageFooter {
			continue
		}
		for _, h := range list {
			show(h, p == pg && !w.off[h])
		}
	}
	if pg != pageProgress && pg != pageFinish {
		w.head = headers[pg]
	}
	if pg == pageWelcome && w.s.Payload != nil {
		w.head[1] = "Version " + w.s.Payload.Version
	}
	if pg == pageUninstall {
		w.head[1] = w.current.Root
	}
	if pg == pageMaintain {
		w.enableMaintain()
	}
	w.buttons()
	pInvalidateRect.Call(w.hwnd, 0, 1)
	w.focusFirst()
}

func (w *wizard) focusFirst() {
	for _, h := range w.pages[w.page] {
		if w.off[h] {
			continue
		}
		if visible, _, _ := pIsWindowVisible.Call(h); visible == 0 {
			continue
		}
		if enabled, _, _ := pIsWindowEnabled.Call(h); enabled == 0 {
			continue
		}
		if h == w.accept || h == w.folderEdit || h == w.extEdit || h == w.zipEdit || h == w.optDesktop || h == w.unKeep || h == w.finStart {
			pSetFocus.Call(h)
			return
		}
	}
	pSetFocus.Call(w.next)
}

func (w *wizard) buttons() {
	nextText, backOn, cancelOn, nextOn := "&Next >", false, true, true
	switch w.page {
	case pageLicense:
		nextOn = checked(w.accept)
	case pageWelcome:
		nextOn, backOn = w.pythonFound, true
	case pageFolder:
		backOn = true
	case pageOptions:
		backOn, nextText = true, "&Install"
	case pageMaintain:
		nextText, backOn = "&Apply", true
		if checked(w.radRemove) {
			nextText = "&Uninstall"
		}
		nextOn = w.maintainReady()
	case pageUninstall:
		nextText = "&Uninstall"
	case pageProgress:
		nextOn, cancelOn = false, false
	case pageFinish:
		nextText, cancelOn, backOn = "&Finish", false, w.failed
	case pageNothing:
		nextText, cancelOn = "&Close", false
	}
	setText(w.next, nextText)
	show(w.back, backOn)
	enable(w.next, nextOn)
	show(w.cancel, cancelOn)
}

// ------------------------------------------------------------------------------------------------ the maintenance page

func (w *wizard) pick(radio uintptr) {
	for _, r := range w.radios {
		setChecked(r, r == radio)
	}
	if w.page == pageMaintain {
		w.enableMaintain()
		w.buttons()
	}
}

func (w *wizard) enableMaintain() {
	zip, links, remove := checked(w.radZip), checked(w.radLinks), checked(w.radRemove)
	enable(w.zipEdit, zip)
	enable(w.zipBrowse, zip)
	enable(w.linkDesktop, links)
	enable(w.linkMenu, links)
	enable(w.keepData, remove)
}

func (w *wizard) maintainReady() bool {
	if checked(w.radZip) {
		path := strings.TrimSpace(strings.Trim(windowText(w.zipEdit), `"`))
		_, err := Describe(path)
		return path != "" && err == nil
	}
	return checked(w.radUpdate) || checked(w.radLinks) || checked(w.radRemove)
}

func (w *wizard) describeZip() {
	path := strings.TrimSpace(strings.Trim(windowText(w.zipEdit), `"`))
	text := "A zip from your Downloads folder is filled in when there is a newer one there."
	delete(w.colors, w.zipInfo)
	if path != "" {
		if d, err := Describe(path); err != nil {
			text = "That is neither Sluka Desktop nor a browser extension."
			if !exists(path) {
				text = "There is no such file."
			}
			w.colors[w.zipInfo] = colorError
		} else {
			have := w.current.Version()
			if d.Kind == "extension" {
				have = w.current.ExtensionVersion()
			}
			switch c := CompareVersions(d.Version, have); {
			case have == "":
				text = d.Words + "."
			case c > 0:
				text = fmt.Sprintf("%s: newer than yours (%s).", d.Words, have)
			case c == 0:
				text = fmt.Sprintf("%s: the one you have.", d.Words)
			default:
				text = fmt.Sprintf("%s: older than yours (%s).", d.Words, have)
			}
		}
	}
	setText(w.zipInfo, text)
	pInvalidateRect.Call(w.zipInfo, 0, 1)
}

// ------------------------------------------------------------------------------------------------ the fresh install's pages

func (w *wizard) describeFolder() {
	folder := strings.TrimSpace(strings.Trim(windowText(w.folderEdit), `"`))
	there := InstallIn(folder)
	var lines []string
	if there.Exists() {
		lines = append(lines, fmt.Sprintf("%s %s is in this folder already (unpacked by hand, say): it is updated there, "+
			"and your data and settings stay as they are.", AppName, there.Version()))
	}
	if w.s.Payload != nil {
		need := (w.s.Payload.Size + w.s.Payload.Size/3) >> 20
		if free, ok := freeSpace(folder); ok {
			lines = append(lines, fmt.Sprintf("It needs about %d MB, and %s are free there.", need, sizeText(free)))
		} else {
			lines = append(lines, fmt.Sprintf("It needs about %d MB.", need))
		}
	}
	lines = append(lines, "Not under \"Program Files\": Sluka keeps its data in its own folder, which a program there "+
		"may not write to.")
	setText(w.folderInfo, strings.Join(lines, "\r\n\r\n"))
}

func sizeText(n int64) string {
	switch {
	case n >= 10<<30:
		return fmt.Sprintf("%d GB", n>>30)
	case n >= 1<<30:
		return fmt.Sprintf("%.1f GB", float64(n)/(1<<30))
	default:
		return fmt.Sprintf("%d MB", n>>20)
	}
}

func (w *wizard) describeExtension() {
	path := strings.TrimSpace(strings.Trim(windowText(w.extEdit), `"`))
	delete(w.colors, w.extInfo)
	var text string
	switch {
	case path == "" && w.target.ExtensionVersion() != "":
		text = fmt.Sprintf("The Sluka extension %s that is there stays. (A newer zip here puts it in instead.)",
			w.target.ExtensionVersion())
	case path == "":
		text = "Leave it empty to add it later (Setup again, \"Update from a zip\"): Sluka Desktop opens once it has it."
	default:
		ext, err := ExtensionIn(path)
		switch {
		case err != nil && !exists(path):
			text, w.colors[w.extInfo] = "There is no such file.", colorError
		case err != nil:
			text, w.colors[w.extInfo] = "That zip holds no browser extension.", colorError
		case !ext.Sluka:
			text, w.colors[w.extInfo] = fmt.Sprintf("%s %s is not the Chrome edition (manifest version 3).", nonEmpty(ext.Name, "That"), ext.Version), colorError
		default:
			text = fmt.Sprintf("%s %s: it goes in with Sluka Desktop.", nonEmpty(ext.Name, "Sluka"), ext.Version)
			if dir := filepath.Dir(path); SamePath(dir, w.p.Downloads()) {
				text += " (Found in your Downloads folder.)"
			}
		}
	}
	setText(w.extInfo, text)
	pInvalidateRect.Call(w.extInfo, 0, 1)
}

func nonEmpty(a, b string) string {
	if a != "" {
		return a
	}
	return b
}

// ------------------------------------------------------------------------------------------------ dialogs

func (w *wizard) browseProc(hwnd, msg, lparam, data uintptr) uintptr {
	if msg == BFFM_INITIALIZED && w.browseStart != nil {
		send(hwnd, BFFM_SETSELECTW, 1, uintptr(unsafe.Pointer(w.browseStart)))
	}
	return 0
}

func (w *wizard) chooseFolder(title, start string) string {
	for start != "" && !isDir(start) && filepath.Dir(start) != start {
		start = filepath.Dir(start)
	}
	w.browseStart = wstr(start)
	name := make([]uint16, 261)
	info := browseInfo{Owner: w.hwnd, DisplayName: &name[0], Title: wstr(title),
		Flags: BIF_RETURNONLYFSDIRS | BIF_NEWDIALOGSTYLE | BIF_EDITBOX, Fn: w.callbacks.browse}
	pidl, _, _ := pSHBrowseForFolderW.Call(uintptr(unsafe.Pointer(&info)))
	w.browseStart = nil
	if pidl == 0 {
		return ""
	}
	defer pCoTaskMemFree.Call(pidl)
	path := make([]uint16, 32768)
	if ok, _, _ := pSHGetPathFromIDListW.Call(pidl, uintptr(unsafe.Pointer(&path[0]))); ok == 0 {
		return ""
	}
	return syscall.UTF16ToString(path)
}

func (w *wizard) chooseFile(title, start string) string {
	file := make([]uint16, 32768)
	filter := wfilter("Zip files and Sluka Desktop setups (*.zip, *.exe)", "*.zip;*.exe", "All files", "*.*")
	ofn := openFileName{Owner: w.hwnd, Filter: &filter[0], File: &file[0], MaxFile: uint32(len(file)), Title: wstr(title),
		InitialDir: wstr(start), Flags: OFN_FILEMUSTEXIST | OFN_PATHMUSTEXIST | OFN_HIDEREADONLY | OFN_EXPLORER | OFN_DONTADDTORECENT}
	ofn.StructSize = uint32(unsafe.Sizeof(ofn))
	if ok, _, _ := pGetOpenFileNameW.Call(uintptr(unsafe.Pointer(&ofn))); ok == 0 {
		return ""
	}
	return syscall.UTF16ToString(file)
}

func wfilter(parts ...string) []uint16 {
	var out []uint16
	for _, p := range parts {
		u, _ := syscall.UTF16FromString(p)
		out = append(out, u...)
	}
	return append(out, 0)
}

func (w *wizard) ask(text string, flags uintptr) int {
	return messageBox(w.hwnd, text, AppName+" Setup", flags)
}

// waitClosed: the app in this folder closed, since its files are changed: asked for until it is.
func (w *wizard) waitClosed(i Install) bool {
	for Running(i) {
		if w.ask(AppName+" is running. Close it -- its windows, and the floating subtitles -- then click Retry.",
			MB_RETRYCANCEL|MB_ICONWARNING) != IDRETRY {
			return false
		}
	}
	return true
}

// ------------------------------------------------------------------------------------------------ the buttons

func (w *wizard) command(id int, code int, ctl uintptr) {
	switch {
	case ctl == w.next && code == BN_CLICKED, id == idNext && ctl == 0:
		if enabled, _, _ := pIsWindowEnabled.Call(w.next); enabled != 0 {
			w.onNext()
		}
	case ctl == w.back && code == BN_CLICKED:
		w.onBack()
	case id == IDCANCEL:
		w.onCancel()
	case ctl == w.getPython:
		pShellExecuteW.Call(w.hwnd, uintptr(unsafe.Pointer(wstr("open"))),
			uintptr(unsafe.Pointer(wstr("https://www.python.org/downloads/windows/"))), 0, 0, SW_SHOWNORMAL)
	case ctl == w.lookAgain:
		setText(w.pythonText, "Looking for Python…")
		enable(w.lookAgain, false)
		go func() {
			py, _ := w.p.FindPython()
			w.mu.Lock()
			w.s.Python = py
			w.mu.Unlock()
			post(w.hwnd, wmPython, 0, 0)
		}()
	case ctl == w.folderBrowse:
		if chosen := w.chooseFolder("The folder Sluka Desktop goes into", windowText(w.folderEdit)); chosen != "" {
			if there := InstallIn(chosen); !there.Exists() && FolderHasThings(chosen) &&
				!strings.EqualFold(filepath.Base(chosen), AppName) {
				chosen = filepath.Join(chosen, AppName)
			}
			setText(w.folderEdit, chosen)
		}
	case ctl == w.folderEdit && code == EN_CHANGE:
		w.describeFolder()
	case ctl == w.extBrowse:
		if chosen := w.chooseFile("Your Sluka extension's zip", w.p.Downloads()); chosen != "" {
			setText(w.extEdit, chosen)
		}
	case ctl == w.extEdit && code == EN_CHANGE:
		w.describeExtension()
	case ctl == w.zipBrowse:
		if chosen := w.chooseFile("A newer Sluka extension, or Sluka Desktop", w.p.Downloads()); chosen != "" {
			setText(w.zipEdit, chosen)
		}
	case ctl == w.zipEdit && code == EN_CHANGE:
		w.describeZip()
		w.buttons()
	case ctl == w.otherFolder:
		if chosen := w.chooseFolder("The folder of another Sluka Desktop", w.current.Root); chosen != "" {
			if there := InstallIn(chosen); there.Exists() {
				w.current = there
				w.prepareMaintain()
				w.showPage(pageMaintain)
			} else {
				w.ask(fmt.Sprintf("There is no %s in %s (no app\\run.py in it).", AppName, chosen), MB_OK|MB_ICONWARNING)
			}
		}
	case ctl == w.radUpdate || ctl == w.radZip || ctl == w.radLinks || ctl == w.radRemove:
		if code == BN_CLICKED {
			w.pick(ctl)
		}
	case ctl == w.accept && code == BN_CLICKED:
		w.buttons()
	case ctl == w.termsLink && code == BN_CLICKED: // (STN_CLICKED, as a static says it)
		pShellExecuteW.Call(w.hwnd, uintptr(unsafe.Pointer(wstr("open"))), uintptr(unsafe.Pointer(wstr(TermsURL))), 0, 0,
			SW_SHOWNORMAL)
	}
}

func (w *wizard) onBack() {
	switch w.page {
	case pageWelcome, pageMaintain:
		w.showPage(pageLicense)
	case pageFolder:
		w.showPage(pageWelcome)
	case pageOptions:
		w.showPage(pageFolder)
	case pageFinish:
		if w.failed {
			w.failed = false
			w.showPage(w.previous)
		}
	}
}

func (w *wizard) onCancel() {
	if w.working {
		return
	}
	switch w.page {
	case pageFinish, pageNothing:
		pDestroyWindow.Call(w.hwnd)
		return
	}
	if w.ask("Leave "+AppName+" Setup?", MB_YESNO|MB_ICONQUEST|MB_DEFBUTTON2) == IDYES {
		pDestroyWindow.Call(w.hwnd)
	}
}

func (w *wizard) onNext() {
	switch w.page {
	case pageLicense:
		if !checked(w.accept) {
			return
		}
		if w.mode == "maintain" {
			w.showPage(pageMaintain)
		} else {
			w.showPage(pageWelcome)
		}
	case pageWelcome:
		if !w.pythonFound {
			return
		}
		w.describeFolder()
		w.showPage(pageFolder)
	case pageFolder:
		folder := strings.TrimSpace(strings.Trim(windowText(w.folderEdit), `"`))
		there := InstallIn(folder)
		if !there.Exists() {
			if problem := w.s.FolderProblem(folder); problem != "" {
				w.ask(problem, MB_OK|MB_ICONWARNING)
				return
			}
			if FolderHasThings(folder) {
				inner := filepath.Join(folder, AppName)
				if w.ask(fmt.Sprintf("%s has other things in it. Put %s into %s instead?", folder, AppName, inner),
					MB_YESNO|MB_ICONQUEST) != IDYES {
					return
				}
				setText(w.folderEdit, inner)
				there = Install{inner}
				if problem := w.s.FolderProblem(inner); problem != "" {
					w.ask(problem, MB_OK|MB_ICONWARNING)
					return
				}
			}
			if strings.Contains(strings.ToLower(folder), "onedrive") &&
				w.ask("That folder is in OneDrive, which copies Sluka's data to the cloud as it changes, and may hold its "+
					"files meanwhile. Put Sluka Desktop there all the same?", MB_YESNO|MB_ICONWARNING|MB_DEFBUTTON2) != IDYES {
				return
			}
		}
		w.target = there
		if there.Exists() {
			desktop, menu := w.s.HasLinks(there)
			setChecked(w.optDesktop, desktop || !w.anyLinks(there))
			setChecked(w.optMenu, menu || !w.anyLinks(there))
			if there.ExtensionVersion() != "" {
				if path := strings.TrimSpace(windowText(w.extEdit)); path != "" {
					if f, err := Describe(path); err != nil || CompareVersions(f.Version, there.ExtensionVersion()) <= 0 {
						setText(w.extEdit, "")
					}
				}
			}
		}
		w.describeExtension()
		w.showPage(pageOptions)
	case pageOptions:
		ext := strings.TrimSpace(strings.Trim(windowText(w.extEdit), `"`))
		if ext != "" {
			found, err := ExtensionIn(ext)
			if err != nil || !found.Sluka {
				w.ask("The extension's zip is not the Sluka extension's Chrome edition. Choose another, or leave it empty "+
					"to add it later.", MB_OK|MB_ICONWARNING)
				return
			}
		}
		if w.target.Exists() && !w.waitClosed(w.target) {
			return
		}
		choices := Choices{Desktop: checked(w.optDesktop), StartMenu: checked(w.optMenu),
			Anki: checked(w.optAnki) && !w.off[w.optAnki], Extension: ext}
		w.waitPython()
		target := w.target
		w.work("install", pageOptions, func(r Reporter) (Result, error) { return w.s.Install(target, choices, r) })
	case pageMaintain:
		w.applyMaintain()
	case pageUninstall:
		if !w.waitClosed(w.current) {
			return
		}
		keep := checked(w.unKeep)
		cur := w.current
		w.waitPython()
		w.work("remove", pageUninstall, func(r Reporter) (Result, error) { return w.s.Uninstall(cur, keep, r) })
	case pageFinish:
		if checked(w.finStart) && !w.off[w.finStart] {
			i := w.result.Install
			var links []string
			for _, which := range []string{"programs", "desktop"} {
				if folder := w.p.ShellFolder(which); folder != "" {
					path := filepath.Join(folder, "Sluka.lnk")
					if data, err := os.ReadFile(path); err == nil && LinkLeadsTo(data, i.Root, `\`) {
						links = append(links, path)
					}
				}
			}
			if err := w.p.Launch(w.python(), i, links); err != nil {
				w.ask(fmt.Sprintf("%s could not be started (%v). Start it from its shortcut, or Sluka.cmd in %s.",
					AppName, err, i.Root), MB_OK|MB_ICONWARNING)
			}
		}
		pDestroyWindow.Call(w.hwnd)
	case pageNothing:
		pDestroyWindow.Call(w.hwnd)
	}
}

func (w *wizard) anyLinks(i Install) bool {
	d, m := w.s.HasLinks(i)
	return d || m
}

func (w *wizard) applyMaintain() {
	cur := w.current
	w.waitPython()
	switch {
	case checked(w.radUpdate) && w.s.Payload != nil:
		if CompareVersions(w.s.Payload.Version, cur.Version()) < 0 && w.ask(fmt.Sprintf("Put %s %s in place of the newer %s?",
			AppName, w.s.Payload.Version, cur.Version()), MB_YESNO|MB_ICONQUEST|MB_DEFBUTTON2) != IDYES {
			return
		}
		if !w.waitClosed(cur) {
			return
		}
		payload := w.s.Payload
		w.work("update", pageMaintain, func(r Reporter) (Result, error) { return w.s.Update(payload, cur, r, "") })
	case checked(w.radZip):
		path := strings.TrimSpace(strings.Trim(windowText(w.zipEdit), `"`))
		d, err := Describe(path)
		if err != nil {
			w.ask(err.Error()+".", MB_OK|MB_ICONWARNING)
			return
		}
		have := cur.Version()
		if d.Kind == "extension" {
			have = cur.ExtensionVersion()
			if ext, err := ExtensionIn(path); err == nil && !ext.Sluka &&
				w.ask(d.Words+" does not look like the Sluka extension's Chrome edition. Put it in all the same?",
					MB_YESNO|MB_ICONWARNING|MB_DEFBUTTON2) != IDYES {
				return
			}
		}
		if have != "" && CompareVersions(d.Version, have) <= 0 {
			what := "the one you have"
			if CompareVersions(d.Version, have) < 0 {
				what = "older than yours (" + have + ")"
			}
			if w.ask(fmt.Sprintf("%s is %s. Put it in all the same?", d.Words, what), MB_YESNO|MB_ICONQUEST|MB_DEFBUTTON2) != IDYES {
				return
			}
		}
		if (d.Kind == "extension" && w.python() == nil) || !w.waitClosed(cur) {
			if d.Kind == "extension" && w.python() == nil {
				w.ask(ErrNoPython.Error()+".", MB_OK|MB_ICONWARNING)
			}
			return
		}
		w.work("zip", pageMaintain, func(r Reporter) (Result, error) { return w.s.UpdateFromZip(path, cur, r) })
	case checked(w.radLinks):
		if w.python() == nil {
			w.ask(ErrNoPython.Error()+".", MB_OK|MB_ICONWARNING)
			return
		}
		desktop, menu := checked(w.linkDesktop), checked(w.linkMenu)
		w.work("links", pageMaintain, func(r Reporter) (Result, error) { return w.s.Shortcuts(cur, desktop, menu, r) })
	case checked(w.radRemove):
		keep := checked(w.keepData)
		if w.ask(fmt.Sprintf("Uninstall %s %s, in %s?", AppName, cur.Version(), cur.Root), MB_YESNO|MB_ICONQUEST|MB_DEFBUTTON2) != IDYES {
			return
		}
		if Inside(w.s.Self, cur.Root) && !w.opts.tempCopy {
			// (This setup is in the folder it takes away: a copy of it elsewhere does it.)
			if relaunchUninstall(w.s.Self, cur.Root, keep) {
				pDestroyWindow.Call(w.hwnd)
				return
			}
		}
		if !w.waitClosed(cur) {
			return
		}
		w.work("remove", pageMaintain, func(r Reporter) (Result, error) { return w.s.Uninstall(cur, keep, r) })
	}
}

// ------------------------------------------------------------------------------------------------ the work

var progressTitles = map[string]string{"install": "Installing Sluka Desktop", "update": "Updating Sluka Desktop",
	"zip": "Updating from the zip", "links": "Making the shortcuts", "remove": "Uninstalling Sluka Desktop"}

var doneTitles = map[string]string{"install": "Sluka Desktop is installed", "update": "Sluka Desktop is updated",
	"zip": "Updated", "links": "The shortcuts are as you chose", "remove": "Sluka Desktop is uninstalled"}

func (w *wizard) work(action string, from page, fn func(Reporter) (Result, error)) {
	w.action, w.previous, w.working, w.failed = action, from, true, false
	w.logLines = nil
	setText(w.logBox, "")
	w.setProgress(0)
	setText(w.status, "")
	w.showPage(pageProgress)
	w.head = [2]string{progressTitles[action] + "…", "This takes a moment."}
	pInvalidateRect.Call(w.hwnd, 0, 1)
	go func() {
		var res Result
		var err error
		func() {
			defer func() {
				if p := recover(); p != nil {
					err = fmt.Errorf("Setup itself stopped on an error: %v", p)
				}
			}()
			res, err = fn(w)
		}()
		w.mu.Lock()
		w.result, w.err = res, err
		w.mu.Unlock()
		post(w.hwnd, wmWorkDone, 0, 0)
	}()
}

func (w *wizard) progressNow() {
	w.mu.Lock()
	status, done, total, lines := w.pending.status, w.pending.done, w.pending.total, w.pending.log
	w.pending.log, w.pending.posted = nil, false
	w.mu.Unlock()
	if status != "" && status != windowText(w.status) {
		setText(w.status, status)
	}
	if total > 0 {
		w.setProgress(int(done * 1000 / total))
	}
	if len(lines) > 0 {
		w.logLines = append(w.logLines, lines...)
		text := strings.Join(lines, "\r\n") + "\r\n"
		end := ^uintptr(0)
		send(w.logBox, EM_SETSEL, end, end)
		pSendMessageW.Call(w.logBox, EM_REPLACESEL, 0, uintptr(unsafe.Pointer(wstr(text))))
	}
}

func (w *wizard) workDone() {
	w.progressNow()
	w.mu.Lock()
	res, err := w.result, w.err
	w.mu.Unlock()
	w.working = false
	var text []string
	if err != nil {
		w.failed = true
		w.head = [2]string{"Setup could not finish", "Nothing more was done."}
		text = append(text, sentence(err.Error()))
		if n := len(w.logLines); n > 0 {
			text = append(text, "", "Its last notes:")
			text = append(text, w.logLines[max(0, n-6):]...)
		}
		text = append(text, "", "Back: try again.")
	} else {
		w.head = [2]string{doneTitles[w.action], res.Install.Root}
		text = append(text, res.Lines...)
		if len(res.Warnings) > 0 {
			text = append(text, "")
			for _, warning := range res.Warnings {
				text = append(text, "! "+warning)
			}
		}
	}
	setText(w.finText, strings.Join(text, "\r\n"))
	startable := err == nil && res.CanStart && (w.action == "install" || w.action == "update" || w.action == "zip")
	w.off[w.finStart] = !startable
	setChecked(w.finStart, startable && !Running(res.Install))
	if w.action == "remove" && err == nil {
		w.current = Install{}
	}
	// (back to the page the work began on: there, its log is under "Back")
	w.page = pageFinish
	w.showFinish()
}

func (w *wizard) showFinish() {
	for p, list := range w.pages {
		if p == pageFooter {
			continue
		}
		for _, h := range list {
			show(h, p == pageFinish && !w.off[h])
		}
	}
	w.buttons()
	pInvalidateRect.Call(w.hwnd, 0, 1)
	pSetFocus.Call(w.next)
}

func sentence(text string) string {
	if text == "" {
		return text
	}
	text = strings.ToUpper(text[:1]) + text[1:]
	if !strings.HasSuffix(text, ".") {
		text += "."
	}
	return text
}

// relaunchUninstall: a copy of this setup, out of the app's folder, started to uninstall it.
func relaunchUninstall(self, root string, keep bool) bool {
	copyPath := filepath.Join(os.TempDir(), fmt.Sprintf("Sluka-Desktop-Uninstall-%d.exe", os.Getpid()))
	if WriteStub(self, copyPath) != nil {
		return false
	}
	args := []string{"/uninstall", root, "/temp-copy"}
	if keep {
		args = append(args, "/keep")
	}
	cmd := exec.Command(copyPath, args...)
	cmd.Dir = os.TempDir()
	return cmd.Start() == nil
}

// ------------------------------------------------------------------------------------------------ painting

func (w *wizard) paintBackground(hdc uintptr) {
	var rc rect
	pGetClientRect.Call(w.hwnd, uintptr(unsafe.Pointer(&rc)))
	pFillRect.Call(hdc, uintptr(unsafe.Pointer(&rc)), w.bgBrush)
	line := rect{0, int32(w.px(headerH)), rc.Right, int32(w.px(headerH)) + 1}
	pFillRect.Call(hdc, uintptr(unsafe.Pointer(&line)), w.lineBrush)
	foot := rect{0, rc.Bottom - int32(w.px(footerH)), rc.Right, rc.Bottom}
	pFillRect.Call(hdc, uintptr(unsafe.Pointer(&foot)), w.footerBrush)
	sep := rect{0, foot.Top, rc.Right, foot.Top + 1}
	pFillRect.Call(hdc, uintptr(unsafe.Pointer(&sep)), w.lineBrush)
}

func (w *wizard) paintHeader(hdc uintptr) {
	var rc rect
	pGetClientRect.Call(w.hwnd, uintptr(unsafe.Pointer(&rc)))
	pSetBkMode.Call(hdc, TRANSPARENT)
	old, _, _ := pSelectObject.Call(hdc, w.title)
	pSetTextColor.Call(hdc, colorText)
	r := rect{int32(w.px(margin)), int32(w.px(14)), rc.Right - int32(w.px(margin+56)), int32(w.px(42))}
	text, _ := syscall.UTF16FromString(w.head[0])
	pDrawTextW.Call(hdc, uintptr(unsafe.Pointer(&text[0])), ^uintptr(0), uintptr(unsafe.Pointer(&r)),
		DT_LEFT|DT_SINGLELINE|DT_VCENTER|DT_END_ELLIPSIS|DT_NOPREFIX)
	pSelectObject.Call(hdc, w.font)
	pSetTextColor.Call(hdc, colorDim)
	r = rect{int32(w.px(margin)), int32(w.px(42)), rc.Right - int32(w.px(margin+56)), int32(w.px(64))}
	sub, _ := syscall.UTF16FromString(w.head[1])
	pDrawTextW.Call(hdc, uintptr(unsafe.Pointer(&sub[0])), ^uintptr(0), uintptr(unsafe.Pointer(&r)),
		DT_LEFT|DT_SINGLELINE|DT_VCENTER|DT_END_ELLIPSIS|DT_NOPREFIX)
	pSelectObject.Call(hdc, old)
	if w.icon != 0 {
		size := w.px(40)
		pDrawIconEx.Call(hdc, uintptr(int(rc.Right)-w.px(margin)-size), uintptr(w.px(16)), w.icon, uintptr(size), uintptr(size), 0, 0, DI_NORMAL)
	}
}

// ------------------------------------------------------------------------------------------------ messages

func (w *wizard) wndProc(hwnd, msg, wparam, lparam uintptr) (result uintptr) {
	defer func() {
		if p := recover(); p != nil {
			messageBox(hwnd, fmt.Sprintf("Setup met an error it did not expect:\n\n%v", p), AppName+" Setup", MB_OK|MB_ICONERROR)
			result = 0
		}
	}()
	if w.hwnd == 0 {
		w.hwnd = hwnd
	}
	switch uint32(msg) {
	case WM_ERASEBKGND:
		w.paintBackground(wparam)
		return 1
	case WM_PRINTCLIENT:
		w.paintBackground(wparam)
		w.paintHeader(wparam)
		return 0
	case WM_PAINT:
		var ps paintStruct
		hdc, _, _ := pBeginPaint.Call(hwnd, uintptr(unsafe.Pointer(&ps)))
		w.paintHeader(hdc)
		pEndPaint.Call(hwnd, uintptr(unsafe.Pointer(&ps)))
		return 0
	case WM_CTLCOLORSTATIC, WM_CTLCOLORBTN, WM_CTLCOLOREDIT:
		bg, brush := w.bgOf(lparam)
		color := uint32(colorText)
		if w.fields[lparam] {
			// (a text box: typed in, read only, or not for now -- a read-only or disabled one asks as a static does)
			bg, brush = colorField, w.fieldBrush
			if enabled, _, _ := pIsWindowEnabled.Call(lparam); enabled == 0 {
				color = colorOff
			}
		}
		if c, ok := w.colors[lparam]; ok {
			color = c
		}
		pSetBkColor.Call(wparam, uintptr(bg))
		pSetTextColor.Call(wparam, uintptr(color))
		return brush
	case WM_DRAWITEM:
		if di := *(**drawItemStruct)(unsafe.Pointer(&lparam)); di.HwndItem == w.bar && w.bar != 0 {
			w.drawProgress(di)
			return 1
		}
	case WM_NOTIFY:
		nm := *(**nmCustomDraw)(unsafe.Pointer(&lparam))
		if nm.Code == nmCustomDrawCode {
			return w.customDraw(nm)
		}
	case WM_SETCURSOR:
		if wparam == w.termsLink && w.termsLink != 0 {
			hand, _, _ := pLoadCursorW.Call(0, IDC_HAND)
			pSetCursor.Call(hand)
			return 1
		}
	case WM_COMMAND:
		w.command(int(lo(wparam)), int(hi(wparam)), lparam)
		return 0
	case DM_GETDEFID:
		return uintptr(DC_HASDEFID)<<16 | idNext
	case WM_CLOSE:
		w.onCancel()
		return 0
	case WM_DESTROY:
		pPostQuitMessage.Call(0)
		return 0
	case wmWorkProgress:
		w.progressNow()
		return 0
	case wmWorkDone:
		w.workDone()
		return 0
	case wmPython:
		enable(w.lookAgain, true)
		w.showPython()
		return 0
	}
	r, _, _ := pDefWindowProcW.Call(hwnd, msg, wparam, lparam)
	return r
}
