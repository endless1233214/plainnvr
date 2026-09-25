import mimetypes
import re
import select
import shutil
import socket
import subprocess
from http import HTTPStatus
from urllib import error as urllib_error, request as urllib_request
from urllib.parse import parse_qs, quote, unquote, urlencode, urlparse


def do_GET(handler, app):
    parsed = urlparse(handler.path)
    if not handler.ensure_authorized(parsed):
        return

    if (
        parsed.path == "/login.html"
        and handler.auth_user()
        and not app.setup_required()
    ):
        handler.redirect("/")
        return

    if parsed.path.startswith("/api/"):
        handler.handle_api_get(parsed)
        return
    if parsed.path.startswith("/go2rtc/"):
        handler.handle_go2rtc_proxy(parsed)
        return
    if parsed.path.startswith("/ha/"):
        handler.handle_home_assistant(parsed)
        return
    if parsed.path.startswith("/live/"):
        handler.handle_live_hls(parsed)
        return
    if parsed.path.startswith("/media/"):
        handler.handle_media(parsed.path)
        return
    handler.serve_static(parsed.path)


def do_HEAD(handler, app):
    parsed = urlparse(handler.path)
    if not handler.ensure_authorized(parsed):
        return

    if parsed.path.startswith("/ha/"):
        handler.handle_home_assistant_head(parsed)
        return
    if parsed.path.startswith("/live/"):
        handler.handle_live_hls_head(parsed)
        return
    if parsed.path.startswith("/media/"):
        handler.handle_media(
            parsed.path,
            head_only=True,
        )
        return
    if parsed.path.startswith("/api/"):
        handler.send_response(
            HTTPStatus.METHOD_NOT_ALLOWED
        )
        handler.send_header(
            "Content-Length", "0"
        )
        handler.end_headers()
        return
    if parsed.path.startswith("/go2rtc/"):
        handler.handle_go2rtc_proxy(
            parsed,
            head_only=True,
        )
        return
    handler.serve_static(
        parsed.path,
        head_only=True,
    )


def do_POST(handler, app):
    if not handler.ensure_same_origin():
        return

    parsed = urlparse(handler.path)
    if not handler.ensure_authorized(parsed):
        return

    if (
        parsed.path
        in (
            "/api/auth/login",
            "/api/auth/setup",
        )
        and not app.login_limiter.allow(
            handler.client_address[0]
        )
    ):
        handler.send_json(
            {
                "error": (
                    "Too many login attempts. "
                    "Try again in a minute."
                )
            },
            HTTPStatus.TOO_MANY_REQUESTS,
            headers={"Retry-After": "60"},
        )
        return

    try:
        payload = app.parse_json_body(handler)
    except ValueError as exc:
        handler.send_error_json(
            HTTPStatus.BAD_REQUEST,
            str(exc),
        )
        return

    if parsed.path == "/api/auth/setup":
        handler.handle_auth_setup(payload)
        return
    if parsed.path == "/api/auth/login":
        handler.handle_auth_login(payload)
        return
    if parsed.path == "/api/auth/logout":
        app.delete_session(
            handler.session_id()
        )
        handler.send_json(
            {"ok": True},
            headers={
                "Set-Cookie": (
                    handler.expired_session_cookie()
                )
            },
        )
        return

    if parsed.path == "/api/cameras":
        try:
            camera = app.create_camera(payload)
        except ValueError as exc:
            handler.send_error_json(
                HTTPStatus.BAD_REQUEST,
                str(exc),
            )
            return
        handler.send_json(
            camera,
            HTTPStatus.CREATED,
        )
        return

    if parsed.path == "/api/onvif/discover":
        handler.handle_onvif_discovery(
            payload
        )
        return

    match = re.match(
        (
            r"^/api/cameras/([a-f0-9]+)/"
            r"(onvif/discover|compatibility)$"
        ),
        parsed.path,
    )
    if match:
        if match.group(2) == "onvif/discover":
            handler.handle_camera_onvif_discovery(
                match.group(1),
                payload,
            )
        else:
            handler.handle_camera_compatibility(
                match.group(1)
            )
        return

    match = re.match(
        r"^/api/cameras/([a-f0-9]+)/ptz$",
        parsed.path,
    )
    if match:
        handler.handle_camera_ptz(
            match.group(1),
            payload,
        )
        return

    match = re.match(
        r"^/api/cameras/([a-f0-9]+)/time$",
        parsed.path,
    )
    if match:
        handler.handle_camera_time(
            match.group(1),
            payload,
        )
        return

    match = re.match(
        (
            r"^/api/cameras/([a-f0-9]+)/"
            r"(recorder|live)/(start|stop|restart)$"
        ),
        parsed.path,
    )
    if match:
        handler.handle_camera_control(
            match.group(1),
            match.group(2),
            match.group(3),
        )
        return

    if parsed.path == "/api/test-stream":
        try:
            handler.send_json(
                app.test_stream(payload)
            )
        except ValueError as exc:
            handler.send_error_json(
                HTTPStatus.BAD_REQUEST,
                str(exc),
            )
        return

    if parsed.path == "/api/users":
        try:
            username = app.create_user(
                payload.get("username"),
                payload.get("password"),
            )
        except ValueError as exc:
            handler.send_error_json(
                HTTPStatus.BAD_REQUEST,
                str(exc),
            )
            return
        handler.send_json(
            {
                "ok": True,
                "username": username,
            },
            HTTPStatus.CREATED,
        )
        return

    handler.send_error_json(
        HTTPStatus.NOT_FOUND,
        "Not found.",
    )


