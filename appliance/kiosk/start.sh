#!/bin/sh
set -eu

export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
exec /usr/bin/cage -- /usr/bin/chromium \
    --ozone-platform=wayland \
    --kiosk \
    --no-first-run \
    --no-default-browser-check \
    --disable-session-crashed-bubble \
    --user-data-dir=/var/lib/plainnvr-kiosk/chromium \
    'file:///opt/plainnvr/current/kiosk/recovery.html'
