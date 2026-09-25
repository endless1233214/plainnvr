import json
import os
import uuid
from datetime import datetime, timedelta


def normalize_grayscale_mode(value):
    value = str(value or "off").strip().lower()
    return (
        value
        if value in ("off", "always", "auto")
        else "off"
    )


def normalize_live_view_mode(value):
    return "hls"


def normalize_view_rotation(value):
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            "Invalid view rotation."
        ) from exc
    if parsed not in (0, 90, 180, 270):
        raise ValueError(
            "Invalid view rotation."
        )
    return parsed


def normalize_ptz_type(value, *, ptz_types):
    value = str(
        value or "onvif"
    ).strip().lower()
    return (
        value
        if value in ptz_types
        else "none"
    )


def normalize_ptz_profile_token(
    value,
    *,
    default_profile_token,
):
    value = str(value or "").strip()
    return value[:80] or default_profile_token


def normalize_ptz_zoom_mode(value):
    value = str(
        value or "auto"
    ).strip().lower()
    return (
        value
        if value
        in (
            "auto",
            "digital",
            "hardware",
            "none",
        )
        else "auto"
    )


def normalize_ptz_speed(value):
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            "Invalid PTZ speed."
        ) from exc
    if parsed < 0.05 or parsed > 1.0:
        raise ValueError(
            "Invalid PTZ speed."
        )
    return round(parsed, 2)


def stable_camera_value(value):
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def camera_from_row(
    row,
    *,
    normalize_schedule,
    normalize_ptz_type,
    normalize_ptz_profile_token,
):
    data = dict(row)
    data["enabled"] = bool(data["enabled"])
    data["record_audio"] = bool(
        data["record_audio"]
    )
    data["ptz_enabled"] = bool(
        data.get("ptz_enabled", False)
    )
    data["audio_url"] = (
        data.get("audio_url") or ""
    )
    data["grayscale_mode"] = (
        normalize_grayscale_mode(
            data.get("grayscale_mode")
        )
    )
    data["live_view_mode"] = (
        normalize_live_view_mode(
            data.get("live_view_mode")
        )
    )
    data["view_rotation"] = (
        normalize_view_rotation(
            data.get("view_rotation")
        )
    )
    data["ptz_type"] = normalize_ptz_type(
        data.get("ptz_type")
    )
    data["onvif_url"] = (
        data.get("onvif_url") or ""
    )
    data["ptz_url"] = (
        data.get("ptz_url") or ""
    )
    data["ptz_profile_token"] = (
        normalize_ptz_profile_token(
            data.get("ptz_profile_token")
        )
    )
    data["ptz_zoom_mode"] = (
        normalize_ptz_zoom_mode(
            data.get("ptz_zoom_mode")
        )
    )
    data["ptz_speed"] = normalize_ptz_speed(
        data.get("ptz_speed")
    )

    try:
        onvif = json.loads(
            data.pop("onvif_json", "{}")
            or "{}"
        )
    except json.JSONDecodeError:
        onvif = {}

    data["onvif"] = onvif
    data["ptz_features"] = list(
        onvif.get("features") or []
    )
    data["ptz_presets"] = list(
        onvif.get("presets") or []
    )
    data["ptz_profiles"] = list(
        onvif.get("profiles") or []
    )

    if data["ptz_type"] == "victure_direct":
        data["ptz_features"] = ["pt"]
    elif (
        data["ptz_type"] == "victure_dvrip"
        and not data["ptz_features"]
    ):
        data["ptz_features"] = [
            "pt",
            "zoom",
        ]

    data["time_sync_supported"] = (
        data["ptz_type"]
        in (
            "victure_direct",
            "victure_dvrip",
        )
    )
    data["schedule"] = normalize_schedule(
        json.loads(
            data.pop("schedule_json")
        )
    )
    return data


