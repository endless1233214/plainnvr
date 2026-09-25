import json
import re
import subprocess
import time


def probe_stream_url(
    url,
    payload,
    select_streams,
    show_entries,
    *,
    stream_url_prefixes,
    ffprobe_bin,
    rtsp_probesize,
    rtsp_analyze_duration,
    rtsp_live_probesize,
    rtsp_live_analyze_duration,
    low_latency=True,
):
    if not url.startswith(stream_url_prefixes):
        raise ValueError("Unsupported stream URL scheme.")

    transport = payload.get("rtsp_transport", "tcp")
    command = [
        ffprobe_bin,
        "-v",
        "error",
    ]
    if url.startswith(("rtsp://", "rtsps://")):
        probesize = (
            rtsp_probesize
            if low_latency
            else rtsp_live_probesize
        )
        analyze_duration = (
            rtsp_analyze_duration
            if low_latency
            else rtsp_live_analyze_duration
        )
        command.extend(
            [
                "-rtsp_transport",
                transport if transport in ("tcp", "udp") else "tcp",
                "-probesize",
                probesize,
                "-analyzeduration",
                analyze_duration,
            ]
        )
        command.extend(
            ["-fflags", "nobuffer"]
            if low_latency
            else ["-fflags", "+genpts"]
        )

    command.extend(
        [
            "-select_streams",
            select_streams,
            "-show_entries",
            show_entries,
            "-of",
            "json",
            "-i",
            url,
        ]
    )

    started = time.time()
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except subprocess.TimeoutExpired:
        return {
            "ok": False,
            "message": "Timed out after 15 seconds.",
            "seconds": 15,
        }

    elapsed = round(time.time() - started, 2)
    if result.returncode != 0:
        message = (
            result.stderr.strip().splitlines()[-1]
            if result.stderr.strip()
            else "ffprobe failed."
        )
        return {
            "ok": False,
            "message": message,
            "seconds": elapsed,
        }

    try:
        details = json.loads(result.stdout or "{}")
    except json.JSONDecodeError:
        details = {}

    return {
        "ok": True,
        "message": "Stream is reachable.",
        "seconds": elapsed,
        "details": details,
    }


def test_stream(
    payload,
    *,
    stream_url_prefixes,
    normalize_bool,
    probe_stream_url,
):
    rtsp_url = str(payload.get("rtsp_url", "")).strip()
    audio_url = str(payload.get("audio_url", "")).strip()
    if not rtsp_url:
        raise ValueError("RTSP URL is required.")
    if not rtsp_url.startswith(stream_url_prefixes):
        raise ValueError(
            "Use an rtsp://, rtsps://, http://, or https:// stream URL."
        )
    if audio_url and not audio_url.startswith(stream_url_prefixes):
        raise ValueError(
            "Use an rtsp://, rtsps://, http://, or https:// audio URL."
        )

    video = probe_stream_url(
        rtsp_url,
        payload,
        "v:0",
        "stream=codec_name,width,height,r_frame_rate",
    )
    if not normalize_bool(payload.get("record_audio", True)):
        return video

    audio_source = audio_url or rtsp_url
    audio = probe_stream_url(
        audio_source,
        payload,
        "a:0",
        "stream=codec_name,sample_rate,channels",
    )
    if video["ok"] and audio["ok"]:
        return {
            "ok": True,
            "message": (
                "Video and secondary audio are reachable."
                if audio_url
                else "Video and camera audio are reachable."
            ),
            "seconds": round(
                video["seconds"] + audio["seconds"], 2
            ),
            "details": {
                "video": video.get("details", {}),
                "audio": audio.get("details", {}),
            },
        }

    return {
        "ok": False,
        "message": (
            audio["message"]
            if video["ok"]
            else video["message"]
        ),
        "seconds": round(
            video["seconds"] + audio["seconds"], 2
        ),
        "details": {"video": video, "audio": audio},
    }


def redact_camera_text(text, camera):
    redacted = text or ""
    replacements = {
        str(camera.get("rtsp_url") or "").strip(): "<stream-url>",
        str(camera.get("audio_url") or "").strip(): "<audio-url>",
        str(camera.get("onvif_url") or "").strip(): "<onvif-url>",
        str(camera.get("ptz_url") or "").strip(): "<ptz-url>",
    }
    for value, label in replacements.items():
        if value:
            redacted = redacted.replace(value, label)

    redacted = re.sub(
        r"([a-zA-Z][a-zA-Z0-9+.-]*://)[^/\s\"'@]+@",
        r"\1<credentials>@",
        redacted,
    )
    return redacted


def stream_summary(probe):
    if not probe or not probe.get("ok"):
        return (
            probe.get("message", "Unavailable")
            if probe
            else "Unavailable"
        )

    streams = (probe.get("details") or {}).get("streams") or []
    if not streams:
        return (
            "Reachable, but no matching stream details were returned"
        )

    stream = streams[0]
    codec = stream.get("codec_name") or "unknown"
    size = ""
    if stream.get("width") and stream.get("height"):
        size = f" {stream['width']}x{stream['height']}"

    sample_rate = stream.get("sample_rate")
    channels = stream.get("channels")
    audio = ""
    if sample_rate or channels:
        audio = (
            f" {sample_rate or '?'}Hz "
            f"{channels or '?'}ch"
        )

    rate = (
        stream.get("r_frame_rate")
        or stream.get("avg_frame_rate")
        or ""
    )
    suffix = rate if rate and rate != "0/0" else ""
    return " ".join(
        part
        for part in [codec + size + audio, suffix]
        if part
    )


