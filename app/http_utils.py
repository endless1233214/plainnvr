import json


MAX_JSON_BODY_BYTES = 1024 * 1024


def parse_json_body(handler):
    if handler.headers.get("Transfer-Encoding"):
        raise ValueError("Transfer-Encoding is not supported.")
    length = int(handler.headers.get("Content-Length", "0") or "0")
    if length < 0 or length > MAX_JSON_BODY_BYTES:
        raise ValueError("JSON body must be at most 1 MiB.")
    if length == 0:
        return {}
    if handler.headers.get("Content-Type", "").split(";", 1)[0].strip().lower() != "application/json":
        raise ValueError("Content-Type must be application/json.")
    raw = handler.rfile.read(length)
    if len(raw) != length:
        raise ValueError("Incomplete JSON body.")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Invalid JSON body.") from exc
    if not isinstance(payload, dict):
        raise ValueError("JSON body must be an object.")
    return payload


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
