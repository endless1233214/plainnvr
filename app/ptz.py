import json
import re
import socket
import time
from datetime import datetime
from html import escape as html_escape
from urllib import error as urllib_error, request as urllib_request
from urllib.parse import unquote, urlencode, urlparse


def netloc_without_credentials(parsed):
    host = parsed.hostname or ""
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    return (
        f"{host}:{parsed.port}"
        if parsed.port
        else host
    )


def url_credentials(parsed):
    if parsed.username is None:
        return None
    return (
        unquote(parsed.username),
        unquote(parsed.password or ""),
    )


def clean_control_url(value):
    parsed = urlparse(value)
    netloc = netloc_without_credentials(parsed)
    path = parsed.path or "/"
    query = f"?{parsed.query}" if parsed.query else ""
    return f"{parsed.scheme}://{netloc}{path}{query}"


def redact_url_credentials(value):
    parsed = urlparse(str(value or ""))
    if not parsed.username:
        return value
    netloc = netloc_without_credentials(parsed)
    path = parsed.path or ""
    query = f"?{parsed.query}" if parsed.query else ""
    return (
        f"{parsed.scheme}://<credentials>@"
        f"{netloc}{path}{query}"
    )


def dvrip_url_for_parse(value):
    value = str(value or "").strip()
    if "://" in value:
        return value
    return f"dvrip://{value}"


def dvrip_target(
    camera,
    *,
    default_profile_token,
    default_port,
    default_user,
    default_passhash,
):
    explicit_url = str(
        camera.get("ptz_url") or ""
    ).strip()
    source = (
        explicit_url
        or str(camera.get("rtsp_url") or "").strip()
    )
    if not source:
        raise ValueError(
            "Could not derive a DVRIP endpoint "
            "from this camera URL."
        )

    parsed = urlparse(
        dvrip_url_for_parse(source)
        if explicit_url
        else source
    )
    host = parsed.hostname
    if not host:
        raise ValueError(
            "Could not derive a DVRIP endpoint "
            "from this camera URL."
        )

    credentials = (
        url_credentials(parsed)
        if explicit_url
        else None
    )
    configured_hash = str(
        camera.get("ptz_profile_token") or ""
    ).strip()
    if (
        not configured_hash
        or configured_hash == default_profile_token
    ):
        configured_hash = default_passhash

    user, passhash = credentials or (
        default_user,
        configured_hash,
    )
    port = (
        (parsed.port if explicit_url else None)
        or default_port
    )
    endpoint = f"dvrip://{host}:{port}"
    if ":" in host and not host.startswith("["):
        endpoint = f"dvrip://[{host}]:{port}"

    return {
        "host": host,
        "port": port,
        "user": user or default_user,
        "passhash": passhash or default_passhash,
        "endpoint": endpoint,
    }


def dvrip_step_from_speed(speed):
    return max(1, min(64, round(speed * 4)))


def dvrip_recv_exact(sock, length):
    chunks = []
    remaining = length
    while remaining:
        chunk = sock.recv(remaining)
        if not chunk:
            raise ConnectionError(
                "DVRIP connection closed early."
            )
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def dvrip_send_packet(
    sock,
    session,
    number,
    packet_type,
    payload,
    *,
    header,
):
    data = payload.encode("utf-8")
    packed = header.pack(
        0xFF,
        0x01,
        0,
        session,
        number,
        0,
        0,
        packet_type,
        len(data),
    )
    sock.sendall(packed + data)


def dvrip_recv_packet(sock, *, header):
    raw_header = dvrip_recv_exact(
        sock, header.size
    )
    (
        magic,
        version,
        _pad,
        session,
        number,
        fragments,
        fragment,
        packet_type,
        length,
    ) = header.unpack(raw_header)

    if magic != 0xFF or version != 0x01:
        raise RuntimeError(
            "DVRIP returned an invalid header."
        )

    payload = (
        dvrip_recv_exact(sock, length)
        if length
        else b""
    )
    return {
        "session": session,
        "number": number,
        "fragments": fragments,
        "fragment": fragment,
        "type": packet_type,
        "payload": payload.decode(
            "utf-8", errors="replace"
        ).rstrip("\0"),
    }


