#!/usr/bin/python3
"""Appliance-only setup, bound to loopback and disabled after provisioning."""
import http.cookies
import json
import os
import pwd
import secrets
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.request import urlopen

import storage

sys.path.insert(0, '/opt/plainnvr/current')
from app.auth import password_hash, validate_password, validate_username, verify_password

STATE = storage.STATE
ADMIN = STATE / 'admin.json'
COMPLETE = Path('/etc/plainnvr/setup-complete')
TOKEN = secrets.token_hex(32)
SESSION = secrets.token_hex(32)
HOSTS = ('127.0.0.1:8790', 'localhost:8790')
FAILURES = []


def finish(selection):
    editor = storage.run('systemctl', 'show', '--value', '-p', 'ActiveState', 'plainnvr-gparted.service')
    if editor in ('active', 'activating', 'deactivating'):
        raise ValueError('Close GParted before finishing storage setup.')
    journal_file = STATE / 'installation.json'
    if journal_file.exists():
        journal = json.loads(journal_file.read_text())
        if journal['selection'] != selection:
            directory_fields = {'data_directory', 'recording_directory'}
            progress_file = STATE / 'zfs-progress.json'
            progress = json.loads(progress_file.read_text()) if progress_file.exists() else None
            editable = directory_fields | ({'dataset'} if progress and not progress['dataset_created'] else set())
            original = {k: v for k, v in journal['selection'].items() if k not in editable}
            requested = {k: v for k, v in selection.items() if k not in editable}
            if journal['directories'] or original != requested:
                raise ValueError('Storage setup has already started. Retry the same storage selection to resume.')
            for field in directory_fields:
                journal['plan'][field] = storage.subdirectory(selection.get(field))
            if 'dataset' in editable:
                journal['plan']['dataset'] = storage.named(selection.get('dataset'))
            if journal['plan']['mode'] == 'default':
                storage.validate(journal['plan'])
            journal['selection'] = selection
            storage.save_json(journal_file, journal)
            if progress:
                progress['plan'] = journal['plan']
                storage.save_json(progress_file, progress)
    else:
        journal = {'selection': selection, 'plan': storage.validate(selection), 'directories': False}
        storage.save_json(journal_file, journal)
    plan = journal['plan']
    try:
        recording_mount = storage.prepare(plan)
    except ValueError:
        if plan['mode'].startswith('zfs-') and not (STATE / 'zfs-progress.json').exists():
            # The pool creation/import was rejected before any recorded change.
            # The next attempt may choose a different pool name or disk set.
            journal_file.unlink(missing_ok=True)
        raise
    data = storage.DATA_MOUNT / plan['data_directory']
    recordings = recording_mount / plan['recording_directory']
    if subprocess.run(['runuser', '-u', 'plainnvr', '--', 'test', '-x', str(recording_mount)]).returncode:
        raise ValueError('The recording filesystem does not permit PlainNVR to access it. Adjust its directory permissions in the maintenance console and retry.')
    if not journal['directories']:
        storage.empty_directory(storage.DATA_MOUNT, plan['data_directory'])
        storage.empty_directory(recording_mount, plan['recording_directory'])
        journal['directories'] = True
        storage.save_json(journal_file, journal)
    for path in (data, recordings):
        if path.resolve() != path or not path.is_dir():
            raise ValueError('A storage directory changed during setup.')
        user = pwd.getpwnam('plainnvr')
        os.chown(path, user.pw_uid, user.pw_gid)
        path.chmod(0o700)
    admin = json.loads(ADMIN.read_text())
    result = subprocess.run(['runuser', '-u', 'plainnvr', '--', '/usr/bin/python3',
                             '/usr/lib/plainnvr/setup/seed-admin.py', str(data)],
                            input=json.dumps(admin), capture_output=True, text=True)
    if result.returncode:
        print('Administrator database initialization failed: ' + result.stderr[-2000:], file=sys.stderr)
        raise ValueError('Could not initialize the administrator. Check the setup service journal.')
    config = Path('/etc/plainnvr')
    config.mkdir(mode=0o755, exist_ok=True)
    (config / 'runtime.env').write_text(f'NVR_DATA_DIR={data}\nNVR_RECORDINGS_DIR={recordings}\n')
    dropin = Path('/etc/systemd/system/plainnvr.service.d/storage.conf')
    dropin.parent.mkdir(parents=True, exist_ok=True)
    dropin.write_text('[Unit]\nAfter=zfs-mount.service\n'
                      f'RequiresMountsFor={storage.DATA_MOUNT} {recording_mount}\n'
                      f'AssertPathIsMountPoint={recording_mount}\n'
                      '[Service]\nEnvironmentFile=/etc/plainnvr/runtime.env\n'
                      f'ReadWritePaths={data} {recordings}\n')
    storage.save_json(config / 'storage.json', plan)
    COMPLETE.touch(mode=0o644)
    try:
        storage.run('systemctl', 'daemon-reload')
        storage.run('systemctl', 'start', 'plainnvr.service')
        for _ in range(30):
            try:
                with urlopen('http://127.0.0.1:8787/api/health', timeout=2) as response:
                    if json.load(response).get('ok'):
                        ADMIN.unlink()
                        return
            except (OSError, ValueError):
                pass
            time.sleep(1)
        raise ValueError('PlainNVR did not become ready. Retry setup after checking its service journal.')
    except Exception:
        COMPLETE.unlink(missing_ok=True)
        subprocess.run(['systemctl', 'stop', 'plainnvr.service'], capture_output=True)
        raise


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        # Request bodies and credentials must never be logged.
        return

    def authenticated(self):
        cookies = http.cookies.SimpleCookie()
        try:
            cookies.load(self.headers.get('Cookie', ''))
        except http.cookies.CookieError:
            return False
        cookie = cookies.get('plainnvr_setup')
        return bool(cookie and secrets.compare_digest(cookie.value, SESSION))

    def send(self, value, status=200, cookie=False, html=False):
        body = value.encode() if html else json.dumps(value).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'text/html; charset=utf-8' if html else 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Content-Security-Policy',
                         f"default-src 'self'; script-src 'nonce-{TOKEN}'; style-src 'unsafe-inline'; frame-ancestors 'none'; base-uri 'none'")
        if cookie:
            self.send_header('Set-Cookie', f'plainnvr_setup={SESSION}; HttpOnly; SameSite=Strict; Path=/')
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.headers.get('Host') not in HOSTS:
            return self.send({'error': 'Local setup only.'}, 403)
        if self.path == '/':
            page = Path(__file__).with_name('index.html').read_text().replace('__TOKEN__', TOKEN)
            return self.send(page, html=True)
        if self.path == '/api/state':
            return self.send({'account_exists': ADMIN.exists(), 'authenticated': self.authenticated(),
                              'complete': COMPLETE.exists()})
        if self.path == '/api/storage' and self.authenticated() and not COMPLETE.exists():
            try:
                result = storage.inventory()
                journal = STATE / 'installation.json'
                saved = json.loads(journal.read_text()) if journal.exists() else None
                result['resume_selection'] = saved['selection'] if saved else None
                result['can_change_directories'] = not saved or not saved['directories']
                progress_file = STATE / 'zfs-progress.json'
                progress = json.loads(progress_file.read_text()) if progress_file.exists() else None
                result['can_change_dataset'] = bool(progress and not progress['dataset_created'])
                return self.send(result)
            except (ValueError, OSError, subprocess.SubprocessError) as exc:
                return self.send({'error': str(exc)}, 400)
        return self.send({'error': 'Not found.'}, 404)

    def do_POST(self):
        if (self.headers.get('Host') not in HOSTS or
            self.headers.get('Origin') not in tuple('http://' + host for host in HOSTS) or
            not secrets.compare_digest(self.headers.get('X-Setup-Token', ''), TOKEN)):
            return self.send({'error': 'Reload the local setup page.'}, 403)
        if COMPLETE.exists():
            return self.send({'error': 'Setup is already complete.'}, 409)
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= 32768 or self.headers.get('Content-Type') != 'application/json':
                raise ValueError('Invalid request.')
            payload = json.loads(self.rfile.read(length))
            if not isinstance(payload, dict):
                raise ValueError('Invalid request.')
            if self.path == '/api/admin':
                if ADMIN.exists():
                    raise ValueError('An administrator already exists. Sign in to continue.')
                username = validate_username(payload.get('username'))
                password = validate_password(payload.get('password'))
                storage.save_json(ADMIN, {'username': username, 'hash': password_hash(password)})
                return self.send({'ok': True}, cookie=True)
            if self.path == '/api/login':
                recent = time.monotonic() - 60
                FAILURES[:] = [t for t in FAILURES if t > recent]
                if len(FAILURES) >= 5:
                    return self.send({'error': 'Wait one minute before trying again.'}, 429)
                admin = json.loads(ADMIN.read_text()) if ADMIN.exists() else {}
                if payload.get('username') != admin.get('username') or not verify_password(str(payload.get('password', '')), admin.get('hash', '')):
                    FAILURES.append(time.monotonic())
                    return self.send({'error': 'Incorrect username or password.'}, 403)
                return self.send({'ok': True}, cookie=True)
            if not self.authenticated():
                return self.send({'error': 'Sign in to continue.'}, 403)
            if self.path == '/api/gparted':
                if (STATE / 'installation.json').exists():
                    raise ValueError('Storage setup has started. Finish or recover it before opening GParted.')
                storage.run('systemctl', 'start', '--no-block', 'plainnvr-gparted.service')
                return self.send({'ok': True})
            if self.path == '/api/finish':
                finish(payload)
                self.send({'ok': True, 'url': 'http://127.0.0.1:8787/'})
                threading.Timer(10, self.server.shutdown).start()
                return
            return self.send({'error': 'Not found.'}, 404)
        except (ValueError, OSError, subprocess.SubprocessError) as exc:
            return self.send({'error': str(exc)}, 400)


if __name__ == '__main__':
    os.umask(0o077)
    STATE.mkdir(mode=0o700, parents=True, exist_ok=True)
    if not COMPLETE.exists():
        HTTPServer(('127.0.0.1', 8790), Handler).serve_forever()
