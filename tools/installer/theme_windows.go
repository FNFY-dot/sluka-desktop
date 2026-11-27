// SPDX-License-Identifier: LicenseRef-Sluka
// Copyright (c) 2026 Sluka. Part of Sluka Desktop's Setup; see LICENSE.txt.

package main

// The setup's look: Sluka's own dark colours (those of its pages' dark theme), a black title bar, and Windows' own
// controls painted over in them -- the main button in Sluka's blue, check boxes and round buttons filled with it when
// on.  The controls still do all their work themselves (keys, focus, clicks, which one of a group is on); only how
// they look is Sluka's: drawn when Windows asks the window to (NM_CUSTOMDRAW), or coloured when it asks for colours.

import (
	"syscall"
	"unsafe"
)

var (
	uxtheme = syscall.NewLazyDLL("uxtheme.dll")
	dwmapi  = syscall.NewLazyDLL("dwmapi.dll")

	pSetWindowTheme        = uxtheme.NewProc("SetWindowTheme")
	pDwmSetWindowAttribute = dwmapi.NewProc("DwmSetWindowAttribute")

	pCreatePen         = gdi32.NewProc("CreatePen")
	pRoundRect         = gdi32.NewProc("RoundRect")
	pEllipse           = gdi32.NewProc("Ellipse")
	pPolyline          = gdi32.NewProc("Polyline")
	pGetStockObject    = gdi32.NewProc("GetStockObject")
	pDrawFocusRect     = user32.NewProc("DrawFocusRect")
	pGetWindowLongPtrW = user32.NewProc("GetWindowLongPtrW")
	pSetCursor         = user32.NewProc("SetCursor")
)

// Sluka's dark theme (its pages' --bg, --surface-1 to 3, --primary, --accent-fill, --accent-text), as Windows writes
// a colour: 0x00BBGGRR.
const (
	colorBg         = 0x101111 // #111110, the window
	colorFooter     = 0x181919 // #191918, under the buttons
	colorField      = 0x212222 // #222221, where text is typed or read
	colorRaised     = 0x282A2A // #2A2A28, a button
	colorRaisedHot  = 0x333535 // #353533, a button pointed at
	colorRaisedDown = 0x212323 // #232321, a button pressed
	colorLine       = 0x2B2E2E // #2E2E2B, the lines between the parts
	colorText       = 0xEBF0F2 // #F2F0EB
	colorDim        = 0x9AA1A3 // #A3A19A, what is said beside
	colorOff        = 0x656A6B // #6B6A65, what cannot be used now
	colorBox        = 0x82888A // #8A8882, an empty check box's edge
	colorAccent     = 0xEB6F2F // #2F6FEB, Sluka's blue
	colorAccentHot  = 0xF0824A // #4A82F0
	colorAccentDown = 0xD1622A // #2A62D1
	colorAccentOff  = 0x6E4733 // #33476E, on, but cannot be changed now
	colorLink       = 0xFF9B6B // #6B9BFF
	colorError      = 0x727BFF // #FF7B72
	colorWhite      = 0xFFFFFF
)

const (
	dwmaDarkModeOld  = 19 // DWMWA_USE_IMMERSIVE_DARK_MODE, as Windows 10 before 20H1 numbered it
	dwmaDarkMode     = 20
	dwmaBorderColor  = 34 // Windows 11
	dwmaCaptionColor = 35
	dwmaTextColor    = 36

	WM_SETCURSOR     = 0x0020
	WM_NOTIFY        = 0x004E
	nmCustomDrawCode = -12 // NM_CUSTOMDRAW
	CDDS_PREPAINT    = 0x1
	CDRF_DODEFAULT   = 0x0
	CDRF_SKIPDEFAULT = 0x4
	CDIS_SELECTED    = 0x1
	CDIS_DISABLED    = 0x4
	CDIS_FOCUS       = 0x10
	CDIS_HOT         = 0x40
	CDIS_SHOWKBCUES  = 0x200

	BS_TYPEMASK        = 0xF
	BS_CHECKBOX        = 0x2
	BS_AUTORADIOBUTTON = 0x9
	BST_CHECKED        = 1
	DT_CENTER          = 0x1
	DT_CALCRECT        = 0x400
	DT_HIDEPREFIX      = 0x100000
	PS_SOLID           = 0
	NULL_BRUSH         = 5
	NULL_PEN           = 8
	IDC_HAND           = 32649
	SS_NOTIFY          = 0x100
	SS_OWNERDRAW       = 0xD
	WM_DRAWITEM        = 0x002B
	gwlStyle           = ^uintptr(15) // GWL_STYLE (-16)
)