def dvrip_parse_session(payload):
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        data = {}

    session_id = data.get("SessionID")
    if isinstance(session_id, str):
        return int(session_id, 16)
    if isinstance(session_id, int):
        return session_id

    match = re.search(
        r'"SessionID"\s*:\s*"?(0x[0-9a-fA-F]+|\d+)"?',
        payload,
    )
    if match:
        return int(match.group(1), 0)
    return 0


def dvrip_parse_json(payload):
    try:
        return json.loads(payload)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            "DVRIP returned invalid JSON."
        ) from exc


def dvrip_login(
    sock,
    target,
    *,
    header,
):
    login = json.dumps(
        {
            "EncryptType": "MD5",
            "LoginType": "DVRIP-Web",
            "PassWord": target["passhash"],
            "UserName": target["user"],
        },
        separators=(",", ":"),
    )
    dvrip_send_packet(
        sock,
        0,
        2,
        1000,
        login,
        header=header,
    )
    reply = dvrip_recv_packet(
        sock,
        header=header,
    )
    details = dvrip_parse_json(reply["payload"])
    session = dvrip_parse_session(reply["payload"])
    if not session or details.get("Ret") != 100:
        raise RuntimeError("DVRIP login failed.")
    return session


def dvrip_query_time(
    sock,
    session,
    *,
    header,
    number=4,
):
    payload = json.dumps(
        {
            "Name": "OPTimeQuery",
            "SessionID": f"0x{session:08X}",
        },
        separators=(",", ":"),
    )
    dvrip_send_packet(
        sock,
        session,
        number,
        1452,
        payload,
        header=header,
    )
    details = dvrip_parse_json(
        dvrip_recv_packet(
            sock,
            header=header,
        )["payload"]
    )
    if (
        details.get("Ret") != 100
        or not details.get("OPTimeQuery")
    ):
        raise RuntimeError(
            "Camera did not return its clock."
        )
    return datetime.strptime(
        details["OPTimeQuery"],
        "%Y-%m-%d %H:%M:%S",
    )


def normalize_requested_camera_time(value):
    text = str(value or "").strip()
    if not text:
        return datetime.now().replace(
            microsecond=0
        )
    try:
        parsed = datetime.fromisoformat(
            text.replace("Z", "+00:00")
        )
    except ValueError as exc:
        raise ValueError(
            "Invalid camera date and time."
        ) from exc

    if parsed.tzinfo is not None:
        parsed = parsed.astimezone().replace(
            tzinfo=None
        )
    parsed = parsed.replace(microsecond=0)
    if parsed.year < 2001 or parsed.year > 2100:
        raise ValueError(
            "Camera date must be between 2001 and 2100."
        )
    return parsed


def camera_time(
    camera,
    requested=None,
    *,
    normalize_ptz_type,
    default_profile_token,
    default_port,
    default_user,
    default_passhash,
    header,
):
    if not camera.get("time_sync_supported"):
        raise ValueError(
            "Clock sync is not available "
            "for this camera driver."
        )

    target_camera = dict(camera)
    if (
        normalize_ptz_type(
            camera.get("ptz_type")
        )
        != "victure_dvrip"
    ):
        target_camera["ptz_url"] = ""

    target = dvrip_target(
        target_camera,
        default_profile_token=default_profile_token,
        default_port=default_port,
        default_user=default_user,
        default_passhash=default_passhash,
    )

    try:
        with socket.create_connection(
            (target["host"], target["port"]),
            timeout=4,
        ) as sock:
            sock.settimeout(4)
            session = dvrip_login(
                sock,
                target,
                header=header,
            )
            if requested is not None:
                value = normalize_requested_camera_time(
                    requested
                )
                payload = json.dumps(
                    {
                        "Name": "OPTimeSetting",
                        "OPTimeSetting": value.strftime(
                            "%Y-%m-%d %H:%M:%S"
                        ),
                        "SessionID": (
                            f"0x{session:08X}"
                        ),
                    },
                    separators=(",", ":"),
                )
                dvrip_send_packet(
                    sock,
                    session,
                    4,
                    1450,
                    payload,
                    header=header,
                )
                details = dvrip_parse_json(
                    dvrip_recv_packet(
                        sock,
                        header=header,
                    )["payload"]
                )
                if details.get("Ret") != 100:
                    raise RuntimeError(
                        "Camera rejected the clock update."
                    )
                current = dvrip_query_time(
                    sock,
                    session,
                    number=6,
                    header=header,
                )
            else:
                current = dvrip_query_time(
                    sock,
                    session,
                    header=header,
                )
    except (TimeoutError, OSError) as exc:
        raise RuntimeError(
            f"Camera clock request failed: {exc}"
        ) from exc

    return {
        "ok": True,
        "driver": "dvrip",
        "time": current.strftime(
            "%Y-%m-%d %H:%M:%S"
        ),
        "endpoint": target["endpoint"],
    }


