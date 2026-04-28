FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY app /app/app
COPY static /app/static

ENV NVR_HOST=0.0.0.0 \
    NVR_PORT=8080 \
    NVR_DATA_DIR=/data \
    NVR_RECORDINGS_DIR=/recordings \
    NVR_STATIC_DIR=/app/static

EXPOSE 8080

CMD ["python", "/app/app/server.py"]
