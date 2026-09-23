#!/bin/sh
set -eu
mkdir -p /licenses/go2rtc
cp LICENSE /licenses/go2rtc/LICENSE
cp /usr/local/go/LICENSE /licenses/GO-LICENSE
# Include notices from the resolved modules, not only the top-level program.
go list -m -f '{{if .Dir}}{{.Path}} {{.Version}} {{.Dir}}{{end}}' all |
while read -r module version directory; do
  [ -n "$directory" ] || continue
  target="/licenses/$module@$version"
  mkdir -p "$target"
  find "$directory" -maxdepth 1 -type f \( -iname 'license*' -o -iname 'copying*' -o -iname 'notice*' \) -exec cp '{}' "$target/" \;
done
