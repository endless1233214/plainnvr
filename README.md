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
- `NVR_GO2RTC_WEBRTC_NETWORKS` (default `udp4,tcp4`; use `udp4,tcp4,udp6,tcp6` for a verified dual-stack deployment)
- `NVR_RTSP_READ_TIMEOUT_SECONDS`
- `NVR_RECORDER_START_GRACE_SECONDS`
- `NVR_RECORDER_STALE_SECONDS`

WebRTC defaults to IPv4. Older go2rtc 1.9.13 builds could abort their WebRTC module
when binding an IPv6 link-local address inside a Docker/TrueNAS container.
PlainNVR 0.1.3 upgrades to go2rtc 1.9.14, which also fixes listener initialization.
The web server could remain healthy in that state while native clients received
no WebRTC signaling answer. When using published container ports, also set
`NVR_GO2RTC_WEBRTC_CANDIDATES` to a reachable server address and media port
(for example, `192.0.2.1:8555`), and publish that port for both TCP and UDP.

## ONVIF And PTZ

**Discover ONVIF** works for fixed cameras as well as PTZ models. PlainNVR
derives common device endpoints from the RTSP host, including port `2020` used
by Tapo Profile-S cameras. The optional **ONVIF Device URL** overrides discovery
without implying that the camera can move. Discovery queries:

- Device, media, imaging, events, and advertised PTZ service endpoints
- Manufacturer, model, and firmware identity
- Media profiles, stream URIs, video, and audio encodings
- PTZ configuration and movement spaces, when present
- Pan, tilt, and zoom capabilities
- Home position and presets

Selecting a discovered stream updates the camera RTSP URL. Fixed ONVIF cameras
remain fully supported for media discovery while PTZ stays disabled. The web
and iPhone controls display only capabilities reported by the camera.

ONVIF movement uses continuous press-and-hold commands and sends STOP when the
control is released. Manual **Control URL** and **Profile / Hash** fields remain
available for movable devices with incomplete discovery. Credentials may be
included in the ONVIF Device URL when WS-Security is required:

```text
http://USERNAME:PASSWORD@CAMERA-HOST:2020/onvif/device_service
```

ONVIF Profile S does not by itself guarantee spotlight, siren, or two-way-talk
control. PlainNVR does not advertise those controls unless a future integration
can identify a standard relay/output or an explicit vendor API. Camera microphone
audio contained in the RTSP stream is supported for live view and recording.

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

## Support Development

PlainNVR is free and open source. Support helps cover testing hardware, hosting,
Apple developer fees for the companion app, and continued development.

[Support EndlessDev on Buy Me a Coffee](https://buymeacoffee.com/endlessdev)

## Upstream Components

- go2rtc `v1.9.14` provides restreaming and the vendored MIT-licensed browser
  player under `static/vendor/go2rtc`.
- Frigate's public ONVIF probe, capability-driven PTZ interface, and live-view
  architecture served as behavioral references. PlainNVR's discovery and
  integration code is independently implemented for this smaller codebase.

## Server security and deployment

The go2rtc management API and RTSP relay bind to localhost by default. Native
and browser playback use authenticated PlainNVR routes; only the WebRTC media
port needs external TCP/UDP access. Publishing the RTSP container port alone
no longer exposes the relay. An administrator can explicitly set
`NVR_GO2RTC_RTSP_HOST=0.0.0.0` for trusted-network RTSP integrations, but that
relay has no authentication: restrict access with the network firewall.
Keep `NVR_GO2RTC_API_HOST` on localhost.

Treat every PlainNVR account as an administrator. Camera credentials are stored
in the data volume; restrict filesystem access and protect backups. For remote
access, use HTTPS through a trusted reverse proxy or a VPN; direct HTTP sends
login credentials and session cookies without transport encryption. Do not
expose an unconfigured instance: first-run setup creates the administrator.

Mutations accept JSON objects up to 1 MiB, reject foreign browser origins, and
login/setup attempts are limited to 20 per minute per network peer. Behind a
reverse proxy, users share that limit unless the proxy connects from different
addresses. Playback WebSockets accept configured camera IDs only. The HLS
proxy exposes only fixed playlist and segment routes.

The release image runs as UID/GID 568 by default; mounted data and recording
folders must be writable by the configured user. New files are private to that
user. HTTP connections are capped at 128 and slow requests time out after 30
seconds. Failed Basic streaming logins also have a per-peer limit; successful
stream requests do not consume it.

Version 0.1.3 uses Python 3.14, Alpine 3.24, source-built go2rtc with updated Go
dependencies, and FFmpeg 9.0.2 with a MOV bounds-check patch. The FFmpeg build
supports camera playback/probing, video-copy MP4 recording with AAC audio,
snapshots and night sampling. It excludes unrelated subtitle/game codecs,
DASH/XML, device capture and hardware acceleration. See the
[release audit](docs/RELEASE-0.1.3-AUDIT.md) for scan scope, compatibility and
verification, and [third-party notices](THIRD_PARTY_NOTICES.md) for source details.
