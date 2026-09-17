"""Regression checks for complete, bounded Desktop API JSON reads."""
import io
import json
import unittest
import urllib.error
from unittest.mock import patch

import server


class BodyTests(unittest.TestCase):
    def request(self, payload, limit=server.MAX_BODY, error=False):
        response = io.BytesIO(payload)
        response.status = 200
        effect = urllib.error.HTTPError('http://localhost', 413, 'large', {}, response) if error else None
        with patch.object(server, 'load_desktop_api', return_value={'ok': True, 'port': 1, 'token': 'test'}), patch.object(server, 'MAX_BODY', limit), patch.object(server.urllib.request, 'urlopen', return_value=response, side_effect=effect):
            return server.api_request('GET', '/v1/test')

    def test_history_over_old_limit(self):
        history = [{'text': 'x' * 2_100_000}]
        self.assertEqual(self.request(json.dumps(history).encode()), (200, history))

    def test_exact_limit(self):
        self.assertEqual(self.request(b'[123]', 5), (200, [123]))

    def test_over_limit_refused(self):
        for error in (False, True):
            with self.subTest(error=error), self.assertRaisesRegex(RuntimeError, 'exceeded 5 bytes'):
                self.request(b'[1234]', 5, error)


class ToolErrorContractTests(unittest.TestCase):
    """A failed tool call must stay machine-readable.

    The desktop handlers return a structured payload (ok/status/error/next_action) for
    the failures they expect. An unexpected exception — a missing optional dependency
    is the usual one — used to escape that contract as a bare string, which a client
    that parses the payload cannot interpret.
    """

    def call(self, handler):
        with patch.dict(server.TOOLS_BY_NAME, {'probe': {'handler': handler}}):
            return server.handle_tools_call({'name': 'probe', 'arguments': {}})

    def payload(self, result):
        return json.loads(next(b['text'] for b in result['content'] if b['type'] == 'text'))

    def test_unexpected_exception_stays_parseable(self):
        def boom(_args):
            raise ModuleNotFoundError("No module named 'PIL'")
        result = self.call(boom)
        self.assertTrue(result['isError'])
        body = self.payload(result)
        self.assertIs(body['ok'], False)
        self.assertEqual(body['status'], 'operation_failed')
        self.assertIn('ModuleNotFoundError', body['error'])
        self.assertIn('PIL', body['error'])
        self.assertIs(body['retry_automatically'], False)
        self.assertIn('next_action', body)

    def test_handled_error_payload_is_untouched(self):
        def refuse(_args):
            return {'ok': False, 'status': 'invalid_state_or_argument', 'error': 'nope'}
        result = self.call(refuse)
        self.assertTrue(result['isError'])
        self.assertEqual(self.payload(result)['status'], 'invalid_state_or_argument')

    def test_success_is_not_marked_as_error(self):
        result = self.call(lambda _args: {'ok': True, 'value': 1})
        self.assertFalse(result['isError'])
        self.assertEqual(self.payload(result)['value'], 1)


if __name__ == '__main__':
    unittest.main()
