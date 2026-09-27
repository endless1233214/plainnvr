#!/usr/bin/python3
"""Signed RAUC bundle hook: compatibility gate and inactive-root preparation."""
import os
import sys
from pathlib import Path
from common import configuration, verify_slots, current, run, load, save, STATE
from slots import copy_machine, configure_root, refresh_boot


def hook(action):
    config = configuration()
    active = current()
    if action == 'install-check':
        verify_slots(config)
        if os.environ.get('RAUC_MF_COMPATIBLE') != 'plainnvr-os-amd64-ab-v1':
            raise RuntimeError('This bundle targets a different appliance layout.')
        # Schema 1 releases must preserve database/config backward compatibility.
        if os.environ.get('RAUC_META_PLAINNVR_STATE_SCHEMA') != '1':
            raise RuntimeError('The update requires an unsupported configuration migration.')
        return
    if action != 'slot-post-install': raise RuntimeError('Unexpected update hook.')
    slot = os.environ['RAUC_SLOT_BOOTNAME']
    if slot not in ('A', 'B') or slot == active:
        raise RuntimeError('Refusing to prepare the active system slot.')
    root = Path(os.environ['RAUC_SLOT_MOUNT_POINT'])
    if not root.is_dir() or not str(root).startswith('/run/'):
        raise RuntimeError('Invalid RAUC slot mount.')
    source = Path(run('findmnt', '-nro', 'SOURCE', '--mountpoint', root)).resolve()
    if source != Path(config['slots'][slot]).resolve(): raise RuntimeError('Unexpected update target.')
    copy_machine(root)
    configure_root(root, config, slot, Path('/etc/fstab').read_text())
    # Build an initramfs with this machine's RAID metadata and the NEW kernel.
    for name in ('dev', 'proc', 'sys'):
        run('mount', '--rbind', '/' + name, root / name)
        run('mount', '--make-rslave', root / name)
    try:
        run('chroot', root, 'update-initramfs', '-u', '-k', 'all', timeout=600)
    finally:
        for name in ('sys', 'proc', 'dev'): run('umount', '-R', root / name)
    refresh_boot(config, root, slot)
    versions = load(STATE / 'slots.json', {})
    versions[slot] = {'version': (root / 'usr/lib/plainnvr/update/VERSION').read_text().strip(), 'healthy': False}
    save(STATE / 'slots.json', versions)


if __name__ == '__main__':
    try: hook(sys.argv[1])
    except Exception as exc:
        print(str(exc), file=sys.stderr); sys.exit(1)
