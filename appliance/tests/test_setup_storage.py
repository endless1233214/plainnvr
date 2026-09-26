import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

path = Path(__file__).resolve().parents[1] / 'setup/storage.py'
spec = importlib.util.spec_from_file_location('setup_storage', path)
storage = importlib.util.module_from_spec(spec)
spec.loader.exec_module(storage)


class StorageSafety(unittest.TestCase):
    def selection(self, **changes):
        result = {'mode': 'default', 'data_directory': 'config', 'recording_directory': 'recordings'}
        result.update(changes)
        return result

    def test_directory_escape_and_unit_injection(self):
        for value in ('/etc', '../etc', 'a/../../etc', 'a//b', '.', 'a\nb', 'a b', 'a;reboot', 'a\\b'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                storage.subdirectory(value)
        self.assertEqual(storage.subdirectory('camera-data/recordings'), 'camera-data/recordings')

    def test_overlapping_directories_are_rejected(self):
        for value in ('config', 'config/cameras'):
            with self.assertRaises(ValueError):
                storage.validate(self.selection(recording_directory=value))

    @patch.object(storage, 'inventory')
    def test_zfs_needs_explicit_blank_disks_and_confirmation(self, inventory):
        inventory.return_value = {'disks': [{'id': '/dev/disk/by-id/test-a'}, {'id': '/dev/disk/by-id/test-b'}],
                                  'filesystems': [], 'pools': [], 'zfs_available': True}
        request = self.selection(mode='zfs-create', pool='cameras', dataset='plainnvr', layout='mirror',
                                 disks=['/dev/disk/by-id/test-a', '/dev/disk/by-id/test-b'], confirmation='CREATE cameras')
        self.assertEqual(storage.validate(request)['layout'], 'mirror')
        for changes in ({'confirmation': ''}, {'disks': ['/dev/sda', '/dev/sdb']},
                        {'disks': ['/dev/disk/by-id/test-a']},
                        {'disks': ['/dev/disk/by-id/test-a'] * 2}, {'pool': 'x\nExecStart=reboot'}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                storage.validate(dict(request, **changes))

    @patch.object(storage, 'inventory', return_value={'filesystems': []})
    def test_unknown_or_mounted_filesystem_is_rejected(self, inventory):
        with self.assertRaises(ValueError):
            storage.validate(self.selection(mode='filesystem', uuid='unknown'))

    def test_symlink_cannot_escape_selected_volume(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'escape').symlink_to('/etc')
            with patch.object(storage.pwd, 'getpwnam'):
                with self.assertRaises(ValueError):
                    storage.empty_directory(root, 'escape/new-directory')


if __name__ == '__main__':
    unittest.main()
