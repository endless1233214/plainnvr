# Appliance management (installer revision 4)

These controls are part of PlainNVR OS. Docker installations continue to use
ordinary PlainNVR settings and do not receive access to their host OS.

## Find and administer the appliance

The attached login screen and dashboard display the current LAN URL, refreshed
every 15 seconds. The server listens on all interfaces on port 8787. The only
public OS information is this list of URLs; all other controls require a normal
PlainNVR login. OS actions additionally require the current password, granting
that browser session ten minutes of access. PlainNVR currently treats all its
users as administrators; there is no separate read-only OS role.

Settings contains System, Network, SSH, Storage, Tools and Logs sections:

- System: hostname, uptime, memory/load, Linux RAID status, timezone, NTP,
  restart and shutdown.
- Network: interface addresses, wired DHCP or static address/prefix, gateway
  and DNS. Changes require confirmation within 120 seconds. An independent
  systemd timer restores the previous configuration otherwise, including after
  a broker restart. Wi-Fi, bonds, bridges and VLAN configuration are not exposed.
- SSH: disabled in a fresh image. Enable key-only access as `plainnvr-admin`;
  this account has sudo access. Paste or select public keys, label them,
  enable/disable individual keys and remove them. Root/password SSH login is
  disabled. Host keys are generated on the appliance, never shipped in an ISO.
- Storage: disk/filesystem inventory, blank recording disk formatting as ext4,
  existing ext4/XFS selection, ZFS single/mirror/RAIDZ pool creation, exported
  pool import into a new dataset, pool status and scrub. Guided operations
  exclude system disks. Destructive operations require explicit confirmation.
  GParted remains a local administrator tool with its own full disk access.
- Tools: authenticated browser file manager and root terminal. On the attached
  monitor, PCManFM, xterm and GParted are also available; closing a desktop tool
  returns to the kiosk. Remote desktop launching is intentionally unavailable.
- Logs: recent NVR, OS broker, SSH, network and boot mirror service entries.

Browser terminals expire after five minutes without input, have bounded output,
and cannot be accessed from another login session. The file manager supports
browsing, exclusive uploads, downloads, directory creation, same-directory
renames and deletion of individual files or empty directories. Browser file
transfers are limited to 512 KiB; use SSH/SFTP for larger transfers or the
normal recording download interface. There is no recursive deletion.

## SMB recording storage

SMB is available in both first-boot storage setup and Settings > Storage.
Specify the server, share name, account, password and optional domain. The UI
requires acknowledgment that performance can be lower and network/NAS outages
can interrupt recording. SMB 3 is required; SMB1 and anonymous guest mounts
are not provided. Credentials are stored in root-only files and excluded from
API responses and setup journals. The configuration database remains local.

An actual address is required before systemd mounts SMB during boot. Recordings
are written as the unprivileged `plainnvr` user after a write/fsync check.
Mount dependencies and mount-point assertions prevent writing to an underlying
OS directory when storage is absent. A missing recording mount prevents the
NVR (including its dashboard) from starting; restore the share/mount and restart
PlainNVR from SSH or the local maintenance console. This release does not yet
provide an independent web recovery console or automatic NAS outage recovery.

Changing a recording destination briefly restarts PlainNVR. Existing recordings
remain on the old destination. Select that saved destination again to browse
and play them; automatic migration and a merged multi-volume timeline are not
implemented. A failed switch restores the previous runtime configuration if
the NVR had already been stopped. ZFS pool replacement/expansion/export and
boot-mirror repair remain maintenance-console operations.

## Implementation

The NVR runs unprivileged and forwards authenticated operations to
`plainnvr-control.service` over a root-owned Unix socket. The broker checks the
peer UID, binds short-lived grants to a browser session, validates structured
arguments and executes explicit operations. There is no network-listening root
management daemon. Root terminal and file access require an unlocked grant.
The terminal renderer is a pinned, integrity-verified local xterm.js asset.

OTA updates are not implemented in revision 4. See `UPDATES.md` for the proposed
release/update design; an installer ISO is not an in-place updater.
