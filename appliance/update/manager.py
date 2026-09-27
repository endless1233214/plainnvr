"""GitHub release discovery and administrator-facing update operations."""
import json
import re
import time
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, HTTPSHandler, HTTPRedirectHandler, build_opener
from common import CONFIG, STATE, configuration, current, load, save, run

REPOSITORY = 'endless1233214/plainnvr'
COMPATIBLE = 'plainnvr-os-amd64-ab-v1'
VERSION = Path('/usr/lib/plainnvr/update/VERSION')
BUSY = {'checking', 'downloading', 'installing', 'rolling-back'}
MAX_BYTES = 6 * 1024**3


def version_tuple(value):
    if not isinstance(value, str) or not re.fullmatch(r'\d{1,5}\.\d{1,5}\.\d{1,5}', value):
        raise ValueError('Invalid OS release version.')
    return tuple(map(int, value.split('.')))


def allowed_url(url):
    parsed = urlparse(url)
    return (parsed.scheme == 'https' and not parsed.username and not parsed.password
            and parsed.port in (None, 443) and parsed.hostname in
            {'api.github.com', 'github.com', 'release-assets.githubusercontent.com', 'objects.githubusercontent.com'})


class Redirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not allowed_url(newurl): raise ValueError('Release download redirected to an untrusted host.')
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def open_url(url):
    if not allowed_url(url): raise ValueError('Invalid release download address.')
    return build_opener(HTTPSHandler(), Redirects()).open(Request(url, headers={
        'User-Agent': 'PlainNVR-OS-Updater', 'Accept': 'application/vnd.github+json',
        'X-GitHub-Api-Version': '2022-11-28'}), timeout=30)


def release_info(release, channel):
    if release.get('draft') or (release.get('prerelease') and channel != 'preview'): return None
    tag = release.get('tag_name', '')
    if not re.fullmatch(r'os-v\d{1,5}\.\d{1,5}\.\d{1,5}', tag): return None
    version = tag[4:]
    name = f'plainnvr-os-{version}-amd64.raucb'
    assets = [a for a in release.get('assets', []) if a.get('name') == name]
    if len(assets) != 1: return None
    asset = assets[0]
    url = f'https://github.com/{REPOSITORY}/releases/download/{tag}/{name}'
    digest = asset.get('digest', '')
    if (asset.get('browser_download_url') != url or not isinstance(asset.get('size'), int)
            or not 4096 <= asset['size'] <= MAX_BYTES or not re.fullmatch('sha256:[a-f0-9]{64}', digest)):
        return None
    return {'version': version, 'url': url, 'size': asset['size'], 'sha256': digest[7:],
            'notes': str(release.get('body') or '')[:12000], 'prerelease': bool(release.get('prerelease')),
            'page': f'https://github.com/{REPOSITORY}/releases/tag/{tag}'}


def discover():
    channel = load('/etc/plainnvr/update-source.json', {}).get('channel', 'stable')
    candidates = []
    # App/Docker releases in this repository do not count as OS releases.
    for page in range(1, 4):
        with open_url(f'https://api.github.com/repos/{REPOSITORY}/releases?per_page=100&page={page}') as response:
            raw = response.read(4 * 1024**2 + 1)
        if len(raw) > 4 * 1024**2: raise ValueError('Release listing is too large.')
        releases = json.loads(raw)
        if not isinstance(releases, list): raise ValueError('GitHub did not return a release listing.')
        candidates.extend(info for release in releases if (info := release_info(release, channel)))
        if len(releases) < 100: break
    newer = [item for item in candidates if version_tuple(item['version']) > version_tuple(VERSION.read_text().strip())]
    release = max(newer, key=lambda x: version_tuple(x['version'])) if newer else None
    save(STATE / 'releases.json', {'checked': int(time.time()), 'release': release})
    return release


def locked():
    return bool(load(STATE / 'pending.json')) or load(STATE / 'job.json', {}).get('state') in BUSY


def status():
    if not CONFIG.exists():
        return {'supported': False, 'message': 'This installation uses the previous disk layout. Back up your data and reinstall with installer 6 or newer to enable A/B updates.'}
    slot = current()
    cache = load(STATE / 'releases.json', {})
    downloaded = load(STATE / 'downloaded.json', {})
    return {'supported': True, 'version': VERSION.read_text().strip(), 'slot': slot,
            'slots': load(STATE / 'slots.json', {}), 'repository': REPOSITORY,
            'channel': load('/etc/plainnvr/update-source.json', {}).get('channel', 'stable'),
            'release': cache.get('release'), 'checked': cache.get('checked'),
            'downloaded': downloaded.get('version') if (STATE / 'download.raucb').is_file() else None,
            'pending': load(STATE / 'pending.json'), 'job': load(STATE / 'job.json', {'state': 'idle'}),
            'last_result': load(STATE / 'last-result.json'), 'locked': locked()}


def start(action, payload):
    configuration()
    if locked(): raise ValueError('Finish the current update or trial boot first.')
    if action == 'channel':
        channel = payload.get('channel')
        if channel not in ('stable', 'preview'): raise ValueError('Choose Stable or Preview.')
        save('/etc/plainnvr/update-source.json', {'repository': REPOSITORY, 'channel': channel})
        (STATE / 'releases.json').unlink(missing_ok=True)
        return {'message': 'Update channel saved.'}
    if action not in ('check', 'download', 'install', 'rollback'): raise ValueError('Unknown update operation.')
    request = {'action': action}
    if action == 'download':
        release = load(STATE / 'releases.json', {}).get('release')
        if not release or release['version'] != payload.get('version'): raise ValueError('Check for updates and select the available release.')
        request['release'] = release
    if action == 'install':
        release = load(STATE / 'downloaded.json')
        if not release or not (STATE / 'download.raucb').is_file(): raise ValueError('Download and verify an update first.')
        if payload.get('confirmation') != 'INSTALL ' + release['version']: raise ValueError('Type INSTALL followed by the downloaded version.')
        request['release'] = release
    if action == 'rollback':
        other = 'B' if current() == 'A' else 'A'
        previous = load(STATE / 'slots.json', {}).get(other, {})
        if not previous.get('healthy'): raise ValueError('The other system slot has not passed a health check.')
        if payload.get('confirmation') != 'ROLLBACK': raise ValueError('Type ROLLBACK to select the previous system.')
        request.update(target=other, version=previous['version'])
    save(STATE / 'request.json', request)
    save(STATE / 'job.json', {'state': {'check': 'checking', 'download': 'downloading', 'install': 'installing', 'rollback': 'rolling-back'}[action], 'message': 'Starting ' + action + '…'})
    try: run('systemctl', 'start', '--no-block', 'plainnvr-update.service')
    except Exception:
        save(STATE / 'job.json', {'state': 'failed', 'message': 'Could not start the update service.'})
        raise
    return {'message': 'Update task started. Progress appears in Updates.'}
