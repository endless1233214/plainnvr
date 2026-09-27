import contextlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'support'))
import diagnostics
import recovery


class RecoverySafety(unittest.TestCase):
    def test_reports_remove_credentials_and_camera_urls(self):
        report = diagnostics.redact('camera rtsp://operator:secret@192.168.1.2/live?token=abc\nPassword=secret\n'
                                    'Authorization: Bearer abc\nsetup code: 12345\nservice failed with exit 1')
        for private in ['operator', 'secret', 'abc', '12345']:
            self.assertNotIn(private, report)
        self.assertIn('service failed with exit 1', report)

    def test_parent_symlink_cannot_escape_installation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'system').symlink_to('/etc', target_is_directory=True)
            with self.assertRaises(ValueError):
                recovery.directory(root, 'system/config')
            with self.assertRaises(ValueError):
                recovery.directory(root, '../elsewhere')

    def test_invalid_device_references_are_rejected(self):
        for reference in ['/dev/sda', '/etc/passwd', '/dev/disk/by-uuid/../../sda', None]:
            with self.subTest(reference=reference), self.assertRaises(ValueError):
                recovery.device(reference)

    def test_support_writer_refuses_symlink_targets_and_parents(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'linked').symlink_to('/etc', target_is_directory=True)
            (root / 'file').symlink_to('/etc/passwd')
            for name in ['linked/new-file', 'file', '../outside']:
                with self.subTest(name=name), self.assertRaises(ValueError):
                    recovery.write_support(root, name, b'not written')

    def test_support_writer_preserves_neighbor_data_under_installer_umask(self):
        import os
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'account-data').write_bytes(b'keep me')
            previous = os.umask(0o077)
            try:
                recovery.write_support(root, 'new/support/report', b'report')
            finally:
                os.umask(previous)
            self.assertEqual((root / 'new').stat().st_mode & 0o777, 0o755)
            self.assertEqual((root / 'new/support/report').stat().st_mode & 0o777, 0o644)
            self.assertEqual((root / 'account-data').read_bytes(), b'keep me')

    def test_wrong_volume_mapping_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'system/config').mkdir(parents=True)
            config = {'layout': 1, 'mirror': False, 'slots': {'A': 'a', 'B': 'b'}, 'data_device': 'data'}
            (root / 'system/config/ab.json').write_text(json.dumps(config))
            with patch.object(recovery, 'device', side_effect=lambda ref: '/dev/' + ref), \
                 self.assertRaisesRegex(ValueError, 'mapping'):
                recovery.configuration(root, '/dev/wrong')

    def test_bad_second_slot_prevents_all_writes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = {'slots': {'A': 'a', 'B': 'b'}}
            @contextlib.contextmanager
            def mount(source, write=False):
                self.assertFalse(write, 'No writes allowed before every slot is validated')
                yield root
            with patch.object(recovery.os, 'geteuid', return_value=0), \
                 patch.object(recovery.Path, 'read_text', return_value='boot=live'), \
                 patch.object(recovery, 'mounted', side_effect=mount), \
                 patch.object(recovery, 'configuration', return_value=config), \
                 patch.object(recovery, 'device', side_effect=lambda ref: ref), \
                 patch.object(recovery, 'verify_root', side_effect=[None, ValueError('bad second slot')]), \
                 self.assertRaisesRegex(ValueError, 'bad second slot'):
                recovery.repair({'device': 'data'})

    def test_repair_refuses_running_installed_os(self):
        with patch.object(recovery.os, 'geteuid', return_value=0), \
             patch.object(recovery.Path, 'read_text', return_value='root=/dev/vda3 rauc.slot=A'), \
             self.assertRaisesRegex(ValueError, 'live USB'):
            recovery.repair({'device': 'data'})