// NMCUSTOMDRAW, as Windows lays it out for 64-bit programs.
type nmCustomDraw struct {
	HwndFrom  uintptr
	IdFrom    uintptr
	Code      int32
	_         uint32
	DrawStage uint32
	_         uint32
	Hdc       uintptr
	Rc        rect
	ItemSpec  uintptr
	ItemState uint32
	_         uint32
	ItemParam uintptr
}

type point struct{ X, Y int32 }

var _ = [1]struct{}{}[unsafe.Sizeof(nmCustomDraw{})-80]

// darkTitleBar: the window's title bar black, as Sluka's own windows are -- whatever colour Windows' settings give
// title bars (an accent colour on them included, from Windows 11 on).  Where Windows cannot, nothing happens.
func darkTitleBar(hwnd uintptr) {
	if pDwmSetWindowAttribute.Find() != nil {
		return
	}
	on := int32(1)
	if r, _, _ := pDwmSetWindowAttribute.Call(hwnd, dwmaDarkMode, uintptr(unsafe.Pointer(&on)), 4); r != 0 {
		pDwmSetWindowAttribute.Call(hwnd, dwmaDarkModeOld, uintptr(unsafe.Pointer(&on)), 4)
	}
	for _, set := range [][2]uint32{{dwmaCaptionColor, colorBg}, {dwmaTextColor, colorText}, {dwmaBorderColor, colorLine}} {
		color := set[1]
		pDwmSetWindowAttribute.Call(hwnd, uintptr(set[0]), uintptr(unsafe.Pointer(&color)), 4)
	}
}

// darkControl: a control drawn by Windows in its own dark style (its edge and its scroll bar), where Windows has one.
func darkControl(h uintptr, theme string) {
	if pSetWindowTheme.Find() != nil {
		return
	}
	pSetWindowTheme.Call(h, uintptr(unsafe.Pointer(wstr(theme))), 0)
}

// DRAWITEMSTRUCT, as Windows lays it out for 64-bit programs.
type drawItemStruct struct {
	CtlType, CtlID, ItemID, ItemAction, ItemState uint32
	_                                             uint32
	HwndItem                                      uintptr
	Hdc                                           uintptr
	RcItem                                        rect
	ItemData                                      uintptr
}

var _ = [1]struct{}{}[unsafe.Sizeof(drawItemStruct{})-64]

// setProgress: how far the work is, in thousandths, shown by the progress bar.
func (w *wizard) setProgress(thousandths int) {
	thousandths = min(max(thousandths, 0), 1000)
	if thousandths == w.progress {
		return
	}
	w.progress = thousandths
	pInvalidateRect.Call(w.bar, 0, 0)
}

// drawProgress: the progress bar, a rounded track that Sluka's blue fills from the left.
func (w *wizard) drawProgress(di *drawItemStruct) {
	r, hdc := di.RcItem, di.Hdc
	solid(hdc, r, colorBg)
	radius := int(r.Bottom - r.Top)
	shape(hdc, r, radius, colorField, colorLine, max(1, w.px(1)), false)
	width := int32(int64(r.Right-r.Left) * int64(w.progress) / 1000)
	if width <= 0 {
		return
	}
	width = max(width, r.Bottom-r.Top) // (never thinner than it is tall, so that its ends stay round)
	shape(hdc, rect{r.Left, r.Top, r.Left + width, r.Bottom}, radius, colorAccent, 0, 0, false)
}

func solid(hdc uintptr, r rect, color uint32) {
	brush, _, _ := pCreateSolidBrush.Call(uintptr(color))
	pFillRect.Call(hdc, uintptr(unsafe.Pointer(&r)), brush)
	pDeleteObject.Call(brush)
}

