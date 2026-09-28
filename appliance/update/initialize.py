#!/usr/bin/python3
"""Called once inside the freshly installed target by Debian Installer."""
import os
import json
import pwd
import re
import shutil
from pathlib import Path
from common import run, save, device_ref
from slots import configure_root, copy_kernel, grub_config


def grub_bootstrap(uuid):
    """Load the A/B menu even when EFI GRUB embeds /boot/grub as prefix."""
    if not re.fullmatch(r'[A-Fa-f0-9-]+', uuid):
        raise RuntimeError('Invalid EFI partition UUID.')
    return ('insmod part_gpt\ninsmod fat\ninsmod search_fs_uuid\n'
            f'search --no-floppy --fs-uuid --set=root {uuid}\n'
            'set prefix=($root)/grub\nconfigfile $prefix/grub.cfg\n')


def prepare_esp(disk):
    """Identify the guided recipe's boot partition, probing outside udev caches.

    partman-efi creates FAT at /boot/efi in a BIOS install but can leave its
    GPT type as Linux data. Only normalize partition 2 of a verified OS disk,
    with the recipe's filesystem and size, before installing either loader.
    """
    tree = json.loads(run('lsblk', '-Jpo', 'NAME,TYPE', disk))['blockdevices'][0]
    candidates = []
    for node in tree.get('children', []):
        if node.get('type') != 'part': continue
        props = dict(line.split('=', 1) for line in
                     run('blkid', '-p', '-o', 'export', node['name'], check=False).splitlines() if '=' in line)
        if props.get('PART_ENTRY_NUMBER') == '2': candidates.append((node['name'], props))
    if len(candidates) != 1: raise RuntimeError(f'Missing guided boot partition on {disk}.')
    device, props = candidates[0]
    esp_type = 'c12a7328-f81f-11d2-ba4b-00a0c93ec93b'
    linux_type = '0fc63daf-8483-4772-8e79-3d69d8477de4'
    if (props.get('PART_ENTRY_SCHEME') != 'gpt' or props.get('TYPE') != 'vfat'
            or props.get('PART_ENTRY_TYPE') not in (esp_type, linux_type)
            or not 1_000_000_000 <= int(run('blockdev', '--getsize64', device)) <= 1_100_000_000):
        raise RuntimeError(f'{device} does not match the guided 1 GB FAT boot partition.')
    if props['PART_ENTRY_TYPE'] != esp_type:
        run('parted', '--script', disk, 'set', '2', 'esp', 'on')
    if run('blkid', '-p', '-s', 'PART_ENTRY_TYPE', '-o', 'value', device) != esp_type:
        raise RuntimeError(f'Cannot set the EFI partition type on {device}.')
    return device


