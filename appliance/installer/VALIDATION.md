# Installer revision 2 validation — September 26, 2026

## Artifact

- `plainnvr-os-0.1.4-installer2-amd64.hybrid.iso`
- Size: 2,032,828,416 bytes.
- SHA-256: `332a41a8bbeeb3a58c8963082be6d8ea04833edb0df4d8d71fbd5b265f827fc5`
- Windows copy: `C:\Users\Zack\Downloads\PlainNVR-OS`.
- Debian package manifest is distributed alongside the ISO.
- Revision 1's record is preserved in `VALIDATION-1.md`.

## Reason for revision

The owner reported that the original image froze at the GRUB Install choice
on an older HP PC, likely using Intel HD graphics. Its separate GParted entry
booted, but the mouse was unusable. Revision 2 uses the live boot path, Openbox,
explicit Xorg input support, a visible pointer, boot status messages, and a
`nomodeset` compatibility entry. The HP has not yet been retested; these VM
results do not establish its physical graphics/input compatibility.

## Completed checks on the final ISO

| Configuration | Result |
| --- | --- |
| UEFI, normal graphics, two 48 GB OS disks, admin during installation | Full installation completed; installed system booted; administrator login and storage setup passed. |
| Legacy BIOS, ISO attached as USB storage, compatibility graphics, one 48 GB OS disk, deferred admin | Full installation completed; installed system booted; remote claim-code pairing, administrator creation and storage setup passed. |

Both paths exercised locale selection, automatic GParted launch, mouse input,
closing GParted back into the wizard, drive selection, the typed erase review,
and visible installation progress. The mounted installer USB was excluded
from installation targets. Installation did not repeat network or Linux-user
questions. First boot obtained a wired DHCP address.

Both installed systems completed storage setup using custom `config-verified`
and `recordings-verified` directories on the installed data filesystem. OS
disks were excluded from available blank recording disks. Remote GParted
launch was rejected. The local monitor automatically changed to the normal
NVR login after remote setup. NVR health and administrator login passed;
the temporary setup listener closed afterward while the NVR stayed healthy.

During reboot validation, the test harness initially removed the live medium
before shutdown began. Restoring it and rebooting through the console recovered
both test systems. Media was removed at the bootloader before installed-system
checks; the BIOS VM was reset there to select its installed disk.

## Mirrored-drive failover

After a clean shutdown, each installed mirror member was booted alone using
fresh UEFI variables and a separate disposable overlay. Both reached the
normal NVR login, passed the health check, and accepted the administrator
created during installation. No firmware boot entry from installation was
required. Degraded-array startup took longer than the normal two-drive boot.
BIOS mirror failover has not been exercised in this revision.

## Automated and image checks

- Seventeen Python tests pass: setup origin/Host and authentication boundaries,
  remote claim-code enforcement, changed/mounted/USB disk rejection, distinct
  mirror members, locale injection, offline locked-account configuration,
  storage path and ZFS-selection safety, and empty removable-drive discovery.
- Shell syntax and Python compilation checks pass.
- Embedded installer/setup sources match the build source. The Windows ISO
  SHA-256 matches the Linux build output.
- Factory image checks exclude validation accounts, administrator settings,
  claim codes, SSH keys, machine identity and private DKMS signing keys.
  Privileged image files have root ownership and executable entry points.

## Integration fixes found during testing

APT now uses the mounted live medium without unmounting it. The guided path
configures wired DHCP in the installed target and locks Linux password
accounts. EFI discovery probes partition metadata directly when the live
installer lacks udev properties. Empty removable devices no longer break
storage discovery. Installer diagnostics retain the installation log.

## Remaining validation

Physical-PC graphics/input and sustained camera load; WebRTC ICE/TCP/UDP;
retention; Docker regression; Secure Boot enrollment and updates; drive
replacement; and a supported production update/rollback process remain
release work. ZFS mirror creation/import/recording passed in revision 1;
those integration checks were not repeated in revision 2. RAIDZ1/RAIDZ2 have
not had that integration pass. This remains a development image.
