#!/usr/bin/env python3
"""Generate private credentials/preseeds ONLY for new disposable test VMs.

Never include these outputs in an ISO. Partition write confirmations remain
interactive even in these test preseeds.
"""
import os
import secrets
import subprocess
import sys
from pathlib import Path


if __name__ == '__main__':
    os.umask(0o077)
    root = Path(sys.argv[1]).resolve()
    root.mkdir(mode=0o700, exist_ok=False)
    public = root / 'public'
    public.mkdir()
    password = secrets.token_hex(12)
    (root / 'password.txt').write_text(password + '\n')
    hashed = subprocess.check_output(['openssl', 'passwd', '-6', '-stdin'], input=password, text=True).strip()
    common = f'''# Disposable VM validation only; not distributed.
d-i debian-installer/locale string en_US.UTF-8
d-i keyboard-configuration/xkb-keymap select us
d-i netcfg/choose_interface select auto
d-i netcfg/get_hostname string plainnvr-test
d-i netcfg/get_domain string local
d-i passwd/root-login boolean false
d-i passwd/user-fullname string Installer Test
d-i passwd/username string vmtest
d-i passwd/user-password-crypted password {hashed}
d-i clock-setup/utc boolean true
d-i time/zone string Etc/UTC
d-i clock-setup/ntp boolean false
d-i apt-setup/use_mirror boolean false
d-i grub-installer/only_debian boolean true
'''
    (public / 'single.cfg').write_text(common + '''d-i partman-auto/disk string /dev/vda
d-i partman-auto/method string regular
d-i grub-installer/bootdev string /dev/vda
''')
    (public / 'mirror.cfg').write_text(common)
