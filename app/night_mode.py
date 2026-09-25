import subprocess
import threading
import time


def analyze_rgb_frame(data):
    if not data:
        return {"brightness": 0.0, "saturation": 0.0}

    total_luma = 0.0
    total_saturation = 0.0
    pixels = len(data) // 3
    for index in range(0, pixels * 3, 3):
        red = data[index]
        green = data[index + 1]
        blue = data[index + 2]
        maximum = max(red, green, blue)
        minimum = min(red, green, blue)
        total_luma += 0.2126 * red + 0.7152 * green + 0.0722 * blue
        total_saturation += (
            0.0
            if maximum == 0
            else ((maximum - minimum) / maximum) * 100
        )
    return {
        "brightness": total_luma / pixels,
        "saturation": total_saturation / pixels,
    }


class NightModeManager:
    def __init__(
        self,
        *,
        ffmpeg_bin,
        ffmpeg_input_args,
        list_cameras,
        iso_now,
        sample_interval_seconds,
        on_seconds,
        off_seconds,
        on_brightness,
        on_saturation,
        dark_brightness,
        off_brightness,
        off_saturation,
    ):
        self.ffmpeg_bin = ffmpeg_bin
        self.ffmpeg_input_args = ffmpeg_input_args
        self.list_cameras = list_cameras
        self.iso_now = iso_now
        self.sample_interval_seconds = sample_interval_seconds
        self.on_seconds = on_seconds
        self.off_seconds = off_seconds
        self.on_brightness = on_brightness
        self.on_saturation = on_saturation
        self.dark_brightness = dark_brightness
        self.off_brightness = off_brightness
        self.off_saturation = off_saturation

        self.lock = threading.RLock()
        self.states = {}
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self.run, daemon=True)

    def start(self):
        self.thread.start()

    def shutdown(self):
        self.stop_event.set()
        self.thread.join(timeout=5)

    def is_night(self, camera_id):
        with self.lock:
            return bool(self.states.get(camera_id, {}).get("night"))

    def status(self):
        with self.lock:
            return {
                camera_id: dict(state)
                for camera_id, state in self.states.items()
            }

    def sample_camera(self, camera):
        command = [
            self.ffmpeg_bin,
            "-hide_banner",
            "-nostdin",
            "-loglevel",
            "error",
        ]
        command.extend(self.ffmpeg_input_args(camera, low_latency=True))
        command.extend(
            [
                "-frames:v",
                "1",
                "-vf",
                "scale=64:36",
                "-f",
                "rawvideo",
                "-pix_fmt",
                "rgb24",
                "pipe:1",
            ]
        )
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                timeout=12,
            )
        except subprocess.TimeoutExpired:
            return None, "Night sample timed out."

        if result.returncode != 0 or not result.stdout:
            message = (
                result.stderr.decode("utf-8", "replace")
                .strip()
                .splitlines()
            )
            return (
                None,
                message[-1] if message else "Night sample failed.",
            )
        return analyze_rgb_frame(result.stdout), None

    def update_state(self, camera, metrics, error=None):
        camera_id = camera["id"]
        now = time.time()
        with self.lock:
            state = self.states.setdefault(
                camera_id,
                {
                    "night": False,
                    "first_on_at": None,
                    "first_off_at": None,
                    "updated_at": None,
                    "brightness": None,
                    "saturation": None,
                    "error": None,
                },
            )
            if error:
                state["error"] = error
                state["updated_at"] = self.iso_now()
                return

            brightness = metrics["brightness"]
            saturation = metrics["saturation"]
            wants_on = (
                saturation <= self.on_saturation
                and brightness <= self.on_brightness
            ) or brightness <= self.dark_brightness
            wants_off = (
                saturation >= self.off_saturation
                or brightness >= self.off_brightness
            )

            if state["night"]:
                state["first_on_at"] = None
                if wants_off:
                    state["first_off_at"] = state["first_off_at"] or now
                    if now - state["first_off_at"] >= self.off_seconds:
                        state["night"] = False
                        state["first_off_at"] = None
                else:
                    state["first_off_at"] = None
            else:
                state["first_off_at"] = None
                if wants_on:
                    state["first_on_at"] = state["first_on_at"] or now
                    if now - state["first_on_at"] >= self.on_seconds:
                        state["night"] = True
                        state["first_on_at"] = None
                else:
                    state["first_on_at"] = None

            state.update(
                {
                    "updated_at": self.iso_now(),
                    "brightness": round(brightness, 2),
                    "saturation": round(saturation, 2),
                    "error": None,
                }
            )

    def run(self):
        while not self.stop_event.is_set():
            cameras = [
                camera
                for camera in self.list_cameras()
                if camera.get("enabled")
                and camera.get("grayscale_mode") == "auto"
            ]
            active_ids = {camera["id"] for camera in cameras}
            with self.lock:
                for camera_id in list(self.states):
                    if camera_id not in active_ids:
                        self.states.pop(camera_id, None)

            for camera in cameras:
                metrics, error = self.sample_camera(camera)
                self.update_state(camera, metrics, error=error)
                if self.stop_event.wait(0.1):
                    return

            self.stop_event.wait(max(5, self.sample_interval_seconds))
