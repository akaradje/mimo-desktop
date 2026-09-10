import subprocess
import unittest
from unittest.mock import Mock, patch
import uia_reader


class ReaderTests(unittest.TestCase):
    @patch.object(uia_reader.subprocess, 'run')
    def test_timeout_bounded(self, run):
        run.side_effect = subprocess.TimeoutExpired('worker', 8)
        with self.assertRaisesRegex(RuntimeError, 'timed out'):
            uia_reader.read_ui(10)
        self.assertEqual(run.call_args.kwargs['timeout'], 8)

    @patch.object(uia_reader.subprocess, 'run')
    def test_malformed_response(self, run):
        run.return_value = Mock(returncode=0, stdout=b'not json')
        with self.assertRaisesRegex(RuntimeError, 'invalid response'):
            uia_reader.read_ui(10)

    @patch.object(uia_reader.subprocess, 'run')
    def test_worker_error(self, run):
        run.return_value = Mock(returncode=0, stdout=b'{"ok":false,"error":"provider unavailable"}')
        with self.assertRaisesRegex(RuntimeError, 'provider unavailable'):
            uia_reader.read_ui(10)


if __name__ == '__main__':
    unittest.main()
