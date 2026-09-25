import json
import re
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler
from urllib.parse import urlparse

try:
    from app import http_api
except ModuleNotFoundError:
    import http_api


class NvrHandler(SimpleHTTPRequestHandler):
    server_version = "PlainNVR/0.1"
    app = None

    def setup(self):
        super().setup()
        self.connection.settimeout(30)

    def ensure_same_origin(self):
        origin = self.headers.get("Origin")
        if origin:
            parsed = urlparse(origin)
            if (
                parsed.scheme not in ("http", "https")
                or parsed.netloc.lower()
                != self.headers.get(
                    "Host", ""
                ).lower()
            ):
                self.send_error_json(
                    HTTPStatus.FORBIDDEN,
                    "Cross-origin request denied.",
                )
                return False

        if (
            self.headers.get("Sec-Fetch-Site")
            == "cross-site"
        ):
            self.send_error_json(
                HTTPStatus.FORBIDDEN,
                "Cross-site request denied.",
            )
            return False
        return True

    def end_headers(self):
        self.send_header(
            "X-Frame-Options",
            "DENY",
        )
        self.send_header(
            "Content-Security-Policy",
            (
                "frame-ancestors 'none'; "
                "base-uri 'self'"
            ),
        )
        self.send_header(
            "Referrer-Policy",
            "same-origin",
        )
        super().end_headers()

    def log_message(self, fmt, *args):
        message = fmt % args
        message = re.sub(
            r"([?&]token=)[^\s&]+",
            r"\1<redacted>",
            message,
        )
        print(
            f"{self.address_string()} - "
            f"{message}"
        )

    def send_json(
        self,
        value,
        status=HTTPStatus.OK,
        headers=None,
        indent=None,
    ):
        data = json.dumps(
            value,
            indent=indent,
        ).encode("utf-8")
        self.send_response(status)
        self.send_header(
            "Content-Type",
            "application/json; charset=utf-8",
        )
        self.send_header(
            "Content-Length",
            str(len(data)),
        )
        self.send_header(
            "X-Content-Type-Options",
            "nosniff",
        )
        self.send_header(
            "Cache-Control",
            "no-store",
        )
        for key, header_value in (
            headers or {}
        ).items():
            self.send_header(
                key,
                header_value,
            )
        self.end_headers()
        if (
            getattr(
                self,
                "command",
                "GET",
            )
            != "HEAD"
        ):
            self.wfile.write(data)

    def send_error_json(
        self,
        status,
        message,
    ):
        self.send_json(
            {"error": message},
            status,
        )

    def session_id(self):
        return self.app.parse_cookie_header(
            self.headers.get("Cookie", "")
        ).get(
            self.app.AUTH_COOKIE_NAME,
            "",
        )

    def auth_user(self):
        if not hasattr(
            self,
            "_auth_user",
        ):
            self._auth_user = (
                self.app.current_session_user(
                    self.session_id()
                )
            )
        return self._auth_user

    def is_public_path(self, parsed):
        public_paths = {
            "/login.html",
            "/styles.css",
            "/favicon.ico",
            "/api/health",
            "/api/auth/state",
            "/api/auth/login",
            "/api/auth/setup",
        }
        return parsed.path in public_paths

    def ensure_authorized(self, parsed):
        if self.is_public_path(parsed):
            return True

        if parsed.path.startswith(
            (
                "/ha/",
                "/live/",
                "/media/",
            )
        ):
            if self.app.valid_stream_auth(
                self,
                parsed,
            ):
                return True
            if parsed.path.startswith("/ha/"):
                self.send_basic_auth_required()
                return False

        if self.auth_user():
            return True

        if parsed.path.startswith("/api/"):
            self.send_error_json(
                HTTPStatus.UNAUTHORIZED,
                "Authentication required.",
            )
        else:
            self.redirect("/login.html")
        return False

    def redirect(self, location):
        self.send_response(
            HTTPStatus.SEE_OTHER
        )
        self.send_header(
            "Location",
            location,
        )
        self.send_header(
            "Content-Length",
            "0",
        )
        self.send_header(
            "Cache-Control",
            "no-store",
        )
        self.end_headers()

    def send_basic_auth_required(self):
        self.send_response(
            HTTPStatus.UNAUTHORIZED
        )
        self.send_header(
            "WWW-Authenticate",
            'Basic realm="PlainNVR"',
        )
        self.send_header(
            "Content-Length",
            "0",
        )
        self.send_header(
            "Cache-Control",
            "no-store",
        )
        self.end_headers()

    def session_cookie(self, session_id):
        return (
            f"{self.app.AUTH_COOKIE_NAME}="
            f"{session_id}; Path=/; "
            "HttpOnly; SameSite=Lax; "
            f"Max-Age="
            f"{self.app.AUTH_SESSION_TTL_SECONDS}"
        )

    def expired_session_cookie(self):
        return (
            f"{self.app.AUTH_COOKIE_NAME}=; "
            "Path=/; HttpOnly; "
            "SameSite=Lax; Max-Age=0"
        )

    def do_GET(self):
        return http_api.do_GET(
            self,
            self.app,
        )

    def do_HEAD(self):
        return http_api.do_HEAD(
            self,
            self.app,
        )

    def do_POST(self):
        return http_api.do_POST(
            self,
            self.app,
        )

    def do_PUT(self):
        return http_api.do_PUT(
            self,
            self.app,
        )

    def do_DELETE(self):
        return http_api.do_DELETE(
            self,
            self.app,
        )

    def handle_auth_setup(self, payload):
        return http_api.handle_auth_setup(
            self,
            self.app,
            payload,
        )

    def handle_auth_login(self, payload):
        return http_api.handle_auth_login(
            self,
            self.app,
            payload,
        )

    def handle_camera_control(
        self,
        camera_id,
        target,
        action,
    ):
        return http_api.handle_camera_control(
            self,
            self.app,
            camera_id,
            target,
            action,
        )

    def handle_recorder_control(
        self,
        camera,
        action,
    ):
        return http_api.handle_recorder_control(
            self,
            self.app,
            camera,
            action,
        )

    def handle_live_control(
        self,
        camera,
        action,
    ):
        return http_api.handle_live_control(
            self,
            self.app,
            camera,
            action,
        )

    def handle_camera_ptz(
        self,
        camera_id,
        payload,
    ):
        return http_api.handle_camera_ptz(
            self,
            self.app,
            camera_id,
            payload,
        )

    def handle_onvif_discovery(
        self,
        payload,
    ):
        return http_api.handle_onvif_discovery(
            self,
            self.app,
            payload,
        )

    def handle_camera_onvif_discovery(
        self,
        camera_id,
        payload=None,
    ):
        return (
            http_api.handle_camera_onvif_discovery(
                self,
                self.app,
                camera_id,
                payload,
            )
        )

    def handle_camera_compatibility(
        self,
        camera_id,
        download=False,
    ):
        return (
            http_api.handle_camera_compatibility(
                self,
                self.app,
                camera_id,
                download,
            )
        )

    def handle_camera_time(
        self,
        camera_id,
        payload=None,
    ):
        return http_api.handle_camera_time(
            self,
            self.app,
            camera_id,
            payload,
        )

    def handle_api_get(self, parsed):
        return http_api.handle_api_get(
            self,
            self.app,
            parsed,
        )

    def handle_go2rtc_proxy(
        self,
        parsed,
        head_only=False,
    ):
        return http_api.handle_go2rtc_proxy(
            self,
            self.app,
            parsed,
            head_only,
        )

    def proxy_go2rtc_websocket(
        self,
        upstream_path,
    ):
        return http_api.proxy_go2rtc_websocket(
            self,
            self.app,
            upstream_path,
        )

    def handle_home_assistant(
        self,
        parsed,
    ):
        return http_api.handle_home_assistant(
            self,
            self.app,
            parsed,
        )

    def handle_home_assistant_head(
        self,
        parsed,
    ):
        return (
            http_api.handle_home_assistant_head(
                self,
                self.app,
                parsed,
            )
        )

    def handle_live_hls(
        self,
        parsed,
        head_only=False,
    ):
        return http_api.handle_live_hls(
            self,
            self.app,
            parsed,
            head_only,
        )

    def handle_live_hls_head(
        self,
        parsed,
    ):
        return http_api.handle_live_hls_head(
            self,
            self.app,
            parsed,
        )

    def proxy_go2rtc_live_hls(
        self,
        upstream_path,
        camera_id,
        token="",
        head_only=False,
    ):
        return http_api.proxy_go2rtc_live_hls(
            self,
            self.app,
            upstream_path,
            camera_id,
            token,
            head_only,
        )

    def send_go2rtc_live_playlist(
        self,
        text,
        camera_id,
        token="",
    ):
        return (
            http_api.send_go2rtc_live_playlist(
                self,
                self.app,
                text,
                camera_id,
                token,
            )
        )

    def handle_snapshot(
        self,
        camera,
        grayscale=False,
    ):
        return http_api.handle_snapshot(
            self,
            self.app,
            camera,
            grayscale,
        )

    def handle_media(
        self,
        path,
        head_only=False,
    ):
        return http_api.handle_media(
            self,
            self.app,
            path,
            head_only,
        )

    def serve_static(
        self,
        path,
        head_only=False,
    ):
        return http_api.serve_static(
            self,
            self.app,
            path,
            head_only,
        )
