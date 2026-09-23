# Third-Party Notices

PlainNVR includes or downloads third-party software. Those components remain
under their own licenses and are not relicensed under PlainNVR's GNU Affero
General Public License.

## go2rtc

PlainNVR builds go2rtc 1.9.14 from checksum-verified source with updated
dependency locks in `build/go2rtc`. The exact module versions and checksums
are recorded there. Runtime notices are under `/usr/share/licenses/go2rtc`.

Project: go2rtc  
Upstream: https://github.com/AlexxIT/go2rtc  
Version currently referenced by PlainNVR: 1.9.14
License: MIT License

Copyright (c) 2022 Alexey Khit

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

## FFmpeg and runtime packages

FFmpeg 9.0.2 is built from https://ffmpeg.org/releases/ffmpeg-9.0.2.tar.xz
with the checksum in Dockerfile and the complete configure script in
`build/ffmpeg/configure.sh`. The bounds-check patch in
`build/ffmpeg/mov-seek-bounds.patch` follows Chromium issue 507090179
(CVE-2026-13858); it is the only source modification. This build
uses LGPL version 3 (OpenSSL enabled; GPL/nonfree components disabled).
The license and build configuration are included under
`/usr/share/licenses/ffmpeg` and `/usr/share/plainnvr` in the image.
Source and build scripts remain available at the linked upstream archive and
in this repository for rebuilding or relinking FFmpeg.

Python and Alpine packages remain under their upstream licenses:

- Python: https://www.python.org/
- Alpine: https://alpinelinux.org/
- FFmpeg: https://ffmpeg.org/

This notice does not replace the components' license or source obligations.
