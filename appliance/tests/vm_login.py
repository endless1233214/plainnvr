#!/usr/bin/env python3
"""Authenticate a disposable test VM console without printing credentials."""
import argparse
import socket
from pathlib import Path

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('socket')
    parser.add_argument('password_file')
    args = parser.parse_args()
    password = Path(args.password_file).read_text().strip().encode()
    with socket.socket(socket.AF_UNIX) as connection:
        connection.settimeout(20)
        connection.connect(args.socket)

        def expect(token):
            data = b''
            while token not in data:
                data += connection.recv(4096)
                if b'Login incorrect' in data:
                    raise RuntimeError('VM login failed')

        connection.sendall(b'vmtest\r')
        expect(b'Password:')
        connection.sendall(password + b'\r')
        expect(b'$ ')
        connection.sendall(b'sudo -i\r')
        expect(b'password for')
        connection.sendall(password + b'\r')
        expect(b'# ')
    print('Test console authenticated.')
