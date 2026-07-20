# Installing PlainNVR on TrueNAS

This guide walks through installing PlainNVR from the TrueNAS Community app
catalog.

## The Short Version

You do not need to enter camera IP addresses during the TrueNAS app install.

The TrueNAS install form is only for the app container, its ports, its storage,
and how TrueNAS should run it. Camera IPs and RTSP URLs are added later inside
the PlainNVR web interface after the app is installed.

The fields named **Host IPs** are also not camera IPs. They mean "which TrueNAS
network address should this app port listen on." Most people can leave those
blank.

## Recommended First Install

For a normal home install, start with these choices:

| Setting | Recommended value |
| --- | --- |
| Application Name | `plainnvr` |
| Timezone | Your local timezone |
| Recording Segment Seconds | `60` |
| WebRTC Candidates | Leave blank |
| Additional Environment Variables | Leave empty |
| User ID | `568` |
| Group ID | `568` |
| Host Network | Off |
| Web UI Port | Published, keep the TrueNAS generated port unless you need a different one |
| RTSP Port | Exposed, unless another app or device needs to connect to PlainNVR RTSP restreams |
| WebRTC Port | Exposed, unless you are deliberately using go2rtc WebRTC directly |
| PlainNVR Data Storage | ixVolume |
| PlainNVR Recordings Storage | Host Path for a large recordings dataset, or ixVolume for a simple test install |
| Labels | Leave empty |
| CPUs | `2` |
| Memory | `4096` MB |

After install, open the PlainNVR web portal and add cameras from inside
PlainNVR.

## Before You Install

It helps to know these things first:

- The IP address or hostname of the TrueNAS system.
- Where you want recordings stored.
- The RTSP URL for each camera, if you already know it.
- A long password for the first PlainNVR admin account.

If you do not know the camera RTSP URLs yet, that is fine. Install PlainNVR
first, then add cameras later.

## Application Name

This is the TrueNAS app instance name. The default `plainnvr` is good unless you
plan to run more than one PlainNVR instance.

This name is only used by TrueNAS. It is not the camera name, server name, or
login username.

## Version

This selects the PlainNVR catalog app version. For a normal install, use the
latest version shown by TrueNAS.

## PlainNVR Configuration

### Timezone

Set this to your local timezone.

PlainNVR uses it for logs, timestamps, schedules, and recording display times.
If this is wrong, the app may still work, but the timeline and schedules can be
confusing.

### Recording Segment Seconds

This controls the default length of each recording file segment.

The default `60` means PlainNVR writes recordings in one-minute chunks. Shorter
segments make smaller files but create more of them. Longer segments create
fewer files, but each file covers more time.

For most users, `60` is the right starting point.

### WebRTC Candidates

Leave this blank for a normal install.

This is an advanced go2rtc setting for WebRTC networking. It tells go2rtc what
address or addresses to advertise when a browser or remote client is trying to
make a WebRTC media connection.

PlainNVR's own web interface uses go2rtc through the PlainNVR web port. The
iPhone companion app uses the PlainNVR server too. Because of that, most users
do not need to set WebRTC candidates.

Only fill this in if you are troubleshooting direct go2rtc WebRTC access,
remote access, VPN access, or a reverse proxy setup where the browser cannot
figure out how to reach the media port.

This is not where camera IP addresses go.

### Additional Environment Variables

Leave this empty unless you are following a specific troubleshooting note or
developer instruction.

These values override advanced PlainNVR environment settings. They are useful
for debugging, but they are not needed for a normal install.

## User And Group Configuration

### User ID

The default `568` is the TrueNAS `apps` user. Keep it unless you have a specific
reason to run PlainNVR as another user.

### Group ID

The default `568` is the TrueNAS `apps` group. Keep it unless your storage
permissions require a different group.

These two values matter most when using Host Path storage. PlainNVR needs write
access to its data directory and recordings directory.

## Network Configuration

### Host Network

Recommended: leave this off.

When Host Network is off, TrueNAS publishes only the ports you choose. This is
cleaner, easier to reason about, and less likely to conflict with other apps.

