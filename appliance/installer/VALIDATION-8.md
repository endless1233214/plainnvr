# Installer Build 8 validation - September 28, 2026

## Final artifact

`C:\Users\Zack\Downloads\PlainNVR-OS\plainnvr-os-0.2.0-installer8-amd64.hybrid.iso`

SHA-256: `e7c0d0d6cbbfa85f1e21acfbc0a24455462efa2e13c8b3ed8427d6a5dd074458`.
Size: 2,040,823,808 bytes. This build includes the root GRUB fallback change;
an earlier internal Build 8 draft did not.

## Disposable VM checks

- All 50 appliance unit tests passed; Python source compiled.
- The final ISO contains the current recovery, diagnostics, and installer
  initialization files byte for byte. The live filesystem includes
  `efibootmgr`, and the Debian Installer late step requests it.
- The final ISO booted as a UEFI USB drive to the PlainNVR wizard, detected an
  existing 500 GB single-drive A/B installation, showed the selected `/dev/vda`
  and `/dev/vda2` at confirmation, and completed **Repair bootloader**.
- OVMF NVRAM then contained `PlainNVR` pointing to
  `\\EFI\\PlainNVR\\grubx64.efi`. With the USB removed, the repaired disk reached
  the PlainNVR login screen in both UEFI and SeaBIOS VM boots.
- Both installed root slots contained the same GRUB fallback. A separate UEFI
  VM test deliberately entered a stale root-menu path; that path chained to
  the A/B menu and reached login.
- SHA-256 of the existing application database, A/B configuration, and storage
  selection matched the untouched base disk after recovery. The repair did not
  change those files.

The final ISO has not completed a new blank-disk installation test or a physical
HP test. The physical checks below remain required before claiming the HP issue
resolved.

## Why this revision exists

The physical HP startup report showed a successful Linux boot from system A
with the expected A/B/shared-data partitions, but `plainnvr-ab-prepare` failed
because `/proc/cmdline` had no `rauc.slot=A/B`. The update safety check was
working correctly; the boot path had bypassed the canonical PlainNVR GRUB menu.

## Change

Build 8 keeps the canonical A/B menu and GRUB environment on the installer-
recorded EFI partition. It also writes a minimal `/boot/grub/grub.cfg` fallback
into both root slots. If older Debian BIOS/UEFI GRUB code enters either root
menu, that fallback searches only the recorded EFI filesystem UUIDs and loads
`/grub/grub.cfg`. The live-USB bootloader repair applies the same root fallback
to an existing single-drive A/B installation after validating both slots.

The userspace slot detector remains strict. It still requires the kernel to
receive exactly one `rauc.slot=A` or `rauc.slot=B`; there is no default-to-A
workaround.

Startup diagnostics now record the kernel command line, root mount source and
EFI boot entries so the next physical report identifies the actual path.

## Required physical validation

Build 8 is not physically validated until the exact built ISO/recovery flow proves on
the HP:

1. First installed/repaired boot includes `rauc.slot=A` in `/proc/cmdline`.
2. `plainnvr-ab-prepare` succeeds.
3. Setup or the configured PlainNVR server starts normally.
4. A normal reboot still identifies slot A.
5. A trial boot of B includes `rauc.slot=B`.
6. A deliberately failed B trial falls back to A and restores the database.
7. UEFI behavior remains functional in disposable VM validation.

Do not publish a release artifact from this note alone.
