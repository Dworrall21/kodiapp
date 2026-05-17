"""HTTP request handler for the proxy server."""

import asyncio
import base64
import gzip
import json
import mimetypes
import os
import re
import threading
import time
import uuid
from urllib.parse import unquote, urlsplit

import http.server

from . import state
from .compression import gzip_compress
from .config import ADDON_REQUEST_TIMEOUT, PROJECT_DIR, WS_SEND_TIMEOUT, SSE_KEEPALIVE
from .websocket_server import ws_send_compressed
from .web_ui import WEB_UI_HTML
from . import repo_manager

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

# Kodi's Chorus web UI uses absolute /jsonrpc calls from inside the iframe.
# Browser reloads can also send conditional cache headers; urllib in the add-on
# raises 304 responses as errors, and the iframe may not have a useful cached
# body in a different tab. Strip conditionals so the tunnel returns fresh bodies.
CONDITIONAL_REQUEST_HEADERS = {
    "if-match",
    "if-none-match",
    "if-modified-since",
    "if-unmodified-since",
    "if-range",
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
        path = unquote(self.path.split("?", 1)[0])
        if path == "/repo":
            path = "/repo/"
        if not path.startswith("/repo/"):
            return False

        rel = path[len("/repo/"):]
        if rel == "":
            target = repo_manager.REPO_STATIC / "index.html"
        else:
            target = (repo_manager.REPO_STATIC / rel).resolve()
            repo_root = repo_manager.REPO_STATIC.resolve()
            if repo_root not in target.parents and target != repo_root:
                self.send_json(403, {"error": "Invalid repo path"})
                return True
            if target.is_dir():
                target = target / "index.html"

        if not target.exists() or not target.is_file():
            self.send_json(404, {"error": f"Repo file not found: {rel or 'index.html'}"})
            return True

        content_type = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        if target.suffix == ".md5":
            content_type = "text/plain"
        elif target.suffix == ".xml":
            content_type = "text/xml"
        self.serve_absolute_file(target, content_type, send_body=send_body)
        return True

    def serve_absolute_file(self, filepath, content_type="application/octet-stream", send_body=True):
        try:
            content = filepath.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Connection", "close")
            self.end_headers()
            if send_body:
                self.wfile.write(content)
        except Exception as e:
            self.send_json(500, {"error": str(e)})

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
        if path == "/jsonrpc":
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
        if self.path.split("?", 1)[0] == "/jsonrpc":
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

        if path in ("live", "live/"):
            self.handle_live_snapshot()
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

        if path in ("repo/status", "repo/status/"):
            self.handle_repo_status()
            return

        if path in ("repo/build", "repo/build/"):
            body = self._json_body()
            self._safe_repo_action(lambda: repo_manager.build_package(body.get("version") or None))
            return

        if path in ("repo/publish", "repo/publish/"):
            self._safe_repo_action(repo_manager.publish_local)
            return

        if path in ("repo/deploy", "repo/deploy/"):
            self._safe_repo_action(repo_manager.deploy_gh_pages)
            return

        if path in ("repo/build-publish", "repo/build-publish/"):
            body = self._json_body()
            def action():
                build = repo_manager.build_package(body.get("version") or None)
                publish = repo_manager.publish_local()
                return {"build": build, "publish": publish}
            self._safe_repo_action(action)
            return

        if path in ("repo/kodi-action", "repo/kodi-action/"):
            body = self._json_body()
            action = body.get("action", "refresh_repos")
            self.handle_kodi_management_action(action, body)
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

        # --- POV Fork endpoints ---

        if path in ("povfork/status", "povfork/status/") or path.startswith("povfork/status?"):
            self.handle_povfork_status()
            return

        if path in ("povfork/logs", "povfork/logs/") or path.startswith("povfork/logs?"):
            lines = 200
            raw_query = urlsplit("/api/" + path).query
            for param in raw_query.split("&") if raw_query else []:
                if param.startswith("lines="):
                    try:
                        lines = int(param.split("=", 1)[1])
                    except ValueError:
                        pass
            self.handle_povfork_logs(lines)
            return

        if path in ("povfork/command", "povfork/command/"):
            body = self._json_body()
            self.handle_povfork_command(body)
            return

        if path in ("povfork/install", "povfork/install/"):
            body = self._json_body()
            self.handle_povfork_install(body)
            return

        if path in ("povfork/enable", "povfork/enable/"):
            self.handle_povfork_set_enabled(True)
            return

        if path in ("povfork/disable", "povfork/disable/"):
            self.handle_povfork_set_enabled(False)
            return

        self.send_json(404, {"error": "Unknown API endpoint"})

    def _json_body(self):
        body = self.read_body()
        if not body:
            return {}
        try:
            return json.loads(body)
        except json.JSONDecodeError:
            return {}

    def _safe_repo_action(self, func):
        try:
            self.send_json(200, {"ok": True, "result": func()})
        except Exception as exc:
            self.send_json(500, {"ok": False, "error": str(exc)})

    def handle_repo_status(self):
        data = repo_manager.status()
        data["kodi"] = {
            "addon": self.kodi_jsonrpc("Addons.GetAddonDetails", {
                "addonid": repo_manager.ADDON_ID,
                "properties": ["name", "version", "enabled", "path", "dependencies"],
            }),
            "repository": self.kodi_jsonrpc("Addons.GetAddonDetails", {
                "addonid": repo_manager.REPOSITORY_ID,
                "properties": ["name", "version", "enabled"],
            }),
            "sources": self.kodi_jsonrpc("Files.GetSources", {"media": "files"}),
        }
        self.send_json(200, data)

    def handle_kodi_management_action(self, action, body=None):
        body = body or {}
        allowed = {
            "refresh_repos",
            "install_addon",
            "update_addon",
            "open_addon_browser",
            "open_sources",
            "install_zip_url",
        }
        if action not in allowed:
            self.send_json(400, {"ok": False, "error": f"Unsupported action: {action}"})
            return
        addon_id = body.get("addon_id") or repo_manager.ADDON_ID
        if not re.match(r"^[A-Za-z0-9_.-]+$", str(addon_id)):
            self.send_json(400, {"ok": False, "error": "Invalid addon_id"})
            return
        response = self.roundtrip_to_addon({
            "type": "management",
            "action": action,
            "addon_id": addon_id,
            "repository_id": body.get("repository_id") or repo_manager.REPOSITORY_ID,
            "source_url": body.get("source_url") or repo_manager.GH_PAGES_URL,
            "zip_url": body.get("zip_url") or "",
        }, timeout=ADDON_REQUEST_TIMEOUT)
        if response is None:
            return
        body = response.get("body", {}) or {}
        if isinstance(body, dict) and "Unknown message type: management" in str(body):
            body["hint"] = "Installed add-on is older than v1.0.7. Publish v1.0.7, update once from Kodi's add-on manager, then these remote management buttons will work."
        self.send_json(response.get("status", 200), body)

    # --- POV Fork handlers ---

    POVFORK_ADDON_ID = "plugin.video.povfork"

    def _povfork_addon_info(self):
        """Get POV Fork addon details from Kodi via the proxy addon."""
        return self.kodi_jsonrpc("Addons.GetAddonDetails", {
            "addonid": self.POVFORK_ADDON_ID,
            "properties": ["name", "version", "enabled", "path", "dependencies"],
        })

    def handle_povfork_status(self):
        """Return POV Fork addon status, settings, and repo availability."""
        addon_info = self._povfork_addon_info()
        repo_status = repo_manager.status()
        result = {
            "addon": addon_info,
            "repo": {
                "local_source_url": repo_status.get("local_source_url"),
                "gh_pages_url": repo_status.get("gh_pages_url"),
                "latest_zip": repo_status.get("latest_static_zip"),
            },
        }
        povfork_zip = os.path.join(repo_manager.REPO_STATIC, "plugin.video.povfork",
                                   "plugin.video.povfork-6.05.20.zip")
        result["repo"]["povfork_zip_exists"] = os.path.isfile(povfork_zip)
        result["repo"]["povfork_zip_path"] = povfork_zip
        self.send_json(200, result)

    def handle_povfork_logs(self, lines=200):
        """Return Kodi log lines filtered for POV Fork activity."""
        response = self.send_request_to_addon("get_logs", {"lines": lines},
                                              timeout=ADDON_REQUEST_TIMEOUT)
        if response is None:
            self.send_json(503, {"error": "Xbox proxy addon not connected",
                                  "lines": [], "filtered": []})
            return
        body = response.get("body", {})
        all_lines = body.get("lines", [])
        if isinstance(all_lines, str):
            all_lines = all_lines.split("\n")
        filtered = [l for l in all_lines if "pov" in l.lower() or "povfork" in l.lower()]
        self.send_json(200, {
            "path": body.get("path"),
            "total_lines": len(all_lines),
            "filtered_lines": len(filtered),
            "lines": filtered if filtered else all_lines[-50:],
            "truncated_to": lines,
        })

    def handle_povfork_command(self, body):
        """Send a command to POV Fork via Kodi JSON-RPC.

        Actions: enable, disable, execute (run action), jsonrpc (raw method)
        """
        action = body.get("action", "")
        if action == "enable":
            self.handle_povfork_set_enabled(True)
            return
        if action == "disable":
            self.handle_povfork_set_enabled(False)
            return
        if action == "execute":
            pov_action = body.get("pov_action", "")
            if not pov_action:
                self.send_json(400, {"error": "Missing pov_action parameter"})
                return
            result = self.kodi_jsonrpc("Addons.ExecuteAddon", {
                "addonid": self.POVFORK_ADDON_ID,
                "params": [pov_action],
            })
            self.send_json(200, {"ok": True, "action": action, "result": result})
            return
        if action == "jsonrpc":
            method = body.get("method", "")
            params = body.get("params", {})
            if not method:
                self.send_json(400, {"error": "Missing method parameter"})
                return
            result = self.kodi_jsonrpc(method, params)
            self.send_json(200, {"ok": True, "method": method, "result": result})
            return
        self.send_json(400, {"error": f"Unknown command action: {action}"})

    def handle_povfork_install(self, body):
        """Install or update POV Fork from the local repo or a zip URL."""
        version = body.get("version")
        zip_url = body.get("zip_url", "")

        if not zip_url:
            lan_ip = repo_manager.get_lan_ip()
            zip_url = f"http://{lan_ip}:8080/repo/plugin.video.povfork/plugin.video.povfork-6.05.20.zip"
            if version:
                zip_url = f"http://{lan_ip}:8080/repo/plugin.video.povfork/plugin.video.povfork-{version}.zip"

        response = self.roundtrip_to_addon({
            "type": "management",
            "action": "install_zip_url",
            "addonid": self.POVFORK_ADDON_ID,
            "zip_url": zip_url,
        }, timeout=60)
        if response is None:
            self.send_json(503, {"error": "Xbox proxy addon not connected"})
            return
        resp_body = response.get("body", {})
        self.send_json(response.get("status", 200), {
            "ok": resp_body.get("ok", False),
            "zip_url": zip_url,
            "result": resp_body,
        })

    def handle_povfork_set_enabled(self, enabled):
        """Enable or disable the POV Fork addon."""
        result = self.kodi_jsonrpc("Addons.SetAddonEnabled", {
            "addonid": self.POVFORK_ADDON_ID,
            "enabled": enabled,
        })
        self.send_json(200, {
            "ok": True,
            "action": "enable" if enabled else "disable",
            "addonid": self.POVFORK_ADDON_ID,
            "enabled": enabled,
            "result": result,
        })

    def handle_live_snapshot(self):
        """Return a dashboard-friendly live snapshot via Kodi JSON-RPC.

        This intentionally polls Kodi on demand instead of relying only on the
        add-on's background telemetry thread. JSON-RPC has proven reliable even
        on Xbox when some InfoLabels/events are flaky or only update while media
        is actively playing.
        """
        active = self.kodi_jsonrpc("Player.GetActivePlayers")
        app = self.kodi_jsonrpc("Application.GetProperties", {
            "properties": ["volume", "muted", "name", "version"]
        })
        labels = self.kodi_jsonrpc("XBMC.GetInfoLabels", {
            "labels": [
                "System.CPUUsage",
                "System.Memory(free)",
                "System.Memory(total)",
                "System.Uptime",
                "System.TotalUptime",
                "System.CPUTemperature",
                "System.GPUTemperature",
                "System.Temperature",
                "System.ScreenResolution",
            ]
        })

        players = active.get("result") if isinstance(active, dict) else []
        players = players if isinstance(players, list) else []
        now_playing = {"playing": False}

        if players:
            player = players[0]
            player_id = player.get("playerid", 1)
            item = self.kodi_jsonrpc("Player.GetItem", {
                "playerid": player_id,
                "properties": [
                    "title", "showtitle", "album", "artist", "season", "episode",
                    "duration", "file", "thumbnail",
                ],
            })
            props = self.kodi_jsonrpc("Player.GetProperties", {
                "playerid": player_id,
                "properties": ["speed", "time", "totaltime", "percentage"],
            })
            item_data = ((item.get("result") or {}).get("item") or {}) if isinstance(item, dict) else {}
            props_data = (props.get("result") or {}) if isinstance(props, dict) else {}
            title = item_data.get("title") or item_data.get("label") or item_data.get("file") or "Unknown"
            subtitle_bits = []
            if item_data.get("showtitle"):
                subtitle_bits.append(item_data.get("showtitle"))
            if item_data.get("season") not in (None, "") and item_data.get("episode") not in (None, ""):
                subtitle_bits.append(f"S{item_data.get('season')}E{item_data.get('episode')}")
            now_playing = {
                "playing": True,
                "playerid": player_id,
                "player_type": player.get("type") or item_data.get("type") or "media",
                "title": title,
                "subtitle": " · ".join(str(x) for x in subtitle_bits if x),
                "time": self._time_to_seconds(props_data.get("time")),
                "duration": self._time_to_seconds(props_data.get("totaltime")) or item_data.get("duration"),
                "progress": props_data.get("percentage", 0),
                "speed": props_data.get("speed"),
            }

        label_result = labels.get("result") if isinstance(labels, dict) else {}
        app_result = app.get("result") if isinstance(app, dict) else {}
        stats = {
            "cpu": self._first_nonempty(label_result, "System.CPUUsage"),
            "memory_free": self._first_nonempty(label_result, "System.Memory(free)"),
            "memory_total": self._first_nonempty(label_result, "System.Memory(total)"),
            "uptime": self._first_nonempty(label_result, "System.Uptime", "System.TotalUptime"),
            "temperature": self._first_nonempty(
                label_result,
                "System.CPUTemperature",
                "System.GPUTemperature",
                "System.Temperature",
            ),
            "screen_resolution": self._first_nonempty(label_result, "System.ScreenResolution"),
        }
        volume = {
            "volume": app_result.get("volume"),
            "muted": app_result.get("muted"),
        }

        self.send_json(200, {
            "connected": state.addon_ws is not None,
            "now_playing": now_playing,
            "stats": stats,
            "volume": volume,
        })

    def kodi_jsonrpc(self, method, params=None):
        response = self.roundtrip_to_addon({
            "type": "jsonrpc",
            "method": method,
            "params": params or {},
        }, timeout=ADDON_REQUEST_TIMEOUT)
        if response is None:
            return {}
        return response.get("body", {}) or {}

    @staticmethod
    def _time_to_seconds(value):
        if not isinstance(value, dict):
            return value or 0
        return (
            int(value.get("hours") or 0) * 3600
            + int(value.get("minutes") or 0) * 60
            + int(value.get("seconds") or 0)
            + float(value.get("milliseconds") or 0) / 1000.0
        )

    @staticmethod
    def _first_nonempty(mapping, *keys):
        for key in keys:
            val = (mapping or {}).get(key)
            if val not in (None, ""):
                return val
        return ""

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
            and key.lower() not in CONDITIONAL_REQUEST_HEADERS
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
        if self.path.split("?", 1)[0].startswith(("/_kodi_", "/jsonrpc")):
            self.send_header("Cache-Control", "no-store")
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
