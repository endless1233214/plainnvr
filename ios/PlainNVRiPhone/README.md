# PlainNVR iPhone

PlainNVR iPhone is a native SwiftUI companion app distributed as source in this
repository. Xcode installs the app on a supported iPhone, and the app connects
directly to a PlainNVR server over a local network, VPN, or other private
connection.

## Features

- Sign in with an existing PlainNVR account
- View camera status, recorder state, disk usage, and recorder events
- Play go2rtc-backed HLS live video
- Restart or pause a selected live stream
- Use capability-aware PTZ controls, press-and-hold ONVIF movement, home
  position, hardware or digital zoom, and discovered presets
- Rotate to landscape for a full-screen live view
- Pinch and drag live video for local inspection
- Start, pause, or restart an individual camera recorder
- Browse recording dates and MP4 segments
- Play, share, or save recording clips to Photos

## Requirements

- A running PlainNVR server reachable from the iPhone
- A current Xcode installation with the required iOS platform
- An Apple account selected as the project's signing team
- Camera streams configured in the PlainNVR web interface

## Install With Xcode

1. Open `PlainNVRiPhone.xcodeproj` in Xcode.
2. Select the `PlainNVRiPhone` target.
3. Open **Signing & Capabilities** and select an Apple development team.
4. Connect a supported iPhone and select it as the run destination.
5. Select **Run**.
6. Enter the PlainNVR server address, such as
   `http://PLAINNVR-HOST:8787`, and sign in.

If Xcode reports that the iOS platform is missing, install the matching platform
from **Xcode Settings > Components**, then reopen the project.

## Server API

The app uses PlainNVR's session-cookie authentication and these primary
endpoints:

- `GET /api/status` for cameras, recorder state, disk usage, events, and the
  stream token
- `GET /api/coverage?camera_id=<id>` for recording dates and storage totals
- `GET /api/segments?camera_id=<id>&date=<yyyy-mm-dd>` for MP4 segment metadata
- `POST /api/cameras/<id>/recorder/<action>` with `start`, `stop`, or `restart`
  for recorder controls
- `POST /api/cameras/<id>/live/<action>` with `stop` or `restart` for
  live-stream recovery
- `POST /api/cameras/<id>/ptz` for PTZ movement, stop, home, and preset commands
- `GET /live/<camera_id>/stream.m3u8?token=<stream_token>` for go2rtc HLS
  playback
- `GET /media/<camera_id>/<segment>.mp4?token=<stream_token>` for recording
  playback, sharing, and download

The HLS player keeps a small forward buffer, seeks toward the live edge when
latency grows, and reopens the stream when playback stops advancing.
