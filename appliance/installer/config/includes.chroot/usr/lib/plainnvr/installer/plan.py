"""Validate live-installer selections and prepare Debian Installer input."""
import json
import re
import shlex
import subprocess
from pathlib import Path

STATE = Path('/run/plainnvr-install')
HERE = Path(__file__).resolve().parent


def run(*args):
    return subprocess.check_output(args, text=True, stderr=subprocess.STDOUT).strip()


def inventory():
    tree = json.loads(run('lsblk', '-Jbpo', 'NAME,TYPE,SIZE,MODEL,SERIAL,WWN,MAJ:MIN,RO,MOUNTPOINTS'))
    disks = []
    def mounted(node):
        return any(node.get('mountpoints') or []) or any(mounted(c) for c in node.get('children', []))
    def active_holder(node):
        return any(c['type'] != 'part' or active_holder(c) for c in node.get('children', []))
    for disk in tree['blockdevices']:
        if disk['type'] != 'disk':
            continue
        disk['blocked'] = ('Mounted or in use (including the installer USB)' if mounted(disk)
                           else 'Part of an active RAID/LVM device' if active_holder(disk)
                           else 'Read-only device' if disk['ro']
                           else 'At least 80 GB is required for two 32 GB OS slots' if int(disk['size']) < 80_000_000_000 else '')
        disks.append(disk)
    return disks


def identity(disk):
    return {k: disk.get(k) for k in ('name', 'size', 'serial', 'wwn', 'maj:min')}


def validate_disks(selected, current, mirror):
    if len(selected) != (2 if mirror else 1) or len({d['name'] for d in selected}) != len(selected):
        raise ValueError('Choose exactly two drives for a mirror, or one for a single-drive install.')
    available = {d['name']: d for d in current}
    for chosen in selected:
        now = available.get(chosen['name'])
        if not now or identity(now) != identity(chosen) or now['blocked']:
            raise ValueError('A chosen disk changed or is now in use. Refresh and select it again.')
        if not re.fullmatch(r'/dev/[A-Za-z0-9_-]+', now['name']):
            raise ValueError('Unsupported disk device name.')
    return selected


def prepare(settings, selected, mirror):
    validate_disks(selected, inventory(), mirror)
    for key in ('locale', 'keyboard', 'timezone'):
        if not re.fullmatch(r'[A-Za-z0-9_./+@-]+', settings[key]):
            raise ValueError('Invalid locale, keyboard or timezone.')
    STATE.mkdir(mode=0o700, exist_ok=True)
    for old in ('confirmed', 'mirror-disks'):
        (STATE / old).unlink(missing_ok=True)
    paths = [d['name'] for d in selected]
    if mirror:
        (STATE / 'mirror-disks').write_text('\n'.join(paths) + '\n')
    # Never persist plaintext account passwords or print them in a command line.
    (STATE / 'settings.json').write_text(json.dumps(settings))
    preseed = (HERE / 'preseed.cfg').read_text()
    values = {
        'debian-installer/locale': ('string', settings['locale']),
        'keyboard-configuration/xkb-keymap': ('select', settings['keyboard']),
        'time/zone': ('string', settings['timezone']),
        'clock-setup/utc': ('boolean', 'true'),
        'clock-setup/ntp': ('boolean', 'false'),
        'netcfg/enable': ('boolean', 'false'),
        # A locked root hash skips both password prompts. Setting root-login
        # false would make user-setup force creation of a separate Linux user.
        'passwd/root-login': ('boolean', 'true'),
        'passwd/root-password-crypted': ('password', '*'),
        'passwd/make-user': ('boolean', 'false'),
        'partman-auto/disk': ('string', ' '.join(paths)),
        'partman-auto/method': ('string', 'raid' if mirror else 'regular'),
        'partman-partitioning/confirm_write_new_label': ('boolean', 'true'),
        'partman/choose_partition': ('select', 'finish'),
        'partman/confirm': ('boolean', 'true'),
        'partman/confirm_nooverwrite': ('boolean', 'true'),
        'partman-md/device_remove_md': ('boolean', 'true'),
        'partman-lvm/device_remove_lvm': ('boolean', 'true'),
        'partman-md/confirm': ('boolean', 'true'),
        'partman-md/confirm_nooverwrite': ('boolean', 'true'),
        'partman-basicfilesystems/no_swap': ('boolean', 'false'),
        'grub-installer/bootdev': ('string', paths[0]),
        'anna/choose_modules': ('string', 'di-utils-exit-installer apt-cdrom-udeb'),
        'di-utils-reboot/really_reboot': ('boolean', 'false'),
        'finish-install/reboot_in_progress': ('note', ''),
    }
    preseed += '\n' + '\n'.join(f'd-i {key} {kind} {value}' for key, (kind, value) in values.items()) + '\n'
    (STATE / 'preseed.cfg').write_text(preseed)
    # d-i repeats identity checks immediately before invoking partitioning.
    checks = ['#!/bin/sh', 'set -eu']
    for disk in selected:
        name = Path(disk['name']).name
        for attribute in ('size', 'dev', 'device/serial'):
            source = Path('/sys/class/block') / name / attribute
            if source.exists():
                checks.append(f'test "$(cat {shlex.quote(str(source))})" = {shlex.quote(source.read_text().strip())}')
        checks.append(f'test "$(blockdev --getro {shlex.quote(disk["name"])})" = 0')
    (STATE / 'preflight').write_text('\n'.join(checks) + '\n')
    for path in STATE.iterdir():
        if path.is_file():
            path.chmod(0o600)
    (STATE / 'confirmed').touch(mode=0o600)
