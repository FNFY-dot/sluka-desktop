// SPDX-License-Identifier: LicenseRef-Sluka
// Copyright (c) 2026 Sluka. Part of Sluka Desktop Setup; see LICENSE.txt.
package main

// What of Windows' own functions the setup calls, and the structures they take (laid out as Windows' headers lay them
// out for 64-bit programs).

import (
	"syscall"
	"unsafe"
)

var (
	user32   = syscall.NewLazyDLL("user32.dll")
	gdi32    = syscall.NewLazyDLL("gdi32.dll")
	kernel32 = syscall.NewLazyDLL("kernel32.dll")
	comctl32 = syscall.NewLazyDLL("comctl32.dll")
	shell32  = syscall.NewLazyDLL("shell32.dll")
	comdlg32 = syscall.NewLazyDLL("comdlg32.dll")
	ole32    = syscall.NewLazyDLL("ole32.dll")
	advapi32 = syscall.NewLazyDLL("advapi32.dll")

	pRegisterClassExW     = user32.NewProc("RegisterClassExW")
	pCreateWindowExW      = user32.NewProc("CreateWindowExW")
	pDefWindowProcW       = user32.NewProc("DefWindowProcW")
	pDestroyWindow        = user32.NewProc("DestroyWindow")
	pGetMessageW          = user32.NewProc("GetMessageW")
	pTranslateMessage     = user32.NewProc("TranslateMessage")
	pDispatchMessageW     = user32.NewProc("DispatchMessageW")
	pIsDialogMessageW     = user32.NewProc("IsDialogMessageW")
	pPostQuitMessage      = user32.NewProc("PostQuitMessage")
	pPostMessageW         = user32.NewProc("PostMessageW")
	pSendMessageW         = user32.NewProc("SendMessageW")
	pShowWindow           = user32.NewProc("ShowWindow")
	pUpdateWindow         = user32.NewProc("UpdateWindow")
	pEnableWindow         = user32.NewProc("EnableWindow")
	pIsWindowEnabled      = user32.NewProc("IsWindowEnabled")
	pIsWindowVisible      = user32.NewProc("IsWindowVisible")
	pSetWindowTextW       = user32.NewProc("SetWindowTextW")
	pGetWindowTextW       = user32.NewProc("GetWindowTextW")
	pGetWindowTextLengthW = user32.NewProc("GetWindowTextLengthW")
	pMessageBoxW          = user32.NewProc("MessageBoxW")
	pLoadImageW           = user32.NewProc("LoadImageW")
	pLoadCursorW          = user32.NewProc("LoadCursorW")
	pGetSystemMetrics     = user32.NewProc("GetSystemMetrics")
	pSystemParametersInfo = user32.NewProc("SystemParametersInfoW")
	pGetDC                = user32.NewProc("GetDC")
	pReleaseDC            = user32.NewProc("ReleaseDC")
	pBeginPaint           = user32.NewProc("BeginPaint")
	pEndPaint             = user32.NewProc("EndPaint")
	pFillRect             = user32.NewProc("FillRect")
	pDrawTextW            = user32.NewProc("DrawTextW")
	pDrawIconEx           = user32.NewProc("DrawIconEx")
	pInvalidateRect       = user32.NewProc("InvalidateRect")
	pSetFocus             = user32.NewProc("SetFocus")
	pGetFocus             = user32.NewProc("GetFocus")
	pSetWindowPos         = user32.NewProc("SetWindowPos")
	pGetClientRect        = user32.NewProc("GetClientRect")
	pAdjustWindowRectEx   = user32.NewProc("AdjustWindowRectEx")
	pSetForegroundWindow  = user32.NewProc("SetForegroundWindow")
	pGetSysColorBrush     = user32.NewProc("GetSysColorBrush")
	pGetDpiForSystem      = user32.NewProc("GetDpiForSystem")
	pAttachConsole        = kernel32.NewProc("AttachConsole")

	pCreateFontW        = gdi32.NewProc("CreateFontW")
	pCreateSolidBrush   = gdi32.NewProc("CreateSolidBrush")
	pDeleteObject       = gdi32.NewProc("DeleteObject")
	pSelectObject       = gdi32.NewProc("SelectObject")
	pSetBkMode          = gdi32.NewProc("SetBkMode")
	pSetBkColor         = gdi32.NewProc("SetBkColor")
	pSetTextColor       = gdi32.NewProc("SetTextColor")
	pGetDeviceCaps      = gdi32.NewProc("GetDeviceCaps")
	pGetModuleHandleW   = kernel32.NewProc("GetModuleHandleW")
	pGetDiskFreeSpaceEx = kernel32.NewProc("GetDiskFreeSpaceExW")
	pExpandEnvStrings   = kernel32.NewProc("ExpandEnvironmentStringsW")

	pInitCommonControlsEx = comctl32.NewProc("InitCommonControlsEx")

	pSHBrowseForFolderW   = shell32.NewProc("SHBrowseForFolderW")
	pSHGetPathFromIDListW = shell32.NewProc("SHGetPathFromIDListW")
	pSHGetFolderPathW     = shell32.NewProc("SHGetFolderPathW")
	pShellExecuteW        = shell32.NewProc("ShellExecuteW")
	pGetOpenFileNameW     = comdlg32.NewProc("GetOpenFileNameW")
	pCommDlgExtendedError = comdlg32.NewProc("CommDlgExtendedError")
	pCoInitializeEx       = ole32.NewProc("CoInitializeEx")
	pCoTaskMemFree        = ole32.NewProc("CoTaskMemFree")

	pRegCreateKeyExW = advapi32.NewProc("RegCreateKeyExW")
	pRegSetValueExW  = advapi32.NewProc("RegSetValueExW")
	pRegDeleteKeyW   = advapi32.NewProc("RegDeleteKeyW")
)