def do_PUT(handler, app):
    if not handler.ensure_same_origin():
        return

    parsed = urlparse(handler.path)
    if not handler.ensure_authorized(parsed):
        return

    try:
        payload = app.parse_json_body(handler)
    except ValueError as exc:
        handler.send_error_json(
            HTTPStatus.BAD_REQUEST,
            str(exc),
        )
        return

    if parsed.path == "/api/settings":
        previous = app.get_app_settings()
        try:
            settings = app.update_app_settings(
                payload
            )
        except ValueError as exc:
            handler.send_error_json(
                HTTPStatus.BAD_REQUEST,
                str(exc),
            )
            return

        if (
            settings["log_level"]
            != previous["log_level"]
        ):
            app.go2rtc.shutdown()
            with app.go2rtc.lock:
                app.go2rtc.stream_keys.clear()
                app.go2rtc.media_states.clear()
            app.go2rtc.start(
                app.list_cameras()
            )

        handler.send_json(
            {"settings": settings}
        )
        return

    match = re.match(
        r"^/api/cameras/([a-f0-9]+)$",
        parsed.path,
    )
    if match:
        try:
            camera = app.update_camera(
                match.group(1),
                payload,
            )
        except ValueError as exc:
            handler.send_error_json(
                HTTPStatus.BAD_REQUEST,
                str(exc),
            )
            return

        if not camera:
            handler.send_error_json(
                HTTPStatus.NOT_FOUND,
                "Camera not found.",
            )
            return
        handler.send_json(camera)
        return

    handler.send_error_json(
        HTTPStatus.NOT_FOUND,
        "Not found.",
    )


def do_DELETE(handler, app):
    if not handler.ensure_same_origin():
        return

    parsed = urlparse(handler.path)
    if not handler.ensure_authorized(parsed):
        return

    match = re.match(
        r"^/api/cameras/([a-f0-9]+)$",
        parsed.path,
    )
    if match:
        if app.delete_camera(match.group(1)):
            handler.send_json({"ok": True})
        else:
            handler.send_error_json(
                HTTPStatus.NOT_FOUND,
                "Camera not found.",
            )
        return

    match = re.match(
        r"^/api/users/([^/]+)$",
        parsed.path,
    )
    if match:
        try:
            deleted = app.delete_user(
                match.group(1),
                handler.auth_user(),
            )
        except ValueError as exc:
            handler.send_error_json(
                HTTPStatus.BAD_REQUEST,
                str(exc),
            )
            return

        if deleted:
            handler.send_json({"ok": True})
        else:
            handler.send_error_json(
                HTTPStatus.NOT_FOUND,
                "User not found.",
            )
        return

    handler.send_error_json(
        HTTPStatus.NOT_FOUND,
        "Not found.",
    )


def handle_auth_setup(handler, app, payload):
    if not app.setup_required():
        handler.send_error_json(
            HTTPStatus.CONFLICT,
            "Admin account already exists.",
        )
        return

    try:
        username = app.create_user(
            payload.get("username"),
            payload.get("password"),
            initial_setup=True,
        )
    except ValueError as exc:
        handler.send_error_json(
            HTTPStatus.BAD_REQUEST,
            str(exc),
        )
        return

    session_id = app.create_session(username)
    handler.send_json(
        {
            "ok": True,
            "username": username,
        },
        HTTPStatus.CREATED,
        headers={
            "Set-Cookie": (
                handler.session_cookie(
                    session_id
                )
            )
        },
    )


