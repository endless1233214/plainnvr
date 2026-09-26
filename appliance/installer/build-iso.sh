#!/bin/sh
set -eu

# Run on Debian 13 amd64. live-build creates a clean rootfs, never a VM clone.
repo_dir=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
if [ "$(id -u)" -ne 0 ] || [ "$(dpkg --print-architecture)" != amd64 ] ||
   ! grep -q '^VERSION_CODENAME=trixie$' /etc/os-release; then
    echo "Run as root on Debian 13 amd64." >&2
    exit 1
fi
if [ "$#" -ne 2 ]; then
    echo "Usage: $0 /absolute/native-runtime /absolute/new-build-directory" >&2
    exit 1
fi
runtime=$(realpath -e "$1")
case "$2" in /*) ;; *) echo "Build directory must be absolute." >&2; exit 1 ;; esac
if [ -e "$2" ]; then
    echo "Choose a new build directory; existing files are never removed." >&2
    exit 1
fi
version=$(cat "$runtime/VERSION")
case "$version" in *[!0-9A-Za-z.+~-]*|'') exit 1 ;; esac
test "$version" = "$(cat "$repo_dir/VERSION")"
for file in bin/go2rtc ffmpeg/bin/ffmpeg ffmpeg/bin/ffprobe kiosk/start.sh; do
    test -x "$runtime/$file"
done
test -d "$runtime/licenses"
for tool in lb debootstrap xorriso mksquashfs unsquashfs; do
    command -v "$tool" >/dev/null || { echo "Missing build tool: $tool" >&2; exit 1; }
done
mkdir -p "$2"
cd "$2"
lb config --mode debian --distribution trixie --architectures amd64 \
    --binary-images iso-hybrid --debian-installer live \
    --debian-installer-gui true --archive-areas 'main contrib non-free non-free-firmware' \
    --apt-recommends false --security true --updates true --backports false \
    --firmware-binary true --firmware-chroot true \
    --iso-application 'PlainNVR OS Installer' --iso-volume PLAINNVR_INSTALL \
    --image-name "plainnvr-os-$version" \
    --bootappend-install 'hostname=plainnvr'

cp -R "$repo_dir/appliance/installer/config/." config/
release="config/includes.chroot/opt/plainnvr/releases/$version"
mkdir -p "$release" config/includes.chroot/etc/systemd/system config/includes.chroot/etc/pam.d
cp -a "$runtime/." "$release/"
mkdir -p config/includes.chroot/usr/lib/plainnvr/setup
cp "$repo_dir/appliance/setup/"*.py "$repo_dir/appliance/setup/index.html" config/includes.chroot/usr/lib/plainnvr/setup/
# Kiosk setup routing is appliance-specific; keep it current when using a
# previously staged native media runtime.
cp "$repo_dir/appliance/kiosk/start.sh" "$release/kiosk/start.sh"
chmod 0755 "$release/kiosk/start.sh"
cp "$repo_dir/appliance/systemd/"*.service config/includes.chroot/etc/systemd/system/
cp "$repo_dir/appliance/kiosk/plainnvr-kiosk.pam" config/includes.chroot/etc/pam.d/plainnvr-kiosk
cp -R /usr/share/live/build/bootloaders config/
cp "$repo_dir/appliance/installer/grub.cfg" config/bootloaders/grub-pc/grub.cfg
cp "$repo_dir/appliance/installer/theme.cfg" config/bootloaders/grub-pc/theme.cfg
cp "$repo_dir/appliance/installer/menu.cfg" config/bootloaders/syslinux_common/menu.cfg
cp "$repo_dir/appliance/installer/stdmenu.cfg" config/bootloaders/syslinux_common/stdmenu.cfg
chmod +x config/includes.installer/plainnvr-partman config/includes.installer/plainnvr-late
chmod +x config/includes.chroot/usr/lib/plainnvr/boot-mirror config/includes.chroot/etc/kernel/postinst.d/zz-plainnvr-boot-mirror
chmod +x config/hooks/live/*.hook.chroot config/includes.chroot/usr/lib/plainnvr/finish-install
chmod +x config/hooks/live/*.hook.binary
lb build
test -s binary/live/filesystem.squashfs
for file in server.py storage.py seed-admin.py index.html; do
    unsquashfs -cat binary/live/filesystem.squashfs "usr/lib/plainnvr/setup/$file" |
        cmp - "$repo_dir/appliance/setup/$file"
done
unsquashfs -cat binary/live/filesystem.squashfs opt/plainnvr/releases/"$version"/VERSION |
    cmp - "$runtime/VERSION"
sha256sum ./*.iso > SHA256SUMS
printf '\nInstaller output: %s\n' "$(pwd)"
