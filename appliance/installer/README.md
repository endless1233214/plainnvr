# PlainNVR OS installer

This builds a Debian 13 amd64 hybrid ISO containing the native PlainNVR runtime,
Debian Installer, GParted and ZFS. It is an appliance development image. The
physical-PC graphics and sustained recording tests are still required.

## Installation flow

1. Write the ISO to a USB drive using an image-writing tool. Boot that USB in
   UEFI or legacy BIOS mode. No disks are changed merely by booting the image.
2. Choose the normal installer or **two mirrored boot drives**. The mirror uses
   Linux software RAID1 for the system and default data filesystem. It is boot
   redundancy, not a second operating system.
3. Select language, keyboard, timezone and a local maintenance user/password.
   This Linux account is separate from the PlainNVR administrator.
4. Choose the intended drive(s), review the partition layout and explicitly
   confirm the destructive changes. Use drives of at least 36 GB each; 64 GB or
   more leaves more room for updates. The supplied layout reserves 24 GB for
   the OS and puts `/var/lib/plainnvr` on a separate filesystem.
   The prototype mirror recipe has no swap partition. With sufficient RAM
   (8 GB recommended), choose **No** when asked to return to partitioning to
   add swap, or use manual partitioning if swap is required.
5. Remove the USB and reboot. The attached monitor opens the first-boot wizard:
   create the PlainNVR administrator, then choose storage and directories.
6. After setup, sign in normally. PlainNVR is available from the LAN on port
   8787. The kiosk requires login again after each reboot.

The installer image carries its OS and application packages; installation does
not require downloading PlainNVR. Network configuration can use Ethernet DHCP.
Firmware is included for common graphics and network devices.

## First-boot storage

The local setup service listens only on `127.0.0.1:8790` and is disabled after
successful setup. It authenticates storage operations with the newly created
admin account. The normal NVR service remains gated until configuration is
complete. The wizard offers:

- The installed data filesystem, with separate configuration and recording
  directories.
- An existing, unmounted ext4/XFS partition, identified and mounted by UUID.
  Setup creates a new empty recording directory without formatting the volume.
- A new ZFS pool on explicitly selected blank disks: single, mirror, RAIDZ1 or
  RAIDZ2. Creation requires a typed confirmation. Boot disks, mounted devices,
  disks with partitions, and disks with existing signatures are excluded.
- An exported ZFS pool, imported without forcing it, with a new dataset for
  PlainNVR. Existing datasets are preserved.

The configuration database stays on the installed persistent data filesystem.
ZFS is supported for recording pools; the boot filesystem uses ext4/RAID1.
The recording mount is asserted by systemd so a missing disk or unimported pool
cannot redirect recordings onto the OS filesystem.

GParted is available from the USB boot menu and from local first-boot setup.
Closing it returns to the wizard; refresh the device list afterward. Its own
Apply operation can erase data. It does not create ZFS pools; use the wizard
for those. Completed storage operations are saved so interrupted setup can
resume without recreating a pool or overwriting an existing directory.

For this prototype, disable Secure Boot when using ZFS. DKMS builds a module
for the installed kernel; the builder's signing keys are excluded from the
image. Per-machine MOK enrollment and Secure Boot update validation are not
yet part of the setup flow.

## Mirrored boot

The mirrored installation asks for exactly two drives. Debian Installer creates
RAID1 arrays and installs the OS. The finishing step installs BIOS boot code on
both selected drives, or copies the installed Debian EFI loader and removable-media
fallback loader to both EFI partitions. The system can therefore boot from the
remaining drive when the other is unavailable (firmware may need its boot order
adjusted). An unavailable primary EFI partition does not force emergency mode.

A service and package/kernel update hooks maintain the EFI copies. Replacing a
failed drive still requires deliberate partitioning and adding the new member
with `mdadm`, plus refreshing the recorded EFI partition UUIDs when applicable;
the appliance never selects or overwrites a replacement drive
automatically. Mirroring does not replace backups.

## Build on Debian 13 amd64

Use a native Debian machine or VM with at least 8 GB RAM and 30 GB free build
space. The rootfs is created by Debian live-build, rather than copied from the
development VM; no VM accounts, SSH keys, camera database or recordings are
included.

```sh
sudo apt-get update
sudo apt-get install --no-install-recommends \
  build-essential curl xz-utils nasm pkgconf libssl-dev golang-go \
  ca-certificates patch live-build debootstrap xorriso squashfs-tools \
  isolinux syslinux-common grub-pc-bin grub-efi-amd64-bin mtools dosfstools
sh appliance/debian/build-runtime.sh /absolute/path/plainnvr-runtime
sudo sh appliance/installer/build-iso.sh \
  /absolute/path/plainnvr-runtime /absolute/path/new-iso-build-directory
```

The ISO, its package manifests, and `SHA256SUMS` appear in the new build
directory. That directory must not exist when invoking the wrapper; it never
cleans or deletes existing output. For a clean retry after an interrupted build,
invoke the wrapper with a new build directory. Advanced recovery must account
for live-build temporarily saving the appliance root under `chroot/chroot`
during the installer stage. Do not rerun earlier chroot stages against that
temporary installer environment. Interrupted initrd repacking can leave
truncated installer cache files and partial binary output; both need to be
cleared before resuming the installer and binary stages.

The media source versions and checksums are pinned. Debian packages include
current trixie security updates, so rebuilding on a different date can produce
different package versions and checksums. Preserve the ISO's package manifest
alongside each distributed image.

## Validation

Run `python3 -m unittest discover -s appliance/tests -v` from the repository.
The setup tests cover origin/Host checks, unauthenticated storage requests,
administrator replacement, path traversal, symlinks, overlapping directories,
and ZFS disk selection/confirmation.

Every release candidate also needs installation onto disposable blank disks in
UEFI and BIOS VMs, first-boot setup, reboot, recording and missing-mount checks.
For the mirror, boot once with each drive absent. Exercise GParted and new/imported
ZFS pools in disposable VMs, and repeat graphics and recording-load tests on
the intended physical PC before treating an image as a release.
