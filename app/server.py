#!/usr/bin/env python3
import base64
from html import escape as html_escape
import json
import hmac
import mimetypes
import os
import re
import secrets
import select
import shutil
import signal
import sqlite3
import socket
import struct
import subprocess
import sys
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib import error as urllib_error, request as urllib_request
from urllib.parse import parse_qs, quote, unquote, urlencode, urlparse

try:
    from onvif_client import (
        OnvifError,
        allowed_endpoint_hosts as onvif_allowed_endpoint_hosts,
        cacheable_discovery,
        discover as discover_onvif,
        goto_preset_body,
        payload_credentials as onvif_payload_credentials,
        redacted_discovery,
        redact_url as redact_onvif_url,
        soap_post as onvif_soap_post,
    )
except ModuleNotFoundError:
    from app.onvif_client import (
        OnvifError,
        allowed_endpoint_hosts as onvif_allowed_endpoint_hosts,
        cacheable_discovery,
        discover as discover_onvif,
        goto_preset_body,
        payload_credentials as onvif_payload_credentials,
        redacted_discovery,
        redact_url as redact_onvif_url,
        soap_post as onvif_soap_post,
    )


try:
    from app.auth import (
        AUTH_HASH_ITERATIONS,
        password_hash,
        validate_password,
        validate_username,
        verify_password,
    )
    from app.common import (
        bounded_int,
        env_float,
        iso_now,
        optional_bounded_int,
        slugify,
        utcnow,
    )
    from app.http_utils import (
        MAX_JSON_BODY_BYTES,
        normalize_bool,
        parse_json_body,
        query_bool,
    )
    from app.schedule import (
        DAY_KEYS,
        default_schedule,
        normalize_schedule,
        schedule_active,
        time_to_minutes,
    )
    from app.media_relay import (
        Go2RTCManager as BaseGo2RTCManager,
        Go2RTCSourceManager,
    )
    from app.night_mode import (
        NightModeManager as BaseNightModeManager,
        analyze_rgb_frame,
    )
    from app.recording import (
        RecorderSupervisor as BaseRecorderSupervisor,
        recording_coverage as recording_coverage_impl,
        scan_segments as scan_segments_impl,
        segment_start as segment_start_impl,
    )
    from app.diagnostics import (
        camera_compatibility_report as camera_compatibility_report_impl,
        compatibility_recommendations as compatibility_recommendations_impl,
        live_diagnostics as live_diagnostics_impl,
        probe_stream_url as probe_stream_url_impl,
        redact_camera_text as redact_camera_text_impl,
        stream_summary as stream_summary_impl,
        test_stream as test_stream_impl,
    )
    from app.media_commands import (
        add_video_filters as add_video_filters_impl,
        build_ffmpeg_command as build_ffmpeg_command_impl,
        build_snapshot_command as build_snapshot_command_impl,
        ffmpeg_input_args as ffmpeg_input_args_impl,
    )
    from app.ptz import (
        camera_time as camera_time_impl,
        clean_control_url,
        dvrip_login as dvrip_login_impl,
        dvrip_parse_json,
        dvrip_parse_session,
        dvrip_query_time as dvrip_query_time_impl,
        dvrip_recv_exact,
        dvrip_recv_packet as dvrip_recv_packet_impl,
        dvrip_send_packet as dvrip_send_packet_impl,
        dvrip_step_from_speed,
        dvrip_target as dvrip_target_impl,
        dvrip_url_for_parse,
        http_admin_url_for_parse,
        netloc_without_credentials,
        normalize_requested_camera_time,
        onvif_home_body,
        onvif_move_body as onvif_move_body_impl,
        onvif_stop_body,
        ptz_url_candidates,
        redact_url_credentials,
        run_ptz_command as run_ptz_command_impl,
        run_victure_direct_ptz_command as run_victure_direct_ptz_command_impl,
        run_victure_dvrip_ptz_command as run_victure_dvrip_ptz_command_impl,
        url_credentials,
        victure_direct_step_from_speed,
        victure_direct_target as victure_direct_target_impl,
    )
except ModuleNotFoundError:
    from auth import (
        AUTH_HASH_ITERATIONS,
        password_hash,
        validate_password,
        validate_username,
        verify_password,
    )
    from common import (
        bounded_int,
        env_float,
        iso_now,
        optional_bounded_int,
        slugify,
        utcnow,
    )
    from http_utils import (
        MAX_JSON_BODY_BYTES,
        normalize_bool,
        parse_json_body,
        query_bool,
    )
    from schedule import (
        DAY_KEYS,
        default_schedule,
        normalize_schedule,
        schedule_active,
        time_to_minutes,
    )
    from media_relay import (
        Go2RTCManager as BaseGo2RTCManager,
        Go2RTCSourceManager,
    )
    from night_mode import (
        NightModeManager as BaseNightModeManager,
        analyze_rgb_frame,
    )
    from recording import (
        RecorderSupervisor as BaseRecorderSupervisor,
        recording_coverage as recording_coverage_impl,
        scan_segments as scan_segments_impl,
        segment_start as segment_start_impl,
    )
    from diagnostics import (
        camera_compatibility_report as camera_compatibility_report_impl,
        compatibility_recommendations as compatibility_recommendations_impl,
        live_diagnostics as live_diagnostics_impl,
        probe_stream_url as probe_stream_url_impl,
        redact_camera_text as redact_camera_text_impl,
        stream_summary as stream_summary_impl,
        test_stream as test_stream_impl,
    )
    from media_commands import (
        add_video_filters as add_video_filters_impl,
        build_ffmpeg_command as build_ffmpeg_command_impl,
        build_snapshot_command as build_snapshot_command_impl,
        ffmpeg_input_args as ffmpeg_input_args_impl,
    )
    from ptz import (
        camera_time as camera_time_impl,
        clean_control_url,
        dvrip_login,
        dvrip_parse_json,
        dvrip_parse_session,
        dvrip_query_time,
        dvrip_recv_exact,
        dvrip_recv_packet,
        dvrip_send_packet,
        dvrip_step_from_speed,
        dvrip_target as dvrip_target_impl,
        dvrip_url_for_parse,
        http_admin_url_for_parse,
        netloc_without_credentials,
        normalize_requested_camera_time,
        onvif_home_body,
        onvif_move_body as onvif_move_body_impl,
        onvif_stop_body,
        ptz_url_candidates,
        redact_url_credentials,
        run_ptz_command as run_ptz_command_impl,
        run_victure_direct_ptz_command as run_victure_direct_ptz_command_impl,
        run_victure_dvrip_ptz_command as run_victure_dvrip_ptz_command_impl,
        url_credentials,
        victure_direct_step_from_speed,
        victure_direct_target as victure_direct_target_impl,
    )


APP_HOST = os.environ.get("NVR_HOST", "0.0.0.0")
APP_PORT = int(os.environ.get("NVR_PORT", "8787"))
DATA_DIR = Path(os.environ.get("NVR_DATA_DIR", "/data")).expanduser()
RECORDINGS_DIR = Path(os.environ.get("NVR_RECORDINGS_DIR", "/recordings")).expanduser()
STATIC_DIR = Path(os.environ.get("NVR_STATIC_DIR", "/app/static")).expanduser()
FFMPEG_BIN = os.environ.get("FFMPEG_BIN", "ffmpeg")
FFPROBE_BIN = os.environ.get("FFPROBE_BIN", "ffprobe")
GO2RTC_BIN = os.environ.get("GO2RTC_BIN", "go2rtc")
GO2RTC_API_HOST = os.environ.get("NVR_GO2RTC_API_HOST", "127.0.0.1")
GO2RTC_API_PORT = int(os.environ.get("NVR_GO2RTC_API_PORT", "1984"))
GO2RTC_RTSP_HOST = os.environ.get("NVR_GO2RTC_RTSP_HOST", "127.0.0.1")
GO2RTC_RTSP_PORT = int(os.environ.get("NVR_GO2RTC_RTSP_PORT", "8554"))
GO2RTC_WEBRTC_PORT = int(os.environ.get("NVR_GO2RTC_WEBRTC_PORT", "8555"))
GO2RTC_START_TIMEOUT_SECONDS = max(
    2, env_float("NVR_GO2RTC_START_TIMEOUT_SECONDS", 10)
)
GO2RTC_MEDIA_STALE_SECONDS = max(10, env_float("NVR_GO2RTC_MEDIA_STALE_SECONDS", 30))
RTSP_PROBESIZE = os.environ.get("NVR_RTSP_PROBESIZE", "32768")
RTSP_ANALYZE_DURATION = os.environ.get("NVR_RTSP_ANALYZE_DURATION", "0")
RTSP_LIVE_PROBESIZE = os.environ.get("NVR_RTSP_LIVE_PROBESIZE", "5000000")
RTSP_LIVE_ANALYZE_DURATION = os.environ.get("NVR_RTSP_LIVE_ANALYZE_DURATION", "5000000")
RTSP_THREAD_QUEUE_SIZE = os.environ.get("NVR_RTSP_THREAD_QUEUE_SIZE", "2048")
RTSP_READ_TIMEOUT_SECONDS = max(3, env_float("NVR_RTSP_READ_TIMEOUT_SECONDS", 15))
SCAN_INTERVAL_SECONDS = int(os.environ.get("NVR_SCAN_INTERVAL_SECONDS", "10"))
RETENTION_INTERVAL_SECONDS = int(os.environ.get("NVR_RETENTION_INTERVAL_SECONDS", "3600"))
DEFAULT_SEGMENT_SECONDS = int(os.environ.get("NVR_DEFAULT_SEGMENT_SECONDS", "60"))
RECORDER_START_GRACE_SECONDS = max(15, env_float("NVR_RECORDER_START_GRACE_SECONDS", 45))
RECORDER_STALE_SECONDS = max(30, env_float("NVR_RECORDER_STALE_SECONDS", 90))
NIGHT_SAMPLE_INTERVAL_SECONDS = int(os.environ.get("NVR_NIGHT_SAMPLE_INTERVAL_SECONDS", "20"))
NIGHT_ON_SECONDS = int(os.environ.get("NVR_NIGHT_ON_SECONDS", "45"))
NIGHT_OFF_SECONDS = int(os.environ.get("NVR_NIGHT_OFF_SECONDS", "180"))
NIGHT_ON_BRIGHTNESS = float(os.environ.get("NVR_NIGHT_ON_BRIGHTNESS", "120"))
NIGHT_ON_SATURATION = float(os.environ.get("NVR_NIGHT_ON_SATURATION", "18"))
NIGHT_DARK_BRIGHTNESS = float(os.environ.get("NVR_NIGHT_DARK_BRIGHTNESS", "35"))
NIGHT_OFF_BRIGHTNESS = float(os.environ.get("NVR_NIGHT_OFF_BRIGHTNESS", "155"))
NIGHT_OFF_SATURATION = float(os.environ.get("NVR_NIGHT_OFF_SATURATION", "35"))
DB_PATH = DATA_DIR / "nvr.sqlite3"
AUTH_COOKIE_NAME = "plainnvr_session"
AUTH_SESSION_TTL_SECONDS = int(os.environ.get("NVR_SESSION_TTL_SECONDS", str(7 * 24 * 60 * 60)))
SESSION_TOUCH_INTERVAL_SECONDS = max(60, int(os.environ.get("NVR_SESSION_TOUCH_INTERVAL_SECONDS", "900")))
BOOTSTRAP_USERNAME = os.environ.get("NVR_AUTH_USERNAME", "admin").strip() or "admin"
BOOTSTRAP_PASSWORD = os.environ.get("NVR_AUTH_PASSWORD", "")
STREAM_TOKEN_OVERRIDE = os.environ.get("NVR_STREAM_TOKEN", "").strip()
DEFAULT_PTZ_PROFILE_TOKEN = os.environ.get("NVR_PTZ_PROFILE_TOKEN", "Profile_1").strip() or "Profile_1"
try:
    DEFAULT_PTZ_SPEED = float(os.environ.get("NVR_PTZ_SPEED", "0.55"))
