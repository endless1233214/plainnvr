# PlainNVR 0.1.3 release audit

Reviewed September 22, 2026. This is a focused source review and dependency scan,
not a penetration test, exhaustive security audit, or bug-free certification.

## Application fixes

- The unauthenticated RTSP relay previously listened on all container interfaces.
  It now binds to localhost by default; external RTSP is an explicit trusted-network
  opt-in. WebRTC TCP/UDP remains reachable for authenticated viewers.
- The authenticated go2rtc proxy exposed arbitrary internal API GET endpoints and
  unrestricted source strings. It now permits only the playback WebSocket for a
  configured, enabled camera, with a browser origin check.
- HLS subpaths accepted arbitrary tails. Only the four upstream HLS routes are
  now forwarded, closing traversal into internal API routes.
- Public login/setup JSON parsing had no size limit or object/type validation.
  Bodies are limited to 1 MiB, malformed bodies return 400, foreign browser
  origins are rejected, and login/setup attempts have a bounded per-peer limit.
  Native clients may omit Origin. Slow request sockets time out after 30 seconds.
- First-user setup now checks for an existing administrator inside the same write
  transaction that creates the account, preventing concurrent setup races.
- Recorded-video suffix ranges were parsed incorrectly and unsatisfiable ranges
  could yield negative Content-Length. Suffix ranges work and invalid bounds return
  416. HEAD JSON errors no longer emit a body.
- Viewer recovery no longer resets the shared camera source or interrupts recording.
  Video packet progress drives relay health and stalled-source recovery. The browser
  watchdog keeps observing after startup; MSE overflow reconnects cleanly.
- HLS preserves upstream failure statuses, HEAD behavior and partial-content headers.

Additional hardening bounds concurrent HTTP handlers at 128, limits failed Basic
stream authentication attempts, rejects non-ASCII token guesses without exceptions,
validates FFprobe inputs at the execution boundary, and adds anti-framing headers.
New data files use a restrictive umask. The image defaults to UID/GID 568.

## Dependency inventory

| Component | Candidate | Assessment as of 2026-09-22 |
| --- | --- | --- |
| Python | 3.14.7, `python:3.14-alpine3.24` | Current supported feature line and image patch; no third-party Python application packages. |
| Alpine | 3.24.2 | Runtime packages refreshed at build; no OS package findings in the candidate scan. |
| FFmpeg | 9.0.2 plus MOV bounds patch | Source checksum and complete build recipe pinned; reviewed separately because Trivy does not discover this source-built C binary. |
| go2rtc | 1.9.14, built with Go 1.27.1 | Updated Pion and golang.org/x dependency locks; readable Go module metadata retained for scanning. |
| Browser player | go2rtc 1.9.14 JavaScript | Updated from upstream, retaining bounded MSE recovery. No npm runtime dependencies. |
| iOS and macOS WebRTC | stasel/WebRTC 153.0.0 | Both local Package.resolved files match the latest published release checked. Binary/transitive client audit is not exhaustive; Apple frameworks depend on OS updates. |
| pip | Removed | Not needed in the runtime. |
| GitHub Actions | Pinned release commits | Test and scan the container before publication; publish the exact saved image without rebuilding. |

Weekly Dependabot checks cover Docker, Go module locks and GitHub Actions. Pinned
FFmpeg/go2rtc source releases still require maintainers to check upstream releases
and advisories; the image scan alone is insufficient for FFmpeg.

References: [go2rtc release](https://github.com/AlexxIT/go2rtc/releases/tag/v1.9.14),
[WebRTC release](https://github.com/stasel/WebRTC/releases/tag/153.0.0),
[FFmpeg releases](https://ffmpeg.org/download.html),
[Python support](https://devguide.python.org/versions/).

## Findings and disposition

The first Debian-based candidate produced 598 package/advisory occurrences,
representing 221 distinct IDs (1 critical, 42 high, 62 medium, 98 low, 18 unknown).
Removing pip fixed six IDs but left distribution packages without available fixes.
The upstream go2rtc manifest separately produced 31 advisory matches. Those
results were release blockers, rather than accepted exceptions.

The candidate now uses a small Alpine runtime and source-built media components.
The Trivy 0.74.0 image scan reports zero OS findings. The Go binary scan has one raw
module-level match, GO-2026-5932, and zero after the narrowly scoped OpenVEX statement.
[That advisory](https://pkg.go.dev/vuln/GO-2026-5932) concerns the unmaintained
`golang.org/x/crypto/openpgp` package. It is absent from `go list -deps .` for this
executable. The Docker build fails if it appears; the compiled package list is
saved in the image. This is a code-absence determination, not an accepted
vulnerable package or a blanket severity exclusion. All other severities, including
unknown and unfixed advisories, fail the image scan.

FFmpeg is reviewed independently in [FFmpeg advisory dispositions](FFMPEG-SECURITY.md).
Its build retains camera transport, H.264/H.265 and common camera audio, MP4
recording, snapshots and night-mode sampling. Unneeded device, subtitle, game-codec,
XML/DASH and hardware-acceleration components are disabled. This is a deliberate
compatibility boundary: it is not a general-purpose FFmpeg distribution or arbitrary
transcoding service.

CVE-2026-13858 remains relevant to upstream FFmpeg 9.0.2. The local patch checks
negative and unequal-length sample indexes before MOV seeking. It follows the
[public Chromium report](https://issues.chromium.org/issues/507090179), and a build-time
ASan/UBSan regression compiles the actual patched function and exercises both
bounds. Other reviewed enabled-component issues are fixed in the pinned source.

## Verification and limits

- 53 Python regression tests and 5 JavaScript tests pass.
- The container builds on TrueNAS amd64 and imports as UID/GID 568.
- The go2rtc build runs its WebRTC/HLS/RTSP package tests and verifies module checksums.
- Actual sandbox HTTP checks reject internal API access, encoded HLS traversal,
  foreign-origin login requests and non-object JSON. Authenticated HLS works.
- Native playback on the final sandbox image delivered 944 frames through second
  65 with a 0.133-second maximum normal frame gap. Four on-demand startup samples
  ranged from 0.531 to 4.488 seconds while waiting for source/keyframe startup;
  three were 1.891 seconds or faster. These are startup measurements, not
  camera-to-display latency. An active recorder keeps the shared source warm.
- Camera color/grayscale JPEG snapshots and multiple MP4 recording segments with
  video and audio passed live sandbox smoke tests.
- A physical Tapo TCW61 discovered its Device, Media, Imaging, and Events services
  on port 2020, three media profiles, H.264/G.711 streams, and correctly reported
  no PTZ service. Main and secondary RTSP audio/video are probed independently.
- During an intentional sandbox redeploy, the native client reconnected and
  decoded a new first frame in 0.294 seconds after its retry; the expected outage
  produced a 16.387-second frame gap and playback remained live through second 65.
- RTSP defaults to loopback. The original catalog instance remains separate.
- No long soak, independent penetration test, multi-camera capacity test, or exhaustive
  client binary security review has been performed. No audit can establish zero
  unknown vulnerabilities or guarantee bug-free behavior.

All users are administrators. Direct HTTP remains cleartext; use HTTPS/VPN for
remote access. Restrict the data volume/backups and use trusted camera networks.
The HTTP connection cap is a bounded resource safeguard, not Internet-scale DoS
protection. Reverse-proxy limits and deployment configuration remain relevant.