// shape: a rounded rectangle (or, round, a circle) filled with one colour and edged with another (width 0: none).
func shape(hdc uintptr, r rect, radius int, fill, edge uint32, width int, round bool) {
	brush, _, _ := pCreateSolidBrush.Call(uintptr(fill))
	pen, _, _ := pGetStockObject.Call(NULL_PEN)
	if width > 0 {
		pen, _, _ = pCreatePen.Call(PS_SOLID, uintptr(width), uintptr(edge))
	}
	oldBrush, _, _ := pSelectObject.Call(hdc, brush)
	oldPen, _, _ := pSelectObject.Call(hdc, pen)
	right, bottom := r.Right, r.Bottom
	if width == 0 {
		right, bottom = right+1, bottom+1 // (with no pen, Windows fills one pixel short of the right and the bottom)
	}
	if round {
		pEllipse.Call(hdc, uintptr(r.Left), uintptr(r.Top), uintptr(right), uintptr(bottom))
	} else {
		pRoundRect.Call(hdc, uintptr(r.Left), uintptr(r.Top), uintptr(right), uintptr(bottom), uintptr(radius), uintptr(radius))
	}
	pSelectObject.Call(hdc, oldBrush)
	pSelectObject.Call(hdc, oldPen)
	pDeleteObject.Call(brush)
	if width > 0 {
		pDeleteObject.Call(pen)
	}
}

// ring: a rounded rectangle's edge alone.
func ring(hdc uintptr, r rect, radius int, color uint32, width int) {
	pen, _, _ := pCreatePen.Call(PS_SOLID, uintptr(width), uintptr(color))
	brush, _, _ := pGetStockObject.Call(NULL_BRUSH)
	oldBrush, _, _ := pSelectObject.Call(hdc, brush)
	oldPen, _, _ := pSelectObject.Call(hdc, pen)
	pRoundRect.Call(hdc, uintptr(r.Left), uintptr(r.Top), uintptr(r.Right), uintptr(r.Bottom), uintptr(radius), uintptr(radius))
	pSelectObject.Call(hdc, oldBrush)
	pSelectObject.Call(hdc, oldPen)
	pDeleteObject.Call(pen)
}

func writeText(hdc uintptr, text string, r *rect, color uint32, font uintptr, flags uintptr) {
	pSetBkMode.Call(hdc, TRANSPARENT)
	pSetTextColor.Call(hdc, uintptr(color))
	old, _, _ := pSelectObject.Call(hdc, font)
	u, _ := syscall.UTF16FromString(text)
	pDrawTextW.Call(hdc, uintptr(unsafe.Pointer(&u[0])), ^uintptr(0), uintptr(unsafe.Pointer(r)), flags)
	pSelectObject.Call(hdc, old)
}

// bgOf: the colour a control sits on (and its brush).
func (w *wizard) bgOf(h uintptr) (uint32, uintptr) {
	if w.footer[h] {
		return colorFooter, w.footerBrush
	}
	return colorBg, w.bgBrush
}

// customDraw: a button of the setup's (a push button, a check box, a round button) drawn in Sluka's colours, when
// Windows asks the window to draw it.  Anything else is left to Windows.
func (w *wizard) customDraw(nm *nmCustomDraw) uintptr {
	if nm.DrawStage != CDDS_PREPAINT || !w.mine[nm.HwndFrom] {
		return CDRF_DODEFAULT
	}
	style, _, _ := pGetWindowLongPtrW.Call(nm.HwndFrom, gwlStyle)
	switch style & BS_TYPEMASK {
	case BS_PUSHBUTTON, BS_DEFPUSHBUTTON:
		w.drawPush(nm)
	case BS_CHECKBOX, BS_AUTOCHECKBOX:
		w.drawCheck(nm, false)
	case BS_RADIOBUTTON, BS_AUTORADIOBUTTON:
		w.drawCheck(nm, true)
	default:
		return CDRF_DODEFAULT
	}
	return CDRF_SKIPDEFAULT
}

func prefixFlags(state uint32) uintptr {
	if state&CDIS_SHOWKBCUES == 0 {
		return DT_HIDEPREFIX // (the letters for the keys underlined only once the keyboard is used, as Windows does)
	}
	return 0
}

