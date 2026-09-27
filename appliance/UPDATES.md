# Installed-system update design

Status: proposed, not implemented. Revision 4 has no OTA update button or
native GitHub release workflow. The existing GitHub Actions workflow builds
Docker images. Do not reinstall an ISO to perform a routine application update.

## Recommended first release

Publish versioned native bundles and a signed manifest as GitHub Release assets.
Use a separate appliance version/revision from the underlying NVR app version.
The appliance pins the update verification public key; the signing private key
stays in a protected release environment. A checksum alone is not a signature.

Settings > Updates should display installed/available versions, release notes,
channel and reboot requirements. Check and download in advance; install only
when the administrator chooses a maintenance window. Do not update cameras or
storage configuration, repartition disks, or reboot automatically.

The updater must validate signature, size/hash, target architecture, required
OS version and bundle paths before extraction. Stage a new immutable release,
back up the configuration database consistently, stop recording, apply compatible
migrations and activate the release atomically. Start services and run a bounded
health check. Restore the previous release and database on failure. Test power
loss and failed migrations before shipping. OS management files/services need
transactional backup and restore too, not just the application symlink.

Debian package/security updates should be a separate explicit maintenance action.
Keep the previous kernel; validate DKMS/ZFS and boot mirror updates before reboot.
Package updates do not provide automatic full-system rollback.

## Accepted layout target for full OS rollback

The owner approved two 32 GB OS slots, small boot/recovery partitions, and the remaining space for shared recordings on a single boot drive. Shared configuration must survive either slot being replaced. This is the target for the OTA work; revision 4 still uses the existing single-root layout.

A/B root filesystem slots plus boot-success tracking can retain a previous OS
and boot it after a failed upgrade. This requires an installer layout and boot
integration change, tested with both UEFI and legacy BIOS and mirrored boot
hardware. Mirrored disks protect against a disk failure; they are not A/B OS
slots. Existing single-root installations need a planned migration rather than
an automatic repartition during an update.

References:
- GitHub release discovery and assets: https://docs.github.com/en/rest/releases/releases
- Release asset metadata/downloads: https://docs.github.com/en/rest/releases/assets
- RAUC signed bundles and system slots: https://rauc.io/ and https://rauc.readthedocs.io/en/latest/reference.html
