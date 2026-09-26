# PlainNVR OS — native Debian x86-64 prototype handoff

## Current checkpoint — September 26, 2026

The sections below this checkpoint describe the original ARM-to-x86 handoff
and are retained as historical context. This checkpoint supersedes their
build/validation status and their statement that no installer exists.

The owner requested a bootable installer with administrator creation first on
the installed system's first boot, followed by storage/directory selection and
GParted. "Two boot drives" means **mirrored boot drives for redundancy**.
Work continues on `feature/plainnvr-os-native-prototype`; nothing is merged
to main. Existing unrelated macOS source changes must be preserved.

- Native go2rtc 1.9.14 and FFmpeg 9.0.2 were built and tested on Debian 13
  amd64. The runtime carries upstream sources, build configuration, licenses
  and dependency notices.
- The original VM passed two-camera H.264/AAC recording, live/playback UI,
  server/kiosk restarts, reboot, and missing-data-mount checks. A VirtualBox
  copy named **PlainNVR OS Prototype** is registered on the Windows host.
- `installer/build-iso.sh` builds a clean Debian live-build hybrid ISO with
  Debian Installer, native PlainNVR, GParted, mdadm and ZFS. Disk selection
  and destructive confirmation remain explicit.
- `setup/` implements the local first-boot wizard. It creates the ordinary
  PlainNVR admin account, then configures recording storage and directories.
  Setup listens only on loopback and stops after success. The normal NVR is
  gated until setup finishes; the kiosk then opens the normal login.
- Mirrored installation uses ext4 on two RAID1 arrays (system and default
  data). ZFS is for recording pools. New pools and imports require explicit
  selection and typed confirmation. Existing datasets are preserved.
- Initial installer validation passed UEFI single-drive installation,
  administrator/storage setup, GParted launch/return, ZFS mirror creation,
  recording and reboot, missing-pool refusal, and pool import preserving
  recordings. BIOS mirror installation booted into the wizard with each
  drive independently absent; default-storage setup also completed on the
  surviving second drive.
- Validation found and fixed the USB GParted service conflicting with normal
  startup, a multiline Debconf recipe, BIOS bootloader target handling,
  optional EFI shim handling, and the kiosk password-save prompt.
- Nine setup boundary/storage tests pass. UEFI mirror installation, first-boot
  setup with custom directories, and boot/login with each drive independently
  absent all passed. The final BIOS USB GParted menu entry is fixed as well.
- The development installer is at
  `C:\Users\Zack\Downloads\PlainNVR-OS\plainnvr-os-0.1.4-amd64.hybrid.iso`,
  with `SHA256SUMS`, package manifest and installation/validation notes.
  SHA-256: `f34575334237dc24ffc41a9ac446026d1f39158c307de19a3493d0db3c5a9855`.
  Consult `installer/VALIDATION.md` for test coverage and remaining release work.

Build/test work uses isolated QEMU overlays in WSL Ubuntu under
`/home/endless/plainnvr-os-vm`. The Debian build guest's SSH endpoint is
127.0.0.1:2224 **inside WSL** when running. Build/test guests are powered off
after validation. The original prototype and the production NVR
are separate. Do not bundle VM test credentials, SSH keys, configuration
databases, or recordings in the installer. NoVNC requires a VNC backend;
VirtualBox's RDP endpoint is not interchangeable with VNC.

Remaining release validation: physical-PC graphics and sustained recording
load, WebRTC ICE/TCP/UDP, retention, Docker regression, Secure Boot enrollment
and updates, and a production update/rollback mechanism. This is an appliance
development image. See `installer/README.md` for the build and installation
workflow. The original handoff follows for historical context.

---

## Objective and boundaries

Build a dedicated x86-64 PlainNVR appliance OS for an old PC. The eventual user
experience is: write an ISO to USB, install it, boot directly into the PlainNVR
interface on the attached monitor, and access the same NVR from other devices
on the LAN. The local UI should reuse the existing PlainNVR web frontend.

The owner chose **Debian 13 with PlainNVR running natively**, with no Docker
daemon or container runtime on the appliance. Docker/TrueNAS remains a separate
supported deployment target. Do not rework the existing backend to fit this
appliance, create a `codex` branch, or build a giant custom installer. First
prove native boot, recording, kiosk, LAN access, and reboot behavior in a VM,
then test on the old physical PC. Only after those work should this become a
reproducible bootable installer image. This is a prototype, not a release.