func (w *wizard) drawPush(nm *nmCustomDraw) {
	h, hdc, r, state := nm.HwndFrom, nm.Hdc, nm.Rc, nm.ItemState
	bg, _ := w.bgOf(h)
	solid(hdc, r, bg)
	main := h == w.next
	fill, text := uint32(colorRaised), uint32(colorText)
	switch {
	case state&CDIS_DISABLED != 0:
		fill, text = colorRaised, colorOff
	case main && state&CDIS_SELECTED != 0:
		fill, text = colorAccentDown, colorWhite
	case main && state&CDIS_HOT != 0:
		fill, text = colorAccentHot, colorWhite
	case main:
		fill, text = colorAccent, colorWhite
	case state&CDIS_SELECTED != 0:
		fill = colorRaisedDown
	case state&CDIS_HOT != 0:
		fill = colorRaisedHot
	}
	radius := w.px(8)
	shape(hdc, r, radius, fill, 0, 0, false)
	if state&CDIS_FOCUS != 0 && state&CDIS_SHOWKBCUES != 0 {
		edge := uint32(colorLink)
		if main {
			edge = colorWhite
		}
		in := rect{r.Left + 1, r.Top + 1, r.Right - 1, r.Bottom - 1}
		ring(hdc, in, radius, edge, max(1, w.px(1)))
	}
	label := r
	writeText(hdc, windowText(h), &label, text, w.font, DT_CENTER|DT_VCENTER|DT_SINGLELINE|prefixFlags(state))
}

func (w *wizard) drawCheck(nm *nmCustomDraw, round bool) {
	h, hdc, r, state := nm.HwndFrom, nm.Hdc, nm.Rc, nm.ItemState
	bg, _ := w.bgOf(h)
	solid(hdc, r, bg)
	on := send(h, BM_GETCHECK, 0, 0) == BST_CHECKED
	off := state&CDIS_DISABLED != 0
	size := int32(w.px(16))
	top := r.Top + (r.Bottom-r.Top-size)/2
	box := rect{r.Left, top, r.Left + size, top + size}
	edgeWidth := max(1, w.px(1))
	switch {
	case on:
		fill := uint32(colorAccent)
		switch {
		case off:
			fill = colorAccentOff
		case state&CDIS_SELECTED != 0:
			fill = colorAccentDown
		case state&CDIS_HOT != 0:
			fill = colorAccentHot
		}
		shape(hdc, box, w.px(5), fill, 0, 0, round)
		mark := uint32(colorWhite)
		if off {
			mark = colorDim
		}
		if round {
			d := size * 3 / 8
			dot := rect{box.Left + (size-d)/2, box.Top + (size-d)/2, box.Left + (size-d)/2 + d, box.Top + (size-d)/2 + d}
			shape(hdc, dot, 0, mark, 0, 0, true)
		} else {
			w.tick(hdc, box, mark)
		}
	default:
		edge, fill := uint32(colorBox), uint32(colorField)
		switch {
		case off:
			edge = colorRaisedHot
		case state&CDIS_HOT != 0:
			edge = colorDim
		}
		shape(hdc, box, w.px(5), fill, edge, edgeWidth, round)
	}
	color := uint32(colorText)
	if off {
		color = colorOff
	}
	label := rect{box.Right + int32(w.px(8)), r.Top, r.Right, r.Bottom}
	flags := DT_LEFT | DT_VCENTER | DT_SINGLELINE | DT_END_ELLIPSIS | prefixFlags(state)
	writeText(hdc, windowText(h), &label, color, w.font, flags)
	if state&CDIS_FOCUS != 0 && state&CDIS_SHOWKBCUES != 0 {
		measured := label
		writeText(hdc, windowText(h), &measured, color, w.font, flags|DT_CALCRECT)
		height := measured.Bottom - measured.Top
		focus := rect{label.Left - 2, r.Top + (r.Bottom-r.Top-height)/2 - 1, measured.Right + 2, r.Top + (r.Bottom-r.Top-height)/2 + height + 1}
		pSetTextColor.Call(hdc, colorText)
		pSetBkColor.Call(hdc, uintptr(bg))
		pDrawFocusRect.Call(hdc, uintptr(unsafe.Pointer(&focus)))
	}
}

// tick: a check box's mark.
func (w *wizard) tick(hdc uintptr, box rect, color uint32) {
	size := float64(box.Right - box.Left)
	at := func(x, y float64) point {
		return point{box.Left + int32(x*size/16+0.5), box.Top + int32(y*size/16+0.5)}
	}
	pts := [3]point{at(4, 8.5), at(7, 11.5), at(12.5, 5)}
	pen, _, _ := pCreatePen.Call(PS_SOLID, uintptr(max(2, w.px(2))), uintptr(color))
	old, _, _ := pSelectObject.Call(hdc, pen)
	pPolyline.Call(hdc, uintptr(unsafe.Pointer(&pts[0])), 3)
	pSelectObject.Call(hdc, old)
	pDeleteObject.Call(pen)
}
