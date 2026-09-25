import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from app import server


class MigrationTests(unittest.TestCase):
    def test_legacy_database_upgrades_without_losing_camera_or_user(self):
        with tempfile.TemporaryDirectory() as directory:
            data_dir = Path(directory)
            db_path = data_dir / "nvr.sqlite3"

            password = "existing-password-123"
            password_hash = server.password_hash(password)
            schedule = json.dumps(
                {
                    "mode": "always",
                    "days": {
                        day: []
                        for day in server.DAY_KEYS
                    },
                }
            )

            conn = sqlite3.connect(db_path)
            try:
                conn.executescript(
                    """
                    CREATE TABLE cameras (
                        id TEXT PRIMARY KEY,
                        name TEXT NOT NULL,
                        slug TEXT NOT NULL UNIQUE,
                        rtsp_url TEXT NOT NULL,
                        enabled INTEGER NOT NULL DEFAULT 1,
                        segment_seconds INTEGER NOT NULL DEFAULT 60,
                        retention_days INTEGER NOT NULL DEFAULT 14,
                        schedule_json TEXT NOT NULL,
                        record_audio INTEGER NOT NULL DEFAULT 1,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );

                    CREATE TABLE users (
                        username TEXT PRIMARY KEY,
                        password_hash TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );
                    """
                )
                conn.execute(
                    """
                    INSERT INTO cameras (
                        id, name, slug, rtsp_url, enabled,
                        segment_seconds, retention_days,
                        schedule_json, record_audio,
                        created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "legacy-camera",
                        "Legacy Camera",
                        "legacy-camera",
                        "rtsp://camera.invalid/stream",
                        1,
                        60,
                        14,
                        schedule,
                        1,
                        "2026-01-01T00:00:00+00:00",
                        "2026-01-01T00:00:00+00:00",
                    ),
                )
                conn.execute(
                    """
                    INSERT INTO users (
                        username, password_hash,
                        created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        "existing-admin",
                        password_hash,
                        "2026-01-01T00:00:00+00:00",
                        "2026-01-01T00:00:00+00:00",
                    ),
                )
                conn.commit()
            finally:
                conn.close()

            with patch.object(server, "DATA_DIR", data_dir), patch.object(
                server, "DB_PATH", db_path
            ), patch.object(server, "BOOTSTRAP_PASSWORD", ""):
                server.init_db()

                camera = server.get_camera("legacy-camera")
                self.assertIsNotNone(camera)
                self.assertEqual(camera["name"], "Legacy Camera")
                self.assertEqual(
                    camera["rtsp_url"],
                    "rtsp://camera.invalid/stream",
                )
                self.assertEqual(camera["audio_url"], "")
                self.assertEqual(camera["grayscale_mode"], "off")
                self.assertEqual(camera["live_view_mode"], "hls")
                self.assertEqual(camera["view_rotation"], 0)
                self.assertEqual(camera["rtsp_transport"], "tcp")
                self.assertFalse(camera["ptz_enabled"])
                self.assertEqual(camera["ptz_type"], "onvif")
                self.assertEqual(camera["ptz_speed"], 0.55)
                self.assertEqual(camera["onvif"], {})

                self.assertEqual(
                    server.authenticate_user(
                        "existing-admin",
                        password,
                    ),
                    "existing-admin",
                )

                with server.db_conn() as upgraded:
                    columns = {
                        row["name"]
                        for row in upgraded.execute(
                            "PRAGMA table_info(cameras)"
                        ).fetchall()
                    }
                    for expected in (
                        "audio_url",
                        "grayscale_mode",
                        "live_view_mode",
                        "view_rotation",
                        "rtsp_transport",
                        "ptz_enabled",
                        "ptz_type",
                        "onvif_url",
                        "ptz_url",
                        "ptz_profile_token",
                        "ptz_zoom_mode",
                        "ptz_speed",
                        "onvif_json",
                        "onvif_updated_at",
                    ):
                        self.assertIn(expected, columns)

                    token = upgraded.execute(
                        """
                        SELECT value
                        FROM app_settings
                        WHERE key = 'stream_token'
                        """
                    ).fetchone()
                    self.assertIsNotNone(token)
                    self.assertTrue(token["value"])


if __name__ == "__main__":
    unittest.main()
