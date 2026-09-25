#!/bin/sh
set -eu

# Developer prototype installer. It never partitions or formats storage.
if [ "$(id -u)" -ne 0 ]; then
    echo "Run as root on Debian 13 amd64." >&2
    exit 1
fi
if [ "$(uname -m)" != x86_64 ] || ! grep -q '^VERSION_CODENAME=trixie$' /etc/os-release; then
    echo "Requires Debian 13 amd64." >&2
    exit 1
fi
if ! mountpoint -q /var/lib/plainnvr; then
    echo "Mount persistent storage at /var/lib/plainnvr before installing." >&2
    exit 1
fi
if [ "$#" -ne 1 ] || [ ! -f "$1/VERSION" ]; then
    echo "Usage: $0 /path/to/native-runtime" >&2
    exit 1
fi
runtime_dir=$(CDPATH= cd -- "$1" && pwd)
version=$(cat "$runtime_dir/VERSION")
case "$version" in
    *[!0-9A-Za-z.+~-]*|'') echo "Invalid runtime version" >&2; exit 1 ;;
esac
for binary in bin/go2rtc ffmpeg/bin/ffmpeg ffmpeg/bin/ffprobe; do
    if [ ! -x "$runtime_dir/$binary" ]; then
        echo "Missing native runtime binary: $binary" >&2
        exit 1
    fi
done

repo_dir=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    python3 ca-certificates libssl3t64 chromium chromium-sandbox cage \
    dbus-user-session libpam-systemd

if ! getent group plainnvr >/dev/null; then
    groupadd --system plainnvr
fi
if ! getent passwd plainnvr >/dev/null; then
    useradd --system --gid plainnvr --home-dir /var/lib/plainnvr \
        --no-create-home --shell /usr/sbin/nologin plainnvr
fi
if ! getent group plainnvr-kiosk >/dev/null; then
    groupadd --system plainnvr-kiosk
fi
if ! getent passwd plainnvr-kiosk >/dev/null; then
    useradd --system --gid plainnvr-kiosk --home-dir /var/lib/plainnvr-kiosk \
        --create-home --shell /usr/sbin/nologin plainnvr-kiosk
fi

install -d -m 0700 -o plainnvr -g plainnvr /var/lib/plainnvr/recordings
chown plainnvr:plainnvr /var/lib/plainnvr
install -d -m 0700 -o plainnvr-kiosk -g plainnvr-kiosk /var/lib/plainnvr-kiosk
release_dir="/opt/plainnvr/releases/$version"
if [ -e "$release_dir" ]; then
    echo "Release already installed: $release_dir" >&2
    exit 1
fi
install -d -m 0755 "$release_dir"
cp -R "$runtime_dir/." "$release_dir/"
chown -R root:root "$release_dir"
chmod -R go-w "$release_dir"
ln -sfn "releases/$version" /opt/plainnvr/current

install -m 0644 "$repo_dir/appliance/systemd/plainnvr.service" \
    /etc/systemd/system/plainnvr.service
install -m 0644 "$repo_dir/appliance/systemd/plainnvr-kiosk@.service" \
    /etc/systemd/system/plainnvr-kiosk@.service
install -m 0644 "$repo_dir/appliance/kiosk/plainnvr-kiosk.pam" \
    /etc/pam.d/plainnvr-kiosk
systemctl daemon-reload
systemctl enable --now plainnvr.service
systemctl enable plainnvr-kiosk@tty1.service
systemctl set-default graphical.target
echo "PlainNVR $version installed. Reboot to start the kiosk."
