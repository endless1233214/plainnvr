# PlainNVR iPhone

Native SwiftUI companion app for PlainNVR. It is meant for personal sideloading through Xcode and talks directly to the PlainNVR server on the local network or over a private tunnel.

## Features

- Sign in with the same PlainNVR account used by the web UI.
- View camera status, recorder state, disk usage, and recent recorder events.
- Play live camera video with audio through PlainNVR's HLS endpoint.
- Browse saved recording dates and MP4 segments.
- Play, share, or save selected recording clips to Photos.

## Server Support

The app uses the existing session cookie API plus these media paths:

- `GET /api/status` for cameras, recorder state, disk usage, events, and the stream token.
- `GET /api/coverage?camera_id=<id>` for saved recording dates and storage totals.
- `GET /api/segments?camera_id=<id>&date=<yyyy-mm-dd>` for MP4 segment metadata.
- `GET /live/<camera_id>/stream.m3u8?token=<stream_token>` for live iPhone playback with audio.
- `GET /media/<camera_id>/<segment>.mp4?token=<stream_token>` for playback, share, and download.

MJPEG is still available for the web/Home Assistant style preview, but MJPEG is video-only. The iPhone app uses HLS for live playback because `AVPlayer` can play audio and video together.

## Run On iPhone

1. Open `PlainNVRiPhone.xcodeproj` in Xcode.
2. Set the target's signing team to your Apple developer account.
3. Plug in the iPhone 15 and choose it as the run destination.
4. Press Run.
5. Enter the PlainNVR server URL, for example `http://192.168.1.172:8787`, and sign in.

If Xcode says the iOS platform is missing, install it from Xcode Settings > Components, then reopen the project.
