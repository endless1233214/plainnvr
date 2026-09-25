import json
import os
import shutil
import subprocess
import threading
import time
from collections import deque
from pathlib import Path
from urllib import error as urllib_error, request as urllib_request
from urllib.parse import urlencode


LOG_LEVELS = ("trace", "debug", "info", "warn", "error", "fatal")


def normalize_log_level(value, default="info"):
    level = str(value or "").strip().lower()
    return level if level in LOG_LEVELS else default


class Go2RTCManager:
    def __init__(
        self,
        *,
        data_dir,
        binary,
        api_host,
        api_port,
        rtsp_host,
        rtsp_port,
        webrtc_port,
        ffmpeg_bin,
        start_timeout_seconds,
        media_stale_seconds,
        stream_url_prefixes,
        log_level_provider=lambda: "info",
    ):
        self.data_dir = Path(data_dir)
        self.binary = binary
        self.api_host = api_host
        self.api_port = int(api_port)
        self.rtsp_host = rtsp_host
        self.rtsp_port = int(rtsp_port)
        self.webrtc_port = int(webrtc_port)
        self.ffmpeg_bin = ffmpeg_bin
        self.start_timeout_seconds = float(start_timeout_seconds)
        self.media_stale_seconds = float(media_stale_seconds)
        self.stream_url_prefixes = tuple(stream_url_prefixes)
        self.log_level_provider = log_level_provider

        self.lock = threading.RLock()
        self.process = None
        self.log_thread = None
        self.log_lines = deque(maxlen=200)
        self.config_path = self.data_dir / "go2rtc.json"
        self.stream_keys = {}
        self.generations = {}
        self.media_states = {}
        self.last_error = None

    def stream_name(self, camera):
        return f"plainnvr_{camera['id']}"

    def source_key(self, camera):
        return str(camera.get("rtsp_url") or "").strip()

    def binary_path(self):
        return shutil.which(self.binary)

    def running(self):
        with self.lock:
            return bool(self.process and self.process.poll() is None)

    def can_restream(self, camera):
        stream_url = self.source_key(camera)
        audio_url = str(camera.get("audio_url") or "").strip()
        separate_audio = bool(
            camera.get("record_audio", True)
            and audio_url
            and audio_url != stream_url
        )
        return (
            self.running()
            and stream_url.startswith(self.stream_url_prefixes)
            and not separate_audio
        )

    def _config(self, log_level="info"):
        networks = [
            item.strip()
            for item in os.environ.get(
                "NVR_GO2RTC_WEBRTC_NETWORKS", "udp4,tcp4"
            ).split(",")
            if item.strip()
        ]
        if not networks or set(networks) - {"udp4", "tcp4", "udp6", "tcp6"}:
            raise ValueError(
                "NVR_GO2RTC_WEBRTC_NETWORKS must contain udp4, tcp4, udp6, or tcp6."
            )
        candidates = [
            item.strip()
            for item in os.environ.get(
                "NVR_GO2RTC_WEBRTC_CANDIDATES", ""
            ).split(",")
            if item.strip()
        ]
        config = {
            "log": {"level": normalize_log_level(log_level)},
            "api": {
                "listen": f"{self.api_host}:{self.api_port}",
                "origin": "*",
            },
            "rtsp": {"listen": f"{self.rtsp_host}:{self.rtsp_port}"},
            "webrtc": {
                "listen": f":{self.webrtc_port}",
                "filters": {"networks": networks},
            },
            "ffmpeg": {"bin": self.ffmpeg_bin},
            "streams": {},
        }
        if candidates:
            config["webrtc"]["candidates"] = candidates
        return config

    def start(self, cameras):
        binary = self.binary_path()
        if not binary:
            self.last_error = (
                f"{self.binary} is not installed; live restreaming is unavailable."
            )
            print(self.last_error)
            return False

        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.config_path.write_text(
            json.dumps(
                self._config(log_level=self.log_level_provider()), indent=2
            )
            + "\n",
            encoding="utf-8",
        )

        with self.lock:
            if self.process and self.process.poll() is None:
                return True
            self.process = subprocess.Popen(
                [binary, "-config", str(self.config_path)],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
            self.log_thread = threading.Thread(
                target=self._capture_logs,
                args=(self.process,),
                daemon=True,
            )
            self.log_thread.start()

        deadline = time.time() + self.start_timeout_seconds
        while time.time() < deadline:
            if not self.running():
                break
            try:
                self._request("/api/streams", timeout=1)
                self.last_error = None
                self.reconcile(cameras)
                print("go2rtc is ready; low-latency restreaming enabled.")
                return True
            except (OSError, urllib_error.URLError, urllib_error.HTTPError):
                time.sleep(0.2)

        self.last_error = (
            f"go2rtc did not become ready. {self.log_tail(8)}".strip()
        )
        print(self.last_error)
        self.shutdown()
        return False

    def _capture_logs(self, process):
        stream = process.stdout
        if stream is None:
            return
        try:
            for line in stream:
                with self.lock:
                    self.log_lines.append(line.rstrip())
        finally:
            try:
                stream.close()
            except OSError:
                pass

    def _request(self, path, method="GET", timeout=3):
        request = urllib_request.Request(
            f"http://{self.api_host}:{self.api_port}{path}",
            method=method,
        )
        with urllib_request.urlopen(request, timeout=timeout) as response:
            return response.read(1024 * 1024)

    def configure_camera(self, camera):
        if not self.running():
            return False
        source = self.source_key(camera)
        if not source.startswith(self.stream_url_prefixes):
            return False

        audio_url = str(camera.get("audio_url") or "").strip()
        if camera.get("record_audio", True) and audio_url and audio_url != source:
            return False

        name = self.stream_name(camera)
        source_key = self.source_key(camera)
        with self.lock:
            if self.stream_keys.get(camera["id"]) == source_key:
                return True

        query = urlencode({"name": name, "src": source})
        try:
            self._request(f"/api/streams?{query}", method="PATCH")
        except (OSError, urllib_error.URLError, urllib_error.HTTPError) as exc:
            self.last_error = f"Could not configure {camera.get('name')}: {exc}"
            return False

        with self.lock:
            self.stream_keys[camera["id"]] = source_key
            self.generations[camera["id"]] = (
                self.generations.get(camera["id"], 0) + 1
            )
            self.media_states.pop(camera["id"], None)
        return True

    def delete_camera(self, camera_id):
        with self.lock:
            self.stream_keys.pop(camera_id, None)
            self.generations.pop(camera_id, None)
            self.media_states.pop(camera_id, None)

        if not self.running():
            return

        name = f"plainnvr_{camera_id}"
        try:
            self._request(
                f"/api/streams?{urlencode({'src': name})}",
                method="DELETE",
            )
        except (OSError, urllib_error.URLError, urllib_error.HTTPError):
            pass

    def restart_camera(self, camera):
        if not self.can_restream(camera):
            return False

        camera_id = camera["id"]
        name = self.stream_name(camera)
        with self.lock:
            previous_generation = self.generations.get(camera_id, 0)
            self.stream_keys.pop(camera_id, None)
            self.generations[camera_id] = previous_generation

        try:
            self._request(
                f"/api/streams?{urlencode({'src': name})}",
                method="DELETE",
            )
        except (OSError, urllib_error.URLError, urllib_error.HTTPError):
            pass
        return self.configure_camera(camera)

    def reconcile(self, cameras):
        if not self.running():
            with self.lock:
                self.stream_keys.clear()
                self.media_states.clear()
            self.start(cameras)
            return

        active_ids = set()
        for camera in cameras:
            if not camera.get("enabled") or not self.can_restream(camera):
                continue
            active_ids.add(camera["id"])
            self.configure_camera(camera)

        with self.lock:
            stale_ids = set(self.stream_keys) - active_ids
        for camera_id in stale_ids:
            self.delete_camera(camera_id)

        self.sample_media(cameras)
        for camera in cameras:
            if camera["id"] not in active_ids:
                continue
            if self.camera_status(camera)["media_state"] == "stalled":
                self.restart_camera(camera)

    def sample_media(self, cameras):
        try:
            streams = json.loads(self._request("/api/streams").decode("utf-8"))
            if not isinstance(streams, dict):
                return
        except (OSError, ValueError, urllib_error.URLError):
            return

        now = time.monotonic()
        with self.lock:
            for camera in cameras:
                camera_id = camera["id"]
                if camera_id not in self.stream_keys:
                    continue

                stream = streams.get(self.stream_name(camera)) or {}
                producers = stream.get("producers") or []
                consumers = stream.get("consumers") or []
                counters = tuple(
                    sorted(
                        (
                            str(receiver.get("id", "")),
                            int(receiver.get("packets") or 0),
                        )
                        for producer in producers
                        for receiver in producer.get("receivers") or []
                        if (receiver.get("codec") or {}).get("codec_type")
                        == "video"
                    )
                )

                previous = self.media_states.get(camera_id, {})
                active = bool(consumers)
                changed = counters != previous.get("counters") and any(
                    count > 0 for _, count in counters
                )
                progress_at = (
                    now if changed else previous.get("progress_at")
                )
                active_since = (
                    previous.get("active_since", now)
                    if previous.get("active")
                    else now
                )

                if not active:
                    phase = "idle"
                    progress_at = None
                elif (
                    progress_at is not None
                    and now - progress_at < self.media_stale_seconds
                ):
                    phase = "streaming"
                elif now - active_since < self.media_stale_seconds:
                    phase = "starting"
                else:
                    phase = "stalled"

                self.media_states[camera_id] = {
                    "counters": counters,
                    "progress_at": progress_at,
                    "sampled_at": now,
                    "active": active,
                    "active_since": active_since,
                    "state": phase,
                }

    def source_camera(self, camera):
        if not self.can_restream(camera) or not self.configure_camera(camera):
            raise RuntimeError(
                "go2rtc restream is unavailable for this camera."
            )

        cloned = dict(camera)
        cloned["rtsp_url"] = (
            f"rtsp://{self.rtsp_host}:{self.rtsp_port}/"
            f"{self.stream_name(camera)}"
        )
        cloned["audio_url"] = ""
        cloned["rtsp_transport"] = "tcp"
        cloned["_relay_generation"] = self.generations.get(camera["id"], 0)
        cloned["_relay_backend"] = "go2rtc"
        return cloned

    def camera_status(self, camera):
        with self.lock:
            configured = (
                self.stream_keys.get(camera["id"]) == self.source_key(camera)
            )
            media = dict(self.media_states.get(camera["id"], {}))

        now = time.monotonic()
        progress_at = media.get("progress_at")
        age = now - progress_at if progress_at is not None else None
        phase = media.get("state", "starting")
        if (
            phase == "streaming"
            and (age is None or age >= self.media_stale_seconds)
        ):
            phase = "stalled"

        return {
            "running": self.running(),
            "healthy": self.running()
            and configured
            and phase == "streaming",
            "available": self.running() and configured,
            "media_state": (
                phase if self.running() and configured else "unavailable"
            ),
            "media_age_seconds": round(age, 2) if age is not None else None,
            "pid": self.process.pid if self.running() else None,
            "started_at": None,
            "last_error": self.last_error,
            "source": (
                f"rtsp://{self.rtsp_host}:{self.rtsp_port}/"
                f"{self.stream_name(camera)}"
            ),
            "generation": self.generations.get(camera["id"], 0),
            "restart_count": 0,
            "backend": "go2rtc",
            "stream": self.stream_name(camera),
        }

    def stream_info(self, camera):
        if not self.can_restream(camera) or not self.configure_camera(camera):
            return None
        try:
            raw = self._request(
                f"/api/streams?{urlencode({'src': self.stream_name(camera)})}"
            )
            return json.loads(raw.decode("utf-8"))
        except (
            OSError,
            ValueError,
            urllib_error.URLError,
            urllib_error.HTTPError,
        ):
            return None

    def status(self):
        return {
            "available": bool(self.binary_path()),
            "running": self.running(),
            "pid": self.process.pid if self.running() else None,
            "error": self.last_error,
            "api_proxy": "/go2rtc/api/ws",
            "rtsp_port": self.rtsp_port,
            "webrtc_port": self.webrtc_port,
        }

    def log_tail(self, line_count=20):
        with self.lock:
            lines = list(self.log_lines)
        return "\n".join(lines[-line_count:]).strip()

    def shutdown(self):
        with self.lock:
            process = self.process
            log_thread = self.log_thread
            self.process = None
            self.log_thread = None

        if process and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=1)

        if log_thread and log_thread.is_alive():
            log_thread.join(timeout=1)


