import asyncio
import http.server
import json
import sys
import threading
import uuid
import websockets

# --- Config ---
HTTP_HOST = "0.0.0.0"
HTTP_PORT = 8080
WS_PORT = 9191

# Shared state — use threading primitives since HTTP server runs in separate thread
pending = {}  # {request_id: {"event": threading.Event, "response": dict}}
addon_ws = None
addon_lock = threading.Lock()


class ProxyHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def do_GET(self):
        self.handle_request("GET")

    def do_POST(self):
        self.handle_request("POST")

    def do_PUT(self):
        self.handle_request("PUT")

    def do_DELETE(self):
        self.handle_request("DELETE")

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.end_headers()

    def handle_request(self, method):
        global addon_ws

        with addon_lock:
            ws = addon_ws

        if not ws:
            self.send_json(503, {"error": "Kodi add-on not connected"})
            return

        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length) if content_length > 0 else b""

        request_id = str(uuid.uuid4())
        event = threading.Event()
        pending[request_id] = {"event": event, "response": None}

        headers = {key: self.headers[key] for key in self.headers}

        tunnel_msg = {
            "type": "request",
            "id": request_id,
            "method": method,
            "path": self.path,
            "headers": headers,
            "body": body.decode("utf-8", errors="replace"),
        }

        # Send via the WebSocket — use the asyncio loop to schedule the send
        try:
            future = asyncio.run_coroutine_threadsafe(
                ws_send(ws, json.dumps(tunnel_msg)),
                ws_loop
            )
            future.result(timeout=5)  # Wait for send to complete
        except Exception as e:
            pending.pop(request_id, None)
            self.send_json(502, {"error": f"Failed to send to add-on: {e}"})
            return

        # Wait for response (timeout 15s)
        if not event.wait(timeout=15):
            pending.pop(request_id, None)
            self.send_json(504, {"error": "Timed out waiting for Kodi"})
            return

        response = pending.pop(request_id, {}).get("response")
        if not response:
            self.send_json(502, {"error": "No response from add-on"})
            return

        status = response.get("status", 200)
        self.send_response(status)
        for key, val in response.get("headers", {}).items():
            if key.lower() not in ("transfer-encoding", "connection"):
                self.send_header(key, val)
        self.end_headers()
        resp_body = response.get("body", "")
        if isinstance(resp_body, str):
            resp_body = resp_body.encode("utf-8")
        self.wfile.write(resp_body)

    def send_json(self, status, data):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode("utf-8"))


async def ws_send(ws, message):
    """Send a message through the WebSocket."""
    await ws.send(message)


def ws_send_handler(ws, message):
    """Thread-safe WebSocket send."""
    try:
        future = asyncio.run_coroutine_threadsafe(ws_send(ws, message), ws_loop)
        future.result(timeout=5)
    except Exception as e:
        print(f"[proxy] Send error: {e}")


async def addon_handler(websocket):
    """Handle WebSocket connections from the Kodi add-on."""
    global addon_ws
    addon_ws = websocket
    print("[proxy] Kodi add-on connected from Xbox")

    try:
        async for message in websocket:
            try:
                data = json.loads(message)
            except json.JSONDecodeError:
                continue

            if data.get("type") == "response":
                req_id = data.get("id")
                if req_id in pending:
                    pending[req_id]["response"] = data
                    pending[req_id]["event"].set()

            elif data.get("type") == "connected":
                print("[proxy] Add-on ready")
    except websockets.exceptions.ConnectionClosed:
        pass
    finally:
        addon_ws = None
        print("[proxy] Add-on disconnected")


async def start_ws_server():
    print(f"[proxy] WebSocket server listening on port {WS_PORT}")
    async with websockets.serve(addon_handler, "0.0.0.0", WS_PORT):
        await asyncio.Future()


def start_http_server():
    server = http.server.HTTPServer((HTTP_HOST, HTTP_PORT), ProxyHandler)
    print(f"[proxy] HTTP proxy listening on port {HTTP_PORT}")
    print(f"[proxy] Open http://localhost:{HTTP_PORT} in your browser")
    server.serve_forever()


# Global reference to the asyncio event loop (set in main)
ws_loop = None


def main():
    global ws_loop

    print("=" * 50)
    print("Kodi Xbox Proxy Server")
    print("=" * 50)
    print(f"  Browser URL:  http://localhost:{HTTP_PORT}")
    print(f"  Add-on WS:    ws://0.0.0.0:{WS_PORT}")
    print()

    # Create a new event loop for the WebSocket server
    ws_loop = asyncio.new_event_loop()

    # Start HTTP server in a thread
    http_thread = threading.Thread(target=start_http_server, daemon=True)
    http_thread.start()

    # Run WebSocket server in the main thread with our event loop
    try:
        ws_loop.run_until_complete(start_ws_server())
    except KeyboardInterrupt:
        print("\n[proxy] Shutting down")
        sys.exit(0)


if __name__ == "__main__":
    main()
