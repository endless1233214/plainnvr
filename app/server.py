#!/usr/bin/env python3
import os
import re
import shutil
import signal
import sqlite3
import struct
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from urllib import request as urllib_request
from urllib.parse import unquote

try:
    from onvif_client import (
        OnvifError,
        allowed_endpoint_hosts as onvif_allowed_endpoint_hosts,
        cacheable_discovery,
        discover as discover_onvif,
        goto_preset_body,
        payload_credentials as onvif_payload_credentials,
        redacted_discovery,
        redact_url as redact_onvif_url,
        soap_post as onvif_soap_post,
    )
except ModuleNotFoundError:
    from app.onvif_client import (
        OnvifError,
        allowed_endpoint_hosts as onvif_allowed_endpoint_hosts,
        cacheable_discovery,
        discover as discover_onvif,
        goto_preset_body,
        payload_credentials as onvif_payload_credentials,
        redacted_discovery,
        redact_url as redact_onvif_url,
        soap_post as onvif_soap_post,
    )


try:
    from app.auth import (
        AUTH_HASH_ITERATIONS,
        password_hash,
        validate_password,
        validate_username,
        verify_password,
    )
    from app.cameras import (
        add_event as add_event_impl,
        camera_dir as camera_dir_impl,
        camera_from_row as camera_from_row_impl,
        create_camera as create_camera_impl,
        delete_camera as delete_camera_impl,
        discover_camera_onvif as discover_camera_onvif_impl,
        ensure_recording_directory as ensure_recording_directory_impl,
        get_camera as get_camera_impl,
        list_cameras as list_cameras_impl,
        normalize_grayscale_mode,
        normalize_live_view_mode,
        normalize_ptz_profile_token as normalize_ptz_profile_token_impl,
        normalize_ptz_speed,
        normalize_ptz_type as normalize_ptz_type_impl,
        normalize_ptz_zoom_mode,
        normalize_view_rotation,
        save_onvif_discovery as save_onvif_discovery_impl,
        stable_camera_value,
        unique_slug as unique_slug_impl,
        update_camera as update_camera_impl,
        validate_camera_payload as validate_camera_payload_impl,
    )
    from app.common import (
        bounded_int,
        env_float,
        iso_now,
        optional_bounded_int,
        slugify,
        utcnow,
    )
    from app.http_utils import (
        MAX_JSON_BODY_BYTES,
        normalize_bool,
        parse_json_body,
        query_bool,
    )
    from app.schedule import (
        DAY_KEYS,
        default_schedule,
        normalize_schedule,
        schedule_active,
        time_to_minutes,
    )
    from app.media_relay import (
        Go2RTCManager as BaseGo2RTCManager,
        Go2RTCSourceManager,
    )
    from app.night_mode import (
        NightModeManager as BaseNightModeManager,
        analyze_rgb_frame,
    )
    from app.recording import (
        RecorderSupervisor as BaseRecorderSupervisor,
        recording_coverage as recording_coverage_impl,
        scan_segments as scan_segments_impl,
        segment_start as segment_start_impl,
    )
    from app.diagnostics import (
        camera_compatibility_report as camera_compatibility_report_impl,
        compatibility_recommendations as compatibility_recommendations_impl,
        live_diagnostics as live_diagnostics_impl,
        probe_stream_url as probe_stream_url_impl,
        redact_camera_text as redact_camera_text_impl,
        stream_summary as stream_summary_impl,
        test_stream as test_stream_impl,
    )
    from app.http_server import NvrHTTPServer
    from app.http_handler import NvrHandler as BaseNvrHandler
    from app.http_auth import (
        LoginLimiter,
        basic_auth_credentials,
        bearer_token,
        parse_cookie_header,
        valid_stream_auth as valid_stream_auth_impl,
    )
    from app.media_commands import (
        add_video_filters as add_video_filters_impl,
        build_ffmpeg_command as build_ffmpeg_command_impl,
        build_snapshot_command as build_snapshot_command_impl,
        ffmpeg_input_args as ffmpeg_input_args_impl,
    )
    from app.persistence import (
        APP_SETTING_DEFAULTS,
        LOG_LEVEL_ORDER,
        LOG_LEVELS,
        authenticate_user as authenticate_user_impl,
        bootstrap_auth_from_env as bootstrap_auth_from_env_impl,
        cleanup_expired_sessions as cleanup_expired_sessions_impl,
        create_session as create_session_impl,
        create_user as create_user_impl,
        current_session_user as current_session_user_impl,
        db_conn as db_conn_impl,
        delete_session as delete_session_impl,
        delete_user as delete_user_impl,
        ensure_camera_schema,
        ensure_stream_token as ensure_stream_token_impl,
        get_app_settings as get_app_settings_impl,
        get_db as get_db_impl,
        init_db as init_db_impl,
        list_users as list_users_impl,
        normalize_log_level,
        setting_bool,
        setup_required as setup_required_impl,
        update_app_settings as update_app_settings_impl,
    )
    from app.ptz import (
        camera_time as camera_time_impl,
        clean_control_url,
        dvrip_login as dvrip_login_impl,
        dvrip_parse_json,
        dvrip_parse_session,
        dvrip_query_time as dvrip_query_time_impl,
        dvrip_recv_exact,
        dvrip_recv_packet as dvrip_recv_packet_impl,
        dvrip_send_packet as dvrip_send_packet_impl,
        dvrip_step_from_speed,
        dvrip_target as dvrip_target_impl,
        dvrip_url_for_parse,
        http_admin_url_for_parse,
        netloc_without_credentials,
        normalize_requested_camera_time,
        onvif_home_body,
        onvif_move_body as onvif_move_body_impl,
        onvif_stop_body,
        ptz_url_candidates,
        redact_url_credentials,
        run_ptz_command as run_ptz_command_impl,
        run_victure_direct_ptz_command as run_victure_direct_ptz_command_impl,
        run_victure_dvrip_ptz_command as run_victure_dvrip_ptz_command_impl,
        url_credentials,
        victure_direct_step_from_speed,
        victure_direct_target as victure_direct_target_impl,
    )
