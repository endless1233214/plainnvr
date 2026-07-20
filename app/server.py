#!/usr/bin/env python3
import base64
from html import escape as html_escape
import json
import hashlib
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


def env_float(name, default):
    try:
        return float(os.environ.get(name, str(default)))
    except ValueError:
        return default


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
AUTH_HASH_ITERATIONS = int(os.environ.get("NVR_AUTH_HASH_ITERATIONS", "260000"))
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

DAY_KEYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
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


def utcnow():
    return datetime.now(timezone.utc)


def iso_now():
    return utcnow().isoformat()


def slugify(value):
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    value = re.sub(r"-+", "-", value).strip("-")
    return value or "camera"


def parse_json_body(handler):
    length = int(handler.headers.get("Content-Length", "0") or "0")
    if length <= 0:
        return {}
    raw = handler.rfile.read(length)
    try:
        return json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON: {exc}") from exc


def normalize_bool(value):
    if isinstance(value, bool):
        return 1 if value else 0
    if isinstance(value, int):
        return 1 if value else 0
    if isinstance(value, str):
        return 1 if value.lower() in ("1", "true", "yes", "on") else 0
    return 0


def query_bool(query, key, default=False):
    values = query.get(key)
    if not values:
        return default
    return normalize_bool(values[0])


def password_hash(password, salt=None, iterations=AUTH_HASH_ITERATIONS):
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        bytes.fromhex(salt),
        iterations,
    )
    return f"pbkdf2_sha256${iterations}${salt}${digest.hex()}"


def verify_password(password, stored_hash):
    try:
        algorithm, iterations, salt, expected = stored_hash.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        candidate = password_hash(password, salt=salt, iterations=int(iterations)).rsplit("$", 1)[-1]
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(candidate, expected)


def validate_username(username):
    username = str(username or "").strip()
    if not re.match(r"^[A-Za-z0-9_.-]{3,40}$", username):
        raise ValueError("Username must be 3-40 letters, numbers, dots, dashes, or underscores.")
    return username


def validate_password(password):
    password = str(password or "")
    if len(password) < 12:
        raise ValueError("Password must be at least 12 characters.")
    return password


def default_schedule():
    return {"mode": "always", "days": {day: [] for day in DAY_KEYS}}


def normalize_schedule(value):
    if not isinstance(value, dict):
        return default_schedule()
    mode = value.get("mode", "always")
    days = value.get("days") if isinstance(value.get("days"), dict) else {}
    normalized = {"mode": "weekly" if mode == "weekly" else "always", "days": {}}
    for day in DAY_KEYS:
        windows = []
        for item in days.get(day, []):
            if not isinstance(item, dict):
                continue
            start = str(item.get("start", "")).strip()
            end = str(item.get("end", "")).strip()
            if re.match(r"^\d{2}:\d{2}$", start) and re.match(r"^\d{2}:\d{2}$", end):
                windows.append({"start": start, "end": end})
        normalized["days"][day] = windows
    return normalized


def time_to_minutes(value):
    hour, minute = value.split(":", 1)
    return int(hour) * 60 + int(minute)


def schedule_active(schedule, now=None):
    schedule = normalize_schedule(schedule)
    if schedule["mode"] == "always":
        return True
    now = now or datetime.now()
    day_key = DAY_KEYS[now.weekday()]
    current = now.hour * 60 + now.minute
    for window in schedule["days"].get(day_key, []):
        start = time_to_minutes(window["start"])
        end = time_to_minutes(window["end"])
        if start == end:
            return True
        if start < end and start <= current < end:
            return True
        if start > end and (current >= start or current < end):
            return True
    return False


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
        (username, password_hash(password), now, now),
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


def get_app_settings():
    settings = {"home_assistant_enabled": False}
    with db_conn() as conn:
        row = conn.execute(
            "SELECT value FROM app_settings WHERE key = 'home_assistant_enabled'"
        ).fetchone()
    if row:
        settings["home_assistant_enabled"] = setting_bool(row["value"])
    return settings


def home_assistant_enabled():
    return bool(get_app_settings().get("home_assistant_enabled"))


def update_app_settings(payload):
    settings = get_app_settings()
    if "home_assistant_enabled" in payload:
        settings["home_assistant_enabled"] = setting_bool(payload.get("home_assistant_enabled"))
    now = iso_now()
    with db_conn() as conn:
        conn.execute(
            """
            INSERT INTO app_settings (key, value, updated_at)
            VALUES ('home_assistant_enabled', ?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
            """,
            (json.dumps(bool(settings["home_assistant_enabled"])), now),
        )
    return settings


def cleanup_expired_sessions(conn):
    conn.execute("DELETE FROM sessions WHERE expires_at <= ?", (iso_now(),))


def setup_required():
    with db_conn() as conn:
        row = conn.execute("SELECT username FROM users LIMIT 1").fetchone()
    return row is None


def create_user(username, password):
    username = validate_username(username)
    password = validate_password(password)
    with db_conn() as conn:
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
        try:
            expires_at = datetime.fromisoformat(row["expires_at"])
        except ValueError:
            conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
            return None
        if expires_at <= utcnow():
            conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
            return None
        conn.execute("UPDATE sessions SET last_seen_at = ? WHERE id = ?", (iso_now(), session_id))
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
                view_rotation, ptz_url, ptz_profile_token, ptz_zoom_mode, ptz_speed, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
        for key in ("rtsp_url", "ptz_url", "ptz_profile_token", "ptz_type")
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
                live_view_mode = ?, view_rotation = ?, rtsp_transport = ?, ptz_enabled = ?, ptz_type = ?, ptz_url = ?,
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


