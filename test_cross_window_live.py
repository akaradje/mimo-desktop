"""Opt-in real MCP drag test between two disposable Tk windows (not OLE)."""
import json
import queue
import sys
import threading
import time
import tkinter as tk
from test_mcp_client import McpStdioClient


def main():
    if '--run' not in sys.argv:
        print('Pass --run to test real cross-window input in disposable windows.')
        return 0
    root = tk.Tk()
    root.title('MCP drag source test')
    root.geometry('300x220+50+100')
    target = tk.Toplevel(root)
    target.title('MCP drag destination test')
    target.geometry('300x220+400+100')
    tk.Label(root, text='Drag test payload from here', bg='lightblue').pack(fill='both', expand=True)
    label = tk.Label(target, text='Drop destination', bg='lightgreen')
    label.pack(fill='both', expand=True)
    state = {'drops': 0, 'ctrl': False, 'held': False, 'exit': 1}
    def down(event):
        state['held'] = True
    def up(event):
        if state['held'] and target.winfo_rootx() <= event.x_root < target.winfo_rootx()+target.winfo_width() and target.winfo_rooty() <= event.y_root < target.winfo_rooty()+target.winfo_height():
            state['drops'] += 1
            state['ctrl'] = bool(event.state & 4)
            label.config(text='Payload received')
        state['held'] = False
    root.bind('<ButtonPress-1>', down)
    root.bind('<ButtonRelease-1>', up)
    queries = queue.Queue()
    def pump():
        try:
            reply = queries.get_nowait()
            reply.put(dict(state))
        except queue.Empty:
            pass
        if state.get('done'):
            root.destroy()
        else:
            root.after(20, pump)
    def snapshot():
        reply = queue.Queue()
        queries.put(reply)
        return reply.get(timeout=5)
    def worker():
        client = McpStdioClient()
        def call(name, args):
            result = client.request('tools/call', {'name': name, 'arguments': args})['result']
            if result.get('isError'):
                raise AssertionError(str(result['content'])[:500])
            return json.loads(next(b['text'] for b in result['content'] if b['type'] == 'text'))
        try:
            client.request('initialize', {'protocolVersion': '2024-11-05', 'capabilities': {}, 'clientInfo': {'name': 'cross-window-test', 'version': '1'}})
            windows = call('desktop_list_windows', {})['windows']
            def find(title):
                matches = [w for w in windows if w['title'] == title]
                assert len(matches) == 1
                return matches[0]['hwnd']
            source_hwnd, dest_hwnd = find('MCP drag source test'), find('MCP drag destination test')
            for i, modifiers in enumerate([[], ['ctrl']]):
                dest = call('desktop_observe', {'hwnd': dest_hwnd})
                source = call('desktop_observe', {'hwnd': source_hwnd, 'focus': True, 'retain_previous': True})
                call('desktop_drag_between', {'observation_id': source['observation_id'],
                    'destination_observation_id': dest['observation_id'],
                    'from_x': source['width']//2, 'from_y': source['height']//2,
                    'to_x': dest['width']//2, 'to_y': dest['height']//2,
                    'duration_ms': 500, 'modifiers': modifiers})
                time.sleep(.15)
                observed = snapshot()
                assert observed['drops'] == i+1 and not observed['held'], observed
                assert observed['ctrl'] == bool(modifiers), observed
                print('PASS cross-window payload drop' + (' with Ctrl' if modifiers else ''))
            state['exit'] = 0
        except Exception as exc:
            print('FAIL', ascii(str(exc)))
        finally:
            client.close()
            state['done'] = True
    root.after(20, pump)
    threading.Thread(target=worker, daemon=True).start()
    root.mainloop()
    return state['exit']


if __name__ == '__main__':
    raise SystemExit(main())
