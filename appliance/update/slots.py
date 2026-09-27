"""Prepare an installed root and boot payload without touching recordings."""
import os
import re
import shutil
from pathlib import Path
from common import run, save, load, esp_mounts

LIB = '/usr/lib/plainnvr/update'
# Only appliance-managed machine configuration is copied between OS versions.
MACHINE_PATHS = ['etc/hostname', 'etc/hosts', 'etc/machine-id', 'etc/ssh',
                 'etc/systemd/network', 'etc/localtime', 'etc/timezone',
                 'etc/default/locale', 'etc/default/keyboard', 'etc/mdadm/mdadm.conf',
                 'etc/network/interfaces', 'etc/resolv.conf',
                 'etc/systemd/system/plainnvr-kiosk@tty1.service.d',
                 'etc/zfs/zpool.cache', 'etc/systemd/system/plainnvr.service.d/storage.conf']


def copy_machine(root, source=Path('/')):
    root = Path(root)
    paths = MACHINE_PATHS + [str(p.relative_to(source)) for p in
                            (source / 'etc/systemd/system').glob('srv-plainnvr*.mount')]
    for name in paths:
        src, dst = source / name, root / name
        if not src.exists() and not src.is_symlink(): continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.is_dir() and not src.is_symlink():
            if dst.exists(): shutil.rmtree(dst)
            shutil.copytree(src, dst, symlinks=True)
        else:
            dst.unlink(missing_ok=True)
            if src.is_symlink(): dst.symlink_to(os.readlink(src))
            else: shutil.copy2(src, dst)
    for unit in ['ssh.service', 'zfs-import-cache.service', 'zfs-mount.service', 'zfs.target']:
        enabled = subprocess_enabled(unit)
        run('systemctl', '--root', root, 'enable' if enabled else 'disable', unit, check=False)
    for mount in (root / 'etc/systemd/system').glob('srv-plainnvr*.mount'):
        run('systemctl', '--root', root, 'enable', mount.name)
    for directory in ('srv/plainnvr-storage', 'srv/plainnvr-volumes'):
        (root / directory).mkdir(parents=True, exist_ok=True)
    # Mount targets must exist before their generated mount units run.
    for path in (source / 'srv/plainnvr-volumes').glob('*'):
        if path.is_dir(): (root / 'srv/plainnvr-volumes' / path.name).mkdir(exist_ok=True)


def subprocess_enabled(unit):
    return run('systemctl', 'is-enabled', unit, check=False) == 'enabled'


def fstab(config, slot, original=''):
    lines = [f'{config["slots"][slot]} / ext4 defaults,errors=remount-ro 0 1',
             f'{config["data_device"]} /persist ext4 defaults 0 2',
             '/persist/nvr /var/lib/plainnvr none bind 0 0']
    for line in original.splitlines():
        fields = line.split()
        if len(fields) >= 4 and not line.startswith('#') and fields[1].startswith('/srv/plainnvr'):
            lines.append(line)
    return '\n'.join(lines) + '\n'


