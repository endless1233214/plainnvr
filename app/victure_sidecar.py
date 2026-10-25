"""Optional, authenticated connection to the separately installed Victure driver.

The recorder never silently falls back to in-process camera control when an
external driver has been configured: a broken driver must be visible to the
operator, not bypass the requested isolation boundary.
"""

import json
import os
import ipaddress
from urllib import error, request
from urllib.parse import urlparse


CAMERA_FIELDS = ("rtsp_url", "ptz_url", "ptz_profile_token", "time_sync_supported")


def configured():
    return bool(os.environ.get("NVR_VICTURE_DRIVER_URL", "").strip())


def call(operation, camera, **parameters):
    base_url = os.environ.get("NVR_VICTURE_DRIVER_URL", "").strip().rstrip("/")
    parsed = urlparse(base_url)
    if (parsed.scheme != "http" or not parsed.hostname or parsed.username or parsed.password
            or parsed.path or parsed.query or parsed.fragment):
        raise RuntimeError("Invalid Victure driver URL configuration.")
    host = parsed.hostname
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        if host != "localhost" and ("." in host or ":" in host):
            raise RuntimeError("Victure driver URL must use a private host.") from None
    else:
        if not (address.is_private or address.is_loopback):
            raise RuntimeError("Victure driver URL must use a private host.")

    token_file = os.environ.get("NVR_VICTURE_DRIVER_TOKEN_FILE", "").strip()
    if not token_file:
        raise RuntimeError("Victure driver token file is not configured.")
    with open(token_file, "r", encoding="utf-8") as handle:
        token = handle.read(257).strip()
    if not token or len(token) > 256:
        raise RuntimeError("Victure driver token file is invalid.")

    body = {"mode": camera.get("ptz_type"), "camera": {
        field: camera.get(field) for field in CAMERA_FIELDS
    }}
    body.update(parameters)
    payload = json.dumps(body, separators=(",", ":")).encode("utf-8")
    if len(payload) > 16384:
        raise ValueError("Victure driver request is too large.")
    outgoing = request.Request(
        f"{base_url}/v1/{operation}", data=payload, method="POST",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    try:
        with request.urlopen(outgoing, timeout=8) as response:
            result = json.loads(response.read(16385))
    except (error.URLError, TimeoutError, OSError, ValueError) as exc:
        raise RuntimeError("Victure driver is unavailable or returned an invalid response.") from exc
    if not isinstance(result, dict) or not result.get("ok"):
        raise RuntimeError("Victure driver rejected the request.")
    return result
