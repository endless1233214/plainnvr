#!/usr/bin/env python3
"""Run a command on an already authenticated disposable VM serial console."""
import argparse
import secrets
import socket
import time

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('socket')
    parser.add_argument('command')
    args = parser.parse_args()
    marker = 'VM_DONE_' + secrets.token_hex(6)
    with socket.socket(socket.AF_UNIX) as connection:
        connection.settimeout(45)
        connection.connect(args.socket)
        # Pace input to avoid overrunning the emulated UART receive buffer.
        for byte in (args.command + "; printf '\\n%s\\n' " + marker + '\r').encode():
            connection.sendall(bytes([byte]))
            time.sleep(.003)
        output = b''
        while ('\r\n' + marker + '\r\n').encode() not in output:
            output += connection.recv(65536)
        print(output.decode(errors='replace'))
