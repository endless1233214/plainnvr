import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'update'))
import manager


class UpdateReleaseMetadata(unittest.TestCase):
    def asset(self, version='0.2.1'):
        name = f'plainnvr-os-{version}-amd64.raucb'
        tag = f'os-v{version}'
        return {
            'name': name,
            'browser_download_url': f'https://github.com/{manager.REPOSITORY}/releases/download/{tag}/{name}',
            'size': 4096,
            'digest': 'sha256:' + 'a' * 64,
        }

    def release(self, version='0.2.1', **changes):
        value = {'tag_name': f'os-v{version}', 'assets': [self.asset(version)],
                 'draft': False, 'prerelease': False, 'body': 'Release notes'}
        value.update(changes)
        return value

    def test_only_os_release_asset_matches(self):
        info = manager.release_info(self.release(), 'stable')
        self.assertEqual(info['version'], '0.2.1')
        self.assertEqual(info['sha256'], 'a' * 64)

    def test_app_release_and_stable_preview_are_ignored(self):
        self.assertIsNone(manager.release_info(self.release(tag_name='v0.2.1'), 'stable'))
        self.assertIsNone(manager.release_info(self.release(prerelease=True), 'stable'))
        self.assertIsNotNone(manager.release_info(self.release(prerelease=True), 'preview'))

    def test_asset_size_digest_and_host_are_strict(self):
        self.assertIsNone(manager.release_info(self.release(assets=[dict(self.asset(), size=4095)]), 'stable'))
        self.assertIsNone(manager.release_info(self.release(assets=[dict(self.asset(), digest='sha1:' + 'a' * 64)]), 'stable'))
        self.assertTrue(manager.allowed_url(self.asset()['browser_download_url']))
        self.assertFalse(manager.allowed_url('https://evil.example/plainnvr.raucb'))

    def test_versions_are_numeric_triplets(self):
        self.assertEqual(manager.version_tuple('1.20.3'), (1, 20, 3))
        with self.assertRaises(ValueError): manager.version_tuple('os-v1.2.3')
