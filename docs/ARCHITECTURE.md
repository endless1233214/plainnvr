# PlainNVR server layout

`app/server.py` is the composition root and compatibility facade. It owns
runtime configuration, wires the services together, and keeps the existing
`server.*` names used by tests and older callers.

The implementation is split by responsibility:

- `auth.py` — password hashing and credential validation
- `common.py` — small shared helpers
- `schedule.py` — weekly recording schedules
- `persistence.py` — SQLite schema, users, sessions, and server settings
- `cameras.py` — camera validation, persistence, and recording paths
- `media_relay.py` — go2rtc process, stream registration, and health
- `media_commands.py` — FFmpeg/RTSP command construction
- `recording.py` — recorder supervision, retention, and segment metadata
- `night_mode.py` — automatic grayscale/night detection
- `onvif_client.py` — ONVIF discovery and SOAP helpers
- `ptz.py` — ONVIF, DVRIP, and Victure camera control
- `diagnostics.py` — stream probing and compatibility reports
- `http_auth.py` / `http_utils.py` — HTTP auth and request parsing
- `http_api.py` — API, HLS, media, and proxy route implementations
- `http_handler.py` — request-handler facade
- `http_server.py` — connection-bounded HTTP server

When changing behavior, keep the compatibility functions in `server.py`
unless the existing tests and callers are updated in the same change. The goal
is for `server.py` to stay orchestration-focused instead of becoming a
monolith again.
