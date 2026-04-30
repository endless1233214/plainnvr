#!/usr/bin/env python3
import base64
import json
import hashlib
import hmac
import mimetypes
import os
import re
import secrets
import shutil
import signal
import sqlite3
import subprocess
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse


APP_HOST = os.environ.get("NVR_HOST", "0.0.0.0")
APP_PORT = int(os.environ.get("NVR_PORT", "8787"))
DATA_DIR = Path(os.environ.get("NVR_DATA_DIR", "/data")).expanduser()
RECORDINGS_DIR = Path(os.environ.get("NVR_RECORDINGS_DIR", "/recordings")).expanduser()
STATIC_DIR = Path(os.environ.get("NVR_STATIC_DIR", "/app/static")).expanduser()
FFMPEG_BIN = os.environ.get("FFMPEG_BIN", "ffmpeg")
FFPROBE_BIN = os.environ.get("FFPROBE_BIN", "ffprobe")
SCAN_INTERVAL_SECONDS = int(os.environ.get("NVR_SCAN_INTERVAL_SECONDS", "10"))
RETENTION_INTERVAL_SECONDS = int(os.environ.get("NVR_RETENTION_INTERVAL_SECONDS", "3600"))
DEFAULT_SEGMENT_SECONDS = int(os.environ.get("NVR_DEFAULT_SEGMENT_SECONDS", "60"))
DB_PATH = DATA_DIR / "nvr.sqlite3"
AUTH_COOKIE_NAME = "plainnvr_session"
AUTH_SESSION_TTL_SECONDS = int(os.environ.get("NVR_SESSION_TTL_SECONDS", str(7 * 24 * 60 * 60)))
AUTH_HASH_ITERATIONS = int(os.environ.get("NVR_AUTH_HASH_ITERATIONS", "260000"))
BOOTSTRAP_USERNAME = os.environ.get("NVR_AUTH_USERNAME", "admin").strip() or "admin"
BOOTSTRAP_PASSWORD = os.environ.get("NVR_AUTH_PASSWORD", "")
STREAM_TOKEN_OVERRIDE = os.environ.get("NVR_STREAM_TOKEN", "").strip()

DAY_KEYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
SEGMENT_RE = re.compile(r"^(?P<stamp>\d{8}T\d{6})\.mp4$")


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
                enabled INTEGER NOT NULL DEFAULT 1,
                segment_seconds INTEGER NOT NULL DEFAULT 60,
                retention_days INTEGER NOT NULL DEFAULT 14,
                schedule_json TEXT NOT NULL,
                record_audio INTEGER NOT NULL DEFAULT 1,
                rtsp_transport TEXT NOT NULL DEFAULT 'tcp',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
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
    data["schedule"] = normalize_schedule(json.loads(data.pop("schedule_json")))
    return data


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
    if not partial or "name" in payload:
        if not name:
            errors["name"] = "Name is required."
    if not partial or "rtsp_url" in payload:
        if not rtsp_url:
            errors["rtsp_url"] = "RTSP URL is required."
        elif not rtsp_url.startswith(("rtsp://", "rtsps://", "http://", "https://")):
            errors["rtsp_url"] = "Use an rtsp://, rtsps://, http://, or https:// stream URL."
    if errors:
        raise ValueError(json.dumps(errors))


