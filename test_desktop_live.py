"""Opt-in end-to-end input test in an isolated disposable Tk window.

Run explicitly: python test_desktop_live.py --run
Exercises the MCP transport and real Win32 input; never targets user documents.
"""
import json
import queue
import sys
import threading
import time
import tkinter as tk

from test_mcp_client import McpStdioClient


def main():
    if '--run' not in sys.argv:
        print('Opt-in: pass --run to open a disposable window and test real input.')
        return 0
    root = tk.Tk()
    root.title('mimo-desktop isolated input test')
    root.geometry('640x420+100+100')
    tk.Label(root, text='Disposable MCP test window — no user files', font=('Arial', 14)).pack(pady=15)
    entry = tk.Entry(root, font=('Arial', 18))
    entry.pack(fill='x', padx=20)
    # Tk does not consistently provide the Windows Ctrl+A convention by default.
    def select_all(event):
        if event.keycode == 65:
            entry.selection_range(0, 'end')
            return 'break'
    # Match the VK code so the test also works with the Thai keyboard layout.
    entry.bind('<Control-KeyPress>', select_all)
    counters = {'clicks': 0, 'wheel': 0, 'drag_moves': 0, 'drag_up': 0}
    button = tk.Button(root, text='Test click', command=lambda: counters.update(clicks=counters['clicks']+1))
    button.pack(pady=15)
    area = tk.Text(root, height=8)
    area.pack(fill='both', expand=True, padx=20, pady=10)
    area.insert('1.0', '\n'.join(f'Test row {i}' for i in range(100)))
    area.bind('<MouseWheel>', lambda event: counters.update(wheel=counters['wheel']+1), add='+')
    area.bind('<B1-Motion>', lambda event: counters.update(drag_moves=counters['drag_moves']+1), add='+')
    area.bind('<ButtonRelease-1>', lambda event: counters.update(drag_up=counters['drag_up']+1), add='+')
    root.update()
    # Native checkbox gives UIA a real named control with queryable state.
    import ctypes as C
    from ctypes import wintypes as W
    native = C.WinDLL('user32', use_last_error=True)
    native.CreateWindowExW.argtypes = [W.DWORD, W.LPCWSTR, W.LPCWSTR, W.DWORD,
        C.c_int, C.c_int, C.c_int, C.c_int, W.HWND, W.HMENU, W.HINSTANCE, C.c_void_p]
    native.CreateWindowExW.restype = W.HWND
    native.SendMessageW.argtypes = [W.HWND, W.UINT, W.WPARAM, W.LPARAM]
    native.SendMessageW.restype = W.LPARAM
    checkbox = native.CreateWindowExW(0, 'BUTTON', 'UIA check test', 0x50000003,
        420, 5, 200, 25, root.winfo_id(), None, None, None)
    assert checkbox, 'Cannot create native test checkbox'
    positions = {name: (widget.winfo_x()+widget.winfo_width()//2,
                        widget.winfo_y()+widget.winfo_height()//2)
                 for name, widget in [('entry', entry), ('button', button), ('area', area)]}
    logical_size = (root.winfo_width(), root.winfo_height())
    requests = queue.Queue()
    result = {'exit': 1}

    def pump():
        try:
            response = requests.get_nowait()
            response.put((entry.get(), {**counters, 'checked': int(native.SendMessageW(checkbox, 0x00F0, 0, 0))}))
        except queue.Empty:
            pass
        if result.get('done'):
            root.destroy()
        else:
            root.after(20, pump)

    def values():
        response = queue.Queue()
        requests.put(response)
        return response.get(timeout=5)

    def worker():
        client = McpStdioClient()
        def call(name, args):
            response = client.request('tools/call', {'name': name, 'arguments': args})['result']
            if response.get('isError'):
                raise AssertionError(str(response['content'])[:500])
            return json.loads(next(b['text'] for b in response['content'] if b['type'] == 'text'))
        try:
            client.request('initialize', {'protocolVersion': '2024-11-05', 'capabilities': {}, 'clientInfo': {'name': 'isolated-live-test', 'version': '1'}})
            windows = call('desktop_list_windows', {})['windows']
            matches = [w for w in windows if w['title'] == 'mimo-desktop isolated input test']
            assert len(matches) == 1, 'Expected exactly one disposable test window'
            hwnd = matches[0]['hwnd']
            scale = [1.0, 1.0]
            def observe():
                state = call('desktop_observe', {'hwnd': hwnd, 'focus': True})
                scale[:] = [state['width']/logical_size[0], state['height']/logical_size[1]]
                return state['observation_id']
            def click(widget):
                token = observe()
                x, y = positions[widget]
                call('desktop_click', {'observation_id': token, 'x': round(x*scale[0]), 'y': round(y*scale[1])})
                time.sleep(.1)
            click('entry')
            call('desktop_type_text', {'observation_id': observe(), 'text': 'MCP ไทย 123'})
            time.sleep(.15)
            assert values()[0] == 'MCP ไทย 123', values()[0]
            print('PASS real click + Unicode typing via MCP')
            call('desktop_press_key', {'observation_id': observe(), 'key': 'Ctrl+A'})
            call('desktop_type_text', {'observation_id': observe(), 'text': 'replacement'})
            time.sleep(.15)
            assert values()[0] == 'replacement', values()[0]
            print('PASS real Ctrl+A and replacement')
            click('button')
            assert values()[1]['clicks'] == 1, values()[1]
            print('PASS real button invocation')
            click('area')
            x, y = positions['area']
            token = observe()
            call('desktop_scroll', {'observation_id': token, 'x': round(x*scale[0]), 'y': round(y*scale[1]), 'ticks': -3})
            time.sleep(.15)
            assert values()[1]['wheel'] > 0
            print('PASS real wheel event')
            before = values()[1]
            token = observe()
            call('desktop_drag', {'observation_id': token,
                 'from_x': round((x-100)*scale[0]), 'from_y': round((y-30)*scale[1]),
                 'to_x': round((x+100)*scale[0]), 'to_y': round((y+30)*scale[1]),
                 'via': [{'x': round(x*scale[0]), 'y': round(y*scale[1])}], 'duration_ms': 500})
            time.sleep(.15)
            after = values()[1]
            assert after['drag_moves'] > before['drag_moves'], after
            assert after['drag_up'] == before['drag_up']+1, after
            print('PASS real multi-point drag motion and button release')
            state = call('desktop_inspect', {'hwnd': hwnd, 'focus': True})
            assert state['elements'], 'UIA returned no elements'
            root_element = next(e for e in state['elements'] if e['name'] == 'mimo-desktop isolated input test')
            check = call('desktop_verify_element', {'observation_id': state['observation_id'],
                'element_index': root_element['element_index'], 'expected_name': 'mimo-desktop isolated input test'})
            assert check['matched'], check
            print('PASS real UIA tree and exact window-name verification')
            state = call('desktop_inspect', {'hwnd': hwnd, 'focus': True})
            checkbox_element = next(e for e in state['elements'] if e['name'] == 'UIA check test')
            call('desktop_click_element', {'observation_id': state['observation_id'],
                'element_index': checkbox_element['element_index']})
            time.sleep(.1)
            assert values()[1]['checked'] == 1
            print('PASS real UIA-selected checkbox click and checked-state verification')
            moved = call('desktop_set_window_rect', {'observation_id': observe(),
                'x': 100, 'y': 100, 'width': 800, 'height': 600})
            assert moved['matched'], moved
            print('PASS real window move/resize with actual geometry check')
            result['exit'] = 0
        except Exception as exc:
            print(f'FAIL {type(exc).__name__}: {ascii(str(exc))}')
        finally:
            client.close()
            result['done'] = True
    root.after(20, pump)
    threading.Thread(target=worker, daemon=True).start()
    root.mainloop()
    return result['exit']


if __name__ == '__main__':
    raise SystemExit(main())
