import io
import json
import os
from email.message import Message
import unittest
from unittest.mock import patch
from unittest.mock import Mock
from urllib.error import HTTPError

from app import server


class CapturedHandler(server.NvrHandler):
    def __init__(self, headers=None):
        self.headers = headers or {}
        self.wfile = io.BytesIO()
        self.status = None
        self.response_headers = {}

    def send_response(self, status, message=None):
        self.status = int(status)

    def send_header(self, key, value):
        self.response_headers[key] = value

    def end_headers(self):
        pass


class UpstreamResponse(io.BytesIO):
    def __init__(self, body, content_type, status=200, **headers):
        super().__init__(body)
        self.status = status
        self.headers = {"Content-Type": content_type, **headers}


class LiveHTTPTests(unittest.TestCase):
    def test_expired_playlist_preserves_upstream_404_and_error_body(self):
        handler = CapturedHandler()
        headers = Message()
        headers["Content-Type"] = "text/plain"
        error = HTTPError("http://relay/playlist.m3u8", 404, "Not Found", headers,
                          io.BytesIO(b"404 page not found\n"))
        with patch.object(server.urllib_request, "urlopen", side_effect=error):
            handler.proxy_go2rtc_live_hls("/api/hls/playlist.m3u8?id=expired", "abc")
        self.assertEqual(handler.status, 404)
        self.assertEqual(handler.response_headers["Content-Type"], "text/plain")
        self.assertEqual(handler.wfile.getvalue(), b"404 page not found\n")

    def test_valid_playlist_rewrites_segments_and_init_with_auth(self):
        handler = CapturedHandler()
        response = UpstreamResponse(
            b'#EXTM3U\n#EXT-X-MAP:URI="init.mp4?id=session"\n'
            b'#EXTINF:0.5,\nsegment.m4s?id=session&n=4\n',
            "application/vnd.apple.mpegurl")
        with patch.object(server.urllib_request, "urlopen", return_value=response):
            handler.proxy_go2rtc_live_hls("/api/hls/playlist.m3u8", "abc", "test-token")
        body = handler.wfile.getvalue().decode()
        self.assertEqual(handler.status, 200)
        self.assertIn('URI="/live/abc/hls/init.mp4?id=session&token=test-token"', body)
        self.assertIn('/live/abc/hls/segment.m4s?id=session&n=4&token=test-token', body)
        self.assertEqual(int(handler.response_headers["Content-Length"]), len(handler.wfile.getvalue()))

    def test_head_preserves_real_segment_type_and_has_no_body(self):
        handler = CapturedHandler()
        response = UpstreamResponse(b"not-sent", "video/iso.segment", **{"Content-Length": "500"})
        with patch.object(server.urllib_request, "urlopen", return_value=response) as request:
            handler.proxy_go2rtc_live_hls("/api/hls/segment.m4s?id=a", "abc", head_only=True)
        self.assertEqual(request.call_args.args[0].method, "HEAD")
        self.assertEqual(handler.status, 200)
        self.assertEqual(handler.response_headers["Content-Type"], "video/iso.segment")
        self.assertEqual(handler.response_headers["Content-Length"], "500")
        self.assertEqual(handler.wfile.getvalue(), b"")

    def test_head_missing_playlist_is_not_reported_as_success(self):
        handler = CapturedHandler()
        error = HTTPError("http://relay/playlist.m3u8", 404, "Not Found", {}, io.BytesIO())
        with patch.object(server.urllib_request, "urlopen", side_effect=error):
            handler.proxy_go2rtc_live_hls("/api/hls/playlist.m3u8?id=missing", "abc", head_only=True)
        self.assertEqual(handler.status, 404)
        self.assertEqual(handler.wfile.getvalue(), b"")

    def test_segment_range_preserves_partial_response(self):
        handler = CapturedHandler({"Range": "bytes=10-19"})
        response = UpstreamResponse(b"0123456789", "video/mp4", 206,
                                    **{"Content-Range": "bytes 10-19/100"})
        with patch.object(server.urllib_request, "urlopen", return_value=response) as request:
            handler.proxy_go2rtc_live_hls("/api/hls/init.mp4", "abc")
        self.assertEqual(request.call_args.args[0].get_header("Range"), "bytes=10-19")
        self.assertEqual(handler.status, 206)
        self.assertEqual(handler.response_headers["Content-Range"], "bytes 10-19/100")
        self.assertEqual(handler.wfile.getvalue(), b"0123456789")

    def test_viewer_restart_does_not_reset_shared_camera(self):
        handler = CapturedHandler()
        with patch.object(server.go2rtc, "restart_camera") as restart:
            handler.handle_live_control({"id": "abc"}, "restart")
        restart.assert_not_called()
        self.assertEqual(handler.status, 200)


