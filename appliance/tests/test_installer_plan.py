import importlib.util
import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch

source = Path(__file__).resolve().parents[1] / 'installer/config/includes.chroot/usr/lib/plainnvr/installer/plan.py'
spec = importlib.util.spec_from_file_location('installer_plan', source)
plan = importlib.util.module_from_spec(spec)
spec.loader.exec_module(plan)


class InstallerDiskSelection(unittest.TestCase):
    def setUp(self):
        self.a = {'name': '/dev/sda', 'size': 64_000_000_000, 'serial': 'DISK-A', 'wwn': 'A', 'maj:min': '8:0', 'blocked': ''}
        self.b = dict(self.a, name='/dev/sdb', serial='DISK-B', wwn='B', **{'maj:min': '8:16'})

    def test_disk_removed_replaced_or_mounted_after_review_is_rejected(self):
        for current in ([], [dict(self.a, serial='REPLACEMENT')], [dict(self.a, blocked='Mounted')]):
            with self.assertRaises(ValueError):
                plan.validate_disks([self.a], current, False)

    def test_mirror_requires_two_distinct_eligible_disks(self):
        for selection in ([self.a], [self.a, self.a], []):
            with self.assertRaises(ValueError):
                plan.validate_disks(selection, [self.a, self.b], True)
        self.assertEqual(plan.validate_disks([self.a, self.b], [self.a, self.b], True), [self.a, self.b])

    def test_installer_usb_cannot_be_selected(self):
        with self.assertRaises(ValueError):
            plan.validate_disks([self.a], [dict(self.a, blocked='Mounted installer USB')], False)

    def test_guided_install_is_offline_and_root_password_is_locked(self):
        template = source.parents[5] / 'includes.installer'
        with tempfile.TemporaryDirectory() as temporary, patch.object(plan, 'STATE', Path(temporary)), patch.object(plan, 'HERE', template), patch.object(plan, 'inventory', return_value=[self.a]):
            plan.prepare({'locale': 'en_US.UTF-8', 'keyboard': 'us', 'timezone': 'UTC', 'admin': None}, [self.a], False)
            seed = (Path(temporary) / 'preseed.cfg').read_text()
            self.assertIn('d-i netcfg/enable boolean false', seed)
            self.assertIn('d-i passwd/root-password-crypted password *', seed)
            self.assertIn('d-i passwd/make-user boolean false', seed)
            self.assertIn('d-i partman-auto/disk string /dev/sda', seed)
            self.assertTrue((Path(temporary) / 'confirmed').exists())

    def test_locale_cannot_inject_another_preseed_directive(self):
        with patch.object(plan, 'inventory', return_value=[self.a]):
            with self.assertRaises(ValueError):
                plan.prepare({'locale': 'en_US\nd-i partman-auto/disk string /dev/sdb', 'keyboard': 'us', 'timezone': 'UTC'}, [self.a], False)
