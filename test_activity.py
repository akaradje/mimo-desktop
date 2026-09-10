import os
import queue
import unittest
from unittest.mock import Mock, patch
from activity import Activity


class ActivityTests(unittest.TestCase):
    @patch.dict(os.environ, {'MIMO_DESKTOP_OVERLAY': '0'})
    def test_disabled_never_starts_worker(self):
        activity = Activity()
        activity.emit('click')
        self.assertIsNone(activity.thread)

    @patch.dict(os.environ, {'MIMO_DESKTOP_OVERLAY': '1'})
    def test_full_queue_does_not_block(self):
        activity = Activity()
        activity.thread = Mock()
        activity.events = queue.Queue(maxsize=1)
        activity.emit('click')
        activity.emit('click', 'done')
        self.assertEqual(activity.events.qsize(), 1)

    @patch.dict(os.environ, {'MIMO_DESKTOP_OVERLAY': '1'})
    def test_only_operation_state_and_time(self):
        activity = Activity()
        activity.thread = Mock()
        activity.emit('paste_text')
        self.assertEqual(set(activity.events.get()), {'operation', 'state', 'time'})


if __name__ == '__main__':
    unittest.main()