def run_victure_dvrip_ptz_command(
    camera,
    action,
    speed,
    duration_ms,
    *,
    commands,
    move_vectors,
    default_profile_token,
    default_port,
    default_user,
    default_passhash,
    header,
):
    if action == "home":
        return {
            "ok": True,
            "action": action,
            "driver": "victure_dvrip",
            "warning": (
                "Home is not available on the "
                "Victure DVRIP driver."
            ),
        }

    command = commands.get(action)
    if not command:
        raise ValueError("Unsupported PTZ action.")

    target = dvrip_target(
        camera,
        default_profile_token=default_profile_token,
        default_port=default_port,
        default_user=default_user,
        default_passhash=default_passhash,
    )
    step = dvrip_step_from_speed(speed)

    try:
        with socket.create_connection(
            (target["host"], target["port"]),
            timeout=4,
        ) as sock:
            sock.settimeout(4)
            session = dvrip_login(
                sock,
                target,
                header=header,
            )

            def ptz_payload(
                ptz_command,
                preset,
            ):
                return json.dumps(
                    {
                        "Name": "OPPTZControl",
                        "OPPTZControl": {
                            "Command": ptz_command,
                            "Parameter": {
                                "AUX": {
                                    "Number": 0,
                                    "Status": "On",
                                },
                                "Channel": 0,
                                "MenuOpts": "Enter",
                                "POINT": {
                                    "bottom": 0,
                                    "left": 0,
                                    "right": 0,
                                    "top": 0,
                                },
                                "Pattern": "SetBegin",
                                "Preset": preset,
                                "Step": step,
                                "Tour": 0,
                            },
                        },
                        "SessionID": (
                            f"0x{session:08X}"
                        ),
                    },
                    separators=(",", ":"),
                )

            if action == "stop":
                for offset, stop_command in enumerate(
                    (
                        "DirectionUp",
                        "DirectionDown",
                        "DirectionLeft",
                        "DirectionRight",
                    )
                ):
                    dvrip_send_packet(
                        sock,
                        session,
                        4 + offset,
                        1400,
                        ptz_payload(
                            stop_command, -1
                        ),
                        header=header,
                    )
            else:
                dvrip_send_packet(
                    sock,
                    session,
                    4,
                    1400,
                    ptz_payload(
                        command, 65535
                    ),
                    header=header,
                )
                time.sleep(
                    duration_ms / 1000
                )
                dvrip_send_packet(
                    sock,
                    session,
                    5,
                    1400,
                    ptz_payload(command, -1),
                    header=header,
                )
    except (TimeoutError, OSError) as exc:
        raise RuntimeError(
            f"DVRIP command failed: {exc}"
        ) from exc

    return {
        "ok": True,
        "action": action,
        "driver": "victure_dvrip",
        "endpoint": target["endpoint"],
        "step": step,
        "duration_ms": (
            duration_ms
            if action in move_vectors
            else 0
        ),
    }


def http_admin_url_for_parse(value):
    value = str(value or "").strip()
    if "://" in value:
        return value
    return f"http://{value}"


