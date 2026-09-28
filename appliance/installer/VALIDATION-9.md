# Installer revision 9 validation - September 27, 2026

## Why this revision exists

The physical HP startup report showed a successful Linux boot from system A
with the expected A/B/shared-data partitions, but `plainnvr-ab-prepare` failed
because `/proc/cmdline` had no `rauc.slot=A/B`. The update safety check was
working correctly; the boot path had bypassed the canonical PlainNVR GRUB menu.

## Change

Revision 9 keeps the canonical A/B menu and GRUB environment on the installer-
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

Revision 9 is not validated until the exact built ISO/recovery flow proves on
the HP:

1. First installed/repaired boot includes `rauc.slot=A` in `/proc/cmdline`.
2. `plainnvr-ab-prepare` succeeds.
3. Setup or the configured PlainNVR server starts normally.
4. A normal reboot still identifies slot A.
5. A trial boot of B includes `rauc.slot=B`.
6. A deliberately failed B trial falls back to A and restores the database.
7. UEFI behavior remains functional in disposable VM validation.

Do not publish a release artifact from this note alone.
