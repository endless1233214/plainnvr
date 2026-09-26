#!/bin/sh
set -eu

export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
mkdir -p "$XDG_RUNTIME_DIR/plainnvr-chromium"
url='file:///opt/plainnvr/current/kiosk/recovery.html'
if [ -f /etc/plainnvr/first-boot ] && [ ! -f /etc/plainnvr/setup-complete ]; then
    # Wait for the loopback setup service before Chromium opens its page.
    until /usr/bin/python3 -c 'import urllib.request; urllib.request.urlopen("http://127.0.0.1:8790/api/state", timeout=2)' >/dev/null 2>&1; do
        sleep 1
    done
    url='http://127.0.0.1:8790/'
fi
exec /usr/bin/cage -- /usr/bin/chromium \
    --ozone-platform=wayland \
    --kiosk \
    --no-first-run \
    --no-default-browser-check \
    --disable-session-crashed-bubble \
    --user-data-dir="$XDG_RUNTIME_DIR/plainnvr-chromium" \
    "$url"