Turn Host Network on only if you know you need it for a specific networking
reason. For example, some unusual LAN discovery or direct-network setups may be
easier with host networking. Most RTSP cameras do not need this. A PlainNVR
container can usually reach camera LAN IPs without host networking.

### Port Bind Mode

TrueNAS uses this setting on each port.

| Mode | Meaning |
| --- | --- |
| Publish | Makes the port reachable from your LAN through the TrueNAS IP address |
| Expose | Keeps the port available only inside TrueNAS app/container networking |
| None | Does not publish or expose the port |

For the Web UI, most users want **Publish**.

For RTSP and WebRTC, most users can leave the defaults unless another device or
app needs direct access to those ports.

### Port Number

This is the port on the TrueNAS system.

If the Web UI port is `30487`, for example, the app opens at:

```text
http://TRUENAS-IP:30487
```

TrueNAS may suggest a different port if the default is already in use. That is
fine. Use the port TrueNAS gives you unless you have a reason to change it.

### Host IPs

This is not for camera IP addresses.

Host IPs means "only bind this app port to these TrueNAS IP addresses." If you
leave it blank, TrueNAS can bind the port on the normal available addresses.

Most users should leave Host IPs empty.

Only add a Host IP if your TrueNAS system has multiple network addresses and
you intentionally want PlainNVR available on just one of them.

### Web UI Port

This is the main PlainNVR web interface and API port.

Recommended:

- Port Bind Mode: Publish
- Port Number: keep the TrueNAS default or generated value
- Host IPs: blank

After install, open:

```text
http://TRUENAS-IP:WEB-UI-PORT
```

For example:

```text
http://192.168.1.172:30487
```

Use the actual port shown by your TrueNAS install screen.

### RTSP Port

This is the go2rtc RTSP restream port. Its internal container port is `8554`.

PlainNVR can use go2rtc internally without publishing this port to your whole
LAN.

Recommended:

- Leave it as Exposed for normal PlainNVR use.
- Publish it only if another app or device needs to connect to PlainNVR's RTSP
  restreams directly.

Camera RTSP URLs are still added inside PlainNVR after install. They do not go
in this TrueNAS field.

### WebRTC Port

This is the go2rtc WebRTC media port. Its internal container port is `8555` and
it uses both TCP and UDP.

PlainNVR's web UI currently uses go2rtc through the PlainNVR web port using
MSE/HLS. The iPhone companion app also talks to PlainNVR, not directly to the
camera or directly to go2rtc.

Recommended:

- Leave it as Exposed for normal PlainNVR use.
- Publish it only if you are intentionally using direct go2rtc WebRTC access or
  troubleshooting a setup that requires it.

If you publish this port for direct WebRTC, make sure both TCP and UDP are
reachable and set WebRTC Candidates only if needed.

### Networks

This is an advanced Docker networking option.

Most users can leave it empty. Use it only if you already have a custom Docker
network and need PlainNVR attached to it.

## Storage Configuration

PlainNVR has two main storage locations.

### PlainNVR Data Storage

This stores the app database, configuration, account setup, camera settings,
and go2rtc state.

Recommended: use ixVolume.

ixVolume lets TrueNAS create and manage the dataset for the app. It is the
simplest and safest choice for app data.

Use Host Path only if you already know exactly where you want PlainNVR's app
data stored.

### PlainNVR Recordings Storage

This stores the actual camera recordings.

For a quick test install, ixVolume is fine.

For a real NVR setup, Host Path is often better because recordings can get big.
Choose or create a dataset where you want video files to live, then point the
recordings storage path there.

Example:

```text
/mnt/stuff/plainNVR/recordings
```

If you are doing a completely clean test, use an empty recordings folder. If you
want to keep old recordings, point this at the existing recordings folder.

### Enable ACL

This controls whether TrueNAS shows ACL options for that storage path.

If you are using ixVolume, leaving ACL off is usually fine.

If you are using Host Path, PlainNVR must be able to write to that path as the
configured User ID and Group ID. With the defaults, that means UID `568` and GID
`568`.