def initialize():
    root_b = Path('/mnt/plainnvr-slot-b')
    if Path('/etc/plainnvr/ab.json').exists(): raise RuntimeError('A/B layout already initialized.')
    for path in ('/', '/var/lib/plainnvr', str(root_b)):
        if run('findmnt', '-nro', 'FSTYPE', '--mountpoint', path) != 'ext4':
            raise RuntimeError('The A/B installer requires two ext4 roots and an ext4 data filesystem.')
    devices = {slot: run('findmnt', '-nro', 'SOURCE', '--mountpoint', path)
               for slot, path in [('A', '/'), ('B', str(root_b))]}
    data = run('findmnt', '-nro', 'SOURCE', '--mountpoint', '/var/lib/plainnvr')
    if len({*devices.values(), data}) != 3: raise RuntimeError('Overlapping A/B layout.')
    # 32 decimal GB per OS slot, matching the guided partition recipe.
    for device in devices.values():
        size = int(run('blockdev', '--getsize64', device))
        if not 31_900_000_000 <= size <= 32_100_000_000:
            raise RuntimeError('Each system slot must be 32 GB.')
    mirror = Path('/etc/plainnvr/mirror-selected').exists()
    disks = set()
    for row in run('lsblk', '--inverse', '--raw', '--noheadings', '--paths', '-o', 'NAME,TYPE', devices['A']).splitlines():
        fields = row.split()
        if fields[1] == 'disk': disks.add(fields[0])
    if len(disks) != (2 if mirror else 1): raise RuntimeError('Unexpected system disk count.')
    if mirror and disks != set(Path('/etc/plainnvr/mirror-selected').read_text().split()):
        raise RuntimeError('System disks do not match the reviewed drive selection.')
    esp_devices = []
    for disk in sorted(disks):
        esp_devices.append((disk, prepare_esp(disk)))
    config = {'layout': 1, 'mirror': mirror, 'slots': {k: device_ref(v) for k, v in devices.items()},
              'data_device': device_ref(data),
              'esp_uuids': [run('blkid', '-s', 'UUID', '-o', 'value', p) for _, p in esp_devices]}
    if mirror:
        arrays = [run('mdadm', '--detail', '--scan', dev) for dev in [*devices.values(), data]]
        Path('/etc/mdadm/mdadm.conf').write_text('HOMEHOST <system>\nMAILADDR root\n' + '\n'.join(arrays) + '\n')
    original_fstab = Path('/etc/fstab').read_text()
    mount = Path('/var/lib/plainnvr')
    (mount / 'nvr').mkdir(mode=0o700)
    for child in list(mount.iterdir()):
        if child.name not in ('nvr', 'lost+found'): shutil.move(str(child), mount / 'nvr' / child.name)
    user = pwd.getpwnam('plainnvr')
    os.chown(mount / 'nvr', user.pw_uid, user.pw_gid)
    (mount / 'system').mkdir(mode=0o711)
    # d-i uses umask 077: mkdir(mode=...) alone removes traversal permissions.
    # The kiosk must reach public setup markers and OpenSSH its public keys.
    (mount / 'system').chmod(0o711)
    for source, name in [('/etc/plainnvr', 'config'), ('/var/lib/plainnvr-setup', 'setup'),
                         ('/var/lib/plainnvr-control', 'control')]:
        if Path(source).exists(): shutil.copytree(source, mount / 'system' / name, symlinks=True)
        else: (mount / 'system' / name).mkdir(mode=0o700)
    (mount / 'system/config').chmod(0o755)
    save(mount / 'system/config/ab.json', config)
    save(mount / 'system/config/update-source.json', {'repository': 'endless1233214/plainnvr', 'channel': 'stable'})
    version = Path('/usr/lib/plainnvr/update/VERSION').read_text().strip()
    save(mount / 'system/update/slots.json', {slot: {'version': version, 'healthy': False} for slot in ('A', 'B')})
    mount.chmod(0o711); os.chown(mount, 0, 0)
    Path('/persist').mkdir(exist_ok=True)
    run('mount', '--bind', mount, '/persist')
    run('umount', mount)
    run('mount', '--bind', '/persist/nvr', mount)
    configure_root('/', config, 'A', original_fstab)
    run('update-initramfs', '-u', '-k', 'all', timeout=600)
    run('rsync', '-aHAXx', '--exclude=/mnt/plainnvr-slot-b/***', '--exclude=/persist/***',
        '--exclude=/var/lib/plainnvr/***', '--exclude=/proc/***', '--exclude=/sys/***',
        '--exclude=/dev/***', '--exclude=/run/***', '/', str(root_b) + '/', timeout=900)
    configure_root(root_b, config, 'B', original_fstab)
    # Firmware-independent bootloaders and independent environment blocks on
    # every ESP allow either mirror member to boot without GRUB writing RAID.
    run('umount', '/boot/efi', check=False)
    for index, (disk, esp) in enumerate(esp_devices):
        destination = Path('/run/plainnvr-install-esp'); destination.mkdir(exist_ok=True)
        run('mount', esp, destination)
        try:
            run('grub-install', '--target=i386-pc', '--boot-directory=' + str(destination), '--recheck', disk)
            run('grub-install', '--target=x86_64-efi', '--efi-directory=' + str(destination),
                '--boot-directory=' + str(destination), '--removable', '--no-nvram', '--force')
            # Some UEFI firmware does not scan the removable fallback path on
            # internal drives. Register the primary SSD as an explicit boot
            # choice when the installer itself was booted in UEFI mode.
            if index == 0 and Path('/sys/firmware/efi/efivars').is_dir():
                run('grub-install', '--target=x86_64-efi', '--efi-directory=' + str(destination),
                    '--boot-directory=' + str(destination), '--bootloader-id=PlainNVR', '--force')
            copy_kernel('/', 'A', destination); copy_kernel(root_b, 'B', destination)
            (destination / 'grub/grub.cfg').write_text(grub_config(config))
            bootstrap = destination / 'boot/grub/grub.cfg'
            bootstrap.parent.mkdir(parents=True, exist_ok=True)
            bootstrap.write_text(grub_bootstrap(config['esp_uuids'][index]))
            run('grub-editenv', destination / 'grub/grubenv', 'create')
            run('grub-editenv', destination / 'grub/grubenv', 'set', 'ORDER=A B', 'PENDING=none', 'A_OK=1', 'A_TRY=0', 'B_OK=1', 'B_TRY=0')
            os.sync()
        finally: run('umount', destination)
    run('umount', root_b)
    os.sync()


if __name__ == '__main__': initialize()
