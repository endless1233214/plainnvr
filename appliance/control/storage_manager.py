"""Recording destinations and deliberate disk/pool operations after first boot."""
import json
import os
import pwd
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from urllib.request import urlopen

import system

sys.path.insert(0, '/usr/lib/plainnvr/setup')
import storage

TARGETS = system.CONFIG / 'storage-targets.json'
LOCK = threading.Lock()


def check_partition_editor():
    if subprocess.run(['pgrep', '-x', 'gpartedbin'], capture_output=True).returncode == 0:
        raise ValueError('Close GParted before changing storage here.')


def destinations():
    targets = system.read_json(TARGETS, [])
    if not targets and (system.CONFIG / 'runtime.env').exists():
        env = dict(line.split('=', 1) for line in (system.CONFIG / 'runtime.env').read_text().splitlines() if '=' in line)
        active = Path(env['NVR_RECORDINGS_DIR'])
        mount = system.run('findmnt', '--first-only', '-nro', 'TARGET', '--target', str(active))
        targets = [{'id': 'installed', 'label': 'Initial recording storage', 'path': str(active), 'mount': mount,
                    'plan': system.read_json(system.CONFIG / 'storage.json', {})}]
        system.save(TARGETS, targets)
    return targets


def inventory():
    result = storage.inventory()
    result.update(devices=storage.device_tree(), protected=sorted(storage.system_devices()),
                  targets=destinations(), active=system.read_json(system.CONFIG / 'storage.json', {}),
                  zpool_status=system.run('zpool', 'status', check=False),
                  zfs_datasets=system.run('zfs', 'list', '-H', '-o', 'name,used,available,mountpoint', check=False))
    return result


def format_disk(payload):
    with LOCK:
        check_partition_editor()
        selected = next((d for d in storage.inventory()['disks'] if d['id'] == payload.get('disk')), None)
        if not selected or payload.get('confirmation') != f'FORMAT {selected["device"]}':
            raise ValueError('Select a blank non-system disk and type FORMAT followed by its device name.')
        system.run('parted', '--script', selected['id'], 'mklabel', 'gpt', 'mkpart', 'primary', 'ext4', '1MiB', '100%')
        system.run('partprobe', selected['id'])
        system.run('udevadm', 'settle')
        tree = json.loads(system.run('lsblk', '-Jpo', 'NAME,TYPE', selected['id']))['blockdevices'][0]
        parts = [item['name'] for item in tree.get('children', []) if item['type'] == 'part']
        if len(parts) != 1:
            raise ValueError('The new partition could not be identified. Refresh storage before continuing.')
        system.run('mkfs.ext4', '-L', 'plainnvr-recordings', parts[0], timeout=180)
        root = system.STATE / 'new-filesystem'
        root.mkdir(exist_ok=True)
        system.run('mount', '-t', 'ext4', parts[0], str(root))
        try:
            user = pwd.getpwnam('plainnvr')
            os.chown(root, user.pw_uid, user.pw_gid)
        finally:
            system.run('umount', str(root))
    return {'ok': True}


def scrub(payload):
    pools = system.run('zpool', 'list', '-H', '-o', 'name').splitlines()
    if payload.get('pool') not in pools:
        raise ValueError('Choose an imported pool.')
    args = ['zpool', 'scrub'] + (['-s'] if payload.get('stop') is True else []) + [payload['pool']]
    system.run(*args)
    return {'ok': True}


def record_job(state, message):
    system.save(system.STATE / 'job.json', {'state': state, 'message': message, 'updated': time.time()})


def switch(payload):
    check_partition_editor()
    if payload.get('confirmation') != 'CHANGE RECORDING STORAGE':
        raise ValueError('Type CHANGE RECORDING STORAGE. Recording will briefly stop; existing recordings stay on their previous destination.')
    if not LOCK.acquire(blocking=False):
        raise ValueError('Another storage operation is running.')
    record_job('running', 'Preparing recording storage.')
    # Return before any NVR restart closes its current HTTP connection.
    timer = threading.Timer(2, switch_worker, args=(dict(payload),))
    timer.start()
    return {'ok': True, 'job': 'storage'}


