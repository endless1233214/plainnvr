import os
import subprocess
import threading
import time


class RecorderSupervisor:
    def __init__(
        self,
        *,
        relay,
        build_ffmpeg_command,
        add_event,
        redact_camera_text,
        get_camera,
        camera_dir,
        list_cameras,
        schedule_active,
        iso_now,
        scan_interval_seconds,
        retention_interval_seconds,
        start_grace_seconds,
        stale_seconds,
    ):
        self.relay = relay
        self.build_ffmpeg_command = build_ffmpeg_command
        self.add_event = add_event
        self.redact_camera_text = redact_camera_text
        self.get_camera = get_camera
        self.camera_dir = camera_dir
        self.list_cameras = list_cameras
        self.schedule_active = schedule_active
        self.iso_now = iso_now
        self.scan_interval_seconds = scan_interval_seconds
        self.retention_interval_seconds = retention_interval_seconds
        self.start_grace_seconds = start_grace_seconds
        self.stale_seconds = stale_seconds

        self.lock = threading.RLock()
        self.processes = {}
        self.paused_camera_ids = set()
        self.stop_event = threading.Event()
        self.last_retention = 0
        self.thread = threading.Thread(target=self.run, daemon=True)

    def start(self):
        self.thread.start()

    def shutdown(self):
        self.stop_event.set()
        with self.lock:
            camera_ids = list(self.processes)
        for camera_id in camera_ids:
            self.stop(camera_id)
        self.thread.join(timeout=5)

    def status(self):
        with self.lock:
            states = {}
            for camera_id, entry in self.processes.items():
                process = entry["process"]
                output_age = self.output_age(camera_id)
                states[camera_id] = {
                    "running": process.poll() is None,
                    "pid": process.pid,
                    "started_at": entry["started_at"],
                    "last_error": entry.get("last_error"),
                    "paused": False,
                    "output_age_seconds": (
                        round(output_age, 1)
                        if output_age is not None
                        else None
                    ),
                    "relay_generation": entry.get("relay_generation"),
                }

            for camera_id in self.paused_camera_ids:
                states.setdefault(
                    camera_id,
                    {
                        "running": False,
                        "pid": None,
                        "started_at": None,
                        "last_error": None,
                        "paused": True,
                    },
                )
            return states

    def restart(self, camera_id):
        self.stop(camera_id)

    def pause(self, camera_id):
        with self.lock:
            self.paused_camera_ids.add(camera_id)
        self.stop(camera_id)
        self.add_event(camera_id, "info", "Recorder paused.")

    def resume(self, camera):
        with self.lock:
            self.paused_camera_ids.discard(camera["id"])
        self.add_event(camera["id"], "info", "Recorder resumed.")
        self.ensure_running(camera)

    def restart_now(self, camera):
        with self.lock:
            self.paused_camera_ids.discard(camera["id"])
        self.restart(camera["id"])
        self.ensure_running(camera)

    def is_paused(self, camera_id):
        with self.lock:
            return camera_id in self.paused_camera_ids

    def stop(self, camera_id):
        with self.lock:
            entry = self.processes.pop(camera_id, None)
        if not entry:
            return
        self._terminate_entry(entry)
        self.add_event(camera_id, "info", "Recorder stopped.")

    def ensure_running(self, camera):
        try:
            source_camera = self.relay.source_camera(camera)
        except (OSError, RuntimeError) as exc:
            with self.lock:
                entry = self.processes.pop(camera["id"], None)
            if entry:
                self._terminate_entry(entry)
            self.add_event(
                camera["id"],
                "error",
                "Recorder waiting for go2rtc: "
                + self.redact_camera_text(str(exc), camera),
            )
            return

        relay_generation = source_camera.get("_relay_generation")
        with self.lock:
            entry = self.processes.get(camera["id"])
            if entry and entry["process"].poll() is None:
                generation_matches = (
                    entry.get("relay_generation") == relay_generation
                )
                output_fresh = self._output_is_fresh(camera, entry)
                if generation_matches and output_fresh:
                    return

                reason = (
                    "Recorder source was replaced; restarting."
                    if not generation_matches
                    else "Recorder stopped producing fresh output; restarting."
                )
                self.processes.pop(camera["id"], None)
                self._terminate_entry(entry)
                self.add_event(camera["id"], "warn", reason)
                entry = None

            if entry:
                stderr = ""
                try:
                    stderr = (
                        entry["process"].stderr.read()
                        if entry["process"].stderr
                        else ""
                    )
                except Exception:
                    stderr = ""
                message = (
                    stderr.strip().splitlines()[-1]
                    if stderr.strip()
                    else "Recorder exited."
                )
                self.add_event(camera["id"], "warn", message)
                self.processes.pop(camera["id"], None)

            try:
                command = self.build_ffmpeg_command(
                    camera,
                    source_camera=source_camera,
                )
                process = subprocess.Popen(
                    command,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                    text=True,
                    preexec_fn=os.setsid if hasattr(os, "setsid") else None,
                )
            except (OSError, RuntimeError) as exc:
                self.add_event(
                    camera["id"],
                    "error",
                    f"Could not start FFmpeg: {exc}",
                )
                return

            self.processes[camera["id"]] = {
                "process": process,
                "started_at": self.iso_now(),
                "started_wall": time.time(),
                "command": command,
                "relay_generation": relay_generation,
            }
            self.add_event(camera["id"], "info", "Recorder started.")

    def output_age(self, camera_id):
        camera = self.get_camera(camera_id)
        if not camera:
            return None

        root = self.camera_dir(camera)
        try:
            latest = max(
                (
                    path.stat().st_mtime
                    for path in root.glob("*.mp4")
                ),
                default=None,
            )
        except OSError:
            return None
        return (
            time.time() - latest
            if latest is not None
            else None
        )

    def _output_is_fresh(self, camera, entry):
        if (
            time.time()
            - entry.get("started_wall", time.time())
            < self.start_grace_seconds
        ):
            return True

        age = self.output_age(camera["id"])
        limit = max(
            self.stale_seconds,
            min(float(camera.get("segment_seconds") or 60), 120),
        )
        return age is not None and age <= limit

    def _terminate_entry(self, entry):
        process = entry["process"]
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                process.kill()

    def run_retention(self, cameras):
        now = time.time()
        if now - self.last_retention < self.retention_interval_seconds:
            return

        self.last_retention = now
        for camera in cameras:
            root = self.camera_dir(camera)
            if not root.exists():
                continue
            cutoff = (
                now
                - int(camera.get("retention_days") or 14) * 86400
            )
            for path in root.glob("*.mp4"):
                try:
                    if path.stat().st_mtime < cutoff:
                        path.unlink()
                except OSError:
                    continue

    def run(self):
        while not self.stop_event.is_set():
            cameras = self.list_cameras()
            self.relay.reconcile(cameras)
            active_ids = set()

            for camera in cameras:
                should_record = (
                    bool(camera["enabled"])
                    and self.schedule_active(camera["schedule"])
                    and not self.is_paused(camera["id"])
                )
                if should_record:
                    active_ids.add(camera["id"])
                    self.ensure_running(camera)
                else:
                    self.stop(camera["id"])

            with self.lock:
                for camera_id in list(self.processes):
                    if (
                        camera_id not in active_ids
                        and not self.get_camera(camera_id)
                    ):
                        self.stop(camera_id)

            self.run_retention(cameras)
            self.stop_event.wait(self.scan_interval_seconds)


