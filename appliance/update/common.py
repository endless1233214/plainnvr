"""Shared appliance A/B helpers. Configuration is root-owned on the data volume."""
import contextlib
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path

CONFIG = Path('/etc/plainnvr/ab.json')
STATE = Path('/persist/system/update')


def run(*args, timeout=180, check=True):
    result = subprocess.run(list(map(str, args)), text=True, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, timeout=timeout)
    if check and result.returncode:
        raise RuntimeError((result.stderr or result.stdout)[-3000:])
    return result.stdout.strip()


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, delete=False) as stream:
        os.fchmod(stream.fileno(), 0o600)
        json.dump(value, stream, indent=2)
        stream.write('\n'); stream.flush(); os.fsync(stream.fileno())
        name = stream.name
    os.replace(name, path)
    descriptor = os.open(path.parent, os.O_RDONLY)
    try: os.fsync(descriptor)
    finally: os.close(descriptor)


def load(path, default=None):
    return json.loads(Path(path).read_text()) if Path(path).exists() else default


def current():
    found = re.findall(r'(?:^|\s)rauc.slot=([AB])(?:\s|$)', Path('/proc/cmdline').read_text())
    if len(found) != 1:
        raise RuntimeError('This system was not booted from a PlainNVR A/B slot.')
    return found[0]


def configuration():
    config = load(CONFIG)
    if not config or config.get('layout') != 1 or set(config.get('slots', {})) != {'A', 'B'}:
        raise RuntimeError('A/B updates require the revision-5 disk layout.')
    return config


@contextlib.contextmanager
def esp_mounts(config, require_all=True):
    """Mount only installer-recorded EFI partitions, never guessed disk names."""
    mounts = []
    try:
        for index, uuid in enumerate(config['esp_uuids']):
            if not re.fullmatch(r'[A-Fa-f0-9-]+', uuid):
                raise RuntimeError('Invalid boot partition identity.')
            device = Path('/dev/disk/by-uuid') / uuid
            if not device.exists():
                if require_all: raise RuntimeError('Reconnect both boot drives before updating.')
                continue
            path = Path('/run/plainnvr-update-esp') / str(index)
            path.mkdir(parents=True, exist_ok=True)
            run('mount', '-t', 'vfat', '-o', 'umask=0077', device, path)
            mounts.append(path)
        if not mounts: raise RuntimeError('No appliance boot partition is available.')
        yield mounts
        os.sync()
    finally:
        for path in reversed(mounts): run('umount', path)


def read_env(path):
    values = run('grub-editenv', path / 'grub/grubenv', 'list')
    return dict(line.split('=', 1) for line in values.splitlines() if '=' in line)


def write_env(path, **values):
    # grub-editenv updates the preallocated environment block in place; GRUB
    # writes its attempt marker before loading a trial kernel.
    run('grub-editenv', path / 'grub/grubenv', 'set', *[f'{k}={v}' for k, v in values.items()])
    os.sync()


def device_ref(device):
    device = Path(device).resolve()
    md = run('mdadm', '--detail', '--export', device, check=False)
    if 'MD_UUID=' in md:
        values = dict(line.split('=', 1) for line in md.splitlines() if '=' in line)
        return '/dev/disk/by-id/md-uuid-' + values['MD_UUID']
    partuuid = run('blkid', '-s', 'PARTUUID', '-o', 'value', device)
    if not re.fullmatch(r'[a-fA-F0-9-]+', partuuid):
        raise RuntimeError('Cannot identify the system partition.')
    return '/dev/disk/by-partuuid/' + partuuid


def verify_slots(config):
    booted = current()
    actual = Path(run('findmnt', '-nro', 'SOURCE', '--mountpoint', '/')).resolve()
    expected = Path(config['slots'][booted]).resolve()
    if actual != expected:
        raise RuntimeError('Booted root device does not match its A/B slot.')
    other = config['slots']['B' if booted == 'A' else 'A']
    if Path(other).resolve() == actual or run('findmnt', '-nro', 'TARGET', '--source', other, check=False):
        raise RuntimeError('Inactive system slot is mounted or overlaps the active root.')
    if config['mirror']:
        for device in [*config['slots'].values(), config['data_device']]:
            values = run('mdadm', '--detail', '--export', device)
            if 'MD_LEVEL=raid1' not in values or 'MD_DEVICES=2' not in values:
                raise RuntimeError('The boot mirror is not healthy.')
            name = Path(device).resolve().name
            if Path('/sys/class/block', name, 'md/degraded').read_text().strip() != '0':
                raise RuntimeError('Repair the boot mirror before updating.')
    return booted
