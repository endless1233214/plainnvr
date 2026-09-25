import threading
from http.server import ThreadingHTTPServer


class NvrHTTPServer(ThreadingHTTPServer):
    """Thread-bounded HTTP server for web, playback, and camera clients."""

    def __init__(
        self,
        address,
        handler,
        max_connections=128,
    ):
        self.connection_slots = (
            threading.BoundedSemaphore(
                max_connections
            )
        )
        super().__init__(address, handler)

    def process_request(
        self,
        request,
        client_address,
    ):
        if not self.connection_slots.acquire(
            blocking=False
        ):
            try:
                request.settimeout(1)
                request.sendall(
                    b"HTTP/1.1 503 Service Unavailable\r\n"
                    b"Content-Length: 0\r\n"
                    b"Connection: close\r\n"
                    b"Retry-After: 1\r\n"
                    b"\r\n"
                )
            except OSError:
                pass
            finally:
                self.shutdown_request(request)
            return

        try:
            super().process_request(
                request,
                client_address,
            )
        except Exception:
            self.connection_slots.release()
            raise

    def process_request_thread(
        self,
        request,
        client_address,
    ):
        try:
            super().process_request_thread(
                request,
                client_address,
            )
        finally:
            self.connection_slots.release()