def handle_auth_login(handler, app, payload):
    username = app.authenticate_user(
        payload.get("username"),
        payload.get("password"),
    )
    if not username:
        handler.send_error_json(
            HTTPStatus.UNAUTHORIZED,
            "Invalid username or password.",
        )
        return

    session_id = app.create_session(username)
    handler.send_json(
        {
            "ok": True,
            "username": username,
        },
        headers={
            "Set-Cookie": (
                handler.session_cookie(
                    session_id
                )
            )
        },
    )


def handle_camera_control(
    handler,
    app,
    camera_id,
    target,
    action,
):
    camera = app.get_camera(camera_id)
    if not camera:
        handler.send_error_json(
            HTTPStatus.NOT_FOUND,
            "Camera not found.",
        )
        return

    if target == "recorder":
        handler.handle_recorder_control(
            camera,
            action,
        )
        return
    handler.handle_live_control(
        camera,
        action,
    )


def handle_recorder_control(
    handler,
    app,
    camera,
    action,
):
    if action == "stop":
        app.recorder.pause(camera["id"])
    elif action == "start":
        if not camera["enabled"]:
            handler.send_error_json(
                HTTPStatus.CONFLICT,
                "Camera is disabled.",
            )
            return
        app.recorder.resume(camera)
    elif action == "restart":
        if not camera["enabled"]:
            handler.send_error_json(
                HTTPStatus.CONFLICT,
                "Camera is disabled.",
            )
            return
        app.recorder.restart_now(camera)

    handler.send_json(
        {
            "ok": True,
            "recorders": (
                app.recorder.status()
            ),
            "events": (
                app.get_recent_events()
            ),
        }
    )


def handle_live_control(
    handler,
    app,
    camera,
    action,
):
    handler.send_json(
        {
            "ok": True,
            "scope": "viewer",
        }
    )


def handle_camera_ptz(
    handler,
    app,
    camera_id,
    payload,
):
    camera = app.get_camera(camera_id)
    if not camera:
        handler.send_error_json(
            HTTPStatus.NOT_FOUND,
            "Camera not found.",
        )
        return

    try:
        result = app.run_ptz_command(
            camera,
            payload,
        )
    except ValueError as exc:
        handler.send_error_json(
            HTTPStatus.BAD_REQUEST,
            str(exc),
        )
        return
    except RuntimeError as exc:
        handler.send_error_json(
            HTTPStatus.BAD_GATEWAY,
            app.redact_camera_text(
                str(exc),
                camera,
            ),
        )
        return
    handler.send_json(result)


def handle_onvif_discovery(
    handler,
    app,
    payload,
):
    rtsp_url = str(
        payload.get("rtsp_url") or ""
    ).strip()
    onvif_url = str(
        payload.get("onvif_url") or ""
    ).strip()
    ptz_url = str(
        payload.get("ptz_url") or ""
    ).strip()

    if (
        not rtsp_url
        and not onvif_url
        and not ptz_url
    ):
        handler.send_error_json(
            HTTPStatus.BAD_REQUEST,
            (
                "Enter a stream URL or "
                "ONVIF device URL first."
            ),
        )
        return

    try:
        result = app.discover_camera_onvif(
            payload
        )
    except app.OnvifError as exc:
        handler.send_error_json(
            HTTPStatus.BAD_GATEWAY,
            str(exc),
        )
        return
    handler.send_json(result)


def handle_camera_onvif_discovery(
    handler,
    app,
    camera_id,
    payload=None,
):
    camera = app.get_camera(camera_id)
    if not camera:
        handler.send_error_json(
            HTTPStatus.NOT_FOUND,
            "Camera not found.",
        )
        return

    try:
        result = app.discover_camera_onvif(
            {
                **camera,
                **(payload or {}),
            },
            camera_id,
        )
    except app.OnvifError as exc:
        handler.send_error_json(
            HTTPStatus.BAD_GATEWAY,
            app.redact_camera_text(
                str(exc),
                camera,
            ),
        )
        return
    handler.send_json(result)