def save_onvif_discovery(
    camera_id,
    result,
    *,
    cacheable_discovery,
    db_conn,
    iso_now,
):
    cached = cacheable_discovery(result)
    updated_at = str(
        cached.get("tested_at")
        or iso_now()
    )
    with db_conn() as conn:
        conn.execute(
            """
            UPDATE cameras
            SET onvif_json = ?,
                onvif_updated_at = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (
                json.dumps(cached),
                updated_at,
                iso_now(),
                camera_id,
            ),
        )
    return cached


def discover_camera_onvif(
    camera_or_payload,
    camera_id=None,
    *,
    discover_onvif,
    save_onvif_discovery,
):
    result = discover_onvif(camera_or_payload)
    if camera_id:
        save_onvif_discovery(
            camera_id,
            result,
        )
    return result


def list_cameras(
    *,
    db_conn,
    camera_from_row,
):
    with db_conn() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM cameras
            ORDER BY name COLLATE NOCASE
            """
        ).fetchall()
    return [
        camera_from_row(row)
        for row in rows
    ]


def get_camera(
    camera_id,
    *,
    db_conn,
    camera_from_row,
):
    with db_conn() as conn:
        row = conn.execute(
            "SELECT * FROM cameras "
            "WHERE id = ?",
            (camera_id,),
        ).fetchone()
    return (
        camera_from_row(row)
        if row
        else None
    )


def unique_slug(
    conn,
    name,
    camera_id=None,
    *,
    slugify,
):
    base = slugify(name)
    slug = base
    index = 2
    while True:
        row = conn.execute(
            "SELECT id FROM cameras "
            "WHERE slug = ?",
            (slug,),
        ).fetchone()
        if (
            row is None
            or row["id"] == camera_id
        ):
            return slug
        slug = f"{base}-{index}"
        index += 1


def validate_camera_payload(
    payload,
    partial=False,
    *,
    stream_url_prefixes,
    control_url_prefixes,
    dvrip_url_prefixes,
    normalize_bool,
    normalize_ptz_type,
):
    errors = {}
    name = str(
        payload.get("name", "")
    ).strip()
    rtsp_url = str(
        payload.get("rtsp_url", "")
    ).strip()
    audio_url = str(
        payload.get("audio_url", "")
    ).strip()
    onvif_url = str(
        payload.get("onvif_url", "")
    ).strip()
    ptz_url = str(
        payload.get("ptz_url", "")
    ).strip()

    if not partial or "name" in payload:
        if not name:
            errors["name"] = (
                "Name is required."
            )

    if not partial or "rtsp_url" in payload:
        if not rtsp_url:
            errors["rtsp_url"] = (
                "RTSP URL is required."
            )
        elif not rtsp_url.startswith(
            stream_url_prefixes
        ):
            errors["rtsp_url"] = (
                "Use an rtsp://, rtsps://, "
                "http://, or https:// stream URL."
            )

    if (
        audio_url
        and not audio_url.startswith(
            stream_url_prefixes
        )
    ):
        errors["audio_url"] = (
            "Use an rtsp://, rtsps://, "
            "http://, or https:// audio URL."
        )

    if (
        audio_url
        and normalize_bool(
            payload.get(
                "record_audio", True
            )
        )
    ):
        errors["audio_url"] = (
            "Separate audio URLs are not supported "
            "by the go2rtc-only restream path."
        )

    if (
        "grayscale_mode" in payload
        and normalize_grayscale_mode(
            payload.get("grayscale_mode")
        )
        != str(
            payload.get("grayscale_mode")
            or ""
        ).strip().lower()
    ):
        errors["grayscale_mode"] = (
            "Use off, always, or auto."
        )

    if (
        "live_view_mode" in payload
        and str(
            payload.get("live_view_mode")
            or "hls"
        ).strip().lower()
        != "hls"
    ):
        errors["live_view_mode"] = "Use hls."

    if "view_rotation" in payload:
        try:
            normalize_view_rotation(
                payload.get("view_rotation")
            )
        except ValueError:
            errors["view_rotation"] = (
                "Use 0, 90, 180, or 270."
            )

    if (
        onvif_url
        and not onvif_url.startswith(
            control_url_prefixes
        )
    ):
        errors["onvif_url"] = (
            "Use an http:// or https:// "
            "ONVIF device endpoint URL."
        )

    ptz_type = normalize_ptz_type(
        payload.get("ptz_type")
    )

    if (
        ptz_url
        and ptz_type == "onvif"
        and not ptz_url.startswith(
            control_url_prefixes
        )
    ):
        errors["ptz_url"] = (
            "Use an http:// or https:// "
            "ONVIF endpoint URL."
        )

    if (
        ptz_url
        and ptz_type == "victure_dvrip"
        and "://" in ptz_url
        and not ptz_url.startswith(
            dvrip_url_prefixes
        )
    ):
        errors["ptz_url"] = (
            "Use a dvrip:// host URL, "
            "or leave blank to use "
            "the stream host."
        )

    if (
        ptz_url
        and ptz_type == "victure_direct"
        and "://" in ptz_url
        and not ptz_url.startswith(
            control_url_prefixes
        )
    ):
        errors["ptz_url"] = (
            "Use an http:// admin URL, "
            "or leave blank to use "
            "the stream host."
        )

    if (
        "ptz_type" in payload
        and ptz_type
        != str(
            payload.get("ptz_type")
            or ""
        ).strip().lower()
    ):
        errors["ptz_type"] = (
            "Use none, onvif, "
            "victure_dvrip, or "
            "victure_direct."
        )

    if "ptz_speed" in payload:
        try:
            normalize_ptz_speed(
                payload.get("ptz_speed")
            )
        except ValueError:
            errors["ptz_speed"] = (
                "Use a PTZ speed "
                "from 0.05 to 1.0."
            )

    if (
        "ptz_profile_token" in payload
        and len(
            str(
                payload.get(
                    "ptz_profile_token"
                )
                or ""
            )
        )
        > 80
    ):
        errors["ptz_profile_token"] = (
            "Profile token is too long."
        )

    if (
        "ptz_zoom_mode" in payload
        and normalize_ptz_zoom_mode(
            payload.get("ptz_zoom_mode")
        )
        != str(
            payload.get("ptz_zoom_mode")
            or ""
        ).strip().lower()
    ):
        errors["ptz_zoom_mode"] = (
            "Use auto, digital, "
            "hardware, or none."
        )

    if errors:
        raise ValueError(
            json.dumps(errors)
        )


