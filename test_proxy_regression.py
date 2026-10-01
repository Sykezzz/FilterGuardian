import unittest
from unittest.mock import patch
import urllib.error
import urllib.request
import filter_test


class Response:
    status = 200

    def __init__(self, content):
        self.content = content

    def read(self, size):
        return self.content[:size]


class ProxyRegression(unittest.TestCase):
    def check_response(self, content, expected):
        # Autospec rejects unsupported context= on OpenerDirector.open.
        with patch.object(urllib.request.OpenerDirector, 'open', autospec=True,
                          return_value=Response(content)) as request:
            result = filter_test.test_via_proxy('https://arcade.example/game', 'localhost:8080')
        self.assertEqual(result['result'], expected)
        self.assertEqual(request.call_args.kwargs, {'timeout': 10})

    def test_allowed(self):
        self.check_response(b'<title>Learning Portal</title>', 'allowed')

    def test_block_page(self):
        self.check_response(b'<title>Access denied</title>', 'blocked')

    def test_proxy_unreachable(self):
        with patch.object(urllib.request.OpenerDirector, 'open', autospec=True,
                          side_effect=urllib.error.URLError('connection refused')):
            self.assertEqual(filter_test.test_via_proxy('https://arcade.example', 'localhost:8080'),
                             {'result': 'error', 'detail': 'Proxy unreachable'})


if __name__ == '__main__':
    unittest.main()