class WebRTCConfigTests(unittest.TestCase):
    def test_default_avoids_ipv6_interface_binding_failure(self):
        with patch.dict(os.environ, {}, clear=True):
            config = server.Go2RTCManager()._config()
        self.assertEqual(config["webrtc"]["filters"]["networks"], ["udp4", "tcp4"])

    def test_dual_stack_can_be_enabled_without_losing_candidates(self):
        with patch.dict(os.environ, {
            "NVR_GO2RTC_WEBRTC_NETWORKS": "udp4, tcp4, udp6, tcp6",
            "NVR_GO2RTC_WEBRTC_CANDIDATES": "192.0.2.1:8555",
        }):
            config = server.Go2RTCManager()._config()
        self.assertEqual(config["webrtc"]["filters"]["networks"],
                         ["udp4", "tcp4", "udp6", "tcp6"])
        self.assertEqual(config["webrtc"]["candidates"], ["192.0.2.1:8555"])

    def test_invalid_networks_fail_instead_of_silently_disabling_media(self):
        for value in ["", " , ", "ipv4", "udp4,typo"]:
            with self.subTest(value=value), patch.dict(os.environ, {
                "NVR_GO2RTC_WEBRTC_NETWORKS": value,
            }):
                with self.assertRaisesRegex(ValueError, "NVR_GO2RTC_WEBRTC_NETWORKS"):
                    server.Go2RTCManager()._config()


class MediaHealthTests(unittest.TestCase):
    def setUp(self):
        self.manager = server.Go2RTCManager()
        self.manager.process = Mock(pid=123)
        self.manager.process.poll.return_value = None
        self.camera = {"id": "abc", "enabled": True, "rtsp_url": "rtsp://camera/live"}
        self.manager.stream_keys["abc"] = self.camera["rtsp_url"]

    def sample(self, now, video=10, audio=20, consumers=True, receiver_id=1):
        response = {"plainnvr_abc": {
            "producers": [{"receivers": [
                {"id": receiver_id, "codec": {"codec_type": "video", "codec_name": "h264"}, "packets": video},
                {"id": 2, "codec": {"codec_type": "audio", "codec_name": "aac"}, "packets": audio},
            ]}],
            "consumers": [{"id": 3}] if consumers else [],
        }}
        with patch.object(self.manager, "_request", return_value=json.dumps(response).encode()), \
             patch.object(server.time, "monotonic", return_value=now):
            self.manager.sample_media([self.camera])
            return self.manager.camera_status(self.camera)

    def test_configuration_alone_does_not_claim_healthy_video(self):
        status = self.manager.camera_status(self.camera)
        self.assertTrue(status["available"])
        self.assertFalse(status["healthy"])

    def test_advancing_video_is_healthy(self):
        self.sample(100, video=10)
        status = self.sample(110, video=20)
        self.assertTrue(status["healthy"])
        self.assertEqual(status["media_age_seconds"], 0)

    def test_audio_progress_cannot_hide_frozen_video(self):
        self.sample(100, video=10, audio=20)
        status = self.sample(100 + server.GO2RTC_MEDIA_STALE_SECONDS + 1, video=10, audio=200)
        self.assertFalse(status["healthy"])
        self.assertEqual(status["media_state"], "stalled")

    def test_idle_source_is_available_without_false_stall(self):
        self.sample(100)
        status = self.sample(200, consumers=False)
        self.assertEqual(status["media_state"], "idle")
        self.assertTrue(status["available"])
        self.assertFalse(status["healthy"])

    def test_new_receiver_recovers_after_counter_reset(self):
        self.sample(100, video=500)
        self.sample(200, video=500)
        status = self.sample(210, video=1, receiver_id=4)
        self.assertTrue(status["healthy"])

    def test_missing_media_samples_age_out(self):
        self.sample(100)
        with patch.object(server.time, "monotonic", return_value=100 + server.GO2RTC_MEDIA_STALE_SECONDS + 1):
            self.assertFalse(self.manager.camera_status(self.camera)["healthy"])

    def test_crashed_service_is_restarted_with_fresh_registrations(self):
        self.manager.process.poll.return_value = 1
        with patch.object(self.manager, "start", return_value=True) as start:
            self.manager.reconcile([self.camera])
        start.assert_called_once_with([self.camera])
        self.assertEqual(self.manager.stream_keys, {})


if __name__ == "__main__":
    unittest.main()
