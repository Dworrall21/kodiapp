"""HTTP request handler for the proxy server."""

import asyncio
import base64
import gzip
import json
import os
import threading
import time
import uuid
from urllib.parse import urlsplit

import http.server

from . import state
from .compression import gzip_compress
from .config import ADDON_REQUEST_TIMEOUT, PROJECT_DIR, WS_SEND_TIMEOUT, SSE_KEEPALIVE
from .websocket_server import ws_send_compressed
from .web_ui import WEB_UI_HTML

HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
}


class ProxyHandler(http.server.BaseHTTPRequestHandler):
    """HTTP handler for dashboard, API, repo, and Kodi proxy."""

    protocol_version = "HTTP/1.1"

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
        return False

    def _serve_addons_md5(self, send_body):
        try:
            content = open(os.path.join(PROJECT_DIR, "addons.xml"), "rb").read()
            md5 = __import__("hashlib").md5(content).hexdigest()
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
            '</ul></body></html>'
        )

    @staticmethod
    def _package_index_html():
        return (
            '<!DOCTYPE html><html><head><title>script.xbox.proxy</title></head><body>'
            '<h1>script.xbox.proxy</h1><ul>'
            '<li><a href="script.xbox.proxy-1.0.4.zip">script.xbox.proxy-1.0.4.zip</a></li>'
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
            self.handle_api(self.path[5:])
            return
        if path.startswith("/_kodi_"):
            self.proxy_to_kodi("GET")
            return

        self.send_json(404, {"error": "Not found"})

    def do_POST(self):
        if self.path.startswith("/api/"):
            self.handle_api(self.path[5:])
            return
        if self.path.split("?", 1)[0].startswith("/_kodi_"):
            self.proxy_to_kodi("POST")
            return
        self.send_json(404, {"error": "Not found"})

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Content-Length", "0")
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
        with state.sse_lock:
            state.sse_clients.append((queue, ready))

        try:
            self.wfile.write(b"data: {\"type\":\"connected\",\"data\":{}}\n\n")
            self.wfile.flush()

            while True:
                ready.wait(timeout=SSE_KEEPALIVE)
                ready.clear()

                while queue:
                    event = queue.pop(0)
                    try:
                        data = json.dumps(event, default=str)
                        # Browser code uses EventSource.onmessage, so do not send named SSE events.
                        self.wfile.write(f"data: {data}\n\n".encode())
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
            with state.sse_lock:
                try:
                    state.sse_clients.remove((queue, ready))
                except ValueError:
                    pass

    # --- API ---

    def handle_api(self, path):
        if path in ("status", "status/"):
            with state.addon_lock:
                ws = state.addon_ws
                info = state.addon_info
            self.send_json(200, {"connected": ws is not None, "info": info})
            return

        if path.startswith("logs"):
            lines = 200
            raw_query = urlsplit("/api/" + path).query
            for param in raw_query.split("&") if raw_query else []:
                if param.startswith("lines="):
                    try:
                        lines = int(param.split("=", 1)[1])
                    except ValueError:
                        pass
            self.send_request_to_addon("get_logs", {"lines": lines}, timeout=ADDON_REQUEST_TIMEOUT)
            return

        if path in ("info", "info/"):
            self.send_json(200, {"connected": state.addon_ws is not None, "info": state.addon_info})
            return

        if path in ("command", "command/"):
            body = self.read_body()
            try:
                data = json.loads(body) if body else {}
            except json.JSONDecodeError:
                self.send_json(400, {"error": "Invalid JSON"})
                return
            self.send_request_to_addon(
                "jsonrpc",
                {"method": data.get("method", ""), "params": data.get("params", {})},
                timeout=ADDON_REQUEST_TIMEOUT,
            )
            return

        if path in ("events", "events/"):
            self.send_json(200, {"events": state.latest_event_log})
            return

        self.send_json(404, {"error": "Unknown API endpoint"})

    # --- Proxy to Kodi ---

    def _kodi_path(self):
        path = self.path
        if path.startswith("/_kodi_/"):
            return "/" + path[len("/_kodi_/"):]
        if path == "/_kodi_":
            return "/"
        if path.startswith("/_kodi_?"):
            return "/" + path[len("/_kodi_"):]
        return path

    def proxy_to_kodi(self, method):
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length) if content_length > 0 else b""

        headers = {
            key: self.headers[key]
            for key in self.headers
            if key.lower() not in HOP_HEADERS
        }

        msg = {
            "type": "http_request",
            "method": method,
            "path": self._kodi_path(),
            "headers": headers,
        }
        if body:
            msg["body"] = base64.b64encode(body).decode("ascii")
            msg["body_encoding"] = "base64"

        response = self.roundtrip_to_addon(msg, timeout=ADDON_REQUEST_TIMEOUT)
        if response is None:
            return

        status = response.get("status", 200)
        headers = response.get("headers", {}) or {}
        raw_body = response.get("body", "")
        encoding = response.get("body_encoding", "utf-8")
        if encoding == "base64":
            try:
                resp_body = base64.b64decode(raw_body)
            except Exception:
                self.send_json(502, {"error": "Invalid base64 response body from add-on"})
                return
        elif isinstance(raw_body, str):
            resp_body = raw_body.encode("utf-8")
        else:
            resp_body = raw_body or b""

        self.send_response(status)
        for key, val in headers.items():
            if key.lower() not in HOP_HEADERS and key.lower() != "content-length":
                self.send_header(key, str(val))
        self.send_header("Content-Length", str(len(resp_body)))
        self.end_headers()
        self.wfile.write(resp_body)

    # --- Add-on request helpers ---

    def roundtrip_to_addon(self, msg, timeout=ADDON_REQUEST_TIMEOUT):
        with state.addon_lock:
            ws = state.addon_ws
            loop = state.ws_loop
        if not ws or not loop:
            self.send_json(503, {"error": "Kodi add-on not connected"})
            return None

        request_id = msg.get("id") or str(uuid.uuid4())
        msg["id"] = request_id
        event = threading.Event()
        state.pending[request_id] = {"event": event, "response": None}

        try:
            future = asyncio.run_coroutine_threadsafe(ws_send_compressed(ws, msg), loop)
            future.result(timeout=WS_SEND_TIMEOUT)
        except Exception as e:
            state.pending.pop(request_id, None)
            self.send_json(502, {"error": f"Failed to reach add-on: {e}"})
            return None

        if not event.wait(timeout=timeout):
            state.pending.pop(request_id, None)
            self.send_json(504, {"error": "Timed out waiting for Kodi"})
            return None

        response = state.pending.pop(request_id, {}).get("response")
        if not response:
            self.send_json(502, {"error": "No response from add-on"})
            return None
        return response

    def send_request_to_addon(self, msg_type, data, timeout=ADDON_REQUEST_TIMEOUT):
        msg = {"type": msg_type, **(data or {})}
        response = self.roundtrip_to_addon(msg, timeout=timeout)
        if response is None:
            return
        status = response.get("status", 200)
        body = response.get("body", {})
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
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)
