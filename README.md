# PlainNVR

PlainNVR also includes `PlainNVRiPhone`, a small native companion app in
[`ios/PlainNVRiPhone`](ios/PlainNVRiPhone). The app signs in with the normal
PlainNVR account, plays live audio/video through the server's HLS endpoint,
browses recordings, and can save or share MP4 clips from iPhone. Live HLS audio
is boosted by default with `NVR_LIVE_AUDIO_GAIN=4.0` for quiet camera
microphones.

PlainNVR is a small RTSP recorder with a web UI for camera setup, schedules, continuous recording, retention cleanup, and simple timeline playback.

It is intentionally boring: FFmpeg copies camera video where it can instead of
re-encoding it. Use H.264 camera streams for the smoothest browser and iPhone
playback.

The Docker image bundles go2rtc as PlainNVR's primary live and restream layer.
Recording, snapshots, and live viewers can share one local RTSP restream instead
of opening a new connection to the camera for every consumer. The web viewer
uses go2rtc's MSE path for native frame rate, resolution, and low latency.

PlainNVR's existing FFmpeg HLS/MJPEG relay remains an automatic fallback when
go2rtc is unavailable, a camera has a separate audio-only URL, or a browser
cannot use the preferred stream.

Relay and recorder health is based on fresh media output, not only whether an
FFmpeg process still exists. If a camera or FFmpeg stalls without exiting,
PlainNVR discards the stale playlist, restarts the relay, and restarts dependent
recording/live workers against the new relay generation. The web and iPhone
players also reject frozen playback and retry instead of leaving the final frame
on screen indefinitely.

## Run Locally

```bash
NVR_DATA_DIR="$PWD/data" \
NVR_RECORDINGS_DIR="$PWD/recordings" \
NVR_STATIC_DIR="$PWD/static" \
python3 app/server.py
```

Open `http://localhost:8787`.

Running directly with Python still works without go2rtc and uses the FFmpeg
fallback. The Docker image includes the pinned go2rtc version used by PlainNVR.

On first launch, PlainNVR asks you to create a local admin account. The password
must be at least 12 characters.

You can also pre-create the first admin account with environment variables:

```bash
NVR_AUTH_USERNAME=admin \
NVR_AUTH_PASSWORD="use-a-long-unique-password" \
NVR_DATA_DIR="$PWD/data" \
NVR_RECORDINGS_DIR="$PWD/recordings" \
NVR_STATIC_DIR="$PWD/static" \
python3 app/server.py
```

## Run With Docker Compose

```bash
docker compose up --build
```

Open `http://localhost:8787`.

Compose also publishes `8554/tcp` for RTSP restreams and `8555/tcp+udp` for
WebRTC media. The go2rtc management API stays on container loopback and is only
available through PlainNVR's authenticated same-origin proxy.

If no account exists in `/data/nvr.sqlite3`, the first browser visit opens the
account setup screen. After that, the UI, API, playback files, and camera
management routes require login.

Additional accounts can be created from the Users panel after signing in. All
accounts currently have full PlainNVR access.

## TrueNAS Notes

See `DEPLOY-TRUENAS.md` for the two supported paths:

- build the image directly on TrueNAS and use `truenas-compose.yaml`
- publish to GitHub Container Registry and use `truenas-compose.registry.yaml`

Use the YAML files as the starting point for "Install via YAML". Replace:

```yaml
/mnt/YOUR_POOL/plainnvr/data
/mnt/YOUR_POOL/plainnvr/recordings
```

with real datasets on your TrueNAS box.

## Home Assistant

Each saved camera exposes two local HTTP endpoints for Home Assistant:

```text
http://PLAINNVR-HOST:8787/live/CAMERA_ID/stream.m3u8?fps=10&width=1280
http://PLAINNVR-HOST:8787/ha/CAMERA_ID/stream.mjpeg?fps=2&width=1280
http://PLAINNVR-HOST:8787/ha/CAMERA_ID/snapshot.jpg
```

For audio/video, try the HLS URL first in integrations or clients that accept
HLS. If an integration only accepts MJPEG, add the MJPEG IP Camera integration
and use the MJPEG URL plus the Still Image URL. MJPEG is video-only.

The PlainNVR camera editor shows the exact URLs after a camera is saved.

Those Home Assistant URLs include a generated stream token after login. Keep
that token private; it lets Home Assistant read the HLS, snapshot, and MJPEG bridge
without using your browser session cookie.

PlainNVR also accepts HTTP Basic auth on those bridge URLs, so the MJPEG IP
Camera integration can use your PlainNVR username and password instead of the
token if needed. The camera editor includes copy buttons for the full URLs and
YAML.

## Live View

PlainNVR also has a Live View panel for quick in-browser monitoring without Home
Assistant. With the Docker image, the web app prefers go2rtc MSE and falls back
through HLS and MJPEG. MSE sends fragmented MP4 directly over a WebSocket instead
of waiting for a multi-segment playlist, which makes PTZ monitoring feel much
closer to the camera's native response.

The iPhone app and Home Assistant HLS endpoint still use PlainNVR's supervised
HLS output, but that output reads from the local go2rtc restream when possible.
This reduces camera connections even where the client cannot use browser MSE.

