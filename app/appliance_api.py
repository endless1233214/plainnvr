"""Authenticated adapter to the optional local PlainNVR OS control service."""
import hashlib
import json
import socket
from pathlib import Path

SOCKET = '/run/plainnvr-control/control.sock'


def address(handler):
    """Only LAN URLs are public, so the attached login screen can display them."""
    if not Path(SOCKET).exists():
        handler.send_json({'available': False})
        return
    try:
        handler.send_json(request('addresses', {}, handler))
    except (ValueError, OSError):
        handler.send_json({'available': False})


def request(operation, payload, handler):
    message = {'operation': operation, 'payload': payload,
               'owner': hashlib.sha256(handler.session_id().encode()).hexdigest(),
               'username': handler.auth_user(),
               'local': handler.client_address[0] in ('127.0.0.1', '::1')}
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(200)
        client.connect(SOCKET)
        client.sendall(json.dumps(message).encode() + b'\n')
        with client.makefile('rb') as stream:
            raw = stream.readline(16 * 1024 * 1024)
    result = json.loads(raw)
    if 'error' in result:
        raise ValueError(result['error'])
    return result


def handle(handler, app, payload=None):
    if not Path(SOCKET).exists():
        handler.send_json({'available': False} if payload is None else {'error': 'Appliance controls are unavailable.'}, 200 if payload is None else 404)
        return
    try:
        if payload is None:
            result = request('status', {}, handler)
        else:
            if not isinstance(payload, dict):
                raise ValueError('Invalid appliance request.')
            operation = payload.pop('operation', '')
            if operation == 'unlock':
                if not app.login_limiter.allow(handler.client_address[0]):
                    handler.send_error_json(429, 'Wait before trying again.')
                    return
                if not app.authenticate_user(handler.auth_user(), payload.get('password', '')):
                    handler.send_error_json(403, 'Incorrect administrator password.')
                    return
                payload = {}
            result = request(operation, payload, handler)
        handler.send_json(result)
    except (ValueError, OSError) as exc:
        handler.send_error_json(400, str(exc) if isinstance(exc, ValueError) else 'The appliance control service did not respond.')
