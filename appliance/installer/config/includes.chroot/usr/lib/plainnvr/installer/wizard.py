#!/usr/bin/python3
"""Local live-USB wizard; Debian Installer performs the installation."""
import json
import os
import subprocess
import sys
import threading
from pathlib import Path

import gi
gi.require_version('Gtk', '3.0')
from gi.repository import GdkPixbuf, GLib, Gtk
import plan
sys.path.insert(0, '/usr/lib/plainnvr/support')
import recovery
from diagnostics import redact

sys.path.insert(0, '/opt/plainnvr/current')
from app.auth import password_hash, validate_password, validate_username


class Wizard(Gtk.Window):
    def __init__(self):
        super().__init__(title='Install PlainNVR OS')
        icon = '/opt/plainnvr/current/static/plainnvr-icon.png'
        self.set_icon_from_file(icon)
        screen = self.get_screen()
        self.set_default_size(min(860, screen.get_width() - 40), min(680, screen.get_height() - 60))
        self.set_position(Gtk.WindowPosition.CENTER)
        self.connect('delete-event', lambda *_: True)
        self.page = 0
        self.settings = {}
        self.selected = []
        self.disk_buttons = []
        self.busy = False
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14, margin=24)
        self.add(outer)
        title = Gtk.Label(xalign=0)
        title.set_markup('<span size="xx-large" weight="bold">PlainNVR OS</span>')
        branding = Gtk.Box(spacing=16)
        branding.pack_start(Gtk.Image.new_from_pixbuf(
            GdkPixbuf.Pixbuf.new_from_file_at_scale(icon, 64, 64, True)), False, False, 0)
        branding.pack_start(title, False, False, 0)
        outer.pack_start(branding, False, False, 0)
        self.steps = Gtk.Label(xalign=0)
        outer.pack_start(self.steps, False, False, 0)
        self.body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.add(self.body)
        outer.pack_start(scroll, True, True, 0)
        self.error = Gtk.Label(xalign=0, wrap=True, selectable=True)
        outer.pack_start(self.error, False, False, 0)
        row = Gtk.Box(spacing=10)
        diagnostics = Gtk.Button(label='Diagnostics')
        diagnostics.connect('clicked', self.diagnostics)
        row.pack_start(diagnostics, False, False, 0)
        self.recover = Gtk.Button(label='Recover existing installation')
        self.recover.connect('clicked', lambda *_: recovery.show(self) if not self.busy else None)
        row.pack_start(self.recover, False, False, 0)
        self.back = Gtk.Button(label='Back')
        self.back.connect('clicked', self.previous)
        self.next = Gtk.Button(label='Continue')
        self.next.connect('clicked', self.advance)
        row.pack_end(self.next, False, False, 0)
        row.pack_end(self.back, False, False, 0)
        outer.pack_start(row, False, False, 0)
        self.render()

    def label(self, text):
        label = Gtk.Label(label=text, xalign=0, wrap=True, selectable=True)
        self.body.pack_start(label, False, False, 0)
        return label

    def combo(self, title, values, selected):
        self.label(title)
        widget = Gtk.ComboBoxText()
        for value in values:
            widget.append(value, value)
        widget.set_active_id(selected)
        self.body.pack_start(widget, False, False, 0)
        return widget

    def entry(self, title, secret=False):
        self.label(title)
        widget = Gtk.Entry()
        widget.set_visibility(not secret)
        self.body.pack_start(widget, False, False, 0)
        return widget

    def render(self):
        for child in self.body.get_children():
            self.body.remove(child)
        self.error.set_text('')
        self.steps.set_text('Locale  →  Prepare disks  →  Install drives  →  Administrator  →  Review')
        self.back.set_sensitive(self.page > 0 and self.page < 5)
        self.recover.set_sensitive(not self.busy and self.page < 5)
        self.next.set_sensitive(True)
        self.next.set_label('Continue')
        if self.page == 0:
            self.label('Choose the language/region, keyboard and timezone for this appliance.')
            locales = [line.split()[0] for line in Path('/usr/share/i18n/SUPPORTED').read_text().splitlines() if 'UTF-8' in line]
            self.locale = self.combo('Language / region', locales, self.settings.get('locale', 'en_US.UTF-8'))
            self.keyboard = self.combo('Keyboard layout', ['us', 'gb', 'de', 'fr', 'es', 'it', 'pt', 'br', 'ca', 'be', 'nl', 'se', 'no', 'dk', 'fi', 'pl', 'cz', 'ru', 'ua', 'jp', 'kr', 'tr', 'ch'], self.settings.get('keyboard', 'us'))
            zones = ['UTC'] + sorted(line.split('\t')[2] for line in Path('/usr/share/zoneinfo/zone.tab').read_text().splitlines() if line and not line.startswith('#'))
            self.zone = self.combo('Timezone', zones, self.settings.get('timezone', 'America/New_York'))
        elif self.page == 1:
            self.label('Prepare disks with GParted')
            self.label('GParted opens in this live session. Close its window to return here; no reboot is needed. You may leave disks unchanged.')
            self.label('The OS installation will erase each whole drive selected in the next step. Use GParted to inspect those drives or prepare separate recording drives. ZFS recording pools are configured after installation.')
            button = Gtk.Button(label='Open GParted')
            button.connect('clicked', self.gparted)
            self.body.pack_start(button, False, False, 0)
        elif self.page == 2:
            self.label('Choose the drive(s) that will hold PlainNVR OS and its persistent data.')
            self.mirror = Gtk.CheckButton(label='Two mirrored boot drives (RAID1)')
            self.mirror.set_active(self.settings.get('mirror', False))
            self.body.pack_start(self.mirror, False, False, 0)
            self.disk_buttons = []
            for disk in plan.inventory():
                label = f'{disk["name"]}  ·  {int(disk["size"])/1e9:.1f} GB  ·  {disk.get("model") or "Drive"}  ·  {disk.get("serial") or "No serial reported"}'
                button = Gtk.CheckButton(label=label)
                button.set_sensitive(not disk['blocked'])
                self.body.pack_start(button, False, False, 0)
                if disk['blocked']:
                    self.label('    ' + disk['blocked'])
                self.disk_buttons.append((button, disk))
            refresh = Gtk.Button(label='Refresh drives')
            refresh.connect('clicked', lambda *_: self.render())
            self.body.pack_start(refresh, False, False, 0)
        elif self.page == 3:
            self.label('PlainNVR administrator')
            self.label('Create the application administrator now, or complete account and storage setup from another computer after installation. The local display will show a one-time setup code and web address.')
            self.defer = Gtk.CheckButton(label='Set up later in the web UI')
            self.defer.set_active(self.settings.get('defer_admin', False))
            self.body.pack_start(self.defer, False, False, 0)
            self.username = self.entry('Username')
            self.username.set_text('admin')
            self.password = self.entry('Password (at least 12 characters)', True)
            self.confirm = self.entry('Confirm password', True)
            self.defer.connect('toggled', lambda *_: [w.set_sensitive(not self.defer.get_active()) for w in (self.username, self.password, self.confirm)])
            self.defer.emit('toggled')
        elif self.page == 4:
            self.label('Review installation')
            self.label(f'{self.settings["locale"]} · Keyboard {self.settings["keyboard"]} · {self.settings["timezone"]}')
            self.label('Mirrored system and data (RAID1)' if self.settings['mirror'] else 'Single system drive')
            for disk in self.selected:
                self.label(f'ERASE: {disk["name"]} · {int(disk["size"])/1e9:.1f} GB · {disk.get("model") or "Drive"} · {disk.get("serial") or ""}')
            self.label('Administrator: ' + (self.settings['admin']['username'] if self.settings.get('admin') else 'Create later using the one-time setup code'))
            self.label('Two 32 GB OS slots for updates and rollback, plus a 1 GB boot partition. Remaining space holds shared settings and recordings. Minimum drive size: 80 GB; 128 GB or larger recommended.')
            self.label('All partitions and data on these selected drives will be erased. Other drives are not installation targets. Changes already applied in GParted remain applied.')
            self.erase = self.entry('Type ERASE to confirm the selected drives')
            self.next.set_label('Install PlainNVR OS')
        self.show_all()

    def previous(self, *_):
        if not self.busy:
            self.page -= 1
            self.render()

    def advance(self, *_):
        try:
            if self.page == 0:
                self.settings.update(locale=self.locale.get_active_id(), keyboard=self.keyboard.get_active_id(), timezone=self.zone.get_active_id())
                subprocess.run(['setxkbmap', self.settings['keyboard']], check=True)
            elif self.page == 2:
                self.selected = [disk for button, disk in self.disk_buttons if button.get_active()]
                self.settings['mirror'] = self.mirror.get_active()
                plan.validate_disks(self.selected, plan.inventory(), self.settings['mirror'])
            elif self.page == 3:
                self.settings['defer_admin'] = self.defer.get_active()
                self.settings['admin'] = None
                if not self.defer.get_active():
                    if self.password.get_text() != self.confirm.get_text():
                        raise ValueError('Passwords do not match.')
                    self.settings['admin'] = {'username': validate_username(self.username.get_text()), 'hash': password_hash(validate_password(self.password.get_text()))}
                self.password.set_text('')
                self.confirm.set_text('')
            elif self.page == 4:
                if self.erase.get_text() != 'ERASE':
                    raise ValueError('Type ERASE to confirm the selected drives.')
                plan.prepare(self.settings, self.selected, self.settings['mirror'])
                self.install()
                return
            self.page += 1
            self.render()
            if self.page == 1:
                self.gparted()
        except (ValueError, OSError, subprocess.SubprocessError) as exc:
            self.error.set_text(str(exc))

    def gparted(self, *_):
        if self.busy:
            return
        self.busy = True
        self.next.set_sensitive(False)
        self.back.set_sensitive(False)
        self.error.set_text('Close GParted to continue installation.')
        def worker():
            result = subprocess.run(['/usr/sbin/gparted'], capture_output=True, text=True)
            def done():
                self.busy = False
                self.render()
                if result.returncode:
                    self.error.set_text('GParted could not start. ' + result.stderr[-700:])
            GLib.idle_add(done)
        threading.Thread(target=worker, daemon=True).start()

    def install(self):
        self.busy = True
        self.page = 5
        self.render()
        self.steps.set_text('Starting installation')
        self.next.set_sensitive(False)
        self.label('Preparing the installation engine. Its progress window will open here shortly. Keep this computer powered on.')
        spinner = Gtk.Spinner()
        spinner.start()
        self.body.pack_start(spinner, False, False, 0)
        self.show_all()
        def worker():
            with open('/run/plainnvr-install/installer.log', 'w') as log:
                result = subprocess.run([str(plan.HERE / 'launch')], stdout=log, stderr=subprocess.STDOUT)
            GLib.idle_add(self.finished, result.returncode)
        threading.Thread(target=worker, daemon=True).start()

    def finished(self, code):
        self.busy = False
        self.page = 5
        self.render()
        self.steps.set_text('Installation finished' if code == 0 and (plan.STATE / 'success').exists() else 'Installation did not complete')
        self.next.set_sensitive(False)
        if code == 0 and (plan.STATE / 'success').exists():
            self.label('Remove the USB after reboot starts. PlainNVR will show the storage setup wizard and the address for completing setup from another computer.')
            button = Gtk.Button(label='Reboot into PlainNVR OS')
            button.connect('clicked', lambda *_: subprocess.Popen(['systemctl', 'reboot']))
            self.body.pack_start(button, False, False, 0)
        else:
            self.label('Open Diagnostics for the installer log. The selected drives may have been changed. Reboot this USB before retrying installation.')
        self.show_all()

    def diagnostics(self, *_):
        commands = [['uname', '-a'], ['xinput', 'list'], ['lsusb'], ['journalctl', '-b', '-n', '120', '--no-pager']]
        text = ''
        for command in commands:
            try:
                text += '\n$ ' + ' '.join(command) + '\n' + subprocess.run(command, capture_output=True, text=True, timeout=8).stdout
            except (OSError, subprocess.SubprocessError) as exc:
                text += str(exc)
        for path in (Path('/var/log/Xorg.0.log'), plan.STATE / 'installer.log', plan.STATE / 'debian-installer.log'):
            if path.exists():
                text += '\n' + str(path) + '\n' + path.read_text(errors='replace')[-200000:]
        text = redact(text)
        Path('/run/plainnvr-installer-diagnostics.txt').write_text(text)
        dialog = Gtk.Dialog(title='Installer diagnostics', transient_for=self)
        dialog.set_default_size(820, 560)
        dialog.add_button('Close', Gtk.ResponseType.CLOSE)
        dialog.add_button('Save log dump…', 1)
        view = Gtk.TextView(editable=False, monospace=True)
        view.get_buffer().set_text('Saved to /run/plainnvr-installer-diagnostics.txt\n' + text)
        scroll = Gtk.ScrolledWindow()
        scroll.add(view)
        dialog.get_content_area().pack_start(scroll, True, True, 0)
        dialog.show_all()
        while dialog.run() == 1:
            recovery.save_dialog(dialog, text)
        dialog.destroy()


if __name__ == '__main__':
    os.umask(0o077)
    Wizard()
    Gtk.main()
