#!/usr/bin/python3
"""Bounded startup report; never read application configuration or key files."""
import base64
import datetime
import grp
import html
import os
import re
import subprocess
from pathlib import Path

UNITS = ('plainnvr', 'plainnvr-setup', 'plainnvr-control', 'plainnvr-ab-prepare',
         'plainnvr-ab-health', 'plainnvr-kiosk@tty1')


def redact(text):
    text = re.sub(r'(?i)(?:rtsp|rtsps|http|https|smb)://[^\s<>"\']+', '[URL omitted]', text)
    text = re.sub(r'(?i)^.*(?:password|passwd|secret|token|authorization|cookie|private.key|setup.code|pair.code|hash["\s]*[:=]).*$',
                  '[credential-bearing line omitted]', text, flags=re.MULTILINE)
    return text


def command(*args):
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=5)
        return redact((result.stdout + result.stderr)[-100000:])
    except (OSError, subprocess.SubprocessError) as exc:
        return 'Unavailable: ' + str(exc)


def collect():
    report = ['PlainNVR OS startup report', datetime.datetime.now(datetime.timezone.utc).isoformat(),
              'Contains device names, local IP addresses and service errors. Review before sharing.']
    for args in [('uname', '-a'), ('cat', '/proc/cmdline'),
                 ('findmnt', '-nro', 'SOURCE,FSTYPE,OPTIONS', '/'),
                 ('ip', '-brief', 'address'),
                 ('lsblk', '-o', 'NAME,SIZE,FSTYPE,MOUNTPOINTS'),
                 ('efibootmgr', '-v'),
                 ('systemctl', '--failed', '--no-pager', '--no-legend')]:
        report.extend(['\n$ ' + ' '.join(args), command(*args)])
    for path in ('/persist', '/persist/system', '/persist/system/config', '/etc/plainnvr/first-boot',
                 '/etc/plainnvr/setup-complete'):
        try:
            st = Path(path).stat()
            report.append(f'{path}: mode={st.st_mode & 0o7777:o} uid={st.st_uid} gid={st.st_gid}')
        except OSError as exc:
            report.append(f'{path}: {exc}')
    for unit in UNITS:
        report.extend(['\nService: ' + unit, command('systemctl', 'show', unit, '-p',
                       'ActiveState,SubState,Result,ExecMainStatus'),
                       command('journalctl', '-b', '-u', unit, '-n', '60', '--no-pager', '-o', 'short-iso')])
    report.extend(['\nRecent kernel errors', command('journalctl', '-b', '-k', '-p', 'warning',
                   '-n', '60', '--no-pager', '-o', 'short-iso')])
    return '\n'.join(report)


def publish(text):
    directory = Path('/run/plainnvr-support')
    gid = grp.getgrnam('plainnvr-kiosk').gr_gid
    directory.mkdir(exist_ok=True)
    os.chown(directory, 0, gid)
    directory.chmod(0o750)
    encoded = base64.b64encode(text.encode()).decode()
    page = ('<!doctype html><meta charset="utf-8"><title>PlainNVR startup diagnostics</title>'
            '<style>body{background:#10171c;color:#f4f7f8;font:16px system-ui;padding:24px}'
            'a{color:#70ddd1;margin-right:24px}pre{white-space:pre-wrap;overflow-wrap:anywhere}</style>'
            '<h1>Startup diagnostics</h1><p>'
            '<a href="file:///opt/plainnvr/current/kiosk/recovery.html">Back to startup</a>'
            f'<a download="plainnvr-startup.txt" href="data:text/plain;base64,{encoded}">Save log dump</a></p>'
            '<p>Saved downloads are in /var/lib/plainnvr-kiosk/Downloads. '
            'The live USB recovery tool can also export installed-system logs.</p>'
            '<pre>' + html.escape(text) + '</pre>')
    for name, value in [('diagnostics.txt', text), ('index.html', page)]:
        temporary = directory / (name + '.new')
        temporary.write_text(value)
        os.chown(temporary, 0, gid)
        temporary.chmod(0o640)
        temporary.replace(directory / name)


if __name__ == '__main__':
    publish(collect())