except ModuleNotFoundError:
    from auth import (
        AUTH_HASH_ITERATIONS,
        password_hash,
        validate_password,
        validate_username,
        verify_password,
    )
    from cameras import (
        add_event as add_event_impl,
        camera_dir as camera_dir_impl,
        camera_from_row as camera_from_row_impl,
        create_camera as create_camera_impl,
        delete_camera as delete_camera_impl,
        discover_camera_onvif as discover_camera_onvif_impl,
        ensure_recording_directory as ensure_recording_directory_impl,
        get_camera as get_camera_impl,
        list_cameras as list_cameras_impl,
        normalize_grayscale_mode,
        normalize_live_view_mode,
        normalize_ptz_profile_token as normalize_ptz_profile_token_impl,
        normalize_ptz_speed,
        normalize_ptz_type as normalize_ptz_type_impl,
        normalize_ptz_zoom_mode,
        normalize_view_rotation,
        save_onvif_discovery as save_onvif_discovery_impl,
        stable_camera_value,
        unique_slug as unique_slug_impl,
        update_camera as update_camera_impl,
        validate_camera_payload as validate_camera_payload_impl,
    )
    from common import (
        bounded_int,
        env_float,
        iso_now,
        optional_bounded_int,
        slugify,
        utcnow,
    )
    from http_utils import (
        MAX_JSON_BODY_BYTES,
        normalize_bool,
        parse_json_body,
        query_bool,
    )
    from schedule import (
        DAY_KEYS,
        default_schedule,
        normalize_schedule,
        schedule_active,
        time_to_minutes,
    )
    from media_relay import (
        Go2RTCManager as BaseGo2RTCManager,
        Go2RTCSourceManager,
    )
    from night_mode import (
        NightModeManager as BaseNightModeManager,
        analyze_rgb_frame,
    )
    from recording import (
        RecorderSupervisor as BaseRecorderSupervisor,
        recording_coverage as recording_coverage_impl,
        scan_segments as scan_segments_impl,
        segment_start as segment_start_impl,
    )
    from diagnostics import (
        camera_compatibility_report as camera_compatibility_report_impl,
        compatibility_recommendations as compatibility_recommendations_impl,
        live_diagnostics as live_diagnostics_impl,
        probe_stream_url as probe_stream_url_impl,
        redact_camera_text as redact_camera_text_impl,
        stream_summary as stream_summary_impl,
        test_stream as test_stream_impl,
    )
    from http_server import NvrHTTPServer
    from http_handler import NvrHandler as BaseNvrHandler
    from http_auth import (
        LoginLimiter,
        basic_auth_credentials,
        bearer_token,
        parse_cookie_header,
        valid_stream_auth as valid_stream_auth_impl,
    )
    from media_commands import (
        add_video_filters as add_video_filters_impl,
        build_ffmpeg_command as build_ffmpeg_command_impl,
        build_snapshot_command as build_snapshot_command_impl,
        ffmpeg_input_args as ffmpeg_input_args_impl,
    )
    from persistence import (
        APP_SETTING_DEFAULTS,
        LOG_LEVEL_ORDER,
        LOG_LEVELS,
        authenticate_user as authenticate_user_impl,
        bootstrap_auth_from_env as bootstrap_auth_from_env_impl,
        cleanup_expired_sessions as cleanup_expired_sessions_impl,
        create_session as create_session_impl,
        create_user as create_user_impl,
        current_session_user as current_session_user_impl,
        db_conn as db_conn_impl,
        delete_session as delete_session_impl,
        delete_user as delete_user_impl,
        ensure_camera_schema,
        ensure_stream_token as ensure_stream_token_impl,
        get_app_settings as get_app_settings_impl,
        get_db as get_db_impl,
        init_db as init_db_impl,
        list_users as list_users_impl,
        normalize_log_level,
        setting_bool,
        setup_required as setup_required_impl,
        update_app_settings as update_app_settings_impl,
    )
    from ptz import (
        camera_time as camera_time_impl,
        clean_control_url,
        dvrip_login as dvrip_login_impl,
        dvrip_parse_json,
        dvrip_parse_session,
        dvrip_query_time as dvrip_query_time_impl,
        dvrip_recv_exact,
        dvrip_recv_packet as dvrip_recv_packet_impl,
        dvrip_send_packet as dvrip_send_packet_impl,
        dvrip_step_from_speed,
        dvrip_target as dvrip_target_impl,
        dvrip_url_for_parse,
        http_admin_url_for_parse,
        netloc_without_credentials,
        normalize_requested_camera_time,
        onvif_home_body,
        onvif_move_body as onvif_move_body_impl,
        onvif_stop_body,
        ptz_url_candidates,
        redact_url_credentials,
        run_ptz_command as run_ptz_command_impl,
        run_victure_direct_ptz_command as run_victure_direct_ptz_command_impl,
        run_victure_dvrip_ptz_command as run_victure_dvrip_ptz_command_impl,
        url_credentials,
        victure_direct_step_from_speed,
        victure_direct_target as victure_direct_target_impl,
    )