class Go2RTCManager:
    def __init__(self):
        self.lock = threading.RLock()
        self.process = None
        self.log_handle = None
        self.config_path = DATA_DIR / "go2rtc.json"
        self.log_path = DATA_DIR / "go2rtc.log"
        self.stream_keys = {}
        self.generations = {}
        self.last_error = None

    def stream_name(self, camera):
        return f"plainnvr_{camera['id']}"

    def source_key(self, camera):
        return str(camera.get("rtsp_url") or "").strip()

    def binary_path(self):
        return shutil.which(GO2RTC_BIN)

    def running(self):
        with self.lock:
            return bool(self.process and self.process.poll() is None)

    def can_restream(self, camera):
        stream_url = self.source_key(camera)
        audio_url = str(camera.get("audio_url") or "").strip()
        separate_audio = bool(
            camera.get("record_audio", True)
            and audio_url
            and audio_url != stream_url
        )
        return (
            self.running()
            and stream_url.startswith(STREAM_URL_PREFIXES)
            and not separate_audio
        )

    def _config(self):
        candidates = [
            item.strip()
            for item in os.environ.get("NVR_GO2RTC_WEBRTC_CANDIDATES", "").split(",")
            if item.strip()
        ]
        config = {
            "api": {
                "listen": f"{GO2RTC_API_HOST}:{GO2RTC_API_PORT}",
                "origin": "*",
            },
            "rtsp": {"listen": f":{GO2RTC_RTSP_PORT}"},
            "webrtc": {"listen": f":{GO2RTC_WEBRTC_PORT}"},
            "ffmpeg": {"bin": FFMPEG_BIN},
            "streams": {},
        }
        if candidates:
            config["webrtc"]["candidates"] = candidates
        return config

    def start(self, cameras):
        binary = self.binary_path()
        if not binary:
            self.last_error = f"{GO2RTC_BIN} is not installed; live restreaming is unavailable."
            print(self.last_error)
            return False
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self.config_path.write_text(
            json.dumps(self._config(), indent=2) + "\n",
            encoding="utf-8",
        )
        with self.lock:
            if self.process and self.process.poll() is None:
                return True
            self.log_handle = self.log_path.open("a", encoding="utf-8", errors="replace")
            self.process = subprocess.Popen(
                [binary, "-config", str(self.config_path)],
                stdout=self.log_handle,
                stderr=subprocess.STDOUT,
            )
        deadline = time.time() + GO2RTC_START_TIMEOUT_SECONDS
        while time.time() < deadline:
            if not self.running():
                break
            try:
                self._request("/api/streams", timeout=1)
                self.last_error = None
                self.reconcile(cameras)
                print("go2rtc is ready; low-latency restreaming enabled.")
                return True
            except (OSError, urllib_error.URLError, urllib_error.HTTPError):
                time.sleep(0.2)
        self.last_error = f"go2rtc did not become ready. {self.log_tail(8)}".strip()
        print(self.last_error)
        self.shutdown()
        return False

    def _request(self, path, method="GET", timeout=3):
        request = urllib_request.Request(
            f"http://{GO2RTC_API_HOST}:{GO2RTC_API_PORT}{path}",
            method=method,
        )
        with urllib_request.urlopen(request, timeout=timeout) as response:
            return response.read(1024 * 1024)

    def configure_camera(self, camera):
        if not self.running():
            return False
        source = self.source_key(camera)
        if not source.startswith(STREAM_URL_PREFIXES):
            return False
        audio_url = str(camera.get("audio_url") or "").strip()
        if camera.get("record_audio", True) and audio_url and audio_url != source:
            return False
        name = self.stream_name(camera)
        source_key = self.source_key(camera)
        with self.lock:
            if self.stream_keys.get(camera["id"]) == source_key:
                return True
        query = urlencode({"name": name, "src": source})
        try:
            self._request(f"/api/streams?{query}", method="PATCH")
        except (OSError, urllib_error.URLError, urllib_error.HTTPError) as exc:
            self.last_error = f"Could not configure {camera.get('name')}: {exc}"
            return False
        with self.lock:
            self.stream_keys[camera["id"]] = source_key
            self.generations[camera["id"]] = self.generations.get(camera["id"], 0) + 1
        return True

    def delete_camera(self, camera_id):
        with self.lock:
            self.stream_keys.pop(camera_id, None)
            self.generations.pop(camera_id, None)
        if not self.running():
            return
        name = f"plainnvr_{camera_id}"
        try:
            self._request(
                f"/api/streams?{urlencode({'src': name})}",
                method="DELETE",
            )
        except (OSError, urllib_error.URLError, urllib_error.HTTPError):
            pass

    def restart_camera(self, camera):
        if not self.can_restream(camera):
            return False
        camera_id = camera["id"]
        name = self.stream_name(camera)
        with self.lock:
            previous_generation = self.generations.get(camera_id, 0)
            self.stream_keys.pop(camera_id, None)
            self.generations[camera_id] = previous_generation
        try:
            self._request(
                f"/api/streams?{urlencode({'src': name})}",
                method="DELETE",
            )
        except (OSError, urllib_error.URLError, urllib_error.HTTPError):
            pass
        return self.configure_camera(camera)

    def reconcile(self, cameras):
        active_ids = set()
        for camera in cameras:
            if not camera.get("enabled") or not self.can_restream(camera):
                continue
            active_ids.add(camera["id"])
            self.configure_camera(camera)
        with self.lock:
            stale_ids = set(self.stream_keys) - active_ids
        for camera_id in stale_ids:
            self.delete_camera(camera_id)

    def source_camera(self, camera):
        if not self.can_restream(camera) or not self.configure_camera(camera):
            raise RuntimeError("go2rtc restream is unavailable for this camera.")
        cloned = dict(camera)
        cloned["rtsp_url"] = (
            f"rtsp://{GO2RTC_RTSP_HOST}:{GO2RTC_RTSP_PORT}/"
            f"{self.stream_name(camera)}"
        )
        cloned["audio_url"] = ""
        cloned["rtsp_transport"] = "tcp"
        cloned["_relay_generation"] = self.generations.get(camera["id"], 0)
        cloned["_relay_backend"] = "go2rtc"
        return cloned

    def camera_status(self, camera):
        configured = self.stream_keys.get(camera["id"]) == self.source_key(camera)
        return {
            "running": self.running(),
            "healthy": self.running() and configured,
            "pid": self.process.pid if self.running() else None,
            "started_at": None,
            "last_error": self.last_error,
            "source": (
                f"rtsp://{GO2RTC_RTSP_HOST}:{GO2RTC_RTSP_PORT}/"
                f"{self.stream_name(camera)}"
            ),
            "generation": self.generations.get(camera["id"], 0),
            "restart_count": 0,
            "backend": "go2rtc",
            "stream": self.stream_name(camera),
        }

    def stream_info(self, camera):
        if not self.can_restream(camera) or not self.configure_camera(camera):
            return None
        try:
            raw = self._request(
                f"/api/streams?{urlencode({'src': self.stream_name(camera)})}"
            )
            return json.loads(raw.decode("utf-8"))
        except (OSError, ValueError, urllib_error.URLError, urllib_error.HTTPError):
            return None

    def status(self):
        return {
            "available": bool(self.binary_path()),
            "running": self.running(),
            "pid": self.process.pid if self.running() else None,
            "error": self.last_error,
            "api_proxy": "/go2rtc/api/ws",
            "rtsp_port": GO2RTC_RTSP_PORT,
            "webrtc_port": GO2RTC_WEBRTC_PORT,
        }

    def log_tail(self, line_count=20):
        try:
            lines = self.log_path.read_text(
                encoding="utf-8", errors="replace"
            ).splitlines()
        except OSError:
            return ""
        return "\n".join(lines[-line_count:]).strip()

    def shutdown(self):
        with self.lock:
            process = self.process
            self.process = None
        if process and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
        with self.lock:
            if self.log_handle:
                self.log_handle.close()
                self.log_handle = None


go2rtc = Go2RTCManager()


class Go2RTCSourceManager:
    def source_camera(self, camera):
        if go2rtc.can_restream(camera):
            try:
                return go2rtc.source_camera(camera)
            except RuntimeError as exc:
                go2rtc.last_error = str(exc)
        raise RuntimeError("go2rtc restream is unavailable for this camera.")

    def status(self, cameras=None):
        states = {}
        for camera in cameras or []:
            if go2rtc.can_restream(camera):
                states[camera["id"]] = go2rtc.camera_status(camera)
            else:
                states[camera["id"]] = {
                    "running": go2rtc.running(),
                    "healthy": False,
                    "pid": go2rtc.process.pid if go2rtc.running() else None,
                    "started_at": None,
                    "last_error": go2rtc.last_error or "go2rtc cannot restream this camera.",
                    "source": None,
                    "generation": go2rtc.generations.get(camera["id"], 0),
                    "restart_count": 0,
                    "backend": "go2rtc",
                    "stream": go2rtc.stream_name(camera),
                }
        return states

    def stop(self, camera_id):
        go2rtc.delete_camera(camera_id)

    def reconcile(self, cameras):
        go2rtc.reconcile(cameras)

    def shutdown(self):
        return None


relay = Go2RTCSourceManager()


def build_ffmpeg_command(camera, source_camera=None):
    camera = source_camera or relay.source_camera(camera)
    target_dir = ensure_recording_directory(camera)
    output_pattern = str(target_dir / "%Y%m%dT%H%M%S.mp4")
    audio_url = str(camera.get("audio_url") or "").strip()
    record_audio = camera.get("record_audio", True)
    command = [
        FFMPEG_BIN,
        "-hide_banner",
        "-nostdin",
        "-loglevel",
        "error",
    ]
    command.extend(ffmpeg_input_args(camera, low_latency=(not record_audio or bool(audio_url))))
    if record_audio and audio_url:
        command.extend(ffmpeg_input_args(camera, "audio_url", low_latency=False))
    command.extend(
        [
            "-map",
            "0:v:0",
        ]
    )
    if record_audio:
        if audio_url:
            command.extend(["-map", "1:a:0?"])
        else:
            command.extend(["-map", "0:a?"])
    if record_audio:
        command.extend(["-c:v", "copy", "-c:a", "aac", "-b:a", "128k", "-ac", "2"])
    else:
        command.extend(["-c", "copy"])
    command.extend(
        [
            "-f",
            "segment",
            "-segment_time",
            str(camera.get("segment_seconds", DEFAULT_SEGMENT_SECONDS)),
            "-reset_timestamps",
            "1",
            "-strftime",
            "1",
            "-segment_format",
            "mp4",
            "-segment_format_options",
            "movflags=+faststart",
            output_pattern,
        ]
    )
    return command


