import copy
import ctypes
import time
import unittest
from unittest.mock import Mock, patch

import desktop_control as d


class DesktopTests(unittest.TestCase):
    def setUp(self):
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
        self.api.SetCursorPos.assert_called_once_with(-480, 130)
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
        self.assertEqual(event.payload.mi.mouseData, (-240) & 0xffffffff)
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


if __name__ == '__main__':
    unittest.main()
