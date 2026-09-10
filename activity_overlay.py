"""Native non-activating status window; no application titles or user text."""
import ctypes as C
from ctypes import wintypes as W
import json
import queue
import sys
import threading
import time


def main():
    u = C.WinDLL('user32', use_last_error=True)
    g = C.WinDLL('gdi32', use_last_error=True)
    u.CreateWindowExW.argtypes = [W.DWORD,W.LPCWSTR,W.LPCWSTR,W.DWORD,C.c_int,C.c_int,C.c_int,C.c_int,W.HWND,W.HMENU,W.HINSTANCE,C.c_void_p]
    u.CreateWindowExW.restype = W.HWND
    u.ShowWindow.argtypes = [W.HWND,C.c_int]
    u.SetWindowPos.argtypes = [W.HWND,W.HWND,C.c_int,C.c_int,C.c_int,C.c_int,W.UINT]
    u.SetWindowTextW.argtypes = [W.HWND,W.LPCWSTR]
    u.InvalidateRect.argtypes = [W.HWND,C.POINTER(W.RECT),W.BOOL]
    u.UpdateWindow.argtypes = [W.HWND]
    u.SendMessageW.argtypes = [W.HWND,W.UINT,W.WPARAM,W.LPARAM]
    u.SendMessageW.restype = W.LPARAM
    u.DestroyWindow.argtypes = [W.HWND]
    u.PeekMessageW.argtypes = [C.POINTER(W.MSG),W.HWND,W.UINT,W.UINT,W.UINT]
    u.TranslateMessage.argtypes = [C.POINTER(W.MSG)]
    u.DispatchMessageW.argtypes = [C.POINTER(W.MSG)]
    g.GetStockObject.argtypes = [C.c_int]
    g.GetStockObject.restype = W.HANDLE
    # WS_EX_NOACTIVATE | TRANSPARENT | TOOLWINDOW | TOPMOST; WS_DISABLED avoids hit tests.
    hwnd = u.CreateWindowExW(0x08000000|0x20|0x80|0x8, 'STATIC', '',
        0x80000000|0x08000000|0x1,
        max(0,u.GetSystemMetrics(0)-344),24,320,88,None,None,None,None)
    if not hwnd:
        return
    u.SendMessageW(hwnd,0x0030,g.GetStockObject(17),1)
    # Paint our own high-contrast text; a disabled STATIC otherwise draws gray text.
    class Paint(C.Structure):
        _fields_ = [('hdc',W.HDC),('erase',W.BOOL),('rect',W.RECT),
                    ('restore',W.BOOL),('inc',W.BOOL),('reserved',C.c_byte*32)]
    u.BeginPaint.argtypes = [W.HWND,C.POINTER(Paint)]
    u.BeginPaint.restype = W.HDC
    u.EndPaint.argtypes = [W.HWND,C.POINTER(Paint)]
    u.GetClientRect.argtypes = [W.HWND,C.POINTER(W.RECT)]
    u.FillRect.argtypes = [W.HDC,C.POINTER(W.RECT),W.HBRUSH]
    u.DrawTextW.argtypes = [W.HDC,W.LPCWSTR,C.c_int,C.POINTER(W.RECT),W.UINT]
    g.CreateSolidBrush.argtypes = [W.DWORD]
    g.CreateSolidBrush.restype = W.HBRUSH
    g.DeleteObject.argtypes = [W.HANDLE]
    g.SetTextColor.argtypes = [W.HDC,W.DWORD]
    g.SetBkMode.argtypes = [W.HDC,C.c_int]
    g.SelectObject.argtypes = [W.HDC,W.HANDLE]
    g.SelectObject.restype = W.HANDLE
    g.CreateRoundRectRgn.argtypes = [C.c_int]*6
    g.CreateRoundRectRgn.restype = W.HRGN
    u.SetWindowRgn.argtypes = [W.HWND,W.HRGN,W.BOOL]
    region = g.CreateRoundRectRgn(0,0,321,89,24,24)
    if not u.SetWindowRgn(hwnd,region,True):
        g.DeleteObject(region)
    g.CreateFontW.argtypes = [C.c_int]*5+[W.DWORD]*8+[W.LPCWSTR]
    g.CreateFontW.restype = W.HFONT
    def font(size, weight):
        return g.CreateFontW(-size,0,0,0,weight,0,0,0,1,0,0,5,0,'Arial')
    small_font, main_font = font(12,400), font(16,600)
    g.Ellipse.argtypes = [W.HDC,C.c_int,C.c_int,C.c_int,C.c_int]
    u.SetWindowLongPtrW.argtypes = [W.HWND,C.c_int,C.c_ssize_t]
    u.SetWindowLongPtrW.restype = C.c_ssize_t
    u.CallWindowProcW.argtypes = [C.c_void_p,W.HWND,W.UINT,W.WPARAM,W.LPARAM]
    u.CallWindowProcW.restype = W.LPARAM
    display = ['Ready', 'Idle', '0.0s', 'running']
    def rgb(r,g,b):
        return r | (g<<8) | (b<<16)
    brush = g.CreateSolidBrush(rgb(25,28,34))
    callback_type = C.WINFUNCTYPE(W.LPARAM,W.HWND,W.UINT,W.WPARAM,W.LPARAM)
    @callback_type
    def paint_proc(window,message,wp,lp):
        if message in (0x000F,0x0317,0x0318):
            paint = Paint()
            dc = u.BeginPaint(window,C.byref(paint)) if message==0x000F else wp
            rect = W.RECT()
            u.GetClientRect(window,C.byref(rect))
            u.FillRect(dc,C.byref(rect),brush)
            oldfont = g.SelectObject(dc,small_font)
            g.SetBkMode(dc,1)
            def text(value,box,color,face=small_font,align=0):
                g.SelectObject(dc,face)
                g.SetTextColor(dc,color)
                box = W.RECT(*box)
                u.DrawTextW(dc,value,-1,C.byref(box),0x8024|align)
            text('mimo  /  desktop',(18,10,250,28),rgb(149,158,174))
            text(display[0],(18,31,250,54),rgb(241,244,249),main_font)
            text(display[2],(251,32,302,54),rgb(180,189,202),small_font,2)
            text(display[1],(18,59,302,77),rgb(149,158,174))
            accent = {'running':rgb(115,166,255),'done':rgb(112,211,167),
                      'waiting_for_focus':rgb(239,190,106),'error':rgb(242,132,137)}.get(display[3],rgb(149,158,174))
            dot = g.CreateSolidBrush(accent)
            oldbrush = g.SelectObject(dc,dot)
            oldpen = g.SelectObject(dc,g.GetStockObject(8))
            g.Ellipse(dc,294,16,301,23)
            g.SelectObject(dc,oldpen)
            g.SelectObject(dc,oldbrush)
            g.DeleteObject(dot)
            g.SelectObject(dc,oldfont)
            if message==0x000F:
                u.EndPaint(window,C.byref(paint))
            return 0
        return u.CallWindowProcW(oldproc,window,message,wp,lp)
    oldproc = u.SetWindowLongPtrW(hwnd,-4,C.cast(paint_proc,C.c_void_p).value)
    if not oldproc:
        raise OSError(C.get_last_error(), 'Cannot install activity window renderer')
    events = queue.Queue(maxsize=64)
    def reader():
        for line in sys.stdin.buffer:
            try:
                events.put(json.loads(line))
            except ValueError:
                pass
        events.put(None)
    threading.Thread(target=reader,daemon=True).start()
    current = None
    started = changed = 0
    msg = W.MSG()
    try:
        while True:
            while u.PeekMessageW(C.byref(msg),None,0,0,1):
                u.TranslateMessage(C.byref(msg))
                u.DispatchMessageW(C.byref(msg))
            try:
                while True:
                    item = events.get_nowait()
                    if item is None:
                        return
                    current = item
                    changed = time.monotonic()
                    if item['state'] == 'running':
                        started = item['time']
                    u.ShowWindow(hwnd,4)  # SW_SHOWNOACTIVATE, never a toolkit activation.
                    u.SetWindowPos(hwnd,W.HWND(-1),0,0,0,0,0x0013)
            except queue.Empty:
                pass
            if current:
                state = current['state']
                elapsed = max(0,(time.monotonic() if state=='running' else current['time'])-started)
                operation = current['operation']
                names = {'drag_between':'Dragging between windows','drag':'Dragging',
                    'click':'Clicking','click_element':'Selecting a control','observe':'Observing window',
                    'inspect':'Reading interface','verify_text':'Verifying text','paste_text':'Pasting text',
                    'type_text':'Typing','press_key':'Pressing keys','scroll':'Scrolling',
                    'list_windows':'Finding windows','set_window_rect':'Arranging window',
                    'verify_element':'Checking control'}
                detail = {'running': 'Working · Esc stops movement' if operation in ('drag','drag_between','click','click_element','scroll') else 'Working…',
                    'waiting_for_focus':'Select the target window to continue',
                    'done':'Finished · check the result',
                    'error':'Needs attention · inspect before retrying'}.get(state,state)
                display[:] = [names.get(operation,operation.replace('_',' ').capitalize()),detail,f'{elapsed:.1f}s',state]
                u.SetWindowTextW(hwnd,'MIMO DESKTOP — '+display[0])
                u.InvalidateRect(hwnd,None,False)
                u.UpdateWindow(hwnd)
                if state!='running' and time.monotonic()-changed > (12 if state=='waiting_for_focus' else 3):
                    u.ShowWindow(hwnd,0)
            time.sleep(.075)
    finally:
        u.DestroyWindow(hwnd)
        g.DeleteObject(brush)
        g.DeleteObject(small_font)
        g.DeleteObject(main_font)


if __name__=='__main__':
    main()