def handle_camera_compatibility(
    handler,
    app,
    camera_id,
    download=False,
):
    camera = app.get_camera(camera_id)
    if not camera:
        handler.send_error_json(
            HTTPStatus.NOT_FOUND,
            "Camera not found.",
        )
        return

    report = app.camera_compatibility_report(
        camera,
        refresh_onvif=True,
    )
    headers = None
    if download:
        headers = {
            "Content-Disposition": (
                "attachment; filename="
                f'"plainnvr-{camera["slug"]}-'
                'compatibility.json"'
            )
        }

    handler.send_json(
        report,
        headers=headers,
        indent=2 if download else None,
    )


def handle_camera_time(
    handler,
    app,
    camera_id,
    payload=None,
):
    camera = app.get_camera(camera_id)
    if not camera:
        handler.send_error_json(
            HTTPStatus.NOT_FOUND,
            "Camera not found.",
        )
        return

    try:
        result = app.camera_time(
            camera,
            (
                None
                if payload is None
                else payload.get("time")
            ),
        )
    except ValueError as exc:
        handler.send_error_json(
            HTTPStatus.BAD_REQUEST,
            str(exc),
        )
        return
    except RuntimeError as exc:
        handler.send_error_json(
            HTTPStatus.BAD_GATEWAY,
            app.redact_camera_text(
                str(exc),
                camera,
            ),
        )
        return
    handler.send_json(result)


def handle_api_get(handler, app, parsed):
    query = parse_qs(parsed.query)

    if parsed.path == "/api/health":
        handler.send_json(
            {
                "ok": True,
                "now": app.iso_now(),
            }
        )
        return

    if parsed.path == "/api/auth/state":
        username = handler.auth_user()
        handler.send_json(
            {
                "authenticated": bool(
                    username
                ),
                "setup_required": (
                    app.setup_required()
                ),
                "username": username,
            }
        )
        return

    if parsed.path == "/api/cameras":
        handler.send_json(
            {
                "cameras": (
                    app.list_cameras()
                )
            }
        )
        return

    if parsed.path == "/api/settings":
        handler.send_json(
            {
                "settings": (
                    app.get_app_settings()
                )
            }
        )
        return

    match = re.match(
        r"^/api/cameras/([a-f0-9]+)/time$",
        parsed.path,
    )
    if match:
        handler.handle_camera_time(
            match.group(1)
        )
        return

    match = re.match(
        (
            r"^/api/cameras/([a-f0-9]+)/"
            r"live/diagnostics$"
        ),
        parsed.path,
    )
    if match:
        camera = app.get_camera(
            match.group(1)
        )
        if not camera:
            handler.send_error_json(
                HTTPStatus.NOT_FOUND,
                "Camera not found.",
            )
            return

        handler.send_json(
            app.live_diagnostics(
                camera,
                include_audio=app.query_bool(
                    query,
                    "audio",
                    default=True,
                ),
            )
        )
        return

    match = re.match(
        (
            r"^/api/cameras/([a-f0-9]+)/"
            r"compatibility-report$"
        ),
        parsed.path,
    )
    if match:
        handler.handle_camera_compatibility(
            match.group(1),
            download=True,
        )
        return

    if parsed.path == "/api/status":
        cameras = app.list_cameras()
        states = app.recorder.status()
        handler.send_json(
            {
                "cameras": cameras,
                "recorders": states,
                "disk": app.disk_status(),
                "events": (
                    app.get_recent_events()
                ),
                "stream_token": (
                    app.get_stream_token()
                ),
                "relays": (
                    app.relay.status(cameras)
                ),
                "go2rtc": (
                    app.go2rtc.status()
                ),
                "night_modes": (
                    app.night_modes.status()
                ),
                "settings": (
                    app.get_app_settings()
                ),
                "users": app.list_users(),
                "username": (
                    handler.auth_user()
                ),
                "now": app.iso_now(),
            }
        )
        return

    if parsed.path == "/api/coverage":
        camera_id = query.get(
            "camera_id", [""]
        )[0]
        camera = app.get_camera(camera_id)
        if not camera:
            handler.send_error_json(
                HTTPStatus.NOT_FOUND,
                "Camera not found.",
            )
            return
        handler.send_json(
            {
                "coverage": (
                    app.recording_coverage(
                        camera
                    )
                )
            }
        )
        return

    if parsed.path == "/api/segments":
        camera_id = query.get(
            "camera_id", [""]
        )[0]
        date_value = (
            query.get("date", [""])[0]
            or None
        )
        camera = app.get_camera(camera_id)
        if not camera:
            handler.send_error_json(
                HTTPStatus.NOT_FOUND,
                "Camera not found.",
            )
            return
        handler.send_json(
            {
                "segments": (
                    app.scan_segments(
                        camera,
                        date_value,
                    )
                )
            }
        )
        return

    handler.send_error_json(
        HTTPStatus.NOT_FOUND,
        "Not found.",
    )


