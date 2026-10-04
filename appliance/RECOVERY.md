# Startup recovery and log dumps

Build 8 includes bootloader repair after physical diagnostics showed
the HP could boot Linux without the required `rauc.slot=A/B` kernel argument.
The repair now also redirects stale GRUB menus on both OS roots into the
canonical PlainNVR A/B menu. Neither action repartitions the SSD or replaces
recordings, accounts or the application database.

## Existing installation stuck at the kiosk

1. Boot the Build 8 USB into the normal live installer wizard.
2. On the first page, choose **Recover existing installation**. Do not advance
   to drive erasure. Recovery displays the detected installed shared-data volume.
3. Review the report. **Save log dump…** exports it to a chosen path, such as a
   mounted writable USB drive. The installer ISO itself is read-only.
4. If the installed SSD falls through to PXE or reports no boot disk, choose
   **Repair bootloader**. Review the exact SSD and EFI partition shown in the
   confirmation. The tool validates the existing A/B roots and boot files,
   reinstalls BIOS and UEFI GRUB, registers a UEFI firmware entry when the
   live USB was booted in UEFI mode, and rewrites the stale root GRUB menus in
   both OS slots so every known boot path reaches the PlainNVR A/B menu.
5. If the SSD boots but the kiosk remains at **PlainNVR is starting**, choose
   **Repair startup + add diagnostics**. This repairs directory permissions and
   installs local diagnostics and bounded persistent logging into both slots.
6. After the chosen repair succeeds, choose **Reboot (remove USB)** and remove
   the installer USB.
   First boot should open account/storage setup, or the dashboard if configured.

These repairs support one-drive PlainNVR A/B installations. Mirrored layouts and
older single-root installations require separate recovery work. Already mounted
partitions are refused; close other disk tools first.

The HP 200 G1 MT later booted Linux on system A, but that boot lacked the
required `rauc.slot` argument. Build 8 has not yet been tested on the HP. If it
still falls through to PXE after a successful bootloader repair, check whether HP
firmware detects the SSD and includes it in UEFI/legacy boot order. A firmware
entry cannot compensate for a missing or undetected drive. On this HP, the USB
keyboard currently starts working only after Debian loads, so firmware setup
may require another compatible keyboard or a working preboot USB setting.

## Logs without a running NVR server

The local startup page offers **View startup diagnostics / save log dump**.
It works from local files even when the setup or recording server is unavailable.
After 30 seconds without a service, the page changes to **PlainNVR needs attention**.

Reports refresh every 30 seconds at `/run/plainnvr-support/`. The report shows
service exit status, relevant journals, mount information, directory permissions
and local addresses. **Save log dump** downloads a text copy to the kiosk user's
Downloads folder, normally `/var/lib/plainnvr-kiosk/Downloads`.

The live USB recovery dialog also reads persistent installed-system journals and
the installer log. Journals are capped at 64 MB and seven days per OS slot. Old
builds may have kept boot journals only in RAM; logs lost after shutdown cannot
be reconstructed. No configuration files, account databases or keys are included
in a report. Common credential lines and URLs are removed; review reports before
sharing because hardware details and local addresses remain.
