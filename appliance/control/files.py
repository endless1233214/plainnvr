"""File manager operations for an explicitly unlocked OS administrator."""
import base64
import os
import stat
from pathlib import Path

MAX_FILE = 512 * 1024


def path(value):
    if not isinstance(value, str) or not value.startswith('/') or '\x00' in value or len(value) > 4096:
        raise ValueError('Enter an absolute filesystem path.')
    result = Path(value)
    if '..' in result.parts:
        raise ValueError('Parent traversal is not allowed; use an absolute path.')
    return result


def regular(value):
    target = path(value)
    if not stat.S_ISREG(target.lstat().st_mode):
        raise ValueError('Choose a regular file, not a device, directory or symbolic link.')
    return target


def list_directory(payload):
    target = path(payload.get('path', '/var/lib/plainnvr')).resolve(strict=True)
    entries = []
    with os.scandir(target) as iterator:
        for entry in iterator:
            if len(entries) >= 2000:
                raise ValueError('This directory has more than 2000 entries. Choose a more specific directory.')
            info = entry.stat(follow_symlinks=False)
            entries.append({'name': entry.name, 'directory': entry.is_dir(follow_symlinks=False),
                            'symlink': entry.is_symlink(), 'bytes': info.st_size,
                            'mode': stat.filemode(info.st_mode), 'uid': info.st_uid, 'gid': info.st_gid})
    entries.sort(key=lambda item: (not item['directory'], item['name'].lower()))
    return {'path': str(target), 'parent': str(target.parent), 'entries': entries, 'transfer_limit': MAX_FILE}


def read(payload):
    target = regular(payload.get('path'))
    with target.open('rb') as stream:
        data = stream.read(MAX_FILE + 1)
    if len(data) > MAX_FILE:
        raise ValueError('Browser file transfers are limited to 512 KiB. Use SSH/SFTP for larger files or the recording download page.')
    return {'name': target.name, 'data': base64.b64encode(data).decode()}


def upload(payload):
    target = path(payload.get('path'))
    data = base64.b64decode(payload.get('data', ''), validate=True)
    if len(data) > MAX_FILE:
        raise ValueError('The upload exceeds 512 KiB; use SFTP for larger files.')
    # Exclusive creation never overwrites an existing file or follows a final symlink.
    with target.open('xb') as stream:
        os.chmod(target, 0o600)
        stream.write(data)
    return {'ok': True}


def mkdir(payload):
    target = path(payload.get('path'))
    target.mkdir(mode=0o700)
    return {'ok': True}


def rename(payload):
    source, destination = path(payload.get('path')), path(payload.get('destination'))
    if source == Path('/') or destination.exists() or destination.is_symlink():
        raise ValueError('Choose a new destination that does not already exist.')
    # Both names stay in one directory; a rename does not move files across mounts.
    if source.parent != destination.parent or source.name in ('', '.', '..'):
        raise ValueError('Rename within the same directory.')
    source.rename(destination)
    return {'ok': True}


def delete(payload):
    target = path(payload.get('path'))
    if payload.get('confirmation') != f'DELETE {target.name}' or target == Path('/'):
        raise ValueError('Type DELETE followed by the exact filename to confirm.')
    if target.is_dir() and not target.is_symlink():
        target.rmdir()  # Empty directories only; no recursive deletion.
    else:
        target.unlink()
    return {'ok': True}
