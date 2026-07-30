# PlainNVR

PlainNVR is a self-hosted network video recorder for RTSP cameras. It provides
a web interface for camera setup, continuous or scheduled recording, retention
cleanup, live monitoring, recording playback, ONVIF discovery, and PTZ control.

The recorder copies camera video whenever possible instead of re-encoding it.
H.264 camera streams provide the broadest compatibility with browsers, iPhone,
Home Assistant, and the bundled go2rtc live-view layer.

## Features

- Continuous or weekly scheduled recording
- Configurable segment length and retention per camera
- Low-latency web live view through go2rtc MSE/HLS
- ONVIF service, profile, stream, and PTZ capability discovery
- Press-and-hold ONVIF movement, home position, hardware zoom, and presets
- Downloadable redacted camera compatibility reports
- Optional Home Assistant HLS and snapshot bridge
- Native SwiftUI companion app for iPhone
- Recorder, go2rtc, and frozen-stream health monitoring

> PlainNVR is free and open source. If it has been useful to you, you can
> [support continued development on Buy Me a Coffee](https://buymeacoffee.com/endlessdev). ☕

## Quick Start With Docker

Docker Engine and the Docker Compose plugin are the recommended installation
method.

```bash
git clone https://github.com/endless1233214/plainnvr.git
cd plainnvr
docker compose up --build -d
```

Open `http://localhost:8787`. The first visit opens account setup. Create the
local administrator account with a password of at least 12 characters.

PlainNVR serves plain HTTP by default. Include the full `http://` address when
opening it from another computer, for example `http://192.168.1.50:8787`.
If Brave or Chrome shows `ERR_SSL_PROTOCOL_ERROR`, the browser upgraded the
address to HTTPS. Allow HTTP for the local address or turn off **Always use
secure connections** for local access. Use `https://` only after placing
PlainNVR behind an HTTPS reverse proxy.

The default Compose configuration stores persistent files in:

```text
./data
./recordings
```

It publishes these ports:

| Port | Purpose |
| --- | --- |
| `8787/tcp` | PlainNVR web interface and API |
| `8554/tcp` | go2rtc RTSP restreams |
| `8555/tcp` and `8555/udp` | go2rtc WebRTC media |

The go2rtc management API on port `1984` is not published. PlainNVR exposes only
the required media endpoints through its authenticated same-origin proxy.

## Add The First Camera

1. Open the **Cameras** panel and select **New**.
2. Enter a descriptive name and the camera's main RTSP URL.
3. Select **Test Stream** and confirm that the probe detects the expected
   codecs.
4. Choose the segment length, retention period, RTSP transport, and view
   rotation.
5. Leave **Enabled** selected to start the recorder after saving. Select
   **Audio** when audio should be recorded.
6. Use **Always** for continuous recording or configure a weekly schedule.
7. Select **Save Camera**.

Common RTSP URL shapes include:

```text
rtsp://USERNAME:PASSWORD@CAMERA-HOST:554/Streaming/Channels/101
rtsp://USERNAME:PASSWORD@CAMERA-HOST:554/h264Preview_01_main
rtsp://USERNAME:PASSWORD@CAMERA-HOST:554/cam/realmonitor?channel=1&subtype=0
```

The path varies by manufacturer and firmware. PlainNVR's go2rtc-only restream
path expects audio to be present on the main camera stream.

## Run Directly With Python

Direct execution requires Python 3 and FFmpeg/FFprobe in `PATH`.

```bash
NVR_DATA_DIR="$PWD/data" \
NVR_RECORDINGS_DIR="$PWD/recordings" \
NVR_STATIC_DIR="$PWD/static" \
python3 app/server.py
```

Open `http://localhost:8787`.

The Docker image includes the pinned go2rtc version used by the project. Direct
Python runs also need a `go2rtc` binary in `PATH` for live viewing and
restream-based recording.

The initial administrator can also be created non-interactively:

```bash
NVR_AUTH_USERNAME=admin \
NVR_AUTH_PASSWORD="use-a-long-unique-password" \
NVR_DATA_DIR="$PWD/data" \
NVR_RECORDINGS_DIR="$PWD/recordings" \
NVR_STATIC_DIR="$PWD/static" \
python3 app/server.py
```

Additional accounts can be created from the **Users** panel. All accounts
currently have full PlainNVR access.

## TrueNAS

The recommended TrueNAS deployment pulls the public image:

PlainNVR is now a community app. You can install the app on TrueNAS simply by searching for it under Discover Apps.

## Live Streaming

The Docker image uses go2rtc as the live and restream layer. Recording,
snapshots, and live viewers can share a local RTSP restream instead of opening a
separate connection to the camera for every consumer.

The web viewer prefers go2rtc MSE for native frame rate, source resolution, and
low latency, with go2rtc HLS for clients that need an HLS URL.

The iPhone app and optional Home Assistant bridge use the go2rtc-backed HLS
endpoint at `/live/<camera_id>/stream.m3u8`.

PlainNVR checks for fresh media output rather than only checking whether a
process exists. A stalled go2rtc restream, recorder, or viewer is restarted
instead of leaving a frozen final frame.

### Live Stream Tuning

go2rtc and recorder supervision can be tuned with:

- `NVR_GO2RTC_WEBRTC_CANDIDATES`
- `NVR_RTSP_READ_TIMEOUT_SECONDS`
- `NVR_RECORDER_START_GRACE_SECONDS`
- `NVR_RECORDER_STALE_SECONDS`

## ONVIF And PTZ

Enable **PTZ** in the camera editor and select **ONVIF** for standards-based
control. **Discover ONVIF** queries the camera for:

- Device, media, and PTZ service endpoints
- Manufacturer, model, and firmware identity
- Media profiles and stream URIs
- PTZ configuration and movement spaces
- Pan, tilt, and zoom capabilities
- Home position and presets

Selecting a discovered profile stores its service endpoint and profile token
with the camera. The web and iPhone controls then display only the capabilities
reported by that camera.

ONVIF movement uses continuous press-and-hold commands and sends STOP when the
control is released. Manual **Control URL** and **Profile / Hash** fields remain
available for devices with incomplete discovery. Credentials may be included in
the ONVIF URL when WS-Security is required:

```text
http://USERNAME:PASSWORD@CAMERA-HOST:8080/onvif/device_service
```

PTZ zoom is configured separately from pan and tilt:

| Setting | Behavior |
| --- | --- |
| `Auto` | Hardware zoom for standard PTZ drivers; digital zoom for the direct-stepper driver |
| `Digital` | Changes only the local viewer |
| `Hardware` | Sends zoom commands to the camera |
| `None` | Hides zoom controls |

### Vendor-Specific Drivers

Vendor drivers are explicit compatibility fallbacks, not general camera
profiles.

- **Victure Direct Stepper** supports compatible Victure/Alloca firmware that
  exposes the direct stepper helper. When **Control URL** is empty, PlainNVR
  derives the camera host from the RTSP URL and uses port `8088`. An explicit
  value can use `http://CAMERA-HOST:8088`.
- **Victure DVRIP** supports compatible legacy DVRIP firmware.

These drivers expose the **Camera Clock** controls when the firmware supports
them. **Read** retrieves the overlay clock, **Now** fills the local browser time,
and **Set** writes and verifies the selected time.

Each saved camera can download a redacted compatibility report containing its
stream probe, firmware identity, discovered profiles, individual PTZ features,
go2rtc state, recorder health, and recommendations. See
[`docs/CAMERA-COMPATIBILITY.md`](docs/CAMERA-COMPATIBILITY.md) for the support
levels and verification procedure.

## Home Assistant

The Home Assistant bridge is optional. Enable **Home Assistant** in **Server
Settings** before using the generated camera URLs.

Enabled cameras expose a go2rtc-backed HLS stream and snapshot endpoint:

```text
http://PLAINNVR-HOST:8787/live/CAMERA_ID/stream.m3u8
http://PLAINNVR-HOST:8787/ha/CAMERA_ID/snapshot.jpg
```

Use Home Assistant's Generic Camera integration with `stream_source` set to the
HLS URL and `still_image_url` set to the snapshot URL.

After a camera is saved, its editor displays complete URLs and example YAML.
Generated URLs include a private stream token so Home Assistant can read media
without a browser session. The bridge endpoints also accept HTTP Basic
authentication when an integration requires a username and password.

## iPhone Companion App

[`ios/PlainNVRiPhone`](ios/PlainNVRiPhone) contains the source-distributed
SwiftUI companion app. It supports authenticated server access, go2rtc HLS live
viewing, capability-aware PTZ controls, recorder controls, recording
browsing, and MP4 sharing or saving.

See the [iPhone app README](ios/PlainNVRiPhone/README.md) for Xcode installation
and server requirements.

## Storage Estimate

Use this estimate for continuously recorded camera video:

```text
GB per day = camera bitrate in Mbps * 10.8
```

Four cameras at 4 Mbps each require approximately 173 GB per day before
filesystem overhead.

## Current Limits

- Playback is per recording segment rather than a merged scrub timeline.
- H.265 can record successfully but does not play in every browser.
- WebRTC requires reachable port `8555` and suitable ICE candidates; MSE is the
  default low-latency web path.
- Separate audio-only URLs are not supported in the go2rtc-only restream path.
- Recordings are timestamped MP4 files stored under each camera directory.
- The playback panel displays one date at a time with recording coverage and
  available-date summaries.
- Deleting a camera does not delete its existing recordings.

## Upstream Components

- go2rtc `v1.9.13` provides restreaming and the vendored MIT-licensed browser
  player under `static/vendor/go2rtc`.
- Frigate's public ONVIF probe, capability-driven PTZ interface, and live-view
  architecture served as behavioral references. PlainNVR's discovery and
  integration code is independently implemented for this smaller codebase.
