"""TCP HWLINK simulator server (ARC-006).

Run with ``hwval-studio --simulator-server --role hwval`` and connect a client
to ``tcp://127.0.0.1:7000``.  Each connection gets an independent device.
"""

from __future__ import annotations

import argparse
import socketserver
import threading
from typing import Any

from hwval_studio.protocol.link import FrameParser, build_raw, cobs_encode
from hwval_studio.simulator.device import SimulatedDevice


class _Handler(socketserver.BaseRequestHandler):
    device: SimulatedDevice

    def handle(self) -> None:
        parser = FrameParser()
        self.request.settimeout(0.05)
        while True:
            try:
                data = self.request.recv(4096)
            except TimeoutError:
                for event in self.device.poll():
                    try:
                        self.request.sendall(cobs_encode(event))
                    except OSError:
                        return
                continue
            except OSError:
                return
            if not data:
                return
            for frame in parser.feed(data):
                replies = self.device.handle_frame(build_raw(frame.payload, frame.seq, frame.flags))
                for reply in replies:
                    try:
                        self.request.sendall(cobs_encode(reply))
                    except OSError:
                        return


class SimulatorServer:
    def __init__(self, host: str = "127.0.0.1", port: int = 7000, role: str = "hwval") -> None:
        self.host = host
        self.port = port
        self.role = role
        self._server: socketserver.ThreadingTCPServer | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        role = self.role

        class Handler(_Handler):
            def __init__(self, *args: Any, **kwargs: Any) -> None:
                self.device = SimulatedDevice(role, auto_answer=False)
                super().__init__(*args, **kwargs)

        class Server(socketserver.ThreadingTCPServer):
            allow_reuse_address = True
            daemon_threads = True

        self._server = Server((self.host, self.port), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def serve_forever(self) -> None:
        self.start()
        if self._thread is not None:
            self._thread.join()

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
        self._thread = None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="HWLINK device simulator server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=7000)
    parser.add_argument("--role", choices=["hwval", "boot", "demo"], default="hwval")
    args = parser.parse_args(argv)
    server = SimulatorServer(args.host, args.port, args.role)
    server.start()
    print(f"HWVAL simulator ({args.role}) listening on tcp://{args.host}:{args.port}")
    try:
        while True:
            threading.Event().wait(1.0)
    except KeyboardInterrupt:
        server.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
