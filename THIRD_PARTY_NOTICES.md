# Third-Party Notices

PlainNVR includes or downloads third-party software. Those components remain
under their own licenses and are not relicensed under PlainNVR's GNU Affero
General Public License.

## go2rtc

PlainNVR's container build downloads and includes go2rtc.

Project: go2rtc  
Upstream: https://github.com/AlexxIT/go2rtc  
Version currently referenced by PlainNVR: 1.9.13  
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

## Container Base and System Packages

The PlainNVR container is built from a Python Debian-based image and installs
system packages including FFmpeg and CA certificates. Those packages and their
dependencies are distributed under their respective upstream licenses.

Relevant upstream projects include:

- Python: https://www.python.org/
- Debian: https://www.debian.org/
- FFmpeg: https://ffmpeg.org/

License and copyright files supplied by Debian packages should remain present
inside distributed container images. This notice does not replace any notices
or source-code obligations required by those packages' individual licenses.
