def build_ffmpeg_command(
    camera,
    *,
    source_camera,
    ensure_recording_directory,
    ffmpeg_bin,
    ffmpeg_input_args,
    default_segment_seconds,
):
    camera = source_camera
    target_dir = ensure_recording_directory(camera)
    output_pattern = str(
        target_dir / "%Y%m%dT%H%M%S.mp4"
    )
    audio_url = str(
        camera.get("audio_url") or ""
    ).strip()
    record_audio = camera.get(
        "record_audio", True
    )

    command = [
        ffmpeg_bin,
        "-hide_banner",
        "-nostdin",
        "-loglevel",
        "error",
    ]
    command.extend(
        ffmpeg_input_args(
            camera,
            low_latency=(
                not record_audio
                or bool(audio_url)
            ),
        )
    )

    if record_audio and audio_url:
        command.extend(
            ffmpeg_input_args(
                camera,
                "audio_url",
                low_latency=False,
            )
        )

    command.extend(["-map", "0:v:0"])
    if record_audio:
        if audio_url:
            command.extend(
                ["-map", "1:a:0?"]
            )
        else:
            command.extend(
                ["-map", "0:a?"]
            )

    if record_audio:
        command.extend(
            [
                "-c:v",
                "copy",
                "-c:a",
                "aac",
                "-b:a",
                "128k",
                "-ac",
                "2",
            ]
        )
    else:
        command.extend(["-c", "copy"])

    command.extend(
        [
            "-f",
            "segment",
            "-segment_time",
            str(
                camera.get("segment_seconds")
                or default_segment_seconds
            ),
            "-reset_timestamps",
            "1",
            "-strftime",
            "1",
            "-segment_format",
            "mp4",
            "-segment_format_options",
            "movflags=+faststart",
            output_pattern,
        ]
    )
    return command


def ffmpeg_input_args(
    camera,
    url_key="rtsp_url",
    low_latency=True,
    *,
    rtsp_probesize,
    rtsp_analyze_duration,
    rtsp_live_probesize,
    rtsp_live_analyze_duration,
    rtsp_thread_queue_size,
    rtsp_read_timeout_seconds,
):
    url = str(camera.get(url_key) or "").strip()
    transport = camera.get(
        "rtsp_transport", "tcp"
    )
    args = []

    if url.startswith(
        ("rtsp://", "rtsps://")
    ):
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
        args.extend(
            [
                "-rtsp_transport",
                (
                    transport
                    if transport in ("tcp", "udp")
                    else "tcp"
                ),
                "-timeout",
                str(
                    round(
                        rtsp_read_timeout_seconds
                        * 1_000_000
                    )
                ),
                "-probesize",
                probesize,
                "-analyzeduration",
                analyze_duration,
            ]
        )
        if low_latency:
            args.extend(
                [
                    "-fflags",
                    "nobuffer",
                    "-flags",
                    "low_delay",
                ]
            )
        else:
            args.extend(
                [
                    "-fflags",
                    "+genpts+igndts",
                    "-use_wallclock_as_timestamps",
                    "1",
                ]
            )
        args.extend(
            [
                "-thread_queue_size",
                rtsp_thread_queue_size,
            ]
        )

    args.extend(["-i", url])
    return args


def add_video_filters(command, filters):
    if filters:
        command.extend(
            ["-vf", ",".join(filters)]
        )


def build_snapshot_command(
    camera,
    *,
    source_camera,
    ffmpeg_bin,
    ffmpeg_input_args,
    grayscale_enabled,
    grayscale=False,
):
    camera = source_camera
    command = [
        ffmpeg_bin,
        "-hide_banner",
        "-nostdin",
        "-loglevel",
        "error",
    ]
    command.extend(
        ffmpeg_input_args(camera)
    )

    video_filters = []
    if (
        grayscale
        or grayscale_enabled(camera)
    ):
        video_filters.append("hue=s=0")
    add_video_filters(
        command, video_filters
    )

    command.extend(
        [
            "-frames:v",
            "1",
            "-q:v",
            "4",
            "-f",
            "image2pipe",
            "-vcodec",
            "mjpeg",
            "pipe:1",
        ]
    )
    return command
