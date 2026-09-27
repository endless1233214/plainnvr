"""Bounded, expiring PTY sessions owned by one authenticated browser session."""
import base64
import fcntl
import os
import pty
import secrets
import select
import signal
import struct
import subprocess
import sys
import termios
import threading
import time


class Terminals:
    def __init__(self):
        self.sessions = {}
        self.lock = threading.RLock()
        threading.Thread(target=self.reap, daemon=True).start()

    def create(self, owner):
        with self.lock:
            if len(self.sessions) >= 4:
                raise ValueError('Close another terminal before opening a new one.')
            master, slave = pty.openpty()
            fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack('HHHH', 24, 100, 0, 0))
            process = subprocess.Popen(['/usr/bin/python3', __file__, '--shell'],
                stdin=slave, stdout=slave, stderr=slave, start_new_session=True,
                close_fds=True, cwd='/var/lib/plainnvr',
                env={'PATH': '/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin',
                     'TERM': 'xterm-256color', 'LANG': 'C.UTF-8', 'HOME': '/root',
                     'HISTFILE': '/dev/null', 'PS1': 'plainnvr:\\w# '})
            os.close(slave)
            identity = secrets.token_hex(24)
            session = {'owner': owner, 'process': process, 'fd': master, 'buffer': bytearray(),
                       'start': 0, 'touched': time.monotonic(), 'closed': False}
            self.sessions[identity] = session
            threading.Thread(target=self.read, args=(session,), daemon=True).start()
            return {'id': identity, 'offset': 0}

    def read(self, session):
        try:
            while not session['closed']:
                if not select.select([session['fd']], [], [], 1)[0]:
                    continue
                chunk = os.read(session['fd'], 16384)
                if not chunk:
                    break
                with self.lock:
                    session['buffer'].extend(chunk)
                    overflow = max(0, len(session['buffer']) - 262144)
                    if overflow:
                        del session['buffer'][:overflow]
                        session['start'] += overflow
        except OSError:
            pass

    def get(self, owner, identity):
        session = self.sessions.get(identity)
        if not session or session['owner'] != owner:
            raise ValueError('Terminal session is unavailable.')
        return session

    def poll(self, owner, payload):
        with self.lock:
            session = self.get(owner, payload.get('id'))
            offset = int(payload.get('offset', 0))
            if offset < 0 or offset > session['start'] + len(session['buffer']):
                raise ValueError('Invalid terminal offset.')
            dropped = offset < session['start']
            start = max(0, offset - session['start'])
            raw = bytes(session['buffer'][start:start + 65536])
            return {'data': base64.b64encode(raw).decode(),
                    'offset': session['start'] + start + len(raw), 'dropped': dropped,
                    'exited': session['process'].poll() is not None}

    def send(self, owner, payload):
        with self.lock:
            session = self.get(owner, payload.get('id'))
            data = str(payload.get('data', '')).encode()
            if len(data) > 8192:
                raise ValueError('Terminal input is too large.')
            if 'cols' in payload:
                rows, cols = int(payload.get('rows', 24)), int(payload['cols'])
                if not 2 <= rows <= 200 or not 10 <= cols <= 400:
                    raise ValueError('Invalid terminal dimensions.')
                fcntl.ioctl(session['fd'], termios.TIOCSWINSZ, struct.pack('HHHH', rows, cols, 0, 0))
            if data:
                os.write(session['fd'], data)
            session['touched'] = time.monotonic()
        return {'ok': True}

    def close(self, owner, payload):
        with self.lock:
            session = self.get(owner, payload.get('id'))
            self.sessions.pop(payload['id'])
            session['closed'] = True
            try:
                os.killpg(session['process'].pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            os.close(session['fd'])
            session['process'].wait(timeout=5)
        return {'ok': True}

    def reap(self):
        while True:
            time.sleep(10)
            with self.lock:
                for identity, session in list(self.sessions.items()):
                    if time.monotonic() - session['touched'] > 300:
                        self.close(session['owner'], {'id': identity})


if __name__ == '__main__':
    # Popen starts this helper in a new session; acquire its controlling TTY.
    fcntl.ioctl(0, termios.TIOCSCTTY, 0)
    os.execv('/bin/bash', ['bash', '--noprofile', '--norc', '-i'])
