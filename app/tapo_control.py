import ipaddress
import json
import os
import subprocess
import threading
from urllib.parse import unquote, urlparse


TAPO_CONTROLS = frozenset(
    {
        "spotlight",
        "spotlight_intensity",
        "privacy",
        "led",
        "night_vision",
        "siren",
        "microphone_volume",
        "speaker_volume",
        "reboot",
    }
)
MAX_HELPER_OUTPUT = 2 << 20


class TapoControlError(RuntimeError):
    pass


_locks_guard = threading.Lock()
_camera_locks = {}


def _camera_lock(camera_id):
    key = str(camera_id or "")
    with _locks_guard:
        lock = _camera_locks.get(key)
        if lock is None:
            lock = threading.Lock()
            _camera_locks[key] = lock
        return lock


def _allowed_camera_ip(value):
    try:
        address = ipaddress.ip_address(str(value or "").strip())
    except ValueError as exc:
        raise ValueError(
            "Tapo control host must be an IP address."
        ) from exc
    allowed = (
        address.is_private
        or address.is_loopback
        or address.is_link_local
    )
    if (
        not allowed
        or address.is_multicast
        or address.is_unspecified
    ):
        raise ValueError(
            "Tapo control host must be a local IP address."
        )
    return str(address)


def _stream_credentials(camera):
    parsed = urlparse(
        str(camera.get("rtsp_url") or "")
    )
    return (
        unquote(parsed.username or ""),
        unquote(parsed.password or ""),
        parsed.hostname or "",
    )


def control_request(camera, operation, control=None, value=None):
    if not camera.get("tapo_enabled"):
        raise ValueError(
            "Local Tapo controls are not enabled for this camera."
        )

    stream_username, stream_password, stream_host = (
        _stream_credentials(camera)
    )
    host = _allowed_camera_ip(
        camera.get("tapo_host") or stream_host
    )
    username = str(
        camera.get("tapo_username")
        or stream_username
        or "admin"
    ).strip()
    password = str(
        camera.get("tapo_password")
        or stream_password
        or ""
    )
    if not password:
        raise ValueError(
            "A Tapo control password is required."
        )
    if len(username) > 320 or len(password) > 1024:
        raise ValueError(
            "Tapo control credentials are too long."
        )
    if operation not in ("probe", "state", "set"):
        raise ValueError("Unsupported Tapo operation.")
    if operation == "set" and control not in TAPO_CONTROLS:
        raise ValueError("Unsupported Tapo control.")

    request = {
        "host": host,
        "username": username,
        "password": password,
        "operation": operation,
    }
    if operation == "set":
        request["control"] = control
        request["value"] = value

    binary = os.environ.get(
        "TAPOCTL_BIN",
        "/usr/local/bin/plainnvr-tapoctl",
    )
    try:
        with _camera_lock(camera.get("id")):
            result = subprocess.run(
                [binary],
                input=json.dumps(
                    request,
                    separators=(",", ":"),
                ).encode("utf-8"),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=15,
                check=False,
            )
    except FileNotFoundError as exc:
        raise TapoControlError(
            "The local Tapo control helper is not installed."
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise TapoControlError(
            "The camera control request timed out."
        ) from exc

    if (
        len(result.stdout) > MAX_HELPER_OUTPUT
        or len(result.stderr) > MAX_HELPER_OUTPUT
    ):
        raise TapoControlError(
            "The camera control helper returned too much data."
        )
    try:
        response = json.loads(
            result.stdout.decode("utf-8")
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TapoControlError(
            "The camera control helper returned an invalid response."
        ) from exc
    if not isinstance(response, dict):
        raise TapoControlError(
            "The camera control helper returned an invalid response."
        )
    if result.returncode != 0 or not response.get("ok"):
        message = str(
            response.get("error")
            or "The camera rejected the control request."
        )
        for secret in (username, password):
            if secret:
                message = message.replace(
                    secret,
                    "<redacted>",
                )
        raise TapoControlError(message[:500])
    return response