const (
	WS_OVERLAPPED    = 0x00000000
	WS_CAPTION       = 0x00C00000
	WS_SYSMENU       = 0x00080000
	WS_MINIMIZEBOX   = 0x00020000
	WS_CLIPCHILDREN  = 0x02000000
	WS_CHILD         = 0x40000000
	WS_VISIBLE       = 0x10000000
	WS_TABSTOP       = 0x00010000
	WS_GROUP         = 0x00020000
	WS_VSCROLL       = 0x00200000
	WS_EX_CLIENTEDGE = 0x00000200
	WS_EX_CONTROLPAR = 0x00010000
	WS_EX_APPWINDOW  = 0x00040000

	SS_LEFT         = 0x0
	SS_NOPREFIX     = 0x80
	SS_ENDELLIPSIS  = 0x4000
	SS_PATHELLIPSIS = 0x8000

	BS_PUSHBUTTON    = 0x0
	BS_DEFPUSHBUTTON = 0x1
	BS_AUTOCHECKBOX  = 0x3
	BS_RADIOBUTTON   = 0x4
	BS_MULTILINE     = 0x2000

	ES_AUTOHSCROLL = 0x80
	ES_AUTOVSCROLL = 0x40
	ES_MULTILINE   = 0x4
	ES_READONLY    = 0x800

	PBS_SMOOTH = 0x1

	WM_CREATE         = 0x0001
	WM_DESTROY        = 0x0002
	WM_PAINT          = 0x000F
	WM_CLOSE          = 0x0010
	WM_ERASEBKGND     = 0x0014
	WM_SETFONT        = 0x0030
	WM_SETICON        = 0x0080
	WM_COMMAND        = 0x0111
	WM_CTLCOLOREDIT   = 0x0133
	WM_CTLCOLORBTN    = 0x0135
	WM_CTLCOLORSTATIC = 0x0138
	WM_PRINTCLIENT    = 0x0318
	WM_USER           = 0x0400
	WM_APP            = 0x8000
	DM_GETDEFID       = WM_USER + 0
	DC_HASDEFID       = 0x534B

	BM_GETCHECK      = 0x00F0
	BM_SETCHECK      = 0x00F1
	BM_SETSTYLE      = 0x00F4
	BN_CLICKED       = 0
	EN_CHANGE        = 0x0300
	EM_SETSEL        = 0x00B1
	EM_REPLACESEL    = 0x00C2
	EM_SETLIMITTEXT  = 0x00C5
	PBM_SETPOS       = WM_USER + 2
	PBM_SETRANGE32   = WM_USER + 6
	BFFM_INITIALIZED = 1
	BFFM_SETSELECTW  = WM_USER + 103

	SW_HIDE       = 0
	SW_SHOWNORMAL = 1
	SW_SHOW       = 5

	IDOK     = 1
	IDCANCEL = 2
	IDYES    = 6
	IDRETRY  = 4

	MB_OK          = 0x0
	MB_OKCANCEL    = 0x1
	MB_YESNO       = 0x4
	MB_RETRYCANCEL = 0x5
	MB_ICONERROR   = 0x10
	MB_ICONQUEST   = 0x20
	MB_ICONWARNING = 0x30
	MB_ICONINFO    = 0x40
	MB_DEFBUTTON2  = 0x100

	IMAGE_ICON      = 1
	LR_DEFAULTCOLOR = 0
	LR_LOADFROMFILE = 0x10
	LR_SHARED       = 0x8000
	IDC_ARROW       = 32512
	SM_CXICON       = 11
	SM_CXSMICON     = 49
	ICON_SMALL      = 0
	ICON_BIG        = 1
	DI_NORMAL       = 3
	COLOR_WINDOW    = 5
	COLOR_BTNFACE   = 15
	TRANSPARENT     = 1
	OPAQUE          = 2
	LOGPIXELSY      = 90
	SPI_GETWORKAREA = 0x0030

	DT_LEFT         = 0x0
	DT_SINGLELINE   = 0x20
	DT_VCENTER      = 0x4
	DT_NOPREFIX     = 0x800
	DT_END_ELLIPSIS = 0x8000
	DT_WORDBREAK    = 0x10

	SWP_NOSIZE   = 0x1
	SWP_NOZORDER = 0x4

	BIF_RETURNONLYFSDIRS = 0x1
	BIF_EDITBOX          = 0x10
	BIF_NEWDIALOGSTYLE   = 0x40

	OFN_HIDEREADONLY    = 0x4
	OFN_PATHMUSTEXIST   = 0x800
	OFN_FILEMUSTEXIST   = 0x1000
	OFN_EXPLORER        = 0x80000
	OFN_DONTADDTORECENT = 0x2000000

	ICC_PROGRESS_CLASS = 0x20
	ICC_STANDARD       = 0x4000

	CSIDL_PROGRAMS           = 0x02
	CSIDL_DESKTOPDIRECTORY   = 0x10
	COINIT_APARTMENTTHREADED = 0x2
	COINIT_DISABLE_OLE1DDE   = 0x4
	ATTACH_PARENT_PROCESS    = ^uintptr(0)
	HKEY_CURRENT_USER        = 0x80000001
	KEY_WRITE                = 0x20006
	REG_SZ                   = 1
	REG_DWORD                = 4
	CREATE_NO_WINDOW         = 0x08000000
	CREATE_NEW_PROCESS_GROUP = 0x00000200
	DETACHED_PROCESS         = 0x00000008
	CW_USEDEFAULT            = ^uintptr(0x7FFFFFFF) // (0x80000000, as an int)
	DEFAULT_CHARSET          = 1
	CLEARTYPE_QUALITY        = 5
	FW_NORMAL                = 400
	FW_SEMIBOLD              = 600
	ERROR_SUCCESS            = 0
	errorFileNotFound        = 2
)