def live_diagnostics(
    camera,
    include_audio=True,
    *,
    probe_stream_url,
    go2rtc,
    redact_camera_text,
):
    include_audio = bool(include_audio)
    profile = (
        f"go2rtc / {'audio' if include_audio else 'video only'}"
    )
    video = probe_stream_url(
        camera["rtsp_url"],
        camera,
        "v:0",
        "stream=codec_name,width,height,r_frame_rate,avg_frame_rate",
        low_latency=False,
    )

    audio = None
    if include_audio and camera.get("record_audio", True):
        audio_url = (
            str(camera.get("audio_url") or "").strip()
            or camera["rtsp_url"]
        )
        audio = probe_stream_url(
            audio_url,
            camera,
            "a:0",
            "stream=codec_name,sample_rate,channels",
            low_latency=False,
        )

    configured = (
        go2rtc.can_restream(camera)
        and go2rtc.configure_camera(camera)
    )
    stream = (
        go2rtc.stream_info(camera)
        if configured
        else None
    )
    go2rtc_result = {
        "ok": bool(
            go2rtc.running()
            and configured
            and stream is not None
        ),
        "message": (
            "go2rtc stream is configured."
            if configured
            else (
                go2rtc.last_error
                or "go2rtc stream is unavailable."
            )
        ),
        "stream": stream,
    }

    log_tail = redact_camera_text(
        go2rtc.log_tail(12),
        camera,
    )
    parts = [
        f"Profile: {profile}.",
        f"Video: {stream_summary(video)}.",
    ]
    if audio:
        parts.append(f"Audio: {stream_summary(audio)}.")
    parts.append(
        f"go2rtc: {go2rtc_result['message']}"
    )

    return {
        "ok": bool(go2rtc_result.get("ok")),
        "message": " ".join(parts),
        "video": video,
        "audio": audio,
        "go2rtc": go2rtc_result,
        "log": log_tail,
    }


def compatibility_recommendations(
    stream_result,
    discovery,
):
    recommendations = []
    details = stream_result.get("details") or {}
    streams = list(details.get("streams") or [])
    for section in ("video", "audio"):
        nested = details.get(section) or {}
        streams.extend(
            nested.get("details", nested).get("streams") or []
        )

    codecs = {
        str(item.get("codec_name") or "").lower()
        for item in streams
    }
    if "h264" not in codecs:
        recommendations.append(
            "Use H.264 for the live stream when possible; "
            "it has the widest MSE, WebRTC, Safari, and "
            "Home Assistant compatibility."
        )
    if (
        codecs.intersection(
            {"pcm_alaw", "pcm_mulaw", "pcma", "pcmu", "opus"}
        )
        and "aac" not in codecs
    ):
        recommendations.append(
            "The camera audio may need on-demand AAC "
            "transcoding for MSE playback."
        )
    if "hevc" in codecs or "h265" in codecs:
        recommendations.append(
            "H.265 support varies by browser. Keep an H.264 "
            "profile available for live view."
        )
    if not discovery.get("success"):
        recommendations.append(
            "ONVIF discovery did not complete. Verify that "
            "ONVIF is enabled in the camera and that the "
            "stream credentials also have ONVIF permission."
        )
    if (
        discovery.get("ptz_supported")
        and not discovery.get("presets")
    ):
        recommendations.append(
            "Pan/tilt was detected, but the selected ONVIF "
            "profile returned no presets."
        )
    if not recommendations:
        recommendations.append(
            "The detected stream and ONVIF capabilities match "
            "PlainNVR's preferred path."
        )
    return recommendations


def camera_compatibility_report(
    camera,
    refresh_onvif=True,
    *,
    test_stream,
    discover_camera_onvif,
    onvif_error,
    iso_now,
    server_version,
    go2rtc,
    redact_onvif_url,
    redacted_discovery,
    relay,
    recorder,
    recording_coverage,
    compatibility_recommendations,
    redact_camera_text,
):
    stream_result = test_stream(camera)
    discovery = camera.get("onvif") or {}
    discovery_error = None

    if refresh_onvif:
        try:
            discovery = discover_camera_onvif(
                camera, camera["id"]
            )
        except onvif_error as exc:
            discovery_error = str(exc)

    if discovery_error and not discovery:
        discovery = {
            "success": False,
            "tested_at": iso_now(),
            "features": [],
            "profiles": [],
            "presets": [],
            "errors": [discovery_error],
        }
    elif discovery_error:
        discovery = dict(discovery)
        discovery.setdefault("errors", []).append(
            discovery_error
        )

    report = {
        "schema_version": 1,
        "generated_at": iso_now(),
        "plainnvr": {
            "server": server_version,
            "go2rtc": go2rtc.status(),
        },
        "camera": {
            "id": camera["id"],
            "name": camera["name"],
            "enabled": camera["enabled"],
            "stream_url": redact_onvif_url(
                camera.get("rtsp_url")
            ),
            "audio_url": redact_onvif_url(
                camera.get("audio_url")
            ),
            "transport": camera.get("rtsp_transport"),
            "record_audio": camera.get("record_audio"),
            "live_view_mode": camera.get("live_view_mode"),
            "onvif_url": redact_onvif_url(
                camera.get("onvif_url")
            ),
            "ptz_enabled": camera.get("ptz_enabled"),
            "ptz_type": camera.get("ptz_type"),
        },
        "stream_probe": stream_result,
        "onvif": redacted_discovery(discovery),
        "go2rtc_stream": go2rtc.stream_info(camera),
        "relay": relay.status([camera]).get(camera["id"]),
        "recorder": recorder.status().get(camera["id"]),
        "recordings": recording_coverage(camera),
        "recommendations": compatibility_recommendations(
            stream_result, discovery
        ),
    }

    serialized = json.dumps(report)
    serialized = redact_camera_text(
        serialized,
        camera,
    )
    return json.loads(serialized)
