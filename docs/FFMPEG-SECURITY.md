# FFmpeg 9.0.2 advisory review

Reviewed 2026-09-22 against the 32 FFmpeg IDs in the original Debian image scan.
This table records disposition of that baseline, not a guarantee that the full
upstream codebase has no unknown issues. Trivy does not discover the source-built
FFmpeg executable; a clean image scan cannot replace this review.

The source archive is checksum-pinned in Dockerfile. `build/ffmpeg/configure.sh`
starts with components disabled and explicitly enables camera features. Selected
exclusions have build-time assertions; the full generated `config_components.h`
is retained in the image under `/usr/share/plainnvr`. Components described as
excluded below are outside that allowlist (including dependencies checked in the
compiled configuration). Common code that remains linked is reviewed separately.

| Advisory | Candidate disposition | Evidence |
| --- | --- | --- |
| CVE-2026-13858 | Patched locally: MOV seek validates negative indexes and both array lengths; actual-function ASan/UBSan regression runs during build. | [Tracker](https://security-tracker.debian.org/tracker/CVE-2026-13858); [public report](https://issues.chromium.org/issues/507090179), [patch](../build/ffmpeg/mov-seek-bounds.patch), [regression](../build/ffmpeg/test-mov-seek-bounds.sh) |
| CVE-2026-18393 | Not built: TDSC decoder. | [Tracker](https://security-tracker.debian.org/tracker/CVE-2026-18393); [upstream](https://code.ffmpeg.org/FFmpeg/FFmpeg/commit/031fae5c41e6200d3d9b593339be724857b2aacd) |
| CVE-2026-30999 | Fixed in 9.0; Debian assessment is a CLI memory leak without security impact. | [Tracker](https://security-tracker.debian.org/tracker/CVE-2026-30999) |
| CVE-2026-38350 | Fixed upstream in 8.0 (swscale arithmetic), included in 9.0.2. | [Tracker](https://security-tracker.debian.org/tracker/CVE-2026-38350); [upstream](https://code.ffmpeg.org/FFmpeg/FFmpeg/commit/aca41d3d9327be4d6ab036f494b700118fcc04e1) |
| CVE-2026-58049 | Not built: RASC decoder. | [Tracker](https://security-tracker.debian.org/tracker/CVE-2026-58049); [upstream](https://code.ffmpeg.org/FFmpeg/FFmpeg/commit/f8d7795dcca36a4dd412e89cbd83e3dfec1e0d81) |
| CVE-2026-6385 | Not built: DVD subtitle parser/decoder. | [Tracker](https://security-tracker.debian.org/tracker/CVE-2026-6385) |
| CVE-2026-64830 | Not built: VobSub demuxer. | [Tracker](https://security-tracker.debian.org/tracker/CVE-2026-64830); [upstream](https://code.ffmpeg.org/FFmpeg/FFmpeg/commit/dbd495f066a85ba96b17433f4306582aa37c3951) |
| CVE-2026-64832 | Not built: NVDEC hardware acceleration. | [Tracker](https://security-tracker.debian.org/tracker/CVE-2026-64832); [upstream](https://code.ffmpeg.org/FFmpeg/FFmpeg/commit/9cbcf979a587a66b280496657d00fabe301bf20f) |
| CVE-2026-64833 | Not built: S/PDIF muxer. | [Tracker](https://security-tracker.debian.org/tracker/CVE-2026-64833); [upstream](https://code.ffmpeg.org/FFmpeg/FFmpeg/commit/6f80e2765492700622596af720534cef33dd31b4) |
| CVE-2026-64834 | Fixed in source: RTP/ASF chunk size is checked for minimum header size and remaining bytes. | [Tracker](https://security-tracker.debian.org/tracker/CVE-2026-64834); [upstream](https://code.ffmpeg.org/FFmpeg/FFmpeg/commit/11d5f475be95d22d5f0692220cc772b116abc632) |
| CVE-2026-64835 | Not built: ADX decoder. | [Tracker](https://security-tracker.debian.org/tracker/CVE-2026-64835); [upstream](https://code.ffmpeg.org/FFmpeg/FFmpeg/commit/1836ef96846937a6cc2443698a693104f5c0b21e) |
| CVE-2026-65703 | Not built: TDSC decoder. | [Tracker](https://security-tracker.debian.org/tracker/CVE-2026-65703); [upstream](https://code.ffmpeg.org/FFmpeg/FFmpeg/commit/fd3ee52fab34d98a95b787d0b5ff45685766200c) |
| CVE-2026-65704 | Not built: concat/TY demuxers and Shorten decoder. | [Tracker](https://security-tracker.debian.org/tracker/CVE-2026-65704); [upstream](https://code.ffmpeg.org/FFmpeg/FFmpeg/commit/de771bd52774a52d45b0e2c82e56995a1ef40df7) |
| CVE-2026-65705 | Not built: floodfill filter. | [Tracker](https://security-tracker.debian.org/tracker/CVE-2026-65705); [upstream](https://code.ffmpeg.org/FFmpeg/FFmpeg/commit/f186c50cf53aec20e9a29059cb22ca3f2d59201c) |
| CVE-2026-65706 | Not built: swaprect filter. | [Tracker](https://security-tracker.debian.org/tracker/CVE-2026-65706); [upstream](https://code.ffmpeg.org/FFmpeg/FFmpeg/commit/a7e38b617b32f996beaa371bbf04b39907d7a527) |
| CVE-2026-66036 | Not built: hqdn3d filter. | [Tracker](https://security-tracker.debian.org/tracker/CVE-2026-66036); [upstream](https://code.ffmpeg.org/FFmpeg/FFmpeg/commit/5d7112c60e6f0f0742ce47d448e6da0718a70f4c) |
| CVE-2026-66037 | Fixed in source: IAMF count_label is checked against remaining bytes before allocation. IAMF code can be linked by MOV even with its standalone demuxer disabled. | [Tracker](https://security-tracker.debian.org/tracker/CVE-2026-66037); [upstream](https://code.ffmpeg.org/FFmpeg/FFmpeg/commit/86708357d126af84c16f80d9c57335d1e8c845c5) |
| CVE-2026-66038 | Not built: LCL/ZLIB decoder. | [Tracker](https://security-tracker.debian.org/tracker/CVE-2026-66038); [upstream](https://code.ffmpeg.org/FFmpeg/FFmpeg/commit/e7cbfd1c507b57a806a5825b87d609963e862c8c) |
| CVE-2026-66039 | Not built: CAF demuxer and MACE decoder. | [Tracker](https://security-tracker.debian.org/tracker/CVE-2026-66039); [upstream](https://code.ffmpeg.org/FFmpeg/FFmpeg/commit/aafb5c655edc76a753275c383ebb139feb032718) |
| CVE-2026-66040 | Not built: PNG/APNG encoders. | [Tracker](https://security-tracker.debian.org/tracker/CVE-2026-66040); [upstream](https://code.ffmpeg.org/FFmpeg/FFmpeg/commit/b506fafec9a19fcbc2be5271875fd4a63d6615bc) |
| CVE-2026-66041 | Not built: quirc filter and subtitle components. | [Tracker](https://security-tracker.debian.org/tracker/CVE-2026-66041); [upstream](https://code.ffmpeg.org/FFmpeg/FFmpeg/commit/030e1401451200566a5303f35cbe1456e31dd81e) |
| CVE-2026-70628 | Not built: DVB subtitle parser. | [Tracker](https://security-tracker.debian.org/tracker/CVE-2026-70628); [upstream](https://code.ffmpeg.org/FFmpeg/FFmpeg/commit/02fc47e13f903768b75f7985a2706a6223ab4506) |
| CVE-2026-70629 | Not built: RSCC decoder. | [Tracker](https://security-tracker.debian.org/tracker/CVE-2026-70629); [upstream](https://code.ffmpeg.org/FFmpeg/FFmpeg/commit/a5fe21a1a410a680fe93c33b0dd696b7e1c3aea4) |
| CVE-2026-70630 | Not built: Screenpresso decoder. | [Tracker](https://security-tracker.debian.org/tracker/CVE-2026-70630); [upstream](https://code.ffmpeg.org/FFmpeg/FFmpeg/commit/c22667d0fd7916a33fd3e79685b7246fc48f1a62) |
| CVE-2026-70631 | Not built: TIFF decoder. | [Tracker](https://security-tracker.debian.org/tracker/CVE-2026-70631); [upstream](https://code.ffmpeg.org/FFmpeg/FFmpeg/commit/3c287af3affe1286350faa69c02bcc5d49de18bb) |
| CVE-2026-70632 | Not built: CineForm decoder. | [Tracker](https://security-tracker.debian.org/tracker/CVE-2026-70632); [upstream](https://code.ffmpeg.org/FFmpeg/FFmpeg/commit/db05df9d135fb56a4babb836d5e9f5c1d984e087) |
| CVE-2026-75141 | Fixed in 9.0.1; source rejects hvcC NAL counts at UINT16_MAX before allocation. | [Tracker](https://security-tracker.debian.org/tracker/CVE-2026-75141); [upstream](https://code.ffmpeg.org/FFmpeg/FFmpeg/commit/c7132ef8f63c383d11a00a9e3034748d8dd15fb3) |
| CVE-2026-75142 | Not built: MPEG-PS muxer. | [Tracker](https://security-tracker.debian.org/tracker/CVE-2026-75142); [upstream](https://code.ffmpeg.org/FFmpeg/FFmpeg/commit/b274f0d21ba684446fd59b49e00f3f8e9ed954df) |
| CVE-2026-75143 | Not built: RIST protocol. | [Tracker](https://security-tracker.debian.org/tracker/CVE-2026-75143); [upstream](https://code.ffmpeg.org/FFmpeg/FFmpeg/commit/8880a174d08131f94f58a0492d1c8c6d68b74f67) |
| CVE-2026-75144 | Fixed in 9.0.1; source validates the VC-2 RTP unit against the destination payload capacity. RTP packetizer code is linked independently of the Dirac decoder. | [Tracker](https://security-tracker.debian.org/tracker/CVE-2026-75144); [upstream](https://code.ffmpeg.org/FFmpeg/FFmpeg/commit/1afd5c3ddafda4209e0881cd30684b919e99de7c) |
| CVE-2026-75146 | Not built: DASH demuxer. | [Tracker](https://security-tracker.debian.org/tracker/CVE-2026-75146); [upstream](https://code.ffmpeg.org/FFmpeg/FFmpeg/commit/999f8ba75ce0bf1167677de7e11a5af678fdb866) |
| CVE-2026-90816 | Deprecated hlsproto implementation removed upstream in 8.1; HLS demuxer remains supported. | [Tracker](https://security-tracker.debian.org/tracker/CVE-2026-90816); [upstream](https://code.ffmpeg.org/FFmpeg/FFmpeg/commit/64fafd63f0b4ebf8dbbdbdc2296f21a03548b5fc) |

## Update procedure

When changing the FFmpeg version, configuration or patch, review new upstream
advisories, preserve or replace the MOV regression, inspect linked helper code
as well as enabled top-level formats, and rerun live recording (with audio),
snapshot, night sampling, HLS and native playback checks. Do not treat disabling
a decoder as proof that a similarly named demuxer/muxer/helper is absent.
