# PlainNVR OS installer

This builds a Debian 13 amd64 hybrid ISO containing the native PlainNVR runtime,
Debian Installer, GParted and ZFS. It is an appliance development image. The
owner confirmed revision 3 installed completely on the HP 200 G1 MT. Revision
6 needs a new HP test; sustained physical recording and storage/mirror tests
are still required.

## Revision 6 and A/B updates

Revision 6 fixes revision 5's final-installation failure in legacy BIOS mode.
It adds two 32 GB system slots with signed updates and rollback; remaining
space is shared configuration and recordings. See [update details](../UPDATES.md)
and the [revision 6 validation record](VALIDATION-6.md) for the scope of testing.

## Appliance controls

Revision 4 adds SMB recording storage, OS Settings, key-only SSH control, network
rollback, disk/pool management, local and browser file managers/terminals, and a
visible LAN address at login and on the dashboard. See [management details](../MANAGEMENT.md)
and [the update design](../UPDATES.md).

The installer, first-boot setup and web interface use the existing PlainNVR
camera icon from the iPhone app, also included as the browser icon.

## Installation flow

1. Write the ISO to a USB drive using an image-writing tool. Boot that USB in
   UEFI or legacy BIOS mode. The text menu starts **Install PlainNVR OS** after
   10 seconds without keyboard input, or press Enter to start immediately.
   No disks are changed merely by booting. For troublesome graphics, try **compatibility
   graphics**, which uses `nomodeset` and a text-mode kernel handoff.
2. Choose locale, keyboard and timezone. GParted opens in this live session.
   Close its window to return to the wizard; no reboot is needed. Use it to
   inspect disks or prepare separate recording drives. Changes you Apply in
   GParted take effect immediately, even if you later cancel installation.
3. Select one OS drive or **two mirrored boot drives**. The OS installation
   replaces all partitions on those whole drives. GParted-created partitions
   on the selected OS drives are also replaced. The mirror uses Linux RAID1
   for system and default data; ZFS recording pools are configured afterward.
4. Create the PlainNVR administrator, or choose **Set up later in the web UI**.
5. Review the exact drives and type **ERASE**, then click **Install PlainNVR
   OS**. Debian Installer runs inside the same desktop and displays progress.
   Use drives of at least 80 GB each; 128 GB or larger is recommended.
   The layout reserves 32 GB each for OS A and B, about 1 GB for boot files,
   and the remainder for shared data. A single 500 GB SSD is supported.
   Mirrored installs have no swap partition; 8 GB RAM is recommended.
6. Reboot and remove the USB. The monitor shows the storage/directory setup
   wizard and its LAN address on port 8790. If you deferred account creation,
   enter the one-time code shown on that monitor when connecting remotely.
   If you created an administrator during installation, sign in with it to
   finish setup. Remote GParted launch is disabled; it uses the local monitor.
7. After setup, sign in normally. PlainNVR is available from the LAN on port
   8787. The kiosk requires login again after each reboot.

The **Diagnostics** button shows input-device, graphics and installer logs,
also saved to `/run/plainnvr-installer-diagnostics.txt` for that live session.
The advanced Debian text installer remains available for manual installations
and maintenance-account creation. The guided live wizard creates the PlainNVR
application administrator only; Linux root and password login remain locked.

Revision 3 uses GRUB's firmware console without loading its graphical terminal
or changing video mode. Legacy BIOS uses the SYSLINUX text menu. If a USB
keyboard is unavailable only at the boot menu, leave it untouched for the
countdown so Linux can take over input. A firmware/bootloader hang can still
prevent the countdown. The owner subsequently confirmed revision 3 installed successfully on the HP 200 G1.

The installer image carries its OS and application packages; installation does
not require downloading PlainNVR. Network configuration can use Ethernet DHCP.
Firmware is included for common graphics and network devices.

## First-boot storage

The setup service on port 8790 closes after successful setup. Guided live
installations enable LAN setup; creating a new administrator remotely requires
the one-time code displayed locally. An existing administrator can sign in
directly. Storage operations require administrator authentication. The normal
NVR service remains gated until configuration is
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
- An SMB 3 network share, with explicit acknowledgement of reduced performance
  and network-outage risks. Credentials stay in a root-only file and the
  configuration database stays on local storage.

The configuration database stays on the installed persistent data filesystem.
ZFS is supported for recording pools; the boot filesystem uses ext4/RAID1.
The recording mount is asserted by systemd so a missing disk or unimported pool
cannot redirect recordings onto the OS filesystem.

GParted is integrated into the live installation wizard and local first-boot setup.
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
