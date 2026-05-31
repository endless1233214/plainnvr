# PlainNVR iPhone

Native SwiftUI companion app for PlainNVR. It is meant for personal sideloading through Xcode and talks directly to the PlainNVR server on the local network or over a private tunnel.

## Features

- Sign in with the same PlainNVR account used by the web UI.
- View camera status, recorder state, disk usage, and recent recorder events.
- Play live camera video through the camera's selected PlainNVR live mode, using HLS for audio/video and low CPU when available.
- Choose live stream FPS and quality from the Live tab. High quality is the default for steadier HLS startup; Source quality is still available when you want a direct camera copy.
- Toggle live audio and set live volume from the Live tab.
- Check a selected live stream from the Live tab and show player/server diagnostics in the app.
- Start, pause, and restart a camera recorder from its detail screen.
- Rotate the phone sideways on the Live tab to show the selected camera full screen.
- Pinch live video to zoom into the image and drag while zoomed to inspect a specific area.
- Browse saved recording dates and MP4 segments.
- Play, share, or save selected recording clips to Photos.

## Server Support

The app uses the existing session cookie API plus these media paths:

- `GET /api/status` for cameras, recorder state, disk usage, events, and the stream token.
- `GET /api/coverage?camera_id=<id>` for saved recording dates and storage totals.
- `GET /api/segments?camera_id=<id>&date=<yyyy-mm-dd>` for MP4 segment metadata.
- `POST /api/cameras/<id>/recorder/start|stop|restart` for manual recorder controls.
- `POST /api/cameras/<id>/live/stop|restart` for live HLS recovery.
- `GET /api/cameras/<id>/live/diagnostics` for stream/player troubleshooting details.
- `GET /live/<camera_id>/stream.m3u8?fps=<fps>&width=<width>&token=<stream_token>` for live iPhone playback with audio. Omit `fps` and `width` to use source quality.
- `GET /media/<camera_id>/<segment>.mp4?token=<stream_token>` for playback, share, and download.

MJPEG is still available for the web/Home Assistant style preview, but MJPEG is video-only. The iPhone app uses HLS by default because `AVPlayer` can play audio and video together, and it falls back to MJPEG only when that camera is configured for MJPEG live view.

Live HLS audio is boosted by default with `NVR_LIVE_AUDIO_GAIN=4.0`. Set it lower if microphones distort, or higher if a camera is still too quiet.

The live player keeps a very small forward buffer and seeks back toward the live
edge whenever drift grows, so PTZ moves should show up faster on the phone.

## Run On iPhone

1. Open `PlainNVRiPhone.xcodeproj` in Xcode.
2. Set the target's signing team to your Apple developer account.
3. Plug in the iPhone 15 and choose it as the run destination.
4. Press Run.
5. Enter the PlainNVR server URL, for example `http://192.168.1.0:8787`, and sign in.

If Xcode says the iOS platform is missing, install it from Xcode Settings > Components, then reopen the project.
