import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest import mock

from app.recording import RecorderSupervisor


class RecordingStorageTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.camera_root = self.root / "camera"
        self.camera_root.mkdir()
        self.camera = {"id": "camera", "segment_seconds": 60}
        self.events = []
        self.settings = {"auto_delete_old_recordings": True}
        self.supervisor = RecorderSupervisor(
            relay=mock.Mock(),
            build_ffmpeg_command=mock.Mock(),
            add_event=lambda *args: self.events.append(args),
            redact_camera_text=lambda text, camera: text,
            get_camera=lambda camera_id: self.camera,
            camera_dir=lambda camera: self.camera_root,
            list_cameras=lambda: [self.camera],
            schedule_active=lambda schedule: True,
            iso_now=lambda: "now",
            scan_interval_seconds=10,
            retention_interval_seconds=3600,
            start_grace_seconds=10,
            stale_seconds=120,
            recordings_dir=self.root,
            get_app_settings=lambda: self.settings,
        )

    def test_pressure_deletes_oldest_completed_clips_only(self):
        old = self.camera_root / "old.mp4"
        newer = self.camera_root / "newer.mp4"
        active = self.camera_root / "active.mp4"
        for path in (old, newer, active):
            path.write_bytes(b"video")
        now = time.time()
        os.utime(old, (now - 600, now - 600))
        os.utime(newer, (now - 300, now - 300))
        available = [19 * 1024**3]

        def disk_usage(_path):
            available[0] += (not old.exists() and available[0] < 20 * 1024**3) * 12 * 1024**3
            return mock.Mock(free=available[0])

        with mock.patch("app.recording.shutil.disk_usage", side_effect=disk_usage):
            self.assertTrue(self.supervisor._storage_ready([self.camera]))
        self.assertFalse(old.exists())
        self.assertTrue(newer.exists())
        self.assertTrue(active.exists())

    def test_guard_blocks_when_cleanup_disabled_and_reports_once(self):
        self.settings["auto_delete_old_recordings"] = False
        with mock.patch("app.recording.shutil.disk_usage", return_value=mock.Mock(free=9 * 1024**3)):
            self.assertFalse(self.supervisor._storage_ready([self.camera]))
            self.supervisor._block_for_storage(self.camera["id"])
            self.supervisor._block_for_storage(self.camera["id"])
        self.assertEqual(len(self.events), 1)
        self.assertEqual(self.events[0][1], "error")
        self.assertIn("10 GiB", self.supervisor.status()["camera"]["last_error"])

    def test_guard_fails_closed_when_storage_unavailable(self):
        with mock.patch("app.recording.shutil.disk_usage", side_effect=OSError("unmounted")):
            self.assertFalse(self.supervisor._storage_ready([self.camera]))

    def test_pressure_never_deletes_outside_recordings_root(self):
        external = tempfile.TemporaryDirectory()
        self.addCleanup(external.cleanup)
        outside = Path(external.name) / "outside.mp4"
        outside.write_bytes(b"video")
        old = time.time() - 600
        os.utime(outside, (old, old))
        with mock.patch.object(self.supervisor, "camera_dir", return_value=Path(external.name)):
            with mock.patch("app.recording.shutil.disk_usage", return_value=mock.Mock(free=9 * 1024**3)):
                self.assertFalse(self.supervisor._storage_ready([self.camera]))
        self.assertTrue(outside.exists())

    def test_low_space_stops_an_existing_recorder_before_restarting(self):
        process = mock.Mock()
        process.poll.return_value = None
        self.supervisor.processes[self.camera["id"]] = {"process": process}
        self.supervisor.ensure_running(self.camera, storage_ready=False)
        process.terminate.assert_called_once()
        self.supervisor.relay.source_camera.assert_not_called()
        self.assertFalse(self.supervisor.status()[self.camera["id"]]["running"])
        self.assertEqual(self.events[-1][1], "error")


if __name__ == "__main__":
    unittest.main()
