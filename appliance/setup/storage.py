"""Storage operations for the local, authenticated first-boot wizard."""
import json
import ipaddress
import os
import pwd
import re
import subprocess
from pathlib import Path

STATE = Path('/var/lib/plainnvr-setup')
RECORDING_MOUNT = Path('/srv/plainnvr-storage')
DATA_MOUNT = Path('/var/lib/plainnvr')
SAFE_NAME = re.compile(r'^[A-Za-z][A-Za-z0-9_-]{0,47}$')
SMB_CREDENTIALS = Path('/etc/plainnvr/smb.credentials')


def smb_options(plan):
    user = pwd.getpwnam('plainnvr')
    return (f'credentials={SMB_CREDENTIALS},vers=3,uid={user.pw_uid},gid={user.pw_gid},'
            'forceuid,forcegid,file_mode=0600,dir_mode=0700,nosuid,nodev,noexec,cache=strict')


def save_smb_credentials(plan, password):
    if not isinstance(password, str) or not password or len(password) > 1024 or any(c in password for c in '\r\n\x00'):
        raise ValueError('Enter the SMB password without line breaks.')
    SMB_CREDENTIALS.parent.mkdir(parents=True, exist_ok=True)
    temporary = SMB_CREDENTIALS.with_suffix('.tmp')
    with open(temporary, 'w', encoding='utf-8') as stream:
        os.chmod(temporary, 0o600)
        stream.write(f'username={plan["smb_username"]}\npassword={password}\ndomain={plan["smb_domain"]}\n')
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, SMB_CREDENTIALS)


def run(*args, timeout=90):
    result = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    if result.returncode:
        raise ValueError((result.stderr or result.stdout or 'Storage command failed').strip()[-1500:])
    return result.stdout.strip()


def save_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    with open(temporary, 'w', encoding='utf-8') as stream:
        os.chmod(temporary, 0o600)
        json.dump(value, stream)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def subdirectory(value):
    if not isinstance(value, str) or not value or len(value) > 160:
        raise ValueError('Enter a relative directory name.')
    parts = value.split('/')
    if any(p in ('', '.', '..') or not re.fullmatch(r'[A-Za-z0-9_.-]+', p) for p in parts):
        raise ValueError('Use directory names with letters, numbers, dots, dashes or underscores.')
    return value


def named(value):
    if not isinstance(value, str) or not SAFE_NAME.fullmatch(value):
        raise ValueError('Names must begin with a letter and contain letters, numbers, dashes or underscores.')
    if value.lower() in ('mirror', 'raidz', 'raidz1', 'raidz2', 'raidz3', 'spare', 'log', 'cache'):
        raise ValueError('That name is reserved by ZFS.')
    return value


def device_tree():
    return json.loads(run('lsblk', '--json', '--paths', '--bytes', '--output',
                         'NAME,TYPE,SIZE,MODEL,SERIAL,FSTYPE,UUID,MOUNTPOINTS'))['blockdevices']


def flatten(nodes):
    for node in nodes:
        yield node
        yield from flatten(node.get('children', []))


def system_devices():
    protected = set()
    for target in ('/', '/boot', '/boot/efi', str(DATA_MOUNT)):
        if not Path(target).exists():
            continue
        for source in run('findmnt', '-nro', 'SOURCE', '--target', target).splitlines():
            source = source.split('[')[0]
            if source.startswith('/dev/'):
                for name in run('lsblk', '--inverse', '--raw', '--noheadings', '--paths', '--output', 'NAME', source).splitlines():
                    protected.add(str(Path(name.strip()).resolve()))
    return protected


def by_id(device):
    resolved = Path(device).resolve()
    links = sorted(Path('/dev/disk/by-id').glob('*'))
    return next((str(p) for p in links if p.resolve() == resolved and '-part' not in p.name), None)