def handle_go2rtc_proxy(
    handler,
    app,
    parsed,
    head_only=False,
):
    if not app.go2rtc.running():
        handler.send_error_json(
            HTTPStatus.SERVICE_UNAVAILABLE,
            "go2rtc is unavailable.",
        )
        return

    query = parse_qs(
        parsed.query,
        keep_blank_values=True,
    )
    source = query.get("src", [""])
    match = (
        re.fullmatch(
            r"plainnvr_([a-f0-9]+)",
            source[0],
        )
        if len(source) == 1
        else None
    )
    if (
        parsed.path != "/go2rtc/api/ws"
        or set(query) != {"src"}
        or not match
    ):
        handler.send_error_json(
            HTTPStatus.NOT_FOUND,
            "Not found.",
        )
        return

    camera = app.get_camera(
        match.group(1)
    )
    if (
        not camera
        or not camera.get("enabled")
    ):
        handler.send_error_json(
            HTTPStatus.NOT_FOUND,
            "Camera not found.",
        )
        return

    if not handler.ensure_same_origin():
        return

    if (
        not app.go2rtc.can_restream(camera)
        or not app.go2rtc.configure_camera(
            camera
        )
    ):
        handler.send_error_json(
            HTTPStatus.SERVICE_UNAVAILABLE,
            "Stream unavailable.",
        )
        return

    upstream_path = (
        "/api/ws?"
        + urlencode(
            {"src": source[0]}
        )
    )
    if (
        handler.headers.get(
            "Upgrade", ""
        ).lower()
        == "websocket"
        and not head_only
    ):
        handler.proxy_go2rtc_websocket(
            upstream_path
        )
        return

    handler.send_error_json(
        HTTPStatus.BAD_REQUEST,
        "WebSocket upgrade required.",
    )


def proxy_go2rtc_websocket(
    handler,
    app,
    upstream_path,
):
    upstream = None
    response_sent = False

    try:
        upstream = socket.create_connection(
            (
                app.GO2RTC_API_HOST,
                app.GO2RTC_API_PORT,
            ),
            timeout=10,
        )
        headers = [
            (
                f"GET {upstream_path} "
                "HTTP/1.1"
            ),
            (
                "Host: "
                f"{app.GO2RTC_API_HOST}:"
                f"{app.GO2RTC_API_PORT}"
            ),
            "Connection: Upgrade",
            "Upgrade: websocket",
        ]
        for key in (
            "Sec-WebSocket-Key",
            "Sec-WebSocket-Version",
            "Sec-WebSocket-Protocol",
            "Sec-WebSocket-Extensions",
            "Origin",
            "User-Agent",
        ):
            value = handler.headers.get(key)
            if value:
                headers.append(
                    f"{key}: {value}"
                )

        upstream.sendall(
            (
                "\r\n".join(headers)
                + "\r\n\r\n"
            ).encode("latin-1")
        )

        response = bytearray()
        while (
            b"\r\n\r\n"
            not in response
            and len(response) < 64 * 1024
        ):
            chunk = upstream.recv(4096)
            if not chunk:
                break
            response.extend(chunk)

        if not response:
            raise RuntimeError(
                "go2rtc closed the "
                "WebSocket handshake."
            )

        handler.connection.sendall(
            response
        )
        response_sent = True
        status_line = bytes(
            response
        ).split(b"\r\n", 1)[0]
        if b" 101 " not in status_line:
            return

        handler.close_connection = True
        upstream.settimeout(None)
        handler.connection.settimeout(None)
        sockets = (
            handler.connection,
            upstream,
        )

        while True:
            readable, _, exceptional = (
                select.select(
                    sockets,
                    [],
                    sockets,
                    30,
                )
            )
            if exceptional:
                break
            if not readable:
                continue

            for source in readable:
                data = source.recv(
                    64 * 1024
                )
                if not data:
                    return
                target = (
                    upstream
                    if source
                    is handler.connection
                    else handler.connection
                )
                target.sendall(data)

    except (
        OSError,
        RuntimeError,
    ) as exc:
        if not response_sent:
            handler.send_error_json(
                HTTPStatus.BAD_GATEWAY,
                (
                    "go2rtc WebSocket "
                    f"proxy failed: {exc}"
                ),
            )
    finally:
        if upstream:
            try:
                upstream.close()
            except OSError:
                pass


