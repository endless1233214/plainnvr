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

PlainNVR runs an internal relay for each enabled camera. The relay pulls the
camera once, merges the optional secondary audio stream, and exposes a local HLS
source that recording, browser live view, iPhone live view, snapshots, and Home
Assistant can share. This keeps small camera nodes from serving a new RTSP reader
for every viewer.

## Run Locally

```bash
NVR_DATA_DIR="$PWD/data" \
NVR_RECORDINGS_DIR="$PWD/recordings" \
NVR_STATIC_DIR="$PWD/static" \
python3 app/server.py
```

Open `http://localhost:8787`.

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
Assistant. HLS mode uses the same live audio/video path as the iPhone app when
the browser supports native HLS, while MJPEG mode stays available as a
video-only fallback.

Live HLS uses fragmented MP4 segments by default for iPhone-friendly playback.
Set `NVR_LIVE_HLS_SEGMENT_TYPE=mpegts` to return to classic `.ts` HLS segments.
Some cameras need extra startup time before FFmpeg can identify the first video
frame and write the HLS playlist; tune `NVR_LIVE_HLS_READY_TIMEOUT_SECONDS`
from the default `25` seconds if the live view is still too impatient.
If an HLS worker is still running but stops updating its playlist, PlainNVR
restarts it after `NVR_LIVE_HLS_STALE_SECONDS` seconds.
PlainNVR uses a more patient RTSP probe for the internal relay so cameras that
expose audio a moment after video still record both tracks. The relay can be
tuned with `NVR_RELAY_HLS_SEGMENT_SECONDS`, `NVR_RELAY_HLS_LIST_SIZE`,
`NVR_RELAY_HLS_DELETE_THRESHOLD`, and `NVR_RELAY_READY_TIMEOUT_SECONDS`.

The live viewer includes a Grayscale toggle. It applies only to the live HLS,
MJPEG, or snapshot output requested by that viewer; recordings stay as the
original camera stream.

## PTZ Control

Camera setup includes a PTZ checkbox beside Enabled and Audio. When PTZ is
enabled, the web live view and iPhone app show pan, tilt, home, stop, and zoom
controls for that camera.

PlainNVR sends ONVIF PTZ commands from the server. If ONVIF URL is blank, it
tries common local ONVIF endpoints on the camera host from the stream URL. For
odd cameras, set the ONVIF URL and Profile token in the camera editor.
Username/password credentials can be embedded in the ONVIF URL when a camera
requires WS-Security, for example
`http://user:password@camera-ip:8080/onvif/device_service`.

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
- Recordings are timestamped MP4 chunks under each camera folder.
- The Playback panel shows one selected date at a time, plus a recording
  coverage summary with the oldest/newest segment and available dates.
- Deleting a camera leaves existing recordings on disk.
