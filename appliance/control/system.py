"""Explicit appliance operations; never execute command text supplied by a client."""
import base64
import fcntl
import functools
import ipaddress
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from pathlib import Path

CONFIG = Path('/etc/plainnvr')
STATE = Path('/var/lib/plainnvr-control')
NETWORK = Path('/etc/systemd/network/10-plainnvr-managed.network')
PENDING = STATE / 'network-pending.json'


def network_locked(function):
    @functools.wraps(function)
    def wrapped(*args, **kwargs):
        STATE.mkdir(parents=True, exist_ok=True)
        with (STATE / 'network.lock').open('a') as stream:
            fcntl.flock(stream, fcntl.LOCK_EX)
            return function(*args, **kwargs)
    return wrapped


def run(*args, timeout=30, check=True):
    result = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    if check and result.returncode:
        raise ValueError((result.stderr or result.stdout or 'Command failed').strip()[-1500:])
    return result.stdout.strip()


def read_json(path, default):
    return json.loads(path.read_text()) if path.exists() else default


def write(path, content, mode=0o600):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        os.chmod(temporary, mode)
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def save(path, value):
    write(path, json.dumps(value, indent=2) + '\n')


def interfaces():
    return [item for item in json.loads(run('ip', '-j', 'address', 'show')) if item['ifname'] != 'lo']


def status():
    keys = read_json(CONFIG / 'ssh-keys.json', [])
    pending = read_json(PENDING, {})
    return {
        'available': True, 'hostname': run('hostname'),
        'uptime_seconds': int(float(Path('/proc/uptime').read_text().split()[0])),
        'memory': Path('/proc/meminfo').read_text().splitlines()[:3],
        'load': Path('/proc/loadavg').read_text().split()[:3],
        'kernel': run('uname', '-r'), 'interfaces': interfaces(),
        'routes': json.loads(run('ip', '-j', 'route', 'show')),
        'network': read_json(CONFIG / 'network.json', {'mode': 'dhcp'}),
        'network_pending': {k: pending[k] for k in ('id', 'deadline') if k in pending},
        'ssh': {'enabled': run('systemctl', 'is-active', 'ssh.service', check=False) == 'active',
                'username': 'plainnvr-admin', 'keys': keys},
        'timezone': run('timedatectl', 'show', '-p', 'Timezone', '--value'),
        'ntp': run('timedatectl', 'show', '-p', 'NTP', '--value') == 'yes',
        'job': read_json(STATE / 'job.json', {}),
        'raid': Path('/proc/mdstat').read_text() if Path('/proc/mdstat').exists() else 'No Linux software RAID is active.',
    }


def ssh_save(payload):
    supplied = payload.get('keys')
    if not isinstance(supplied, list) or len(supplied) > 32:
        raise ValueError('Supply up to 32 SSH public keys.')
    keys = []
    fingerprints = set()
    for item in supplied:
        public = str(item.get('public_key', '')).strip()
        label = str(item.get('label', '')).strip()
        if not label or len(label) > 80 or any(c in label for c in '\r\n\x00'):
            raise ValueError('Give each key a name of up to 80 characters.')
        parts = public.split()
        if len(parts) < 2 or parts[0] not in ('ssh-ed25519', 'ssh-rsa', 'ecdsa-sha2-nistp256', 'ecdsa-sha2-nistp384', 'ecdsa-sha2-nistp521', 'sk-ssh-ed25519@openssh.com', 'sk-ecdsa-sha2-nistp256@openssh.com') or '\n' in public or len(public) > 16384:
            raise ValueError('Paste an OpenSSH public key, never a private key.')
        try:
            base64.b64decode(parts[1], validate=True)
        except ValueError:
            raise ValueError('Invalid public key encoding.') from None
        with tempfile.NamedTemporaryFile(mode='w') as stream:
            stream.write(' '.join(parts[:2]) + '\n'); stream.flush()
            details = run('ssh-keygen', '-l', '-f', stream.name)
        fingerprint = details.split()[1]
        if fingerprint in fingerprints:
            raise ValueError('Duplicate SSH key.')
        fingerprints.add(fingerprint)
        keys.append({'label': label, 'public_key': ' '.join(parts[:2]), 'fingerprint': fingerprint,
                     'enabled': item.get('enabled') is True})
    enabled = payload.get('enabled') is True
    if enabled and not any(k['enabled'] for k in keys):
        raise ValueError('Select at least one authorized public key before enabling SSH.')
    config = ('PermitRootLogin no\nPasswordAuthentication no\nKbdInteractiveAuthentication no\n'
              'PubkeyAuthentication yes\nAllowUsers plainnvr-admin\n'
              'AuthorizedKeysFile /etc/plainnvr/authorized_keys\nX11Forwarding no\nAllowAgentForwarding no\n')
    write(Path('/etc/ssh/sshd_config.d/00-plainnvr.conf'), config)
    write(CONFIG / 'authorized_keys', ''.join(k['public_key'] + ' ' + k['label'] + '\n' for k in keys if k['enabled']), 0o644)
    run('ssh-keygen', '-A')
    Path('/run/sshd').mkdir(mode=0o755, exist_ok=True)
    run('sshd', '-t')
    save(CONFIG / 'ssh-keys.json', keys)
    if enabled:
        run('systemctl', 'enable', 'ssh.service')
        run('systemctl', 'restart', 'ssh.service')
    else:
        run('systemctl', 'disable', '--now', 'ssh.socket', check=False)
        run('systemctl', 'disable', '--now', 'ssh.service')
    return {'ok': True}


