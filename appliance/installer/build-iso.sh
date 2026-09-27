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
revision=$(cat "$repo_dir/appliance/installer/REVISION")
case "$revision" in *[!0-9]*|'') exit 1 ;; esac
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
    --image-name "plainnvr-os-$version-installer$revision" \
    --bootappend-install 'hostname=plainnvr'

cp -R "$repo_dir/appliance/installer/config/." config/
cp "$repo_dir/appliance/installer/config/includes.installer/preseed.cfg" \
    config/includes.chroot/usr/lib/plainnvr/installer/preseed.cfg
release="config/includes.chroot/opt/plainnvr/releases/$version"
mkdir -p "$release" config/includes.chroot/etc/systemd/system config/includes.chroot/etc/pam.d
cp -a "$runtime/." "$release/"
# Refresh application/UI sources alongside the appliance management layer.
cp -R "$repo_dir/app/." "$release/app/"
cp -R "$repo_dir/static/." "$release/static/"
mkdir -p config/includes.chroot/usr/lib/plainnvr/control
mkdir -p config/includes.chroot/usr/lib/plainnvr/update
cp "$repo_dir/appliance/update/"*.py "$repo_dir/appliance/update/VERSION" "$repo_dir/appliance/update/release.pem" config/includes.chroot/usr/lib/plainnvr/update/
chmod 0755 config/includes.chroot/usr/lib/plainnvr/update/boot.py config/includes.chroot/usr/lib/plainnvr/update/hook.py
cp "$repo_dir/appliance/control/"*.py "$repo_dir/appliance/control/local-tool" config/includes.chroot/usr/lib/plainnvr/control/
chmod 0755 config/includes.chroot/usr/lib/plainnvr/control/local-tool
mkdir -p config/includes.chroot/usr/lib/plainnvr/setup
mkdir -p config/includes.chroot/usr/lib/plainnvr/support
cp "$repo_dir/appliance/support/"*.py config/includes.chroot/usr/lib/plainnvr/support/
cp "$repo_dir/appliance/setup/"*.py "$repo_dir/appliance/setup/index.html" config/includes.chroot/usr/lib/plainnvr/setup/
# Kiosk setup routing is appliance-specific; keep it current when using a
# previously staged native media runtime.
cp "$repo_dir/appliance/kiosk/start.sh" "$release/kiosk/start.sh"
cp "$repo_dir/appliance/kiosk/recovery.html" "$release/kiosk/recovery.html"
chmod 0755 "$release/kiosk/start.sh"
cp "$repo_dir/appliance/systemd/"*.service config/includes.chroot/etc/systemd/system/
cp "$repo_dir/appliance/systemd/"*.timer config/includes.chroot/etc/systemd/system/
cp "$repo_dir/appliance/kiosk/plainnvr-kiosk.pam" config/includes.chroot/etc/pam.d/plainnvr-kiosk
cp -R /usr/share/live/build/bootloaders config/
cp "$repo_dir/appliance/installer/grub.cfg" config/bootloaders/grub-pc/grub.cfg
cp "$repo_dir/appliance/installer/grub-console.cfg" config/bootloaders/grub-pc/config.cfg
cp "$repo_dir/appliance/installer/theme.cfg" config/bootloaders/grub-pc/theme.cfg
cp "$repo_dir/appliance/installer/menu.cfg" config/bootloaders/syslinux_common/menu.cfg
cp "$repo_dir/appliance/installer/stdmenu.cfg" config/bootloaders/syslinux_common/stdmenu.cfg
# live-build's default BIOS module list only includes the graphical menu.
mkdir -p config/includes.binary/isolinux
cp /usr/lib/syslinux/modules/bios/menu.c32 /usr/lib/syslinux/modules/bios/libutil.c32 config/includes.binary/isolinux/
chmod +x config/includes.installer/plainnvr-partman config/includes.installer/plainnvr-late
chmod +x config/includes.chroot/usr/lib/plainnvr/boot-mirror config/includes.chroot/etc/kernel/postinst.d/zz-plainnvr-boot-mirror
chmod +x config/hooks/live/*.hook.chroot config/includes.chroot/usr/lib/plainnvr/finish-install
chmod +x config/hooks/live/*.hook.binary
chmod +x config/includes.chroot/usr/lib/plainnvr/installer/session config/includes.chroot/usr/lib/plainnvr/installer/launch config/includes.chroot/usr/lib/plainnvr/installer/gparted-session config/includes.chroot/usr/lib/plainnvr/installer/prepare-media
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
