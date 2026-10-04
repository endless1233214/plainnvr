# PlainNVR for Android (native companion)

The Android app connects to an existing PlainNVR server. It uses the same
session-cookie API as the iPhone app and does not talk directly to cameras.
It provides a camera list, HLS live view, recording calendar and MP4 playback,
recent events, recorder start/stop/restart, and camera-advertised PTZ actions.

It uses only endpoints implemented in `app/http_api.py`. Live and recording
playback use the server's short-lived stream token; the token never goes to an
external player. The app saves the server address and username, but not the
password. Session cookies remain in memory and are discarded when the app
process ends. Plain HTTP is supported for trusted local networks only.

## PC build

Install Android Studio and Android SDK platform 37 plus build tools 36.0.0.
The project uses Java 17 language features, Android Gradle Plugin 9.3.2,
Gradle 9.7.1, and Media3 1.11.1. Set `ANDROID_HOME` to the SDK directory,
then run from this directory:

```powershell
.\gradlew.bat :app:assembleDebug
```

For the on-device authentication and session-cookie test, start an Android
emulator or connect a test device, then run:

```powershell
.\gradlew.bat :app:connectedDebugAndroidTest
```

The test uses a temporary loopback HTTP fixture on the device. It does not
connect to a production PlainNVR server.

The unsigned-for-distribution debug APK is at
`app/build/outputs/apk/debug/app-debug.apk`. It is signed with Android's local
debug key only. To install on a USB-connected Android device:

```powershell
adb install -r app/build/outputs/apk/debug/app-debug.apk
```

## Release APK or Play Store AAB

Create and back up your own Android signing keystore; do not commit it or its
passwords. In Android Studio, choose **Build > Generate Signed App Bundle / APK**,
select **Android App Bundle** for Play Store or **APK** for direct distribution,
choose the `release` variant, and point the wizard to your keystore. Keep the
same signing key for every future update. The repository does not include a
release key or an automated signed-release task.

Android uses HLS for live playback, whereas the iPhone app can also try WebRTC.
The server's actual HLS endpoint is `/live/{camera_id}/stream.m3u8`; this
companion does not invent an Android-only streaming API.
