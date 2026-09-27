# Installer revision 4 validation - September 27, 2026

## Artifact

- File: `plainnvr-os-0.1.4-installer4-amd64.hybrid.iso`
- Size: 2,044,821,504 bytes.
- SHA-256: `cfdccad8e44335fd195bbf72bec600070decbc5e5b164ee108bd7851da3ac171`
- The copied Windows ISO hash matches the builder output.
Windows artifact directory: `C:\Users\Zack\Downloads\PlainNVR-OS`.

## Changes

SMB recording storage in first-boot setup and OS Settings; system, network,
SSH, storage and log controls; browser file manager and root terminal; local
PCManFM, xterm and GParted; visible LAN URLs; the existing PlainNVR camera icon
throughout the installer/setup/web interface. The OS partition layout and text
boot menus are unchanged from revision 3. OTA and A/B updates are not included.

## Automated checks

- 29 appliance and installer tests passed, including SMB credential handling,
  protected-disk selection, administrator grants, SSH key validation, network
  rollback and safe file operations. Repeated successfully after branding.
- 60 existing core Python tests passed.
- New browser JavaScript passed Node syntax checks.

## Disposable Debian VM integration

These checks used a separate development VM with disposable virtual disks and
an SMB fixture bound to that VM's loopback interface. No production recordings,
HP disks or NAS shares were modified.

- First-boot administrator and SMB setup completed. Configuration stayed local;
  the recording directory passed a write/fsync probe as the NVR service user.
- Settings created another SMB destination and switched back to the original.
- A synthetic RTSP camera produced playable H.264/AAC MP4 recordings on SMB.
  ffprobe inspected an 11-second recording.
- Stopping the recording mount stopped PlainNVR; the underlying mount directory
  remained empty. Restoring the mount/service resumed recordings.
- A blank test disk was formatted ext4, selected for recordings, and retained
  when switching back to SMB. A two-disk ZFS mirror was created, used and scrubbed.
- DHCP settings were applied and confirmed. A second unconfirmed change was
  restored by the real 120-second rollback timer.
- SSH enabled with an authorized public key; key login and sudo worked. Disabling
  SSH closed new SSH access. Re-enabling it restored access.
- Browser and API file create/upload/read/rename/delete operations passed.
- Root PTY output, input, resize, close, and session ownership checks passed.
  A browser terminal displayed output from a typed command.
- Unauthenticated access, wrong passwords, cross-origin requests and grants
  reused by a different browser session were rejected.
- Local PCManFM and xterm launched; closing each returned to the kiosk.
- The public address API exposed only appliance availability and LAN URLs.
  The unauthenticated login page displayed the supplied icon and LAN address.
- First-boot/SSH credentials and completed-setup state were absent from the
  image factory. SSH is disabled in the factory image.

## Final ISO installation

The exact branded ISO was booted as USB storage in a disposable SeaBIOS/KVM
guest with USB keyboard/tablet and PS/2 disabled. It automatically reached the
locale wizard, displayed the PlainNVR icon, opened GParted and returned to the
wizard, accepted one blank 48 GiB virtual disk and deferred administrator setup.
After explicit ERASE confirmation, Debian Installer completed successfully.
The VM was powered down and started from its installed disk with no ISO attached.

The branded first-boot account page appeared. Remote pairing, administrator
creation and default storage/directory selection completed. NVR health, normal
admin login, OS status, password unlock and privileged file listing passed.
The LAN address was displayed and SSH was disabled with no authorized keys.
A reboot requested through the authenticated OS API returned to the branded
login page; NVR health, admin login and the recording path persisted, with SSH
still disabled. Screenshots are saved in Downloads as revision4-installer.png,
revision4-login.png and revision4-installed.png.

## Hardware and remaining limits

The owner successfully installed revision 3 on the HP 200 G1 MT (Pentium J2900,
8 GB RAM) through first-boot setup and the main dashboard. Its confirmed URL
is http://192.168.1.116:8787/. Revision 4 has not been deployed to that HP.

Revision 2's full UEFI mirrored install and independent mirror-member boots are
recorded in VALIDATION-2.md; revision 3's BIOS/UEFI USB input checks are in
VALIDATION-3.md. Physical mirrored boot, ZFS and separate ext4 recording storage
still need testing, as do sustained physical SMB recording and outage recovery.

Browser file transfers are limited to 512 KiB. Existing recordings are retained
at their old destination and are not migrated. A missing recording mount stops
the NVR and its web dashboard; recovery currently uses SSH/local maintenance.
See ../MANAGEMENT.md for supported controls and limitations. The accepted future
OTA layout is two 32 GB OS slots plus boot/recovery and shared remaining space;
see ../UPDATES.md. It is not this installer's partition layout.