except ValueError:
    DEFAULT_PTZ_SPEED = 0.55
DEFAULT_PTZ_SPEED = max(0.05, min(DEFAULT_PTZ_SPEED, 1.0))
try:
    PTZ_DEFAULT_DURATION_MS = int(os.environ.get("NVR_PTZ_DURATION_MS", "350"))
except ValueError:
    PTZ_DEFAULT_DURATION_MS = 350
PTZ_DEFAULT_DURATION_MS = max(80, min(PTZ_DEFAULT_DURATION_MS, 1500))

SEGMENT_RE = re.compile(r"^(?P<stamp>\d{8}T\d{6})\.mp4$")
STREAM_URL_PREFIXES = ("rtsp://", "rtsps://", "http://", "https://")
CONTROL_URL_PREFIXES = ("http://", "https://")
DVRIP_URL_PREFIXES = ("dvrip://", "tcp://")
PTZ_TYPES = ("none", "onvif", "victure_dvrip", "victure_direct")
PTZ_MOVE_VECTORS = {
    "up": (0, 1, 0),
    "down": (0, -1, 0),
    "left": (-1, 0, 0),
    "right": (1, 0, 0),
    "up_left": (-1, 1, 0),
    "up_right": (1, 1, 0),
    "down_left": (-1, -1, 0),
    "down_right": (1, -1, 0),
    "zoom_in": (0, 0, 1),
    "zoom_out": (0, 0, -1),
}
DVRIP_DEFAULT_PORT = 34567
DVRIP_DEFAULT_USER = "admin"
DVRIP_DEFAULT_PASSHASH = "nTBCS19C"
DVRIP_HEADER = struct.Struct("<BBHIIBBHI")
VICTURE_DIRECT_DEFAULT_PORT = 8088
VICTURE_DIRECT_ACTIONS = {
    "up",
    "down",
    "left",
    "right",
    "up_left",
    "up_right",
    "down_left",
    "down_right",
}
DVRIP_PTZ_COMMANDS = {
    "up": "DirectionUp",
    "down": "DirectionDown",
    "left": "DirectionLeft",
    "right": "DirectionRight",
    "up_left": "DirectionLeftUp",
    "up_right": "DirectionRightUp",
    "down_left": "DirectionLeftDown",
    "down_right": "DirectionRightDown",
    "zoom_in": "ZoomTile",
    "zoom_out": "ZoomWide",
    "stop": "Stop",
}


def get_db():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


