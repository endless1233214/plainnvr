# Installer revision 3 validation - September 26, 2026

## Artifact

- `plainnvr-os-0.1.4-installer3-amd64.hybrid.iso`
- Size: 2,032,828,416 bytes.
- SHA-256: `d4c54a9ff034d42f6cfd402fd5cf006fb8e16def916b1f8c28f8300d27dba871`
- Windows directory: `C:\Users\Zack\Downloads\PlainNVR-OS`.

## Hardware report and scope

The owner identified the affected machine as HP 200 G1 MT, Intel Pentium
J2900 at 2.41 GHz, 8192 MB DDR3, motherboard ID 2B1A, BIOS SHA v80.08 dated
July 18, 2014. The keyboard is USB directly into the motherboard. BIOS input
works, but installer 2's boot menu is unresponsive. A photograph of that menu
was unavailable, so whether this is lost keyboard input or a complete
bootloader hang remains unconfirmed.

Inspection found that revision 2 sourced live-build's graphical GRUB console
configuration before applying text payload settings inside its menu entries.
It also waited indefinitely for input. Revision 3 replaces that initialization
with the native firmware console and a visible 10-second menu timeout. BIOS
uses `menu.c32` instead of `vesamenu.c32`, also with a 10-second timeout. The
default action starts the live wizard; drive changes still require explicit
selection and confirmation later.

## Image checks

The live squashfs, live kernel/initrd, and text Debian Installer kernel/initrd
were checked unchanged by SHA-256 against revision 2's validated build tree.
Only boot-menu files and the added BIOS text-menu module changed in the ISO,
plus generated checksums. GRUB syntax checks passed. The copied Windows ISO
hash matches the build output. The package manifest is unchanged.

Revision 2's full UEFI mirrored and BIOS single-drive installs, administrator
and storage setup, and independent UEFI mirror-member boot are recorded in
`VALIDATION-2.md`. Full installation was not repeated for this boot-menu-only
revision. Revision 1's record is in `VALIDATION-1.md`.

## Boot/input checks

Disposable QEMU/KVM guests used UEFI/OVMF and legacy BIOS/SeaBIOS, each booting
the final ISO as USB storage. The PS/2 controller was disabled (`i8042=off`);
input devices were a USB keyboard and USB tablet.

- Both menus timed out and reached the locale wizard with no keys sent.
- On a second boot, the USB Down key selected the compatibility entry in both
  menus, stopping the countdown. Screenshots confirmed the selected entry.
- Enter booted the compatibility entry into the locale wizard on both systems.

## Limits

### Physical laptop report - September 27, 2026

The owner reported successful testing of revisions 1 and 2 on the current
development laptop. Revision 2 reached GParted; the test stopped there to
preserve existing data. Revision 1's exact stopping point was not specified.
No physical installation/formatting or revision-3 result was reported. This
supports a machine-dependent compatibility investigation for the HP; it does
not identify the failing firmware/bootloader/input component.

The HP still needs a physical retest. These changes remove graphical GRUB
initialization and indefinite waiting; they do not establish the exact cause
of its firmware/input failure. No BIOS update was attempted. Previous remaining
production-release checks in `VALIDATION-2.md` still apply.