def ffmpeg_input_args(camera_or_payload, url_key="rtsp_url", low_latency=True):
    url = str(camera_or_payload[url_key]).strip()
    transport = camera_or_payload.get("rtsp_transport", "tcp")
    args = []
    if url.startswith(("rtsp://", "rtsps://")):
        probesize = RTSP_PROBESIZE if low_latency else RTSP_LIVE_PROBESIZE
        analyze_duration = RTSP_ANALYZE_DURATION if low_latency else RTSP_LIVE_ANALYZE_DURATION
        args.extend(
            [
                "-rtsp_transport",
                transport if transport in ("tcp", "udp") else "tcp",
                "-timeout",
                str(round(RTSP_READ_TIMEOUT_SECONDS * 1_000_000)),
                "-probesize",
                probesize,
                "-analyzeduration",
                analyze_duration,
            ]
        )
        if low_latency:
            args.extend(["-fflags", "nobuffer", "-flags", "low_delay"])
        else:
            args.extend(["-fflags", "+genpts+igndts", "-use_wallclock_as_timestamps", "1"])
        args.extend(["-thread_queue_size", RTSP_THREAD_QUEUE_SIZE])
    args.extend(["-i", url])
    return args


def grayscale_enabled(camera):
    mode = normalize_grayscale_mode(camera.get("grayscale_mode"))
    if mode == "always":
        return True
    if mode == "auto":
        return night_modes.is_night(camera["id"])
    return False


def add_video_filters(command, filters):
    if filters:
        command.extend(["-vf", ",".join(filters)])


def build_snapshot_command(camera, grayscale=False):
    camera = relay.source_camera(camera)
    command = [
        FFMPEG_BIN,
        "-hide_banner",
        "-nostdin",
        "-loglevel",
        "error",
    ]
    command.extend(ffmpeg_input_args(camera))
    video_filters = []
    if grayscale or grayscale_enabled(camera):
        video_filters.append("hue=s=0")
    add_video_filters(command, video_filters)
    command.extend(["-frames:v", "1", "-q:v", "4", "-f", "image2pipe", "-vcodec", "mjpeg", "pipe:1"])
    return command


def bounded_int(value, default, minimum, maximum):
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(parsed, maximum))


def optional_bounded_int(value, minimum, maximum):
    if value in (None, ""):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return max(minimum, min(parsed, maximum))


def netloc_without_credentials(parsed):
    host = parsed.hostname or ""
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    return f"{host}:{parsed.port}" if parsed.port else host


def url_credentials(parsed):
    if parsed.username is None:
        return None
    return unquote(parsed.username), unquote(parsed.password or "")


def clean_control_url(value):
    parsed = urlparse(value)
    netloc = netloc_without_credentials(parsed)
    path = parsed.path or "/"
    query = f"?{parsed.query}" if parsed.query else ""
    return f"{parsed.scheme}://{netloc}{path}{query}"


def redact_url_credentials(value):
    parsed = urlparse(str(value or ""))
    if not parsed.username:
        return value
    netloc = netloc_without_credentials(parsed)
    path = parsed.path or ""
    query = f"?{parsed.query}" if parsed.query else ""
    return f"{parsed.scheme}://<credentials>@{netloc}{path}{query}"


def dvrip_url_for_parse(value):
    value = str(value or "").strip()
    if "://" in value:
        return value
    return f"dvrip://{value}"


def dvrip_target(camera):
    explicit_url = str(camera.get("ptz_url") or "").strip()
    source = explicit_url or str(camera.get("rtsp_url") or "").strip()
    if not source:
        raise ValueError("Could not derive a DVRIP endpoint from this camera URL.")

    parsed = urlparse(dvrip_url_for_parse(source) if explicit_url else source)
    host = parsed.hostname
    if not host:
        raise ValueError("Could not derive a DVRIP endpoint from this camera URL.")
    credentials = url_credentials(parsed) if explicit_url else None
    configured_hash = str(camera.get("ptz_profile_token") or "").strip()
    if not configured_hash or configured_hash == DEFAULT_PTZ_PROFILE_TOKEN:
        configured_hash = DVRIP_DEFAULT_PASSHASH
    user, passhash = credentials or (DVRIP_DEFAULT_USER, configured_hash)
    port = (parsed.port if explicit_url else None) or DVRIP_DEFAULT_PORT
    endpoint = f"dvrip://{host}:{port}"
    if ":" in host and not host.startswith("["):
        endpoint = f"dvrip://[{host}]:{port}"
    return {
        "host": host,
        "port": port,
        "user": user or DVRIP_DEFAULT_USER,
        "passhash": passhash or DVRIP_DEFAULT_PASSHASH,
        "endpoint": endpoint,
    }


def dvrip_step_from_speed(speed):
    return max(1, min(64, round(speed * 4)))


def dvrip_recv_exact(sock, length):
    chunks = []
    remaining = length
    while remaining:
        chunk = sock.recv(remaining)
        if not chunk:
            raise ConnectionError("DVRIP connection closed early.")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def dvrip_send_packet(sock, session, number, packet_type, payload):
    data = payload.encode("utf-8")
    header = DVRIP_HEADER.pack(0xFF, 0x01, 0, session, number, 0, 0, packet_type, len(data))
    sock.sendall(header + data)


def dvrip_recv_packet(sock):
    header = dvrip_recv_exact(sock, DVRIP_HEADER.size)
    magic, version, _pad, session, number, fragments, fragment, packet_type, length = DVRIP_HEADER.unpack(header)
    if magic != 0xFF or version != 0x01:
        raise RuntimeError("DVRIP returned an invalid header.")
    payload = dvrip_recv_exact(sock, length) if length else b""
    return {
        "session": session,
        "number": number,
        "fragments": fragments,
        "fragment": fragment,
        "type": packet_type,
        "payload": payload.decode("utf-8", errors="replace").rstrip("\0"),
    }


def dvrip_parse_session(payload):
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        data = {}
    session_id = data.get("SessionID")
    if isinstance(session_id, str):
        return int(session_id, 16)
    if isinstance(session_id, int):
        return session_id
    match = re.search(r'"SessionID"\s*:\s*"?(0x[0-9a-fA-F]+|\d+)"?', payload)
    if match:
        return int(match.group(1), 0)
    return 0


def dvrip_parse_json(payload):
    try:
        return json.loads(payload)
    except json.JSONDecodeError as exc:
        raise RuntimeError("DVRIP returned invalid JSON.") from exc


def dvrip_login(sock, target):
    login = json.dumps(
        {
            "EncryptType": "MD5",
            "LoginType": "DVRIP-Web",
            "PassWord": target["passhash"],
            "UserName": target["user"],
        },
        separators=(",", ":"),
    )
    dvrip_send_packet(sock, 0, 2, 1000, login)
    reply = dvrip_recv_packet(sock)
    details = dvrip_parse_json(reply["payload"])
    session = dvrip_parse_session(reply["payload"])
    if not session or details.get("Ret") != 100:
        raise RuntimeError("DVRIP login failed.")
    return session


def dvrip_time_target(camera):
    target_camera = dict(camera)
    if normalize_ptz_type(camera.get("ptz_type")) != "victure_dvrip":
        target_camera["ptz_url"] = ""
    return dvrip_target(target_camera)


def dvrip_query_time(sock, session, number=4):
    payload = json.dumps(
        {
            "Name": "OPTimeQuery",
            "SessionID": f"0x{session:08X}",
        },
        separators=(",", ":"),
    )
    dvrip_send_packet(sock, session, number, 1452, payload)
    details = dvrip_parse_json(dvrip_recv_packet(sock)["payload"])
    if details.get("Ret") != 100 or not details.get("OPTimeQuery"):
        raise RuntimeError("Camera did not return its clock.")
    return datetime.strptime(details["OPTimeQuery"], "%Y-%m-%d %H:%M:%S")


