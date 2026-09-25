# PlainNVR for macOS

This directory contains the native macOS SwiftUI client. Open
`PlainNVRMac/PlainNVRMac.xcodeproj` in Xcode and run the `PlainNVRMac` scheme.

The target shares the API client, data models, and native WebRTC session with
the iPhone app. Its macOS views provide Live, Cameras, Recordings, and Settings.
Live playback prefers WebRTC and uses AVPlayer for HLS compatibility. The Mac
target uses the same bundle identifier as the iPhone target so both platforms
belong to the same App Store Connect app record. It is sandboxed with outbound
network access; the user supplies their own PlainNVR server address.

Build locally with:

```sh
xcodebuild -project MacOS/PlainNVRMac/PlainNVRMac.xcodeproj \
  -scheme PlainNVRMac -destination 'platform=macOS' build
```