def create_camera(payload):
    validate_camera_payload(payload)
    now = iso_now()
    camera_id = uuid.uuid4().hex
    schedule = normalize_schedule(payload.get("schedule"))
    segment_seconds = max(10, int(payload.get("segment_seconds") or DEFAULT_SEGMENT_SECONDS))
    retention_days = max(1, int(payload.get("retention_days") or 14))
    with db_conn() as conn:
        slug = unique_slug(conn, payload["name"])
        conn.execute(
            """
            INSERT INTO cameras (
                id, name, slug, rtsp_url, enabled, segment_seconds, retention_days,
                schedule_json, record_audio, rtsp_transport, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                camera_id,
                payload["name"].strip(),
                slug,
                payload["rtsp_url"].strip(),
                normalize_bool(payload.get("enabled", True)),
                segment_seconds,
                retention_days,
                json.dumps(schedule),
                normalize_bool(payload.get("record_audio", True)),
                payload.get("rtsp_transport", "tcp") if payload.get("rtsp_transport") in ("tcp", "udp") else "tcp",
                now,
                now,
            ),
        )
    return get_camera(camera_id)


def update_camera(camera_id, payload):
    existing = get_camera(camera_id)
    if not existing:
        return None
    validate_camera_payload(payload, partial=True)
    merged = {**existing, **payload}
    schedule = normalize_schedule(merged.get("schedule"))
    segment_seconds = max(10, int(merged.get("segment_seconds") or DEFAULT_SEGMENT_SECONDS))
    retention_days = max(1, int(merged.get("retention_days") or 14))
    with db_conn() as conn:
        slug = unique_slug(conn, merged["name"], camera_id)
        conn.execute(
            """
            UPDATE cameras
            SET name = ?, slug = ?, rtsp_url = ?, enabled = ?, segment_seconds = ?,
                retention_days = ?, schedule_json = ?, record_audio = ?,
                rtsp_transport = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                str(merged["name"]).strip(),
                slug,
                str(merged["rtsp_url"]).strip(),
                normalize_bool(merged.get("enabled")),
                segment_seconds,
                retention_days,
                json.dumps(schedule),
                normalize_bool(merged.get("record_audio")),
                merged.get("rtsp_transport") if merged.get("rtsp_transport") in ("tcp", "udp") else "tcp",
                iso_now(),
                camera_id,
            ),
        )
    recorder.restart(camera_id)
    return get_camera(camera_id)


def delete_camera(camera_id):
    recorder.stop(camera_id)
    with db_conn() as conn:
        cur = conn.execute("DELETE FROM cameras WHERE id = ?", (camera_id,))
    return cur.rowcount > 0


def add_event(camera_id, level, message):
    try:
        with db_conn() as conn:
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