@contextmanager
def db_conn():
    conn = get_db()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    with db_conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS cameras (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                slug TEXT NOT NULL UNIQUE,
                rtsp_url TEXT NOT NULL,
                audio_url TEXT NOT NULL DEFAULT '',
                enabled INTEGER NOT NULL DEFAULT 1,
                segment_seconds INTEGER NOT NULL DEFAULT 60,
                retention_days INTEGER NOT NULL DEFAULT 14,
                schedule_json TEXT NOT NULL,
                record_audio INTEGER NOT NULL DEFAULT 1,
                grayscale_mode TEXT NOT NULL DEFAULT 'off',
                live_view_mode TEXT NOT NULL DEFAULT 'hls',
                view_rotation INTEGER NOT NULL DEFAULT 0,
                rtsp_transport TEXT NOT NULL DEFAULT 'tcp',
                ptz_enabled INTEGER NOT NULL DEFAULT 0,
                ptz_type TEXT NOT NULL DEFAULT 'onvif',
                onvif_url TEXT NOT NULL DEFAULT '',
                ptz_url TEXT NOT NULL DEFAULT '',
                ptz_profile_token TEXT NOT NULL DEFAULT 'Profile_1',
                ptz_zoom_mode TEXT NOT NULL DEFAULT 'auto',
                ptz_speed REAL NOT NULL DEFAULT 0.55,
                onvif_json TEXT NOT NULL DEFAULT '{}',
                onvif_updated_at TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        ensure_camera_schema(conn)
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS recorder_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                camera_id TEXT NOT NULL,
                level TEXT NOT NULL,
                message TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(camera_id) REFERENCES cameras(id) ON DELETE CASCADE
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                username TEXT PRIMARY KEY,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                username TEXT NOT NULL,
                created_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                FOREIGN KEY(username) REFERENCES users(username) ON DELETE CASCADE
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS app_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        bootstrap_auth_from_env(conn)
        ensure_stream_token(conn)
        cleanup_expired_sessions(conn)


def ensure_camera_schema(conn):
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(cameras)").fetchall()}
    if "audio_url" not in columns:
        conn.execute("ALTER TABLE cameras ADD COLUMN audio_url TEXT NOT NULL DEFAULT ''")
    if "grayscale_mode" not in columns:
        conn.execute("ALTER TABLE cameras ADD COLUMN grayscale_mode TEXT NOT NULL DEFAULT 'off'")
    if "live_view_mode" not in columns:
        conn.execute("ALTER TABLE cameras ADD COLUMN live_view_mode TEXT NOT NULL DEFAULT 'hls'")
    if "view_rotation" not in columns:
        conn.execute("ALTER TABLE cameras ADD COLUMN view_rotation INTEGER NOT NULL DEFAULT 0")
    if "rtsp_transport" not in columns:
        conn.execute("ALTER TABLE cameras ADD COLUMN rtsp_transport TEXT NOT NULL DEFAULT 'tcp'")
    if "ptz_enabled" not in columns:
        conn.execute("ALTER TABLE cameras ADD COLUMN ptz_enabled INTEGER NOT NULL DEFAULT 0")
    if "ptz_type" not in columns:
        conn.execute("ALTER TABLE cameras ADD COLUMN ptz_type TEXT NOT NULL DEFAULT 'onvif'")
    if "onvif_url" not in columns:
        conn.execute("ALTER TABLE cameras ADD COLUMN onvif_url TEXT NOT NULL DEFAULT ''")
    if "ptz_url" not in columns:
        conn.execute("ALTER TABLE cameras ADD COLUMN ptz_url TEXT NOT NULL DEFAULT ''")
    if "ptz_profile_token" not in columns:
        conn.execute("ALTER TABLE cameras ADD COLUMN ptz_profile_token TEXT NOT NULL DEFAULT 'Profile_1'")
    if "ptz_zoom_mode" not in columns:
        conn.execute("ALTER TABLE cameras ADD COLUMN ptz_zoom_mode TEXT NOT NULL DEFAULT 'auto'")
    if "ptz_speed" not in columns:
        conn.execute("ALTER TABLE cameras ADD COLUMN ptz_speed REAL NOT NULL DEFAULT 0.55")
    if "onvif_json" not in columns:
        conn.execute("ALTER TABLE cameras ADD COLUMN onvif_json TEXT NOT NULL DEFAULT '{}'")
    if "onvif_updated_at" not in columns:
        conn.execute("ALTER TABLE cameras ADD COLUMN onvif_updated_at TEXT NOT NULL DEFAULT ''")


def bootstrap_auth_from_env(conn):
    row = conn.execute("SELECT username FROM users LIMIT 1").fetchone()
    if row or not BOOTSTRAP_PASSWORD:
        return
    username = validate_username(BOOTSTRAP_USERNAME)
    password = validate_password(BOOTSTRAP_PASSWORD)
    now = iso_now()
    conn.execute(
        """
        INSERT INTO users (username, password_hash, created_at, updated_at)
        VALUES (?, ?, ?, ?)
        """,
        (username, hashed, now, now),
    )
    print(f"Created PlainNVR admin user from NVR_AUTH_USERNAME/NVR_AUTH_PASSWORD: {username}")


def ensure_stream_token(conn):
    if STREAM_TOKEN_OVERRIDE:
        return STREAM_TOKEN_OVERRIDE
    row = conn.execute("SELECT value FROM app_settings WHERE key = 'stream_token'").fetchone()
    if row:
        return row["value"]
    token = secrets.token_urlsafe(32)
    conn.execute(
        """
        INSERT INTO app_settings (key, value, updated_at)
        VALUES ('stream_token', ?, ?)
        """,
        (token, iso_now()),
    )
    return token


def get_stream_token():
    if STREAM_TOKEN_OVERRIDE:
        return STREAM_TOKEN_OVERRIDE
    with db_conn() as conn:
        return ensure_stream_token(conn)


def setting_bool(value, default=False):
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    raw = str(value or "").strip().lower()
    if raw in ("1", "true", "yes", "on"):
        return True
    if raw in ("0", "false", "no", "off"):
        return False
    try:
        return bool(json.loads(raw))
    except (TypeError, ValueError, json.JSONDecodeError):
        return default


LOG_LEVELS = ("trace", "debug", "info", "warn", "error", "fatal")
LOG_LEVEL_ORDER = {level: index for index, level in enumerate(LOG_LEVELS)}

APP_SETTING_DEFAULTS = {
    "home_assistant_enabled": False,
    "reduce_storage_writes": True,
    "log_level": "info",
}


def normalize_log_level(value, default="info"):
    level = str(value or "").strip().lower()
    return level if level in LOG_LEVELS else default


def get_app_settings():
    settings = dict(APP_SETTING_DEFAULTS)
    with db_conn() as conn:
        rows = conn.execute(
            """
            SELECT key, value
            FROM app_settings
            WHERE key IN ('home_assistant_enabled', 'reduce_storage_writes', 'log_level')
            """
        ).fetchall()
    for row in rows:
        key = row["key"]
        if key == "log_level":
            raw = row["value"]
            try:
                raw = json.loads(raw)
            except (TypeError, ValueError, json.JSONDecodeError):
                pass
            settings[key] = normalize_log_level(raw)
        else:
            settings[key] = setting_bool(
                row["value"], default=APP_SETTING_DEFAULTS[key]
            )
    return settings


def home_assistant_enabled():
    return bool(get_app_settings().get("home_assistant_enabled"))


def app_log_level():
    return normalize_log_level(get_app_settings().get("log_level"))


def event_level_enabled(level):
    level = normalize_log_level(level, default="info")
    configured = app_log_level()
    return LOG_LEVEL_ORDER[level] >= LOG_LEVEL_ORDER[configured]


def update_app_settings(payload):
    settings = get_app_settings()
    for key in ("home_assistant_enabled", "reduce_storage_writes"):
        if key in payload:
            settings[key] = setting_bool(
                payload.get(key), default=APP_SETTING_DEFAULTS[key]
            )
    if "log_level" in payload:
        requested = str(payload.get("log_level") or "").strip().lower()
        if requested not in LOG_LEVELS:
            raise ValueError("Log level must be TRACE, DEBUG, INFO, WARN, ERROR, or FATAL.")
        settings["log_level"] = requested

    now = iso_now()
    with db_conn() as conn:
        for key, value in settings.items():
            encoded = json.dumps(value)
            conn.execute(
                """
                INSERT INTO app_settings (key, value, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
                """,
                (key, encoded, now),
            )
    return settings


def cleanup_expired_sessions(conn):
    conn.execute("DELETE FROM sessions WHERE expires_at <= ?", (iso_now(),))


def setup_required():
    with db_conn() as conn:
        row = conn.execute("SELECT username FROM users LIMIT 1").fetchone()
    return row is None


def create_user(username, password, initial_setup=False):
    username = validate_username(username)
    password = validate_password(password)
    hashed = password_hash(password)
    with db_conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        if initial_setup and conn.execute("SELECT 1 FROM users LIMIT 1").fetchone():
            raise ValueError("Admin account already exists.")
        if conn.execute("SELECT username FROM users WHERE username = ?", (username,)).fetchone():
            raise ValueError("Username already exists.")
        now = iso_now()
        conn.execute(
            """
            INSERT INTO users (username, password_hash, created_at, updated_at)
            VALUES (?, ?, ?, ?)
            """,
            (username, password_hash(password), now, now),
        )
    return username


def list_users():
    with db_conn() as conn:
        rows = conn.execute(
            "SELECT username, created_at, updated_at FROM users ORDER BY username COLLATE NOCASE"
        ).fetchall()
    return [dict(row) for row in rows]


def delete_user(username, current_username=None):
    username = validate_username(unquote(username))
    if current_username and username == current_username:
        raise ValueError("You cannot delete the account you are using.")
    with db_conn() as conn:
        row = conn.execute("SELECT username FROM users WHERE username = ?", (username,)).fetchone()
        if not row:
            return False
        count = conn.execute("SELECT COUNT(*) AS count FROM users").fetchone()["count"]
        if count <= 1:
            raise ValueError("At least one user account is required.")
        conn.execute("DELETE FROM users WHERE username = ?", (username,))
    return True


def authenticate_user(username, password):
    username = str(username or "").strip()
    with db_conn() as conn:
        row = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    if not row or not verify_password(str(password or ""), row["password_hash"]):
        return None
    return row["username"]


def create_session(username):
    session_id = secrets.token_urlsafe(32)
    now = utcnow()
    expires_at = now + timedelta(seconds=AUTH_SESSION_TTL_SECONDS)
    with db_conn() as conn:
        cleanup_expired_sessions(conn)
        conn.execute(
            """
            INSERT INTO sessions (id, username, created_at, last_seen_at, expires_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (session_id, username, now.isoformat(), now.isoformat(), expires_at.isoformat()),
        )
    return session_id


def delete_session(session_id):
    if not session_id:
        return
    with db_conn() as conn:
        conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))


def current_session_user(session_id):
    if not session_id:
        return None
    with db_conn() as conn:
        row = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
        if not row:
            return None
        now = utcnow()
        try:
            expires_at = datetime.fromisoformat(row["expires_at"])
        except ValueError:
            conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
            return None
        if expires_at <= now:
            conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
            return None

        setting_row = conn.execute(
            "SELECT value FROM app_settings WHERE key = 'reduce_storage_writes'"
        ).fetchone()
        reduce_writes = (
            setting_bool(setting_row["value"], default=True)
            if setting_row
            else True
        )
        touch_session = not reduce_writes
        if reduce_writes:
            try:
                last_seen_at = datetime.fromisoformat(row["last_seen_at"])
                if last_seen_at.tzinfo is None:
                    last_seen_at = last_seen_at.replace(tzinfo=timezone.utc)
                touch_session = (
                    now - last_seen_at
                    >= timedelta(seconds=SESSION_TOUCH_INTERVAL_SECONDS)
                )
            except (TypeError, ValueError):
                touch_session = True
        if touch_session:
            conn.execute(
                "UPDATE sessions SET last_seen_at = ? WHERE id = ?",
                (now.isoformat(), session_id),
            )
        return row["username"]


def camera_from_row(row):
    data = dict(row)
    data["enabled"] = bool(data["enabled"])
    data["record_audio"] = bool(data["record_audio"])
    data["ptz_enabled"] = bool(data.get("ptz_enabled", False))
    data["audio_url"] = data.get("audio_url") or ""
    data["grayscale_mode"] = normalize_grayscale_mode(data.get("grayscale_mode"))
    data["live_view_mode"] = normalize_live_view_mode(data.get("live_view_mode"))
    data["view_rotation"] = normalize_view_rotation(data.get("view_rotation"))
    data["ptz_type"] = normalize_ptz_type(data.get("ptz_type"))
    data["onvif_url"] = data.get("onvif_url") or ""
    data["ptz_url"] = data.get("ptz_url") or ""
    data["ptz_profile_token"] = normalize_ptz_profile_token(data.get("ptz_profile_token"))
    data["ptz_zoom_mode"] = normalize_ptz_zoom_mode(data.get("ptz_zoom_mode"))
    data["ptz_speed"] = normalize_ptz_speed(data.get("ptz_speed"))
    try:
        onvif = json.loads(data.pop("onvif_json", "{}") or "{}")
    except json.JSONDecodeError:
        onvif = {}
    data["onvif"] = onvif
    data["ptz_features"] = list(onvif.get("features") or [])
    data["ptz_presets"] = list(onvif.get("presets") or [])
    data["ptz_profiles"] = list(onvif.get("profiles") or [])
    if data["ptz_type"] == "victure_direct":
        data["ptz_features"] = ["pt"]
    elif data["ptz_type"] == "victure_dvrip" and not data["ptz_features"]:
        data["ptz_features"] = ["pt", "zoom"]
    data["time_sync_supported"] = data["ptz_type"] in ("victure_direct", "victure_dvrip")
    data["schedule"] = normalize_schedule(json.loads(data.pop("schedule_json")))
    return data


def save_onvif_discovery(camera_id, result):
    cached = cacheable_discovery(result)
    updated_at = str(cached.get("tested_at") or iso_now())
    with db_conn() as conn:
        conn.execute(
            """
            UPDATE cameras
            SET onvif_json = ?, onvif_updated_at = ?, updated_at = ?
            WHERE id = ?
            """,
            (json.dumps(cached), updated_at, iso_now(), camera_id),
        )
    return cached


def discover_camera_onvif(camera_or_payload, camera_id=None):
    result = discover_onvif(camera_or_payload)
    if camera_id:
        save_onvif_discovery(camera_id, result)
    return result


def list_cameras():
    with db_conn() as conn:
        rows = conn.execute("SELECT * FROM cameras ORDER BY name COLLATE NOCASE").fetchall()
    return [camera_from_row(row) for row in rows]


def get_camera(camera_id):
    with db_conn() as conn:
        row = conn.execute("SELECT * FROM cameras WHERE id = ?", (camera_id,)).fetchone()
    return camera_from_row(row) if row else None


def unique_slug(conn, name, camera_id=None):
    base = slugify(name)
    slug = base
    index = 2
    while True:
        row = conn.execute("SELECT id FROM cameras WHERE slug = ?", (slug,)).fetchone()
        if row is None or row["id"] == camera_id:
            return slug
        slug = f"{base}-{index}"
        index += 1


def validate_camera_payload(payload, partial=False):
    errors = {}
    name = str(payload.get("name", "")).strip()
    rtsp_url = str(payload.get("rtsp_url", "")).strip()
    audio_url = str(payload.get("audio_url", "")).strip()
    onvif_url = str(payload.get("onvif_url", "")).strip()
    ptz_url = str(payload.get("ptz_url", "")).strip()
    if not partial or "name" in payload:
        if not name:
            errors["name"] = "Name is required."
    if not partial or "rtsp_url" in payload:
        if not rtsp_url:
            errors["rtsp_url"] = "RTSP URL is required."
        elif not rtsp_url.startswith(STREAM_URL_PREFIXES):
            errors["rtsp_url"] = "Use an rtsp://, rtsps://, http://, or https:// stream URL."
    if audio_url and not audio_url.startswith(STREAM_URL_PREFIXES):
        errors["audio_url"] = "Use an rtsp://, rtsps://, http://, or https:// audio URL."
    if audio_url and normalize_bool(payload.get("record_audio", True)):
        errors["audio_url"] = "Separate audio URLs are not supported by the go2rtc-only restream path."
    if "grayscale_mode" in payload and normalize_grayscale_mode(payload.get("grayscale_mode")) != str(payload.get("grayscale_mode") or "").strip().lower():
        errors["grayscale_mode"] = "Use off, always, or auto."
    if "live_view_mode" in payload and str(payload.get("live_view_mode") or "hls").strip().lower() != "hls":
        errors["live_view_mode"] = "Use hls."
    if "view_rotation" in payload:
        try:
            normalize_view_rotation(payload.get("view_rotation"))
        except ValueError:
            errors["view_rotation"] = "Use 0, 90, 180, or 270."
    if onvif_url and not onvif_url.startswith(CONTROL_URL_PREFIXES):
        errors["onvif_url"] = "Use an http:// or https:// ONVIF device endpoint URL."
    ptz_type = normalize_ptz_type(payload.get("ptz_type"))
    if ptz_url and ptz_type == "onvif" and not ptz_url.startswith(CONTROL_URL_PREFIXES):
        errors["ptz_url"] = "Use an http:// or https:// ONVIF endpoint URL."
    if ptz_url and ptz_type == "victure_dvrip" and "://" in ptz_url and not ptz_url.startswith(DVRIP_URL_PREFIXES):
        errors["ptz_url"] = "Use a dvrip:// host URL, or leave blank to use the stream host."
    if ptz_url and ptz_type == "victure_direct" and "://" in ptz_url and not ptz_url.startswith(CONTROL_URL_PREFIXES):
        errors["ptz_url"] = "Use an http:// admin URL, or leave blank to use the stream host."
    if "ptz_type" in payload and ptz_type != str(payload.get("ptz_type") or "").strip().lower():
        errors["ptz_type"] = "Use none, onvif, victure_dvrip, or victure_direct."
    if "ptz_speed" in payload:
        try:
            normalize_ptz_speed(payload.get("ptz_speed"))
        except ValueError:
            errors["ptz_speed"] = "Use a PTZ speed from 0.05 to 1.0."
    if "ptz_profile_token" in payload and len(str(payload.get("ptz_profile_token") or "")) > 80:
        errors["ptz_profile_token"] = "Profile token is too long."
    if "ptz_zoom_mode" in payload and normalize_ptz_zoom_mode(payload.get("ptz_zoom_mode")) != str(payload.get("ptz_zoom_mode") or "").strip().lower():
        errors["ptz_zoom_mode"] = "Use auto, digital, hardware, or none."
    if errors:
        raise ValueError(json.dumps(errors))


def normalize_grayscale_mode(value):
    value = str(value or "off").strip().lower()
    return value if value in ("off", "always", "auto") else "off"


def normalize_live_view_mode(value):
    value = str(value or "hls").strip().lower()
    return "hls"


def normalize_view_rotation(value):
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("Invalid view rotation.") from exc
    if parsed not in (0, 90, 180, 270):
        raise ValueError("Invalid view rotation.")
    return parsed


def normalize_ptz_type(value):
    value = str(value or "onvif").strip().lower()
    return value if value in PTZ_TYPES else "none"


def normalize_ptz_profile_token(value):
    value = str(value or "").strip()
    return value[:80] or DEFAULT_PTZ_PROFILE_TOKEN


def normalize_ptz_zoom_mode(value):
    value = str(value or "auto").strip().lower()
    return value if value in ("auto", "digital", "hardware", "none") else "auto"


def normalize_ptz_speed(value):
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("Invalid PTZ speed.") from exc
    if parsed < 0.05 or parsed > 1.0:
        raise ValueError("Invalid PTZ speed.")
    return round(parsed, 2)


def stable_camera_value(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def create_camera(payload):
    validate_camera_payload(payload)
    now = iso_now()
    camera_id = uuid.uuid4().hex
    schedule = normalize_schedule(payload.get("schedule"))
    segment_seconds = max(10, int(payload.get("segment_seconds") or DEFAULT_SEGMENT_SECONDS))
    retention_days = max(1, int(payload.get("retention_days") or 14))
    ptz_type = normalize_ptz_type(payload.get("ptz_type"))
    ptz_speed = normalize_ptz_speed(payload.get("ptz_speed", DEFAULT_PTZ_SPEED))
    with db_conn() as conn:
        slug = unique_slug(conn, payload["name"])
        conn.execute(
            """
            INSERT INTO cameras (
                id, name, slug, rtsp_url, audio_url, enabled, segment_seconds, retention_days,
                schedule_json, record_audio, grayscale_mode, live_view_mode, rtsp_transport, ptz_enabled, ptz_type,
                view_rotation, onvif_url, ptz_url, ptz_profile_token, ptz_zoom_mode, ptz_speed, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                camera_id,
                payload["name"].strip(),
                slug,
                payload["rtsp_url"].strip(),
                str(payload.get("audio_url", "")).strip(),
                normalize_bool(payload.get("enabled", True)),
                segment_seconds,
                retention_days,
                json.dumps(schedule),
                normalize_bool(payload.get("record_audio", True)),
                normalize_grayscale_mode(payload.get("grayscale_mode")),
                normalize_live_view_mode(payload.get("live_view_mode")),
                payload.get("rtsp_transport", "tcp") if payload.get("rtsp_transport") in ("tcp", "udp") else "tcp",
                normalize_bool(payload.get("ptz_enabled", False)),
                ptz_type,
                normalize_view_rotation(payload.get("view_rotation", 0)),
                str(payload.get("onvif_url", "")).strip(),
                str(payload.get("ptz_url", "")).strip(),
                normalize_ptz_profile_token(payload.get("ptz_profile_token")),
                normalize_ptz_zoom_mode(payload.get("ptz_zoom_mode")),
                ptz_speed,
                now,
                now,
            ),
        )
    camera = get_camera(camera_id)
    manager = globals().get("go2rtc")
    if manager:
        manager.configure_camera(camera)
    return camera


def update_camera(camera_id, payload):
    existing = get_camera(camera_id)
    if not existing:
        return None
    validate_camera_payload(payload, partial=True)
    merged = {**existing, **payload}
    schedule = normalize_schedule(merged.get("schedule"))
    segment_seconds = max(10, int(merged.get("segment_seconds") or DEFAULT_SEGMENT_SECONDS))
    retention_days = max(1, int(merged.get("retention_days") or 14))
    ptz_type = normalize_ptz_type(merged.get("ptz_type"))
    ptz_speed = normalize_ptz_speed(merged.get("ptz_speed", DEFAULT_PTZ_SPEED))
    restart_fields = (
        "name",
        "rtsp_url",
        "audio_url",
        "enabled",
        "segment_seconds",
        "retention_days",
        "schedule",
        "record_audio",
        "grayscale_mode",
        "live_view_mode",
        "rtsp_transport",
    )
    restart_required = any(
        stable_camera_value(existing.get(key)) != stable_camera_value(merged.get(key))
        for key in restart_fields
    )
    discovery_changed = any(
        str(existing.get(key) or "") != str(merged.get(key) or "")
        for key in ("rtsp_url", "onvif_url", "ptz_url", "ptz_profile_token", "ptz_type")
    )
    onvif_json = "{}" if discovery_changed else json.dumps(existing.get("onvif") or {})
    onvif_updated_at = "" if discovery_changed else str(existing.get("onvif_updated_at") or "")
    with db_conn() as conn:
        slug = unique_slug(conn, merged["name"], camera_id)
        conn.execute(
            """
            UPDATE cameras
            SET name = ?, slug = ?, rtsp_url = ?, audio_url = ?, enabled = ?, segment_seconds = ?,
                retention_days = ?, schedule_json = ?, record_audio = ?, grayscale_mode = ?,
                live_view_mode = ?, view_rotation = ?, rtsp_transport = ?, ptz_enabled = ?, ptz_type = ?, onvif_url = ?, ptz_url = ?,
                ptz_profile_token = ?, ptz_zoom_mode = ?, ptz_speed = ?, onvif_json = ?, onvif_updated_at = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                str(merged["name"]).strip(),
                slug,
                str(merged["rtsp_url"]).strip(),
                str(merged.get("audio_url", "")).strip(),
                normalize_bool(merged.get("enabled")),
                segment_seconds,
                retention_days,
                json.dumps(schedule),
                normalize_bool(merged.get("record_audio")),
                normalize_grayscale_mode(merged.get("grayscale_mode")),
                normalize_live_view_mode(merged.get("live_view_mode")),
                normalize_view_rotation(merged.get("view_rotation", 0)),
                merged.get("rtsp_transport") if merged.get("rtsp_transport") in ("tcp", "udp") else "tcp",
                normalize_bool(merged.get("ptz_enabled")),
                ptz_type,
                str(merged.get("onvif_url", "")).strip(),
                str(merged.get("ptz_url", "")).strip(),
                normalize_ptz_profile_token(merged.get("ptz_profile_token")),
                normalize_ptz_zoom_mode(merged.get("ptz_zoom_mode")),
                ptz_speed,
                onvif_json,
                onvif_updated_at,
                iso_now(),
                camera_id,
            ),
        )
    camera = get_camera(camera_id)
    if restart_required:
        manager = globals().get("go2rtc")
        if manager:
            manager.configure_camera(camera)
        recorder.restart(camera_id)
        relay.stop(camera_id)
    return camera


def delete_camera(camera_id):
    recorder.stop(camera_id)
    relay.stop(camera_id)
    manager = globals().get("go2rtc")
    if manager:
        manager.delete_camera(camera_id)
    with db_conn() as conn:
        cur = conn.execute("DELETE FROM cameras WHERE id = ?", (camera_id,))
    return cur.rowcount > 0


def add_event(camera_id, level, message):
    if not event_level_enabled(level):
        return
    try:
        with db_conn() as conn:
            previous = conn.execute(
                """
                SELECT created_at
                FROM recorder_events
                WHERE camera_id = ? AND level = ? AND message = ?
                ORDER BY id DESC
                LIMIT 1
                """,
                (camera_id, level, message[:500]),
            ).fetchone()
            if previous:
                try:
                    previous_at = datetime.fromisoformat(previous["created_at"])
                    if utcnow() - previous_at < timedelta(seconds=60):
                        return
                except (TypeError, ValueError):
                    pass
            conn.execute(
                "INSERT INTO recorder_events (camera_id, level, message, created_at) VALUES (?, ?, ?, ?)",
                (camera_id, level, message[:500], iso_now()),
            )
            conn.execute(
                """
                DELETE FROM recorder_events
                WHERE id NOT IN (
                    SELECT id FROM recorder_events
                    WHERE camera_id = ?
                    ORDER BY id DESC
                    LIMIT 50
                ) AND camera_id = ?
                """,
                (camera_id, camera_id),
            )
    except sqlite3.Error:
        pass


def camera_dir(camera):
    return RECORDINGS_DIR / camera["slug"]


def ensure_recording_directory(camera):
    target_dir = camera_dir(camera)
    probe_path = target_dir / f".plainnvr-write-test-{uuid.uuid4().hex}"
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
        with probe_path.open("wb") as handle:
            handle.write(b"")
        probe_path.unlink()
    except OSError as exc:
        try:
            probe_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise RuntimeError(
            "Recording directory is not writable: "
            f"{target_dir}. Check storage ownership or ACLs for UID {os.getuid()} "
            f"and GID {os.getgid()}."
        ) from exc
    return target_dir


class Go2RTCManager(BaseGo2RTCManager):
    def __init__(self):
        super().__init__(
            data_dir=DATA_DIR,
            binary=GO2RTC_BIN,
            api_host=GO2RTC_API_HOST,
            api_port=GO2RTC_API_PORT,
            rtsp_host=GO2RTC_RTSP_HOST,
            rtsp_port=GO2RTC_RTSP_PORT,
            webrtc_port=GO2RTC_WEBRTC_PORT,
            ffmpeg_bin=FFMPEG_BIN,
            start_timeout_seconds=GO2RTC_START_TIMEOUT_SECONDS,
            media_stale_seconds=GO2RTC_MEDIA_STALE_SECONDS,
            stream_url_prefixes=STREAM_URL_PREFIXES,
            log_level_provider=app_log_level,
        )


go2rtc = Go2RTCManager()
relay = Go2RTCSourceManager(go2rtc)


def build_ffmpeg_command(
    camera,
    source_camera=None,
):
    return build_ffmpeg_command_impl(
        camera,
        source_camera=(
            source_camera
            or relay.source_camera(camera)
        ),
        ensure_recording_directory=ensure_recording_directory,
        ffmpeg_bin=FFMPEG_BIN,
        ffmpeg_input_args=ffmpeg_input_args,
        default_segment_seconds=DEFAULT_SEGMENT_SECONDS,
    )


def ffmpeg_input_args(
    camera,
    url_key="rtsp_url",
    low_latency=True,
):
    return ffmpeg_input_args_impl(
        camera,
        url_key,
        low_latency,
        rtsp_probesize=RTSP_PROBESIZE,
        rtsp_analyze_duration=RTSP_ANALYZE_DURATION,
        rtsp_live_probesize=RTSP_LIVE_PROBESIZE,
        rtsp_live_analyze_duration=RTSP_LIVE_ANALYZE_DURATION,
        rtsp_thread_queue_size=RTSP_THREAD_QUEUE_SIZE,
        rtsp_read_timeout_seconds=RTSP_READ_TIMEOUT_SECONDS,
    )


def grayscale_enabled(camera):
    mode = normalize_grayscale_mode(
        camera.get("grayscale_mode")
    )
    if mode == "always":
        return True
    if mode == "auto":
        return night_modes.is_night(
            camera["id"]
        )
    return False


def add_video_filters(command, filters):
    return add_video_filters_impl(
        command,
        filters,
    )


def build_snapshot_command(
    camera,
    grayscale=False,
):
    return build_snapshot_command_impl(
        camera,
        source_camera=relay.source_camera(camera),
        ffmpeg_bin=FFMPEG_BIN,
        ffmpeg_input_args=ffmpeg_input_args,
        grayscale_enabled=grayscale_enabled,
        grayscale=grayscale,
    )


def dvrip_send_packet(
    sock,
    session,
    number,
    packet_type,
    payload,
):
    return dvrip_send_packet_impl(
        sock,
        session,
        number,
        packet_type,
        payload,
        header=DVRIP_HEADER,
    )


def dvrip_recv_packet(sock):
    return dvrip_recv_packet_impl(
        sock,
        header=DVRIP_HEADER,
    )


def dvrip_login(sock, target):
    return dvrip_login_impl(
        sock,
        target,
        header=DVRIP_HEADER,
    )


def dvrip_query_time(sock, session, number=4):
    return dvrip_query_time_impl(
        sock,
        session,
        number=number,
        header=DVRIP_HEADER,
    )


def dvrip_target(camera):
    return dvrip_target_impl(
        camera,
        default_profile_token=DEFAULT_PTZ_PROFILE_TOKEN,
        default_port=DVRIP_DEFAULT_PORT,
        default_user=DVRIP_DEFAULT_USER,
        default_passhash=DVRIP_DEFAULT_PASSHASH,
    )


def camera_time(camera, requested=None):
    return camera_time_impl(
        camera,
        requested,
        normalize_ptz_type=normalize_ptz_type,
        default_profile_token=DEFAULT_PTZ_PROFILE_TOKEN,
        default_port=DVRIP_DEFAULT_PORT,
        default_user=DVRIP_DEFAULT_USER,
        default_passhash=DVRIP_DEFAULT_PASSHASH,
        header=DVRIP_HEADER,
    )


def run_victure_dvrip_ptz_command(
    camera,
    action,
    speed,
    duration_ms,
):
    return run_victure_dvrip_ptz_command_impl(
        camera,
        action,
        speed,
        duration_ms,
        commands=DVRIP_PTZ_COMMANDS,
        move_vectors=PTZ_MOVE_VECTORS,
        default_profile_token=DEFAULT_PTZ_PROFILE_TOKEN,
        default_port=DVRIP_DEFAULT_PORT,
        default_user=DVRIP_DEFAULT_USER,
        default_passhash=DVRIP_DEFAULT_PASSHASH,
        header=DVRIP_HEADER,
    )


def victure_direct_target(camera):
    return victure_direct_target_impl(
        camera,
        default_port=VICTURE_DIRECT_DEFAULT_PORT,
    )


def run_victure_direct_ptz_command(
    camera,
    action,
    speed,
):
    return run_victure_direct_ptz_command_impl(
        camera,
        action,
        speed,
        direct_actions=VICTURE_DIRECT_ACTIONS,
        default_port=VICTURE_DIRECT_DEFAULT_PORT,
    )


def onvif_move_body(
    action,
    speed,
    duration_ms,
    profile_token,
    continuous=False,
):
    return onvif_move_body_impl(
        action,
        speed,
        duration_ms,
        profile_token,
        move_vectors=PTZ_MOVE_VECTORS,
        continuous=continuous,
    )


def run_ptz_command(camera, payload):
    return run_ptz_command_impl(
        camera,
        payload,
        normalize_ptz_type=normalize_ptz_type,
        normalize_ptz_speed=normalize_ptz_speed,
        normalize_bool=normalize_bool,
        bounded_int=bounded_int,
        default_ptz_speed=DEFAULT_PTZ_SPEED,
        default_duration_ms=PTZ_DEFAULT_DURATION_MS,
        move_vectors=PTZ_MOVE_VECTORS,
        run_victure_dvrip=run_victure_dvrip_ptz_command,
        run_victure_direct=run_victure_direct_ptz_command,
        discover_camera_onvif=discover_camera_onvif,
        onvif_error=OnvifError,
        normalize_ptz_profile_token=normalize_ptz_profile_token,
        onvif_payload_credentials=onvif_payload_credentials,
        onvif_allowed_endpoint_hosts=onvif_allowed_endpoint_hosts,
        onvif_soap_post=onvif_soap_post,
        goto_preset_body=goto_preset_body,
    )


class NightModeManager(BaseNightModeManager):
    def __init__(self):
        super().__init__(
            ffmpeg_bin=FFMPEG_BIN,
            ffmpeg_input_args=ffmpeg_input_args,
            list_cameras=list_cameras,
            iso_now=iso_now,
            sample_interval_seconds=NIGHT_SAMPLE_INTERVAL_SECONDS,
            on_seconds=NIGHT_ON_SECONDS,
            off_seconds=NIGHT_OFF_SECONDS,
            on_brightness=NIGHT_ON_BRIGHTNESS,
            on_saturation=NIGHT_ON_SATURATION,
            dark_brightness=NIGHT_DARK_BRIGHTNESS,
            off_brightness=NIGHT_OFF_BRIGHTNESS,
            off_saturation=NIGHT_OFF_SATURATION,
        )


night_modes = NightModeManager()


class RecorderSupervisor(BaseRecorderSupervisor):
    def __init__(self):
        super().__init__(
            relay=relay,
            build_ffmpeg_command=build_ffmpeg_command,
            add_event=add_event,
            redact_camera_text=lambda text, camera: redact_camera_text(
                text, camera
            ),
            get_camera=get_camera,
            camera_dir=camera_dir,
            list_cameras=list_cameras,
            schedule_active=schedule_active,
            iso_now=iso_now,
            scan_interval_seconds=SCAN_INTERVAL_SECONDS,
            retention_interval_seconds=RETENTION_INTERVAL_SECONDS,
            start_grace_seconds=RECORDER_START_GRACE_SECONDS,
            stale_seconds=RECORDER_STALE_SECONDS,
        )


recorder = RecorderSupervisor()


def scan_segments(camera, date_value=None):
    return scan_segments_impl(
        camera,
        date_value,
        camera_dir=camera_dir,
        segment_re=SEGMENT_RE,
    )


def segment_start(path):
    return segment_start_impl(path, SEGMENT_RE)


def recording_coverage(camera):
    return recording_coverage_impl(
        camera,
        camera_dir=camera_dir,
        segment_re=SEGMENT_RE,
    )


def probe_stream_url(
    url,
    payload,
    select_streams,
    show_entries,
    low_latency=True,
):
    return probe_stream_url_impl(
        url,
        payload,
        select_streams,
        show_entries,
        stream_url_prefixes=STREAM_URL_PREFIXES,
        ffprobe_bin=FFPROBE_BIN,
        rtsp_probesize=RTSP_PROBESIZE,
        rtsp_analyze_duration=RTSP_ANALYZE_DURATION,
        rtsp_live_probesize=RTSP_LIVE_PROBESIZE,
        rtsp_live_analyze_duration=RTSP_LIVE_ANALYZE_DURATION,
        low_latency=low_latency,
    )


def test_stream(payload):
    return test_stream_impl(
        payload,
        stream_url_prefixes=STREAM_URL_PREFIXES,
        normalize_bool=normalize_bool,
        probe_stream_url=probe_stream_url,
    )


def redact_camera_text(text, camera):
    return redact_camera_text_impl(text, camera)


def stream_summary(probe):
    return stream_summary_impl(probe)


def live_diagnostics(camera, include_audio=True):
    return live_diagnostics_impl(
        camera,
        include_audio,
        probe_stream_url=probe_stream_url,
        go2rtc=go2rtc,
        redact_camera_text=redact_camera_text,
    )


def compatibility_recommendations(stream_result, discovery):
    return compatibility_recommendations_impl(
        stream_result,
        discovery,
    )


def camera_compatibility_report(
    camera,
    refresh_onvif=True,
):
    return camera_compatibility_report_impl(
        camera,
        refresh_onvif,
        test_stream=test_stream,
        discover_camera_onvif=discover_camera_onvif,
        onvif_error=OnvifError,
        iso_now=iso_now,
        server_version=NvrHandler.server_version,
        go2rtc=go2rtc,
        redact_onvif_url=redact_onvif_url,
        redacted_discovery=redacted_discovery,
        relay=relay,
        recorder=recorder,
        recording_coverage=recording_coverage,
        compatibility_recommendations=compatibility_recommendations,
        redact_camera_text=redact_camera_text,
    )


def get_recent_events(camera_id=None):
    with db_conn() as conn:
        if camera_id:
            rows = conn.execute(
                "SELECT * FROM recorder_events WHERE camera_id = ? ORDER BY id DESC LIMIT 20",
                (camera_id,),
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM recorder_events ORDER BY id DESC LIMIT 50").fetchall()
    return [dict(row) for row in rows]


def disk_status():
    RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)
    usage = shutil.disk_usage(RECORDINGS_DIR)
    return {"total": usage.total, "used": usage.used, "free": usage.free}


def parse_cookie_header(value):
    cookies = {}
    for part in str(value or "").split(";"):
        if "=" not in part:
            continue
        key, raw_value = part.split("=", 1)
        cookies[key.strip()] = raw_value.strip()
    return cookies


def bearer_token(headers):
    value = headers.get("Authorization", "")
    scheme, _, token = value.partition(" ")
    if scheme.lower() == "bearer" and token:
        return token.strip()
    return ""


def basic_auth_credentials(headers):
    value = headers.get("Authorization", "")
    scheme, _, token = value.partition(" ")
    if scheme.lower() != "basic" or not token:
        return None, None
    try:
        decoded = base64.b64decode(token, validate=True).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return None, None
    username, separator, password = decoded.partition(":")
    if not separator:
        return None, None
    return username, password


def valid_stream_auth(handler, parsed):
    expected = get_stream_token()
    query = parse_qs(parsed.query)
    provided = query.get("token", [""])[0] or bearer_token(handler.headers)
    if expected and provided and hmac.compare_digest(provided.encode("utf-8"), expected.encode("utf-8")):
        return True
    username, password = basic_auth_credentials(handler.headers)
    if not username:
        return False
    peer = handler.client_address[0]
    if basic_failure_limiter.blocked(peer):
        return False
    authenticated = bool(authenticate_user(username, password))
    if not authenticated:
        basic_failure_limiter.allow(peer)
    return authenticated


class LoginLimiter:
    """Bound unauthenticated password work per peer without trusting proxy headers."""
    def __init__(self):
        self.lock = threading.Lock()
        self.attempts = {}

    def blocked(self, peer):
        with self.lock:
            started, count = self.attempts.get(peer, (0, 0))
            return count >= 20 and time.monotonic() - started < 60

    def allow(self, peer):
        now = time.monotonic()
        with self.lock:
            self.attempts = {key: entry for key, entry in self.attempts.items() if now - entry[0] < 60}
            started, count = self.attempts.get(peer, (now, 0))
            if count >= 20 or (peer not in self.attempts and len(self.attempts) >= 4096):
                return False
            self.attempts[peer] = (started, count + 1)
            return True


login_limiter = LoginLimiter()
basic_failure_limiter = LoginLimiter()


class NvrHandler(SimpleHTTPRequestHandler):
    server_version = "PlainNVR/0.1"

    def setup(self):
        super().setup()
        self.connection.settimeout(30)

    def ensure_same_origin(self):
        # Native clients omit Origin. Browsers must use the same public host,
        # including port, for mutations and authenticated WebSocket sessions.
        origin = self.headers.get("Origin")
        if origin:
            parsed = urlparse(origin)
            if parsed.scheme not in ("http", "https") or parsed.netloc.lower() != self.headers.get("Host", "").lower():
                self.send_error_json(HTTPStatus.FORBIDDEN, "Cross-origin request denied.")
                return False
        if self.headers.get("Sec-Fetch-Site") == "cross-site":
            self.send_error_json(HTTPStatus.FORBIDDEN, "Cross-site request denied.")
            return False
        return True

    def end_headers(self):
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Content-Security-Policy", "frame-ancestors 'none'; base-uri 'self'")
        self.send_header("Referrer-Policy", "same-origin")
        super().end_headers()

    def log_message(self, fmt, *args):
        message = fmt % args
        message = re.sub(r"([?&]token=)[^\s&]+", r"\1<redacted>", message)
        print(f"{self.address_string()} - {message}")

    def send_json(self, value, status=HTTPStatus.OK, headers=None, indent=None):
        data = json.dumps(value, indent=indent).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "no-store")
        for key, header_value in (headers or {}).items():
            self.send_header(key, header_value)
        self.end_headers()
        if getattr(self, "command", "GET") != "HEAD":
            self.wfile.write(data)

    def send_error_json(self, status, message):
        self.send_json({"error": message}, status)

    def session_id(self):
        return parse_cookie_header(self.headers.get("Cookie", "")).get(AUTH_COOKIE_NAME, "")

    def auth_user(self):
        if not hasattr(self, "_auth_user"):
            self._auth_user = current_session_user(self.session_id())
        return self._auth_user

    def is_public_path(self, parsed):
        public_paths = {
            "/login.html",
            "/styles.css",
            "/favicon.ico",
            "/api/health",
            "/api/auth/state",
            "/api/auth/login",
            "/api/auth/setup",
        }
        return parsed.path in public_paths

    def ensure_authorized(self, parsed):
        if self.is_public_path(parsed):
            return True
        if parsed.path.startswith(("/ha/", "/live/", "/media/")):
            if valid_stream_auth(self, parsed):
                return True
            if parsed.path.startswith("/ha/"):
                self.send_basic_auth_required()
                return False
        if self.auth_user():
            return True
        if parsed.path.startswith("/api/"):
            self.send_error_json(HTTPStatus.UNAUTHORIZED, "Authentication required.")
        else:
            self.redirect("/login.html")
        return False

    def redirect(self, location):
        self.send_response(HTTPStatus.SEE_OTHER)
        self.send_header("Location", location)
        self.send_header("Content-Length", "0")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()

    def send_basic_auth_required(self):
        self.send_response(HTTPStatus.UNAUTHORIZED)
        self.send_header("WWW-Authenticate", 'Basic realm="PlainNVR"')
        self.send_header("Content-Length", "0")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()

    def session_cookie(self, session_id):
        return (
            f"{AUTH_COOKIE_NAME}={session_id}; Path=/; HttpOnly; SameSite=Lax; "
            f"Max-Age={AUTH_SESSION_TTL_SECONDS}"
        )

    def expired_session_cookie(self):
        return f"{AUTH_COOKIE_NAME}=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0"

    def do_GET(self):
        parsed = urlparse(self.path)
        if not self.ensure_authorized(parsed):
            return
        if parsed.path == "/login.html" and self.auth_user() and not setup_required():
            self.redirect("/")
            return
        if parsed.path.startswith("/api/"):
            self.handle_api_get(parsed)
            return
        if parsed.path.startswith("/go2rtc/"):
            self.handle_go2rtc_proxy(parsed)
            return
        if parsed.path.startswith("/ha/"):
            self.handle_home_assistant(parsed)
            return
        if parsed.path.startswith("/live/"):
            self.handle_live_hls(parsed)
            return
        if parsed.path.startswith("/media/"):
            self.handle_media(parsed.path)
            return
        self.serve_static(parsed.path)

    def do_HEAD(self):
        parsed = urlparse(self.path)
        if not self.ensure_authorized(parsed):
            return
        if parsed.path.startswith("/ha/"):
            self.handle_home_assistant_head(parsed)
            return
        if parsed.path.startswith("/live/"):
            self.handle_live_hls_head(parsed)
            return
        if parsed.path.startswith("/media/"):
            self.handle_media(parsed.path, head_only=True)
            return
        if parsed.path.startswith("/api/"):
            self.send_response(HTTPStatus.METHOD_NOT_ALLOWED)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if parsed.path.startswith("/go2rtc/"):
            self.handle_go2rtc_proxy(parsed, head_only=True)
            return
        self.serve_static(parsed.path, head_only=True)

    def do_POST(self):
        if not self.ensure_same_origin():
            return
        parsed = urlparse(self.path)
        if not self.ensure_authorized(parsed):
            return
        if parsed.path in ("/api/auth/login", "/api/auth/setup") and not login_limiter.allow(self.client_address[0]):
            self.send_json({"error": "Too many login attempts. Try again in a minute."}, HTTPStatus.TOO_MANY_REQUESTS, headers={"Retry-After": "60"})
            return
        try:
            payload = parse_json_body(self)
        except ValueError as exc:
            self.send_error_json(HTTPStatus.BAD_REQUEST, str(exc))
            return
        if parsed.path == "/api/auth/setup":
            self.handle_auth_setup(payload)
            return
        if parsed.path == "/api/auth/login":
            self.handle_auth_login(payload)
            return
        if parsed.path == "/api/auth/logout":
            delete_session(self.session_id())
            self.send_json({"ok": True}, headers={"Set-Cookie": self.expired_session_cookie()})
            return
        if parsed.path == "/api/cameras":
            try:
                camera = create_camera(payload)
            except ValueError as exc:
                self.send_error_json(HTTPStatus.BAD_REQUEST, str(exc))
                return
            self.send_json(camera, HTTPStatus.CREATED)
            return
        if parsed.path == "/api/onvif/discover":
            self.handle_onvif_discovery(payload)
            return
        match = re.match(
            r"^/api/cameras/([a-f0-9]+)/(onvif/discover|compatibility)$",
            parsed.path,
        )
        if match:
            if match.group(2) == "onvif/discover":
                self.handle_camera_onvif_discovery(match.group(1), payload)
            else:
                self.handle_camera_compatibility(match.group(1))
            return
        match = re.match(r"^/api/cameras/([a-f0-9]+)/ptz$", parsed.path)
        if match:
            self.handle_camera_ptz(match.group(1), payload)
            return
        match = re.match(r"^/api/cameras/([a-f0-9]+)/time$", parsed.path)
        if match:
            self.handle_camera_time(match.group(1), payload)
            return
        match = re.match(r"^/api/cameras/([a-f0-9]+)/(recorder|live)/(start|stop|restart)$", parsed.path)
        if match:
            self.handle_camera_control(match.group(1), match.group(2), match.group(3))
            return
        if parsed.path == "/api/test-stream":
            try:
                self.send_json(test_stream(payload))
            except ValueError as exc:
                self.send_error_json(HTTPStatus.BAD_REQUEST, str(exc))
            return
        if parsed.path == "/api/users":
            try:
                username = create_user(payload.get("username"), payload.get("password"))
            except ValueError as exc:
                self.send_error_json(HTTPStatus.BAD_REQUEST, str(exc))
                return
            self.send_json({"ok": True, "username": username}, HTTPStatus.CREATED)
            return
        self.send_error_json(HTTPStatus.NOT_FOUND, "Not found.")

    def do_PUT(self):
        if not self.ensure_same_origin():
            return
        parsed = urlparse(self.path)
        if not self.ensure_authorized(parsed):
            return
        try:
            payload = parse_json_body(self)
        except ValueError as exc:
            self.send_error_json(HTTPStatus.BAD_REQUEST, str(exc))
            return
        if parsed.path == "/api/settings":
            previous = get_app_settings()
            try:
                settings = update_app_settings(payload)
            except ValueError as exc:
                self.send_error_json(HTTPStatus.BAD_REQUEST, str(exc))
                return
            if settings["log_level"] != previous["log_level"]:
                go2rtc.shutdown()
                with go2rtc.lock:
                    go2rtc.stream_keys.clear()
                    go2rtc.media_states.clear()
                go2rtc.start(list_cameras())
            self.send_json({"settings": settings})
            return
        match = re.match(r"^/api/cameras/([a-f0-9]+)$", parsed.path)
        if match:
            try:
                camera = update_camera(match.group(1), payload)
            except ValueError as exc:
                self.send_error_json(HTTPStatus.BAD_REQUEST, str(exc))
                return
            if not camera:
                self.send_error_json(HTTPStatus.NOT_FOUND, "Camera not found.")
                return
            self.send_json(camera)
            return
        self.send_error_json(HTTPStatus.NOT_FOUND, "Not found.")

    def do_DELETE(self):
        if not self.ensure_same_origin():
            return
        parsed = urlparse(self.path)
        if not self.ensure_authorized(parsed):
            return
        match = re.match(r"^/api/cameras/([a-f0-9]+)$", parsed.path)
        if match:
            if delete_camera(match.group(1)):
                self.send_json({"ok": True})
            else:
                self.send_error_json(HTTPStatus.NOT_FOUND, "Camera not found.")
            return
        match = re.match(r"^/api/users/([^/]+)$", parsed.path)
        if match:
            try:
                deleted = delete_user(match.group(1), self.auth_user())
            except ValueError as exc:
                self.send_error_json(HTTPStatus.BAD_REQUEST, str(exc))
                return
            if deleted:
                self.send_json({"ok": True})
            else:
                self.send_error_json(HTTPStatus.NOT_FOUND, "User not found.")
            return
        self.send_error_json(HTTPStatus.NOT_FOUND, "Not found.")

    def handle_auth_setup(self, payload):
        if not setup_required():
            self.send_error_json(HTTPStatus.CONFLICT, "Admin account already exists.")
            return
        try:
            username = create_user(payload.get("username"), payload.get("password"), initial_setup=True)
        except ValueError as exc:
            self.send_error_json(HTTPStatus.BAD_REQUEST, str(exc))
            return
        session_id = create_session(username)
        self.send_json(
            {"ok": True, "username": username},
            HTTPStatus.CREATED,
            headers={"Set-Cookie": self.session_cookie(session_id)},
        )

    def handle_auth_login(self, payload):
        username = authenticate_user(payload.get("username"), payload.get("password"))
        if not username:
            self.send_error_json(HTTPStatus.UNAUTHORIZED, "Invalid username or password.")
            return
        session_id = create_session(username)
        self.send_json({"ok": True, "username": username}, headers={"Set-Cookie": self.session_cookie(session_id)})

    def handle_camera_control(self, camera_id, target, action):
        camera = get_camera(camera_id)
        if not camera:
            self.send_error_json(HTTPStatus.NOT_FOUND, "Camera not found.")
            return
        if target == "recorder":
            self.handle_recorder_control(camera, action)
            return
        self.handle_live_control(camera, action)

    def handle_recorder_control(self, camera, action):
        if action == "stop":
            recorder.pause(camera["id"])
        elif action == "start":
            if not camera["enabled"]:
                self.send_error_json(HTTPStatus.CONFLICT, "Camera is disabled.")
                return
            recorder.resume(camera)
        elif action == "restart":
            if not camera["enabled"]:
                self.send_error_json(HTTPStatus.CONFLICT, "Camera is disabled.")
                return
            recorder.restart_now(camera)
        self.send_json({"ok": True, "recorders": recorder.status(), "events": get_recent_events()})

    def handle_live_control(self, camera, action):
        # Live controls belong to a viewer. Deleting the shared source here
        # disconnects every viewer and the recorder when one client retries.
        self.send_json({"ok": True, "scope": "viewer"})

    def handle_camera_ptz(self, camera_id, payload):
        camera = get_camera(camera_id)
        if not camera:
            self.send_error_json(HTTPStatus.NOT_FOUND, "Camera not found.")
            return
        try:
            result = run_ptz_command(camera, payload)
        except ValueError as exc:
            self.send_error_json(HTTPStatus.BAD_REQUEST, str(exc))
            return
        except RuntimeError as exc:
            self.send_error_json(HTTPStatus.BAD_GATEWAY, redact_camera_text(str(exc), camera))
            return
        self.send_json(result)

    def handle_onvif_discovery(self, payload):
        rtsp_url = str(payload.get("rtsp_url") or "").strip()
        onvif_url = str(payload.get("onvif_url") or "").strip()
        ptz_url = str(payload.get("ptz_url") or "").strip()
        if not rtsp_url and not onvif_url and not ptz_url:
            self.send_error_json(
                HTTPStatus.BAD_REQUEST,
                "Enter a stream URL or ONVIF device URL first.",
            )
            return
        try:
            result = discover_camera_onvif(payload)
        except OnvifError as exc:
            self.send_error_json(HTTPStatus.BAD_GATEWAY, str(exc))
            return
        self.send_json(result)

    def handle_camera_onvif_discovery(self, camera_id, payload=None):
        camera = get_camera(camera_id)
        if not camera:
            self.send_error_json(HTTPStatus.NOT_FOUND, "Camera not found.")
            return
        try:
            result = discover_camera_onvif({**camera, **(payload or {})}, camera_id)
        except OnvifError as exc:
            self.send_error_json(
                HTTPStatus.BAD_GATEWAY,
                redact_camera_text(str(exc), camera),
            )
            return
        self.send_json(result)

    def handle_camera_compatibility(self, camera_id, download=False):
        camera = get_camera(camera_id)
        if not camera:
            self.send_error_json(HTTPStatus.NOT_FOUND, "Camera not found.")
            return
        report = camera_compatibility_report(camera, refresh_onvif=True)
        headers = None
        if download:
            headers = {
                "Content-Disposition": (
                    f'attachment; filename="plainnvr-{camera["slug"]}-compatibility.json"'
                )
            }
        self.send_json(report, headers=headers, indent=2 if download else None)

    def handle_camera_time(self, camera_id, payload=None):
        camera = get_camera(camera_id)
        if not camera:
            self.send_error_json(HTTPStatus.NOT_FOUND, "Camera not found.")
            return
        try:
            result = camera_time(camera, None if payload is None else payload.get("time"))
        except ValueError as exc:
            self.send_error_json(HTTPStatus.BAD_REQUEST, str(exc))
            return
        except RuntimeError as exc:
            self.send_error_json(HTTPStatus.BAD_GATEWAY, redact_camera_text(str(exc), camera))
            return
        self.send_json(result)

    def handle_api_get(self, parsed):
        query = parse_qs(parsed.query)
        if parsed.path == "/api/health":
            self.send_json({"ok": True, "now": iso_now()})
            return
        if parsed.path == "/api/auth/state":
            username = self.auth_user()
            self.send_json(
                {
                    "authenticated": bool(username),
                    "setup_required": setup_required(),
                    "username": username,
                }
            )
            return
        if parsed.path == "/api/cameras":
            self.send_json({"cameras": list_cameras()})
            return
        if parsed.path == "/api/settings":
            self.send_json({"settings": get_app_settings()})
            return
        match = re.match(r"^/api/cameras/([a-f0-9]+)/time$", parsed.path)
        if match:
            self.handle_camera_time(match.group(1))
            return
        match = re.match(r"^/api/cameras/([a-f0-9]+)/live/diagnostics$", parsed.path)
        if match:
            camera = get_camera(match.group(1))
            if not camera:
                self.send_error_json(HTTPStatus.NOT_FOUND, "Camera not found.")
                return
            self.send_json(
                live_diagnostics(
                    camera,
                    include_audio=query_bool(query, "audio", default=True),
                )
            )
            return
        match = re.match(
            r"^/api/cameras/([a-f0-9]+)/compatibility-report$",
            parsed.path,
        )
        if match:
            self.handle_camera_compatibility(match.group(1), download=True)
            return
        if parsed.path == "/api/status":
            cameras = list_cameras()
            states = recorder.status()
            self.send_json(
                {
                    "cameras": cameras,
                    "recorders": states,
                    "disk": disk_status(),
                    "events": get_recent_events(),
                    "stream_token": get_stream_token(),
                    "relays": relay.status(cameras),
                    "go2rtc": go2rtc.status(),
                    "night_modes": night_modes.status(),
                    "settings": get_app_settings(),
                    "users": list_users(),
                    "username": self.auth_user(),
                    "now": iso_now(),
                }
            )
            return
        if parsed.path == "/api/coverage":
            camera_id = query.get("camera_id", [""])[0]
            camera = get_camera(camera_id)
            if not camera:
                self.send_error_json(HTTPStatus.NOT_FOUND, "Camera not found.")
                return
            self.send_json({"coverage": recording_coverage(camera)})
            return
        if parsed.path == "/api/segments":
            camera_id = query.get("camera_id", [""])[0]
            date_value = query.get("date", [""])[0] or None
            camera = get_camera(camera_id)
            if not camera:
                self.send_error_json(HTTPStatus.NOT_FOUND, "Camera not found.")
                return
            self.send_json({"segments": scan_segments(camera, date_value)})
            return
        self.send_error_json(HTTPStatus.NOT_FOUND, "Not found.")

    def handle_go2rtc_proxy(self, parsed, head_only=False):
        if not go2rtc.running():
            self.send_error_json(HTTPStatus.SERVICE_UNAVAILABLE, "go2rtc is unavailable.")
            return
        # Only expose the playback socket, never go2rtc's management/debug
        # APIs or arbitrary sources (which can invoke go2rtc source handlers).
        query = parse_qs(parsed.query, keep_blank_values=True)
        source = query.get("src", [""])
        match = re.fullmatch(r"plainnvr_([a-f0-9]+)", source[0]) if len(source) == 1 else None
        if parsed.path != "/go2rtc/api/ws" or set(query) != {"src"} or not match:
            self.send_error_json(HTTPStatus.NOT_FOUND, "Not found.")
            return
        camera = get_camera(match.group(1))
        if not camera or not camera.get("enabled"):
            self.send_error_json(HTTPStatus.NOT_FOUND, "Camera not found.")
            return
        if not self.ensure_same_origin():
            return
        if not go2rtc.can_restream(camera) or not go2rtc.configure_camera(camera):
            self.send_error_json(HTTPStatus.SERVICE_UNAVAILABLE, "Stream unavailable.")
            return
        upstream_path = "/api/ws?" + urlencode({"src": source[0]})
        if self.headers.get("Upgrade", "").lower() == "websocket" and not head_only:
            self.proxy_go2rtc_websocket(upstream_path)
            return
        self.send_error_json(HTTPStatus.BAD_REQUEST, "WebSocket upgrade required.")
        return

    def proxy_go2rtc_websocket(self, upstream_path):
        upstream = None
        response_sent = False
        try:
            upstream = socket.create_connection(
                (GO2RTC_API_HOST, GO2RTC_API_PORT),
                timeout=10,
            )
            headers = [
                f"GET {upstream_path} HTTP/1.1",
                f"Host: {GO2RTC_API_HOST}:{GO2RTC_API_PORT}",
                "Connection: Upgrade",
                "Upgrade: websocket",
            ]
            for key in (
                "Sec-WebSocket-Key",
                "Sec-WebSocket-Version",
                "Sec-WebSocket-Protocol",
                "Sec-WebSocket-Extensions",
                "Origin",
                "User-Agent",
            ):
                value = self.headers.get(key)
                if value:
                    headers.append(f"{key}: {value}")
            upstream.sendall(("\r\n".join(headers) + "\r\n\r\n").encode("latin-1"))

            response = bytearray()
            while b"\r\n\r\n" not in response and len(response) < 64 * 1024:
                chunk = upstream.recv(4096)
                if not chunk:
                    break
                response.extend(chunk)
            if not response:
                raise RuntimeError("go2rtc closed the WebSocket handshake.")
            self.connection.sendall(response)
            response_sent = True
            status_line = bytes(response).split(b"\r\n", 1)[0]
            if b" 101 " not in status_line:
                return

            self.close_connection = True
            upstream.settimeout(None)
            self.connection.settimeout(None)
            sockets = (self.connection, upstream)
            while True:
                readable, _, exceptional = select.select(sockets, [], sockets, 30)
                if exceptional:
                    break
                if not readable:
                    continue
                for source in readable:
                    data = source.recv(64 * 1024)
                    if not data:
                        return
                    target = upstream if source is self.connection else self.connection
                    target.sendall(data)
        except (OSError, RuntimeError) as exc:
            if not response_sent:
                self.send_error_json(
                    HTTPStatus.BAD_GATEWAY,
                    f"go2rtc WebSocket proxy failed: {exc}",
                )
        finally:
            if upstream:
                try:
                    upstream.close()
                except OSError:
                    pass

    def handle_home_assistant(self, parsed):
        match = re.match(r"^/ha/([a-f0-9]+)/(snapshot\.jpg|stream\.mjpeg)$", parsed.path)
        if not match:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        if not home_assistant_enabled():
            self.send_error(HTTPStatus.NOT_FOUND, "Home Assistant bridge is disabled.")
            return
        camera = get_camera(match.group(1))
        if not camera:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        query = parse_qs(parsed.query)
        if match.group(2) == "snapshot.jpg":
            self.handle_snapshot(camera, grayscale=query_bool(query, "grayscale"))
            return
        self.send_error(
            HTTPStatus.GONE,
            "MJPEG live streaming is disabled. Use the go2rtc-backed HLS URL under /live/.",
        )

    def handle_home_assistant_head(self, parsed):
        match = re.match(r"^/ha/([a-f0-9]+)/(snapshot\.jpg|stream\.mjpeg)$", parsed.path)
        if not match or not home_assistant_enabled():
            self.send_response(HTTPStatus.NOT_FOUND)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if not get_camera(match.group(1)):
            self.send_response(HTTPStatus.NOT_FOUND)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if match.group(2) == "snapshot.jpg":
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "image/jpeg")
        else:
            self.send_response(HTTPStatus.GONE)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def handle_live_hls(self, parsed, head_only=False):
        match = re.match(r"^/live/([a-f0-9]+)/(stream\.m3u8|hls/(?:playlist\.m3u8|init\.mp4|segment\.(?:ts|m4s)))$", parsed.path)
        if not match:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        camera = get_camera(match.group(1))
        if not camera:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        token = parse_qs(parsed.query).get("token", [""])[0]
        if match.group(2) == "stream.m3u8":
            if not go2rtc.can_restream(camera) or not go2rtc.configure_camera(camera):
                self.send_error(
                    HTTPStatus.SERVICE_UNAVAILABLE,
                    "go2rtc stream is unavailable.",
                )
                return
            upstream_path = f"/api/stream.m3u8?{urlencode({'src': go2rtc.stream_name(camera)})}"
        else:
            rest = match.group(2)[len("hls/") :]
            query = parse_qs(parsed.query, keep_blank_values=True)
            query.pop("token", None)
            upstream_path = f"/api/hls/{rest}"
            encoded_query = urlencode(query, doseq=True)
            if encoded_query:
                upstream_path = f"{upstream_path}?{encoded_query}"
        self.proxy_go2rtc_live_hls(upstream_path, camera["id"], token, head_only=head_only)

    def handle_live_hls_head(self, parsed):
        self.handle_live_hls(parsed, head_only=True)

    def proxy_go2rtc_live_hls(self, upstream_path, camera_id, token="", head_only=False):
        headers = {"Accept": self.headers.get("Accept", "*/*")}
        if self.headers.get("Range"):
            headers["Range"] = self.headers["Range"]
        request = urllib_request.Request(
            f"http://{GO2RTC_API_HOST}:{GO2RTC_API_PORT}{upstream_path}",
            headers=headers,
            method="HEAD" if head_only else "GET",
        )
        try:
            response = urllib_request.urlopen(request, timeout=10)
        except urllib_error.HTTPError as exc:
            response = exc
        except (OSError, urllib_error.URLError) as exc:
            self.send_error(HTTPStatus.BAD_GATEWAY, f"go2rtc HLS proxy failed: {exc}")
            return
        with response:
            content_type = response.headers.get("Content-Type", "")
            is_playlist = "mpegurl" in content_type or upstream_path.split("?", 1)[0].endswith(".m3u8")
            if is_playlist and response.status == HTTPStatus.OK and not head_only:
                text = response.read().decode("utf-8", "replace")
                self.send_go2rtc_live_playlist(text, camera_id, token)
                return
            self.send_response(response.status)
            for key in ("Content-Type", "Content-Length", "Content-Range", "Accept-Ranges", "Cache-Control", "Retry-After"):
                value = response.headers.get(key)
                if value:
                    self.send_header(key, value)
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            if not head_only:
                shutil.copyfileobj(response, self.wfile, length=64 * 1024)

    def send_go2rtc_live_playlist(self, text, camera_id, token=""):
        def rewrite_uri(uri):
            if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", uri):
                return uri
            if uri.startswith("/api/hls/"):
                uri = uri[len("/api/hls/") :]
            elif uri.startswith("hls/"):
                uri = uri[len("hls/") :]
            uri = f"/live/{camera_id}/hls/{uri}"
            if token:
                separator = "&" if "?" in uri else "?"
                uri = f"{uri}{separator}token={quote(token)}"
            return uri

        lines = []
        for line in text.splitlines():
            if line.startswith("#") and 'URI="' in line:
                line = re.sub(
                    r'URI="([^"]+)"',
                    lambda match: f'URI="{rewrite_uri(match.group(1))}"',
                    line,
                )
                lines.append(line)
            elif not line or line.startswith("#"):
                lines.append(line)
            else:
                lines.append(rewrite_uri(line.strip()))
        text = "\n".join(lines) + "\n"
        payload = text.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/vnd.apple.mpegurl")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    def handle_snapshot(self, camera, grayscale=False):
        try:
            result = subprocess.run(build_snapshot_command(camera, grayscale=grayscale), capture_output=True, timeout=20)
        except RuntimeError as exc:
            self.send_error(HTTPStatus.BAD_GATEWAY, redact_camera_text(str(exc), camera))
            return
        except subprocess.TimeoutExpired:
            self.send_error(HTTPStatus.GATEWAY_TIMEOUT, "Snapshot timed out.")
            return
        if result.returncode != 0 or not result.stdout:
            message = result.stderr.decode("utf-8", "replace").strip().splitlines()
            self.send_error(HTTPStatus.BAD_GATEWAY, message[-1] if message else "Snapshot failed.")
            return
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "image/jpeg")
        self.send_header("Content-Length", str(len(result.stdout)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(result.stdout)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def handle_media(self, path, head_only=False):
        parts = path.split("/")
        if len(parts) != 4:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        camera_id = parts[2]
        filename = unquote(parts[3])
        if not SEGMENT_RE.match(filename):
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        camera = get_camera(camera_id)
        if not camera:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        target = (camera_dir(camera) / filename).resolve()
        root = camera_dir(camera).resolve()
        if root not in target.parents or not target.exists():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        size = target.stat().st_size
        start = 0
        end = size - 1
        status = HTTPStatus.OK
        range_header = self.headers.get("Range")
        if range_header:
            match = re.fullmatch(r"bytes=(\d*)-(\d*)", range_header)
            if not match or not any(match.groups()):
                # Unsupported range syntax (including multipart): serve whole file.
                match = None
            if match:
                first, last = match.groups()
                if first:
                    start = int(first)
                    end = min(int(last), size - 1) if last else size - 1
                else:
                    start = max(0, size - int(last))
                if start >= size or start > end:
                    self.send_response(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
                    self.send_header("Content-Range", f"bytes */{size}")
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                status = HTTPStatus.PARTIAL_CONTENT
        self.send_response(status)
        self.send_header("Content-Type", "video/mp4")
        self.send_header("Content-Length", str(end - start + 1))
        self.send_header("Accept-Ranges", "bytes")
        if status == HTTPStatus.PARTIAL_CONTENT:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        if head_only:
            return
        with target.open("rb") as src:
            src.seek(start)
            remaining = end - start + 1
            while remaining > 0:
                chunk = src.read(min(1024 * 1024, remaining))
                if not chunk:
                    break
                self.wfile.write(chunk)
                remaining -= len(chunk)

    def serve_static(self, path, head_only=False):
        if path in ("", "/"):
            path = "/index.html"
        target = (STATIC_DIR / path.lstrip("/")).resolve()
        root = STATIC_DIR.resolve()
        if root not in target.parents and target != root:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        if not target.exists() or not target.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        content_type = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(target.stat().st_size))
        self.end_headers()
        if head_only:
            return
        with target.open("rb") as src:
            shutil.copyfileobj(src, self.wfile)


class NvrHTTPServer(ThreadingHTTPServer):
    # Idle/slow peers and long-lived playback sockets cannot spawn unlimited
    # handler threads. Each camera/viewer may use more than one connection.
    def __init__(self, address, handler, max_connections=128):
        self.connection_slots = threading.BoundedSemaphore(max_connections)
        super().__init__(address, handler)

    def process_request(self, request, client_address):
        if not self.connection_slots.acquire(blocking=False):
            try:
                request.settimeout(1)
                request.sendall(b"HTTP/1.1 503 Service Unavailable\r\nContent-Length: 0\r\nConnection: close\r\nRetry-After: 1\r\n\r\n")
            except OSError:
                pass
            finally:
                self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except Exception:
            self.connection_slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.connection_slots.release()


def main():
    os.umask(0o077)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)
    init_db()
    go2rtc.start(list_cameras())
    recorder.start()
    server = NvrHTTPServer((APP_HOST, APP_PORT), NvrHandler)

    def handle_signal(signum, _frame):
        print(f"Received signal {signum}, shutting down.")
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)
    print(f"PlainNVR listening on http://{APP_HOST}:{APP_PORT}")
    try:
        server.serve_forever()
    finally:
        recorder.shutdown()
        go2rtc.shutdown()
        server.server_close()


if __name__ == "__main__":
    main()