APP_HOST = os.environ.get("NVR_HOST", "0.0.0.0")
APP_PORT = int(os.environ.get("NVR_PORT", "8787"))
DATA_DIR = Path(os.environ.get("NVR_DATA_DIR", "/data")).expanduser()
RECORDINGS_DIR = Path(os.environ.get("NVR_RECORDINGS_DIR", "/recordings")).expanduser()
STATIC_DIR = Path(os.environ.get("NVR_STATIC_DIR", "/app/static")).expanduser()
FFMPEG_BIN = os.environ.get("FFMPEG_BIN", "ffmpeg")
FFPROBE_BIN = os.environ.get("FFPROBE_BIN", "ffprobe")
GO2RTC_BIN = os.environ.get("GO2RTC_BIN", "go2rtc")
GO2RTC_API_HOST = os.environ.get("NVR_GO2RTC_API_HOST", "127.0.0.1")
GO2RTC_API_PORT = int(os.environ.get("NVR_GO2RTC_API_PORT", "1984"))
GO2RTC_RTSP_HOST = os.environ.get("NVR_GO2RTC_RTSP_HOST", "127.0.0.1")
GO2RTC_RTSP_PORT = int(os.environ.get("NVR_GO2RTC_RTSP_PORT", "8554"))
GO2RTC_WEBRTC_PORT = int(os.environ.get("NVR_GO2RTC_WEBRTC_PORT", "8555"))
GO2RTC_START_TIMEOUT_SECONDS = max(
    2, env_float("NVR_GO2RTC_START_TIMEOUT_SECONDS", 10)
)
GO2RTC_MEDIA_STALE_SECONDS = max(10, env_float("NVR_GO2RTC_MEDIA_STALE_SECONDS", 30))
RTSP_PROBESIZE = os.environ.get("NVR_RTSP_PROBESIZE", "32768")
RTSP_ANALYZE_DURATION = os.environ.get("NVR_RTSP_ANALYZE_DURATION", "0")
RTSP_LIVE_PROBESIZE = os.environ.get("NVR_RTSP_LIVE_PROBESIZE", "5000000")
RTSP_LIVE_ANALYZE_DURATION = os.environ.get("NVR_RTSP_LIVE_ANALYZE_DURATION", "5000000")
RTSP_THREAD_QUEUE_SIZE = os.environ.get("NVR_RTSP_THREAD_QUEUE_SIZE", "2048")
RTSP_READ_TIMEOUT_SECONDS = max(3, env_float("NVR_RTSP_READ_TIMEOUT_SECONDS", 15))
SCAN_INTERVAL_SECONDS = int(os.environ.get("NVR_SCAN_INTERVAL_SECONDS", "10"))
RETENTION_INTERVAL_SECONDS = int(os.environ.get("NVR_RETENTION_INTERVAL_SECONDS", "3600"))
DEFAULT_SEGMENT_SECONDS = int(os.environ.get("NVR_DEFAULT_SEGMENT_SECONDS", "60"))
RECORDER_START_GRACE_SECONDS = max(15, env_float("NVR_RECORDER_START_GRACE_SECONDS", 45))
RECORDER_STALE_SECONDS = max(30, env_float("NVR_RECORDER_STALE_SECONDS", 90))
NIGHT_SAMPLE_INTERVAL_SECONDS = int(os.environ.get("NVR_NIGHT_SAMPLE_INTERVAL_SECONDS", "20"))
NIGHT_ON_SECONDS = int(os.environ.get("NVR_NIGHT_ON_SECONDS", "45"))
NIGHT_OFF_SECONDS = int(os.environ.get("NVR_NIGHT_OFF_SECONDS", "180"))
NIGHT_ON_BRIGHTNESS = float(os.environ.get("NVR_NIGHT_ON_BRIGHTNESS", "120"))
NIGHT_ON_SATURATION = float(os.environ.get("NVR_NIGHT_ON_SATURATION", "18"))
NIGHT_DARK_BRIGHTNESS = float(os.environ.get("NVR_NIGHT_DARK_BRIGHTNESS", "35"))
NIGHT_OFF_BRIGHTNESS = float(os.environ.get("NVR_NIGHT_OFF_BRIGHTNESS", "155"))
NIGHT_OFF_SATURATION = float(os.environ.get("NVR_NIGHT_OFF_SATURATION", "35"))
DB_PATH = DATA_DIR / "nvr.sqlite3"
AUTH_COOKIE_NAME = "plainnvr_session"
AUTH_SESSION_TTL_SECONDS = int(os.environ.get("NVR_SESSION_TTL_SECONDS", str(7 * 24 * 60 * 60)))
SESSION_TOUCH_INTERVAL_SECONDS = max(60, int(os.environ.get("NVR_SESSION_TOUCH_INTERVAL_SECONDS", "900")))
BOOTSTRAP_USERNAME = os.environ.get("NVR_AUTH_USERNAME", "admin").strip() or "admin"
BOOTSTRAP_PASSWORD = os.environ.get("NVR_AUTH_PASSWORD", "")
STREAM_TOKEN_OVERRIDE = os.environ.get("NVR_STREAM_TOKEN", "").strip()
DEFAULT_PTZ_PROFILE_TOKEN = os.environ.get("NVR_PTZ_PROFILE_TOKEN", "Profile_1").strip() or "Profile_1"
try:
    DEFAULT_PTZ_SPEED = float(os.environ.get("NVR_PTZ_SPEED", "0.55"))
