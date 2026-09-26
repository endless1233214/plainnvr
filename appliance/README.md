# PlainNVR OS: native Debian prototype

This directory contains the Debian 13 amd64 appliance prototype and its
[bootable installer](installer/README.md). The appliance runs the existing PlainNVR server directly
under systemd, with native go2rtc and FFmpeg binaries. Docker is not installed
or used on the appliance.

## Layout

- `debian/build-runtime.sh` builds the pinned media binaries and stages the
  current application and frontend in `appliance/out/`.
- `debian/install-prototype.sh` installs a staged runtime and enables the
  server and local kiosk services.
- `systemd/plainnvr.service` owns the server; the server supervises go2rtc and
  FFmpeg recorders as it does in the existing deployment.
- `systemd/plainnvr-kiosk@.service` owns Cage and Chromium on tty1. The kiosk
  displays the ordinary PlainNVR login and UI; it has no automatic admin login.
  Its browser profile is cleared at reboot, so the console requires a fresh
  login after each boot.

## Prototype VM setup

Use a Debian 13 amd64 VM with a graphical display and Ethernet. Attach a
persistent virtual data disk, format and mount it at `/var/lib/plainnvr` using
the VM's normal disk tools, and add it to `/etc/fstab` by UUID. The scripts in
`debian/` never select, partition, or format a disk. The server refuses
to start if `/var/lib/plainnvr` is not a mount point, so recordings cannot
silently fall back to the OS filesystem.

On the Debian build VM, install build prerequisites:

```sh
sudo apt-get update
sudo apt-get install --no-install-recommends \
  build-essential curl xz-utils nasm pkgconf libssl-dev golang-go \
  ca-certificates patch
./appliance/debian/build-runtime.sh
```

The Debian 13 Go package is older than this project's pinned Go toolchain.
The build requests Go 1.27.1 through Go's toolchain download mechanism. Builds
require internet access, and the source archives are checked against the
checksums in the current Dockerfile. The FFmpeg security patch and codec
selection are the same as in the Docker build.

After mounting `/var/lib/plainnvr`, install the staged runtime:

```sh
sudo ./appliance/debian/install-prototype.sh \
  appliance/out/plainnvr-$(cat VERSION)-amd64
sudo reboot
```

The monitor should open PlainNVR's login page without a desktop. The app is
also available at `http://APPLIANCE-IP:8787/`. Keep the appliance on a trusted
LAN for this prototype: the web login uses plain HTTP. go2rtc's management and
RTSP endpoints retain their loopback-only defaults; WebRTC uses port 8555 on
TCP and UDP. Do not expose these ports to the internet.

For diagnosis, use `systemctl status plainnvr.service`,
`systemctl status plainnvr-kiosk@tty1.service`, and the corresponding journal
logs from a separate maintenance session. The kiosk shows a retry screen if
the server is not ready at boot. The data disk contains the database and
recordings and is not replaced by application updates.

## Milestone validation

Test on a VM, then on the intended old PC: first account setup, LAN access,
live wall with several cameras, recording across reboot, clean shutdown,
recovery after restarting either service, and CPU/decoding load. The physical
PC test decides whether Cage/Wayland works well on its graphics hardware;
an Xorg kiosk fallback can be added if required. The bootable installer and
first-boot setup are described in [installer/README.md](installer/README.md).
Automatic updates and rollback remain later milestones.

The Debian 13 amd64 VM prototype has now completed the native validation pass:

- The pinned go2rtc and FFmpeg builds produced native amd64 binaries. go2rtc
  is statically linked with CGO disabled; FFmpeg and FFprobe link only against
  the expected Debian runtime libraries.
- The separate ext4 data disk is mounted at `/var/lib/plainnvr` by UUID. The
  server refuses to start when that mount is absent.
- PlainNVR, Cage, and Chromium start through systemd. The local display opens
  the ordinary login page and requires a new login after reboot.
- Two synthetic H.264/AAC camera sources recorded simultaneous MP4 segments;
  recordings survived server restarts, kiosk restarts, and full VM reboots.
  Playback was verified from the Recordings page.
- The VirtualBox copy is bridged to the LAN and responded at
  `http://192.168.1.150:8787/` during validation. The address is assigned by
  DHCP and will change on another network.

Remaining validation includes the intended old physical PC, graphics hardware,
sustained CPU/decoding load, WebRTC ICE over TCP/UDP, retention, and a Docker
regression build. There is no production update mechanism yet. See
[installer/README.md](installer/README.md) for the installer work and first-boot
storage setup.