def normalize_requested_camera_time(value):
    text = str(value or "").strip()
    if not text:
        return datetime.now().replace(microsecond=0)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("Invalid camera date and time.") from exc
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone().replace(tzinfo=None)
    parsed = parsed.replace(microsecond=0)
    if parsed.year < 2001 or parsed.year > 2100:
        raise ValueError("Camera date must be between 2001 and 2100.")
    return parsed


def camera_time(camera, requested=None):
    if not camera.get("time_sync_supported"):
        raise ValueError("Clock sync is not available for this camera driver.")
    target = dvrip_time_target(camera)
    try:
        with socket.create_connection((target["host"], target["port"]), timeout=4) as sock:
            sock.settimeout(4)
            session = dvrip_login(sock, target)
            if requested is not None:
                value = normalize_requested_camera_time(requested)
                payload = json.dumps(
                    {
                        "Name": "OPTimeSetting",
                        "OPTimeSetting": value.strftime("%Y-%m-%d %H:%M:%S"),
                        "SessionID": f"0x{session:08X}",
                    },
                    separators=(",", ":"),
                )
                dvrip_send_packet(sock, session, 4, 1450, payload)
                details = dvrip_parse_json(dvrip_recv_packet(sock)["payload"])
                if details.get("Ret") != 100:
                    raise RuntimeError("Camera rejected the clock update.")
                current = dvrip_query_time(sock, session, number=6)
            else:
                current = dvrip_query_time(sock, session)
    except (TimeoutError, OSError) as exc:
        raise RuntimeError(f"Camera clock request failed: {exc}") from exc
    return {
        "ok": True,
        "driver": "dvrip",
        "time": current.strftime("%Y-%m-%d %H:%M:%S"),
        "endpoint": target["endpoint"],
    }


def run_victure_dvrip_ptz_command(camera, action, speed, duration_ms):
    if action == "home":
        return {
            "ok": True,
            "action": action,
            "driver": "victure_dvrip",
            "warning": "Home is not available on the Victure DVRIP driver.",
        }

    command = DVRIP_PTZ_COMMANDS.get(action)
    if not command:
        raise ValueError("Unsupported PTZ action.")

    target = dvrip_target(camera)
    step = dvrip_step_from_speed(speed)
    try:
        with socket.create_connection((target["host"], target["port"]), timeout=4) as sock:
            sock.settimeout(4)
            session = dvrip_login(sock, target)
            def ptz_payload(ptz_command, preset):
                return json.dumps({
                    "Name": "OPPTZControl",
                    "OPPTZControl": {
                        "Command": ptz_command,
                        "Parameter": {
                            "AUX": {"Number": 0, "Status": "On"},
                            "Channel": 0,
                            "MenuOpts": "Enter",
                            "POINT": {"bottom": 0, "left": 0, "right": 0, "top": 0},
                            "Pattern": "SetBegin",
                            "Preset": preset,
                            "Step": step,
                            "Tour": 0,
                        },
                    },
                    "SessionID": f"0x{session:08X}",
                }, separators=(",", ":"))

            if action == "stop":
                for offset, stop_command in enumerate(("DirectionUp", "DirectionDown", "DirectionLeft", "DirectionRight")):
                    dvrip_send_packet(sock, session, 4 + offset, 1400, ptz_payload(stop_command, -1))
            else:
                dvrip_send_packet(sock, session, 4, 1400, ptz_payload(command, 65535))
                time.sleep(duration_ms / 1000)
                dvrip_send_packet(sock, session, 5, 1400, ptz_payload(command, -1))
    except (TimeoutError, OSError) as exc:
        raise RuntimeError(f"DVRIP command failed: {exc}") from exc

    return {
        "ok": True,
        "action": action,
        "driver": "victure_dvrip",
        "endpoint": target["endpoint"],
        "step": step,
        "duration_ms": duration_ms if action in PTZ_MOVE_VECTORS else 0,
    }


def http_admin_url_for_parse(value):
    value = str(value or "").strip()
    if "://" in value:
        return value
    return f"http://{value}"


def victure_direct_target(camera):
    explicit_url = str(camera.get("ptz_url") or "").strip()
    source = explicit_url or str(camera.get("rtsp_url") or "").strip()
    if not source:
        raise ValueError("Could not derive a Victure admin endpoint from this camera URL.")

    parsed = urlparse(http_admin_url_for_parse(source) if explicit_url else source)
    host = parsed.hostname
    if not host:
        raise ValueError("Could not derive a Victure admin endpoint from this camera URL.")
    scheme = parsed.scheme if explicit_url and parsed.scheme in ("http", "https") else "http"
    port = (parsed.port if explicit_url else None) or VICTURE_DIRECT_DEFAULT_PORT
    netloc = f"[{host}]:{port}" if ":" in host and not host.startswith("[") else f"{host}:{port}"
    return f"{scheme}://{netloc}"


def victure_direct_step_from_speed(speed):
    return max(1, min(256, round(speed * 64)))