def switch_worker(payload):
    dropin = Path('/etc/systemd/system/plainnvr.service.d/storage.conf')
    restarted = False
    original_mount, original_state, original_credentials = storage.RECORDING_MOUNT, storage.STATE, storage.SMB_CREDENTIALS
    try:
        old_env = (system.CONFIG / 'runtime.env').read_text()
        old_dropin = dropin.read_text()
        old_plan = system.read_json(system.CONFIG / 'storage.json', {})
        targets = destinations()
        if payload.get('target_id'):
            target = next((t for t in targets if t['id'] == payload['target_id']), None)
            if not target:
                raise ValueError('That recording destination no longer exists.')
            mount = Path(target['mount'])
            if subprocess.run(['mountpoint', '-q', str(mount)]).returncode:
                system.run('systemctl', 'start', system.run('systemd-escape', '--path', '--suffix=mount', str(mount)))
            storage.assert_mount(mount)
            recording = Path(target['path'])
            plan = target['plan']
        else:
            selection = dict(payload.get('selection', {}))
            env = dict(line.split('=', 1) for line in old_env.splitlines() if '=' in line)
            selection['data_directory'] = str(Path(env['NVR_DATA_DIR']).relative_to(storage.DATA_MOUNT))
            plan = storage.validate(selection)
            identity = uuid.uuid4().hex[:12]
            volumes = Path('/srv/plainnvr-volumes')
            volumes.mkdir(mode=0o755, exist_ok=True)
            volumes.chmod(0o755)
            storage.RECORDING_MOUNT = volumes / identity
            storage.STATE = system.STATE / 'storage' / identity
            storage.STATE.mkdir(parents=True, exist_ok=True)
            if plan['mode'] == 'smb':
                storage.SMB_CREDENTIALS = system.CONFIG / f'smb-{identity}.credentials'
                storage.save_smb_credentials(plan, selection.get('smb_password'))
            mount = storage.prepare(plan)
            recording = storage.empty_directory(mount, plan['recording_directory'], network=plan['mode'] == 'smb')
            plan['mount_path'] = str(mount)
            target = {'id': identity, 'label': str(payload.get('label', '')).strip()[:80] or plan['mode'],
                      'path': str(recording), 'mount': str(mount), 'plan': plan}
            targets.append(target)
            system.save(TARGETS, targets)
        if not recording.is_dir() or recording.is_symlink():
            raise ValueError('Recording directory is missing or is a symbolic link.')
        storage.run('runuser', '-u', 'plainnvr', '--', '/usr/bin/python3', '-c',
                    'import os,sys,tempfile; f=tempfile.NamedTemporaryFile(dir=sys.argv[1]); f.write(b"PlainNVR storage check"); f.flush(); os.fsync(f.fileno()); f.close()',
                    str(recording), timeout=30)
        env = dict(line.split('=', 1) for line in old_env.splitlines() if '=' in line)
        data = env['NVR_DATA_DIR']
        unit = system.run('systemd-escape', '--path', '--suffix=mount', str(mount))
        record_job('running', 'Switching recording destination; PlainNVR is restarting.')
        system.run('systemctl', 'stop', 'plainnvr.service', timeout=60)
        restarted = True
        system.write(system.CONFIG / 'runtime.env', f'NVR_DATA_DIR={data}\nNVR_RECORDINGS_DIR={recording}\n', 0o644)
        system.write(dropin, '[Unit]\nAfter=zfs-mount.service\n'
                     f'RequiresMountsFor={storage.DATA_MOUNT} {mount}\nAssertPathIsMountPoint={mount}\nBindsTo={unit}\n'
                     '[Service]\nEnvironmentFile=/etc/plainnvr/runtime.env\n'
                     f'ReadWritePaths={data} {recording}\n', 0o644)
        system.save(system.CONFIG / 'storage.json', plan)
        system.run('systemctl', 'daemon-reload')
        system.run('systemctl', 'start', 'plainnvr.service', timeout=60)
        for attempt in range(30):
            try:
                with urlopen('http://127.0.0.1:8787/api/health', timeout=2) as response:
                    if json.load(response).get('ok'):
                        break
            except (OSError, ValueError):
                pass
            time.sleep(1)
        else:
            raise ValueError('PlainNVR did not become ready with the new storage; restoring the previous destination.')
        record_job('complete', 'Recording storage changed. Existing recordings remain on their previous destination; select it again to browse them.')
    except Exception as exc:
        if restarted:
            system.write(system.CONFIG / 'runtime.env', old_env, 0o644)
            system.write(dropin, old_dropin, 0o644)
            system.save(system.CONFIG / 'storage.json', old_plan)
            system.run('systemctl', 'daemon-reload', check=False)
            system.run('systemctl', 'start', 'plainnvr.service', timeout=60, check=False)
        record_job('failed', str(exc)[-1500:])
    finally:
        storage.RECORDING_MOUNT, storage.STATE, storage.SMB_CREDENTIALS = original_mount, original_state, original_credentials
        LOCK.release()
