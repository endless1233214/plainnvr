import importlib.util
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'setup'))
sys.path.insert(0, str(ROOT / 'control'))
import storage
import system
import files
import storage_manager

spec = importlib.util.spec_from_file_location('control_server', ROOT / 'control/server.py')
broker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(broker)


class SMBStorage(unittest.TestCase):
    def selection(self):
        return dict(mode='smb', data_directory='config', recording_directory='recordings',
                    smb_host='192.168.1.10', smb_share='recordings', smb_username='camera',
                    smb_domain='', smb_password='not-in-public-plan', smb_acknowledged=True)

    def test_smb_validates_without_enumerating_or_formatting_local_disks(self):
        with patch.object(storage, 'inventory', side_effect=AssertionError('unneeded disk scan')):
            plan = storage.validate(self.selection())
        self.assertNotIn('smb_password', plan)
        self.assertNotIn('not-in-public-plan', json.dumps(plan))

    def test_mount_and_credentials_injection_is_rejected(self):
        for field, value in [('smb_host', 'nas\nOptions=rw'), ('smb_host', 'nas%H'),
                             ('smb_share', '../other'), ('smb_share', 'share,guest'),
                             ('smb_username', 'user\npassword=other'), ('smb_domain', 'work\x00group'),
                             ('smb_acknowledged', False)]:
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                storage.validate(dict(self.selection(), **{field: value}))

    def test_credentials_are_private_and_password_newlines_rejected(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(storage, 'SMB_CREDENTIALS', Path(directory) / 'smb.credentials'):
            plan = storage.validate(self.selection())
            storage.save_smb_credentials(plan, 'test-password')
            self.assertEqual(storage.SMB_CREDENTIALS.stat().st_mode & 0o777, 0o600)
            self.assertIn('password=test-password\n', storage.SMB_CREDENTIALS.read_text())
            with self.assertRaises(ValueError):
                storage.save_smb_credentials(plan, 'bad\nusername=intruder')


class PrivilegeBoundary(unittest.TestCase):
    def test_grant_is_scoped_to_browser_session(self):
        owner, other = 'a' * 64, 'b' * 64
        token = broker.grant(owner)['token']
        self.assertTrue(broker.authorized(owner, token))
        self.assertFalse(broker.authorized(other, token))
        with patch.object(files, 'read') as read:
            with self.assertRaises(ValueError):
                broker.dispatch({'operation': 'files-read', 'owner': other,
                                 'payload': {'token': token, 'path': '/etc/shadow'}})
            read.assert_not_called()

    def test_expired_grant_cannot_execute(self):
        token = broker.grant('a' * 64)['token']
        broker.GRANTS[token] = ('a' * 64, time.monotonic() - 1)
        self.assertFalse(broker.authorized('a' * 64, token))

    def test_ssh_private_key_and_options_cannot_be_installed(self):
        for key in ('-----BEGIN OPENSSH PRIVATE KEY-----', 'command="id" ssh-ed25519 AAAA'):
            with patch.object(system, 'write') as write, self.assertRaises(ValueError):
                system.ssh_save({'enabled': True, 'keys': [{'label': 'test', 'public_key': key, 'enabled': True}]})
            write.assert_not_called()

    def test_ssh_cannot_be_enabled_without_an_authorized_key(self):
        with self.assertRaises(ValueError):
            system.ssh_save({'enabled': True, 'keys': []})

    def test_format_rejects_disk_not_in_blank_inventory(self):
        with patch.object(storage, 'inventory', return_value={'disks': []}), patch.object(system, 'run') as run:
            with self.assertRaises(ValueError):
                storage_manager.format_disk({'disk': '/dev/sda', 'confirmation': 'FORMAT /dev/sda'})
            run.assert_not_called()


class NetworkSafety(unittest.TestCase):
    def test_invalid_interface_or_static_config_is_rejected(self):
        for request in ({'interface': 'eth0\n', 'mode': 'dhcp'},
                        {'interface': 'eth0', 'mode': 'static', 'address': '192.168.1.2\nDHCP=yes', 'gateway': '192.168.1.1', 'dns': '1.1.1.1'},
                        {'interface': 'eth0', 'mode': 'static', 'address': '192.168.1.2/24', 'gateway': '::1', 'dns': '1.1.1.1'}):
            with self.assertRaises(ValueError):
                system.network_plan(request, [{'ifname': 'eth0'}])

    def test_rollback_restores_exact_previous_network_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(system, 'STATE', root), patch.object(system, 'CONFIG', root / 'config'), patch.object(system, 'NETWORK', root / 'network'), patch.object(system, 'PENDING', root / 'pending.json'), patch.object(system, 'reload_network') as reload:
                system.NETWORK.write_text('new config')
                system.save(system.PENDING, {'old_file': 'previous config\n', 'old_config': {'mode': 'dhcp'}})
                system.rollback_network()
                self.assertEqual(system.NETWORK.read_text(), 'previous config\n')
                self.assertFalse(system.PENDING.exists())
                reload.assert_called_once()


class FileSafety(unittest.TestCase):
    def test_upload_never_overwrites_a_file_or_symlink(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'existing'
            path.write_text('preserve')
            link = Path(directory) / 'link'; link.symlink_to(path)
            for target in (path, link):
                with self.assertRaises(FileExistsError):
                    files.upload({'path': str(target), 'data': 'Y2hhbmdl'})
            self.assertEqual(path.read_text(), 'preserve')

    def test_deletion_needs_exact_confirmation_and_cannot_recurse(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory) / 'folder'; folder.mkdir(); (folder / 'keep').touch()
            with self.assertRaises(ValueError):
                files.delete({'path': str(folder), 'confirmation': 'DELETE wrong'})
            with self.assertRaises(OSError):
                files.delete({'path': str(folder), 'confirmation': 'DELETE folder'})
            self.assertTrue((folder / 'keep').exists())
