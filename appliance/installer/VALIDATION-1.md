# Installer validation — September 26, 2026

Development image: `plainnvr-os-0.1.4-amd64.hybrid.iso`

SHA-256: `f34575334237dc24ffc41a9ac446026d1f39158c307de19a3493d0db3c5a9855`

Build: Debian 13 amd64, live-build 20250505+deb13u1, kernel
6.12.107+deb13-amd64, ZFS 2.3.9, native go2rtc 1.9.14 and FFmpeg 9.0.2.
Preserve the adjacent `.packages` manifest for exact Debian package versions.

## Completed checks

- Nine Python tests: local setup origin/Host boundary, authentication,
  administrator replacement, completed-setup lockout, directory traversal,
  symlinks, directory overlap, and explicit ZFS disk selection/confirmation.
- Shell syntax, Python compilation, and Git whitespace checks.
- ISO El Torito entries for BIOS and UEFI; Windows delivery checksum matches.
- Embedded setup Python/HTML and boot-mirror helper match the source files.
- Clean root contains the two nologin appliance service accounts. No test
  credentials, pending administrator hash, setup-complete marker, recording
  database, SSH test key or builder DKMS signing key is included.
- Final ISO UEFI boot menu and live GParted start successfully on blank disks.
- Initial image UEFI installation onto one blank 40 GiB disk: separate system
  and persistent-data partitions, with two extra 3 GiB disks left untouched.
- First-boot account creation, storage selection, local GParted launch/return,
  and normal PlainNVR login after setup. Startup fixes found in these tests
  are included in the final image.
- New ZFS recording mirror on the two explicitly selected extra drives.
  Recorded MP4 files contain H.264 video and AAC audio. Recordings and the
  mounted pool survive reboot, and recording resumes.
- Exporting the test recording pool makes the NVR mount assertion refuse
  startup. It writes no recording files into the unmounted directory. Import
  restores service.
- Existing-pool import creates a separate new dataset and preserves the
  original dataset and its 53 recording files.
- BIOS installation onto two 40 GiB disks: healthy RAID1 system/data arrays.
  With each disk independently absent, the surviving disk boots into first
  setup. Setup also completes using default storage on the second disk alone.
  Tests used isolated overlays, preserving the healthy original mirror.

## Final UEFI mirror check

Graphical installation onto two blank 40 GiB drives completed without manual
installer repairs. First boot showed administrator creation before storage
selection. Setup completed with custom configuration/recording directories;
administrator API login returned HTTP 200. Both root/data arrays were healthy,
both EFI loader copies were present, and the boot-mirror service succeeded.

Independent overlays of the installed drives were booted with only drive A,
then only drive B available. Each test started with fresh firmware variables,
using the disk's fallback EFI loader. Both reached the normal kiosk login,
started PlainNVR, and accepted the administrator login over the forwarded LAN
port (HTTP 200). Both arrays operated degraded with the intended surviving
member, the surviving EFI partition mounted, and custom directories persisted.
The VM's NIC/controller topology was kept consistent with the installed VM so
the interface name stayed unchanged when removing a disk.

The installed payload was tested from image SHA-256
`7e73c1d7eb8f254ee97c4640f924159cad682f3426e1cd05d8bde4523ed3a784`.
The delivered image above contains the same filesystem and installer payload.
Its final binary-stage rebuild adds the missing legacy-BIOS GParted menu entry
and refreshes ISO checksums; the live-build hook now uses its actual working
directory. The delivered BIOS menu and GParted boot were checked separately.

## Still required before a production release

Physical-PC graphics and sustained camera/decoding load; WebRTC ICE over both
TCP and UDP; retention behavior; Docker regression; Secure Boot enrollment and
update validation; drive-replacement recovery; and a supported production
update/rollback mechanism. RAIDZ1/RAIDZ2 options are present but have not received
the same VM integration pass as ZFS mirror creation/import. These VM results
do not establish physical-hardware compatibility.
