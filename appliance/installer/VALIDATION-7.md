# Installer revision 7 validation — September 27, 2026

## Startup failure

The owner reported a completed installation followed by the old kiosk waiting
page indefinitely. The Build 6 ISO in Downloads (SHA-256 `d595055b...`) lacks the
explicit shared-directory traversal fix. This prevents the kiosk user from
reading the first-boot marker while setup can still run separately. The HP
itself has not been inspected: its previous address, 192.168.1.116, did not
answer setup/dashboard requests or neighbor discovery during this work.

Build 7 preserves explicit directory permissions and routes the kiosk by
probing both setup and NVR. A local diagnostics page works independently of
either server. Its root collector publishes a restricted, redacted report to
the kiosk group; journals are bounded to 64 MB and seven days per OS slot.

## Checks against the final ISO

Artifact SHA-256:
`770279e3f1346b0fb4c3ecc9dcb68182caa24d6c220b4895b4e834b560cd4b8a`

File: `C:\Users\Zack\Downloads\PlainNVR-OS\plainnvr-os-0.2.0-installer7-amd64.hybrid.iso`
(2,040,823,808 bytes). The Windows copy's SHA-256 matches the builder output.

- 46 appliance tests passed, including recovery path/symlink checks, device
  mapping, refusing writes if the second slot is invalid, umask 077, redaction,
  and the existing setup/storage/update tests.
- Booted the final hybrid ISO as a USB disk under SeaBIOS/KVM with USB keyboard
  and tablet input. Recovery detected an earlier 500 GB single-drive A/B system
  with `/persist/system` deliberately restored to mode 0700.
- The actual GTK recovery action repaired it and installed diagnostics into
  both A and B. A read-only disk inspection verified modes 0711/0711/0755 for
  the data root/system/config, both diagnostic timers, and journald settings.
- A pre-existing recording fixture retained SHA-256
  `e9bf58cde37f314a4b1c82731bb101c7a4438012b26c0479649f8028a72fc3d1`.
- The recovery dialog's Save log dump action wrote a 167,082-byte report.
- Booting the repaired disk without the USB automatically opened account
  setup. Remote pairing, administrator creation, recording-directory selection,
  NVR health/login, authenticated files and LAN address reporting passed.
  SSH was disabled by default; a test key was enabled through the normal OS API
  for subsequent inspection.
- With both web services deliberately unavailable, the local diagnostics link
  opened successfully. Save log dump produced a 15,348-byte text file in the
  kiosk Downloads directory. The collector exited successfully; journals used
  16 MB. These tests used disposable VMs only.
- A subsequent normal reboot restored all services, retained the recording
  fixture and prior-boot journals, and passed the 32 GB/32 GB/shared-data layout,
  ownership, A/B health and no-failed-units checks.

## Fresh installation

The final ISO completed the entire live wizard and Debian Installer on a
blank 500,000,000,000-byte virtual disk, including the previously failing late
command. The wizard displayed **Installation finished**. Read-only inspection
confirmed shared-volume modes 0711/0711/0755 and the kiosk's A/B ordering.

Booting from the installed disk with the USB removed automatically opened the
administrator setup page. Remote pairing, administrator creation, installed
recording storage and directory selection completed successfully. NVR health,
administrator login, OS controls, authenticated file listing and LAN address
reporting passed; factory SSH was disabled. The kiosk automatically transitioned
to the normal login screen. No manual permissions fix or service override was
applied to this clean installation.

## Limits

The owner subsequently ran Build 7 recovery on the HP: its dialog reported
success, but after USB removal the machine fell through to Realtek PXE and
reported no boot disk. Build 7 only repaired permissions and diagnostics; it
did not repair boot code or register a firmware entry. A Build 7 live USB photo
then confirmed one 500 GB SSD with GPT BIOS and EFI boot partitions, 29.8 GiB
A/B ext4 slots, a 405.1 GiB ext4 shared volume, and **UEFI** live boot. The
physical SSD remains unverified until a later bootloader repair test.

This recovery tool intentionally
supports a single-drive A/B installation only; mirrored and legacy single-root
layouts are refused. This pass does not establish mirrored-drive failure
recovery, UEFI/Secure Boot behavior, long-running physical recording, ZFS or SMB
load, or GitHub release publication. A log export destination must be writable;
the ISO filesystem is read-only. Old volatile logs cannot be reconstructed
after shutdown.