def network_plan(payload, available):
    interface = payload.get('interface')
    if interface not in {i['ifname'] for i in available} or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,32}', str(interface)):
        raise ValueError('Choose an available network interface.')
    mode = payload.get('mode')
    if mode not in ('dhcp', 'static'):
        raise ValueError('Choose DHCP or static addressing.')
    text = f'[Match]\nName={interface}\n[Link]\nRequiredForOnline=no\n[Network]\n'
    plan = {'interface': interface, 'mode': mode}
    if mode == 'dhcp':
        text += 'DHCP=yes\n'
    else:
        try:
            address = ipaddress.ip_interface(str(payload.get('address', '')))
            gateway = ipaddress.ip_address(str(payload.get('gateway', '')))
            dns = [ipaddress.ip_address(value) for value in str(payload.get('dns', '')).split()]
            if (gateway.version != address.version or not dns or '/' not in str(payload.get('address', ''))
                    or '%' in str(address) + str(gateway) + ''.join(map(str, dns))):
                raise ValueError()
        except ValueError:
            raise ValueError('Enter an address with prefix (for example 192.168.1.20/24), gateway and DNS IPs.') from None
        plan.update(address=str(address), gateway=str(gateway), dns=' '.join(map(str, dns)))
        text += f'DHCP=no\nAddress={address}\nGateway={gateway}\n' + ''.join(f'DNS={ip}\n' for ip in dns)
    return plan, text


def reload_network():
    run('networkctl', 'reload')
    run('networkctl', 'reconfigure', *[i['ifname'] for i in interfaces()])


@network_locked
def rollback_network():
    pending = read_json(PENDING, {})
    if not pending:
        return
    if pending['old_file'] is None:
        NETWORK.unlink(missing_ok=True)
    else:
        write(NETWORK, pending['old_file'], 0o644)
    save(CONFIG / 'network.json', pending['old_config'])
    reload_network()
    PENDING.unlink(missing_ok=True)


@network_locked
def network_apply(payload):
    if PENDING.exists():
        raise ValueError('Confirm or revert the pending network change first.')
    plan, text = network_plan(payload, interfaces())
    pending = {'id': uuid.uuid4().hex, 'deadline': time.time() + 120,
               'old_file': NETWORK.read_text() if NETWORK.exists() else None,
               'old_config': read_json(CONFIG / 'network.json', {'mode': 'dhcp'})}
    save(PENDING, pending)
    # Independent systemd timer still restores connectivity if the broker exits.
    try:
        run('systemd-run', '--collect', '--unit=plainnvr-network-rollback', '--on-active=120s',
            '/usr/bin/python3', '/usr/lib/plainnvr/control/system.py', '--rollback')
    except Exception:
        PENDING.unlink(missing_ok=True)
        raise
    write(NETWORK, text, 0o644)
    save(CONFIG / 'network.json', plan)
    threading.Timer(2, reload_network).start()
    return {'ok': True, 'pending': {'id': pending['id'], 'deadline': pending['deadline']}, 'network': plan}


@network_locked
def network_confirm(payload):
    pending = read_json(PENDING, {})
    if not pending or payload.get('id') != pending.get('id') or time.time() >= pending['deadline']:
        raise ValueError('That network change has expired. Refresh its status.')
    run('systemctl', 'stop', 'plainnvr-network-rollback.timer')
    PENDING.unlink()
    run('systemctl', 'reset-failed', 'plainnvr-network-rollback.service', check=False)
    return {'ok': True}


def clock_save(payload):
    timezone = str(payload.get('timezone', ''))
    if timezone not in run('timedatectl', 'list-timezones').splitlines():
        raise ValueError('Choose a valid timezone.')
    run('timedatectl', 'set-timezone', timezone)
    run('timedatectl', 'set-ntp', 'true' if payload.get('ntp') is True else 'false')
    return {'ok': True}


if __name__ == '__main__':
    if sys.argv[1:] == ['--wait-online']:
        # Installed wired interfaces are optional for local operation. SMB
        # mounts still need an actual address, rather than only network.target.
        for attempt in range(60):
            if any(i.get('operstate') == 'UP' and any(a.get('scope') == 'global' for a in i.get('addr_info', [])) for i in interfaces()):
                break
            time.sleep(1)
        else:
            raise SystemExit('No usable network address became available for SMB storage.')
    elif sys.argv[1:] == ['--rollback']:
        rollback_network()
    else:
        raise SystemExit('Expected --rollback or --wait-online.')
