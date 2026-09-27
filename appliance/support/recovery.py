#!/usr/bin/python3
"""Inspect and repair the known A/B setup-permissions issue from a live USB."""
import contextlib
import json
import os
import re
import stat
import subprocess
import tempfile
from pathlib import Path
from diagnostics import command, redact, UNITS


def run(*args):
    result = subprocess.run(list(map(str, args)), capture_output=True, text=True, timeout=30)
    if result.returncode:
        raise ValueError((result.stderr or result.stdout)[-1000:])
    return result.stdout.strip()


def directory(root, relative):
    """Refuse symlinks before reading or changing a mounted installation."""
    path = Path(root)
    for part in Path(relative).parts:
        if part in ('..', '/'):
            raise ValueError('Invalid recovery path.')
        path /= part
        if not stat.S_ISDIR(path.lstat().st_mode):
            raise ValueError(f'Unexpected directory or symlink: {relative}')
    return path


def device(reference):
    if not isinstance(reference, str) or not re.fullmatch(r'/dev/disk/by-(?:partuuid|uuid)/[A-Za-z0-9-]+', reference):
        raise ValueError('Unrecognized installed device reference.')
    path = Path(reference).resolve(strict=True)
    if not stat.S_ISBLK(path.stat().st_mode):
        raise ValueError('Expected a block device.')
    return str(path)


@contextlib.contextmanager
def mounted(source, write=False):
    if run('lsblk', '-nro', 'MOUNTPOINTS', source):
        raise ValueError(f'{source} is already mounted. Close disk tools before recovery.')
    with tempfile.TemporaryDirectory(prefix='plainnvr-recovery-') as temporary:
        run('mount', '-t', 'ext4', '-o', 'rw,nosuid,nodev,noexec' if write else 'ro,noload,nosuid,nodev,noexec', source, temporary)
        try:
            yield Path(temporary)
        finally:
            run('umount', temporary)


def configuration(root, source):
    path = directory(root, 'system/config') / 'ab.json'
    if path.is_symlink() or path.stat().st_size > 16384:
        raise ValueError('Invalid A/B configuration file.')
    config = json.loads(path.read_text())
    if config.get('layout') != 1 or config.get('mirror') is not False or set(config.get('slots', {})) != {'A', 'B'}:
        raise ValueError('This repair supports a single-drive PlainNVR A/B installation.')
    disks = [device(config['data_device'])] + [device(config['slots'][slot]) for slot in ('A', 'B')]
    if disks[0] != str(Path(source).resolve()) or len(set(disks)) != 3:
        raise ValueError('Installed device mapping does not match this volume.')
    parents = set()
    for disk in disks:
        if run('blkid', '-s', 'TYPE', '-o', 'value', disk) != 'ext4':
            raise ValueError('Unexpected filesystem in A/B layout.')
        if run('lsblk', '-nro', 'TYPE', disk) != 'part':
            raise ValueError('Expected single-drive partitions.')
        parents.add(run('lsblk', '-nro', 'PKNAME', disk))
    if len(parents) != 1 or not next(iter(parents)):
        raise ValueError('The A/B partitions must belong to the same system disk.')
    return config


def verify_root(root, reference):
    directory(root, 'usr/lib/plainnvr/update')
    directory(root, 'etc/systemd/system')
    if (root / 'etc/plainnvr').readlink() != Path('/persist/system/config'):
        raise ValueError('Unexpected configuration link in installed system.')
    rows = [line.split() for line in (root / 'etc/fstab').read_text().splitlines() if line and not line.startswith('#')]
    if not any(len(row) >= 3 and row[:3] == [reference, '/', 'ext4'] for row in rows):
        raise ValueError('System slot does not match its fstab.')
    release = (directory(root, 'opt/plainnvr') / 'current').readlink()
    if not re.fullmatch(r'releases/[A-Za-z0-9.+_-]+', str(release)):
        raise ValueError('Unexpected application release link.')
    directory(root, 'opt/plainnvr/' + str(release) + '/kiosk')


def write_support(root, relative, content, mode=0o644):
    path = root / relative
    parent = root
    for part in Path(relative).parent.parts:
        candidate = parent / part
        if not candidate.exists() and not candidate.is_symlink():
            candidate.mkdir(mode=0o755)
            candidate.chmod(0o755)
        parent = directory(parent, part)
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise ValueError('Unexpected recovery file: ' + relative)
    with tempfile.NamedTemporaryFile(dir=parent, delete=False) as temporary:
        temporary.write(content)
        temporary.flush()
        os.fsync(temporary.fileno())
        os.fchmod(temporary.fileno(), mode)
        staged = Path(temporary.name)
    staged.replace(path)


