import os
from pathlib import Path
import tempfile
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

    def test_view_rotation_allows_quarter_turns_only(self):
        self.assertEqual(server.normalize_view_rotation("180"), 180)
        self.assertEqual(server.normalize_view_rotation(270), 270)
        with self.assertRaises(ValueError):
            server.normalize_view_rotation(45)

    def test_recording_directory_probe_reports_permission_errors(self):
        original_recordings_dir = server.RECORDINGS_DIR
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            camera_dir = root / "cam"
            camera_dir.mkdir()
            camera_dir.chmod(0o555)
            server.RECORDINGS_DIR = root
            try:
                if os.access(camera_dir, os.W_OK):
                    self.skipTest("current user can write to read-only directories")
                with self.assertRaisesRegex(RuntimeError, "Recording directory is not writable"):
                    server.ensure_recording_directory({"slug": "cam"})
            finally:
                camera_dir.chmod(0o755)
                server.RECORDINGS_DIR = original_recordings_dir

    def test_recording_directory_probe_creates_missing_directory(self):
        original_recordings_dir = server.RECORDINGS_DIR
        with tempfile.TemporaryDirectory() as tmp:
            server.RECORDINGS_DIR = Path(tmp)
            try:
                target = server.ensure_recording_directory({"slug": "cam"})
                self.assertTrue(target.is_dir())
            finally:
                server.RECORDINGS_DIR = original_recordings_dir


if __name__ == "__main__":
    unittest.main()