except ValueError:
    DEFAULT_PTZ_SPEED = 0.55
DEFAULT_PTZ_SPEED = max(0.05, min(DEFAULT_PTZ_SPEED, 1.0))
try:
    PTZ_DEFAULT_DURATION_MS = int(os.environ.get("NVR_PTZ_DURATION_MS", "350"))
except ValueError:
    PTZ_DEFAULT_DURATION_MS = 350
PTZ_DEFAULT_DURATION_MS = max(80, min(PTZ_DEFAULT_DURATION_MS, 1500))

SEGMENT_RE = re.compile(r"^(?P<stamp>\d{8}T\d{6})\.mp4$")
STREAM_URL_PREFIXES = ("rtsp://", "rtsps://", "http://", "https://")
CONTROL_URL_PREFIXES = ("http://", "https://")
DVRIP_URL_PREFIXES = ("dvrip://", "tcp://")
PTZ_TYPES = ("none", "onvif", "victure_dvrip", "victure_direct")
PTZ_MOVE_VECTORS = {
    "up": (0, 1, 0),
    "down": (0, -1, 0),
    "left": (-1, 0, 0),
    "right": (1, 0, 0),
    "up_left": (-1, 1, 0),
    "up_right": (1, 1, 0),
    "down_left": (-1, -1, 0),
    "down_right": (1, -1, 0),
    "zoom_in": (0, 0, 1),
    "zoom_out": (0, 0, -1),
}
DVRIP_DEFAULT_PORT = 34567
DVRIP_DEFAULT_USER = "admin"
DVRIP_DEFAULT_PASSHASH = "nTBCS19C"
DVRIP_HEADER = struct.Struct("<BBHIIBBHI")
VICTURE_DIRECT_DEFAULT_PORT = 8088
VICTURE_DIRECT_ACTIONS = {
    "up",
    "down",
    "left",
    "right",
    "up_left",
    "up_right",
    "down_left",
    "down_right",
}
DVRIP_PTZ_COMMANDS = {
    "up": "DirectionUp",
    "down": "DirectionDown",
    "left": "DirectionLeft",
    "right": "DirectionRight",
    "up_left": "DirectionLeftUp",
    "up_right": "DirectionRightUp",
    "down_left": "DirectionLeftDown",
    "down_right": "DirectionRightDown",
    "zoom_in": "ZoomTile",
    "zoom_out": "ZoomWide",
    "stop": "Stop",
}


def get_db():
    return get_db_impl(
        DATA_DIR,
        DB_PATH,
    )


@contextmanager
def db_conn():
    with db_conn_impl(
        DATA_DIR,
        DB_PATH,
    ) as conn:
        yield conn


def bootstrap_auth_from_env(conn):
    return bootstrap_auth_from_env_impl(
        conn,
        bootstrap_password=BOOTSTRAP_PASSWORD,
        bootstrap_username=BOOTSTRAP_USERNAME,
        validate_username=validate_username,
        validate_password=validate_password,
        password_hash=password_hash,
        iso_now=iso_now,
    )


def ensure_stream_token(conn):
    return ensure_stream_token_impl(
        conn,
        stream_token_override=STREAM_TOKEN_OVERRIDE,
        iso_now=iso_now,
    )


def cleanup_expired_sessions(conn):
    return cleanup_expired_sessions_impl(
        conn,
        iso_now=iso_now,
    )