def inventory():
    protected = system_devices()
    disks, filesystems = [], []
    for node in flatten(device_tree()):
        device = node['name']
        if str(Path(device).resolve()) in protected:
            continue
        mounted = any(node.get('mountpoints') or [])
        if node['type'] == 'disk' and not node.get('children') and not mounted and not node.get('fstype'):
            stable = by_id(device)
            # Empty removable drives (including legacy floppy controllers)
            # may exist as block devices but cannot be probed with wipefs.
            if not stable or int(node.get('size') or 0) <= 0:
                continue
            signatures = json.loads(run('wipefs', '--json', '--no-act', device)).get('signatures', [])
            if not signatures:
                disks.append({'id': stable, 'device': device, 'model': node.get('model'),
                              'serial': node.get('serial'), 'bytes': node['size']})
        if node['type'] == 'part' and node.get('fstype') in ('ext4', 'xfs') and node.get('uuid') and not mounted:
            filesystems.append({'uuid': node['uuid'], 'device': device,
                                'filesystem': node['fstype'], 'bytes': node['size']})
    pools = []
    zfs_available = subprocess.run(['modprobe', 'zfs'], capture_output=True).returncode == 0
    available = subprocess.run(['zpool', 'import'], capture_output=True, text=True, timeout=45)
    # Discovery is read-only; do not import or force-import pools here.
    for block in re.split(r'(?m)^\s*pool:', available.stdout)[1:]:
        match = re.search(r'(?m)^\s*id:\s*(\d+)\s*$', block)
        if match:
            pools.append({'name': block.splitlines()[0].strip(), 'id': match.group(1)})
    return {'disks': disks, 'filesystems': filesystems, 'pools': pools,
            'default_mount': str(DATA_MOUNT), 'recording_mount': str(RECORDING_MOUNT),
            'zfs_available': zfs_available}


def validate(request):
    if not isinstance(request, dict):
        raise ValueError('Invalid storage selection.')
    mode = request.get('mode')
    if mode not in ('default', 'filesystem', 'zfs-create', 'zfs-import', 'smb'):
        raise ValueError('Choose a storage type.')
    plan = {'mode': mode, 'data_directory': subdirectory(request.get('data_directory')),
            'recording_directory': subdirectory(request.get('recording_directory'))}
    if mode == 'default':
        left, right = plan['data_directory'], plan['recording_directory']
        if left == right or left.startswith(right + '/') or right.startswith(left + '/'):
            raise ValueError('Configuration and recording directories must be separate.')
        return plan
    if mode == 'smb':
        host = str(request.get('smb_host', '')).strip()
        if '%' in host:
            raise ValueError('Scoped SMB addresses are not supported; use a hostname or unscoped IP.')
        try:
            ipaddress.ip_address(host)
        except ValueError:
            if not re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?', host):
                raise ValueError('Enter an SMB server IP address or hostname, without slashes.')
        share = str(request.get('smb_share', '')).strip()
        if not re.fullmatch(r'[A-Za-z0-9_$.-]{1,80}', share) or share in ('.', '..'):
            raise ValueError('Enter a share name using letters, numbers, dots, dashes, underscores or $.')
        username, domain = request.get('smb_username', ''), request.get('smb_domain', '')
        for value in (username, domain):
            if not isinstance(value, str) or len(value) > 128 or any(c in value for c in '\r\n\x00'):
                raise ValueError('Invalid SMB username or domain.')
        if not username.strip():
            raise ValueError('Enter an SMB username.')
        if request.get('smb_acknowledged') is not True:
            raise ValueError('Acknowledge the SMB performance and network availability warning.')
        plan.update(smb_host=host, smb_share=share, smb_username=username, smb_domain=domain,
                    smb_acknowledged=True)
        return plan
    devices = inventory()
    if mode == 'filesystem':
        selected = next((f for f in devices['filesystems'] if f['uuid'] == request.get('uuid')), None)
        if not selected:
            raise ValueError('That filesystem is unavailable, mounted, or part of the system.')
        plan.update(selected)
    elif mode == 'zfs-create':
        if not devices['zfs_available']:
            raise ValueError('The ZFS kernel module is unavailable. Check the local maintenance console.')
        pool = named(request.get('pool'))
        layout = request.get('layout')
        minima = {'single': 1, 'mirror': 2, 'raidz1': 3, 'raidz2': 4}
        selected = request.get('disks', [])
        if not isinstance(selected, list) or any(not isinstance(p, str) for p in selected):
            raise ValueError('Select blank disks for the pool.')
        valid = {d['id'] for d in devices['disks']}
        if (layout not in minima or len(selected) < minima[layout] or len(selected) != len(set(selected))
                or not set(selected) <= valid or (layout == 'single' and len(selected) != 1)):
            raise ValueError('Select enough distinct, unused disks for that layout.')
        if request.get('confirmation') != f'CREATE {pool}':
            raise ValueError(f'Type CREATE {pool} to confirm creation on the selected disks.')
        plan.update(pool=pool, layout=layout, disks=selected)
    else:
        selected = next((p for p in devices['pools'] if p['id'] == request.get('pool_id')), None)
        if not selected:
            raise ValueError('That exported pool is unavailable.')
        if request.get('confirmation') != f'IMPORT {selected["name"]}':
            raise ValueError(f'Type IMPORT {selected["name"]} to confirm pool import.')
        plan.update(pool=selected['name'], pool_id=selected['id'])
    if mode.startswith('zfs-'):
        plan['dataset'] = named(request.get('dataset'))
    return plan


