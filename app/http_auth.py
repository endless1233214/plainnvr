import base64
import hmac
import threading
import time


def parse_cookie_header(value):
    cookies = {}
    for part in str(value or "").split(";"):
        if "=" not in part:
            continue
        key, item = part.split("=", 1)
        cookies[key.strip()] = item.strip()
    return cookies


def bearer_token(headers):
    value = str(
        headers.get("Authorization") or ""
    )
    if not value.lower().startswith("bearer "):
        return ""
    return value.split(" ", 1)[1].strip()


def basic_auth_credentials(headers):
    value = str(
        headers.get("Authorization") or ""
    )
    if not value.lower().startswith("basic "):
        return None
    try:
        decoded = base64.b64decode(
            value.split(" ", 1)[1],
            validate=True,
        ).decode("utf-8")
    except (
        ValueError,
        UnicodeDecodeError,
    ):
        return None
    if ":" not in decoded:
        return None
    return tuple(decoded.split(":", 1))


def valid_stream_auth(
    headers,
    stream_token,
    *,
    authenticate_user,
):
    token = bearer_token(headers)
    if token and hmac.compare_digest(
        token, stream_token
    ):
        return True

    credentials = basic_auth_credentials(
        headers
    )
    if not credentials:
        return False

    username, password = credentials
    return bool(
        authenticate_user(
            username,
            password,
        )
    )


class LoginLimiter:
    def __init__(
        self,
        *,
        limit=20,
        window_seconds=60,
    ):
        self.limit = limit
        self.window_seconds = window_seconds
        self.lock = threading.Lock()
        self.failures = {}

    def allow(self, peer):
        now = time.monotonic()
        with self.lock:
            values = [
                item
                for item in self.failures.get(
                    peer, []
                )
                if now - item
                < self.window_seconds
            ]
            if len(values) >= self.limit:
                self.failures[peer] = values
                return False
            values.append(now)
            self.failures[peer] = values
            return True

    def clear(self, peer):
        with self.lock:
            self.failures.pop(peer, None)