def create_camera(
    payload,
    *,
    validate_camera_payload,
    iso_now,
    normalize_schedule,
    default_segment_seconds,
    default_ptz_speed,
    normalize_ptz_type,
    normalize_ptz_speed,
    db_conn,
    unique_slug,
    normalize_bool,
    normalize_ptz_profile_token,
    get_camera,
    configure_camera,
):
    validate_camera_payload(payload)
    now = iso_now()
    camera_id = uuid.uuid4().hex
    schedule = normalize_schedule(
        payload.get("schedule")
    )
    segment_seconds = max(
        10,
        int(
            payload.get("segment_seconds")
            or default_segment_seconds
        ),
    )
    retention_days = max(
        1,
        int(
            payload.get("retention_days")
            or 14
        ),
    )
    ptz_type = normalize_ptz_type(
        payload.get("ptz_type")
    )
    ptz_speed = normalize_ptz_speed(
        payload.get(
            "ptz_speed",
            default_ptz_speed,
        )
    )

    with db_conn() as conn:
        slug = unique_slug(
            conn, payload["name"]
        )
        conn.execute(
            """
            INSERT INTO cameras (
                id, name, slug,
                rtsp_url, audio_url,
                enabled, segment_seconds,
                retention_days,
                schedule_json, record_audio,
                grayscale_mode,
                live_view_mode,
                rtsp_transport,
                ptz_enabled, ptz_type,
                view_rotation,
                onvif_url, ptz_url,
                ptz_profile_token,
                ptz_zoom_mode,
                ptz_speed,
                created_at, updated_at
            )
            VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?, ?
            )
            """,
            (
                camera_id,
                payload["name"].strip(),
                slug,
                payload["rtsp_url"].strip(),
                str(
                    payload.get(
                        "audio_url", ""
                    )
                ).strip(),
                normalize_bool(
                    payload.get(
                        "enabled", True
                    )
                ),
                segment_seconds,
                retention_days,
                json.dumps(schedule),
                normalize_bool(
                    payload.get(
                        "record_audio", True
                    )
                ),
                normalize_grayscale_mode(
                    payload.get(
                        "grayscale_mode"
                    )
                ),
                normalize_live_view_mode(
                    payload.get(
                        "live_view_mode"
                    )
                ),
                (
                    payload.get(
                        "rtsp_transport",
                        "tcp",
                    )
                    if payload.get(
                        "rtsp_transport"
                    )
                    in ("tcp", "udp")
                    else "tcp"
                ),
                normalize_bool(
                    payload.get(
                        "ptz_enabled", False
                    )
                ),
                ptz_type,
                normalize_view_rotation(
                    payload.get(
                        "view_rotation", 0
                    )
                ),
                str(
                    payload.get(
                        "onvif_url", ""
                    )
                ).strip(),
                str(
                    payload.get(
                        "ptz_url", ""
                    )
                ).strip(),
                normalize_ptz_profile_token(
                    payload.get(
                        "ptz_profile_token"
                    )
                ),
                normalize_ptz_zoom_mode(
                    payload.get(
                        "ptz_zoom_mode"
                    )
                ),
                ptz_speed,
                now,
                now,
            ),
        )

    camera = get_camera(camera_id)
    if configure_camera:
        configure_camera(camera)
    return camera


