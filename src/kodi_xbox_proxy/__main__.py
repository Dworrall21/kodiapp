"""Kodi Xbox Proxy Server — main entry point."""

import asyncio
import http.server
import signal
import sys
import threading

import websockets

from .config import HTTP_HOST, HTTP_PORT, WS_PORT
from .state import addon_info, addon_lock, addon_ws, pending, sse_clients, sse_lock
from .websocket_server import addon_handler, ws_loop as _ws_loop, ws_send_compressed
from .http_handler import ProxyHandler


def run(host=HTTP_HOST, port=HTTP_PORT, ws_port=WS_PORT):
    """Start the Kodi Xbox Proxy Server."""
    global _ws_loop

    print("=" * 50)
    print("Kodi Xbox Proxy Server")
    print("=" * 50)
    print(f"  Dashboard:   http://localhost:{port}")
    print(f"  Kodi Web UI: http://localhost:{port}/_kodi_/")
    print(f"  API:         http://localhost:{port}/api/")
    print(f"  SSE Events:  http://localhost:{port}/api/events")
    print(f"  Add-on WS:   ws://0.0.0.0:{ws_port}")
    print()

    # Start HTTP server in a daemon thread
    http_thread = threading.Thread(
        target=lambda: http.server.HTTPServer((host, port), ProxyHandler).serve_forever(),
        daemon=True,
    )
    http_thread.start()
    print(f"[proxy] HTTP server listening on {host}:{port}")

    # Start WebSocket server in the asyncio event loop
    async def main():
        _ws_loop = asyncio.get_event_loop()
        print(f"[proxy] WebSocket server listening on port {ws_port}")
        async with websockets.serve(addon_handler, "0.0.0.0", ws_port):
            await asyncio.Future()  # run forever

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[proxy] Shutting down")
        sys.exit(0)


if __name__ == "__main__":
    run()