def handle_home_assistant(
    handler,
    app,
    parsed,
):
    match = re.match(
        (
            r"^/ha/([a-f0-9]+)/"
            r"(snapshot\.jpg|stream\.mjpeg)$"
        ),
        parsed.path,
    )
    if not match:
        handler.send_error(
            HTTPStatus.NOT_FOUND
        )
        return

    if not app.home_assistant_enabled():
        handler.send_error(
            HTTPStatus.NOT_FOUND,
            (
                "Home Assistant bridge "
                "is disabled."
            ),
        )
        return

    camera = app.get_camera(
        match.group(1)
    )
    if not camera:
        handler.send_error(
            HTTPStatus.NOT_FOUND
        )
        return

    query = parse_qs(parsed.query)
    if match.group(2) == "snapshot.jpg":
        handler.handle_snapshot(
            camera,
            grayscale=app.query_bool(
                query,
                "grayscale",
            ),
        )
        return

    handler.send_error(
        HTTPStatus.GONE,
        (
            "MJPEG live streaming is disabled. "
            "Use the go2rtc-backed HLS URL "
            "under /live/."
        ),
    )


def handle_home_assistant_head(
    handler,
    app,
    parsed,
):
    match = re.match(
        (
            r"^/ha/([a-f0-9]+)/"
            r"(snapshot\.jpg|stream\.mjpeg)$"
        ),
        parsed.path,
    )
    if (
        not match
        or not app.home_assistant_enabled()
    ):
        handler.send_response(
            HTTPStatus.NOT_FOUND
        )
        handler.send_header(
            "Content-Length", "0"
        )
        handler.end_headers()
        return

    if not app.get_camera(match.group(1)):
        handler.send_response(
            HTTPStatus.NOT_FOUND
        )
        handler.send_header(
            "Content-Length", "0"
        )
        handler.end_headers()
        return

    if match.group(2) == "snapshot.jpg":
        handler.send_response(
            HTTPStatus.OK
        )
        handler.send_header(
            "Content-Type",
            "image/jpeg",
        )
    else:
        handler.send_response(
            HTTPStatus.GONE
        )
        handler.send_header(
            "Content-Type",
            "text/plain; charset=utf-8",
        )

    handler.send_header(
        "Cache-Control", "no-store"
    )
    handler.send_header(
        "Content-Length", "0"
    )
    handler.end_headers()


def handle_live_hls(
    handler,
    app,
    parsed,
    head_only=False,
):
    match = re.match(
        (
            r"^/live/([a-f0-9]+)/"
            r"(stream\.m3u8|hls/"
            r"(?:playlist\.m3u8|init\.mp4|"
            r"segment\.(?:ts|m4s)))$"
        ),
        parsed.path,
    )
    if not match:
        handler.send_error(
            HTTPStatus.NOT_FOUND
        )
        return

    camera = app.get_camera(
        match.group(1)
    )
    if not camera:
        handler.send_error(
            HTTPStatus.NOT_FOUND
        )
        return

    token = parse_qs(
        parsed.query
    ).get("token", [""])[0]

    if match.group(2) == "stream.m3u8":
        if (
            not app.go2rtc.can_restream(
                camera
            )
            or not app.go2rtc.configure_camera(
                camera
            )
        ):
            handler.send_error(
                HTTPStatus.SERVICE_UNAVAILABLE,
                (
                    "go2rtc stream "
                    "is unavailable."
                ),
            )
            return

        upstream_path = (
            "/api/stream.m3u8?"
            + urlencode(
                {
                    "src": (
                        app.go2rtc.stream_name(
                            camera
                        )
                    )
                }
            )
        )
    else:
        rest = match.group(2)[
            len("hls/") :
        ]
        query = parse_qs(
            parsed.query,
            keep_blank_values=True,
        )
        query.pop("token", None)
        upstream_path = (
            f"/api/hls/{rest}"
        )
        encoded_query = urlencode(
            query,
            doseq=True,
        )
        if encoded_query:
            upstream_path = (
                f"{upstream_path}?"
                f"{encoded_query}"
            )

    handler.proxy_go2rtc_live_hls(
        upstream_path,
        camera["id"],
        token,
        head_only=head_only,
    )


def handle_live_hls_head(
    handler,
    app,
    parsed,
):
    handler.handle_live_hls(
        parsed,
        head_only=True,
    )


