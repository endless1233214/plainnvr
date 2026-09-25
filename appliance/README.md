# PlainNVR OS: native Debian prototype

This directory is a developer prototype for Debian 13 amd64. It is not yet an
end-user installer ISO. The appliance runs the existing PlainNVR server directly
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

## Prototype VM setup

Use a Debian 13 amd64 VM with a graphical display and Ethernet. Attach a
persistent virtual data disk, format and mount it at `/var/lib/plainnvr` using
the VM's normal disk tools, and add it to `/etc/fstab` by UUID. The scripts in
this directory never select, partition, or format a disk. The server refuses
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
an Xorg kiosk fallback can be added if required. Disk selection, final ISO,
automatic updates, and rollback are later milestones.
