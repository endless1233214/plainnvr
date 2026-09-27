#!/usr/bin/python3
"""Root OS broker, reachable only through the authenticated NVR on a Unix socket."""
import json
import os
import pwd
import secrets
import socket
import socketserver
import struct
import threading
import time
import sys
from pathlib import Path

import files
import storage_manager
import system
from terminal import Terminals
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'update'))
import manager as updates

SOCKET = Path('/run/plainnvr-control/control.sock')
GRANTS = {}
GRANT_LOCK = threading.Lock()
OPERATIONS = threading.Lock()
TERMINALS = None


def grant(owner):
    with GRANT_LOCK:
        now = time.monotonic()
        for key, value in list(GRANTS.items()):
            if value[1] <= now:
                del GRANTS[key]
        token = secrets.token_hex(32)
        GRANTS[token] = (owner, now + 600)
    return {'token': token, 'expires_in': 600}


def authorized(owner, token):
    with GRANT_LOCK:
        entry = GRANTS.get(token)
        return bool(entry and entry[0] == owner and entry[1] > time.monotonic())


def dispatch(request):
    operation, payload, owner = request['operation'], request['payload'], request['owner']
    if not isinstance(payload, dict) or not isinstance(owner, str) or len(owner) != 64:
        raise ValueError('Invalid request.')
    if operation == 'status':
        return dict(system.status(), local=request.get('local', False), updates=updates.status())
    if operation == 'addresses':
        urls = []
        for interface in system.interfaces():
            for address in interface.get('addr_info', []):
                if address.get('scope') == 'global':
                    ip = address['local']
                    urls.append(f'http://[{ip}]:8787/' if ':' in ip else f'http://{ip}:8787/')
        return {'available': True, 'urls': urls}
    if operation == 'unlock':
        return grant(owner)
    if not authorized(owner, payload.get('token')):
        raise ValueError('Unlock appliance controls with your administrator password.')
    if operation.startswith('update-'):
        with OPERATIONS:
            if storage_manager.LOCK.locked() or system.PENDING.exists():
                raise ValueError('Finish the storage or network change before updating.')
            return updates.start(operation[7:], payload)
    if updates.locked() and operation in ('storage-switch', 'disk-format', 'pool-scrub', 'ssh-save',
            'network-apply', 'clock-save', 'hostname-save', 'local-tool', 'terminal-open',
            'files-upload', 'files-mkdir', 'files-rename', 'files-delete'):
        raise ValueError('Complete the OS update and trial boot before changing appliance settings.')
    if operation.startswith('terminal-'):
        if operation == 'terminal-open':
            return TERMINALS.create(owner)
        method = {'terminal-read': TERMINALS.poll, 'terminal-write': TERMINALS.send, 'terminal-close': TERMINALS.close}.get(operation)
        if method:
            return method(owner, payload)
    file_methods = {'files-list': files.list_directory, 'files-read': files.read, 'files-upload': files.upload,
                    'files-mkdir': files.mkdir, 'files-rename': files.rename, 'files-delete': files.delete}
    if operation in file_methods:
        return file_methods[operation](payload)
    with OPERATIONS:
        if operation == 'storage-list':
            with storage_manager.LOCK:
                return storage_manager.inventory()
        if operation == 'storage-switch':
            return storage_manager.switch(payload)
        if operation == 'disk-format':
            return storage_manager.format_disk(payload)
        if operation == 'pool-scrub':
            return storage_manager.scrub(payload)
        if operation == 'ssh-save':
            return system.ssh_save(payload)
        if operation == 'network-apply':
            return system.network_apply(payload)
        if operation == 'network-confirm':
            return system.network_confirm(payload)
        if operation == 'network-revert':
            system.rollback_network()
            return {'ok': True}
        if operation == 'clock-save':
            return system.clock_save(payload)
        if operation == 'hostname-save':
            import re
            hostname = payload.get('hostname', '')
            if not re.fullmatch(r'[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?', hostname):
                raise ValueError('Enter a hostname of up to 63 letters, numbers or dashes.')
            system.run('hostnamectl', 'set-hostname', hostname)
            return {'ok': True}
        if operation == 'logs':
            unit = payload.get('unit')
            if unit not in ('plainnvr.service', 'plainnvr-control.service', 'systemd-networkd.service', 'ssh.service', 'plainnvr-boot-mirror.service', 'plainnvr-update.service', 'plainnvr-ab-health.service', 'rauc.service'):
                raise ValueError('Choose an appliance service.')
            return {'text': system.run('journalctl', '-u', unit, '-n', '200', '--no-pager', '-o', 'short-iso')[-65536:]}
        if operation == 'power':
            action = payload.get('action')
            if action not in ('reboot', 'poweroff') or payload.get('confirmation') != action.upper():
                raise ValueError('Type REBOOT or POWEROFF to confirm.')
            if updates.load(updates.STATE / 'job.json', {}).get('state') in updates.BUSY:
                raise ValueError('Wait for the update task to finish before restarting or shutting down.')
            threading.Timer(2, lambda: system.run('systemctl', action)).start()
            return {'ok': True}
        if operation == 'local-tool':
            tool = payload.get('tool')
            if not request.get('local') or tool not in ('files', 'terminal', 'gparted'):
                raise ValueError('Launch desktop tools from the appliance monitor.')
            if storage_manager.LOCK.locked():
                raise ValueError('Wait for the current storage operation to finish.')
            # Explicitly authorized local maintenance; the kiosk returns on exit.
            system.run('systemctl', 'start', '--no-block', f'plainnvr-tool@{tool}.service')
            return {'ok': True}
    raise ValueError('Unknown appliance operation.')


class Handler(socketserver.StreamRequestHandler):
    def handle(self):
        self.connection.settimeout(15)
        _pid, uid, _gid = struct.unpack('3i', self.connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
        if uid != pwd.getpwnam('plainnvr').pw_uid:
            return
        raw = self.rfile.readline(1024 * 1024 + 1)
        if len(raw) > 1024 * 1024 or not raw.endswith(b'\n'):
            return
        try:
            result = dispatch(json.loads(raw))
        except Exception as exc:
            # Never print request bodies, passwords, terminal data or file contents.
            result = {'error': str(exc)[-1500:] if isinstance(exc, (ValueError, OSError)) else 'Appliance operation failed; inspect its service log.'}
        self.wfile.write(json.dumps(result).encode() + b'\n')


class Server(socketserver.ThreadingUnixStreamServer):
    daemon_threads = True


if __name__ == '__main__':
    os.umask(0o077)
    system.STATE.mkdir(parents=True, exist_ok=True)
    SOCKET.parent.mkdir(parents=True, exist_ok=True)
    SOCKET.parent.chmod(0o755)
    SOCKET.unlink(missing_ok=True)
    if system.PENDING.exists():
        system.rollback_network()
    TERMINALS = Terminals()
    with Server(str(SOCKET), Handler) as server:
        os.chown(SOCKET, 0, pwd.getpwnam('plainnvr').pw_gid)
        SOCKET.chmod(0o660)
        server.serve_forever()