def init_db():
    return init_db_impl(
        db_conn=db_conn,
        bootstrap_auth_from_env=bootstrap_auth_from_env,
        ensure_stream_token=ensure_stream_token,
        cleanup_expired_sessions=cleanup_expired_sessions,
    )


def get_stream_token():
    if STREAM_TOKEN_OVERRIDE:
        return STREAM_TOKEN_OVERRIDE
    with db_conn() as conn:
        return ensure_stream_token(conn)


def get_app_settings():
    return get_app_settings_impl(
        db_conn=db_conn,
    )


def home_assistant_enabled():
    return bool(
        get_app_settings().get(
            "home_assistant_enabled"
        )
    )


def app_log_level():
    return normalize_log_level(
        get_app_settings().get("log_level")
    )


def event_level_enabled(level):
    level = normalize_log_level(
        level,
        default="info",
    )
    configured = app_log_level()
    return (
        LOG_LEVEL_ORDER[level]
        >= LOG_LEVEL_ORDER[configured]
    )


def update_app_settings(payload):
    return update_app_settings_impl(
        payload,
        get_app_settings=get_app_settings,
        db_conn=db_conn,
        iso_now=iso_now,
    )


def setup_required():
    return setup_required_impl(
        db_conn=db_conn,
    )


def create_user(
    username,
    password,
    initial_setup=False,
):
    return create_user_impl(
        username,
        password,
        initial_setup,
        validate_username=validate_username,
        validate_password=validate_password,
        password_hash=password_hash,
        db_conn=db_conn,
        iso_now=iso_now,
    )


def list_users():
    return list_users_impl(
        db_conn=db_conn,
    )


def delete_user(
    username,
    current_username=None,
):
    return delete_user_impl(
        username,
        current_username,
        validate_username=validate_username,
        unquote=unquote,
        db_conn=db_conn,
    )


def authenticate_user(username, password):
    return authenticate_user_impl(
        username,
        password,
        db_conn=db_conn,
        verify_password=verify_password,
    )


def create_session(username):
    return create_session_impl(
        username,
        db_conn=db_conn,
        cleanup_expired_sessions=cleanup_expired_sessions,
        utcnow=utcnow,
        session_ttl_seconds=AUTH_SESSION_TTL_SECONDS,
    )


def delete_session(session_id):
    return delete_session_impl(
        session_id,
        db_conn=db_conn,
    )


def current_session_user(session_id):
    return current_session_user_impl(
        session_id,
        db_conn=db_conn,
        utcnow=utcnow,
        session_touch_interval_seconds=SESSION_TOUCH_INTERVAL_SECONDS,
    )


def normalize_ptz_type(value):
    return normalize_ptz_type_impl(
        value,
        ptz_types=PTZ_TYPES,
    )


def normalize_ptz_profile_token(value):
    return normalize_ptz_profile_token_impl(
        value,
        default_profile_token=DEFAULT_PTZ_PROFILE_TOKEN,
    )


def camera_from_row(row):
    return camera_from_row_impl(
        row,
        normalize_schedule=normalize_schedule,
        normalize_ptz_type=normalize_ptz_type,
        normalize_ptz_profile_token=normalize_ptz_profile_token,
    )


def save_onvif_discovery(camera_id, result):
    return save_onvif_discovery_impl(
        camera_id,
        result,
        cacheable_discovery=cacheable_discovery,
        db_conn=db_conn,
        iso_now=iso_now,
    )


def discover_camera_onvif(
    camera_or_payload,
    camera_id=None,
):
    return discover_camera_onvif_impl(
        camera_or_payload,
        camera_id,
        discover_onvif=discover_onvif,
        save_onvif_discovery=save_onvif_discovery,
    )


def list_cameras():
    return list_cameras_impl(
        db_conn=db_conn,
        camera_from_row=camera_from_row,
    )


def get_camera(camera_id):
    return get_camera_impl(
        camera_id,
        db_conn=db_conn,
        camera_from_row=camera_from_row,
    )


def unique_slug(
    conn,
    name,
    camera_id=None,
):
    return unique_slug_impl(
        conn,
        name,
        camera_id,
        slugify=slugify,
    )


def validate_camera_payload(
    payload,
    partial=False,
):
    return validate_camera_payload_impl(
        payload,
        partial,
        stream_url_prefixes=STREAM_URL_PREFIXES,
        control_url_prefixes=CONTROL_URL_PREFIXES,
        dvrip_url_prefixes=DVRIP_URL_PREFIXES,
        normalize_bool=normalize_bool,
        normalize_ptz_type=normalize_ptz_type,
    )