type wndClassEx struct {
	Size       uint32
	Style      uint32
	WndProc    uintptr
	ClsExtra   int32
	WndExtra   int32
	Instance   uintptr
	Icon       uintptr
	Cursor     uintptr
	Background uintptr
	MenuName   *uint16
	ClassName  *uint16
	IconSm     uintptr
}

type msgT struct {
	Hwnd     uintptr
	Message  uint32
	WParam   uintptr
	LParam   uintptr
	Time     uint32
	PtX      int32
	PtY      int32
	LPrivate uint32
}

type rect struct{ Left, Top, Right, Bottom int32 }

type paintStruct struct {
	Hdc       uintptr
	Erase     int32
	Paint     rect
	Restore   int32
	IncUpdate int32
	Reserved  [32]byte
}

type initCommonControlsEx struct {
	Size uint32
	ICC  uint32
}

type browseInfo struct {
	Owner       uintptr
	Root        uintptr
	DisplayName *uint16
	Title       *uint16
	Flags       uint32
	Fn          uintptr
	LParam      uintptr
	Image       int32
}

type openFileName struct {
	StructSize    uint32
	Owner         uintptr
	Instance      uintptr
	Filter        *uint16
	CustomFilter  *uint16
	MaxCustFilter uint32
	FilterIndex   uint32
	File          *uint16
	MaxFile       uint32
	FileTitle     *uint16
	MaxFileTitle  uint32
	InitialDir    *uint16
	Title         *uint16
	Flags         uint32
	FileOffset    uint16
	FileExtension uint16
	DefExt        *uint16
	CustData      uintptr
	FnHook        uintptr
	TemplateName  *uint16
	PvReserved    uintptr
	DwReserved    uint32
	FlagsEx       uint32
}

