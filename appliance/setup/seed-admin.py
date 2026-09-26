#!/usr/bin/python3
"""Initialize the ordinary PlainNVR schema as the plainnvr service account."""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, '/opt/plainnvr/current')
from app import persistence

data = Path(sys.argv[1])
admin = json.load(sys.stdin)
now = lambda: datetime.now(timezone.utc).isoformat()
connection = lambda: persistence.db_conn(data, data / 'nvr.sqlite3')
persistence.init_db(
    db_conn=connection,
    bootstrap_auth_from_env=lambda conn: None,
    ensure_stream_token=lambda conn: persistence.ensure_stream_token(conn, stream_token_override='', iso_now=now),
    cleanup_expired_sessions=lambda conn: persistence.cleanup_expired_sessions(conn, iso_now=now),
)
with connection() as conn:
    conn.execute('BEGIN IMMEDIATE')
    rows = conn.execute('SELECT username, password_hash FROM users').fetchall()
    if rows:
        if len(rows) != 1 or rows[0]['username'] != admin['username'] or rows[0]['password_hash'] != admin['hash']:
            raise RuntimeError('The selected data directory already contains another account.')
    else:
        conn.execute('INSERT INTO users (username,password_hash,created_at,updated_at) VALUES (?,?,?,?)',
                     (admin['username'], admin['hash'], now(), now()))