class Go2RTCSourceManager:
    def __init__(self, manager):
        self.manager = manager

    def source_camera(self, camera):
        if self.manager.can_restream(camera):
            try:
                return self.manager.source_camera(camera)
            except RuntimeError as exc:
                self.manager.last_error = str(exc)
        raise RuntimeError("go2rtc restream is unavailable for this camera.")

    def status(self, cameras=None):
        states = {}
        for camera in cameras or []:
            if self.manager.can_restream(camera):
                states[camera["id"]] = self.manager.camera_status(camera)
            else:
                states[camera["id"]] = {
                    "running": self.manager.running(),
                    "healthy": False,
                    "pid": (
                        self.manager.process.pid
                        if self.manager.running()
                        else None
                    ),
                    "started_at": None,
                    "last_error": (
                        self.manager.last_error
                        or "go2rtc cannot restream this camera."
                    ),
                    "source": None,
                    "generation": self.manager.generations.get(
                        camera["id"], 0
                    ),
                    "restart_count": 0,
                    "backend": "go2rtc",
                    "stream": self.manager.stream_name(camera),
                }
        return states

    def stop(self, camera_id):
        self.manager.delete_camera(camera_id)

    def reconcile(self, cameras):
        self.manager.reconcile(cameras)

    def shutdown(self):
        return None
