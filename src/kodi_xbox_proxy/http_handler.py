"""HTTP request handler for the proxy server."""

import hashlib
import json
import os
import threading
import time
import uuid

import http.server

from .compression import gzip_compress
from .config import ADDON_REQUEST_TIMEOUT, PROJECT_DIR, WS_SEND_TIMEOUT, SSE_KEEPALIVE
from .state import addon_info, addon_lock, addon_ws, pending, sse_clients, sse_lock
from .websocket_server import ws_loop, ws_send_compressed
from .web_ui import WEB_UI_HTML


class ProxyHandler(http.server.BaseHTTPRequestHandler):
    """HTTP handler for dashboard, API, repo, and Kodi proxy."""

    def log_message(self, format, *args):
        pass

    # --- File / HTML serving ---

    def serve_file(self, filename, content_type="application/octet-stream",
                   as_attachment=True, send_body=True):
        filepath = os.path.join(PROJECT_DIR, filename)
        if not os.path.isfile(filepath):
            self.send_json(404, {"error": f"{filename} not found"})
            return
        try:
            with open(filepath, "rb") as f:
                content = f.read()
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Connection", "close")
            if as_attachment:
                self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
            self.end_headers()
            if send_body:
                self.wfile.write(content)
        except Exception as e:
            self.send_json(500, {"error": str(e)})

    def serve_html(self, html, send_body=True):
        content = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Connection", "close")
        self.end_headers()
        if send_body:
            self.wfile.write(content)

    # --- Repo serving ---

    def handle_repo_get_or_head(self, send_body=True):
        path = self.path.split("?", 1)[0]

        if path in ("/repo", "/repo/"):
            self.serve_html(self._repo_index_html(), send_body=send_body)
            return True
        if path in ("/repo/script.xbox.proxy", "/repo/script.xbox.proxy/"):
            self.serve_html(self._package_index_html(), send_body=send_body)
            return True
        if path in ("/repo/script.kodi.proxytest", "/repo/script.kodi.proxytest/"):
            self.serve_html(self._proxytest_index_html(), send_body=send_body)
            return True
        if path in ("/repo/addons.xml", "/repo/addons.xml/"):
            self.serve_file("addons.xml", "text/xml", send_body=send_body)
            return True
        if path in ("/repo/addons.xml.md5", "/repo/addons.xml.md5/"):
            self._serve_addons_md5(send_body)
            return True
        if path in ("/repo/script.xbox.proxy/script.xbox.proxy-1.0.4.zip",
                     "/repo/script.xbox.proxy/script.xbox.proxy-1.0.4.zip/"):
            self.serve_file("addon.zip", "application/zip", as_attachment=False, send_body=send_body)
            return True
        if path in ("/repo/script.xbox.proxy/script.xbox.proxy-1.0.3.zip",
                     "/repo/script.xbox.proxy/script.xbox.proxy-1.0.3.zip/"):
            self.serve_file("addon.zip", "application/zip", as_attachment=False, send_body=send_body)
            return True
        if path in ("/repo/script.xbox.proxy/script.xbox.proxy-1.0.2.zip",
                     "/repo/script.xbox.proxy/script.xbox.proxy-1.0.2.zip/"):
            self.serve_file("addon-safe.zip", "application/zip", as_attachment=False, send_body=send_body)
            return True
        if path in ("/repo/script.xbox.proxy/script.xbox.proxy-1.0.1.zip",
                     "/repo/script.xbox.proxy/script.xbox.proxy-1.0.1.zip/",
                     "/repo/script.xbox.proxy/script.xbox.proxy-1.0.0.zip",
                     "/repo/script.xbox.proxy/script.xbox.proxy-1.0.0.zip/"):
            self.serve_file("addon.zip", "application/zip", as_attachment=False, send_body=send_body)
            return True
        if path in ("/repo/script.kodi.proxytest/script.kodi.proxytest-0.0.1.zip",
                     "/repo/script.kodi.proxytest/script.kodi.proxytest-0.0.1.zip/"):
            self.serve_file("proxytest.zip", "application/zip", as_attachment=False, send_body=send_body)
            return True
        return False

    def _serve_addons_md5(self, send_body):
        try:
            content = open(os.path.join(PROJECT_DIR, "addons.xml"), "rb").read()
            md5 = hashlib.md5(content).hexdigest()
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(md5)))
            self.send_header("Connection", "close")
            self.end_headers()
            if send_body:
                self.wfile.write(md5.encode())
        except FileNotFoundError:
            self.send_json(404, {"error": "addons.xml not found"})

    @staticmethod
    def _repo_index_html():
        return (
            '<!DOCTYPE html><html><head><title>Kodi Xbox Proxy Repo</title></head><body>'
            '<h1>Kodi Xbox Proxy Repo</h1><ul>'
            '<li><a href="addons.xml">addons.xml</a></li>'
            '<li><a href="addons.xml.md5">addons.xml.md5</a></li>'
            '<li><a href="script.xbox.proxy/">script.xbox.proxy/</a></li>'
            '<li><a href="script.kodi.proxytest/">script.kodi.proxytest/</a> ultra-minimal diagnostic</li>'
            '</ul></body></html>'
        )

    @staticmethod
    def _package_index_html():
        return (
            '<!DOCTYPE html><html><head><title>script.xbox.proxy</title></head><body>'
            '<h1>script.xbox.proxy</h1><ul>'
            '<li><a href="script.xbox.proxy-1.0.4.zip">script.xbox.proxy-1.0.4.zip</a> full service package (with compression)</li>'
            '<li><a href="script.xbox.proxy-1.0.3.zip">script.xbox.proxy-1.0.3.zip</a> full service package (with compression)</li>'
            '<li><a href="script.xbox.proxy-1.0.2.zip">script.xbox.proxy-1.0.2.zip</a> safe diagnostic package</li>'
            '<li><a href="script.xbox.proxy-1.0.1.zip">script.xbox.proxy-1.0.1.zip</a> full service package</li>'
            '</ul></body></html>'
        )

    @staticmethod
    def _proxytest_index_html():
        return (
            '<!DOCTYPE html><html><head><title>script.kodi.proxytest</title></head><body>'
            '<h1>script.kodi.proxytest</h1><ul>'
            '<li><a href="script.kodi.proxytest-0.0.1.zip">script.kodi.proxytest-0.0.1.zip</a> metadata-only diagnostic package</li>'
            '</ul></body></html>'
        )

    # --- HTTP method handlers ---

    def do_HEAD(self):
        if self.handle_repo_get_or_head(send_body=False):
            return
        self.send_error(404)

    def do_GET(self):
        if self.handle_repo_get_or_head(send_body=True):
            return

        path = self.path.split("?", 1)[0]

        if path == "/api/events":
            self.handle_sse()
            return

        if path in ("/", "/index.html"):
            self._serve_web_ui()
            return

        if path.startswith("/api/"):
            self.handle_api(path[5:])
            return

        self.proxy_to_kodi("GET")

    def do_POST(self):
        if self.path.startswith("/api/"):
            self.handle_api(self.path[5:])
            return
        self.proxy_to_kodi("POST")

    def do_PUT(self):
        self.proxy_to_kodi("PUT")

    def do_DELETE(self):
        self.proxy_to_kodi("DELETE")

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    # --- Web UI ---

    def _serve_web_ui(self):
        html = WEB_UI_HTML.encode("utf-8")
        accept_encoding = self.headers.get("Accept-Encoding", "")
        if "gzip" in accept_encoding:
            compressed, was_compressed = gzip_compress(html)
            if was_compressed:
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Encoding", "gzip")
                self.send_header("Content-Length", str(len(compressed)))
                self.end_headers()
                self.wfile.write(compressed)
                return
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(html)))
        self.end_headers()
        self.wfile.write(html)

    # --- SSE ---

    def handle_sse(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()

        queue = []
        ready = threading.Event()
        with sse_lock:
            sse_clients.append((queue, ready))

        try:
            self.wfile.write(b"event: connected\ndata: {}\n\n")
            self.wfile.flush()

            while True:
                ready.wait(timeout=SSE_KEEPALIVE)
                ready.clear()

                while queue:
                    event = queue.pop(0)
                    try:
                        data = json.dumps(event)
                        self.wfile.write(
                            f"event: {event.get('type', 'message')}\ndata: {data}\n\n".encode()
                        )
                        self.wfile.flush()
                    except Exception:
                        return

                try:
                    self.wfile.write(b": keepalive\n\n")
                    self.wfile.flush()
                except Exception:
                    return
        except Exception:
            pass
        finally:
            with sse_lock:
                try:
                    sse_clients.remove((queue, ready))
                except ValueError:
                    pass

    # --- API ---

    def handle_api(self, path):
        global addon_info

        if path in ("status", "status/"):
            with addon_lock:
                ws = addon_ws
                info = addon_info
            self.send_json(200, {"connected": ws is not None, "info": info})

        elif path.startswith("logs"):
            lines = 200
            if "?" in path:
                qs = path.split("?", 1)[1]
                for param in qs.split("&"):
                    if param.startswith("lines="):
                        lines = int(param.split("=", 1)[1])
            self.send_request_to_addon("get_logs", {"lines": lines}, timeout=ADDON_REQUEST_TIMEOUT)

        elif path in ("info", "info/"):
            self.send_request_to_addon("get_info", {}, timeout=10)

        elif path in ("command", "command/"):
            body = self.read_body()
            try:
                data = json.loads(body) if body else {}
            except json.JSONDecodeError:
                self.send_json(400, {"error": "Invalid JSON"})
                return
            self.send_request_to_addon(
                "kodi_command",
                {"method": data.get("method", ""), "params": data.get("params", {})},
                timeout=ADDON_REQUEST_TIMEOUT,
            )
        else:
            self.send_json(404, {"error": "Unknown API endpoint"})

    # --- Proxy to Kodi ---

    def proxy_to_kodi(self, method):
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

        tunnel_msg = {
            "type": "request",
            "id": request_id,
            "method": method,
            "path": self.path,
            "headers": {key: self.headers[key] for key in self.headers},
            "body": body.decode("utf-8", errors="replace"),
        }

        try:
            future = asyncio.run_coroutine_threadsafe(
                ws_send_compressed(ws, tunnel_msg), ws_loop
            )
            future.result(timeout=WS_SEND_TIMEOUT)
        except Exception as e:
            pending.pop(request_id, None)
            self.send_json(502, {"error": f"Failed to reach add-on: {e}"})
            return

        if not event.wait(timeout=ADDON_REQUEST_TIMEOUT):
            pending.pop(request_id, None)
            self.send_json(504, {"error": "Timed out waiting for Kodi"})
            return

        response = pending.pop(request_id, {}).get("response")
        if not response:
            self.send_json(502, {"error": "No response from add-on"})
            return

        self.send_response(response.get("status", 200))
        for key, val in response.get("headers", {}).items():
            if key.lower() not in ("transfer-encoding", "connection"):
                self.send_header(key, val)
        self.end_headers()
        resp_body = response.get("body", "")
        if isinstance(resp_body, str):
            resp_body = resp_body.encode("utf-8")
        self.wfile.write(resp_body)

    # --- Helpers ---

    def send_request_to_addon(self, msg_type, data, timeout=ADDON_REQUEST_TIMEOUT):
        with addon_lock:
            ws = addon_ws
        if not ws:
            self.send_json(503, {"error": "Kodi add-on not connected"})
            return

        request_id = str(uuid.uuid4())
        event = threading.Event()
        pending[request_id] = {"event": event, "response": None}

        msg = {"type": msg_type, "id": request_id, **data}

        try:
            future = asyncio.run_coroutine_threadsafe(
                ws_send_compressed(ws, msg), ws_loop
            )
            future.result(timeout=WS_SEND_TIMEOUT)
        except Exception as e:
            pending.pop(request_id, None)
            self.send_json(502, {"error": str(e)})
            return

        if not event.wait(timeout=timeout):
            pending.pop(request_id, None)
            self.send_json(504, {"error": "Timed out"})
            return

        response = pending.pop(request_id, {}).get("response")
        if not response:
            self.send_json(502, {"error": "No response"})
            return

        status = response.get("status", 200)
        body = response.get("body", {})
        if isinstance(body, str):
            try:
                body = json.loads(body)
            except json.JSONDecodeError:
                pass
        self.send_json(status, body)

    def read_body(self):
        content_length = int(self.headers.get("Content-Length", 0))
        if content_length > 0:
            return self.rfile.read(content_length).decode("utf-8", errors="replace")
        return ""

    def send_json(self, status, data):
        raw = json.dumps(data, default=str).encode("utf-8")
        accept_encoding = self.headers.get("Accept-Encoding", "")
        if "gzip" in accept_encoding:
            compressed, was_compressed = gzip_compress(raw)
            if was_compressed:
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Encoding", "gzip")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Content-Length", str(len(compressed)))
                self.end_headers()
                self.wfile.write(compressed)
                return
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(raw)
