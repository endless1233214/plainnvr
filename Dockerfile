# Build media dependencies from pinned source with an auditable dependency lock.
FROM golang:1.27.1-alpine3.24 AS go2rtc-build
ADD https://codeload.github.com/AlexxIT/go2rtc/tar.gz/refs/tags/v1.9.14 /tmp/go2rtc.tar.gz
RUN echo "e3d59e553dfd0085889a2956281cfc0fd78bb7b4d6269d1c90c217d2ffcf2c7b  /tmp/go2rtc.tar.gz" | sha256sum -c - \
    && mkdir /src && tar -xzf /tmp/go2rtc.tar.gz -C /src --strip-components=1
WORKDIR /src
COPY build/go2rtc/go.mod build/go2rtc/go.sum ./
RUN go mod download && go mod verify \
    && go test ./internal/webrtc ./internal/hls ./internal/rtsp ./pkg/webrtc ./pkg/rtsp \
    && go list -deps . > /compiled-packages.txt \
    && ! grep -q '^golang.org/x/crypto/openpgp' /compiled-packages.txt \
    && CGO_ENABLED=0 go build -mod=readonly -trimpath -o /go2rtc .
COPY build/go2rtc/collect-licenses.sh /collect-licenses.sh
RUN sh /collect-licenses.sh

FROM alpine:3.24 AS ffmpeg-build
RUN apk add --no-cache build-base nasm pkgconf openssl-dev
ADD https://ffmpeg.org/releases/ffmpeg-9.0.2.tar.xz /tmp/ffmpeg.tar.xz
RUN echo "8c3850283eb25fa026482078a04051e0be17347b09ef81a0849bec15a96e002e  /tmp/ffmpeg.tar.xz" | sha256sum -c - \
    && mkdir /src && tar -xJf /tmp/ffmpeg.tar.xz -C /src --strip-components=1
WORKDIR /src
COPY build/ffmpeg/configure.sh /configure.sh
COPY build/ffmpeg/mov-seek-bounds.patch /mov-seek-bounds.patch
COPY build/ffmpeg/test-mov-seek-bounds.sh /test-mov-seek-bounds.sh
RUN patch -p1 < /mov-seek-bounds.patch && sh /test-mov-seek-bounds.sh
RUN sh /configure.sh

FROM python:3.14-alpine3.24
RUN apk add --no-cache ca-certificates tzdata libssl3 libcrypto3 \
    && python -m pip uninstall -y pip
COPY --from=go2rtc-build /go2rtc /usr/local/bin/go2rtc
COPY --from=ffmpeg-build /opt/ffmpeg/bin /usr/local/bin/
COPY --from=ffmpeg-build /src/COPYING.LGPLv3 /usr/share/licenses/ffmpeg/COPYING.LGPLv3
COPY --from=go2rtc-build /licenses /usr/share/licenses/go2rtc/
COPY --from=go2rtc-build /compiled-packages.txt /usr/share/plainnvr/go2rtc-compiled-packages.txt
COPY --from=ffmpeg-build /src/config_components.h /usr/share/plainnvr/ffmpeg-config-components.h
COPY build/ffmpeg/configure.sh /usr/share/plainnvr/ffmpeg-configure.sh

WORKDIR /app

COPY app /app/app
COPY static /app/static
RUN chmod -R a+rX /app/app /app/static \
    && mkdir -p /data /recordings && chown 568:568 /data /recordings

ENV NVR_HOST=0.0.0.0 \
    NVR_PORT=8787 \
    NVR_DATA_DIR=/data \
    NVR_RECORDINGS_DIR=/recordings \
    NVR_STATIC_DIR=/app/static

EXPOSE 8787 8554 8555/tcp 8555/udp

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import os, urllib.request; port = os.environ.get('NVR_PORT', '8787'); urllib.request.urlopen(f'http://127.0.0.1:{port}/api/health', timeout=3).read()" || exit 1

USER 568:568

CMD ["python", "/app/app/server.py"]
