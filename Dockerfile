FROM python:3.12-slim

ARG TARGETARCH

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# No Python packages are installed at runtime; omit the unused package installer.
RUN python -m pip uninstall -y pip

ADD --chmod=755 "https://github.com/AlexxIT/go2rtc/releases/download/v1.9.14/go2rtc_linux_${TARGETARCH}" /usr/local/bin/go2rtc

RUN case "${TARGETARCH}" in \
      amd64) checksum=32d616af226bd731678ffde328b94cfb94e30339bfefc469cfb76323144615a6 ;; \
      arm64) checksum=359fabade8a7a51e81a55fe6df6b0ef81764a5e1d63179577534eaaa71904b50 ;; \
      *) echo "Unsupported architecture: ${TARGETARCH}" >&2; exit 1 ;; \
    esac \
    && echo "${checksum}  /usr/local/bin/go2rtc" | sha256sum -c -

WORKDIR /app

COPY app /app/app
COPY static /app/static
RUN chmod -R a+rX /app/app /app/static

ENV NVR_HOST=0.0.0.0 \
    NVR_PORT=8787 \
    NVR_DATA_DIR=/data \
    NVR_RECORDINGS_DIR=/recordings \
    NVR_STATIC_DIR=/app/static

EXPOSE 8787 8554 8555/tcp 8555/udp

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import os, urllib.request; port = os.environ.get('NVR_PORT', '8787'); urllib.request.urlopen(f'http://127.0.0.1:{port}/api/health', timeout=3).read()" || exit 1

CMD ["python", "/app/app/server.py"]