def victure_direct_target(
    camera,
    *,
    default_port,
):
    explicit_url = str(
        camera.get("ptz_url") or ""
    ).strip()
    source = (
        explicit_url
        or str(camera.get("rtsp_url") or "").strip()
    )
    if not source:
        raise ValueError(
            "Could not derive a Victure admin "
            "endpoint from this camera URL."
        )

    parsed = urlparse(
        http_admin_url_for_parse(source)
        if explicit_url
        else source
    )
    host = parsed.hostname
    if not host:
        raise ValueError(
            "Could not derive a Victure admin "
            "endpoint from this camera URL."
        )

    scheme = (
        parsed.scheme
        if explicit_url
        and parsed.scheme in ("http", "https")
        else "http"
    )
    port = (
        (parsed.port if explicit_url else None)
        or default_port
    )
    netloc = (
        f"[{host}]:{port}"
        if ":" in host
        and not host.startswith("[")
        else f"{host}:{port}"
    )
    return f"{scheme}://{netloc}"


def victure_direct_step_from_speed(speed):
    return max(1, min(256, round(speed * 64)))


def run_victure_direct_ptz_command(
    camera,
    action,
    speed,
    *,
    direct_actions,
    default_port,
):
    if action not in direct_actions:
        return {
            "ok": True,
            "action": action,
            "driver": "victure_direct",
            "warning": (
                "This Victure direct-step driver "
                "only supports directional moves."
            ),
        }

    base_url = victure_direct_target(
        camera,
        default_port=default_port,
    )
    endpoint = f"{base_url}/ptz"
    step = victure_direct_step_from_speed(
        speed
    )
    body = urlencode(
        {"action": action, "step": step}
    ).encode("utf-8")
    request = urllib_request.Request(
        endpoint,
        data=body,
        method="POST",
        headers={
            "Content-Type": (
                "application/x-www-form-urlencoded"
            )
        },
    )

    try:
        with urllib_request.urlopen(
            request, timeout=4
        ) as response:
            response.read(2048)
            status = getattr(
                response, "status", 200
            )
    except urllib_error.HTTPError as exc:
        if exc.code in (
            301,
            302,
            303,
            307,
            308,
        ):
            status = exc.code
            exc.read(2048)
        else:
            raise RuntimeError(
                "Victure direct-step command "
                f"failed: {exc}"
            ) from exc
    except (
        TimeoutError,
        OSError,
        urllib_error.URLError,
    ) as exc:
        raise RuntimeError(
            "Victure direct-step command "
            f"failed: {exc}"
        ) from exc

    return {
        "ok": True,
        "action": action,
        "driver": "victure_direct",
        "endpoint": endpoint,
        "step": step,
        "status": status,
    }


def ptz_url_candidates(camera):
    explicit_url = str(
        camera.get("ptz_url") or ""
    ).strip()
    rtsp_url = str(
        camera.get("rtsp_url") or ""
    ).strip()
    source = explicit_url or rtsp_url
    parsed = urlparse(source)
    credentials = (
        url_credentials(
            urlparse(explicit_url)
        )
        or url_credentials(
            urlparse(rtsp_url)
        )
    )
    candidates = []

    def add(value):
        if value not in candidates:
            candidates.append(value)

    if explicit_url:
        if parsed.path and parsed.path != "/":
            add(clean_control_url(explicit_url))
        else:
            base = (
                f"{parsed.scheme}://"
                f"{netloc_without_credentials(parsed)}"
            )
            for path in (
                "/onvif/ptz_service",
                "/onvif/PTZ",
                "/onvif/ptz",
                "/onvif/device_service",
            ):
                add(f"{base}{path}")
        return candidates, credentials

    host = parsed.hostname
    if not host:
        return [], credentials
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"

    for port in (8080, 80):
        port_suffix = (
            ""
            if port == 80
            else f":{port}"
        )
        for path in (
            "/onvif/ptz_service",
            "/onvif/PTZ",
            "/onvif/ptz",
            "/onvif/device_service",
        ):
            add(
                f"http://{host}"
                f"{port_suffix}{path}"
            )
    return candidates, credentials


