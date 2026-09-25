#!/bin/sh
set -eu

export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
mkdir -p "$XDG_RUNTIME_DIR/plainnvr-chromium"
exec /usr/bin/cage -- /usr/bin/chromium \
    --ozone-platform=wayland \
    --kiosk \
    --no-first-run \
    --no-default-browser-check \
    --disable-session-crashed-bubble \
    --user-data-dir="$XDG_RUNTIME_DIR/plainnvr-chromium" \
    'file:///opt/plainnvr/current/kiosk/recovery.html'
