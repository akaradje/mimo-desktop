"""Explicit CF_UNICODETEXT publishing. Replaces clipboard; never auto-restores it.

Paste is asynchronous in many applications. Restoring immediately after Ctrl+V
can paste the old value, so callers must opt into leaving the requested text there.
"""
import ctypes as C
from ctypes import wintypes as W
import time

U = C.WinDLL('user32', use_last_error=True)
K = C.WinDLL('kernel32', use_last_error=True)
U.CreateWindowExW.argtypes = [W.DWORD, W.LPCWSTR, W.LPCWSTR, W.DWORD,
    C.c_int, C.c_int, C.c_int, C.c_int, W.HWND, W.HMENU, W.HINSTANCE, C.c_void_p]
U.CreateWindowExW.restype = W.HWND
U.DestroyWindow.argtypes = [W.HWND]
U.OpenClipboard.argtypes = [W.HWND]
U.OpenClipboard.restype = W.BOOL
U.EmptyClipboard.restype = W.BOOL
U.CloseClipboard.restype = W.BOOL
U.SetClipboardData.argtypes = [W.UINT, W.HANDLE]
U.SetClipboardData.restype = W.HANDLE
K.GlobalAlloc.argtypes = [W.UINT, C.c_size_t]
K.GlobalAlloc.restype = W.HGLOBAL
K.GlobalLock.argtypes = [W.HGLOBAL]
K.GlobalLock.restype = C.c_void_p
K.GlobalUnlock.argtypes = [W.HGLOBAL]
K.GlobalFree.argtypes = [W.HGLOBAL]
K.GlobalFree.restype = W.HGLOBAL


def set_text(text):
    data = text.encode('utf-16-le') + b'\0\0'
    memory = K.GlobalAlloc(0x0002, len(data))
    if not memory:
        raise RuntimeError('Clipboard allocation failed; no paste attempted')
    owner = None
    opened = False
    try:
        pointer = K.GlobalLock(memory)
        if not pointer:
            raise RuntimeError('Clipboard memory lock failed; no paste attempted')
        try:
            C.memmove(pointer, data, len(data))
        finally:
            K.GlobalUnlock(memory)
        owner = U.CreateWindowExW(0, 'STATIC', 'MCP clipboard owner', 0,
                                  0, 0, 0, 0, W.HWND(-3), None, None, None)
        if not owner:
            raise RuntimeError('Clipboard owner creation failed; no paste attempted')
        for attempt in range(10):
            if U.OpenClipboard(owner):
                opened = True
                break
            time.sleep(.02)
        if not opened:
            raise RuntimeError('Clipboard busy; no paste attempted. Observe again before retrying')
        if not U.EmptyClipboard():
            raise RuntimeError('Cannot clear clipboard; no paste attempted')
        if not U.SetClipboardData(13, memory):
            raise RuntimeError('Cannot set clipboard; clipboard was cleared; no paste attempted')
        memory = None  # Ownership transferred to Windows only after success.
    finally:
        if opened:
            U.CloseClipboard()
        if owner:
            U.DestroyWindow(owner)
        if memory:
            K.GlobalFree(memory)
