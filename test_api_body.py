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


if __name__ == '__main__':
    unittest.main()
