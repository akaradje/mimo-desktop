import ctypes
import unittest
from unittest.mock import patch
import clipboard_text as clip


class ClipboardTests(unittest.TestCase):
    def setUp(self):
        self.u = patch.object(clip, 'U').start()
        self.k = patch.object(clip, 'K').start()
        patch.object(clip.time, 'sleep').start()
        self.addCleanup(patch.stopall)
        self.buffer = ctypes.create_string_buffer(512)
        self.k.GlobalAlloc.return_value = 100
        self.k.GlobalLock.return_value = ctypes.addressof(self.buffer)
        self.u.CreateWindowExW.return_value = 200
        self.u.OpenClipboard.return_value = True
        self.u.EmptyClipboard.return_value = True
        self.u.SetClipboardData.return_value = 100

    def test_unicode_ownership_transfer(self):
        text = 'ทดสอบ mimo-desktop สำเร็จ'
        clip.set_text(text)
        expected = text.encode('utf-16-le') + b'\0\0'
        self.assertEqual(self.buffer.raw[:len(expected)], expected)
        self.u.SetClipboardData.assert_called_once_with(13, 100)
        self.k.GlobalFree.assert_not_called()
        self.u.CloseClipboard.assert_called_once()
        self.u.DestroyWindow.assert_called_once_with(200)

    def test_busy_preserves_clipboard_and_frees_memory(self):
        self.u.OpenClipboard.return_value = False
        with self.assertRaisesRegex(RuntimeError, 'busy'):
            clip.set_text('text')
        self.assertEqual(self.u.OpenClipboard.call_count, 10)
        self.u.EmptyClipboard.assert_not_called()
        self.k.GlobalFree.assert_called_once_with(100)

    def test_set_failure_frees_memory(self):
        self.u.SetClipboardData.return_value = 0
        with self.assertRaisesRegex(RuntimeError, 'cleared'):
            clip.set_text('text')
        self.k.GlobalFree.assert_called_once_with(100)
        self.u.CloseClipboard.assert_called_once()


if __name__ == '__main__':
    unittest.main()