If recordings do not save after install, check storage permissions first. The
recordings path must be writable by the user and group that PlainNVR runs as.

### Additional Storage

Most users can leave this empty.

This is for mounting extra folders or network shares into the container. It is
not needed for normal camera setup and it is not where camera IPs go.

## Labels Configuration

Docker labels are advanced metadata for the container.

Most users can leave this empty.

## Resources Configuration

### CPUs

The default `2` is a good starting point.

PlainNVR tries to copy camera streams instead of re-encoding them, so it should
not need huge CPU for basic recording. More cameras, higher bitrates, live view
load, and troubleshooting can all increase CPU use.

### Memory

The default `4096` MB is a good starting point.

If you run many cameras or see memory pressure, raise it. For a one-camera test
install, the default is usually more than enough.

## First Run After Install

1. Install the app in TrueNAS.
2. Open the Web UI port from your browser:

   ```text
   http://TRUENAS-IP:WEB-UI-PORT
   ```

3. Create the first PlainNVR admin account.
4. Open the Cameras section.
5. Add a camera using its RTSP URL.
6. Select Test Stream.
7. Save the camera.
8. Confirm live view works.
9. Confirm recordings are being written.

Common RTSP URL examples:

```text
rtsp://USERNAME:PASSWORD@CAMERA-IP:554/Streaming/Channels/101
rtsp://USERNAME:PASSWORD@CAMERA-IP:554/h264Preview_01_main
rtsp://USERNAME:PASSWORD@CAMERA-IP:554/cam/realmonitor?channel=1&subtype=0
```

The exact path depends on the camera brand and firmware.

## Suggested Clean Install Test

For testing a fresh TrueNAS install:

1. Leave WebRTC Candidates blank.
2. Leave Additional Environment Variables empty.
3. Keep User ID and Group ID at `568`.
4. Leave Host Network off.
5. Publish the Web UI port.
6. Leave RTSP and WebRTC ports exposed unless you know you need them published.
7. Use ixVolume for PlainNVR Data Storage.
8. Use an empty Host Path or ixVolume for Recordings Storage.
9. Install the app.
10. Create the first admin account.
11. Add one camera in PlainNVR.
12. Test live view.
13. Wait a few minutes and confirm recording files appear.

Once the clean test works, add the rest of your cameras and tune retention.

## Troubleshooting

### The Web UI Does Not Open

Check these first:

- Host Network should usually be off.
- Web UI Port should be Published.
- Use `http://`, not `https://`, unless you added a reverse proxy.
- Use the TrueNAS IP address and the Web UI port shown in the app install.
- Check the app logs in TrueNAS.

### The Camera Does Not Connect

Check these first:

- The RTSP URL is entered inside PlainNVR, not in the TrueNAS install form.
- The camera IP is reachable from the TrueNAS network.
- The username and password are correct.
- The RTSP path matches the camera brand and model.
- The camera stream is H.264 if you want the broadest browser and iPhone
  compatibility.

### Live View Works But Recordings Do Not Save

Check storage permissions.

If using Host Path recordings, the path must be writable by the User ID and
Group ID configured for PlainNVR. With the defaults, that is `568:568`.

Also check that the dataset has enough free space.

### WebRTC Or Remote Live View Is Not Working

For normal PlainNVR use, start with the Web UI and HLS/MSE live view first.

Only troubleshoot WebRTC Candidates if you are intentionally using direct
go2rtc WebRTC or a remote setup that needs advertised media candidates.

## What To Show In A Setup Video

This guide can be used as a simple video outline:

1. Show PlainNVR in the TrueNAS Community app catalog.
2. Explain that camera IPs are added after install, not in the TrueNAS form.
3. Walk through the recommended install settings.
4. Point out the Host IPs fields and explain that they are TrueNAS bind IPs.
5. Choose app data and recordings storage.
6. Install the app.
7. Open the PlainNVR web portal.
8. Create the first admin account.
9. Add one camera with an RTSP URL.
10. Test live view and confirm recordings.
