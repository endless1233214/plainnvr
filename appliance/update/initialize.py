#!/usr/bin/python3
"""Called once inside the freshly installed target by Debian Installer."""
import os
import pwd
import shutil
from pathlib import Path
from common import run, save, device_ref
from slots import configure_root, copy_kernel, grub_config


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
        import json
        tree = json.loads(run('lsblk', '-Jpo', 'NAME,PARTTYPE', disk))['blockdevices'][0]
        choices = [p['name'] for p in tree.get('children', [])
                   if p.get('parttype') == 'c12a7328-f81f-11d2-ba4b-00a0c93ec93b']
        if len(choices) != 1: raise RuntimeError('Each system disk must have one EFI partition.')
        esp_devices.append((disk, choices[0]))
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
    for source, name in [('/etc/plainnvr', 'config'), ('/var/lib/plainnvr-setup', 'setup'),
                         ('/var/lib/plainnvr-control', 'control')]:
        if Path(source).exists(): shutil.copytree(source, mount / 'system' / name, symlinks=True)
        else: (mount / 'system' / name).mkdir(mode=0o700)
    (mount / 'system/config').chmod(0o755)
    save(mount / 'system/config/ab.json', config)
    save(mount / 'system/config/update-source.json', {'repository': 'endless1233214/plainnvr', 'channel': 'stable'})
    version = Path('/usr/lib/plainnvr/update/VERSION').read_text().strip()
    save(mount / 'system/update/slots.json', {slot: {'version': version, 'healthy': True} for slot in ('A', 'B')})
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
    for disk, esp in esp_devices:
        destination = Path('/run/plainnvr-install-esp'); destination.mkdir(exist_ok=True)
        run('mount', esp, destination)
        try:
            run('grub-install', '--target=i386-pc', '--boot-directory=' + str(destination), '--recheck', disk)
            run('grub-install', '--target=x86_64-efi', '--efi-directory=' + str(destination),
                '--boot-directory=' + str(destination), '--removable', '--no-nvram', '--force')
            copy_kernel('/', 'A', destination); copy_kernel(root_b, 'B', destination)
            (destination / 'grub/grub.cfg').write_text(grub_config(config))
            run('grub-editenv', destination / 'grub/grubenv', 'create')
            run('grub-editenv', destination / 'grub/grubenv', 'set', 'ORDER=A B', 'PENDING=none', 'A_OK=1', 'A_TRY=0', 'B_OK=1', 'B_TRY=0')
            os.sync()
        finally: run('umount', destination)
    run('umount', root_b)
    os.sync()


if __name__ == '__main__': initialize()
