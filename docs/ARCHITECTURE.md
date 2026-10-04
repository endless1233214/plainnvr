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
- `tapo_control.py` — validated invocation of the local Tapo control helper
- app event ingestion — narrow token-authenticated boundary for optional
  detection apps and camera-driver sidecars
- `diagnostics.py` — stream probing and compatibility reports
- `http_auth.py` / `http_utils.py` — HTTP auth and request parsing
- `http_api.py` — API, HLS, media, and proxy route implementations
- `http_handler.py` — request-handler facade
- `http_server.py` — connection-bounded HTTP server

`build/tapoctl` contains the dependency-free Go helper for Tapo camera-local
authentication and the strictly allowlisted device controls. Credentials cross
the Python/Go boundary only through stdin. The helper validates that its target
is a literal local IP and pins every HTTPS connection to that address.

Optional apps and drivers are cataloged in the separate `plainnvr-os-apps`
repository. They run as sidecars and communicate through typed APIs: apps
consume explicitly exposed go2rtc restreams and submit detection events to
`/api/apps/events`; drivers expose vendor-specific capabilities without becoming
imports in the recorder process. `NVR_APP_TOKEN` is a separate bearer
credential for that boundary and is disabled when unset.

When changing behavior, keep the compatibility functions in `server.py`
unless the existing tests and callers are updated in the same change. The goal
is for `server.py` to stay orchestration-focused instead of becoming a
monolith again.