def assert_mount(path):
    if subprocess.run(['mountpoint', '-q', str(path)]).returncode:
        raise ValueError(f'{path} is not mounted. Setup stopped to protect the system disk.')


def empty_directory(base, relative, network=False):
    # Reject symlinks at every component, including a final dangling symlink.
    current = base
    user = pwd.getpwnam('plainnvr')
    for component in relative.split('/'):
        current /= component
        if current.is_symlink():
            raise ValueError('Storage directories cannot contain symbolic links.')
        if not current.exists():
            if network:
                run('runuser', '-u', 'plainnvr', '--', 'mkdir', '-m', '0700', '--', str(current))
            else:
                current.mkdir(mode=0o700)
                os.chown(current, user.pw_uid, user.pw_gid)
        elif current.stat().st_uid != user.pw_uid:
            raise ValueError('Choose a new directory; an existing parent belongs to another user.')
    if any(current.iterdir()):
        raise ValueError(f'{current} is not empty. Choose a new directory to preserve its contents.')
    return current


def prepare(plan):
    assert_mount(DATA_MOUNT)
    if plan['mode'] == 'default':
        return DATA_MOUNT
    RECORDING_MOUNT.mkdir(parents=True, exist_ok=True)
    if RECORDING_MOUNT.is_symlink():
        raise ValueError('Recording mount cannot be a symbolic link.')
    if plan['mode'] == 'smb':
        if not SMB_CREDENTIALS.is_file():
            raise ValueError('Enter the SMB credentials again.')
        host = plan['smb_host']
        source = f'//{("[" + host + "]") if ":" in host else host}/{plan["smb_share"]}'
        if subprocess.run(['mountpoint', '-q', str(RECORDING_MOUNT)]).returncode:
            if any(RECORDING_MOUNT.iterdir()):
                raise ValueError('Recording mount directory is not empty.')
            run('mount', '-t', 'cifs', source, str(RECORDING_MOUNT), '-o', smb_options(plan), timeout=30)
        actual = run('findmnt', '-nro', 'SOURCE,FSTYPE', '--mountpoint', str(RECORDING_MOUNT)).split()
        if actual != [source, 'cifs']:
            raise ValueError('The recording mount belongs to a different share or filesystem.')
        unit = Path('/etc/systemd/system') / run('systemd-escape', '--path', '--suffix=mount', str(RECORDING_MOUNT))
        unit.write_text('[Unit]\nDescription=PlainNVR SMB recordings\nRequires=plainnvr-network-online.service\nAfter=plainnvr-network-online.service\n'
                        f'[Mount]\nWhat={source}\nWhere={RECORDING_MOUNT}\nType=cifs\nOptions={smb_options(plan)}\nTimeoutSec=30\n'
                        '[Install]\nWantedBy=multi-user.target\n')
        run('systemctl', 'daemon-reload')
        run('systemctl', 'enable', unit.name)
    elif plan['mode'] == 'filesystem':
        source = f'UUID={plan["uuid"]}'
        if subprocess.run(['mountpoint', '-q', str(RECORDING_MOUNT)]).returncode:
            if any(RECORDING_MOUNT.iterdir()):
                raise ValueError('Recording mount directory is not empty.')
            run('mount', '-t', plan['filesystem'], '-o', 'nosuid,nodev', source, str(RECORDING_MOUNT))
        actual = run('findmnt', '-nro', 'UUID', '--mountpoint', str(RECORDING_MOUNT))
        if actual != plan['uuid']:
            raise ValueError('The recording mount belongs to a different filesystem.')
        line = f'{source} {RECORDING_MOUNT} {plan["filesystem"]} defaults,nosuid,nodev,nofail,x-systemd.device-timeout=10s 0 2\n'
        fstab = Path('/etc/fstab')
        existing = fstab.read_text()
        if line not in existing:
            if any(str(RECORDING_MOUNT) in row.split()[:2] for row in existing.splitlines() if not row.startswith('#')):
                raise ValueError('The recording mount already has an fstab entry.')
            with fstab.open('a') as stream:
                stream.write('\n# PlainNVR recording storage\n' + line)
    else:
        dataset = f'{plan["pool"]}/{plan["dataset"]}'
        progress_file = STATE / 'zfs-progress.json'
        progress = json.loads(progress_file.read_text()) if progress_file.exists() else {}
        if progress and progress.get('plan') != plan:
            raise ValueError('A different ZFS setup is already in progress. Resume the original selection.')
        if not progress:
            if plan['mode'] == 'zfs-create':
                # Recheck immediately before creation. No -f: disks containing
                # existing signatures must be prepared deliberately in GParted.
                available = {d['id'] for d in inventory()['disks']}
                if not set(plan['disks']) <= available:
                    raise ValueError('A selected disk is no longer unused.')
                layout = [] if plan['layout'] == 'single' else [plan['layout']]
                run('zpool', 'create', '-o', 'ashift=12', '-o', 'cachefile=/etc/zfs/zpool.cache',
                    '-O', 'mountpoint=none', '-O', 'compression=lz4', '-O', 'atime=off',
                    plan['pool'], *layout, *plan['disks'], timeout=180)
            else:
                run('zpool', 'import', '-N', '-o', 'cachefile=/etc/zfs/zpool.cache', plan['pool_id'])
            progress = {'plan': plan, 'imported': True, 'dataset_created': False}
            save_json(progress_file, progress)
        if not progress['dataset_created']:
            run('zfs', 'create', '-o', f'mountpoint={RECORDING_MOUNT}', '-o', 'compression=lz4',
                '-o', 'atime=off', '-o', 'setuid=off', '-o', 'devices=off', dataset)
            progress['dataset_created'] = True
            save_json(progress_file, progress)
        if run('zfs', 'get', '-H', '-o', 'value', 'mounted', dataset) != 'yes':
            run('zfs', 'mount', dataset)
        if run('findmnt', '-nro', 'SOURCE', '--mountpoint', str(RECORDING_MOUNT)) != dataset:
            raise ValueError('Unexpected filesystem at the recording mount.')
        run('systemctl', 'enable', 'zfs-import-cache.service', 'zfs-mount.service', 'zfs.target')
    assert_mount(RECORDING_MOUNT)
    return RECORDING_MOUNT