def onvif_stop_body(profile_token):
    token = html_escape(
        profile_token, quote=True
    )
    return f"""<tptz:Stop>
      <tptz:ProfileToken>{token}</tptz:ProfileToken>
      <tptz:PanTilt>true</tptz:PanTilt>
      <tptz:Zoom>true</tptz:Zoom>
    </tptz:Stop>"""


def onvif_home_body(profile_token):
    token = html_escape(
        profile_token, quote=True
    )
    return f"""<tptz:GotoHomePosition>
      <tptz:ProfileToken>{token}</tptz:ProfileToken>
    </tptz:GotoHomePosition>"""


def onvif_move_body(
    action,
    speed,
    duration_ms,
    profile_token,
    *,
    move_vectors,
    continuous=False,
):
    x_dir, y_dir, z_dir = move_vectors[action]
    token = html_escape(
        profile_token, quote=True
    )
    velocity = []

    if x_dir or y_dir:
        velocity.append(
            '<tt:PanTilt '
            f'x="{x_dir * speed:.2f}" '
            f'y="{y_dir * speed:.2f}" '
            'space="http://www.onvif.org/ver10/'
            'tptz/PanTiltSpaces/'
            'VelocityGenericSpace"/>'
        )
    if z_dir:
        velocity.append(
            '<tt:Zoom '
            f'x="{z_dir * speed:.2f}" '
            'space="http://www.onvif.org/ver10/'
            'tptz/ZoomSpaces/'
            'VelocityGenericSpace"/>'
        )

    timeout = ""
    if not continuous:
        timeout_seconds = max(
            0.08,
            min(duration_ms / 1000, 1.5),
        )
        timeout = (
            "<tptz:Timeout>"
            f"PT{timeout_seconds:.2f}S"
            "</tptz:Timeout>"
        )

    return f"""<tptz:ContinuousMove>
      <tptz:ProfileToken>{token}</tptz:ProfileToken>
      <tptz:Velocity>{''.join(velocity)}</tptz:Velocity>
      {timeout}
    </tptz:ContinuousMove>"""


