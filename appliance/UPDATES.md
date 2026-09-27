# Installed-system update design

Status: revision 5 failed full installation on the owner's single-drive HP.
Its earlier validation only reached the live wizard and was insufficient.
Revision 6 corrects the BIOS boot partition type, restores both firmware GRUB
module packages, and fixes persistent management state. Full install and A/B
update validation is in progress. The existing GitHub repository remains the
release source; check, download, install, restart, and rollback are separate
Settings actions. Revision 4 installations require a backed-up reinstall to
adopt the two-slot layout.

## Recommended first release

Publish versioned native bundles and a signed manifest as GitHub Release assets.
Use a separate appliance version/revision from the underlying NVR app version.
The appliance pins `appliance/update/release.pem`; the signing private key stays
in the protected GitHub Actions secret `PLAINNVR_OS_RELEASE_KEY`. A checksum
alone is not a signature. The release workflow only publishes tags matching
`os-vX.Y.Z`, and the tag must equal `appliance/update/VERSION`.

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

A/B root filesystem slots plus boot-success tracking retain a previous OS and
boot it after a failed upgrade. Each ESP gets an independent GRUB copy and
environment block, so a mirrored drive can start the appliance on its own.
Mirrored disks protect against a disk failure; they are not A/B OS slots.
Existing single-root installations need a planned migration rather than an
automatic repartition during an update.

## Revision 5 installer layout

The guided layout requires 80 GB and recommends 128 GB or more:

| Partition | Size | Purpose |
| --- | ---: | --- |
| BIOS GRUB | 1 MiB | Legacy firmware boot code |
| EFI System Partition | 1 GiB | UEFI boot code, both kernels and GRUB state |
| System A | 32 GB | Running or trial OS |
| System B | 32 GB | Inactive update or rollback OS |
| Shared data | Remaining space | Recordings, configuration, update state |

Two selected drives create RAID1 arrays for both system slots and shared data.
The installer puts a bootloader and independent boot state on every selected
drive. Recording pools such as ext4, XFS, ZFS, and SMB are configured after the
OS install and are not included in an OS bundle.

The withdrawn revision 5 artifact (do not use for new installations) is:

`plainnvr-os-0.2.0-installer5-amd64.hybrid.iso`

SHA-256:
`63685f7163f8d9c32bc9800d6b6c4411e482862acec99178792db15c0c7ea727`

The public release certificate fingerprint is:
`EB:B2:38:1B:0C:89:8C:6C:15:AD:70:FC:88:23:66:61:6C:C1:3B:00:14:28:14:ED:21:AD:67:CB:F4:8B:59:1C`.
Back up the private key separately before enabling the GitHub release workflow;
losing it makes future signed updates impossible for installed appliances.

References:
- GitHub release discovery and assets: https://docs.github.com/en/rest/releases/releases
- Release asset metadata/downloads: https://docs.github.com/en/rest/releases/assets
- RAUC signed bundles and system slots: https://rauc.io/ and https://rauc.readthedocs.io/en/latest/reference.html
