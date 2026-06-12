import unittest

from app import server


class RunningProcess:
    pid = 123

    def poll(self):
        return None


class ServerFeatureTests(unittest.TestCase):
    def test_continuous_onvif_move_has_no_timeout(self):
        continuous = server.onvif_move_body(
            "left", 0.5, 300, "profile-1", continuous=True
        )
        pulse = server.onvif_move_body(
            "left", 0.5, 300, "profile-1", continuous=False
        )
        self.assertNotIn("Timeout", continuous)
        self.assertIn("PT0.30S", pulse)

    def test_go2rtc_restream_skips_separate_audio_source(self):
        manager = server.Go2RTCManager()
        manager.process = RunningProcess()
        camera = {
            "id": "abc",
            "rtsp_url": "rtsp://camera/main",
            "audio_url": "",
            "record_audio": True,
        }
        self.assertTrue(manager.can_restream(camera))
        camera["audio_url"] = "rtsp://camera/audio"
        self.assertFalse(manager.can_restream(camera))

    def test_codec_recommendations_flag_h265(self):
        result = {
            "details": {
                "streams": [
                    {"codec_name": "hevc"},
                    {"codec_name": "pcm_alaw"},
                ]
            }
        }
        recommendations = server.compatibility_recommendations(
            result, {"success": True, "ptz_supported": False}
        )
        text = " ".join(recommendations)
        self.assertIn("H.264", text)
        self.assertIn("H.265", text)
        self.assertIn("AAC", text)

    def test_report_redaction_catches_normalized_go2rtc_urls(self):
        camera = {"rtsp_url": "", "audio_url": "", "ptz_url": ""}
        value = '{"url":"rtsp://probe-user:probe-secret@127.0.0.1:9/test"}'
        redacted = server.redact_camera_text(value, camera)
        self.assertNotIn("probe-user", redacted)
        self.assertNotIn("probe-secret", redacted)
        self.assertIn("rtsp://<credentials>@127.0.0.1:9/test", redacted)


if __name__ == "__main__":
    unittest.main()
