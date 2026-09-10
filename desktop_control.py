"""Window-scoped Win32 control. Coordinates are physical client pixels.

Observe before each input. A one-use observation binds HWND, PID, geometry,
and foreground state, preventing stale coordinates from silently targeting
another window. This is same-user desktop automation, not a security boundary.
"""
import base64
import ctypes as C
from ctypes import wintypes as W
import secrets
import time

U = C.WinDLL('user32', use_last_error=True)
K = C.WinDLL('kernel32', use_last_error=True)


def signature(lib, name, result, *args):
    fn = getattr(lib, name)
    fn.restype, fn.argtypes = result, list(args)
    return fn


signature(U, 'GetForegroundWindow', W.HWND)
signature(U, 'GetAncestor', W.HWND, W.HWND, W.UINT)
signature(U, 'WindowFromPoint', W.HWND, W.POINT)
signature(U, 'IsWindow', W.BOOL, W.HWND)
signature(U, 'IsWindowVisible', W.BOOL, W.HWND)
signature(U, 'IsIconic', W.BOOL, W.HWND)
signature(U, 'GetWindowThreadProcessId', W.DWORD, W.HWND, C.POINTER(W.DWORD))
signature(U, 'GetClientRect', W.BOOL, W.HWND, C.POINTER(W.RECT))
signature(U, 'ClientToScreen', W.BOOL, W.HWND, C.POINTER(W.POINT))
signature(U, 'GetWindowTextW', C.c_int, W.HWND, W.LPWSTR, C.c_int)
signature(U, 'ShowWindow', W.BOOL, W.HWND, C.c_int)
signature(U, 'SetForegroundWindow', W.BOOL, W.HWND)
signature(U, 'SetCursorPos', W.BOOL, C.c_int, C.c_int)
signature(U, 'GetAsyncKeyState', C.c_short, C.c_int)
signature(U, 'SetThreadDpiAwarenessContext', W.HANDLE, W.HANDLE)
signature(K, 'OpenProcess', W.HANDLE, W.DWORD, W.BOOL, W.DWORD)
signature(K, 'QueryFullProcessImageNameW', W.BOOL, W.HANDLE, W.DWORD, W.LPWSTR, C.POINTER(W.DWORD))
signature(K, 'CloseHandle', W.BOOL, W.HANDLE)


class Mouse(C.Structure):
    _fields_ = [('dx', W.LONG), ('dy', W.LONG), ('mouseData', W.DWORD),
                ('dwFlags', W.DWORD), ('time', W.DWORD), ('extra', C.c_size_t)]


class Keyboard(C.Structure):
    _fields_ = [('vk', W.WORD), ('scan', W.WORD), ('flags', W.DWORD),
                ('time', W.DWORD), ('extra', C.c_size_t)]


class Payload(C.Union):
    _fields_ = [('mi', Mouse), ('ki', Keyboard)]


class Input(C.Structure):
    _fields_ = [('type', W.DWORD), ('payload', Payload)]


signature(U, 'SendInput', W.UINT, W.UINT, C.POINTER(Input), C.c_int)
ENUM = C.WINFUNCTYPE(W.BOOL, W.HWND, W.LPARAM)
signature(U, 'EnumWindows', W.BOOL, ENUM, W.LPARAM)


def integer(args, key, low, high):
    value = args.get(key)
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f'{key} must be an integer in {low}..{high}')
    return value


def keyboard(vk=0, scan=0, flags=0):
    return Input(1, Payload(ki=Keyboard(vk, scan, flags, 0, 0)))


def mouse(flags, data=0):
    return Input(0, Payload(mi=Mouse(0, 0, data & 0xffffffff, flags, 0, 0)))


