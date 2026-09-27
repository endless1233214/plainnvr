#!/bin/sh
set -eu

export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
mkdir -p "$XDG_RUNTIME_DIR/plainnvr-chromium"
url='file:///opt/plainnvr/current/kiosk/recovery.html'
# The local page probes both services and remains usable when either fails.
# Do not gate recovery on reading configuration from the persistent volume.
exec /usr/bin/cage -- /usr/bin/chromium \
    --ozone-platform=wayland \
    --kiosk \
    --no-first-run \
    --no-default-browser-check \
    --disable-session-crashed-bubble \
    --user-data-dir="$XDG_RUNTIME_DIR/plainnvr-chromium" \
    "$url"
