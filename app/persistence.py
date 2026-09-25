import json
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone


LOG_LEVELS = ("trace", "debug", "info", "warn", "error", "fatal")
LOG_LEVEL_ORDER = {
    level: index
    for index, level in enumerate(LOG_LEVELS)
}
APP_SETTING_DEFAULTS = {
    "home_assistant_enabled": False,
    "reduce_storage_writes": True,
    "log_level": "info",
}


def get_db(data_dir, db_path):
    data_dir.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


@contextmanager
def db_conn(data_dir, db_path):
    conn = get_db(data_dir, db_path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def ensure_camera_schema(conn):
    columns = {
        row["name"]
        for row in conn.execute(
            "PRAGMA table_info(cameras)"
        ).fetchall()
    }
    migrations = (
        (
            "audio_url",
            "ALTER TABLE cameras ADD COLUMN "
            "audio_url TEXT NOT NULL DEFAULT ''",
        ),
        (
            "grayscale_mode",
            "ALTER TABLE cameras ADD COLUMN "
            "grayscale_mode TEXT NOT NULL DEFAULT 'off'",
        ),
        (
            "live_view_mode",
            "ALTER TABLE cameras ADD COLUMN "
            "live_view_mode TEXT NOT NULL DEFAULT 'hls'",
        ),
        (
            "view_rotation",
            "ALTER TABLE cameras ADD COLUMN "
            "view_rotation INTEGER NOT NULL DEFAULT 0",
        ),
        (
            "rtsp_transport",
            "ALTER TABLE cameras ADD COLUMN "
            "rtsp_transport TEXT NOT NULL DEFAULT 'tcp'",
        ),
        (
            "ptz_enabled",
            "ALTER TABLE cameras ADD COLUMN "
            "ptz_enabled INTEGER NOT NULL DEFAULT 0",
        ),
        (
            "ptz_type",
            "ALTER TABLE cameras ADD COLUMN "
            "ptz_type TEXT NOT NULL DEFAULT 'onvif'",
        ),
        (
            "onvif_url",
            "ALTER TABLE cameras ADD COLUMN "
            "onvif_url TEXT NOT NULL DEFAULT ''",
        ),
        (
            "ptz_url",
            "ALTER TABLE cameras ADD COLUMN "
            "ptz_url TEXT NOT NULL DEFAULT ''",
        ),
        (
            "ptz_profile_token",
            "ALTER TABLE cameras ADD COLUMN "
            "ptz_profile_token TEXT NOT NULL DEFAULT 'Profile_1'",
        ),
        (
            "ptz_zoom_mode",
            "ALTER TABLE cameras ADD COLUMN "
            "ptz_zoom_mode TEXT NOT NULL DEFAULT 'auto'",
        ),
        (
            "ptz_speed",
            "ALTER TABLE cameras ADD COLUMN "
            "ptz_speed REAL NOT NULL DEFAULT 0.55",
        ),
        (
            "onvif_json",
            "ALTER TABLE cameras ADD COLUMN "
            "onvif_json TEXT NOT NULL DEFAULT '{}'",
        ),
        (
            "onvif_updated_at",
            "ALTER TABLE cameras ADD COLUMN "
            "onvif_updated_at TEXT NOT NULL DEFAULT ''",
        ),
    )
    for column, statement in migrations:
        if column not in columns:
            conn.execute(statement)


def bootstrap_auth_from_env(
    conn,
    *,
    bootstrap_password,
    bootstrap_username,
    validate_username,
    validate_password,
    password_hash,
    iso_now,
):
    row = conn.execute(
        "SELECT username FROM users LIMIT 1"
    ).fetchone()
    if row or not bootstrap_password:
        return

    username = validate_username(
        bootstrap_username
    )
    password = validate_password(
        bootstrap_password
    )
    hashed = password_hash(password)
    now = iso_now()
    conn.execute(
        """
        INSERT INTO users (
            username, password_hash,
            created_at, updated_at
        )
        VALUES (?, ?, ?, ?)
        """,
        (username, hashed, now, now),
    )
    print(
        "Created PlainNVR admin user from "
        "NVR_AUTH_USERNAME/NVR_AUTH_PASSWORD: "
        f"{username}"
    )


def ensure_stream_token(
    conn,
    *,
    stream_token_override,
    iso_now,
):
    if stream_token_override:
        return stream_token_override

    row = conn.execute(
        "SELECT value FROM app_settings "
        "WHERE key = 'stream_token'"
    ).fetchone()
    if row:
        return row["value"]

    token = secrets.token_urlsafe(32)
    conn.execute(
        """
        INSERT INTO app_settings (
            key, value, updated_at
        )
        VALUES ('stream_token', ?, ?)
        """,
        (token, iso_now()),
    )
    return token


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
    except (
        TypeError,
        ValueError,
        json.JSONDecodeError,
    ):
        return default


def normalize_log_level(value, default="info"):
    level = str(value or "").strip().lower()
    return (
        level
        if level in LOG_LEVELS
        else default
    )


def get_app_settings(
    *,
    db_conn,
):
    settings = dict(APP_SETTING_DEFAULTS)
    with db_conn() as conn:
        rows = conn.execute(
            """
            SELECT key, value
            FROM app_settings
            WHERE key IN (
                'home_assistant_enabled',
                'reduce_storage_writes',
                'log_level'
            )
            """
        ).fetchall()

    for row in rows:
        key = row["key"]
        if key == "log_level":
            raw = row["value"]
            try:
                raw = json.loads(raw)
            except (
                TypeError,
                ValueError,
                json.JSONDecodeError,
            ):
                pass
            settings[key] = normalize_log_level(raw)
        else:
            settings[key] = setting_bool(
                row["value"],
                default=APP_SETTING_DEFAULTS[key],
            )
    return settings


def update_app_settings(
    payload,
    *,
    get_app_settings,
    db_conn,
    iso_now,
):
    settings = get_app_settings()
    for key in (
        "home_assistant_enabled",
        "reduce_storage_writes",
    ):
        if key in payload:
            settings[key] = setting_bool(
                payload.get(key),
                default=APP_SETTING_DEFAULTS[key],
            )

    if "log_level" in payload:
        requested = str(
            payload.get("log_level") or ""
        ).strip().lower()
        if requested not in LOG_LEVELS:
            raise ValueError(
                "Log level must be TRACE, DEBUG, "
                "INFO, WARN, ERROR, or FATAL."
            )
        settings["log_level"] = requested

    now = iso_now()
    with db_conn() as conn:
        for key, value in settings.items():
            conn.execute(
                """
                INSERT INTO app_settings (
                    key, value, updated_at
                )
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    updated_at = excluded.updated_at
                """,
                (
                    key,
                    json.dumps(value),
                    now,
                ),
            )
    return settings


def cleanup_expired_sessions(
    conn,
    *,
    iso_now,
):
    conn.execute(
        "DELETE FROM sessions "
        "WHERE expires_at <= ?",
        (iso_now(),),
    )


def setup_required(*, db_conn):
    with db_conn() as conn:
        row = conn.execute(
            "SELECT username FROM users LIMIT 1"
        ).fetchone()
    return row is None


def create_user(
    username,
    password,
    initial_setup=False,
    *,
    validate_username,
    validate_password,
    password_hash,
    db_conn,
    iso_now,
):
    username = validate_username(username)
    password = validate_password(password)
    hashed = password_hash(password)

    with db_conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        if (
            initial_setup
            and conn.execute(
                "SELECT 1 FROM users LIMIT 1"
            ).fetchone()
        ):
            raise ValueError(
                "Admin account already exists."
            )
        if conn.execute(
            "SELECT username FROM users "
            "WHERE username = ?",
            (username,),
        ).fetchone():
            raise ValueError(
                "Username already exists."
            )

        now = iso_now()
        conn.execute(
            """
            INSERT INTO users (
                username, password_hash,
                created_at, updated_at
            )
            VALUES (?, ?, ?, ?)
            """,
            (
                username,
                hashed,
                now,
                now,
            ),
        )
    return username


def list_users(*, db_conn):
    with db_conn() as conn:
        rows = conn.execute(
            """
            SELECT username, created_at, updated_at
            FROM users
            ORDER BY username COLLATE NOCASE
            """
        ).fetchall()
    return [dict(row) for row in rows]


def delete_user(
    username,
    current_username=None,
    *,
    validate_username,
    unquote,
    db_conn,
):
    username = validate_username(
        unquote(username)
    )
    if (
        current_username
        and username == current_username
    ):
        raise ValueError(
            "You cannot delete the account "
            "you are using."
        )

    with db_conn() as conn:
        row = conn.execute(
            "SELECT username FROM users "
            "WHERE username = ?",
            (username,),
        ).fetchone()
        if not row:
            return False

        count = conn.execute(
            "SELECT COUNT(*) AS count FROM users"
        ).fetchone()["count"]
        if count <= 1:
            raise ValueError(
                "At least one user account "
                "is required."
            )

        conn.execute(
            "DELETE FROM users "
            "WHERE username = ?",
            (username,),
        )
    return True


def authenticate_user(
    username,
    password,
    *,
    db_conn,
    verify_password,
):
    username = str(username or "").strip()
    with db_conn() as conn:
        row = conn.execute(
            "SELECT * FROM users "
            "WHERE username = ?",
            (username,),
        ).fetchone()

    if (
        not row
        or not verify_password(
            str(password or ""),
            row["password_hash"],
        )
    ):
        return None
    return row["username"]


def create_session(
    username,
    *,
    db_conn,
    cleanup_expired_sessions,
    utcnow,
    session_ttl_seconds,
):
    session_id = secrets.token_urlsafe(32)
    now = utcnow()
    expires_at = now + timedelta(
        seconds=session_ttl_seconds
    )

    with db_conn() as conn:
        cleanup_expired_sessions(conn)
        conn.execute(
            """
            INSERT INTO sessions (
                id, username, created_at,
                last_seen_at, expires_at
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                session_id,
                username,
                now.isoformat(),
                now.isoformat(),
                expires_at.isoformat(),
            ),
        )
    return session_id


def delete_session(
    session_id,
    *,
    db_conn,
):
    if not session_id:
        return
    with db_conn() as conn:
        conn.execute(
            "DELETE FROM sessions WHERE id = ?",
            (session_id,),
        )


def current_session_user(
    session_id,
    *,
    db_conn,
    utcnow,
    session_touch_interval_seconds,
):
    if not session_id:
        return None

    with db_conn() as conn:
        row = conn.execute(
            "SELECT * FROM sessions WHERE id = ?",
            (session_id,),
        ).fetchone()
        if not row:
            return None

        now = utcnow()
        try:
            expires_at = datetime.fromisoformat(
                row["expires_at"]
            )
        except ValueError:
            conn.execute(
                "DELETE FROM sessions WHERE id = ?",
                (session_id,),
            )
            return None

        if expires_at <= now:
            conn.execute(
                "DELETE FROM sessions WHERE id = ?",
                (session_id,),
            )
            return None

        setting_row = conn.execute(
            "SELECT value FROM app_settings "
            "WHERE key = 'reduce_storage_writes'"
        ).fetchone()
        reduce_writes = (
            setting_bool(
                setting_row["value"],
                default=True,
            )
            if setting_row
            else True
        )
        touch_session = not reduce_writes

        if reduce_writes:
            try:
                last_seen_at = (
                    datetime.fromisoformat(
                        row["last_seen_at"]
                    )
                )
                if last_seen_at.tzinfo is None:
                    last_seen_at = (
                        last_seen_at.replace(
                            tzinfo=timezone.utc
                        )
                    )
                touch_session = (
                    now - last_seen_at
                    >= timedelta(
                        seconds=(
                            session_touch_interval_seconds
                        )
                    )
                )
            except (TypeError, ValueError):
                touch_session = True

        if touch_session:
            conn.execute(
                "UPDATE sessions "
                "SET last_seen_at = ? "
                "WHERE id = ?",
                (
                    now.isoformat(),
                    session_id,
                ),
            )
        return row["username"]


def init_db(
    *,
    db_conn,
    bootstrap_auth_from_env,
    ensure_stream_token,
    cleanup_expired_sessions,
):
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
                FOREIGN KEY(camera_id)
                    REFERENCES cameras(id)
                    ON DELETE CASCADE
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
                FOREIGN KEY(username)
                    REFERENCES users(username)
                    ON DELETE CASCADE
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