def configure_root(root, config, slot, original_fstab=''):
    root = Path(root)
    (root / 'persist').mkdir(exist_ok=True)
    for name, target in [('etc/plainnvr', '/persist/system/config'),
                         ('var/lib/plainnvr-setup', '/persist/system/setup'),
                         ('var/lib/plainnvr-control', '/persist/system/control')]:
        path = root / name
        if path.is_dir() and not path.is_symlink(): shutil.rmtree(path)
        else: path.unlink(missing_ok=True)
        path.symlink_to(target)
    (root / 'etc/fstab').write_text(fstab(config, slot, original_fstab))
    (root / 'etc/rauc').mkdir(exist_ok=True)
    (root / 'etc/rauc/system.conf').write_text(
        '[system]\ncompatible=plainnvr-os-amd64-ab-v1\nbootloader=custom\n'
        'data-directory=/persist/system/rauc\nmountprefix=/run/rauc\nbundle-formats=verity\n'
        '[keyring]\npath=' + LIB + '/release.pem\n'
        '[handlers]\nbootloader-custom-backend=' + LIB + '/boot.py\n'
        '[slot.rootfs.0]\ndevice=' + config['slots']['A'] + '\ntype=ext4\nbootname=A\n'
        '[slot.rootfs.1]\ndevice=' + config['slots']['B'] + '\ntype=ext4\nbootname=B\n')
    for unit in ['plainnvr-ab-prepare.service', 'plainnvr-ab-health.service']:
        run('systemctl', '--root', root, 'enable', unit)
    for unit in ['plainnvr.service', 'plainnvr-setup.service', 'plainnvr-control.service']:
        directory = root / 'etc/systemd/system' / (unit + '.d')
        directory.mkdir(parents=True, exist_ok=True)
        (directory / 'ab.conf').write_text('[Unit]\nRequires=plainnvr-ab-prepare.service\nAfter=plainnvr-ab-prepare.service\n')
    directory = root / 'etc/systemd/system/rauc.service.d'
    directory.mkdir(parents=True, exist_ok=True)
    (directory / 'ab.conf').write_text('[Unit]\nRequiresMountsFor=/persist\n')
    for unit in ['networking.service', 'ssh.socket']:
        run('systemctl', '--root', root, 'disable', unit, check=False)
    for unit in ['systemd-networkd.service', 'systemd-resolved.service']:
        run('systemctl', '--root', root, 'enable', unit)
    run('systemctl', '--root', root, 'disable', 'plainnvr-boot-mirror.service', check=False)
    # Updates are whole system images; apt hooks must never overwrite A/B GRUB.
    for path in ['etc/kernel/postinst.d/zz-plainnvr-boot-mirror', 'etc/apt/apt.conf.d/99plainnvr-boot-mirror']:
        (root / path).unlink(missing_ok=True)
    # Remove builder/live-only configuration from both the ISO-installed and
    # update-installed root. These services remain on the live ISO itself.
    for unit in ['plainnvr-live-installer.service', 'rsync.service']:
        run('systemctl', '--root', root, 'disable', unit, check=False)


def grub_config(config):
    roots = {slot: run('blkid', '-s', 'UUID', '-o', 'value', device)
             for slot, device in config['slots'].items()}
    if any(not re.fullmatch(r'[a-fA-F0-9-]+', value) for value in roots.values()):
        raise RuntimeError('Missing root filesystem identity.')
    text = '''insmod fat
insmod part_gpt
insmod linux
terminal_input console
terminal_output console
set timeout=5
set default=A
set ORDER="A B"
set A_OK=1
set A_TRY=0
set B_OK=0
set B_TRY=0
set PENDING=none
load_env --file=$prefix/grubenv
for slot in $ORDER; do
  if [ "$slot" = "A" -a "$A_OK" = "1" -a "$A_TRY" = "0" ]; then
    set default=A
    break
  fi
  if [ "$slot" = "B" -a "$B_OK" = "1" -a "$B_TRY" = "0" ]; then
    set default=B
    break
  fi
done
'''
    for slot in ('A', 'B'):
        text += f'''menuentry 'PlainNVR OS — system {slot}' --id {slot} {{
  if [ "$PENDING" = "{slot}" ]; then
    set {slot}_TRY=1
    if ! save_env --file=$prefix/grubenv {slot}_TRY; then
      echo 'Cannot record trial boot. Restart and select the previous system.'
      sleep 10
      halt
    fi
  fi
  linux $prefix/slots/{slot}/vmlinuz root=UUID={roots[slot]} ro rauc.slot={slot} panic=30
  initrd $prefix/slots/{slot}/initrd
}}
'''
    return text


def copy_kernel(root, slot, mount):
    boot = Path(root) / 'boot'
    kernels = sorted(boot.glob('vmlinuz-*'), key=lambda p: p.stat().st_mtime)
    if not kernels: raise RuntimeError('The new image has no kernel.')
    kernel = kernels[-1]
    initrd = boot / kernel.name.replace('vmlinuz-', 'initrd.img-')
    if not initrd.is_file(): raise RuntimeError('The new image has no initramfs.')
    destination = mount / 'grub/slots' / slot
    destination.mkdir(parents=True, exist_ok=True)
    for source, name in [(kernel, 'vmlinuz'), (initrd, 'initrd')]:
        temporary = destination / (name + '.new')
        shutil.copyfile(source, temporary)
        with temporary.open('rb') as stream: os.fsync(stream.fileno())
        os.replace(temporary, destination / name)
    os.sync()


def refresh_boot(config, root, slot):
    text = grub_config(config)
    with esp_mounts(config) as mounts:
        for mount in mounts:
            copy_kernel(root, slot, mount)
            path = mount / 'grub/grub.cfg'
            temporary = path.with_suffix('.new')
            temporary.write_text(text)
            os.replace(temporary, path)
            os.sync()