def run_victure_direct_ptz_command(camera, action, speed):
    if action not in VICTURE_DIRECT_ACTIONS:
        return {
            "ok": True,
            "action": action,
            "driver": "victure_direct",
            "warning": "This Victure direct-step driver only supports directional moves.",
        }

    base_url = victure_direct_target(camera)
    endpoint = f"{base_url}/ptz"
    step = victure_direct_step_from_speed(speed)
    body = urlencode({"action": action, "step": step}).encode("utf-8")
    request = urllib_request.Request(
        endpoint,
        data=body,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        with urllib_request.urlopen(request, timeout=4) as response:
            response.read(2048)
            status = getattr(response, "status", 200)
    except urllib_error.HTTPError as exc:
        if exc.code in (301, 302, 303, 307, 308):
            status = exc.code
            exc.read(2048)
        else:
            raise RuntimeError(f"Victure direct-step command failed: {exc}") from exc
    except (TimeoutError, OSError, urllib_error.URLError) as exc:
        raise RuntimeError(f"Victure direct-step command failed: {exc}") from exc

    return {
        "ok": True,
        "action": action,
        "driver": "victure_direct",
        "endpoint": endpoint,
        "step": step,
        "status": status,
    }


def ptz_url_candidates(camera):
    explicit_url = str(camera.get("ptz_url") or "").strip()
    rtsp_url = str(camera.get("rtsp_url") or "").strip()
    source = explicit_url or rtsp_url
    parsed = urlparse(source)
    credentials = url_credentials(urlparse(explicit_url)) or url_credentials(urlparse(rtsp_url))
    candidates = []

    def add(value):
        if value not in candidates:
            candidates.append(value)

    if explicit_url:
        if parsed.path and parsed.path != "/":
            add(clean_control_url(explicit_url))
        else:
            base = f"{parsed.scheme}://{netloc_without_credentials(parsed)}"
            for path in ("/onvif/ptz_service", "/onvif/PTZ", "/onvif/ptz", "/onvif/device_service"):
                add(f"{base}{path}")
        return candidates, credentials

    host = parsed.hostname
    if not host:
        return [], credentials
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    for port in (8080, 80):
        port_suffix = "" if port == 80 else f":{port}"
        for path in ("/onvif/ptz_service", "/onvif/PTZ", "/onvif/ptz", "/onvif/device_service"):
            add(f"http://{host}{port_suffix}{path}")
    return candidates, credentials


def onvif_stop_body(profile_token):
    token = html_escape(profile_token, quote=True)
    return f"""<tptz:Stop>
      <tptz:ProfileToken>{token}</tptz:ProfileToken>
      <tptz:PanTilt>true</tptz:PanTilt>
      <tptz:Zoom>true</tptz:Zoom>
    </tptz:Stop>"""


def onvif_home_body(profile_token):
    token = html_escape(profile_token, quote=True)
    return f"""<tptz:GotoHomePosition>
      <tptz:ProfileToken>{token}</tptz:ProfileToken>
    </tptz:GotoHomePosition>"""


def onvif_move_body(action, speed, duration_ms, profile_token, continuous=False):
    x_dir, y_dir, z_dir = PTZ_MOVE_VECTORS[action]
    token = html_escape(profile_token, quote=True)
    velocity = []
    if x_dir or y_dir:
        velocity.append(
            f'<tt:PanTilt x="{x_dir * speed:.2f}" y="{y_dir * speed:.2f}" '
            'space="http://www.onvif.org/ver10/tptz/PanTiltSpaces/VelocityGenericSpace"/>'
        )
    if z_dir:
        velocity.append(
            f'<tt:Zoom x="{z_dir * speed:.2f}" '
            'space="http://www.onvif.org/ver10/tptz/ZoomSpaces/VelocityGenericSpace"/>'
        )
    timeout = ""
    if not continuous:
        timeout_seconds = max(0.08, min(duration_ms / 1000, 1.5))
        timeout = f"<tptz:Timeout>PT{timeout_seconds:.2f}S</tptz:Timeout>"
    return f"""<tptz:ContinuousMove>
      <tptz:ProfileToken>{token}</tptz:ProfileToken>
      <tptz:Velocity>{''.join(velocity)}</tptz:Velocity>
      {timeout}
    </tptz:ContinuousMove>"""


def run_ptz_command(camera, payload):
    if not camera.get("ptz_enabled"):
        raise ValueError("PTZ is disabled for this camera.")
    ptz_type = normalize_ptz_type(camera.get("ptz_type"))
    if ptz_type == "none":
        raise ValueError("This camera does not have a PTZ driver configured.")

    action = str(payload.get("action", "")).strip().lower().replace("-", "_")
    if action not in PTZ_MOVE_VECTORS and action not in ("stop", "home", "preset"):
        raise ValueError("Unsupported PTZ action.")
    speed = normalize_ptz_speed(payload.get("speed", camera.get("ptz_speed", DEFAULT_PTZ_SPEED)))
    duration_ms = bounded_int(payload.get("duration_ms"), PTZ_DEFAULT_DURATION_MS, 80, 1500)
    continuous = bool(normalize_bool(payload.get("continuous", False)))

    if ptz_type == "victure_dvrip":
        if action == "preset":
            raise ValueError("Presets are not supported by this PTZ driver.")
        return run_victure_dvrip_ptz_command(camera, action, speed, duration_ms)
    if ptz_type == "victure_direct":
        if action == "preset":
            raise ValueError("Presets are not supported by this PTZ driver.")
        return run_victure_direct_ptz_command(camera, action, speed)
    if ptz_type != "onvif":
        raise ValueError("This camera does not have a supported PTZ driver configured.")

    discovery = camera.get("onvif") or {}
    if not discovery.get("success"):
        try:
            discovery = discover_camera_onvif(camera, camera["id"])
        except OnvifError:
            discovery = {}

    selected_profile = discovery.get("selected_profile") or {}
    profile_token = normalize_ptz_profile_token(
        selected_profile.get("token") or camera.get("ptz_profile_token")
    )
    discovered_url = (discovery.get("services") or {}).get("ptz")
    candidates, legacy_credentials = ptz_url_candidates(camera)
    if discovered_url:
        candidates = [discovered_url] + [
            candidate for candidate in candidates if candidate != discovered_url
        ]
    credentials = onvif_payload_credentials(camera) or legacy_credentials
    if not candidates:
        raise ValueError("Could not derive an ONVIF endpoint from this camera URL.")
    allowed_hosts = onvif_allowed_endpoint_hosts(camera)

    features = set(discovery.get("features") or [])
    if features:
        if action in PTZ_MOVE_VECTORS and action.startswith("zoom") and "zoom" not in features:
            raise ValueError("This camera did not advertise continuous zoom support.")
        if action in PTZ_MOVE_VECTORS and not action.startswith("zoom") and "pt" not in features:
            raise ValueError("This camera did not advertise continuous pan/tilt support.")
        if action == "home" and "home" not in features:
            raise ValueError("This camera did not advertise a home position.")
        if action == "preset" and "presets" not in features:
            raise ValueError("This camera did not advertise PTZ presets.")

    if action == "stop":
        body = onvif_stop_body(profile_token)
    elif action == "home":
        body = onvif_home_body(profile_token)
    elif action == "preset":
        preset_token = str(payload.get("preset_token") or "").strip()
        if not preset_token:
            preset_name = str(payload.get("preset_name") or "").strip()
            preset = next(
                (
                    item
                    for item in discovery.get("presets") or []
                    if item.get("name") == preset_name
                ),
                None,
            )
            preset_token = str((preset or {}).get("token") or "")
        if not preset_token:
            raise ValueError("Choose a PTZ preset.")
        body = goto_preset_body(profile_token, preset_token)
    else:
        body = onvif_move_body(
            action,
            speed,
            duration_ms,
            profile_token,
            continuous=continuous,
        )

    last_error = None
    for url in candidates:
        try:
            onvif_soap_post(
                url,
                body,
                credentials=credentials,
                timeout=4,
                allowed_hosts=allowed_hosts,
            )
            stop_warning = None
            if action in PTZ_MOVE_VECTORS and not continuous:
                time.sleep(duration_ms / 1000)
                try:
                    onvif_soap_post(
                        url,
                        onvif_stop_body(profile_token),
                        credentials=credentials,
                        timeout=4,
                        allowed_hosts=allowed_hosts,
                    )
                except OnvifError as exc:
                    stop_warning = f"Move sent, but stop failed: {exc}"
            return {
                "ok": True,
                "action": action,
                "endpoint": redact_url_credentials(url),
                "warning": stop_warning,
                "continuous": continuous,
            }
        except OnvifError as exc:
            last_error = exc

    raise RuntimeError(f"PTZ command failed: {last_error}")


class NightModeManager:
    def __init__(self):
        self.lock = threading.RLock()
        self.states = {}
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self.run, daemon=True)

    def start(self):
        self.thread.start()

    def shutdown(self):
        self.stop_event.set()
        self.thread.join(timeout=5)

    def is_night(self, camera_id):
        with self.lock:
            return bool(self.states.get(camera_id, {}).get("night"))

    def status(self):
        with self.lock:
            return {camera_id: dict(state) for camera_id, state in self.states.items()}

    def sample_camera(self, camera):
        command = [
            FFMPEG_BIN,
            "-hide_banner",
            "-nostdin",
            "-loglevel",
            "error",
        ]
        command.extend(ffmpeg_input_args(camera, low_latency=True))
        command.extend(
            [
                "-frames:v",
                "1",
                "-vf",
                "scale=64:36",
                "-f",
                "rawvideo",
                "-pix_fmt",
                "rgb24",
                "pipe:1",
            ]
        )
        try:
            result = subprocess.run(command, capture_output=True, timeout=12)
        except subprocess.TimeoutExpired:
            return None, "Night sample timed out."
        if result.returncode != 0 or not result.stdout:
            message = result.stderr.decode("utf-8", "replace").strip().splitlines()
            return None, message[-1] if message else "Night sample failed."
        return analyze_rgb_frame(result.stdout), None

    def update_state(self, camera, metrics, error=None):
        camera_id = camera["id"]
        now = time.time()
        with self.lock:
            state = self.states.setdefault(
                camera_id,
                {
                    "night": False,
                    "first_on_at": None,
                    "first_off_at": None,
                    "updated_at": None,
                    "brightness": None,
                    "saturation": None,
                    "error": None,
                },
            )
            if error:
                state["error"] = error
                state["updated_at"] = iso_now()
                return

            brightness = metrics["brightness"]
            saturation = metrics["saturation"]
            wants_on = (saturation <= NIGHT_ON_SATURATION and brightness <= NIGHT_ON_BRIGHTNESS) or (
                brightness <= NIGHT_DARK_BRIGHTNESS
            )
            wants_off = saturation >= NIGHT_OFF_SATURATION or brightness >= NIGHT_OFF_BRIGHTNESS
            if state["night"]:
                state["first_on_at"] = None
                if wants_off:
                    state["first_off_at"] = state["first_off_at"] or now
                    if now - state["first_off_at"] >= NIGHT_OFF_SECONDS:
                        state["night"] = False
                        state["first_off_at"] = None
                else:
                    state["first_off_at"] = None
            else:
                state["first_off_at"] = None
                if wants_on:
                    state["first_on_at"] = state["first_on_at"] or now
                    if now - state["first_on_at"] >= NIGHT_ON_SECONDS:
                        state["night"] = True
                        state["first_on_at"] = None
                else:
                    state["first_on_at"] = None

            state.update(
                {
                    "updated_at": iso_now(),
                    "brightness": round(brightness, 2),
                    "saturation": round(saturation, 2),
                    "error": None,
                }
            )

    def run(self):
        while not self.stop_event.is_set():
            cameras = [camera for camera in list_cameras() if camera.get("enabled") and camera.get("grayscale_mode") == "auto"]
            active_ids = {camera["id"] for camera in cameras}
            with self.lock:
                for camera_id in list(self.states.keys()):
                    if camera_id not in active_ids:
                        self.states.pop(camera_id, None)
            for camera in cameras:
                metrics, error = self.sample_camera(camera)
                self.update_state(camera, metrics, error=error)
                if self.stop_event.wait(0.1):
                    return
            self.stop_event.wait(max(5, NIGHT_SAMPLE_INTERVAL_SECONDS))


