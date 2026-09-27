#!/bin/bash
set -euo pipefail
# Use the clean factory root from build-iso.sh, never an installed appliance.
if [ "$#" != 4 ]; then
  echo "Usage: $0 factory-root signing-cert signing-key new-output-directory" >&2
  exit 1
fi
root=$(realpath -e "$1")
cert=$(realpath -e "$2")
key=$(realpath -e "$3")
out=$(realpath -m "$4")
test ! -e "$out"
test -f "$root/usr/lib/plainnvr/update/VERSION"
test ! -e "$root/etc/plainnvr/setup-complete"
test ! -e "$root/etc/plainnvr/runtime.env"
test ! -e "$root/etc/plainnvr/ab.json"
test ! -e "$root/etc/plainnvr/authorized_keys"
test ! -e "$root/etc/plainnvr/smb.credentials"
test ! -e "$root/var/lib/plainnvr/nvr.sqlite3"
test -z "$(find "$root/etc/ssh" -name 'ssh_host_*key' -print -quit)"
test ! -s "$root/etc/machine-id"
cmp "$cert" "$root/usr/lib/plainnvr/update/release.pem"
version=$(cat "$root/usr/lib/plainnvr/update/VERSION")
[[ "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]
mkdir -p "$out/content"
cp "$root/usr/lib/plainnvr/update/"{hook,common,slots}.py "$out/content/"
chmod 755 "$out/content/hook.py"
tar --numeric-owner --acls --xattrs --one-file-system -C "$root" \
  --exclude='./dev/*' --exclude='./proc/*' --exclude='./sys/*' --exclude='./run/*' \
  --exclude='./tmp/*' --exclude='./var/tmp/*' --exclude='./persist/*' \
  --exclude='./var/lib/plainnvr/*' --exclude='./var/lib/plainnvr-setup/*' \
  --exclude='./var/lib/plainnvr-control/*' --exclude='./var/log/*' \
  --exclude='./var/cache/apt/archives/*' --exclude='./var/lib/apt/lists/*' \
  -czf "$out/content/rootfs.tar.gz" .
cat > "$out/content/manifest.raucm" <<EOF
[update]
compatible=plainnvr-os-amd64-ab-v1
version=$version
description=PlainNVR OS $version
[bundle]
format=verity
[hooks]
filename=hook.py
hooks=install-check
[image.rootfs]
filename=rootfs.tar.gz
hooks=post-install
[meta.plainnvr]
state-schema=1
EOF
rauc bundle --cert="$cert" --key="$key" --signing-keyring="$cert" \
  "$out/content" "$out/plainnvr-os-$version-amd64.raucb"
rauc --keyring="$cert" info --output-format=json "$out/plainnvr-os-$version-amd64.raucb" > "$out/bundle-info.json"
(cd "$out"; sha256sum "plainnvr-os-$version-amd64.raucb" > SHA256SUMS)
