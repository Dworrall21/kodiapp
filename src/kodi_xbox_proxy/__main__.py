"""Kodi Xbox Proxy Server — main entry point."""

import asyncio
import http.server
import socket
import sys
import threading

import websockets

from . import state
from .config import HTTP_HOST, HTTP_PORT, WS_PORT
from .websocket_server import addon_handler
from .http_handler import ProxyHandler


def _serve_http(host, port):
    """Start HTTP server with SO_REUSEADDR to handle quick restarts."""
    server = http.server.ThreadingHTTPServer((host, port), ProxyHandler)
    server.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.serve_forever()


def run(host=HTTP_HOST, port=HTTP_PORT, ws_port=WS_PORT):
    """Start the Kodi Xbox Proxy Server."""
    print("=" * 50)
    print("Kodi Xbox Proxy Server")
    print("=" * 50)
    print(f"  Dashboard:   http://localhost:{port}")
    print(f"  Kodi Web UI: http://localhost:{port}/_kodi_/")
    print(f"  API:         http://localhost:{port}/api/")
    print(f"  SSE Events:  http://localhost:{port}/api/events")
    print(f"  Add-on WS:   ws://0.0.0.0:{ws_port}")
    print()

    http_thread = threading.Thread(
        target=_serve_http,
        args=(host, port),
        daemon=True,
    )
    http_thread.start()
    print(f"[proxy] HTTP server listening on {host}:{port}")

    async def main():
        state.ws_loop = asyncio.get_running_loop()
        print(f"[proxy] WebSocket server listening on port {ws_port}")
        async with websockets.serve(
            addon_handler,
            "0.0.0.0",
            ws_port,
            ping_interval=20,
            ping_timeout=10,
            close_timeout=5,
        ):
            await asyncio.Future()

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[proxy] Shutting down")
        sys.exit(0)


if __name__ == "__main__":
    run()