def create_camera(payload):
    manager = globals().get("go2rtc")
    return create_camera_impl(
        payload,
        validate_camera_payload=validate_camera_payload,
        iso_now=iso_now,
        normalize_schedule=normalize_schedule,
        default_segment_seconds=DEFAULT_SEGMENT_SECONDS,
        default_ptz_speed=DEFAULT_PTZ_SPEED,
        normalize_ptz_type=normalize_ptz_type,
        normalize_ptz_speed=normalize_ptz_speed,
        db_conn=db_conn,
        unique_slug=unique_slug,
        normalize_bool=normalize_bool,
        normalize_ptz_profile_token=normalize_ptz_profile_token,
        get_camera=get_camera,
        configure_camera=(
            manager.configure_camera
            if manager
            else None
        ),
    )


def update_camera(camera_id, payload):
    manager = globals().get("go2rtc")
    return update_camera_impl(
        camera_id,
        payload,
        get_camera=get_camera,
        validate_camera_payload=validate_camera_payload,
        normalize_schedule=normalize_schedule,
        default_segment_seconds=DEFAULT_SEGMENT_SECONDS,
        default_ptz_speed=DEFAULT_PTZ_SPEED,
        normalize_ptz_type=normalize_ptz_type,
        normalize_ptz_speed=normalize_ptz_speed,
        db_conn=db_conn,
        unique_slug=unique_slug,
        normalize_bool=normalize_bool,
        normalize_ptz_profile_token=normalize_ptz_profile_token,
        iso_now=iso_now,
        configure_camera=(
            manager.configure_camera
            if manager
            else None
        ),
        recorder_restart=recorder.restart,
        relay_stop=relay.stop,
    )


def delete_camera(camera_id):
    manager = globals().get("go2rtc")
    return delete_camera_impl(
        camera_id,
        recorder_stop=recorder.stop,
        relay_stop=relay.stop,
        manager_delete_camera=(
            manager.delete_camera
            if manager
            else None
        ),
        db_conn=db_conn,
    )


def add_event(camera_id, level, message):
    return add_event_impl(
        camera_id,
        level,
        message,
        event_level_enabled=event_level_enabled,
        db_conn=db_conn,
        utcnow=utcnow,
        iso_now=iso_now,
        sqlite_error=sqlite3.Error,
    )


def camera_dir(camera):
    return camera_dir_impl(
        camera,
        RECORDINGS_DIR,
    )


def ensure_recording_directory(camera):
    return ensure_recording_directory_impl(
        camera,
        camera_dir=camera_dir,
    )


class Go2RTCManager(BaseGo2RTCManager):
    def __init__(self):
        super().__init__(
            data_dir=DATA_DIR,
            binary=GO2RTC_BIN,
            api_host=GO2RTC_API_HOST,
            api_port=GO2RTC_API_PORT,
            rtsp_host=GO2RTC_RTSP_HOST,
            rtsp_port=GO2RTC_RTSP_PORT,
            webrtc_port=GO2RTC_WEBRTC_PORT,
            ffmpeg_bin=FFMPEG_BIN,
            start_timeout_seconds=GO2RTC_START_TIMEOUT_SECONDS,
            media_stale_seconds=GO2RTC_MEDIA_STALE_SECONDS,
            stream_url_prefixes=STREAM_URL_PREFIXES,
            log_level_provider=app_log_level,
        )


go2rtc = Go2RTCManager()
relay = Go2RTCSourceManager(go2rtc)


def build_ffmpeg_command(
    camera,
    source_camera=None,
):
    return build_ffmpeg_command_impl(
        camera,
        source_camera=(
            source_camera
            or relay.source_camera(camera)
        ),
        ensure_recording_directory=ensure_recording_directory,
        ffmpeg_bin=FFMPEG_BIN,
        ffmpeg_input_args=ffmpeg_input_args,
        default_segment_seconds=DEFAULT_SEGMENT_SECONDS,
    )


def ffmpeg_input_args(
    camera_or_payload,
    url_key="rtsp_url",
    low_latency=True,
):
    return ffmpeg_input_args_impl(
        camera_or_payload,
        url_key,
        low_latency,
        rtsp_probesize=RTSP_PROBESIZE,
        rtsp_analyze_duration=RTSP_ANALYZE_DURATION,
        rtsp_live_probesize=RTSP_LIVE_PROBESIZE,
        rtsp_live_analyze_duration=RTSP_LIVE_ANALYZE_DURATION,
        rtsp_thread_queue_size=RTSP_THREAD_QUEUE_SIZE,
        rtsp_read_timeout_seconds=RTSP_READ_TIMEOUT_SECONDS,
    )


def grayscale_enabled(camera):
    mode = normalize_grayscale_mode(
        camera.get("grayscale_mode")
    )
    if mode == "always":
        return True
    if mode == "auto":
        return night_modes.is_night(
            camera["id"]
        )
    return False


def add_video_filters(command, filters):
    return add_video_filters_impl(
        command,
        filters,
    )


def build_snapshot_command(
    camera,
    grayscale=False,
):
    return build_snapshot_command_impl(
        camera,
        source_camera=relay.source_camera(camera),
        ffmpeg_bin=FFMPEG_BIN,
        ffmpeg_input_args=ffmpeg_input_args,
        grayscale_enabled=grayscale_enabled,
        grayscale=grayscale,
    )