// The sizes Windows checks (64-bit): a wrong one, and the call fails.
var _ = [1]struct{}{}[unsafe.Sizeof(wndClassEx{})-80]
var _ = [1]struct{}{}[unsafe.Sizeof(msgT{})-48]
var _ = [1]struct{}{}[unsafe.Sizeof(paintStruct{})-72]
var _ = [1]struct{}{}[unsafe.Sizeof(browseInfo{})-64]
var _ = [1]struct{}{}[unsafe.Sizeof(openFileName{})-152]

func wstr(text string) *uint16 {
	out := make([]uint16, 0, len(text)+1)
	for _, r := range text {
		if r == 0 {
			continue
		}
		if r >= 0x10000 {
			r -= 0x10000
			out = append(out, uint16(0xD800+(r>>10)), uint16(0xDC00+(r&0x3FF)))
		} else {
			out = append(out, uint16(r))
		}
	}
	out = append(out, 0)
	return &out[0]
}

// (A string's pointer is made into a number in the call itself, never before: so Go keeps the string until the call
// is done.)

func lo(v uintptr) uint16 { return uint16(v & 0xFFFF) }
func hi(v uintptr) uint16 { return uint16((v >> 16) & 0xFFFF) }

func send(hwnd uintptr, msg uint32, wparam, lparam uintptr) uintptr {
	r, _, _ := pSendMessageW.Call(hwnd, uintptr(msg), wparam, lparam)
	return r
}

func post(hwnd uintptr, msg uint32, wparam, lparam uintptr) {
	pPostMessageW.Call(hwnd, uintptr(msg), wparam, lparam)
}

func windowText(hwnd uintptr) string {
	n, _, _ := pGetWindowTextLengthW.Call(hwnd)
	buf := make([]uint16, n+1)
	pGetWindowTextW.Call(hwnd, uintptr(unsafe.Pointer(&buf[0])), n+1)
	return syscall.UTF16ToString(buf)
}

func setText(hwnd uintptr, text string) {
	pSetWindowTextW.Call(hwnd, uintptr(unsafe.Pointer(wstr(text))))
}

func show(hwnd uintptr, on bool) {
	if on {
		pShowWindow.Call(hwnd, SW_SHOW)
	} else {
		pShowWindow.Call(hwnd, SW_HIDE)
	}
}

func enable(hwnd uintptr, on bool) {
	v := uintptr(0)
	if on {
		v = 1
	}
	pEnableWindow.Call(hwnd, v)
}

func checked(hwnd uintptr) bool { return send(hwnd, BM_GETCHECK, 0, 0) == 1 }

func setChecked(hwnd uintptr, on bool) {
	v := uintptr(0)
	if on {
		v = 1
	}
	send(hwnd, BM_SETCHECK, v, 0)
}

func messageBox(owner uintptr, text, title string, flags uintptr) int {
	r, _, _ := pMessageBoxW.Call(owner, uintptr(unsafe.Pointer(wstr(text))), uintptr(unsafe.Pointer(wstr(title))), flags)
	return int(r)
}
