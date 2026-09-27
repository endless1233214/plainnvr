#!/usr/bin/python3
"""Persistent update worker, independent of the web server and browser session."""
import fcntl
import hashlib
import json
import os
import shutil
import sys
import time
from pathlib import Path
from common import STATE, configuration, verify_slots, load, save, run, esp_mounts, write_env
from manager import COMPATIBLE, VERSION, discover, open_url, version_tuple
from slots import copy_machine, configure_root, refresh_boot

LIB = Path('/usr/lib/plainnvr/update')


def progress(state, message, **extra):
    save(STATE / 'job.json', dict(state=state, message=message, **extra))


def verify_bundle(path, release):
    if path.stat().st_size != release['size']: raise ValueError('Update size does not match the release.')
    with path.open('rb') as stream: digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    if digest != release['sha256']: raise ValueError('Update checksum does not match the release.')
    # rauc info verifies CMS signature, pinned trust, and verity manifest.
    info = json.loads(run('rauc', '--keyring', LIB / 'release.pem', 'info', '--output-format=json', path, timeout=180))
    if info.get('compatible') != COMPATIBLE or info.get('version') != release['version']:
        raise ValueError('Signed update identity does not match this OS release.')
    if info.get('format') != 'verity':
        # RAUC 1.13 reports bundle format; don't accept legacy plain bundles.
        raise ValueError('The update is not a verity bundle.')
    return info


def download(release):
    if version_tuple(release['version']) <= version_tuple(VERSION.read_text().strip()):
        raise ValueError('This OS version is already installed. Use rollback for the previous slot.')
    if shutil.disk_usage(STATE).free < release['size'] + 2 * 1024**3:
        raise ValueError('Free space on the installed data volume must cover the download plus 2 GB.')
    partial = STATE / 'download.partial'
    (STATE / 'downloaded.json').unlink(missing_ok=True)
    try:
        with open_url(release['url']) as response, partial.open('wb') as output:
            total = 0; last = 0
            while chunk := response.read(1024**2):
                total += len(chunk)
                if total > release['size']: raise ValueError('Update download is larger than advertised.')
                output.write(chunk)
                if time.monotonic() - last >= 2:
                    progress('downloading', 'Downloading signed OS update…', percent=round(total * 100 / release['size']))
                    last = time.monotonic()
            output.flush(); os.fsync(output.fileno())
        progress('downloading', 'Checking checksum and release signature…')
        verify_bundle(partial, release)
        os.replace(partial, STATE / 'download.raucb')
        save(STATE / 'downloaded.json', release)
        progress('downloaded', 'Verified update downloaded. Install when ready.')
    finally: partial.unlink(missing_ok=True)


def stage(request):
    config = configuration(); active = verify_slots(config)
    other = 'B' if active == 'A' else 'A'
    # Validate both boot partitions before modifying an inactive system.
    with esp_mounts(config): pass
    rollback = request['action'] == 'rollback'
    version = request['version'] if rollback else request['release']['version']
    if not rollback: verify_bundle(STATE / 'download.raucb', request['release'])
    pending = {'previous': active, 'target': other, 'version': version, 'phase': 'installing', 'rollback': rollback}
    save(STATE / 'pending.json', pending)
    try:
        if rollback:
            target = Path('/run/plainnvr-rollback'); target.mkdir(exist_ok=True)
            run('mount', config['slots'][other], target)
            try:
                copy_machine(target)
                configure_root(target, config, other, Path('/etc/fstab').read_text())
                refresh_boot(config, target, other)
            finally: run('umount', target)
            run(LIB / 'boot.py', 'set-primary', other)
        else:
            progress('installing', 'Writing the inactive system. Keep both boot drives connected.')
            run('rauc', 'install', STATE / 'download.raucb', timeout=2400)
        pending['phase'] = 'ready'; save(STATE / 'pending.json', pending)
        progress('awaiting-reboot', 'Ready. Restart the appliance to try system ' + other + '.')
    except Exception:
        # An incomplete image must never become the default on either drive.
        with esp_mounts(config, require_all=False) as mounts:
            for mount in mounts:
                write_env(mount, ORDER=active + ' ' + other, PENDING='none', **{other + '_OK': '0', other + '_TRY': '0'})
        (STATE / 'pending.json').unlink(missing_ok=True)
        raise


def main():
    os.umask(0o077); STATE.mkdir(parents=True, exist_ok=True)
    with (STATE / 'worker.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        request = load(STATE / 'request.json')
        try:
            if request['action'] == 'check':
                release = discover()
                progress('idle', 'OS ' + release['version'] + ' is available.' if release else 'No newer OS release is available in this channel.')
            elif request['action'] == 'download': download(request['release'])
            else: stage(request)
        except Exception as exc:
            progress('failed', str(exc)[-2000:] or 'Update failed. The current system remains selected.')
            raise


if __name__ == '__main__': main()