def proxy_go2rtc_live_hls(
    handler,
    app,
    upstream_path,
    camera_id,
    token="",
    head_only=False,
):
    headers = {
        "Accept": handler.headers.get(
            "Accept", "*/*"
        )
    }
    if handler.headers.get("Range"):
        headers["Range"] = (
            handler.headers["Range"]
        )

    request = urllib_request.Request(
        (
            "http://"
            f"{app.GO2RTC_API_HOST}:"
            f"{app.GO2RTC_API_PORT}"
            f"{upstream_path}"
        ),
        headers=headers,
        method=(
            "HEAD"
            if head_only
            else "GET"
        ),
    )

    try:
        response = urllib_request.urlopen(
            request,
            timeout=10,
        )
    except urllib_error.HTTPError as exc:
        response = exc
    except (
        OSError,
        urllib_error.URLError,
    ) as exc:
        handler.send_error(
            HTTPStatus.BAD_GATEWAY,
            (
                "go2rtc HLS proxy "
                f"failed: {exc}"
            ),
        )
        return

    with response:
        content_type = response.headers.get(
            "Content-Type", ""
        )
        is_playlist = (
            "mpegurl" in content_type
            or upstream_path.split(
                "?", 1
            )[0].endswith(".m3u8")
        )
        if (
            is_playlist
            and response.status
            == HTTPStatus.OK
            and not head_only
        ):
            text = response.read().decode(
                "utf-8", "replace"
            )
            handler.send_go2rtc_live_playlist(
                text,
                camera_id,
                token,
            )
            return

        handler.send_response(
            response.status
        )
        for key in (
            "Content-Type",
            "Content-Length",
            "Content-Range",
            "Accept-Ranges",
            "Cache-Control",
            "Retry-After",
        ):
            value = response.headers.get(key)
            if value:
                handler.send_header(
                    key,
                    value,
                )

        handler.send_header(
            "X-Content-Type-Options",
            "nosniff",
        )
        handler.end_headers()

        if not head_only:
            shutil.copyfileobj(
                response,
                handler.wfile,
                length=64 * 1024,
            )


def send_go2rtc_live_playlist(
    handler,
    app,
    text,
    camera_id,
    token="",
):
    def rewrite_uri(uri):
        if re.match(
            (
                r"^[a-zA-Z]"
                r"[a-zA-Z0-9+.-]*://"
            ),
            uri,
        ):
            return uri

        if uri.startswith("/api/hls/"):
            uri = uri[
                len("/api/hls/") :
            ]
        elif uri.startswith("hls/"):
            uri = uri[
                len("hls/") :
            ]

        uri = (
            f"/live/{camera_id}/"
            f"hls/{uri}"
        )
        if token:
            separator = (
                "&"
                if "?" in uri
                else "?"
            )
            uri = (
                f"{uri}{separator}"
                f"token={quote(token)}"
            )
        return uri

    lines = []
    for line in text.splitlines():
        if (
            line.startswith("#")
            and 'URI="' in line
        ):
            line = re.sub(
                r'URI="([^"]+)"',
                lambda match: (
                    'URI="'
                    + rewrite_uri(
                        match.group(1)
                    )
                    + '"'
                ),
                line,
            )
            lines.append(line)
        elif (
            not line
            or line.startswith("#")
        ):
            lines.append(line)
        else:
            lines.append(
                rewrite_uri(
                    line.strip()
                )
            )

    text = "\n".join(lines) + "\n"
    payload = text.encode("utf-8")
    handler.send_response(HTTPStatus.OK)
    handler.send_header(
        "Content-Type",
        "application/vnd.apple.mpegurl",
    )
    handler.send_header(
        "Content-Length",
        str(len(payload)),
    )
    handler.send_header(
        "Cache-Control",
        "no-store",
    )
    handler.end_headers()
    handler.wfile.write(payload)


