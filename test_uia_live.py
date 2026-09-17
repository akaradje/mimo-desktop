"""Opt-in live check of the two UI Automation tools that need a real provider.

Run explicitly: python test_uia_live.py --run [--hwnd N]

Requires pywinauto in the interpreter that runs this file, because the server
inherits it (see requirements.txt). Read-only: no clicks, typing, or keys are
sent. desktop_verify_text enforces focus, so the window that was in front is
restored on exit. Nothing is created and no user document is modified.

Both checks derive their expected values from the live provider instead of
hardcoding names, so the test works on any desktop.
"""
import ctypes
import json
import sys
import time

from test_mcp_client import McpStdioClient

ABSENT_NAME = 'zzz-uia-live-absent-do-not-create-9f2c'
TEXT_TYPES = ('Edit', 'Document')


def _pywinauto():
    try:
        from pywinauto.controls.uiawrapper import UIAWrapper
        from pywinauto.uia_element_info import UIAElementInfo
    except ImportError as exc:
        raise SystemExit(f'pywinauto is required for this test: {exc}')
    return UIAWrapper, UIAElementInfo


def read_control_value(hwnd, wanted):
    """Read a control's text out-of-band, to supply a known-good expected value."""
    UIAWrapper, UIAElementInfo = _pywinauto()
    import collections
    pending, seen = collections.deque([UIAElementInfo(hwnd)]), 0
    while pending and seen < 200:
        node = pending.popleft()
        seen += 1
        try:
            wrapper = UIAWrapper(node)
            if wrapper.element_info.control_type in wanted:
                try:
                    return wrapper.iface_value.CurrentValue, 'ValuePattern'
                except Exception:
                    return wrapper.iface_text.DocumentRange.GetText(4097), 'TextPattern'
            pending.extend(node.children())
        except Exception:
            continue
    return None, None


def main():
    if '--run' not in sys.argv:
        print('Opt-in: pass --run to exercise the live UI Automation provider.')
        return 0
    _pywinauto()  # fail early with a clear message rather than mid-run
    explicit_hwnd = None
    if '--hwnd' in sys.argv:
        explicit_hwnd = int(sys.argv[sys.argv.index('--hwnd') + 1])

    user32 = ctypes.WinDLL('user32')
    original_foreground = user32.GetForegroundWindow()
    client = McpStdioClient()
    failures = []

    def call(name, args):
        response = client.request('tools/call', {'name': name, 'arguments': args})['result']
        text = next(b['text'] for b in response['content'] if b['type'] == 'text')
        try:
            payload = json.loads(text)
        except ValueError:
            payload = {'ok': False, 'error': text[:300]}
        payload['_isError'] = bool(response.get('isError'))
        return payload

    def check(label, condition, detail):
        print(f'{"PASS" if condition else "FAIL"} {label}: {detail}')
        if not condition:
            failures.append(label)

    try:
        client.request('initialize', {'protocolVersion': '2024-11-05', 'capabilities': {},
                                      'clientInfo': {'name': 'uia-live-test', 'version': '1'}})

        # --- element_present, using a name the provider itself reports ----------
        windows = call('desktop_list_windows', {})['windows']
        shell = next((w for w in windows if w['title'] == 'Program Manager'), None)
        if shell is None:
            print('SKIP element_present: no Program Manager window to read names from')
        else:
            tree = call('desktop_inspect', {'hwnd': shell['hwnd']})
            if tree.get('_isError'):
                check('element_present', False, f"inspect failed: {tree.get('error')}")
            else:
                known = next((row['name'] for row in tree.get('elements', []) if row['name']), None)
                if known is None:
                    print('SKIP element_present: provider returned no named elements')
                else:
                    hit = call('desktop_wait_for', {'condition': 'element_present',
                                                    'hwnd': shell['hwnd'],
                                                    'name_exact': known, 'timeout_ms': 10000})
                    check('element_present hit', hit.get('satisfied') is True
                          and hit.get('outcome') == 'condition_met',
                          f'name={known!r} outcome={hit.get("outcome")} attempts={hit.get("attempts")}')

                    miss = call('desktop_wait_for', {'condition': 'element_present',
                                                     'hwnd': shell['hwnd'],
                                                     'name_exact': ABSENT_NAME,
                                                     'timeout_ms': 2000, 'interval_ms': 500})
                    check('element_present miss', miss.get('satisfied') is False
                          and miss.get('outcome') == 'condition_not_met',
                          f'outcome={miss.get("outcome")} attempts={miss.get("attempts")}')

        # --- verify_text against a live text control ----------------------------
        candidates = [explicit_hwnd] if explicit_hwnd else [w['hwnd'] for w in windows]
        target = None
        for hwnd in candidates[:12]:
            probe = call('desktop_inspect', {'hwnd': hwnd})
            if probe.get('_isError'):
                continue
            control = next((row for row in probe.get('elements', [])
                            if row['control_type'] in TEXT_TYPES), None)
            if control is not None:
                target = (hwnd, control)
                break
        if target is None:
            print('SKIP verify_text: no visible window exposed an Edit or Document control')
        else:
            hwnd, control = target
            print(f'     verify_text target hwnd={hwnd} control={control["control_type"]} '
                  f'name={control["name"][:40]!r}')

            # inspect with focus=true: verify_text requires the window in front, and the
            # server tracks FocusRequired per window, so focus must go through the tool.
            focused = call('desktop_inspect', {'hwnd': hwnd, 'focus': True})
            if focused.get('_isError'):
                check('verify_text', False, f"focused inspect failed: {focused.get('error')}")
            else:
                row = next((r for r in focused.get('elements', [])
                            if r['control_type'] == control['control_type']), None)
                true_value, backend = read_control_value(hwnd, (control['control_type'],))
                if row is None or true_value is None:
                    print('SKIP verify_text: could not resolve the control or its value')
                else:
                    good = call('desktop_verify_text', {'observation_id': focused['observation_id'],
                                                        'element_index': row['element_index'],
                                                        'expected_text': true_value})
                    check('verify_text match', good.get('verification') == 'verified'
                          and good.get('matched') is True,
                          f'backend={good.get("backend")} read={backend} len={good.get("actual_length")}')

                    again = call('desktop_inspect', {'hwnd': hwnd, 'focus': True})
                    row2 = next((r for r in again.get('elements', [])
                                 if r['control_type'] == control['control_type']), None)
                    if row2 is not None:
                        bad = call('desktop_verify_text', {'observation_id': again['observation_id'],
                                                           'element_index': row2['element_index'],
                                                           'expected_text': ABSENT_NAME})
                        check('verify_text mismatch', bad.get('verification') == 'mismatch'
                              and bad.get('matched') is False,
                              f'verification={bad.get("verification")} matched={bad.get("matched")}')
    except Exception as exc:
        print(f'FAIL {type(exc).__name__}: {ascii(str(exc))}')
        failures.append(type(exc).__name__)
    finally:
        client.close()
        if original_foreground:
            user32.SetForegroundWindow(original_foreground)
        print(f'restored foreground hwnd={original_foreground}')

    print(f'\n{len(failures)} failure(s)' + (f': {failures}' if failures else ''))
    return 1 if failures else 0


if __name__ == '__main__':
    raise SystemExit(main())
