#!/usr/bin/env python3
"""Small QMP console helper for disposable installer-validation VMs."""
import argparse
import json
import socket
import time


class Console:
    def __init__(self, path):
        self.socket = socket.socket(socket.AF_UNIX)
        self.socket.connect(path)
        self.stream = self.socket.makefile('rwb')
        self.stream.readline()
        self.command('qmp_capabilities')

    def command(self, name, arguments=None):
        self.stream.write(json.dumps({'execute': name, 'arguments': arguments or {}}).encode() + b'\n')
        self.stream.flush()
        while True:
            result = json.loads(self.stream.readline())
            if 'error' in result:
                raise RuntimeError(result['error'])
            if 'return' in result:
                return result['return']

    def key(self, key):
        self.command('human-monitor-command', {'command-line': 'sendkey ' + key + ' 30'})
        time.sleep(.05)

    def text(self, text):
        special = {' ': 'spc', '/': 'slash', '.': 'dot', '-': 'minus', '_': 'shift-minus',
                   ':': 'shift-semicolon', '=': 'equal', '+': 'shift-equal', ',': 'comma',
                   '\n': 'ret', '\t': 'tab', '?': 'shift-slash', ';': 'semicolon',
                   '"': 'shift-apostrophe', "'": 'apostrophe', '\\': 'backslash',
                   '|': 'shift-backslash', '>': 'shift-dot', '<': 'shift-comma',
                   '!': 'shift-1', '@': 'shift-2', '#': 'shift-3', '$': 'shift-4',
                   '%': 'shift-5', '^': 'shift-6', '&': 'shift-7', '*': 'shift-8',
                   '(': 'shift-9', ')': 'shift-0', '[': 'bracket_left', ']': 'bracket_right'}
        for char in text:
            key = special.get(char, ('shift-' + char.lower()) if char.isupper() else char)
            self.key(key)

    def click(self, x, y, width, height):
        # Launch the test VM with a USB tablet for absolute pointer input.
        if not (0 <= x < width and 0 <= y < height):
            raise ValueError('Click must be inside the captured screen.')
        self.command('input-send-event', {'events': [
            {'type': 'abs', 'data': {'axis': 'x', 'value': round(x * 32767 / (width - 1))}},
            {'type': 'abs', 'data': {'axis': 'y', 'value': round(y * 32767 / (height - 1))}},
            {'type': 'btn', 'data': {'down': True, 'button': 'left'}},
        ]})
        self.command('input-send-event', {'events': [
            {'type': 'btn', 'data': {'down': False, 'button': 'left'}},
        ]})


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('socket')
    sub = parser.add_subparsers(dest='action', required=True)
    sub.add_parser('status')
    sub.add_parser('shot').add_argument('path')
    sub.add_parser('text').add_argument('text')
    sub.add_parser('keys').add_argument('keys', nargs='+')
    sub.add_parser('click').add_argument('coordinates', type=int, nargs=4, metavar=('X', 'Y', 'WIDTH', 'HEIGHT'))
    args = parser.parse_args()
    console = Console(args.socket)
    if args.action == 'shot':
        console.command('screendump', {'filename': args.path, 'format': 'png'})
    elif args.action == 'text':
        console.text(args.text)
    elif args.action == 'keys':
        for key in args.keys:
            console.key(key)
    elif args.action == 'click':
        console.click(*args.coordinates)
    else:
        print(json.dumps(console.command('query-status')))