Live HLS uses fragmented MP4 segments by default for iPhone-friendly playback.
Set `NVR_LIVE_HLS_SEGMENT_TYPE=mpegts` to return to classic `.ts` HLS segments.
Live playlists are tuned to start near the live edge by default: 1-second
segments, 4 listed segments, and a 1-second `EXT-X-START` offset. Tune those
with `NVR_LIVE_HLS_SEGMENT_SECONDS`, `NVR_LIVE_HLS_LIST_SIZE`,
`NVR_LIVE_HLS_DELETE_THRESHOLD`, and `NVR_LIVE_HLS_START_OFFSET_SECONDS` if a
camera needs more buffering or lower delay.
Some cameras need extra startup time before FFmpeg can identify the first video
frame and write the HLS playlist; tune `NVR_LIVE_HLS_READY_TIMEOUT_SECONDS`
from the default `25` seconds if the live view is still too impatient.
If an HLS worker is still running but stops updating its playlist, PlainNVR
restarts it after `NVR_LIVE_HLS_STALE_SECONDS` seconds.
PlainNVR uses a more patient RTSP probe for the internal relay so cameras that
expose audio a moment after video still record both tracks. The relay can be
tuned with `NVR_RELAY_HLS_SEGMENT_SECONDS`, `NVR_RELAY_HLS_LIST_SIZE`,
`NVR_RELAY_HLS_DELETE_THRESHOLD`, `NVR_RELAY_READY_TIMEOUT_SECONDS`, and
`NVR_RELAY_HLS_STALE_SECONDS`. RTSP reads time out after
`NVR_RTSP_READ_TIMEOUT_SECONDS` so a dead camera connection cannot hang forever.
Recorder output is also supervised with `NVR_RECORDER_START_GRACE_SECONDS` and
`NVR_RECORDER_STALE_SECONDS`.

The live viewer includes a Grayscale toggle. It applies only to the live HLS,
MJPEG, or snapshot output requested by that viewer; recordings stay as the
original camera stream.

## PTZ Control

Camera setup includes a PTZ checkbox beside Enabled and Audio. When PTZ is
enabled, the web live view and iPhone app show controls supported by the
selected driver.

PTZ zoom is configured separately from pan/tilt. Auto mode uses hardware zoom
for normal PTZ drivers and digital viewer zoom for the Victure direct-stepper
driver; set Zoom to Digital, Hardware, or None when a camera needs a specific
behavior. Digital zoom only changes the local viewer and never sends a camera
zoom command.

PlainNVR sends PTZ commands from the server. Use **Discover ONVIF** in the camera
editor to query device services, media profiles, stream URIs, PTZ configuration,
supported movement spaces, home position, and presets. The selected ONVIF
service and profile token are cached with the camera, and both the web and
iPhone controls only show capabilities the camera advertised.

ONVIF movement uses press-and-hold continuous movement with STOP on release.
Click movement remains available for vendor drivers that only support discrete
steps. For odd cameras, Control URL and Profile token remain available as manual
fallbacks. Username/password credentials can be embedded in the stream or ONVIF
URL when a camera requires WS-Security, for example
`http://user:password@camera-ip:8080/onvif/device_service`.

Each saved camera can download a redacted compatibility report containing its
stream probe, device/firmware identity, discovered profiles, individual PTZ
features, go2rtc state, recorder health, and recommendations. See
[`docs/CAMERA-COMPATIBILITY.md`](docs/CAMERA-COMPATIBILITY.md) for the publishing
matrix and test procedure.

For the local Victure/Alloca firmware build with the direct stepper helper,
choose the `Victure Direct Stepper` driver. Leave Control URL blank to use the
RTSP host with admin port `8088`, or set `http://192.168.1.135:8088`. The
legacy `Victure DVRIP` driver is kept for older experiments, but the direct
stepper driver is the one that avoids the vendor homing behavior.

Those Victure drivers also expose a Camera Clock section in the camera editor.
Use Read to inspect the camera's overlay clock, Now to fill the browser's local
time, and Set to send and verify it over DVRIP.

## Camera URL Examples

Common RTSP shapes look like:

```text
rtsp://user:password@192.168.1.50:554/Streaming/Channels/101
rtsp://user:password@192.168.1.50:554/h264Preview_01_main
rtsp://user:password@192.168.1.50:554/cam/realmonitor?channel=1&subtype=0
```

The exact path depends on the camera brand.

Most cameras send video and audio in the same RTSP stream. Leave the Audio URL
field empty for those cameras; PlainNVR will record audio from the main stream
when Audio is enabled. If a camera exposes audio separately, put the video
stream in Stream URL and the audio-only stream in Audio URL.

## Storage Estimate

Use:

```text
GB per day = camera bitrate in Mbps * 10.8
```

Four cameras at 4 Mbps each need about 173 GB per day, before filesystem overhead.

## Current Limits

- Playback is per segment, not a scrubby merged timeline yet.
- H.265 may record fine but may not play in every browser.
- WebRTC requires reachable port `8555` and suitable ICE candidates; MSE is the
  default low-latency web path.
- Cameras with a separate audio URL use the FFmpeg relay until multi-source
  go2rtc composition is configured.
- Recordings are timestamped MP4 chunks under each camera folder.
- The Playback panel shows one selected date at a time, plus a recording
  coverage summary with the oldest/newest segment and available dates.
- Deleting a camera leaves existing recordings on disk.

## Upstream Components

- go2rtc `v1.9.13` provides restreaming and the vendored MIT-licensed browser
  player under `static/vendor/go2rtc`.
- Frigate's public ONVIF probe, capability-driven PTZ UI, and live-view
  architecture were used as behavioral references. PlainNVR's server discovery
  and integration code is independently implemented for this smaller codebase.