def add_diagnostics(root):
    release = (root / 'opt/plainnvr/current').readlink()
    copies = [('/usr/lib/plainnvr/support/diagnostics.py', 'usr/lib/plainnvr/support/diagnostics.py', 0o644),
              ('/etc/systemd/system/plainnvr-diagnostics.service', 'etc/systemd/system/plainnvr-diagnostics.service', 0o644),
              ('/etc/systemd/system/plainnvr-diagnostics.timer', 'etc/systemd/system/plainnvr-diagnostics.timer', 0o644),
              ('/etc/systemd/journald.conf.d/plainnvr.conf', 'etc/systemd/journald.conf.d/plainnvr.conf', 0o644)]
    for name, mode in [('start.sh', 0o755), ('recovery.html', 0o644)]:
        copies.append(('/opt/plainnvr/current/kiosk/' + name, 'opt/plainnvr/' + str(release) + '/kiosk/' + name, mode))
    for source, destination, mode in copies:
        write_support(root, destination, Path(source).read_bytes(), mode)
    write_support(root, 'etc/systemd/system/plainnvr-kiosk@tty1.service.d/ab.conf',
                  b'[Unit]\nAfter=plainnvr-ab-prepare.service\n')
    parent = directory(root, 'etc/systemd/system') / 'timers.target.wants'
    if not parent.exists():
        parent.mkdir(mode=0o755)
        parent.chmod(0o755)
    directory(root, 'etc/systemd/system/timers.target.wants')
    link = parent / 'plainnvr-diagnostics.timer'
    if link.is_symlink():
        if link.readlink() not in (Path('../plainnvr-diagnostics.timer'), Path('/etc/systemd/system/plainnvr-diagnostics.timer')):
            raise ValueError('Unexpected diagnostics timer link.')
    elif link.exists():
        raise ValueError('Unexpected diagnostics timer file.')
    else:
        link.symlink_to('../plainnvr-diagnostics.timer')


def inventory():
    tree = json.loads(run('lsblk', '-Jbpo', 'NAME,TYPE,FSTYPE,SIZE,MOUNTPOINTS'))
    found = []
    def walk(nodes):
        for node in nodes:
            if node['type'] == 'part' and node.get('fstype') == 'ext4' and not any(node.get('mountpoints') or []):
                try:
                    with mounted(node['name']) as root:
                        config = configuration(root, node['name'])
                    found.append({'device': node['name'], 'size': node['size'], 'config': config})
                except (OSError, ValueError, subprocess.SubprocessError):
                    pass
            walk(node.get('children', []))
    walk(tree['blockdevices'])
    return found


def inspect(item):
    source = item['device']
    lines = ['PlainNVR installed-system recovery report', command('lsblk', '-o', 'NAME,SIZE,FSTYPE,MOUNTPOINTS')]
    with mounted(source) as root:
        config = configuration(root, source)
        for relative in ('system', 'system/config', 'nvr'):
            info = directory(root, relative).stat()
            lines.append(f'{relative}: mode={info.st_mode & 0o7777:o} uid={info.st_uid} gid={info.st_gid}')
    for slot, ref in config['slots'].items():
        with mounted(device(ref)) as root:
            verify_root(root, ref)
            lines.append('\nSystem slot ' + slot)
            logbase = directory(root, 'var/log')
            logroot = logbase / 'journal'
            if logroot.is_dir() and not logroot.is_symlink():
                for journal in logroot.iterdir():
                    if journal.is_dir() and not journal.is_symlink():
                        args = ['journalctl', '--directory', str(journal), '-n', '200', '--no-pager', '-o', 'short-iso']
                        for unit in UNITS:
                            args += ['-u', unit]
                        lines.append(command(*args))
            else:
                lines.append('No persistent journal in this build; prior volatile boot logs cannot be recovered after power-off.')
            logfile = directory(root, 'var/log/installer') / 'syslog' if (logbase / 'installer').exists() else logbase / 'missing-installer-log'
            if logfile.is_file() and not logfile.is_symlink():
                with logfile.open('rb') as stream:
                    stream.seek(max(0, logfile.stat().st_size - 160000))
                    lines.append(redact(stream.read().decode(errors='replace')))
    return '\n'.join(lines)


