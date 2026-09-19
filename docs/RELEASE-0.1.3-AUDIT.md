# PlainNVR 0.1.3 release audit

Reviewed September 19, 2026. This is a focused source review and dependency scan,
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

## Dependency inventory

| Component | Candidate | Assessment |
| --- | --- | --- |
| Python | 3.12.14, `python:3.12-slim` | Current security patch in supported 3.12 line; not latest feature line. No third-party Python application packages. |
| Debian | 13.7 image, repository packages refreshed at build | Current repository packages still have known advisories; see below. |
| FFmpeg | Debian 7:7.1.5-0+deb13u1 | Distribution-maintained version, not latest upstream major. |
| go2rtc | 1.9.14, formerly 1.9.13 | Latest published release checked via GitHub; fixes UDP listener startup, but transitive advisories remain. Release binary checksums are verified. |
| Browser player | go2rtc 1.9.14 JavaScript | Updated from upstream, retaining the bounded MSE recovery patch. |
| iOS and macOS WebRTC | stasel/WebRTC 153.0.0 | Both local Package.resolved files match latest published release. Binary/transitive client audit not completed; Apple framework security also depends on OS updates. |
| pip | Removed | Unneeded at runtime; its installed distribution had six fixable advisories. |
| GitHub Actions | Latest published checkout/setup-node/login/build-push, pinned by commit | PRs test/build without publishing. Publishing is restricted to main after successful tests. |

Upstream references:
- https://github.com/AlexxIT/go2rtc/releases/tag/v1.9.14
- https://github.com/stasel/WebRTC/releases/tag/153.0.0
- https://devguide.python.org/versions/

## Remaining dependency findings — release decision required

Trivy 0.74.0 scanned the freshly rebuilt Debian container. Before removing pip,
it reported 598 package/advisory occurrences (the same CVE appears against multiple
binary packages). Deduplicating CVE IDs gives 221: 1 critical, 42 high, 62 medium,
98 low and 18 unknown. Six fixable IDs belonged to unused pip; the other Debian
findings had no fixed version in the scanner's Debian 13 database at scan time.
Removing pip does not resolve the remaining Debian findings.

Examples checked against the Debian tracker:
- CVE-2026-6653: libxml2 use-after-free/denial of service, scanner critical;
  Debian labels it a minor issue with no security update planned for trixie.
  PlainNVR ONVIF uses Python ElementTree, not libxml2; FFmpeg's XML-related
  features remain a separate surface. This is not proof of unreachability.
  https://security-tracker.debian.org/tracker/CVE-2026-6653
- CVE-2026-86138: libxml2 integer overflow/heap overflow; Debian 13 affected.
  https://security-tracker.debian.org/tracker/CVE-2026-86138
- CVE-2026-64834: FFmpeg RTP/ASF CPU exhaustion; fix deferred in Debian 13.
  https://security-tracker.debian.org/tracker/CVE-2026-64834

A separate manifest scan of go2rtc v1.9.14 go.mod/go.sum reported 31 advisories:
17 high, 12 medium, 2 unknown. These are package-version matches, not confirmed
reachable vulnerabilities. Examples include Pion DTLS (CVE-2026-26014,
CVE-2026-54908), STUN (CVE-2026-54909), and older golang.org/x dependencies.
The container scan did not detect go2rtc's bundled Go modules, so its report alone
is insufficient. The manifest scan also does not establish the binary's Go runtime
patch level. Updating go2rtc's own release version does not fix all these findings.

Recommended next step before stable publication: test a maintained/patched go2rtc
build and evaluate a patched FFmpeg/base image, with reachable-code analysis and
recording/playback regression tests. Do not silently suppress the scanner findings.

## Verification and limits

- 44 Python regression tests and 5 JavaScript tests pass.
- Container builds on TrueNAS amd64, and source imports successfully as UID/GID 568.
- Actual sandbox rejects internal API access, encoded HLS traversal, foreign-origin
  login requests and non-object JSON. Authenticated HLS playlists work.
- RTSP connection to the container's non-loopback address is refused.
- Original catalog instance remains running separately; only sandbox is updated.
- Native playback, startup timing and 65-second frame delivery are checked with
  the existing Mac WebRTC harness: first frame 0.556 s, 979 frames counted
  through second 65, maximum inter-frame gap 0.151 s.
- No long soak, independent penetration test, multi-camera capacity test, or exhaustive
  client security review has been performed. Prior startup measurements are not
  glass-to-glass latency measurements.

All users are administrators. Direct HTTP remains cleartext; use HTTPS/VPN for
remote access. Restrict the data volume/backups and use trusted camera networks.
The built-in HTTP server, basic-auth streaming endpoints, proxy deployment policy,
and broader resource limits merit further hardening for public Internet service.
