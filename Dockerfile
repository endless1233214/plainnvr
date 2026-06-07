FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY app /app/app
COPY static /app/static

ENV NVR_HOST=0.0.0.0 \
    NVR_PORT=8787 \
    NVR_DATA_DIR=/data \
    NVR_RECORDINGS_DIR=/recordings \
    NVR_STATIC_DIR=/app/static

EXPOSE 8787

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import os, urllib.request; port = os.environ.get('NVR_PORT', '8787'); urllib.request.urlopen(f'http://127.0.0.1:{port}/api/health', timeout=3).read()" || exit 1

CMD ["python", "/app/app/server.py"]