def analyze_rgb_frame(data):
    if not data:
        return {"brightness": 0.0, "saturation": 0.0}
    total_luma = 0.0
    total_saturation = 0.0
    pixels = len(data) // 3
    for index in range(0, pixels * 3, 3):
        red = data[index]
        green = data[index + 1]
        blue = data[index + 2]
        maximum = max(red, green, blue)
        minimum = min(red, green, blue)
        total_luma += 0.2126 * red + 0.7152 * green + 0.0722 * blue
        total_saturation += 0.0 if maximum == 0 else ((maximum - minimum) / maximum) * 100
    return {"brightness": total_luma / pixels, "saturation": total_saturation / pixels}


night_modes = NightModeManager()


class RecorderSupervisor:
    def __init__(self):
        self.lock = threading.RLock()
        self.processes = {}
        self.paused_camera_ids = set()
        self.stop_event = threading.Event()
        self.last_retention = 0
        self.thread = threading.Thread(target=self.run, daemon=True)

    def start(self):
        self.thread.start()

    def shutdown(self):
        self.stop_event.set()
        with self.lock:
            camera_ids = list(self.processes.keys())
        for camera_id in camera_ids:
            self.stop(camera_id)
        self.thread.join(timeout=5)

    def status(self):
        with self.lock:
            states = {}
            for camera_id, entry in self.processes.items():
                process = entry["process"]
                output_age = self.output_age(camera_id)
                states[camera_id] = {
                    "running": process.poll() is None,
                    "pid": process.pid,
                    "started_at": entry["started_at"],
                    "last_error": entry.get("last_error"),
                    "paused": False,
                    "output_age_seconds": round(output_age, 1) if output_age is not None else None,
                    "relay_generation": entry.get("relay_generation"),
                }
            for camera_id in self.paused_camera_ids:
                states.setdefault(
                    camera_id,
                    {
                        "running": False,
                        "pid": None,
                        "started_at": None,
                        "last_error": None,
                        "paused": True,
                    },
                )
            return states

    def restart(self, camera_id):
        self.stop(camera_id)

    def pause(self, camera_id):
        with self.lock:
            self.paused_camera_ids.add(camera_id)
        self.stop(camera_id)
        add_event(camera_id, "info", "Recorder paused.")

    def resume(self, camera):
        with self.lock:
            self.paused_camera_ids.discard(camera["id"])
        add_event(camera["id"], "info", "Recorder resumed.")
        self.ensure_running(camera)

    def restart_now(self, camera):
        with self.lock:
            self.paused_camera_ids.discard(camera["id"])
        self.restart(camera["id"])
        self.ensure_running(camera)

    def is_paused(self, camera_id):
        with self.lock:
            return camera_id in self.paused_camera_ids

    def stop(self, camera_id):
        with self.lock:
            entry = self.processes.pop(camera_id, None)
        if not entry:
            return
        self._terminate_entry(entry)
        add_event(camera_id, "info", "Recorder stopped.")

    def ensure_running(self, camera):
        try:
            source_camera = relay.source_camera(camera)
        except (OSError, RuntimeError) as exc:
            with self.lock:
                entry = self.processes.pop(camera["id"], None)
            if entry:
                self._terminate_entry(entry)
            add_event(camera["id"], "error", f"Recorder waiting for go2rtc: {redact_camera_text(str(exc), camera)}")
            return

        relay_generation = source_camera.get("_relay_generation")
        with self.lock:
            entry = self.processes.get(camera["id"])
            if entry and entry["process"].poll() is None:
                generation_matches = entry.get("relay_generation") == relay_generation
                output_fresh = self._output_is_fresh(camera, entry)
                if generation_matches and output_fresh:
                    return
                reason = (
                    "Recorder source was replaced; restarting."
                    if not generation_matches
                    else "Recorder stopped producing fresh output; restarting."
                )
                self.processes.pop(camera["id"], None)
                self._terminate_entry(entry)
                add_event(camera["id"], "warn", reason)
                entry = None
            if entry:
                stderr = ""
                try:
                    stderr = entry["process"].stderr.read() if entry["process"].stderr else ""
                except Exception:
                    stderr = ""
                message = stderr.strip().splitlines()[-1] if stderr.strip() else "Recorder exited."
                add_event(camera["id"], "warn", message)
                self.processes.pop(camera["id"], None)

            try:
                command = build_ffmpeg_command(camera, source_camera=source_camera)
                process = subprocess.Popen(
                    command,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                    text=True,
                    preexec_fn=os.setsid if hasattr(os, "setsid") else None,
                )
            except (OSError, RuntimeError) as exc:
                add_event(camera["id"], "error", f"Could not start FFmpeg: {exc}")
                return
            self.processes[camera["id"]] = {
                "process": process,
                "started_at": iso_now(),
                "started_wall": time.time(),
                "command": command,
                "relay_generation": relay_generation,
            }
            add_event(camera["id"], "info", "Recorder started.")

    def output_age(self, camera_id):
        camera = get_camera(camera_id)
        if not camera:
            return None
        root = camera_dir(camera)
        try:
            latest = max((path.stat().st_mtime for path in root.glob("*.mp4")), default=None)
        except OSError:
            return None
        return time.time() - latest if latest is not None else None

    def _output_is_fresh(self, camera, entry):
        if time.time() - entry.get("started_wall", time.time()) < RECORDER_START_GRACE_SECONDS:
            return True
        age = self.output_age(camera["id"])
        limit = max(RECORDER_STALE_SECONDS, min(float(camera.get("segment_seconds") or 60), 120))
        return age is not None and age <= limit

    def _terminate_entry(self, entry):
        process = entry["process"]
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                process.kill()

    def run_retention(self, cameras):
        now = time.time()
        if now - self.last_retention < RETENTION_INTERVAL_SECONDS:
            return
        self.last_retention = now
        for camera in cameras:
            root = camera_dir(camera)
            if not root.exists():
                continue
            cutoff = now - (int(camera.get("retention_days") or 14) * 86400)
            for path in root.glob("*.mp4"):
                try:
                    if path.stat().st_mtime < cutoff:
                        path.unlink()
                except OSError:
                    continue

    def run(self):
        while not self.stop_event.is_set():
            cameras = list_cameras()
            relay.reconcile(cameras)
            active_ids = set()
            for camera in cameras:
                should_record = (
                    bool(camera["enabled"])
                    and schedule_active(camera["schedule"])
                    and not self.is_paused(camera["id"])
                )
                if should_record:
                    active_ids.add(camera["id"])
                    self.ensure_running(camera)
                else:
                    self.stop(camera["id"])

            with self.lock:
                for camera_id in list(self.processes.keys()):
                    if camera_id not in active_ids and not get_camera(camera_id):
                        self.stop(camera_id)
            self.run_retention(cameras)
            self.stop_event.wait(SCAN_INTERVAL_SECONDS)