Priority order: preserve existing PlainNVR; reliable recording; reliable
startup, reboot and recovery; existing web UI; local kiosk UI; installation;
updates; polish. No automatic disk selection or formatting. No automatic
administrator login on the local display.

## Git checkpoint

- Repository: <https://github.com/endless1233214/plainnvr>
- Base `main` at the start of this work:
  `1963e0dbae1a75a0608ed5e5e9be3939ba9a6371` (PlainNVR 0.1.4).
- Existing feature branch:
  `feature/plainnvr-os-native-prototype`.
- Scaffold checkpoint before this handoff file:
  `affc9149725df5758268f8a034b70e4d52c70a94`.
- Continue on that existing feature branch. Fetch it from GitHub on the x86
  machine; do not make a new branch. Check its current head with
  `git rev-parse HEAD` after fetching, since this handoff file was added later.
- No PR has been opened and nothing has been merged to `main`.
- No TrueNAS application or server was modified for this appliance work.

## What the existing app already does

`app/server.py` is the composition root. It creates the data and recording
directories, initializes the SQLite database, starts go2rtc, starts the
recorder supervisor, and then starts its HTTP server. PlainNVR's own Python
process supervises go2rtc and per-camera FFmpeg recorders. It can already run
directly with Python; its Python imports are standard-library code rather than
a pip-managed application stack.

Camera streams go through go2rtc. FFmpeg records timestamped MP4 segments,
normally copying video and encoding audio to AAC. The frontend in `static/`
already contains Dashboard, Live View/wall, Cameras, Recordings, Events and
Settings. The normal HTTP/API port is 8787. WebRTC media uses port 8555 on TCP
and UDP. The go2rtc API on 1984 and RTSP relay on 8554 bind to loopback by
default; keep them that way. `/api/health` only proves the HTTP server
responds; authenticated `/api/status` and actual segment files are needed to
verify recording.

SQLite uses WAL mode and stores users, settings and camera information under
`NVR_DATA_DIR`; recordings use `NVR_RECORDINGS_DIR`. All current PlainNVR
accounts have administrator-level access. The local kiosk therefore opens the
normal login, and its browser profile is cleared on reboot. An unattended
camera wall that appears without login requires a separate, intentional
limited-view role or security decision.

## What is implemented on the branch

The following files were added under `appliance/`:

| File | Purpose |
| --- | --- |
| `README.md` | Developer prototype setup and validation notes. |
| `debian/build-runtime.sh` | Build native amd64 go2rtc and FFmpeg, then stage the existing app and static frontend. |
| `debian/install-prototype.sh` | Install a staged runtime on Debian 13 amd64 and enable the server and kiosk services. Refuses to proceed without a mounted data filesystem. Does not partition or format disks. |
| `systemd/plainnvr.service` | Run the existing Python server as a non-root `plainnvr` user, with explicit data paths and a mount-point assertion. |
| `systemd/plainnvr-kiosk@.service` | Start Cage and Chromium on tty1 as a separate non-login user. |
| `kiosk/start.sh` | Launch Chromium in kiosk mode with a browser profile stored only in the per-boot runtime directory. |
| `kiosk/recovery.html` | Show a PlainNVR startup/retry screen before the server is available. |
| `kiosk/plainnvr-kiosk.pam` | Set up the kiosk's logind/PAM session. |

`build/ffmpeg/configure.sh` received only two small parameterizations:
`FFMPEG_PREFIX` and `FFMPEG_DESTDIR`. Their defaults preserve the existing
Docker build behavior. `.gitignore` excludes `appliance/out/`.

The media build uses the same pinned source archives and SHA-256 checksums as
the current Dockerfile: go2rtc v1.9.14 and FFmpeg 9.0.2. It uses the repo's
locked Go modules, FFmpeg codec configuration and FFmpeg security patch. The
build requests Go 1.27.1 via Go's toolchain mechanism because Debian 13's
packaged Go is older than the project's module requirement. The Go and FFmpeg
builds have **not** been executed on Debian yet.

The staged runtime is designed for `/opt/plainnvr/releases/<version>` with
`/opt/plainnvr/current` pointing to the active version. Application data and
recordings live on a separate persistent filesystem mounted at
`/var/lib/plainnvr`; recording files go in its `recordings/` directory. The
server unit has both `RequiresMountsFor` and `AssertPathIsMountPoint` so it
cannot silently write recordings to the OS filesystem if the data mount is
absent. This guard still needs an actual boot test.

## Verification already performed

- `sh -n` succeeded for the added shell scripts and the modified FFmpeg
  configure script.