def dvrip_send_packet(
    sock,
    session,
    number,
    packet_type,
    payload,
):
    return dvrip_send_packet_impl(
        sock,
        session,
        number,
        packet_type,
        payload,
        header=DVRIP_HEADER,
    )


def dvrip_recv_packet(sock):
    return dvrip_recv_packet_impl(
        sock,
        header=DVRIP_HEADER,
    )


def dvrip_login(sock, target):
    return dvrip_login_impl(
        sock,
        target,
        header=DVRIP_HEADER,
    )


def dvrip_query_time(sock, session, number=4):
    return dvrip_query_time_impl(
        sock,
        session,
        number=number,
        header=DVRIP_HEADER,
    )


def dvrip_target(camera):
    return dvrip_target_impl(
        camera,
        default_profile_token=DEFAULT_PTZ_PROFILE_TOKEN,
        default_port=DVRIP_DEFAULT_PORT,
        default_user=DVRIP_DEFAULT_USER,
        default_passhash=DVRIP_DEFAULT_PASSHASH,
    )


def dvrip_time_target(camera):
    target_camera = dict(camera)
    if normalize_ptz_type(camera.get("ptz_type")) != "victure_dvrip":
        target_camera["ptz_url"] = ""
    return dvrip_target(target_camera)


def camera_time(camera, requested=None):
    return camera_time_impl(
        camera,
        requested,
        normalize_ptz_type=normalize_ptz_type,
        default_profile_token=DEFAULT_PTZ_PROFILE_TOKEN,
        default_port=DVRIP_DEFAULT_PORT,
        default_user=DVRIP_DEFAULT_USER,
        default_passhash=DVRIP_DEFAULT_PASSHASH,
        header=DVRIP_HEADER,
    )


def run_victure_dvrip_ptz_command(
    camera,
    action,
    speed,
    duration_ms,
):
    return run_victure_dvrip_ptz_command_impl(
        camera,
        action,
        speed,
        duration_ms,
        commands=DVRIP_PTZ_COMMANDS,
        move_vectors=PTZ_MOVE_VECTORS,
        default_profile_token=DEFAULT_PTZ_PROFILE_TOKEN,
        default_port=DVRIP_DEFAULT_PORT,
        default_user=DVRIP_DEFAULT_USER,
        default_passhash=DVRIP_DEFAULT_PASSHASH,
        header=DVRIP_HEADER,
    )


def victure_direct_target(camera):
    return victure_direct_target_impl(
        camera,
        default_port=VICTURE_DIRECT_DEFAULT_PORT,
    )


def run_victure_direct_ptz_command(
    camera,
    action,
    speed,
):
    return run_victure_direct_ptz_command_impl(
        camera,
        action,
        speed,
        direct_actions=VICTURE_DIRECT_ACTIONS,
        default_port=VICTURE_DIRECT_DEFAULT_PORT,
    )


def onvif_move_body(
    action,
    speed,
    duration_ms,
    profile_token,
    continuous=False,
):
    return onvif_move_body_impl(
        action,
        speed,
        duration_ms,
        profile_token,
        move_vectors=PTZ_MOVE_VECTORS,
        continuous=continuous,
    )


def run_ptz_command(camera, payload):
    return run_ptz_command_impl(
        camera,
        payload,
        normalize_ptz_type=normalize_ptz_type,
        normalize_ptz_speed=normalize_ptz_speed,
        normalize_bool=normalize_bool,
        bounded_int=bounded_int,
        default_ptz_speed=DEFAULT_PTZ_SPEED,
        default_duration_ms=PTZ_DEFAULT_DURATION_MS,
        move_vectors=PTZ_MOVE_VECTORS,
        run_victure_dvrip=run_victure_dvrip_ptz_command,
        run_victure_direct=run_victure_direct_ptz_command,
        discover_camera_onvif=discover_camera_onvif,
        onvif_error=OnvifError,
        normalize_ptz_profile_token=normalize_ptz_profile_token,
        onvif_payload_credentials=onvif_payload_credentials,
        onvif_allowed_endpoint_hosts=onvif_allowed_endpoint_hosts,
        onvif_soap_post=onvif_soap_post,
        goto_preset_body=goto_preset_body,
    )


class NightModeManager(BaseNightModeManager):
    def __init__(self):
        super().__init__(
            ffmpeg_bin=FFMPEG_BIN,
            ffmpeg_input_args=ffmpeg_input_args,
            list_cameras=list_cameras,
            iso_now=iso_now,
            sample_interval_seconds=NIGHT_SAMPLE_INTERVAL_SECONDS,
            on_seconds=NIGHT_ON_SECONDS,
            off_seconds=NIGHT_OFF_SECONDS,
            on_brightness=NIGHT_ON_BRIGHTNESS,
            on_saturation=NIGHT_ON_SATURATION,
            dark_brightness=NIGHT_DARK_BRIGHTNESS,
            off_brightness=NIGHT_OFF_BRIGHTNESS,
            off_saturation=NIGHT_OFF_SATURATION,
        )


