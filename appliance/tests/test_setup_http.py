import http.client
import importlib.util
import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

setup = Path(__file__).resolve().parents[1] / 'setup'
sys.path.insert(0, str(setup))
spec = importlib.util.spec_from_file_location('first_boot_server', setup / 'server.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class LocalSetupBoundary(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.http = module.HTTPServer(('127.0.0.1', 0), module.Handler)
        self.host = '127.0.0.1:' + str(self.http.server_port)
        self.patches = [patch.object(module, 'ADMIN', root / 'admin.json'),
                        patch.object(module, 'COMPLETE', root / 'complete'),
                        patch.object(module, 'HOSTS', (self.host,))]
        for item in self.patches:
            item.start()
        self.thread = threading.Thread(target=self.http.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.http.shutdown()
        self.http.server_close()
        self.thread.join()
        for item in self.patches:
            item.stop()
        self.temp.cleanup()

    def post(self, path, payload, **overrides):
        headers = {'Host': self.host, 'Origin': 'http://' + self.host,
                   'X-Setup-Token': module.TOKEN, 'Content-Type': 'application/json'}
        headers.update(overrides)
        client = http.client.HTTPConnection('127.0.0.1', self.http.server_port)
        client.request('POST', path, json.dumps(payload), headers)
        response = client.getresponse()
        result = response.status, dict(response.getheaders()), json.load(response)
        client.close()
        return result

    def test_storage_operations_require_account_session(self):
        with patch.object(module, 'finish') as finish:
            self.assertEqual(self.post('/api/finish', {})[0], 403)
            finish.assert_not_called()
        self.assertEqual(self.post('/api/gparted', {})[0], 403)

    def test_cross_origin_and_dns_rebinding_are_rejected(self):
        for headers in ({'Origin': 'https://example.com'}, {'Host': 'example.com'}, {'X-Setup-Token': ''}):
            self.assertEqual(self.post('/api/admin', {}, **headers)[0], 403)
        self.assertFalse(module.ADMIN.exists())

    def test_admin_is_hashed_and_cannot_be_replaced(self):
        payload = {'username': 'owner', 'password': 'a-long-test-password'}
        status, headers, body = self.post('/api/admin', payload)
        self.assertEqual(status, 200)
        self.assertIn('HttpOnly', headers['Set-Cookie'])
        stored = json.loads(module.ADMIN.read_text())
        self.assertNotIn(payload['password'], module.ADMIN.read_text())
        self.assertTrue(module.verify_password(payload['password'], stored['hash']))
        self.assertEqual(self.post('/api/admin', dict(payload, username='replacement'))[0], 400)
        self.assertEqual(json.loads(module.ADMIN.read_text())['username'], 'owner')

    def test_completed_setup_cannot_mutate_storage(self):
        module.COMPLETE.touch()
        with patch.object(module, 'finish') as finish:
            self.assertEqual(self.post('/api/finish', {})[0], 409)
            finish.assert_not_called()


if __name__ == '__main__':
    unittest.main()