def handle_snapshot(
    handler,
    app,
    camera,
    grayscale=False,
):
    try:
        result = subprocess.run(
            app.build_snapshot_command(
                camera,
                grayscale=grayscale,
            ),
            capture_output=True,
            timeout=20,
        )
    except RuntimeError as exc:
        handler.send_error(
            HTTPStatus.BAD_GATEWAY,
            app.redact_camera_text(
                str(exc),
                camera,
            ),
        )
        return
    except subprocess.TimeoutExpired:
        handler.send_error(
            HTTPStatus.GATEWAY_TIMEOUT,
            "Snapshot timed out.",
        )
        return

    if (
        result.returncode != 0
        or not result.stdout
    ):
        message = (
            result.stderr.decode(
                "utf-8",
                "replace",
            )
            .strip()
            .splitlines()
        )
        handler.send_error(
            HTTPStatus.BAD_GATEWAY,
            (
                message[-1]
                if message
                else "Snapshot failed."
            ),
        )
        return

    handler.send_response(HTTPStatus.OK)
    handler.send_header(
        "Content-Type",
        "image/jpeg",
    )
    handler.send_header(
        "Content-Length",
        str(len(result.stdout)),
    )
    handler.send_header(
        "Cache-Control",
        "no-store",
    )
    handler.end_headers()
    try:
        handler.wfile.write(
            result.stdout
        )
    except (
        BrokenPipeError,
        ConnectionResetError,
    ):
        pass


def handle_media(
    handler,
    app,
    path,
    head_only=False,
):
    parts = path.split("/")
    if len(parts) != 4:
        handler.send_error(
            HTTPStatus.NOT_FOUND
        )
        return

    camera_id = parts[2]
    filename = unquote(parts[3])
    if not app.SEGMENT_RE.match(filename):
        handler.send_error(
            HTTPStatus.NOT_FOUND
        )
        return

    camera = app.get_camera(camera_id)
    if not camera:
        handler.send_error(
            HTTPStatus.NOT_FOUND
        )
        return

    target = (
        app.camera_dir(camera)
        / filename
    ).resolve()
    root = app.camera_dir(
        camera
    ).resolve()
    if (
        root not in target.parents
        or not target.exists()
    ):
        handler.send_error(
            HTTPStatus.NOT_FOUND
        )
        return

    size = target.stat().st_size
    start = 0
    end = size - 1
    status = HTTPStatus.OK

    range_header = handler.headers.get(
        "Range"
    )
    if range_header:
        match = re.fullmatch(
            r"bytes=(\d*)-(\d*)",
            range_header,
        )
        if (
            not match
            or not any(match.groups())
        ):
            match = None

        if match:
            first, last = match.groups()
            if first:
                start = int(first)
                end = (
                    min(
                        int(last),
                        size - 1,
                    )
                    if last
                    else size - 1
                )
            else:
                start = max(
                    0,
                    size - int(last),
                )

            if (
                start >= size
                or start > end
            ):
                handler.send_response(
                    HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE
                )
                handler.send_header(
                    "Content-Range",
                    f"bytes */{size}",
                )
                handler.send_header(
                    "Content-Length",
                    "0",
                )
                handler.end_headers()
                return
            status = (
                HTTPStatus.PARTIAL_CONTENT
            )

    handler.send_response(status)
    handler.send_header(
        "Content-Type",
        "video/mp4",
    )
    handler.send_header(
        "Content-Length",
        str(end - start + 1),
    )
    handler.send_header(
        "Accept-Ranges",
        "bytes",
    )
    if status == HTTPStatus.PARTIAL_CONTENT:
        handler.send_header(
            "Content-Range",
            (
                f"bytes {start}-{end}/"
                f"{size}"
            ),
        )
    handler.end_headers()

    if head_only:
        return

    with target.open("rb") as src:
        src.seek(start)
        remaining = end - start + 1
        while remaining > 0:
            chunk = src.read(
                min(
                    1024 * 1024,
                    remaining,
                )
            )
            if not chunk:
                break
            handler.wfile.write(chunk)
            remaining -= len(chunk)


def serve_static(
    handler,
    app,
    path,
    head_only=False,
):
    if path in ("", "/"):
        path = "/index.html"

    target = (
        app.STATIC_DIR
        / path.lstrip("/")
    ).resolve()
    root = app.STATIC_DIR.resolve()

    if (
        root not in target.parents
        and target != root
    ):
        handler.send_error(
            HTTPStatus.NOT_FOUND
        )
        return
    if (
        not target.exists()
        or not target.is_file()
    ):
        handler.send_error(
            HTTPStatus.NOT_FOUND
        )
        return

    content_type = (
        mimetypes.guess_type(
            str(target)
        )[0]
        or "application/octet-stream"
    )
    handler.send_response(HTTPStatus.OK)
    handler.send_header(
        "Content-Type",
        content_type,
    )
    handler.send_header(
        "Content-Length",
        str(target.stat().st_size),
    )
    handler.end_headers()

    if head_only:
        return

    with target.open("rb") as src:
        shutil.copyfileobj(
            src,
            handler.wfile,
        )