recorder = RecorderSupervisor()


def scan_segments(camera, date_value=None):
    root = camera_dir(camera)
    if not root.exists():
        return []
    segments = []
    for path in root.glob("*.mp4"):
        start = segment_start(path)
        if not start:
            continue
        if date_value and start.strftime("%Y-%m-%d") != date_value:
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        segments.append(
            {
                "camera_id": camera["id"],
                "camera_name": camera["name"],
                "filename": path.name,
                "start": start.isoformat(),
                "approx_end": (start + timedelta(seconds=int(camera["segment_seconds"]))).isoformat(),
                "size": stat.st_size,
                "url": f"/media/{camera['id']}/{path.name}",
            }
        )
    segments.sort(key=lambda item: item["start"])
    return segments


def segment_start(path):
    match = SEGMENT_RE.match(path.name)
    if not match:
        return None
    try:
        return datetime.strptime(match.group("stamp"), "%Y%m%dT%H%M%S")
    except ValueError:
        return None


def recording_coverage(camera):
    root = camera_dir(camera)
    summary = {
        "camera_id": camera["id"],
        "count": 0,
        "total_size": 0,
        "oldest": None,
        "newest": None,
        "dates": [],
        "retention_days": int(camera.get("retention_days") or 14),
    }
    if not root.exists():
        return summary
    dates = set()
    oldest = None
    newest = None
    for path in root.glob("*.mp4"):
        start = segment_start(path)
        if not start:
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        summary["count"] += 1
        summary["total_size"] += stat.st_size
        dates.add(start.strftime("%Y-%m-%d"))
        oldest = start if oldest is None or start < oldest else oldest
        newest = start if newest is None or start > newest else newest
    summary["oldest"] = oldest.isoformat() if oldest else None
    summary["newest"] = newest.isoformat() if newest else None
    summary["dates"] = sorted(dates)
    return summary


def probe_stream_url(url, payload, select_streams, show_entries, low_latency=True):
    transport = payload.get("rtsp_transport", "tcp")
    command = [
        FFPROBE_BIN,
        "-v",
        "error",
    ]
    if url.startswith(("rtsp://", "rtsps://")):
        probesize = RTSP_PROBESIZE if low_latency else RTSP_LIVE_PROBESIZE
        analyze_duration = RTSP_ANALYZE_DURATION if low_latency else RTSP_LIVE_ANALYZE_DURATION
        command.extend(
            [
                "-rtsp_transport",
                transport if transport in ("tcp", "udp") else "tcp",
                "-probesize",
                probesize,
                "-analyzeduration",
                analyze_duration,
            ]
        )
        if low_latency:
            command.extend(["-fflags", "nobuffer"])
        else:
            command.extend(["-fflags", "+genpts"])
    command.extend(
        [
            "-select_streams",
            select_streams,
            "-show_entries",
            show_entries,
            "-of",
            "json",
            url,
        ]
    )
    started = time.time()
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=15)
    except subprocess.TimeoutExpired:
        return {"ok": False, "message": "Timed out after 15 seconds.", "seconds": 15}
    elapsed = round(time.time() - started, 2)
    if result.returncode != 0:
        message = result.stderr.strip().splitlines()[-1] if result.stderr.strip() else "ffprobe failed."
        return {"ok": False, "message": message, "seconds": elapsed}
    try:
        details = json.loads(result.stdout or "{}")
    except json.JSONDecodeError:
        details = {}
    return {"ok": True, "message": "Stream is reachable.", "seconds": elapsed, "details": details}


def test_stream(payload):
    rtsp_url = str(payload.get("rtsp_url", "")).strip()
    audio_url = str(payload.get("audio_url", "")).strip()
    if not rtsp_url:
        raise ValueError("RTSP URL is required.")
    if not rtsp_url.startswith(STREAM_URL_PREFIXES):
        raise ValueError("Use an rtsp://, rtsps://, http://, or https:// stream URL.")
    if audio_url and not audio_url.startswith(STREAM_URL_PREFIXES):
        raise ValueError("Use an rtsp://, rtsps://, http://, or https:// audio URL.")

    video = probe_stream_url(rtsp_url, payload, "v:0", "stream=codec_name,width,height,r_frame_rate")
    if not audio_url or not normalize_bool(payload.get("record_audio", True)):
        return video

    audio = probe_stream_url(audio_url, payload, "a:0", "stream=codec_name,sample_rate,channels")
    if video["ok"] and audio["ok"]:
        return {
            "ok": True,
            "message": "Video and secondary audio are reachable.",
            "seconds": round(video["seconds"] + audio["seconds"], 2),
            "details": {"video": video.get("details", {}), "audio": audio.get("details", {})},
        }
    return {
        "ok": False,
        "message": audio["message"] if video["ok"] else video["message"],
        "seconds": round(video["seconds"] + audio["seconds"], 2),
        "details": {"video": video, "audio": audio},
    }


def redact_camera_text(text, camera):
    redacted = text or ""
    replacements = {
        str(camera.get("rtsp_url") or "").strip(): "<stream-url>",
        str(camera.get("audio_url") or "").strip(): "<audio-url>",
        str(camera.get("ptz_url") or "").strip(): "<ptz-url>",
    }
    for value, label in replacements.items():
        if value:
            redacted = redacted.replace(value, label)
    redacted = re.sub(
        r"([a-zA-Z][a-zA-Z0-9+.-]*://)[^/\s\"'@]+@",
        r"\1<credentials>@",
        redacted,
    )
    return redacted


def stream_summary(probe):
    if not probe or not probe.get("ok"):
        return probe.get("message", "Unavailable") if probe else "Unavailable"
    streams = (probe.get("details") or {}).get("streams") or []
    if not streams:
        return "Reachable, but no matching stream details were returned"
    stream = streams[0]
    codec = stream.get("codec_name") or "unknown"
    size = ""
    if stream.get("width") and stream.get("height"):
        size = f" {stream['width']}x{stream['height']}"
    sample_rate = stream.get("sample_rate")
    channels = stream.get("channels")
    audio = ""
    if sample_rate or channels:
        audio = f" {sample_rate or '?'}Hz {channels or '?'}ch"
    rate = stream.get("r_frame_rate") or stream.get("avg_frame_rate") or ""
    suffix = rate if rate and rate != "0/0" else ""
    return " ".join(part for part in [codec + size + audio, suffix] if part)


def live_diagnostics(camera, include_audio=True):
    include_audio = bool(include_audio)
    profile = f"go2rtc / {'audio' if include_audio else 'video only'}"
    video = probe_stream_url(
        camera["rtsp_url"],
        camera,
        "v:0",
        "stream=codec_name,width,height,r_frame_rate,avg_frame_rate",
        low_latency=False,
    )
    audio = None
    if include_audio and camera.get("record_audio", True):
        audio_url = str(camera.get("audio_url") or "").strip() or camera["rtsp_url"]
        audio = probe_stream_url(
            audio_url,
            camera,
            "a:0",
            "stream=codec_name,sample_rate,channels",
            low_latency=False,
        )

    configured = go2rtc.can_restream(camera) and go2rtc.configure_camera(camera)
    stream = go2rtc.stream_info(camera) if configured else None
    go2rtc_result = {
        "ok": bool(go2rtc.running() and configured and stream is not None),
        "message": "go2rtc stream is configured."
        if configured
        else (go2rtc.last_error or "go2rtc stream is unavailable."),
        "stream": stream,
    }

    log_tail = redact_camera_text(go2rtc.log_tail(12), camera)
    parts = [
        f"Profile: {profile}.",
        f"Video: {stream_summary(video)}.",
    ]
    if audio:
        parts.append(f"Audio: {stream_summary(audio)}.")
    parts.append(f"go2rtc: {go2rtc_result['message']}")
    return {
        "ok": bool(go2rtc_result.get("ok")),
        "message": " ".join(parts),
        "video": video,
        "audio": audio,
        "go2rtc": go2rtc_result,
        "log": log_tail,
    }