def repair(item):
    if os.geteuid() != 0 or 'boot=live' not in Path('/proc/cmdline').read_text().split():
        raise ValueError('Run this repair from the PlainNVR live USB.')
    with mounted(item['device']) as root:
        config = configuration(root, item['device'])
    # Validate both system slots read-only before any changes are made.
    for ref in config['slots'].values():
        with mounted(device(ref)) as root:
            verify_root(root, ref)
    with mounted(item['device'], write=True) as root:
        if configuration(root, item['device']) != config:
            raise ValueError('Disk configuration changed. Inspect it again.')
        for relative, mode in [('', 0o711), ('system', 0o711), ('system/config', 0o755)]:
            path = directory(root, relative)
            os.chown(path, 0, 0)
            path.chmod(mode)
    for ref in config['slots'].values():
        with mounted(device(ref), write=True) as root:
            verify_root(root, ref)
            for relative, mode in [('', 0o755), ('etc', 0o755), ('persist', 0o711)]:
                path = directory(root, relative)
                os.chown(path, 0, 0)
                path.chmod(mode)
            add_diagnostics(root)
    os.sync()
    return 'Startup access repaired and local diagnostics added to both OS slots. Reboot and remove the USB. Recordings and account data were preserved.'


def show(parent):
    import gi
    gi.require_version('Gtk', '3.0')
    from gi.repository import Gtk
    dialog = Gtk.Dialog(title='Recover existing PlainNVR installation', transient_for=parent, modal=True)
    dialog.set_default_size(820, 560)
    dialog.add_button('Close', Gtk.ResponseType.CLOSE)
    dialog.add_button('Save log dump…', 1)
    dialog.add_button('Repair startup + add diagnostics', 2)
    dialog.add_button('Reboot (remove USB)', 3)
    dialog.set_response_sensitive(3, False)
    content = dialog.get_content_area()
    select = Gtk.ComboBoxText()
    items = inventory()
    for index, item in enumerate(items):
        select.append(str(index), f"{item['device']} · {int(item['size']) / 1e9:.1f} GB shared data")
    content.pack_start(select, False, False, 6)
    view = Gtk.TextView(editable=False, monospace=True)
    scroll = Gtk.ScrolledWindow()
    scroll.add(view)
    content.pack_start(scroll, True, True, 0)
    state = {'text': 'No eligible single-drive A/B installation found. No changes were made.'}
    def refresh(*_):
        try:
            state['text'] = inspect(items[select.get_active()])
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            state['text'] = 'Inspection failed: ' + str(exc)
        view.get_buffer().set_text(state['text'])
    select.connect('changed', refresh)
    if items:
        select.set_active(0)
    else:
        view.get_buffer().set_text(state['text'])
    dialog.set_response_sensitive(1, bool(items))
    dialog.set_response_sensitive(2, bool(items))
    dialog.show_all()
    while True:
        response = dialog.run()
        if response == 3:
            subprocess.Popen(['systemctl', 'reboot'])
            break
        if response not in (1, 2):
            break
        if response == 1:
            save_dialog(dialog, state['text'])
        else:
            confirmation = Gtk.MessageDialog(transient_for=dialog, modal=True, message_type=Gtk.MessageType.QUESTION,
                buttons=Gtk.ButtonsType.OK_CANCEL, text='Repair startup on ' + items[select.get_active()]['device'] + '?')
            confirmation.format_secondary_text('This corrects directory permissions and adds local startup diagnostics with bounded persistent logs to both OS slots. It does not format partitions or change recordings or account data.')
            accepted = confirmation.run() == Gtk.ResponseType.OK
            confirmation.destroy()
            if accepted:
                try:
                    state['text'] += '\n\n' + repair(items[select.get_active()])
                    dialog.set_response_sensitive(3, True)
                except (OSError, ValueError, subprocess.SubprocessError) as exc:
                    state['text'] += '\n\nRepair stopped: ' + str(exc)
                view.get_buffer().set_text(state['text'])
    dialog.destroy()


def save_dialog(parent, text):
    from gi.repository import Gtk
    chooser = Gtk.FileChooserDialog(title='Save diagnostic log to a mounted USB drive', transient_for=parent,
        action=Gtk.FileChooserAction.SAVE)
    chooser.add_buttons('Cancel', Gtk.ResponseType.CANCEL, 'Save', Gtk.ResponseType.OK)
    chooser.set_current_name('plainnvr-recovery.txt')
    chooser.set_do_overwrite_confirmation(True)
    if chooser.run() == Gtk.ResponseType.OK:
        try:
            destination = Path(chooser.get_filename())
            if destination.is_symlink():
                raise ValueError('Choose a regular file, not a symbolic link.')
            destination.write_text(text)
        except (OSError, ValueError) as exc:
            error = Gtk.MessageDialog(transient_for=chooser, modal=True, message_type=Gtk.MessageType.ERROR,
                                      buttons=Gtk.ButtonsType.CLOSE, text='Could not save the log dump')
            error.format_secondary_text(str(exc))
            error.run()
            error.destroy()
    chooser.destroy()