- `git diff --check` passed.
- The changes were committed and pushed to the existing feature branch.

No Debian build, binary/linkage test, systemd boot, kiosk session, VM test,
recording test, physical GPU test, or Docker regression build has been run.
Do not describe this as production-ready.

## Why transfer to the x86 machine

The original working Mac is ARM64 and has no local x86 VM tool installed.
Building FFmpeg/go2rtc for native amd64 and booting a Debian amd64 VM there
would require emulation. An x86-64 machine with more RAM and CPU can do the
actual target-architecture build and VM tests directly. The physical old PC
must still be tested afterward for graphics compatibility and viewing load.

## Next work on the x86 machine

1. Fetch and check out `feature/plainnvr-os-native-prototype`. Read
   `appliance/README.md` and inspect the scripts before running anything as
   root. Keep work on the existing branch.
2. Create a Debian 13 **amd64** VM with a graphical display and Ethernet.
   Attach a separate persistent virtual disk, intentionally format it, mount
   it at `/var/lib/plainnvr`, and configure `/etc/fstab` by UUID. Disk work is
   manual for this prototype; no provided script should select a disk.
3. On Debian, install the build prerequisites listed in
   `appliance/README.md`, run `appliance/debian/build-runtime.sh`, and inspect
   the resulting native amd64 binaries. Check `file` and `ldd` on FFmpeg and
   FFprobe; the CGO-disabled go2rtc binary is expected to be static.
4. Run `systemd-analyze verify` on the units and execute
   `appliance/debian/install-prototype.sh` against the staged runtime. Check
   package names, PAM/logind behavior, permissions and the mount assertion
   on real Debian. Fix only what the real test shows is needed.
5. Reboot. Verify the monitor shows the startup screen and then the normal
   PlainNVR login without a desktop. Create an account and use Dashboard,
   Live View, camera wall, Cameras, Recordings, Events and Settings with a
   mouse and keyboard. Confirm the browser requires login again after reboot.
6. From another LAN machine, check `http://APPLIANCE-IP:8787/`. Test the
   WebRTC media port on both TCP and UDP; verify any advertised ICE candidate
   is actually reachable. Do not expose this HTTP prototype to the internet.
7. Add test cameras and verify simultaneous live viewing, HLS/WebRTC as
   applicable, FFmpeg segments, playback and retention. Record before and
   after reboot and after restarting the kiosk. Restart the server and ensure
   it returns. Simulate a missing data mount and confirm PlainNVR refuses to
   start instead of filling the OS disk.
8. Repeat the graphics and CPU/decoding test on the old x86 PC. Cage/Wayland
   may need an Xorg kiosk fallback on that particular hardware; decide from
   measurements rather than assumption.

Useful diagnostics on Debian: `systemctl status plainnvr.service`,
`systemctl status plainnvr-kiosk@tty1.service`, `journalctl -u
plainnvr.service -b`, `journalctl -u plainnvr-kiosk@tty1.service -b`,
`mountpoint /var/lib/plainnvr`, and
`curl http://127.0.0.1:8787/api/health`. Verify recording with authenticated
status and on-disk MP4 files, not just the health endpoint.

## Known prototype gaps and decisions

- The kiosk systemd/PAM session is based on Cage's published systemd pattern
  but has not been boot-tested. The recovery page's stylesheet probe from a
  `file:` URL needs a real Chromium test. Fix these if they fail on Debian.
- Chromium kiosk mode by itself is not a security boundary. Before public
  distribution, constrain navigation/escape paths and confirm the kiosk user
  cannot access the NVR database or recordings. It already runs separately
  from the server account.
- The local UI does not yet show the appliance LAN IP address. This should be
  a small, deliberate capability after the basic service/kiosk path works.
- No firewall policy, signed native package feed, update button, OS rollback,
  automated installer, or ISO exists. Prototype access should stay on a
  trusted LAN. Plan application updates and OS A/B recovery only after native
  startup and persistent recording are proven.
- Native Debian FFmpeg must be built and tested with the repo's pinned
  configuration and patch; substituting Debian's stock FFmpeg would create a
  second, unreviewed media runtime.
- The existing Docker/TrueNAS target must remain functional. The modified
  FFmpeg configuration script preserves its defaults, but run the existing
  image build when the native build changes are ready for review.

The first meaningful completion point is a Debian amd64 VM that boots into
PlainNVR, records across reboot onto the persistent mount, stays reachable
from another LAN device, and keeps recording if the kiosk restarts. That is
the basis for the eventual PlainNVR OS installer image.
