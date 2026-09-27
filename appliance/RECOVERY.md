# Startup recovery and log dumps

Build 7 adds recovery for the single-drive A/B startup-permissions issue in
the earlier Build 6 image. It repairs the existing installation; it does not
repartition the SSD or replace recordings, accounts or the application database.

## Existing installation stuck at the kiosk

1. Boot the Build 7 USB into the normal live installer wizard.
2. On the first page, choose **Recover existing installation**. Do not advance
   to drive erasure. Recovery displays the detected installed shared-data volume.
3. Review the report. **Save log dump…** exports it to a chosen path, such as a
   mounted writable USB drive. The installer ISO itself is read-only.
4. Choose **Repair startup + add diagnostics** and confirm the shown volume.
   The tool validates both OS slots before writing, fixes traversal permissions,
   and installs local diagnostics and bounded persistent logging into both slots.
5. After success, choose **Reboot (remove USB)** and remove the installer USB.
   First boot should open account/storage setup, or the dashboard if configured.

This repair supports one-drive PlainNVR A/B installations. Mirrored layouts and
older single-root installations require separate recovery work. Already mounted
partitions are refused; close other disk tools first.

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