def segment_start(path, segment_re):
    from datetime import datetime

    match = segment_re.match(path.name)
    if not match:
        return None
    try:
        return datetime.strptime(match.group("stamp"), "%Y%m%dT%H%M%S")
    except ValueError:
        return None


def scan_segments(
    camera,
    date_value=None,
    *,
    camera_dir,
    segment_re,
):
    from datetime import timedelta

    root = camera_dir(camera)
    if not root.exists():
        return []

    segments = []
    for path in root.glob("*.mp4"):
        start = segment_start(path, segment_re)
        if not start:
            continue
        if (
            date_value
            and start.strftime("%Y-%m-%d") != date_value
        ):
            continue

        try:
            stat = path.stat()
        except OSError:
            continue

        segments.append(
            {
                "camera_id": camera["id"],
                "camera_name": camera["name"],
                "filename": path.name,
                "start": start.isoformat(),
                "approx_end": (
                    start
                    + timedelta(
                        seconds=int(camera["segment_seconds"])
                    )
                ).isoformat(),
                "size": stat.st_size,
                "url": f"/media/{camera['id']}/{path.name}",
            }
        )

    segments.sort(key=lambda item: item["start"])
    return segments


def recording_coverage(
    camera,
    *,
    camera_dir,
    segment_re,
):
    root = camera_dir(camera)
    summary = {
        "camera_id": camera["id"],
        "count": 0,
        "total_size": 0,
        "oldest": None,
        "newest": None,
        "dates": [],
        "retention_days": int(
            camera.get("retention_days") or 14
        ),
    }
    if not root.exists():
        return summary

    dates = set()
    oldest = None
    newest = None
    for path in root.glob("*.mp4"):
        start = segment_start(path, segment_re)
        if not start:
            continue
        try:
            stat = path.stat()
        except OSError:
            continue

        summary["count"] += 1
        summary["total_size"] += stat.st_size
        dates.add(start.strftime("%Y-%m-%d"))
        oldest = (
            start
            if oldest is None or start < oldest
            else oldest
        )
        newest = (
            start
            if newest is None or start > newest
            else newest
        )

    summary["oldest"] = (
        oldest.isoformat() if oldest else None
    )
    summary["newest"] = (
        newest.isoformat() if newest else None
    )
    summary["dates"] = sorted(dates)
    return summary