night_modes = NightModeManager()


class RecorderSupervisor(BaseRecorderSupervisor):
    def __init__(self):
        super().__init__(
            relay=relay,
            build_ffmpeg_command=build_ffmpeg_command,
            add_event=add_event,
            redact_camera_text=lambda text, camera: redact_camera_text(
                text, camera
            ),
            get_camera=get_camera,
            camera_dir=camera_dir,
            list_cameras=list_cameras,
            schedule_active=schedule_active,
            iso_now=iso_now,
            scan_interval_seconds=SCAN_INTERVAL_SECONDS,
            retention_interval_seconds=RETENTION_INTERVAL_SECONDS,
            start_grace_seconds=RECORDER_START_GRACE_SECONDS,
            stale_seconds=RECORDER_STALE_SECONDS,
        )


recorder = RecorderSupervisor()


def scan_segments(camera, date_value=None):
    return scan_segments_impl(
        camera,
        date_value,
        camera_dir=camera_dir,
        segment_re=SEGMENT_RE,
    )


def segment_start(path):
    return segment_start_impl(path, SEGMENT_RE)


def recording_coverage(camera):
    return recording_coverage_impl(
        camera,
        camera_dir=camera_dir,
        segment_re=SEGMENT_RE,
    )


def probe_stream_url(
    url,
    payload,
    select_streams,
    show_entries,
    low_latency=True,
):
    return probe_stream_url_impl(
        url,
        payload,
        select_streams,
        show_entries,
        stream_url_prefixes=STREAM_URL_PREFIXES,
        ffprobe_bin=FFPROBE_BIN,
        rtsp_probesize=RTSP_PROBESIZE,
        rtsp_analyze_duration=RTSP_ANALYZE_DURATION,
        rtsp_live_probesize=RTSP_LIVE_PROBESIZE,
        rtsp_live_analyze_duration=RTSP_LIVE_ANALYZE_DURATION,
        low_latency=low_latency,
    )


def test_stream(payload):
    return test_stream_impl(
        payload,
        stream_url_prefixes=STREAM_URL_PREFIXES,
        normalize_bool=normalize_bool,
        probe_stream_url=probe_stream_url,
    )


def redact_camera_text(text, camera):
    return redact_camera_text_impl(text, camera)


def stream_summary(probe):
    return stream_summary_impl(probe)


def live_diagnostics(camera, include_audio=True):
    return live_diagnostics_impl(
        camera,
        include_audio,
        probe_stream_url=probe_stream_url,
        go2rtc=go2rtc,
        redact_camera_text=redact_camera_text,
    )


def compatibility_recommendations(stream_result, discovery):
    return compatibility_recommendations_impl(
        stream_result,
        discovery,
    )


def camera_compatibility_report(
    camera,
    refresh_onvif=True,
):
    return camera_compatibility_report_impl(
        camera,
        refresh_onvif,
        test_stream=test_stream,
        discover_camera_onvif=discover_camera_onvif,
        onvif_error=OnvifError,
        iso_now=iso_now,
        server_version=NvrHandler.server_version,
        go2rtc=go2rtc,
        redact_onvif_url=redact_onvif_url,
        redacted_discovery=redacted_discovery,
        relay=relay,
        recorder=recorder,
        recording_coverage=recording_coverage,
        compatibility_recommendations=compatibility_recommendations,
        redact_camera_text=redact_camera_text,
    )


def get_recent_events(camera_id=None):
    with db_conn() as conn:
        if camera_id:
            rows = conn.execute(
                "SELECT * FROM recorder_events WHERE camera_id = ? ORDER BY id DESC LIMIT 20",
                (camera_id,),
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM recorder_events ORDER BY id DESC LIMIT 50").fetchall()
    return [dict(row) for row in rows]


def disk_status():
    RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)
    usage = shutil.disk_usage(RECORDINGS_DIR)
    return {"total": usage.total, "used": usage.used, "free": usage.free}


def valid_stream_auth(handler, parsed):
    return valid_stream_auth_impl(
        handler,
        parsed,
        get_stream_token=get_stream_token,
        authenticate_user=authenticate_user,
        basic_failure_limiter=basic_failure_limiter,
    )


login_limiter = LoginLimiter()
basic_failure_limiter = LoginLimiter()


class NvrHandler(BaseNvrHandler):
    app = sys.modules[__name__]



def main():
    os.umask(0o077)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)
    init_db()
    go2rtc.start(list_cameras())
    recorder.start()
    server = NvrHTTPServer((APP_HOST, APP_PORT), NvrHandler)

    def handle_signal(signum, _frame):
        print(f"Received signal {signum}, shutting down.")
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)
    print(f"PlainNVR listening on http://{APP_HOST}:{APP_PORT}")
    try:
        server.serve_forever()
    finally:
        recorder.shutdown()
        go2rtc.shutdown()
        server.server_close()


if __name__ == "__main__":
    main()
