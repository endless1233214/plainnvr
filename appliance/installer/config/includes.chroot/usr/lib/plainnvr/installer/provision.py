#!/usr/bin/python3
"""Apply the live wizard's hashed administrator to the installed appliance."""
import json
import os
import subprocess
from pathlib import Path

os.umask(0o077)
settings_file = Path('/etc/plainnvr/install-settings.json')
settings = json.loads(settings_file.read_text())
if settings.get('admin'):
    state = Path('/var/lib/plainnvr-setup')
    state.mkdir(mode=0o700, exist_ok=True)
    (state / 'admin.json').write_text(json.dumps(settings['admin']))
Path('/etc/plainnvr/setup-remote').touch(mode=0o600)
# The offline installer does not need to configure the live session's network.
# Match wired devices on the installed host, including changed PCI enumeration.
network = Path('/etc/systemd/network')
network.mkdir(parents=True, exist_ok=True)
network.chmod(0o755)
(network / '20-plainnvr-wired.network').write_text('[Match]\nName=en* eth*\n\n[Link]\nRequiredForOnline=no\n\n[Network]\nDHCP=yes\n')
(network / '20-plainnvr-wired.network').chmod(0o644)
Path('/etc/network/interfaces').write_text('auto lo\niface lo inet loopback\n')
subprocess.run(['systemctl', 'disable', 'networking.service'], check=True)
subprocess.run(['systemctl', 'enable', 'systemd-networkd.service', 'systemd-resolved.service'], check=True)
resolv = Path('/etc/resolv.conf')
resolv.unlink(missing_ok=True)
resolv.symlink_to('/run/systemd/resolve/stub-resolv.conf')
# The setup service generates a fresh claim code on the installed machine.
settings_file.unlink()
