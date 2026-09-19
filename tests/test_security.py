import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, Mock
from urllib.parse import urlparse

from app import server
from test_live_streaming import CapturedHandler


class RequestSafetyTests(unittest.TestCase):
    def test_rejects_oversized_body_before_read(self):
        handler = Mock(headers={'Content-Length': str(server.MAX_JSON_BODY_BYTES + 1)})
        with self.assertRaises(ValueError):
            server.parse_json_body(handler)
        handler.rfile.read.assert_not_called()

    def test_rejects_invalid_types_encoding_framing_and_form_posts(self):
        for body, headers in [
            (b'[]', {}), (b'null', {}), (b'"hello"', {}), (b'\xff', {}),
            (b'{}', {'Content-Type': 'text/plain'}),
            (b'{}', {'Transfer-Encoding': 'chunked'}),
            (b'{}', {'Content-Length': '-1'}),
            (b'{}', {'Content-Length': '4'}),
        ]:
            with self.subTest(body=body, headers=headers):
                handler = Mock(headers={'Content-Type': 'application/json', 'Content-Length': str(len(body)), **headers}, rfile=io.BytesIO(body))
                with self.assertRaises(ValueError):
                    server.parse_json_body(handler)

    def test_accepts_native_json(self):
        handler = Mock(headers={'Content-Type': 'application/json; charset=utf-8', 'Content-Length': '2'}, rfile=io.BytesIO(b'{}'))
        self.assertEqual(server.parse_json_body(handler), {})

    def test_cross_origin_denied_native_and_same_origin_allowed(self):
        for origin, expected in [(None, True), ('http://nvr:8787', True), ('https://nvr:8787', True), ('http://evil', False), ('null', False), ('http://nvr:9999', False)]:
            headers = {'Host': 'nvr:8787'}
            if origin is not None:
                headers['Origin'] = origin
            handler = CapturedHandler(headers)
            self.assertEqual(handler.ensure_same_origin(), expected)
        self.assertFalse(CapturedHandler({'Sec-Fetch-Site': 'cross-site'}).ensure_same_origin())

    def test_json_head_errors_have_no_body(self):
        handler = CapturedHandler()
        handler.command = 'HEAD'
        handler.send_error_json(401, 'Authentication required')
        self.assertEqual(handler.wfile.getvalue(), b'')

    def test_proxy_rejects_management_arbitrary_sources_and_duplicate_sources(self):
        for path in ['/go2rtc/api/config', '/go2rtc/api/streams', '/go2rtc/api/ws?src=exec:foo', '/go2rtc/api/ws?src=plainnvr_abc&src=exec:foo', '/go2rtc/api/ws?src=plainnvr_abc&dst=foo']:
            handler = CapturedHandler({'Upgrade': 'websocket'})
            with patch.object(server.go2rtc, 'running', return_value=True), patch.object(handler, 'proxy_go2rtc_websocket') as proxy:
                handler.handle_go2rtc_proxy(urlparse(path))
                proxy.assert_not_called()
                self.assertEqual(handler.status, 404)

    def test_proxy_accepts_registered_camera_and_blocks_foreign_origin(self):
        for headers, expected in [({'Upgrade': 'websocket'}, True), ({'Upgrade': 'websocket', 'Origin': 'http://evil', 'Host': 'nvr'}, False)]:
            handler = CapturedHandler(headers)
            with patch.object(server.go2rtc, 'running', return_value=True), patch.object(server.go2rtc, 'can_restream', return_value=True), patch.object(server.go2rtc, 'configure_camera', return_value=True), patch.object(server, 'get_camera', return_value={'id': 'abc', 'enabled': True}), patch.object(handler, 'proxy_go2rtc_websocket') as proxy:
                handler.handle_go2rtc_proxy(urlparse('/go2rtc/api/ws?src=plainnvr_abc'))
                self.assertEqual(proxy.called, expected)

    def test_hls_rejects_traversal_before_proxy(self):
        for path in ['../../config', '%2e%2e/config', 'unknown', 'playlist.m3u8/extra']:
            handler = CapturedHandler()
            with patch.object(handler, 'send_error') as error, patch.object(handler, 'proxy_go2rtc_live_hls') as proxy:
                handler.handle_live_hls(urlparse('/live/abc/hls/' + path))
                proxy.assert_not_called()
                error.assert_called_once()

    def test_rtsp_is_loopback_by_default(self):
        self.assertEqual(server.Go2RTCManager()._config()['rtsp']['listen'], '127.0.0.1:8554')

    def test_login_rate_limit_expires_and_does_not_trust_usernames(self):
        limiter = server.LoginLimiter()
        with patch.object(server.time, 'monotonic', return_value=100):
            self.assertTrue(all(limiter.allow('peer') for _ in range(20)))
            self.assertFalse(limiter.allow('peer'))
            self.assertTrue(limiter.allow('another-peer'))
        with patch.object(server.time, 'monotonic', return_value=161):
            self.assertTrue(limiter.allow('peer'))

    def test_initial_setup_cannot_create_second_admin(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(server, 'DATA_DIR', Path(directory)), patch.object(server, 'DB_PATH', Path(directory) / 'test.sqlite3'), patch.object(server, 'BOOTSTRAP_PASSWORD', ''):
            server.init_db()
            server.create_user('first', 'first-password-123', initial_setup=True)
            with self.assertRaisesRegex(ValueError, 'already exists'):
                server.create_user('second', 'second-password-123', initial_setup=True)
            self.assertEqual(len(server.list_users()), 1)


class RecordingRangeTests(unittest.TestCase):
    def test_suffix_and_open_ranges_and_unsatisfiable_requests(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / '20260919T120000.mp4').write_bytes(b'0123456789')
            for value, status, body in [('bytes=-3', 206, b'789'), ('bytes=5-', 206, b'56789'), ('bytes=2-4', 206, b'234'), ('bytes=50-', 416, b''), ('bytes=4-2', 416, b''), ('bytes=-0', 416, b''), ('bytes=0-1,3-4', 200, b'0123456789')]:
                with self.subTest(value=value):
                    handler = CapturedHandler({'Range': value})
                    with patch.object(server, 'get_camera', return_value={'id': 'abc'}), patch.object(server, 'camera_dir', return_value=root):
                        handler.handle_media('/media/abc/20260919T120000.mp4')
                    self.assertEqual(handler.status, status)
                    self.assertEqual(handler.wfile.getvalue(), body)
                    self.assertEqual(int(handler.response_headers['Content-Length']), len(body))
