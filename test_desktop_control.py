import copy
import ctypes
import time
import unittest
from unittest.mock import Mock, patch

import desktop_control as d


class DesktopTests(unittest.TestCase):
    def setUp(self):
        patch.object(d.activity, 'emit').start()
        self.api = patch.object(d, 'U').start()
        self.addCleanup(patch.stopall)
        self.desktop = d.Desktop(Mock(), Mock(), Mock())
        self.w = {'hwnd': 10, 'pid': 20, 'path': 'test.exe', 'minimized': False,
                  'client': {'x': -500, 'y': 100, 'width': 300, 'height': 200}}
        self.desktop.window = Mock(return_value=copy.deepcopy(self.w))
        self.api.GetForegroundWindow.return_value = 10
        self.api.GetAsyncKeyState.return_value = 0
        self.api.WindowFromPoint.return_value = 10
        self.api.GetAncestor.return_value = 10
        self.api.SendInput.side_effect = lambda count, *_: count
        self.token()

    def token(self, age=0):
        self.desktop.observations['test'] = (time.monotonic()-age, copy.deepcopy(self.w))

    def test_input_structure_native_size(self):
        self.assertEqual(ctypes.sizeof(d.Input), 40 if ctypes.sizeof(ctypes.c_void_p) == 8 else 28)

    def test_one_use_observation(self):
        self.desktop.target({'observation_id': 'test'})
        with self.assertRaises(ValueError):
            self.desktop.target({'observation_id': 'test'})

    def test_stale_observation(self):
        self.token(61)
        with self.assertRaises(ValueError):
            self.desktop.target({'observation_id': 'test'})

    def test_window_change_rejected(self):
        for field, value in [('pid', 21), ('path', 'other.exe'), ('minimized', True),
                             ('client', {'x': 0, 'y': 0, 'width': 300, 'height': 200})]:
            self.token()
            self.desktop.window.return_value = {**self.w, field: value}
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.desktop.target({'observation_id': 'test'})
        self.api.SendInput.assert_not_called()

    def test_lost_foreground(self):
        self.api.GetForegroundWindow.return_value = 99
        with self.assertRaises(ValueError):
            self.desktop.type_text({'observation_id': 'test', 'text': 'hello'})
        self.api.SendInput.assert_not_called()

    def test_held_modifier(self):
        self.api.GetAsyncKeyState.return_value = 0x8000
        with self.assertRaises(ValueError):
            self.desktop.target({'observation_id': 'test'})

    def test_click_negative_monitor(self):
        self.desktop.click({'observation_id': 'test', 'x': 20, 'y': 30})
        self.api.SetCursorPos.assert_called_with(-480, 130)
        self.assertEqual(self.api.SendInput.call_args.args[0], 2)

    def test_occluded_point(self):
        self.api.GetAncestor.return_value = 99
        with self.assertRaises(ValueError):
            self.desktop.click({'observation_id': 'test', 'x': 20, 'y': 30})
        self.api.SendInput.assert_not_called()

    def test_bounds_and_types(self):
        for x in [-1, 300, True, 1.5]:
            self.token()
            with self.subTest(x=x), self.assertRaises(ValueError):
                self.desktop.click({'observation_id': 'test', 'x': x, 'y': 10})
        self.api.SendInput.assert_not_called()

    def test_unicode_surrogates(self):
        text = 'ไทย🙂'
        self.desktop.type_text({'observation_id': 'test', 'text': text})
        count, events, _ = self.api.SendInput.call_args.args
        raw = b''.join(int(events[i].payload.ki.scan).to_bytes(2, 'little') for i in range(0, count, 2))
        self.assertEqual(raw.decode('utf-16-le'), text)
        self.assertTrue(all(events[i].payload.ki.flags == 6 for i in range(1, count, 2)))

    def test_control_text_rejected(self):
        with self.assertRaises(ValueError):
            self.desktop.type_text({'observation_id': 'test', 'text': 'hello\n'})
        self.api.SendInput.assert_not_called()

    def test_key_chord_order(self):
        events = d.key_events('Ctrl+Shift+A')
        self.assertEqual([e.payload.ki.vk for e in events], [17, 16, 65, 65, 16, 17])
        self.assertEqual([e.payload.ki.flags for e in events], [0, 0, 0, 2, 2, 2])
        for key in ['Ctrl+Ctrl+A', 'Bogus', 'Ctrl+', 3]:
            with self.assertRaises(ValueError):
                d.key_events(key)

    def test_scroll_direction(self):
        self.desktop.scroll({'observation_id': 'test', 'x': 2, 'y': 3, 'ticks': -2})
        event = self.api.SendInput.call_args.args[1][0]
        self.assertEqual(event.payload.mi.mouseData, (-120) & 0xffffffff)
        self.assertEqual(self.api.SendInput.call_count, 2)
        self.assertEqual(event.payload.mi.dwFlags, 0x800)

    def test_partial_input_release(self):
        self.api.SendInput.side_effect = [1, 1]
        with self.assertRaisesRegex(RuntimeError, 'partial'):
            d.send(d.key_events('A'))
        self.assertEqual(self.api.SendInput.call_count, 2)
        self.assertEqual(self.api.SendInput.call_args.args[1][0].payload.ki.flags, 2)

    def drag_args(self, **extra):
        return dict(observation_id='test', from_x=10, from_y=20, to_x=150, to_y=100,
                    duration_ms=100, **extra)

    @patch.object(d.time, 'sleep')
    def test_drag_path_and_release(self, _sleep):
        result = self.desktop.drag(self.drag_args(via=[{'x': 80, 'y': 150}]))
        self.assertTrue(result['button_released'])
        self.api.SetCursorPos.assert_any_call(-420, 250)
        self.api.SetCursorPos.assert_called_with(-350, 200)
        self.assertEqual(self.api.SendInput.call_args_list[0].args[1][0].payload.mi.dwFlags, 2)
        self.assertEqual(self.api.SendInput.call_args.args[1][0].payload.mi.dwFlags, 4)

    @patch.object(d.time, 'sleep')
    def test_drag_focus_loss_releases(self, _sleep):
        self.api.GetForegroundWindow.side_effect = [10, 10, 99]
        with self.assertRaises(ValueError):
            self.desktop.drag(self.drag_args())
        self.assertEqual(self.api.SendInput.call_args.args[1][0].payload.mi.dwFlags, 4)

    @patch.object(d.time, 'sleep')
    def test_drag_escape_releases(self, _sleep):
        self.api.GetAsyncKeyState.side_effect = lambda key: 0x8000 if key == 27 else 0
        with self.assertRaisesRegex(RuntimeError, 'cancelled'):
            self.desktop.drag(self.drag_args())
        self.assertEqual(self.api.SendInput.call_args.args[1][0].payload.mi.dwFlags, 4)

    @patch.object(d.time, 'sleep')
    def test_drag_pointer_failure_releases(self, _sleep):
        self.api.SetCursorPos.side_effect = [True, False]
        with self.assertRaisesRegex(RuntimeError, 'pointer'):
            self.desktop.drag(self.drag_args(button='right'))
        self.assertEqual(self.api.SendInput.call_args.args[1][0].payload.mi.dwFlags, 16)

    @patch.object(d, 'animate', return_value={'frames_sent': 1})
    @patch.object(d.time, 'sleep')
    def test_drag_final_dwell_failure_releases(self, sleep, _animate):
        for failure in ('focus', 'escape', 'geometry'):
            with self.subTest(failure=failure):
                self.token()
                self.api.GetForegroundWindow.return_value = 10
                self.api.GetAsyncKeyState.side_effect = None
                self.desktop.window.return_value = copy.deepcopy(self.w)
                self.api.SendInput.reset_mock()
                sleeps = 0

                def interrupt(_seconds):
                    nonlocal sleeps
                    sleeps += 1
                    if sleeps == 2:
                        if failure == 'focus':
                            self.api.GetForegroundWindow.return_value = 99
                        elif failure == 'escape':
                            self.api.GetAsyncKeyState.side_effect = lambda key: 0x8000 if key == 27 else 0
                        else:
                            self.desktop.window.return_value['client']['x'] += 1

                sleep.side_effect = interrupt
                error = RuntimeError if failure == 'escape' else ValueError
                with self.assertRaises(error):
                    self.desktop.drag(self.drag_args(modifiers=['ctrl']))
                up = self.api.SendInput.call_args.args[1]
                self.assertEqual(up[0].payload.mi.dwFlags, 4)
                self.assertEqual(up[1].payload.ki.vk, 17)
                self.assertEqual(up[1].payload.ki.flags, 2)

    def test_drag_invalid_path_no_input(self):
        for via in [[{'x': 301, 'y': 3}], [False], 'invalid', [{}]*65]:
            self.token()
            with self.assertRaises(ValueError):
                self.desktop.drag(self.drag_args(via=via))
        self.api.SendInput.assert_not_called()
        self.api.SetCursorPos.assert_not_called()

    @patch.object(d.time, 'sleep')
    def test_drag_release_retry(self, _sleep):
        self.api.SendInput.side_effect = [1, 0, 1]
        self.desktop.drag(self.drag_args(button='middle'))
        self.assertEqual(self.api.SendInput.call_count, 3)
        self.assertEqual(self.api.SendInput.call_args.args[1][0].payload.mi.dwFlags, 64)

    def test_failed_observe_invalidates_token(self):
        with self.assertRaises(ValueError):
            self.desktop.observe({'hwnd': 10, 'focus': 'bad'})
        self.assertEqual(self.desktop.observations, {})

    @patch.object(d.time, 'sleep')
    def test_drag_geometry_change_releases(self, _sleep):
        self.desktop.window.side_effect = [self.w, self.w, {**self.w, 'pid': 999}]
        with self.assertRaises(ValueError):
            self.desktop.drag(self.drag_args())
        self.assertEqual(self.api.SendInput.call_args.args[1][0].payload.mi.dwFlags, 4)

    @patch.object(d.time, 'sleep')
    def test_drag_occlusion_releases(self, _sleep):
        self.api.GetAncestor.side_effect = [10, 99]
        with self.assertRaises(ValueError):
            self.desktop.drag(self.drag_args())
        self.assertEqual(self.api.SendInput.call_args.args[1][0].payload.mi.dwFlags, 4)

    @patch.object(d.time, 'sleep')
    def test_drag_modifiers_released(self, _sleep):
        self.desktop.drag(self.drag_args(modifiers=['ctrl', 'shift']))
        down = self.api.SendInput.call_args_list[0].args[1]
        self.assertEqual([down[i].payload.ki.vk for i in (0, 1)], [17, 16])
        up = self.api.SendInput.call_args.args[1]
        self.assertEqual(up[0].payload.mi.dwFlags, 4)
        self.assertEqual([up[i].payload.ki.vk for i in (1, 2)], [16, 17])

    def cross_setup(self):
        dest = {**self.w, 'hwnd': 30, 'pid': 40,
                'client': {'x': 200, 'y': 100, 'width': 300, 'height': 200}}
        self.desktop.observations['dest'] = (time.monotonic(), dest)
        self.desktop.window.side_effect = lambda hwnd: copy.deepcopy(dest if hwnd == 30 else self.w)
        self.api.GetAncestor.side_effect = lambda hit, _: hit
        self.api.WindowFromPoint.side_effect = lambda pt: 30 if pt.x >= 200 else 10
        return dict(observation_id='test', destination_observation_id='dest',
                    from_x=10, from_y=20, to_x=150, to_y=100, duration_ms=100)

    @patch.object(d.time, 'sleep')
    def test_cross_window_negative_monitor(self, _sleep):
        args = self.cross_setup()
        result = self.desktop.drag_between(args)
        self.assertTrue(result['button_released'])
        self.api.SetCursorPos.assert_called_with(350, 200)
        self.assertEqual(self.desktop.observations, {})

    @patch.object(d.time, 'sleep')
    def test_cross_window_escape_releases_modifiers(self, _sleep):
        args = self.cross_setup()
        args['modifiers'] = ['alt']
        self.api.GetAsyncKeyState.side_effect = lambda key: 0x8000 if key == 27 else 0
        with self.assertRaisesRegex(RuntimeError, 'cancelled'):
            self.desktop.drag_between(args)
        up = self.api.SendInput.call_args.args[1]
        self.assertEqual(up[0].payload.mi.dwFlags, 4)
        self.assertEqual(up[1].payload.ki.vk, 18)

    def test_cross_window_occluded_destination_no_input(self):
        args = self.cross_setup()
        self.api.WindowFromPoint.side_effect = None
        self.api.WindowFromPoint.return_value = 99
        with self.assertRaises(ValueError):
            self.desktop.drag_between(args)
        self.api.SendInput.assert_not_called()

    def test_drag_invalid_modifiers(self):
        for value in [['ctrl', 'ctrl'], ['windows'], [1], 'ctrl']:
            with self.assertRaises(ValueError):
                self.desktop.drag(self.drag_args(modifiers=value))
        self.api.SendInput.assert_not_called()

    @patch.object(d, 'set_clipboard_text')
    def test_explicit_clipboard_typing(self, clipboard):
        text = 'ทดสอบ mimo-desktop สำเร็จ'
        result = self.desktop.type_text({'observation_id': 'test', 'text': text, 'method': 'clipboard'})
        clipboard.assert_called_once_with(text)
        self.assertTrue(result['clipboard_replaced'])
        batch = self.api.SendInput.call_args.args[1]
        self.assertEqual([batch[i].payload.ki.vk for i in range(4)], [17, 86, 86, 17])

    @patch.object(d, 'set_clipboard_text', side_effect=RuntimeError('busy'))
    def test_clipboard_failure_never_pastes(self, clipboard):
        with self.assertRaises(RuntimeError):
            self.desktop.type_text({'observation_id': 'test', 'text': 'abc', 'method': 'clipboard'})
        self.api.SendInput.assert_not_called()

    @patch.object(d, 'set_clipboard_text')
    def test_clipboard_focus_change_never_pastes(self, clipboard):
        self.api.GetForegroundWindow.side_effect = [10, 99]
        with self.assertRaises(ValueError):
            self.desktop.type_text({'observation_id': 'test', 'text': 'abc', 'method': 'clipboard'})
        self.api.SendInput.assert_not_called()

    @patch.object(d.time, 'sleep')
    def test_focus_refusal_not_retried(self, _sleep):
        self.api.GetForegroundWindow.return_value = 99
        for _ in range(3):
            with self.assertRaises(d.FocusRequired):
                self.desktop.observe({'hwnd': 10, 'focus': True})
        self.api.SetForegroundWindow.assert_called_once_with(10)
        self.api.SendInput.assert_not_called()
        self.assertEqual(self.desktop.observations, {})

    @patch.object(d.time, 'sleep')
    def test_manual_focus_recovers(self, _sleep):
        self.desktop.waiting_for_focus.add(10)
        self.desktop.capture.return_value = (b'pixels', 300, 200, 'test', [])
        self.desktop.blank.return_value = (False, '')
        self.desktop.encode.return_value = b'png'
        result = self.desktop.observe({'hwnd': 10, 'focus': True})
        self.assertTrue(result['ok'])
        self.assertNotIn(10, self.desktop.waiting_for_focus)
        self.assertIn(result['observation_id'], self.desktop.observations)
        self.api.SetForegroundWindow.assert_not_called()

    def test_focus_status_tool_result(self):
        with patch.object(d.Desktop, 'observe', side_effect=d.FocusRequired(10)):
            tool = next(t for t in d.build_tools(Mock(), Mock(), Mock()) if t['name'] == 'desktop_observe')
            result = tool['handler']({'hwnd': 10})
        self.assertFalse(result['ok'])
        self.assertEqual(result['status'], 'waiting_for_focus')
        self.assertFalse(result['retry_automatically'])

    def list_setup(self):
        windows = {
            10: {**self.w, 'title': 'Untitled - Notepad', 'path': r'C:\Windows\System32\notepad.exe', 'pid': 20},
            30: {**self.w, 'hwnd': 30, 'title': 'Documents - File Explorer', 'path': r'C:\Windows\explorer.exe', 'pid': 40},
            50: {**self.w, 'hwnd': 50, 'title': '', 'path': r'C:\hidden.exe', 'pid': 60},
        }
        self.desktop.window.side_effect = lambda hwnd: copy.deepcopy(windows[hwnd])

        def enum(callback, _):
            for hwnd in windows:
                callback(hwnd, 0)
            return 1

        self.api.EnumWindows.side_effect = enum
        return windows

    def test_list_windows_unfiltered(self):
        self.list_setup()
        result = self.desktop.list_windows({})
        # Untitled windows are still excluded by the pre-existing visibility rule.
        self.assertEqual([w['hwnd'] for w in result['windows']], [10, 30])
        self.assertEqual(result['total_visible'], 2)
        self.assertEqual(result['filters'], {})

    def test_list_windows_filters_are_case_insensitive(self):
        self.list_setup()
        self.assertEqual([w['hwnd'] for w in self.desktop.list_windows({'title_contains': 'notepad'})['windows']], [10])
        self.assertEqual([w['hwnd'] for w in self.desktop.list_windows({'path_contains': 'EXPLORER.EXE'})['windows']], [30])
        self.assertEqual([w['hwnd'] for w in self.desktop.list_windows({'pid': 20})['windows']], [10])

    def test_list_windows_filter_reports_unfiltered_total(self):
        self.list_setup()
        result = self.desktop.list_windows({'title_contains': 'no such window'})
        self.assertEqual(result['windows'], [])
        self.assertEqual(result['total_visible'], 2)

    def test_list_windows_invalid_filters_no_enumeration(self):
        for args in ({'title_contains': ''}, {'title_contains': 5}, {'title_contains': 'x' * 201},
                     {'path_contains': ''}, {'path_contains': 5}, {'path_contains': 'x' * 261},
                     {'pid': 0}, {'pid': 'x'}, {'pid': True}):
            with self.subTest(args=args), self.assertRaises(ValueError):
                self.desktop.list_windows(args)
        self.api.EnumWindows.assert_not_called()

    @patch.object(d.time, 'sleep')
    @patch.object(d.time, 'monotonic')
    def test_wait_timeout_is_not_an_error(self, monotonic, sleep):
        self.list_setup()
        clock = {'t': 1000.0}
        monotonic.side_effect = lambda: clock['t']
        sleep.side_effect = lambda seconds: clock.__setitem__('t', clock['t'] + seconds)
        result = self.desktop.wait_for({'condition': 'window_visible', 'title_contains': 'no such window',
                                        'timeout_ms': 1000, 'interval_ms': 250})
        self.assertTrue(result['ok'])
        self.assertFalse(result['satisfied'])
        self.assertEqual(result['elapsed_ms'], 1000)
        self.assertGreaterEqual(result['attempts'], 4)
        self.assertEqual(result['timeout_ms'], 1000)

    def test_wait_window_gone(self):
        self.desktop.window.side_effect = ValueError('window is gone')
        result = self.desktop.wait_for({'condition': 'window_gone', 'hwnd': 10})
        self.assertTrue(result['satisfied'])
        self.assertEqual(result['hwnd'], 10)
        self.assertEqual(result['attempts'], 1)

    @patch.object(d, 'read_ui')
    def test_wait_element_present_by_substring(self, reader):
        reader.return_value = {'elements': [
            {'runtime_id': [1], 'name': 'Cancel', 'control_type': 'Button', 'automation_id': 'c',
             'enabled': True, 'visible': True, 'rect': [0, 0, 10, 10]},
            {'runtime_id': [2], 'name': 'Send message', 'control_type': 'Button', 'automation_id': 's',
             'enabled': True, 'visible': True, 'rect': [0, 0, 10, 10]}]}
        result = self.desktop.wait_for({'condition': 'element_present', 'hwnd': 10, 'name_contains': 'SEND'})
        self.assertTrue(result['satisfied'])
        self.assertEqual(result['element']['name'], 'Send message')
        self.assertNotIn('runtime_id', result['element'])

    @patch.object(d, 'read_ui')
    def test_wait_element_truncated_name_never_matches_exactly(self, reader):
        reader.return_value = {'elements': [
            {'runtime_id': [1], 'name': 'Button', 'name_truncated': True, 'control_type': 'Button',
             'automation_id': 'b', 'enabled': True, 'visible': True, 'rect': [0, 0, 10, 10]}]}
        result = self.desktop.wait_for({'condition': 'element_present', 'hwnd': 10,
                                        'name_exact': 'Button', 'timeout_ms': 100})
        self.assertFalse(result['satisfied'])
        self.assertEqual(result['elements_scanned'], 1)

    @patch.object(d.time, 'sleep')
    @patch.object(d.time, 'monotonic')
    def test_wait_element_interval_has_a_floor(self, monotonic, sleep):
        clock = {'t': 0.0}
        monotonic.side_effect = lambda: clock['t']
        sleep.side_effect = lambda seconds: clock.__setitem__('t', clock['t'] + seconds)
        with patch.object(d, 'read_ui', return_value={'elements': []}):
            result = self.desktop.wait_for({'condition': 'element_present', 'hwnd': 10, 'name_contains': 'x',
                                            'interval_ms': 50, 'timeout_ms': 600})
        self.assertEqual(result['interval_ms'], 500)

    def test_wait_escape_cancels_without_input(self):
        self.api.GetAsyncKeyState.return_value = 0x8000
        with self.assertRaisesRegex(RuntimeError, 'cancelled'):
            self.desktop.wait_for({'condition': 'window_gone', 'hwnd': 10})
        self.api.SendInput.assert_not_called()

    def test_wait_invalid_arguments_no_enumeration(self):
        for args in ({'condition': 'bogus'},
                     {'condition': 'window_visible'},
                     {'condition': 'window_visible', 'title_contains': ''},
                     {'condition': 'window_visible', 'title_contains': 5},
                     {'condition': 'window_gone'},
                     {'condition': 'window_gone', 'hwnd': 0},
                     {'condition': 'element_present', 'hwnd': 10},
                     {'condition': 'element_present', 'hwnd': 10, 'name_contains': 'a', 'name_exact': 'a'},
                     {'condition': 'element_present', 'hwnd': 10, 'name_exact': 5},
                     {'condition': 'window_visible', 'title_contains': 'a', 'timeout_ms': 50},
                     {'condition': 'window_visible', 'title_contains': 'a', 'timeout_ms': 40000},
                     {'condition': 'window_visible', 'title_contains': 'a', 'interval_ms': 10}):
            with self.subTest(args=args), self.assertRaises(ValueError):
                self.desktop.wait_for(args)
        self.api.EnumWindows.assert_not_called()

    def test_wait_tool_result_is_annotated(self):
        tool = next(t for t in d.build_tools(Mock(), Mock(), Mock()) if t['name'] == 'desktop_wait_for')
        with patch.object(d.Desktop, 'wait_for', return_value={'ok': True, 'satisfied': False}):
            result = tool['handler']({'condition': 'window_gone', 'hwnd': 10})
        self.assertEqual(result['outcome'], 'condition_not_met')

    def element_setup(self):
        row = {'runtime_id': [1, 2], 'name': 'Button', 'control_type': 'Button',
               'automation_id': 'test', 'enabled': True, 'visible': True,
               'rect': [-480, 120, -380, 160]}
        self.desktop.elements['test'] = [row]
        return row

    @patch.object(d, 'read_ui')
    def test_element_click_revalidates(self, reader):
        row = self.element_setup()
        reader.return_value = {'elements': [dict(row)]}
        self.desktop.click_element({'observation_id': 'test', 'element_index': 0})
        self.api.SetCursorPos.assert_called_with(-430, 140)
        self.assertEqual(self.api.SendInput.call_args.args[0], 2)

    @patch.object(d, 'read_ui')
    def test_changed_element_rejected(self, reader):
        row = self.element_setup()
        reader.return_value = {'elements': [{**row, 'name': 'Other'}]}
        with self.assertRaises(ValueError):
            self.desktop.click_element({'observation_id': 'test', 'element_index': 0})
        self.api.SendInput.assert_not_called()

    @patch.object(d, 'read_ui')
    def test_disabled_element_rejected(self, reader):
        row = self.element_setup()
        row['enabled'] = False
        reader.return_value = {'elements': [row]}
        with self.assertRaises(ValueError):
            self.desktop.click_element({'observation_id': 'test', 'element_index': 0})
        self.api.SendInput.assert_not_called()

    @patch.object(d, 'read_ui')
    def test_truncated_name_never_exact_match(self, reader):
        row = self.element_setup()
        row['name_truncated'] = True
        reader.return_value = {'elements': [row]}
        result = self.desktop.verify_element({'observation_id': 'test', 'element_index': 0, 'expected_name': 'Button'})
        self.assertFalse(result['matched'])

    @patch.object(d, 'read_ui', side_effect=RuntimeError('timeout'))
    def test_element_timeout_no_input(self, reader):
        self.element_setup()
        with self.assertRaises(RuntimeError):
            self.desktop.click_element({'observation_id': 'test', 'element_index': 0})
        self.api.SendInput.assert_not_called()

    @patch.object(d.time, 'sleep')
    def test_window_geometry_report(self, _sleep):
        def rect(hwnd, pointer):
            pointer._obj.left, pointer._obj.top = 10, 20
            pointer._obj.right, pointer._obj.bottom = 610, 420
            return True
        self.api.GetWindowRect.side_effect = rect
        result = self.desktop.set_window_rect({'observation_id': 'test', 'x': 10, 'y': 20, 'width': 600, 'height': 400})
        self.assertTrue(result['matched'])

    def test_window_geometry_invalid_no_move(self):
        with self.assertRaises(ValueError):
            self.desktop.set_window_rect({'observation_id': 'test', 'x': 0, 'y': 0, 'width': 0, 'height': 400})
        self.api.SetWindowPos.assert_not_called()

    @patch.object(d, 'read_ui')
    def test_verify_text_reads_selected_identity(self, reader):
        row = self.element_setup()
        reader.side_effect = [{'elements': [row]}, {'ok': True, 'verification': 'verified', 'matched': True}]
        result = self.desktop.verify_text({'observation_id': 'test', 'element_index': 0, 'expected_text': 'ไทย English'})
        self.assertTrue(result['matched'])
        self.assertEqual(reader.call_args.args[1]['runtime_id'], row['runtime_id'])
        self.api.SendInput.assert_not_called()

    @patch.object(d, 'set_clipboard_text')
    def test_paste_text_explicit_adapter(self, clipboard):
        result = self.desktop.paste_text({'observation_id': 'test', 'text': 'ไทย English'})
        clipboard.assert_called_once_with('ไทย English')
        self.assertEqual(result['method'], 'clipboard')

    def test_bad_drag_dwell_no_input(self):
        args = self.cross_setup()
        args['drop_ms'] = 100000
        with self.assertRaises(ValueError):
            self.desktop.drag_between(args)
        self.api.SendInput.assert_not_called()


if __name__ == '__main__':
    unittest.main()
