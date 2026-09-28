import sys
import os
import unittest
import json
import tempfile
import sqlite3
import shutil
from contextlib import closing, nullcontext
from unittest.mock import patch
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'update'))
import manager
import initialize
import slots
import health


class FailedTrialRecovery(unittest.TestCase):
    def test_database_restore_disables_failed_rollback_slot(self):
        with tempfile.TemporaryDirectory() as temporary:
            state = Path(temporary)
            database = state / 'app.sqlite3'
            with closing(sqlite3.connect(database)) as db: db.execute('pragma user_version=0')
            shutil.copyfile(database, state / 'before-trial.sqlite3')
            with closing(sqlite3.connect(database)) as db: db.execute('pragma user_version=99')
            (state / 'pending.json').write_text(json.dumps({'previous': 'A', 'target': 'B', 'version': '0.2.1',
                'phase': 'trial', 'database_existed': True}))
            (state / 'slots.json').write_text(json.dumps({'A': {'version': '0.2.0', 'healthy': True},
                                                        'B': {'version': '0.2.1', 'healthy': True}}))
            with patch.object(health, 'STATE', state), patch.object(health, 'current', return_value='A'), \
                 patch.object(health, 'database', return_value=database), patch.object(health, 'configuration'), \
                 patch.object(health, 'esp_mounts', return_value=nullcontext([])), patch.object(health.os, 'chown'):
                health.prepare()
            with closing(sqlite3.connect(database)) as db:
                self.assertEqual(db.execute('pragma user_version').fetchone()[0], 0)
            self.assertFalse((state / 'pending.json').exists())
            self.assertFalse(json.loads((state / 'slots.json').read_text())['B']['healthy'])
            self.assertEqual(json.loads((state / 'last-result.json').read_text())['state'], 'rolled-back')
            with patch.object(manager, 'STATE', state), patch.object(manager, 'current', return_value='A'), \
                 patch.object(manager, 'configuration'):
                with self.assertRaisesRegex(ValueError, 'not passed a health check'):
                    manager.start('rollback', {'confirmation': 'ROLLBACK'})


class ClonedRootConfiguration(unittest.TestCase):
    def test_runtime_mounts_and_persistent_control_state(self):
        previous_mask = os.umask(0o077)
        self.addCleanup(os.umask, previous_mask)
        with tempfile.TemporaryDirectory() as temporary, patch.object(slots, 'run'), patch.object(slots.os, 'chown'):
            root = Path(temporary)
            (root / 'etc/systemd/system').mkdir(parents=True)
            (root / 'var/lib').mkdir(parents=True)
            config = {'slots': {'A': '/dev/test-a', 'B': '/dev/test-b'}, 'data_device': '/dev/test-data'}
            slots.configure_root(root, config, 'B')
            for name in ('dev', 'proc', 'sys', 'run', 'tmp', 'var/tmp', 'var/lib/plainnvr'):
                self.assertTrue((root / name).is_dir())
            self.assertEqual((root / 'tmp').stat().st_mode & 0o7777, 0o1777)
            self.assertEqual(root.stat().st_mode & 0o7777, 0o755)
            self.assertEqual((root / 'persist').stat().st_mode & 0o7777, 0o711)
            self.assertEqual((root / 'var/lib/plainnvr-control').readlink(), Path('/persist/system/control'))
            override = (root / 'etc/systemd/system/plainnvr-control.service.d/ab.conf').read_text()
            self.assertIn('Requires=plainnvr-ab-prepare.service', override)
            self.assertIn('[Service]\nStateDirectory=\n', override)
            kiosk = (root / 'etc/systemd/system/plainnvr-kiosk@tty1.service.d/ab.conf').read_text()
            self.assertIn('After=plainnvr-ab-prepare.service', kiosk)
            self.assertNotIn('Requires=plainnvr-ab-prepare.service', kiosk)


class InstallerBootPartition(unittest.TestCase):
    def probe(self, *, kind='linux', filesystem='vfat', size=1024458752, number='2'):
        efi = 'c12a7328-f81f-11d2-ba4b-00a0c93ec93b'
        linux = '0fc63daf-8483-4772-8e79-3d69d8477de4'
        props = {'TYPE': filesystem, 'PART_ENTRY_SCHEME': 'gpt', 'PART_ENTRY_NUMBER': number,
                 'PART_ENTRY_TYPE': efi if kind == 'efi' else linux}
        def command(*args, **kwargs):
            if args[0] == 'lsblk':
                return json.dumps({'blockdevices': [{'name': '/dev/vda', 'children': [
                    {'name': '/dev/vda2', 'type': 'part'}]}]})
            if args[:4] == ('blkid', '-p', '-o', 'export'):
                return '\n'.join(f'{k}={v}' for k, v in props.items())
            if args[0] == 'blockdev': return str(size)
            if args[0] == 'parted':
                props['PART_ENTRY_TYPE'] = efi
                return ''
            if args[:4] == ('blkid', '-p', '-s', 'PART_ENTRY_TYPE'): return props['PART_ENTRY_TYPE']
            raise AssertionError(args)
        return command

    def test_bios_partition_is_normalized_and_reprobed(self):
        with patch.object(initialize, 'run', side_effect=self.probe()) as command:
            self.assertEqual(initialize.prepare_esp('/dev/vda'), '/dev/vda2')
            command.assert_any_call('parted', '--script', '/dev/vda', 'set', '2', 'esp', 'on')
            command.assert_any_call('blkid', '-p', '-s', 'PART_ENTRY_TYPE', '-o', 'value', '/dev/vda2')

    def test_existing_efi_partition_needs_no_change(self):
        with patch.object(initialize, 'run', side_effect=self.probe(kind='efi')) as command:
            self.assertEqual(initialize.prepare_esp('/dev/vda'), '/dev/vda2')
            self.assertNotIn('parted', [call.args[0] for call in command.call_args_list])

    def test_non_recipe_partitions_are_never_modified(self):
        for changes in ({'filesystem': 'ext4'}, {'size': 32_000_000_000}, {'number': '3'}):
            with self.subTest(changes=changes), patch.object(initialize, 'run', side_effect=self.probe(**changes)) as command:
                with self.assertRaises(RuntimeError): initialize.prepare_esp('/dev/vda')
                self.assertNotIn('parted', [call.args[0] for call in command.call_args_list])

    def test_root_fallback_tries_every_recorded_esp(self):
        script = initialize.grub_fallback_bootstrap(['1073-D84E', '22AA-44BB'])
        self.assertIn('search --no-floppy --fs-uuid --set=plainnvr_boot 1073-D84E', script)
        self.assertIn('search --no-floppy --fs-uuid --set=plainnvr_boot 22AA-44BB', script)
        self.assertIn('configfile $prefix/grub.cfg', script)
        with self.assertRaises(RuntimeError):
            initialize.grub_fallback_bootstrap(['1073-D84E; reboot'])


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