def compatibility_recommendations(stream_result, discovery):
    recommendations = []
    details = stream_result.get("details") or {}
    streams = list(details.get("streams") or [])
    for section in ("video", "audio"):
        nested = details.get(section) or {}
        streams.extend(nested.get("details", nested).get("streams") or [])
    codecs = {str(item.get("codec_name") or "").lower() for item in streams}
    if "h264" not in codecs:
        recommendations.append(
            "Use H.264 for the live stream when possible; it has the widest MSE, "
            "WebRTC, Safari, and Home Assistant compatibility."
        )
    if codecs.intersection({"pcm_alaw", "pcm_mulaw", "pcma", "pcmu", "opus"}) and "aac" not in codecs:
        recommendations.append(
            "The camera audio may need on-demand AAC transcoding for MSE playback."
        )
    if "hevc" in codecs or "h265" in codecs:
        recommendations.append(
            "H.265 support varies by browser. Keep an H.264 profile available for live view."
        )
    if not discovery.get("success"):
        recommendations.append(
            "ONVIF discovery did not complete. Verify that ONVIF is enabled in the "
            "camera and that the stream credentials also have ONVIF permission."
        )
    if discovery.get("ptz_supported") and not discovery.get("presets"):
        recommendations.append(
            "Pan/tilt was detected, but the selected ONVIF profile returned no presets."
        )
    if not recommendations:
        recommendations.append(
            "The detected stream and ONVIF capabilities match PlainNVR's preferred path."
        )
    return recommendations


def camera_compatibility_report(camera, refresh_onvif=True):
    stream_result = test_stream(camera)
    discovery = camera.get("onvif") or {}
    discovery_error = None
    if refresh_onvif:
        try:
            discovery = discover_camera_onvif(camera, camera["id"])
        except OnvifError as exc:
            discovery_error = str(exc)
    if discovery_error and not discovery:
        discovery = {
            "success": False,
            "tested_at": iso_now(),
            "features": [],
            "profiles": [],
            "presets": [],
            "errors": [discovery_error],
        }
    elif discovery_error:
        discovery = dict(discovery)
        discovery.setdefault("errors", []).append(discovery_error)

    report = {
        "schema_version": 1,
        "generated_at": iso_now(),
        "plainnvr": {
            "server": NvrHandler.server_version,
            "go2rtc": go2rtc.status(),
        },
        "camera": {
            "id": camera["id"],
            "name": camera["name"],
            "enabled": camera["enabled"],
            "stream_url": redact_onvif_url(camera.get("rtsp_url")),
            "audio_url": redact_onvif_url(camera.get("audio_url")),
            "transport": camera.get("rtsp_transport"),
            "record_audio": camera.get("record_audio"),
            "live_view_mode": camera.get("live_view_mode"),
            "ptz_enabled": camera.get("ptz_enabled"),
            "ptz_type": camera.get("ptz_type"),
        },
        "stream_probe": stream_result,
        "onvif": redacted_discovery(discovery),
        "go2rtc_stream": go2rtc.stream_info(camera),
        "relay": relay.status([camera]).get(camera["id"]),
        "recorder": recorder.status().get(camera["id"]),
        "recordings": recording_coverage(camera),
        "recommendations": compatibility_recommendations(stream_result, discovery),
    }
    serialized = json.dumps(report)
    serialized = redact_camera_text(serialized, camera)
    return json.loads(serialized)


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
    if expected and provided and hmac.compare_digest(provided, expected):
        return True
    username, password = basic_auth_credentials(handler.headers)
    return bool(username and authenticate_user(username, password))


class NvrHandler(SimpleHTTPRequestHandler):
    server_version = "PlainNVR/0.1"

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
        parsed = urlparse(self.path)
        if not self.ensure_authorized(parsed):
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
        parsed = urlparse(self.path)
        if not self.ensure_authorized(parsed):
            return
        try:
            payload = parse_json_body(self)
        except ValueError as exc:
            self.send_error_json(HTTPStatus.BAD_REQUEST, str(exc))
            return
        if parsed.path == "/api/settings":
            self.send_json({"settings": update_app_settings(payload)})
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
            username = create_user(payload.get("username"), payload.get("password"))
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
        if action == "restart":
            go2rtc.restart_camera(camera)
        elif action == "start":
            pass
        self.send_json({"ok": True})

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
        ptz_url = str(payload.get("ptz_url") or "").strip()
        if not rtsp_url and not ptz_url:
            self.send_error_json(
                HTTPStatus.BAD_REQUEST,
                "Enter a stream URL or ONVIF control URL first.",
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
        upstream_path = parsed.path[len("/go2rtc") :]
        if not upstream_path.startswith("/api/"):
            self.send_error_json(HTTPStatus.NOT_FOUND, "Not found.")
            return
        if parsed.query:
            upstream_path = f"{upstream_path}?{parsed.query}"
        if self.headers.get("Upgrade", "").lower() == "websocket":
            self.proxy_go2rtc_websocket(upstream_path)
            return
        request_headers = {"Accept": self.headers.get("Accept", "*/*")}
        if self.headers.get("Range"):
            request_headers["Range"] = self.headers["Range"]
        request = urllib_request.Request(
            f"http://{GO2RTC_API_HOST}:{GO2RTC_API_PORT}{upstream_path}",
            method="HEAD" if head_only else "GET",
            headers=request_headers,
        )
        try:
            response = urllib_request.urlopen(request, timeout=10)
        except urllib_error.HTTPError as exc:
            response = exc
        except (OSError, urllib_error.URLError) as exc:
            self.send_error_json(HTTPStatus.BAD_GATEWAY, f"go2rtc proxy failed: {exc}")
            return
        with response:
            self.send_response(response.status)
            for key in (
                "Content-Type",
                "Content-Length",
                "Content-Range",
                "Accept-Ranges",
                "Cache-Control",
            ):
                value = response.headers.get(key)
                if value:
                    self.send_header(key, value)
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            if not head_only:
                shutil.copyfileobj(response, self.wfile, length=64 * 1024)

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

    def handle_live_hls(self, parsed):
        match = re.match(r"^/live/([a-f0-9]+)/(stream\.m3u8|hls/.+)$", parsed.path)
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
        self.proxy_go2rtc_live_hls(upstream_path, camera["id"], token)

    def handle_live_hls_head(self, parsed):
        match = re.match(r"^/live/([a-f0-9]+)/(stream\.m3u8|hls/.+)$", parsed.path)
        if not match or not get_camera(match.group(1)):
            self.send_response(HTTPStatus.NOT_FOUND)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/vnd.apple.mpegurl")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def proxy_go2rtc_live_hls(self, upstream_path, camera_id, token=""):
        request = urllib_request.Request(
            f"http://{GO2RTC_API_HOST}:{GO2RTC_API_PORT}{upstream_path}",
            headers={"Accept": self.headers.get("Accept", "*/*")},
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
            if is_playlist:
                text = response.read().decode("utf-8", "replace")
                self.send_go2rtc_live_playlist(text, camera_id, token)
                return
            self.send_response(response.status)
            for key in ("Content-Type", "Content-Length", "Accept-Ranges", "Cache-Control"):
                value = response.headers.get(key)
                if value:
                    self.send_header(key, value)
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
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
            match = re.match(r"bytes=(\d*)-(\d*)", range_header)
            if match:
                if match.group(1):
                    start = int(match.group(1))
                if match.group(2):
                    end = int(match.group(2))
                end = min(end, size - 1)
                if start <= end:
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


def main():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)
    init_db()
    go2rtc.start(list_cameras())
    recorder.start()
    server = ThreadingHTTPServer((APP_HOST, APP_PORT), NvrHandler)

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
