#!/bin/sh
set -eu

# Build on Debian 13 amd64. This produces native binaries, not a container.
repo_dir=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
version=$(cat "$repo_dir/VERSION")
case "$version" in
    *[!0-9A-Za-z.+~-]*|'') echo "Invalid VERSION" >&2; exit 1 ;;
esac
if [ "$(uname -s)" != Linux ] || [ "$(uname -m)" != x86_64 ]; then
    echo "Build on Debian amd64." >&2
    exit 1
fi
if ! command -v dpkg-query >/dev/null || ! grep -q '^VERSION_CODENAME=trixie$' /etc/os-release; then
    echo "Build on Debian 13 (trixie)." >&2
    exit 1
fi
for tool in curl sha256sum tar patch go make pkg-config gcc nasm; do
    command -v "$tool" >/dev/null || { echo "Missing build tool: $tool" >&2; exit 1; }
done

output_dir=${1:-"$repo_dir/appliance/out/plainnvr-$version-amd64"}
case "$output_dir" in
    /*) ;;
    *) output_dir="$(pwd)/$output_dir" ;;
esac
if [ -e "$output_dir" ]; then
    echo "Output already exists: $output_dir" >&2
    exit 1
fi
mkdir -p "$(dirname "$output_dir")"
work_dir=$(mktemp -d)
trap 'rm -rf "$work_dir"' EXIT HUP INT TERM
stage="$work_dir/stage"
release="$stage/opt/plainnvr/current"
mkdir -p "$release/bin" "$release/ffmpeg" "$release/app" "$release/static"

curl --fail --location --silent --show-error \
    https://codeload.github.com/AlexxIT/go2rtc/tar.gz/refs/tags/v1.9.14 \
    -o "$work_dir/go2rtc.tar.gz"
printf '%s  %s\n' \
    e3d59e553dfd0085889a2956281cfc0fd78bb7b4d6269d1c90c217d2ffcf2c7b \
    "$work_dir/go2rtc.tar.gz" | sha256sum -c -
mkdir "$work_dir/go2rtc"
tar -xzf "$work_dir/go2rtc.tar.gz" -C "$work_dir/go2rtc" --strip-components=1
cp "$repo_dir/build/go2rtc/go.mod" "$repo_dir/build/go2rtc/go.sum" "$work_dir/go2rtc/"
(
    cd "$work_dir/go2rtc"
    export GOTOOLCHAIN=go1.27.1
    go mod download
    go mod verify
    CGO_ENABLED=0 go list -deps . > "$work_dir/go2rtc-deps.txt"
    if grep -q '^golang.org/x/crypto/openpgp$' "$work_dir/go2rtc-deps.txt"; then
        echo "Unexpected OpenPGP dependency" >&2
        exit 1
    fi
    CGO_ENABLED=0 go build -mod=readonly -trimpath -o "$release/bin/go2rtc" .
)

curl --fail --location --silent --show-error \
    https://ffmpeg.org/releases/ffmpeg-9.0.2.tar.xz \
    -o "$work_dir/ffmpeg.tar.xz"
printf '%s  %s\n' \
    8c3850283eb25fa026482078a04051e0be17347b09ef81a0849bec15a96e002e \
    "$work_dir/ffmpeg.tar.xz" | sha256sum -c -
mkdir "$work_dir/ffmpeg"
tar -xJf "$work_dir/ffmpeg.tar.xz" -C "$work_dir/ffmpeg" --strip-components=1
(
    cd "$work_dir/ffmpeg"
    patch -p1 < "$repo_dir/build/ffmpeg/mov-seek-bounds.patch"
    sh "$repo_dir/build/ffmpeg/test-mov-seek-bounds.sh"
    FFMPEG_PREFIX=/opt/plainnvr/current/ffmpeg \
        FFMPEG_DESTDIR="$stage" \
        sh "$repo_dir/build/ffmpeg/configure.sh"
)

cp -R "$repo_dir/app/." "$release/app/"
cp -R "$repo_dir/static/." "$release/static/"
cp -R "$repo_dir/appliance/kiosk" "$release/kiosk"
printf '%s\n' "$version" > "$release/VERSION"
mkdir -p "$output_dir"
cp -R "$release/." "$output_dir/"
printf 'Native PlainNVR runtime: %s\n' "$output_dir"