def run_ptz_command(
    camera,
    payload,
    *,
    normalize_ptz_type,
    normalize_ptz_speed,
    normalize_bool,
    bounded_int,
    default_ptz_speed,
    default_duration_ms,
    move_vectors,
    run_victure_dvrip,
    run_victure_direct,
    discover_camera_onvif,
    onvif_error,
    normalize_ptz_profile_token,
    onvif_payload_credentials,
    onvif_allowed_endpoint_hosts,
    onvif_soap_post,
    goto_preset_body,
):
    if not camera.get("ptz_enabled"):
        raise ValueError(
            "PTZ is disabled for this camera."
        )

    ptz_type = normalize_ptz_type(
        camera.get("ptz_type")
    )
    if ptz_type == "none":
        raise ValueError(
            "This camera does not have a PTZ "
            "driver configured."
        )

    action = str(
        payload.get("action", "")
    ).strip().lower().replace("-", "_")
    if (
        action not in move_vectors
        and action not in (
            "stop",
            "home",
            "preset",
        )
    ):
        raise ValueError(
            "Unsupported PTZ action."
        )

    speed = normalize_ptz_speed(
        payload.get(
            "speed",
            camera.get(
                "ptz_speed",
                default_ptz_speed,
            ),
        )
    )
    duration_ms = bounded_int(
        payload.get("duration_ms"),
        default_duration_ms,
        80,
        1500,
    )
    continuous = bool(
        normalize_bool(
            payload.get(
                "continuous", False
            )
        )
    )

    if ptz_type == "victure_dvrip":
        if action == "preset":
            raise ValueError(
                "Presets are not supported "
                "by this PTZ driver."
            )
        return run_victure_dvrip(
            camera,
            action,
            speed,
            duration_ms,
        )

    if ptz_type == "victure_direct":
        if action == "preset":
            raise ValueError(
                "Presets are not supported "
                "by this PTZ driver."
            )
        return run_victure_direct(
            camera,
            action,
            speed,
        )

    if ptz_type != "onvif":
        raise ValueError(
            "This camera does not have a supported "
            "PTZ driver configured."
        )

    discovery = camera.get("onvif") or {}
    if not discovery.get("success"):
        try:
            discovery = discover_camera_onvif(
                camera, camera["id"]
            )
        except onvif_error:
            discovery = {}

    if (
        discovery.get("success")
        and discovery.get("ptz_supported")
        is False
    ):
        raise ValueError(
            "This ONVIF camera does not "
            "advertise PTZ support."
        )

    selected_profile = (
        discovery.get("selected_profile")
        or {}
    )
    profile_token = (
        normalize_ptz_profile_token(
            selected_profile.get("token")
            or camera.get(
                "ptz_profile_token"
            )
        )
    )
    discovered_url = (
        discovery.get("services") or {}
    ).get("ptz")
    candidates, legacy_credentials = (
        ptz_url_candidates(camera)
    )
    if discovered_url:
        candidates = [
            discovered_url
        ] + [
            candidate
            for candidate in candidates
            if candidate != discovered_url
        ]

    credentials = (
        onvif_payload_credentials(camera)
        or legacy_credentials
    )
    if not candidates:
        raise ValueError(
            "Could not derive an ONVIF "
            "endpoint from this camera URL."
        )

    allowed_hosts = (
        onvif_allowed_endpoint_hosts(camera)
    )
    features = set(
        discovery.get("features") or []
    )
    if features:
        if (
            action in move_vectors
            and action.startswith("zoom")
            and "zoom" not in features
        ):
            raise ValueError(
                "This camera did not advertise "
                "continuous zoom support."
            )
        if (
            action in move_vectors
            and not action.startswith("zoom")
            and "pt" not in features
        ):
            raise ValueError(
                "This camera did not advertise "
                "continuous pan/tilt support."
            )
        if (
            action == "home"
            and "home" not in features
        ):
            raise ValueError(
                "This camera did not advertise "
                "a home position."
            )
        if (
            action == "preset"
            and "presets" not in features
        ):
            raise ValueError(
                "This camera did not advertise "
                "PTZ presets."
            )

    if action == "stop":
        body = onvif_stop_body(
            profile_token
        )
    elif action == "home":
        body = onvif_home_body(
            profile_token
        )
    elif action == "preset":
        preset_token = str(
            payload.get("preset_token") or ""
        ).strip()
        if not preset_token:
            preset_name = str(
                payload.get("preset_name") or ""
            ).strip()
            preset = next(
                (
                    item
                    for item in (
                        discovery.get("presets")
                        or []
                    )
                    if item.get("name")
                    == preset_name
                ),
                None,
            )
            preset_token = str(
                (preset or {}).get("token")
                or ""
            )
        if not preset_token:
            raise ValueError(
                "Choose a PTZ preset."
            )
        body = goto_preset_body(
            profile_token,
            preset_token,
        )
    else:
        body = onvif_move_body(
            action,
            speed,
            duration_ms,
            profile_token,
            move_vectors=move_vectors,
            continuous=continuous,
        )

    last_error = None
    for url in candidates:
        try:
            onvif_soap_post(
                url,
                body,
                credentials=credentials,
                timeout=4,
                allowed_hosts=allowed_hosts,
            )
            stop_warning = None

            if (
                action in move_vectors
                and not continuous
            ):
                time.sleep(
                    duration_ms / 1000
                )
                try:
                    onvif_soap_post(
                        url,
                        onvif_stop_body(
                            profile_token
                        ),
                        credentials=credentials,
                        timeout=4,
                        allowed_hosts=allowed_hosts,
                    )
                except onvif_error as exc:
                    stop_warning = (
                        "Move sent, but stop "
                        f"failed: {exc}"
                    )

            return {
                "ok": True,
                "action": action,
                "endpoint": (
                    redact_url_credentials(
                        url
                    )
                ),
                "warning": stop_warning,
                "continuous": continuous,
            }
        except onvif_error as exc:
            last_error = exc

    raise RuntimeError(
        f"PTZ command failed: {last_error}"
    )