def send(events):
    batch = (Input * len(events))(*events)
    sent = U.SendInput(len(batch), batch, C.sizeof(Input))
    if sent != len(batch):
        # Best effort release of keys/buttons potentially left down after partial input.
        releases = []
        for e in events:
            if e.type == 1 and not e.payload.ki.flags & 2:
                k = e.payload.ki
                releases.append(keyboard(k.vk, k.scan, k.flags | 2))
            elif e.type == 0:
                for down, up in ((2, 4), (8, 16), (32, 64)):
                    if e.payload.mi.dwFlags & down:
                        releases.append(mouse(up))
        if releases:
            U.SendInput(len(releases), (Input * len(releases))(*releases), C.sizeof(Input))
        raise RuntimeError(f'SendInput accepted {sent}/{len(batch)} events; outcome may be partial. Elevated apps may reject input. Observe again.')


KEYS = {'enter': 13, 'tab': 9, 'escape': 27, 'space': 32, 'backspace': 8,
        'delete': 46, 'left': 37, 'up': 38, 'right': 39, 'down': 40,
        'home': 36, 'end': 35, 'pageup': 33, 'pagedown': 34,
        'insert': 45, **{f'f{i}': 111+i for i in range(1, 13)},
        **{c.lower(): ord(c) for c in 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789'}}
MODIFIERS = {'ctrl': 17, 'alt': 18, 'shift': 16}


def drag_modifiers(args):
    names = args.get('modifiers', [])
    if not isinstance(names, list) or any(not isinstance(n, str) or n not in MODIFIERS for n in names) or len(set(names)) != len(names):
        raise ValueError('modifiers must be unique ctrl/shift/alt names')
    return [MODIFIERS[n] for n in names]


def release_drag(up, modifiers):
    events = [mouse(up)] + [keyboard(code, flags=2) for code in reversed(modifiers)]
    for attempt in range(3):
        try:
            send(events)
            return
        except RuntimeError:
            if attempt == 2:
                raise RuntimeError('Input release failed after 3 attempts; release buttons/modifiers manually and observe again')
            time.sleep(.02)


def key_events(chord):
    if not isinstance(chord, str):
        raise ValueError('key must be a string such as Ctrl+A or Enter')
    parts = [p.strip().lower() for p in chord.split('+')]
    if not parts or parts[-1] not in KEYS or any(p not in MODIFIERS for p in parts[:-1]) or len(set(parts[:-1])) != len(parts[:-1]):
        raise ValueError('Use Ctrl/Alt/Shift modifiers and a supported named key, A-Z, 0-9 or F1-F12')
    codes = [MODIFIERS[p] for p in parts[:-1]] + [KEYS[parts[-1]]]
    def event(code, up=False):
        return keyboard(code, flags=(1 if code in range(33, 47) else 0) | (2 if up else 0))
    return [event(c) for c in codes] + [event(c, True) for c in reversed(codes)]


class Desktop:
    def __init__(self, capture, encode, blank):
        self.capture, self.encode, self.blank = capture, encode, blank
        self.observations = {}

    def window(self, hwnd):
        if not U.IsWindow(hwnd) or not U.IsWindowVisible(hwnd):
            raise ValueError('Window is no longer visible or valid; list windows again')
        pid, title = W.DWORD(), C.create_unicode_buffer(2048)
        U.GetWindowThreadProcessId(hwnd, C.byref(pid))
        U.GetWindowTextW(hwnd, title, len(title))
        rc, pt = W.RECT(), W.POINT()
        if not U.GetClientRect(hwnd, C.byref(rc)) or not U.ClientToScreen(hwnd, C.byref(pt)):
            raise RuntimeError('Cannot read client geometry')
        path = ''
        handle = K.OpenProcess(0x1000, False, pid.value)
        if handle:
            try:
                buf, size = C.create_unicode_buffer(32768), W.DWORD(32768)
                if K.QueryFullProcessImageNameW(handle, 0, buf, C.byref(size)):
                    path = buf.value
            finally:
                K.CloseHandle(handle)
        return {'hwnd': hwnd, 'pid': pid.value, 'title': title.value, 'path': path,
                'minimized': bool(U.IsIconic(hwnd)),
                'client': {'x': pt.x, 'y': pt.y, 'width': rc.right, 'height': rc.bottom}}

    def list_windows(self, args):
        result = []
        @ENUM
        def visit(hwnd, _):
            try:
                w = self.window(int(hwnd))
                if w['title'] and w['client']['width'] > 0:
                    result.append(w)
            except (ValueError, RuntimeError):
                pass
            return True
        U.EnumWindows(visit, 0)
        return {'ok': True, 'windows': result}

    def observe(self, args):
        # A failed refresh must not leave a previously observed target actionable.
        previous = dict(self.observations) if args.get('retain_previous') is True else {}
        self.observations.clear()
        if type(args.get('retain_previous', False)) is not bool:
            raise ValueError('retain_previous must be boolean')
        if type(args.get('focus', False)) is not bool:
            raise ValueError('focus must be boolean')
        hwnd = integer(args, 'hwnd', 1, 2**63-1)
        w = self.window(hwnd)
        if args.get('focus', False):
            if w['minimized']:
                U.ShowWindow(hwnd, 9)
            if U.GetForegroundWindow() != hwnd:
                U.SetForegroundWindow(hwnd)
            time.sleep(.15)
            if U.GetForegroundWindow() != hwnd:
                raise RuntimeError('Windows refused foreground activation; select the window manually')
            w = self.window(hwnd)
        if w['minimized']:
            raise ValueError('Window minimized; observe with focus=true to restore')
        pixels, width, height, method, notes = self.capture(hwnd, False)
        blank, reason = self.blank(pixels, width, height)
        if blank:
            raise RuntimeError(f'Capture appears blank: {reason}')
        after = self.window(hwnd)
        if any(w[k] != after[k] for k in ('pid', 'path', 'client')):
            raise RuntimeError('Window changed during capture; observe again')
        if (width, height) != (w['client']['width'], w['client']['height']):
            raise RuntimeError('Capture geometry mismatch; observe again')
        token = secrets.token_urlsafe(18)
        self.observations = {key: value for key, value in previous.items()
                             if time.monotonic()-value[0] <= 60 and value[1]['hwnd'] != hwnd}
        self.observations = dict(list(self.observations.items())[-7:])
        self.observations[token] = (time.monotonic(), w)
        return {'ok': True, 'window': w, 'observation_id': token,
                'expires_in_seconds': 60, 'coordinates': 'physical client pixels',
                'width': width, 'height': height, 'method': method, 'notes': notes,
                '_image_b64': base64.b64encode(self.encode(pixels, width, height)).decode(),
                '_image_mime': 'image/png'}

    def target(self, args, foreground=True):
        token = args.get('observation_id')
        if not isinstance(token, str):
            raise ValueError('observation_id required; call desktop_observe first')
        old = self.observations.pop(token, None)
        if old is None or time.monotonic() - old[0] > 60:
            raise ValueError('Observation expired or already used; observe again')
        w = old[1]
        self.check_target(w, foreground=foreground)
        if any(U.GetAsyncKeyState(k) & 0x8000 for k in (1, 2, 4, 16, 17, 18, 91, 92)):
            raise ValueError('Release physical mouse buttons/modifier keys, then observe again')
        return w

    def check_target(self, w, foreground=True):
        now = self.window(w['hwnd'])
        if now['minimized'] or any(now[k] != w[k] for k in ('pid', 'path', 'client')):
            raise ValueError('Window moved, resized or changed owner; observe again')
        if foreground and U.GetForegroundWindow() != w['hwnd']:
            raise ValueError('Target is not foreground; observe with focus=true')

    def point(self, args, w):
        r = w['client']
        x = integer(args, 'x', 0, r['width']-1) + r['x']
        y = integer(args, 'y', 0, r['height']-1) + r['y']
        hit = U.WindowFromPoint(W.POINT(x, y))
        if not hit or U.GetAncestor(hit, 2) != w['hwnd']:
            raise ValueError('Point is covered by another window; observe again')
        if not U.SetCursorPos(x, y):
            raise RuntimeError('Cannot move pointer')

    def click(self, args):
        button = args.get('button', 'left')
        if button not in ('left', 'right', 'middle'):
            raise ValueError('button must be left, right or middle')
        count = integer({'count': args.get('count', 1)}, 'count', 1, 2)
        w = self.target(args)
        self.point(args, w)
        down, up = {'left': (2, 4), 'right': (8, 16), 'middle': (32, 64)}[button]
        self.check_target(w)
        send([e for _ in range(count) for e in (mouse(down), mouse(up))])
        return {'ok': True, 'hwnd': w['hwnd'], 'observe_again': True}

    def drag(self, args):
        modifiers = drag_modifiers(args)
        button = args.get('button', 'left')
        if button not in ('left', 'right', 'middle'):
            raise ValueError('button must be left, right or middle')
        duration = integer({'duration_ms': args.get('duration_ms', 800)}, 'duration_ms', 100, 10000)
        # Validate the entire path before moving the pointer or pressing a button.
        coordinates = [(integer(args, 'from_x', 0, 8000), integer(args, 'from_y', 0, 8000))]
        via = args.get('via', [])
        if not isinstance(via, list) or len(via) > 64:
            raise ValueError('via must contain at most 64 {x,y} points')
        for point in via:
            if not isinstance(point, dict):
                raise ValueError('Each via point must be {x,y}')
            coordinates.append((integer(point, 'x', 0, 8000), integer(point, 'y', 0, 8000)))
        coordinates.append((integer(args, 'to_x', 0, 8000), integer(args, 'to_y', 0, 8000)))
        w = self.target(args)
        for x, y in coordinates:
            if x >= w['client']['width'] or y >= w['client']['height']:
                raise ValueError('Drag path outside client image')
        lengths = [((b[0]-a[0])**2 + (b[1]-a[1])**2)**.5 for a,b in zip(coordinates, coordinates[1:])]
        total = sum(lengths)
        if total == 0:
            raise ValueError('Drag path must have nonzero length')
        down, up = {'left': (2, 4), 'right': (8, 16), 'middle': (32, 64)}[button]
        self.point({'x': coordinates[0][0], 'y': coordinates[0][1]}, w)
        pressed = False
        moves = 0
        try:
            self.check_target(w)
            # Set before SendInput so partial/unknown failures also attempt release.
            pressed = True
            send([keyboard(code) for code in modifiers] + [mouse(down)])
            time.sleep(.05)
            for a, b, length in zip(coordinates, coordinates[1:], lengths):
                seconds = duration / 1000 * length / total
                steps = max(1, round(seconds * 60))
                for i in range(1, steps + 1):
                    time.sleep(seconds / steps)
                    if U.GetAsyncKeyState(27) & 0x8000:
                        raise RuntimeError('Drag cancelled by Escape; partial movement may remain')
                    self.check_target(w)
                    x = round(a[0] + (b[0]-a[0])*i/steps)
                    y = round(a[1] + (b[1]-a[1])*i/steps)
                    self.point({'x': x, 'y': y}, w)
                    moves += 1
            time.sleep(.05)
        finally:
            if pressed:
                release_drag(up, modifiers)
        return {'ok': True, 'hwnd': w['hwnd'], 'moves': moves, 'button_released': True,
                'observe_again': True}

    def drag_between(self, args):
        modifiers = drag_modifiers(args)
        button = args.get('button', 'left')
        if button not in ('left', 'right', 'middle'):
            raise ValueError('button must be left, right or middle')
        duration = integer({'duration_ms': args.get('duration_ms', 1000)}, 'duration_ms', 100, 10000)
        destination_id = args.get('destination_observation_id')
        if destination_id == args.get('observation_id'):
            raise ValueError('Use two distinct observations for cross-window drag')
        destination = self.target({'observation_id': destination_id}, foreground=False)
        source = self.target(args)
        if source['hwnd'] == destination['hwnd']:
            raise ValueError('Use desktop_drag for the same window')
        sx = integer(args, 'from_x', 0, source['client']['width']-1)
        sy = integer(args, 'from_y', 0, source['client']['height']-1)
        tx = integer(args, 'to_x', 0, destination['client']['width']-1)
        ty = integer(args, 'to_y', 0, destination['client']['height']-1)
        start = (source['client']['x']+sx, source['client']['y']+sy)
        end = (destination['client']['x']+tx, destination['client']['y']+ty)
        def visible_destination():
            hit = U.WindowFromPoint(W.POINT(*end))
            if not hit or U.GetAncestor(hit, 2) != destination['hwnd']:
                raise ValueError('Destination is covered; arrange both windows visibly and observe again')
        visible_destination()
        self.point({'x': sx, 'y': sy}, source)
        down, up = {'left': (2, 4), 'right': (8, 16), 'middle': (32, 64)}[button]
        attempted = False
        steps = max(2, round(duration / 1000 * 60))
        try:
            self.check_target(source)
            self.check_target(destination, foreground=False)
            attempted = True
            send([keyboard(code) for code in modifiers] + [mouse(down)])
            time.sleep(.05)
            for i in range(1, steps+1):
                time.sleep(duration / 1000 / steps)
                if U.GetAsyncKeyState(27) & 0x8000:
                    raise RuntimeError('Drag cancelled by Escape; partial movement may remain')
                self.check_target(source, foreground=False)
                self.check_target(destination, foreground=False)
                if U.GetForegroundWindow() not in (source['hwnd'], destination['hwnd']):
                    raise ValueError('Another window took foreground during drag')
                visible_destination()
                x = round(start[0] + (end[0]-start[0])*i/steps)
                y = round(start[1] + (end[1]-start[1])*i/steps)
                if not U.SetCursorPos(x, y):
                    raise RuntimeError('Cannot move pointer during cross-window drag')
            time.sleep(.05)
            self.check_target(destination, foreground=False)
            visible_destination()
        finally:
            if attempted:
                release_drag(up, modifiers)
        return {'ok': True, 'source_hwnd': source['hwnd'], 'destination_hwnd': destination['hwnd'],
                'button_released': True, 'modifiers_released': True, 'observe_again': True,
                'note': 'Input delivered; inspect destination to verify whether the application accepted the drop.'}

    def type_text(self, args):
        text = args.get('text')
        if not isinstance(text, str) or not 1 <= len(text) <= 2000 or any(ord(c) < 32 for c in text):
            raise ValueError('text must contain 1..2000 printable characters; use desktop_press_key for Enter/Tab')
        raw = text.encode('utf-16-le')
        w = self.target(args)
        events = []
        for i in range(0, len(raw), 2):
            unit = int.from_bytes(raw[i:i+2], 'little')
            events.extend((keyboard(scan=unit, flags=4), keyboard(scan=unit, flags=6)))
        send(events)
        return {'ok': True, 'characters': len(text), 'hwnd': w['hwnd'], 'observe_again': True}

    def press_key(self, args):
        events = key_events(args.get('key'))
        w = self.target(args)
        send(events)
        return {'ok': True, 'hwnd': w['hwnd'], 'observe_again': True}

    def scroll(self, args):
        ticks = integer(args, 'ticks', -20, 20)
        axis = args.get('axis', 'vertical')
        if axis not in ('vertical', 'horizontal') or ticks == 0:
            raise ValueError('axis must be vertical/horizontal; ticks must be nonzero')
        w = self.target(args)
        self.point(args, w)
        self.check_target(w)
        send([mouse(0x800 if axis == 'vertical' else 0x1000, ticks * 120)])
        return {'ok': True, 'hwnd': w['hwnd'], 'observe_again': True}


def build_tools(capture, encode, blank):
    desktop = Desktop(capture, encode, blank)
    token = {'observation_id': {'type': 'string'}}
    xy = {'x': {'type': 'integer', 'minimum': 0}, 'y': {'type': 'integer', 'minimum': 0}}
    specs = [
        ('list_windows', 'List visible Windows application windows and HWND/PID/path. Choose the intended window explicitly.', {}, []),
        ('observe', 'Capture a selected window client area. Returns image and one-use observation_id valid for 60 seconds. Use focus=true before input. Inspect image before acting.', {'hwnd': {'type': 'integer', 'minimum': 1}, 'focus': {'type': 'boolean', 'default': False}}, ['hwnd']),
        ('click', 'Click physical client-image coordinates from the latest observation. Reobserve after every action.', {**token, **xy, 'button': {'type': 'string', 'enum': ['left', 'right', 'middle']}, 'count': {'type': 'integer', 'minimum': 1, 'maximum': 2}}, ['observation_id', 'x', 'y']),
        ('drag', 'Drag inside the observed window client image, optionally through via points. Supports left/right/middle. Smooth movement, Escape cancellation, foreground/geometry checks throughout, and button release on failure. Partial movement can remain on failure; observe again, never blindly retry. Does not support cross-window dragging.', {**token, **{k: {'type': 'integer', 'minimum': 0} for k in ('from_x', 'from_y', 'to_x', 'to_y')}, 'button': {'type': 'string', 'enum': ['left', 'right', 'middle']}, 'duration_ms': {'type': 'integer', 'minimum': 100, 'maximum': 10000, 'default': 800}, 'via': {'type': 'array', 'maxItems': 64, 'items': {'type': 'object', 'properties': xy, 'required': ['x', 'y'], 'additionalProperties': False}}}, ['observation_id', 'from_x', 'from_y', 'to_x', 'to_y']),
        ('type_text', 'Type literal Unicode into the currently focused editor. First click the intended editor and observe its focus. Does not use clipboard. Reobserve afterwards.', {**token, 'text': {'type': 'string', 'minLength': 1, 'maxLength': 2000}}, ['observation_id', 'text']),
        ('press_key', 'Press a key or chord, e.g. Ctrl+A, Enter, Tab, Escape, Alt+F4. May submit or close; follow user intent and inspect current focus first.', {**token, 'key': {'type': 'string'}}, ['observation_id', 'key']),
        ('scroll', 'Scroll at client-image x/y. Positive ticks scroll up (vertical) or right (horizontal). One tick is 120 Windows wheel units.', {**token, **xy, 'ticks': {'type': 'integer', 'minimum': -20, 'maximum': 20}, 'axis': {'type': 'string', 'enum': ['vertical', 'horizontal']}}, ['observation_id', 'x', 'y', 'ticks']),
    ]
    modifier_schema = {'type': 'array', 'uniqueItems': True, 'maxItems': 3,
                       'items': {'type': 'string', 'enum': ['ctrl', 'shift', 'alt']}}
    for name, description, props, required in specs:
        if name == 'observe':
            props['retain_previous'] = {'type': 'boolean', 'default': False,
                'description': 'Keep up to 7 other recent window observations for cross-window drag; same-window observations are replaced.'}
        if name == 'drag':
            props['modifiers'] = modifier_schema
    specs.append(('drag_between',
        'Drag between two observed windows. First observe destination, then observe source with focus=true and retain_previous=true. Inspect both images. from_x/y are source client pixels, to_x/y destination client pixels. Both endpoints must be visible. Straight screen path can hover over other windows. Ctrl/Shift/Alt alter app-specific drop behavior. Escape cancels; partial effects can remain. Verify the drop with another observation.',
        {**token, 'destination_observation_id': {'type': 'string'},
         **{k: {'type': 'integer', 'minimum': 0} for k in ('from_x', 'from_y', 'to_x', 'to_y')},
         'modifiers': modifier_schema, 'button': {'type': 'string', 'enum': ['left', 'right', 'middle']},
         'duration_ms': {'type': 'integer', 'minimum': 100, 'maximum': 10000, 'default': 1000}},
        ['observation_id', 'destination_observation_id', 'from_x', 'from_y', 'to_x', 'to_y']))
    def handler(method):
        def run(args):
            previous = U.SetThreadDpiAwarenessContext(W.HANDLE(-4))
            try:
                return getattr(desktop, method)(args)
            finally:
                if previous:
                    U.SetThreadDpiAwarenessContext(previous)
        return run
    return [{'name': 'desktop_' + name, 'description': description,
             'inputSchema': {'type': 'object', 'properties': props, 'required': required, 'additionalProperties': False},
             'handler': handler(name)} for name, description, props, required in specs]
