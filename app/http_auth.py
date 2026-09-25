import base64
import hmac
import threading
import time
from urllib.parse import parse_qs


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
        decoded = base64.b64decode(
            token,
            validate=True,
        ).decode("utf-8")
    except (
        ValueError,
        UnicodeDecodeError,
    ):
        return None, None
    username, separator, password = decoded.partition(":")
    if not separator:
        return None, None
    return username, password


def valid_stream_auth(
    handler,
    parsed,
    *,
    get_stream_token,
    authenticate_user,
    basic_failure_limiter,
):
    expected = get_stream_token()
    query = parse_qs(parsed.query)
    provided = (
        query.get("token", [""])[0]
        or bearer_token(handler.headers)
    )
    if (
        expected
        and provided
        and hmac.compare_digest(
            provided.encode("utf-8"),
            expected.encode("utf-8"),
        )
    ):
        return True

    username, password = basic_auth_credentials(
        handler.headers
    )
    if not username:
        return False

    peer = handler.client_address[0]
    if basic_failure_limiter.blocked(peer):
        return False

    authenticated = bool(
        authenticate_user(
            username,
            password,
        )
    )
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
            started, count = self.attempts.get(
                peer,
                (0, 0),
            )
            return (
                count >= 20
                and time.monotonic() - started < 60
            )

    def allow(self, peer):
        now = time.monotonic()
        with self.lock:
            self.attempts = {
                key: entry
                for key, entry in self.attempts.items()
                if now - entry[0] < 60
            }
            started, count = self.attempts.get(
                peer,
                (now, 0),
            )
            if (
                count >= 20
                or (
                    peer not in self.attempts
                    and len(self.attempts) >= 4096
                )
            ):
                return False
            self.attempts[peer] = (
                started,
                count + 1,
            )
            return True