def build_ffmpeg_command(camera):
    target_dir = camera_dir(camera)
    target_dir.mkdir(parents=True, exist_ok=True)
    output_pattern = str(target_dir / "%Y%m%dT%H%M%S.mp4")
    command = [
        FFMPEG_BIN,
        "-hide_banner",
        "-nostdin",
        "-loglevel",
        "warning",
    ]
    command.extend(ffmpeg_input_args(camera))
    command.extend(
        [
            "-map",
            "0:v:0",
        ]
    )
    if camera.get("record_audio", True):
        command.extend(["-map", "0:a?"])
    command.extend(
        [
            "-c",
            "copy",
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


def ffmpeg_input_args(camera_or_payload):
    url = str(camera_or_payload["rtsp_url"]).strip()
    transport = camera_or_payload.get("rtsp_transport", "tcp")
    args = []
    if url.startswith(("rtsp://", "rtsps://")):
        args.extend(["-rtsp_transport", transport if transport in ("tcp", "udp") else "tcp"])
    args.extend(["-i", url])
    return args


def build_snapshot_command(camera):
    command = [
        FFMPEG_BIN,
        "-hide_banner",
        "-nostdin",
        "-loglevel",
        "error",
    ]
    command.extend(ffmpeg_input_args(camera))
    command.extend(["-frames:v", "1", "-q:v", "4", "-f", "image2pipe", "-vcodec", "mjpeg", "pipe:1"])
    return command


def build_mjpeg_command(camera, fps=2, width=1280):
    try:
        fps = int(fps)
    except (TypeError, ValueError):
        fps = 2
    try:
        width = int(width)
    except (TypeError, ValueError):
        width = 1280
    fps = max(1, min(fps, 10))
    width = max(320, min(width, 1920))
    command = [
        FFMPEG_BIN,
        "-hide_banner",
        "-nostdin",
        "-loglevel",
        "error",
    ]
    command.extend(ffmpeg_input_args(camera))
    command.extend(
        [
            "-an",
            "-vf",
            f"fps={fps},scale='min({width},iw)':-2",
            "-q:v",
            "6",
            "-f",
            "mpjpeg",
            "pipe:1",
        ]
    )
    return command


class RecorderSupervisor:
    def __init__(self):
        self.lock = threading.RLock()
        self.processes = {}
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
                states[camera_id] = {
                    "running": process.poll() is None,
                    "pid": process.pid,
                    "started_at": entry["started_at"],
                    "last_error": entry.get("last_error"),
                }
            return states

    def restart(self, camera_id):
        self.stop(camera_id)

    def stop(self, camera_id):
        with self.lock:
            entry = self.processes.pop(camera_id, None)
        if not entry:
            return
        process = entry["process"]
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                process.kill()
        add_event(camera_id, "info", "Recorder stopped.")

    def ensure_running(self, camera):
        with self.lock:
            entry = self.processes.get(camera["id"])
            if entry and entry["process"].poll() is None:
                return
            if entry:
                stderr = ""
                try:
                    stderr = entry["process"].stderr.read() if entry["process"].stderr else ""
                except Exception:
                    stderr = ""
                message = stderr.strip().splitlines()[-1] if stderr.strip() else "Recorder exited."
                add_event(camera["id"], "warn", message)
                self.processes.pop(camera["id"], None)

            command = build_ffmpeg_command(camera)
            try:
                process = subprocess.Popen(
                    command,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                    text=True,
                    preexec_fn=os.setsid if hasattr(os, "setsid") else None,
                )
            except OSError as exc:
                add_event(camera["id"], "error", f"Could not start FFmpeg: {exc}")
                return
            self.processes[camera["id"]] = {
                "process": process,
                "started_at": iso_now(),
                "command": command,
            }
            add_event(camera["id"], "info", "Recorder started.")

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
            active_ids = set()
            for camera in cameras:
                should_record = bool(camera["enabled"]) and schedule_active(camera["schedule"])
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


def test_stream(payload):
    rtsp_url = str(payload.get("rtsp_url", "")).strip()
    if not rtsp_url:
        raise ValueError("RTSP URL is required.")
    transport = payload.get("rtsp_transport", "tcp")
    command = [
        FFPROBE_BIN,
        "-v",
        "error",
    ]
    if rtsp_url.startswith(("rtsp://", "rtsps://")):
        command.extend(["-rtsp_transport", transport if transport in ("tcp", "udp") else "tcp"])
    command.extend(
        [
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=codec_name,width,height,r_frame_rate",
            "-of",
            "json",
            rtsp_url,
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
        print(f"{self.address_string()} - {fmt % args}")

    def send_json(self, value, status=HTTPStatus.OK, headers=None):
        data = json.dumps(value).encode("utf-8")
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
            "/api/auth/state",
            "/api/auth/login",
            "/api/auth/setup",
        }
        return parsed.path in public_paths

    def ensure_authorized(self, parsed):
        if self.is_public_path(parsed):
            return True
        if parsed.path.startswith("/ha/"):
            if valid_stream_auth(self, parsed):
                return True
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
        if parsed.path.startswith("/ha/"):
            self.handle_home_assistant(parsed)
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
        if parsed.path.startswith("/api/"):
            self.send_response(HTTPStatus.METHOD_NOT_ALLOWED)
            self.send_header("Content-Length", "0")
            self.end_headers()
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

    def handle_api_get(self, parsed):
        query = parse_qs(parsed.query)
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

    def handle_home_assistant(self, parsed):
        match = re.match(r"^/ha/([a-f0-9]+)/(snapshot\.jpg|stream\.mjpeg)$", parsed.path)
        if not match:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        camera = get_camera(match.group(1))
        if not camera:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        if match.group(2) == "snapshot.jpg":
            self.handle_snapshot(camera)
            return
        query = parse_qs(parsed.query)
        fps = query.get("fps", ["2"])[0]
        width = query.get("width", ["1280"])[0]
        self.handle_mjpeg(camera, fps, width)

    def handle_home_assistant_head(self, parsed):
        match = re.match(r"^/ha/([a-f0-9]+)/(snapshot\.jpg|stream\.mjpeg)$", parsed.path)
        if not match:
            self.send_response(HTTPStatus.NOT_FOUND)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if not get_camera(match.group(1)):
            self.send_response(HTTPStatus.NOT_FOUND)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        self.send_response(HTTPStatus.OK)
        if match.group(2) == "snapshot.jpg":
            self.send_header("Content-Type", "image/jpeg")
        else:
            self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=ffmpeg")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def handle_snapshot(self, camera):
        try:
            result = subprocess.run(build_snapshot_command(camera), capture_output=True, timeout=20)
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
        self.wfile.write(result.stdout)

    def handle_mjpeg(self, camera, fps, width):
        try:
            process = subprocess.Popen(
                build_mjpeg_command(camera, fps, width),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        except OSError as exc:
            self.send_error(HTTPStatus.BAD_GATEWAY, f"Could not start FFmpeg: {exc}")
            return

        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=ffmpeg")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            while True:
                chunk = process.stdout.read(8192)
                if not chunk:
                    break
                self.wfile.write(chunk)
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()

    def handle_media(self, path):
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
        server.server_close()


if __name__ == "__main__":
    main()
