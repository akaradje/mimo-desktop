import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import uia_reader
import uia_worker


# A stub that speaks the worker's line protocol, so the transport can be tested
# without depending on an installed UI Automation provider.
ECHO_STUB = """
import json
import sys
sys.stdout.reconfigure(encoding="utf-8")
for line in sys.stdin.buffer:
    line = line.strip()
    if not line:
        continue
    request = json.loads(line)
    sys.stdout.write(json.dumps({"id": request["id"], "ok": True, "echo": request["hwnd"]}) + chr(10))
    sys.stdout.flush()
"""

HANG_STUB = """
import time
time.sleep(600)
"""


class FakeWorker:
    """Records construction, requests, and disposal without spawning a process."""

    instances = []
    script = []

    def __init__(self, *args, **kwargs):
        self.requests = []
        self.stopped = False
        FakeWorker.instances.append(self)

    def start(self):
        pass

    def stop(self):
        self.stopped = True

    def request(self, hwnd, verification=None):
        self.requests.append((hwnd, verification))
        item = FakeWorker.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class TransportTests(unittest.TestCase):
    def stub(self, source):
        path = Path(tempfile.mkdtemp(prefix='uia-stub-')) / 'stub_worker.py'
        path.write_text(source, encoding='utf-8')
        return str(path)

    def test_round_trip_reuses_one_process(self):
        worker = uia_reader.UiaWorker(timeout=10, script=self.stub(ECHO_STUB))
        worker.start()
        try:
            first = worker.request(10)
            second = worker.request(20)
        finally:
            worker.stop()
        self.assertEqual(first, {'id': 1, 'ok': True, 'echo': 10})
        self.assertEqual(second, {'id': 2, 'ok': True, 'echo': 20})

    def test_timeout_reports_seconds_and_leaves_no_process(self):
        worker = uia_reader.UiaWorker(timeout=0.5, script=self.stub(HANG_STUB))
        worker.start()
        with self.assertRaisesRegex(RuntimeError, 'timed out after 0.5 seconds'):
            worker.request(10)
        worker.stop()
        self.assertIsNone(worker.process)

    def test_dead_worker_is_replaced_before_sending(self):
        worker = uia_reader.UiaWorker(timeout=10, script=self.stub(ECHO_STUB))
        worker.start()
        try:
            worker.process.kill()
            worker.process.wait()
            # Nothing was sent to the dead process, so replacing it cannot duplicate work.
            self.assertEqual(worker.request(30)['echo'], 30)
        finally:
            worker.stop()


class ReaderTests(unittest.TestCase):
    def setUp(self):
        FakeWorker.instances = []
        FakeWorker.script = []
        uia_reader._worker = None
        self.addCleanup(setattr, uia_reader, '_worker', None)
        patch.object(uia_reader, 'UiaWorker', FakeWorker).start()
        self.addCleanup(patch.stopall)

    def test_worker_is_reused_across_calls(self):
        FakeWorker.script = [{'ok': True, 'elements': []}, {'ok': True, 'elements': []}]
        uia_reader.read_ui(10)
        uia_reader.read_ui(20)
        self.assertEqual(len(FakeWorker.instances), 1)
        self.assertEqual([call[0] for call in FakeWorker.instances[0].requests], [10, 20])

    def test_failed_worker_is_discarded_and_replaced(self):
        FakeWorker.script = [
            RuntimeError('UI Automation timed out after 8 seconds; provider may be unresponsive'),
            {'ok': True, 'elements': []}]
        with self.assertRaisesRegex(RuntimeError, 'timed out'):
            uia_reader.read_ui(10)
        self.assertTrue(FakeWorker.instances[0].stopped)
        self.assertIsNone(uia_reader._worker)
        uia_reader.read_ui(10)
        self.assertEqual(len(FakeWorker.instances), 2)

    def test_provider_error_keeps_the_worker(self):
        FakeWorker.script = [{'ok': False, 'error': 'provider unavailable'}]
        with self.assertRaisesRegex(RuntimeError, 'provider unavailable'):
            uia_reader.read_ui(10)
        # A provider that answered is not a broken transport.
        self.assertEqual(len(FakeWorker.instances), 1)
        self.assertFalse(FakeWorker.instances[0].stopped)
        self.assertIsNotNone(uia_reader._worker)

    def test_transport_id_is_not_leaked_to_callers(self):
        FakeWorker.script = [{'ok': True, 'id': 1, 'elements': []}]
        self.assertEqual(uia_reader.read_ui(10), {'ok': True, 'elements': []})

    def test_verification_payload_is_forwarded(self):
        FakeWorker.script = [{'ok': True, 'verification': 'verified', 'matched': True}]
        payload = {'runtime_id': [1, 2], 'expected_text': 'hello'}
        result = uia_reader.read_ui(10, payload)
        self.assertEqual(FakeWorker.instances[0].requests[0], (10, payload))
        self.assertTrue(result['matched'])


class OneShotTests(unittest.TestCase):
    """The diagnostic entry point must accept the same request shape as serve.

    It previously read hwnd only from argv and forwarded the whole request as the
    verification payload, so a diagnostic run did not reproduce what the server
    sends and a missing argument surfaced as 'list index out of range'.
    """

    def resolve(self, argv, raw):
        return uia_worker.one_shot(argv, io.BytesIO(raw))

    def test_hwnd_is_accepted_from_json_like_serve(self):
        hwnd, verification = self.resolve([], b'{"hwnd": 42}')
        self.assertEqual(hwnd, 42)
        self.assertIsNone(verification)

    def test_hwnd_is_accepted_positionally(self):
        hwnd, verification = self.resolve(['99'], b'{}')
        self.assertEqual(hwnd, 99)
        self.assertIsNone(verification)

    def test_json_hwnd_wins_over_positional(self):
        hwnd, _ = self.resolve(['99'], b'{"hwnd": 42}')
        self.assertEqual(hwnd, 42)

    def test_verification_is_unwrapped_not_the_whole_request(self):
        payload = {'runtime_id': [1, 2], 'expected_text': 'hi'}
        request = json.dumps({'hwnd': 7, 'verification': payload}).encode()
        hwnd, verification = self.resolve([], request)
        self.assertEqual(hwnd, 7)
        self.assertEqual(verification, payload)

    def test_missing_hwnd_names_both_forms(self):
        with self.assertRaises(ValueError) as caught:
            self.resolve([], b'{}')
        self.assertIn('stdin', str(caught.exception))
        self.assertIn('argument', str(caught.exception))

    def test_non_integer_hwnd_is_rejected(self):
        with self.assertRaises(ValueError) as caught:
            self.resolve([], b'{"hwnd": "abc"}')
        self.assertIn('integer', str(caught.exception))

    def test_malformed_json_is_rejected_clearly(self):
        with self.assertRaises(ValueError) as caught:
            self.resolve([], b'not json')
        self.assertIn('JSON', str(caught.exception))

    def test_non_object_request_is_rejected(self):
        with self.assertRaises(ValueError):
            self.resolve([], b'[1, 2]')


if __name__ == '__main__':
    unittest.main()