def update_camera(
    camera_id,
    payload,
    *,
    get_camera,
    validate_camera_payload,
    normalize_schedule,
    default_segment_seconds,
    default_ptz_speed,
    normalize_ptz_type,
    normalize_ptz_speed,
    db_conn,
    unique_slug,
    normalize_bool,
    normalize_ptz_profile_token,
    iso_now,
    configure_camera,
    recorder_restart,
    relay_stop,
):
    existing = get_camera(camera_id)
    if not existing:
        return None

    validate_camera_payload(
        payload,
        partial=True,
    )
    merged = {**existing, **payload}
    schedule = normalize_schedule(
        merged.get("schedule")
    )
    segment_seconds = max(
        10,
        int(
            merged.get("segment_seconds")
            or default_segment_seconds
        ),
    )
    retention_days = max(
        1,
        int(
            merged.get("retention_days")
            or 14
        ),
    )
    ptz_type = normalize_ptz_type(
        merged.get("ptz_type")
    )
    ptz_speed = normalize_ptz_speed(
        merged.get(
            "ptz_speed",
            default_ptz_speed,
        )
    )

    restart_fields = (
        "name",
        "rtsp_url",
        "audio_url",
        "enabled",
        "segment_seconds",
        "retention_days",
        "schedule",
        "record_audio",
        "grayscale_mode",
        "live_view_mode",
        "rtsp_transport",
    )
    restart_required = any(
        stable_camera_value(
            existing.get(key)
        )
        != stable_camera_value(
            merged.get(key)
        )
        for key in restart_fields
    )

    discovery_changed = any(
        str(existing.get(key) or "")
        != str(merged.get(key) or "")
        for key in (
            "rtsp_url",
            "onvif_url",
            "ptz_url",
            "ptz_profile_token",
            "ptz_type",
        )
    )
    onvif_json = (
        "{}"
        if discovery_changed
        else json.dumps(
            existing.get("onvif") or {}
        )
    )
    onvif_updated_at = (
        ""
        if discovery_changed
        else str(
            existing.get(
                "onvif_updated_at"
            )
            or ""
        )
    )

    with db_conn() as conn:
        slug = unique_slug(
            conn,
            merged["name"],
            camera_id,
        )
        conn.execute(
            """
            UPDATE cameras
            SET name = ?, slug = ?,
                rtsp_url = ?, audio_url = ?,
                enabled = ?,
                segment_seconds = ?,
                retention_days = ?,
                schedule_json = ?,
                record_audio = ?,
                grayscale_mode = ?,
                live_view_mode = ?,
                view_rotation = ?,
                rtsp_transport = ?,
                ptz_enabled = ?,
                ptz_type = ?,
                onvif_url = ?,
                ptz_url = ?,
                ptz_profile_token = ?,
                ptz_zoom_mode = ?,
                ptz_speed = ?,
                onvif_json = ?,
                onvif_updated_at = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (
                str(
                    merged["name"]
                ).strip(),
                slug,
                str(
                    merged["rtsp_url"]
                ).strip(),
                str(
                    merged.get(
                        "audio_url", ""
                    )
                ).strip(),
                normalize_bool(
                    merged.get("enabled")
                ),
                segment_seconds,
                retention_days,
                json.dumps(schedule),
                normalize_bool(
                    merged.get(
                        "record_audio"
                    )
                ),
                normalize_grayscale_mode(
                    merged.get(
                        "grayscale_mode"
                    )
                ),
                normalize_live_view_mode(
                    merged.get(
                        "live_view_mode"
                    )
                ),
                normalize_view_rotation(
                    merged.get(
                        "view_rotation", 0
                    )
                ),
                (
                    merged.get(
                        "rtsp_transport"
                    )
                    if merged.get(
                        "rtsp_transport"
                    )
                    in ("tcp", "udp")
                    else "tcp"
                ),
                normalize_bool(
                    merged.get(
                        "ptz_enabled"
                    )
                ),
                ptz_type,
                str(
                    merged.get(
                        "onvif_url", ""
                    )
                ).strip(),
                str(
                    merged.get(
                        "ptz_url", ""
                    )
                ).strip(),
                normalize_ptz_profile_token(
                    merged.get(
                        "ptz_profile_token"
                    )
                ),
                normalize_ptz_zoom_mode(
                    merged.get(
                        "ptz_zoom_mode"
                    )
                ),
                ptz_speed,
                onvif_json,
                onvif_updated_at,
                iso_now(),
                camera_id,
            ),
        )

    camera = get_camera(camera_id)
    if restart_required:
        if configure_camera:
            configure_camera(camera)
        recorder_restart(camera_id)
        relay_stop(camera_id)
    return camera


def delete_camera(
    camera_id,
    *,
    recorder_stop,
    relay_stop,
    manager_delete_camera,
    db_conn,
):
    recorder_stop(camera_id)
    relay_stop(camera_id)
    if manager_delete_camera:
        manager_delete_camera(camera_id)
    with db_conn() as conn:
        cur = conn.execute(
            "DELETE FROM cameras WHERE id = ?",
            (camera_id,),
        )
    return cur.rowcount > 0


def add_event(
    camera_id,
    level,
    message,
    *,
    event_level_enabled,
    db_conn,
    utcnow,
    iso_now,
    sqlite_error,
):
    if not event_level_enabled(level):
        return

    try:
        with db_conn() as conn:
            previous = conn.execute(
                """
                SELECT created_at
                FROM recorder_events
                WHERE camera_id = ?
                  AND level = ?
                  AND message = ?
                ORDER BY id DESC
                LIMIT 1
                """,
                (
                    camera_id,
                    level,
                    message[:500],
                ),
            ).fetchone()

            if previous:
                try:
                    previous_at = (
                        datetime.fromisoformat(
                            previous["created_at"]
                        )
                    )
                    if (
                        utcnow() - previous_at
                        < timedelta(seconds=60)
                    ):
                        return
                except (
                    TypeError,
                    ValueError,
                ):
                    pass

            conn.execute(
                """
                INSERT INTO recorder_events (
                    camera_id, level,
                    message, created_at
                )
                VALUES (?, ?, ?, ?)
                """,
                (
                    camera_id,
                    level,
                    message[:500],
                    iso_now(),
                ),
            )
            conn.execute(
                """
                DELETE FROM recorder_events
                WHERE id NOT IN (
                    SELECT id
                    FROM recorder_events
                    WHERE camera_id = ?
                    ORDER BY id DESC
                    LIMIT 50
                )
                AND camera_id = ?
                """,
                (
                    camera_id,
                    camera_id,
                ),
            )
    except sqlite_error:
        pass


def camera_dir(camera, recordings_dir):
    return recordings_dir / camera["slug"]


def ensure_recording_directory(
    camera,
    *,
    camera_dir,
):
    target_dir = camera_dir(camera)
    probe_path = (
        target_dir
        / f".plainnvr-write-test-{uuid.uuid4().hex}"
    )
    try:
        target_dir.mkdir(
            parents=True,
            exist_ok=True,
        )
        with probe_path.open("wb") as handle:
            handle.write(b"")
        probe_path.unlink()
    except OSError as exc:
        try:
            probe_path.unlink(
                missing_ok=True
            )
        except OSError:
            pass
        raise RuntimeError(
            "Recording directory is not writable: "
            f"{target_dir}. Check storage ownership "
            f"or ACLs for UID {os.getuid()} "
            f"and GID {os.getgid()}."
        ) from exc
    return target_dir
