#!/usr/bin/python3
"""RAUC custom boot backend, synchronizing GRUB state on the installed ESPs."""
import sys
from common import configuration, current, esp_mounts, read_env, write_env


def operation(args):
    config = configuration()
    command = args[0]
    if command == 'get-current':
        print(current()); return
    with esp_mounts(config, require_all=command == 'set-primary') as mounts:
        env = read_env(mounts[0])
        if command == 'get-primary':
            print(env.get('ORDER', 'A B').split()[0]); return
        slot = args[1]
        if slot not in ('A', 'B'): raise ValueError('Unknown boot slot.')
        if command == 'get-state':
            print('good' if env.get(slot + '_OK') == '1' else 'bad'); return
        if command == 'set-state' and args[2] in ('good', 'bad'):
            values = {slot + '_OK': '1' if args[2] == 'good' else '0', slot + '_TRY': '0'}
        elif command == 'set-primary':
            other = 'B' if slot == 'A' else 'A'
            values = {'ORDER': slot + ' ' + other, 'PENDING': slot, slot + '_OK': '1', slot + '_TRY': '0'}
        else:
            raise ValueError('Unknown boot operation.')
        for mount in mounts: write_env(mount, **values)


if __name__ == '__main__':
    try: operation(sys.argv[1:])
    except Exception as exc:
        print(str(exc), file=sys.stderr); sys.exit(1)
