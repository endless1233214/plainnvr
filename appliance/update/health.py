#!/usr/bin/python3
"""Trial boot preparation, database recovery, and bounded health confirmation."""
import json
import os
import shutil
import sqlite3
import sys
import time
from pathlib import Path
from urllib.request import urlopen
from common import STATE, load, save, current, configuration, esp_mounts, write_env, run


def database():
    env = dict(line.split('=', 1) for line in Path('/etc/plainnvr/runtime.env').read_text().splitlines() if '=' in line)
    path = Path(env['NVR_DATA_DIR']) / 'nvr.sqlite3'
    if not path.resolve().is_relative_to(Path('/var/lib/plainnvr').resolve()):
        raise RuntimeError('Configuration database is outside the appliance data volume.')
    return path


def prepare():
    slot = current()
    pending = load(STATE / 'pending.json')
    if not pending:
        if load(STATE / 'job.json', {}).get('state') in ('checking', 'downloading', 'installing', 'rolling-back'):
            save(STATE / 'job.json', {'state': 'failed', 'message': 'The update task was interrupted. Check or download again.'})
        return
    if slot == pending['target']:
        if pending['phase'] != 'trial':
            db = database()
            backup = STATE / 'before-trial.sqlite3'
            temporary = backup.with_suffix('.new')
            temporary.unlink(missing_ok=True)
            if db.exists():
                with sqlite3.connect(f'file:{db}?mode=ro', uri=True) as source:
                    with sqlite3.connect(temporary) as target: source.backup(target)
                with temporary.open('rb') as stream: os.fsync(stream.fileno())
                os.replace(temporary, backup)
            else:
                backup.unlink(missing_ok=True)
            pending['database_existed'] = db.exists()
            pending['phase'] = 'trial'
            save(STATE / 'pending.json', pending)
        return
    # The bootloader returned to the previous slot before marking the trial good.
    if slot != pending['previous']: raise RuntimeError('Unexpected fallback system slot.')
    if pending['phase'] == 'trial' and pending.get('database_existed', True):
        db = database()
        metadata = db.stat()
        backup = STATE / 'before-trial.sqlite3'
        if not backup.is_file(): raise RuntimeError('Trial database backup is missing; manual recovery required.')
        temporary = db.with_suffix('.restore')
        shutil.copyfile(backup, temporary)
        os.chown(temporary, metadata.st_uid, metadata.st_gid)
        os.chmod(temporary, metadata.st_mode & 0o777)
        for suffix in ('-wal', '-shm'): Path(str(db) + suffix).unlink(missing_ok=True)
        os.replace(temporary, db)
        os.sync()
    with esp_mounts(configuration(), require_all=False) as mounts:
        for mount in mounts:
            write_env(mount, ORDER=slot + ' ' + pending['target'], PENDING='none', **{
                slot + '_OK': '1', slot + '_TRY': '0', pending['target'] + '_OK': '0',
                pending['target'] + '_TRY': '0'})
    save(STATE / 'last-result.json', {'state': 'rolled-back', 'version': pending['version'],
                                    'message': 'The trial did not complete; the previous system was restored.'})
    (STATE / 'pending.json').unlink()
    save(STATE / 'job.json', {'state': 'idle', 'message': 'Previous system restored.'})


def healthy():
    configured = Path('/etc/plainnvr/setup-complete').exists()
    url = 'http://127.0.0.1:8787/api/health' if configured else 'http://127.0.0.1:8790/api/state'
    with urlopen(url, timeout=3) as response:
        state = json.load(response)
    if configured and not state.get('ok'): return False
    if configured and not Path('/run/plainnvr-control/control.sock').exists(): return False
    if configured:
        env = dict(line.split('=', 1) for line in Path('/etc/plainnvr/runtime.env').read_text().splitlines() if '=' in line)
        run('runuser', '-u', 'plainnvr', '--', 'test', '-w', env['NVR_RECORDINGS_DIR'], timeout=5)
    return True


def confirm():
    slot = current()
    pending = load(STATE / 'pending.json')
    successes = 0
    for _ in range(24):
        try: successes = successes + 1 if healthy() else 0
        except (OSError, ValueError, RuntimeError): successes = 0
        if successes >= 3:
            other = 'B' if slot == 'A' else 'A'
            with esp_mounts(configuration(), require_all=False) as mounts:
                for mount in mounts: write_env(mount, ORDER=slot + ' ' + other, PENDING='none', **{slot + '_OK': '1', slot + '_TRY': '0'})
            versions = load(STATE / 'slots.json', {})
            version = Path('/usr/lib/plainnvr/update/VERSION').read_text().strip()
            versions[slot] = {'version': version, 'healthy': True}
            save(STATE / 'slots.json', versions)
            if pending:
                save(STATE / 'last-result.json', {'state': 'healthy', 'version': version, 'message': 'Update boot health check passed.'})
                (STATE / 'pending.json').unlink(missing_ok=True)
                save(STATE / 'job.json', {'state': 'idle', 'message': 'Update completed.'})
            return
        time.sleep(5)
    if pending and slot == pending['target']:
        save(STATE / 'last-result.json', {'state': 'failed', 'version': pending['version'], 'message': 'Trial health check failed. Rebooting to the previous system.'})
        run('systemctl', 'reboot')
    raise RuntimeError('Appliance health check did not pass; boot success was not confirmed.')


if __name__ == '__main__':
    if sys.argv[1:] == ['prepare']: prepare()
    else: confirm()
