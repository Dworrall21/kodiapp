# -*- coding: utf-8 -*-
"""Robust Xbox Web Proxy service for Kodi.

Protocol v2:
- Client opens an outbound WebSocket to the bridge.
- Text frames are plain JSON.
- Binary frames use a one-byte envelope: 0x00 raw JSON bytes, 0x01 zlib JSON bytes.
- HTTP bodies are returned as utf-8 text or base64 binary using body_encoding.

iPhone Remote Bridge (Option B2):
- Optional custom iPhone remote app mode.
- The iPhone app listens on the LAN while foregrounded.
- This add-on connects outbound to the iPhone app and receives JSON-line commands.
- This is not official Kore compatibility and does not require inbound Xbox LAN access.
"""
from __future__ import unicode_literals

import base64
import collections
import hashlib
import json
import os
import random
import socket
import struct
import sys
import threading
import time
import traceback
import urllib.request
import zipfile
import zlib

import xbmc
import xbmcaddon
import xbmcvfs

# ssl imported lazily to avoid UWP sandbox issues on Xbox
ssl = None

try:
    from iphone_bridge import (
        BridgeProtocolError,
        encode_json_line,
        extract_json_lines,
        is_timeout_error,
        make_auth_message,
        make_error_message,
        make_hello_message,
        make_result_message,
    )
except Exception:
    try:
        from addon.iphone_bridge import (
            BridgeProtocolError,
            encode_json_line,
            extract_json_lines,
            is_timeout_error,
            make_auth_message,
            make_error_message,
            make_hello_message,
            make_result_message,
        )
    except Exception:
        BridgeProtocolError = ValueError
        encode_json_line = None
        extract_json_lines = None
        is_timeout_error = None
        make_auth_message = None
        make_error_message = None
        make_hello_message = None
        make_result_message = None

ADDON = xbmcaddon.Addon()
ADDON_ID = ADDON.getAddonInfo("id")
ADDON_VERSION = ADDON.getAddonInfo("version")
ADDON_NAME = ADDON.getAddonInfo("name") or ADDON_ID
GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
PROTOCOL_VERSION = 2
MAX_FRAME_BYTES = 4 * 1024 * 1024
MAX_REQUEST_BODY_BYTES = 4 * 1024 * 1024
MAX_LOG_LINES = 1000
TEXT_TYPES = ("text/", "application/json", "application/javascript", "application/xml", "application/xhtml+xml", "image/svg+xml")
ALLOWED_METHODS = {"GET", "POST", "HEAD", "OPTIONS"}
HOP_HEADERS = {"connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "te", "trailer", "transfer-encoding", "upgrade"}


def log(msg, level=xbmc.LOGINFO):
    try:
        xbmc.log("[%s] %s" % (ADDON_ID, msg), level)
    except Exception:
        pass


def setting(name, default=""):
    try:
        value = ADDON.getSetting(name)
        return value if value not in (None, "") else default
    except Exception:
        return default


def int_setting(name, default, lo=None, hi=None):
    try:
        value = int(setting(name, str(default)))
    except Exception:
        value = default
    if lo is not None:
        value = max(lo, value)
    if hi is not None:
        value = min(hi, value)
    return value


def bool_setting(name, default=False):
    value = setting(name, "true" if default else "false").lower().strip()
    return value in ("1", "true", "yes", "on")


def config():
    return {
        "bridge_host": setting("bridge_host", "127.0.0.1"),
        "bridge_port": int_setting("bridge_port", 8765, 1, 65535),
        "bridge_path": setting("bridge_path", "/"),
        "use_tls": bool_setting("use_tls", False),
        "verify_tls": bool_setting("verify_tls", True),
        "auth_token": setting("auth_token", ""),
        "kodi_host": setting("kodi_host", "127.0.0.1"),
        "kodi_port": int_setting("kodi_port", 8080, 1, 65535),
        "reconnect_min_seconds": int_setting("reconnect_min_seconds", 5, 1, 300),
        "reconnect_max_seconds": int_setting("reconnect_max_seconds", 60, 1, 600),
        "telemetry_interval_seconds": int_setting("telemetry_interval_seconds", 30, 5, 3600),
        "enable_http_proxy": bool_setting("enable_http_proxy", True),
        "enable_management_rpc": bool_setting("enable_management_rpc", True),
        "enable_log_tail": bool_setting("enable_log_tail", True),
        "enable_iphone_bridge": bool_setting("enable_iphone_bridge", False),
        "iphone_bridge_host": setting("iphone_bridge_host", ""),
        "iphone_bridge_port": int_setting("iphone_bridge_port", 9192, 1, 65535),
        "iphone_bridge_token": setting("iphone_bridge_token", ""),
        "iphone_bridge_reconnect_min_seconds": int_setting("iphone_bridge_reconnect_min_seconds", 3, 1, 300),
        "iphone_bridge_reconnect_max_seconds": int_setting("iphone_bridge_reconnect_max_seconds", 30, 1, 600),
    }


class ProtocolError(Exception):
    pass


class SimpleWebSocket(object):
    def __init__(self, cfg):
        self.cfg = cfg
        self.sock = None
        self.connected = False

    def connect(self, timeout=15):
        raw = socket.create_connection((self.cfg["bridge_host"], self.cfg["bridge_port"]), timeout=timeout)
        raw.settimeout(timeout)
        if self.cfg["use_tls"]:
            global ssl
            if ssl is None:
                import ssl as _ssl
                ssl = _ssl
            ctx = ssl.create_default_context() if self.cfg["verify_tls"] else ssl._create_unverified_context()
            raw = ctx.wrap_socket(raw, server_hostname=self.cfg["bridge_host"])
        self.sock = raw
        path = self.cfg["bridge_path"] or "/"
        if not path.startswith("/"):
            path = "/" + path
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        headers = [
            "GET %s HTTP/1.1" % path,
            "Host: %s:%s" % (self.cfg["bridge_host"], self.cfg["bridge_port"]),
            "Upgrade: websocket",
            "Connection: Upgrade",
            "Sec-WebSocket-Key: %s" % key,
            "Sec-WebSocket-Version: 13",
            "X-Kodi-Proxy-Protocol: %s" % PROTOCOL_VERSION,
            "X-Kodi-Proxy-Addon: %s/%s" % (ADDON_ID, ADDON_VERSION),
        ]
        if self.cfg["auth_token"]:
            headers.append("Authorization: Bearer %s" % self.cfg["auth_token"])
        self.sock.sendall(("\r\n".join(headers) + "\r\n\r\n").encode("ascii"))
        response = self._read_handshake()
        status_line = response.split("\r\n", 1)[0]
        if " 101 " not in status_line:
            raise ProtocolError("WebSocket upgrade failed: %s" % status_line)
        expected = base64.b64encode(hashlib.sha1((key + GUID).encode("ascii")).digest()).decode("ascii")
        if expected.lower() not in response.lower():
            raise ProtocolError("WebSocket accept key mismatch")
        self.sock.settimeout(1.0)
        self.connected = True

    def _read_handshake(self):
        data = b""
        while b"\r\n\r\n" not in data:
            chunk = self.sock.recv(4096)
            if not chunk:
                break
            data += chunk
            if len(data) > 65536:
                raise ProtocolError("Handshake response too large")
        return data.decode("iso-8859-1", errors="replace")

    def close(self):
        self.connected = False
        try:
            if self.sock:
                self.sock.close()
        except Exception:
            pass
        self.sock = None

    def _recv_exact(self, size):
        data = b""
        while len(data) < size:
            chunk = self.sock.recv(size - len(data))
            if not chunk:
                raise ProtocolError("Socket closed")
            data += chunk
        return data

    def recv(self):
        first = self._recv_exact(2)
        b1, b2 = struct.unpack("!BB", first)
        opcode = b1 & 0x0F
        masked = bool(b2 & 0x80)
        size = b2 & 0x7F
        if size == 126:
            size = struct.unpack("!H", self._recv_exact(2))[0]
        elif size == 127:
            size = struct.unpack("!Q", self._recv_exact(8))[0]
        if size > MAX_FRAME_BYTES:
            raise ProtocolError("Frame too large: %s bytes" % size)
        mask = self._recv_exact(4) if masked else None
        payload = self._recv_exact(size) if size else b""
        if masked and mask:
            payload = bytes(byte ^ mask[i % 4] for i, byte in enumerate(payload))
        if opcode == 0x8:
            self.close()
            return None
        if opcode == 0x9:
            self._send_frame(payload, 0xA)
            return "__ping__"
        if opcode == 0xA:
            return "__pong__"
        if opcode == 0x1:
            return payload.decode("utf-8", errors="replace")
        if opcode == 0x2:
            if not payload:
                return ""
            flag, body = payload[:1], payload[1:]
            if flag == b"\x01":
                body = zlib.decompress(body)
            elif flag != b"\x00":
                raise ProtocolError("Unknown binary payload flag")
            return body.decode("utf-8", errors="replace")
        return ""

    def send_json(self, obj, compress=False):
        raw = json.dumps(obj, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        if compress and len(raw) > 1024:
            self._send_frame(b"\x01" + zlib.compress(raw), 0x2)
        else:
            self._send_frame(raw, 0x1)

    def _send_frame(self, payload, opcode):
        payload = payload or b""
        key = os.urandom(4)
        size = len(payload)
        if size < 126:
            header = struct.pack("!BB", 0x80 | opcode, 0x80 | size)
        elif size < (1 << 16):
            header = struct.pack("!BBH", 0x80 | opcode, 0x80 | 126, size)
        else:
            header = struct.pack("!BBQ", 0x80 | opcode, 0x80 | 127, size)
        masked = bytes(byte ^ key[i % 4] for i, byte in enumerate(payload))
        self.sock.sendall(header + key + masked)


def clean_headers(headers):
    out = {}
    for k, v in (headers or {}).items():
        name = str(k)
        if name.lower() in HOP_HEADERS or "\r" in name or "\n" in name:
            continue
        out[name] = str(v).replace("\r", "").replace("\n", "")
    return out


def validate_request(data):
    req_id = data.get("id")
    method = str(data.get("method", "GET")).upper()
    path = data.get("path", "/")
    if not req_id:
        raise ValueError("Missing request id")
    if method not in ALLOWED_METHODS:
        raise ValueError("HTTP method not allowed: %s" % method)
    if not isinstance(path, str) or not path.startswith("/") or "\r" in path or "\n" in path:
        raise ValueError("Invalid path")
    return req_id, method, path


def encode_body(body, headers):
    body = body or b""
    content_type = ""
    for k, v in headers.items():
        if k.lower() == "content-type":
            content_type = v.lower()
    if any(content_type.startswith(t) for t in TEXT_TYPES):
        return {"body": body.decode("utf-8", errors="replace"), "body_encoding": "utf-8"}
    return {"body": base64.b64encode(body).decode("ascii"), "body_encoding": "base64"}


def decode_body(data):
    body = data.get("body", "")
    enc = data.get("body_encoding", "utf-8")
    raw = base64.b64decode(body) if enc == "base64" else (body.encode("utf-8") if isinstance(body, str) else body or b"")
    if len(raw) > MAX_REQUEST_BODY_BYTES:
        raise ValueError("Request body too large")
    return raw


def send_error(ws, req_id, msg, status=500, response_type="error"):
    ws.send_json({"type": response_type, "id": req_id, "status": status, "error": str(msg)})


def handle_http(ws, data, cfg):
    req_id = data.get("id", "unknown")
    try:
        req_id, method, path = validate_request(data)
        if data.get("query") and "?" not in path:
            path += "?" + str(data["query"]).lstrip("?")
        url = "http://%s:%s%s" % (cfg["kodi_host"], cfg["kodi_port"], path)
        req = urllib.request.Request(url, data=decode_body(data) if method not in ("GET", "HEAD") else None, headers=clean_headers(data.get("headers", {})), method=method)
        with urllib.request.urlopen(req, timeout=15) as resp:
            headers = dict(resp.headers.items())
            response = {"type": "response", "id": req_id, "status": getattr(resp, "status", resp.getcode()), "headers": clean_headers(headers)}
            response.update(encode_body(resp.read(MAX_FRAME_BYTES), headers))
            ws.send_json(response, compress=True)
    except Exception as exc:
        log("HTTP proxy error: %s" % exc, xbmc.LOGERROR)
        send_error(ws, req_id, exc, 500, "response")


def handle_rpc(ws, data, cfg):
    req_id = data.get("id", "unknown")
    try:
        if not cfg["enable_management_rpc"]:
            raise ValueError("Management RPC is disabled")
        if not data.get("method"):
            raise ValueError("Missing JSON-RPC method")
        raw = xbmc.executeJSONRPC(json.dumps({"jsonrpc": "2.0", "method": data["method"], "params": data.get("params", {}), "id": req_id}))
        try:
            body = json.loads(raw) if raw else None
        except Exception:
            body = raw
        ws.send_json({"type": "command_result", "id": req_id, "status": 200, "body": body})
    except Exception as exc:
        log("Kodi command error: %s" % exc, xbmc.LOGERROR)
        send_error(ws, req_id, exc, 500, "command_result")


def handle_management(ws, data, cfg):
    req_id = data.get("id", "unknown")
    action = data.get("action", "")
    addon_id = data.get("addon_id", ADDON_ID)
    zip_url = data.get("zip_url", "")
    allowed = {
        "refresh_repos": ["UpdateAddonRepos"],
        "install_addon": ["InstallAddon(%s)" % addon_id],
        "update_addon": ["UpdateAddonRepos", "UpdateLocalAddons", "InstallAddon(%s)" % addon_id],
        "open_addon_browser": ["ActivateWindow(AddonBrowser)"],
        "open_sources": ["ActivateWindow(FileManager)"],
    }
    try:
        if not cfg["enable_management_rpc"]:
            raise ValueError("Management RPC is disabled")
        if action == "install_zip_url":
            result = install_zip_url(zip_url)
            xbmc.executebuiltin("UpdateLocalAddons")
            xbmc.executebuiltin("UpdateAddonRepos")
            ws.send_json({"type": "management_result", "id": req_id, "status": 200, "body": {"ok": True, "action": action, "result": result}})
            return
        builtins = allowed.get(action)
        if not builtins:
            raise ValueError("Unsupported management action: %s" % action)
        for builtin in builtins:
            log("Running management builtin: %s" % builtin)
            xbmc.executebuiltin(builtin)
            time.sleep(0.5)
        ws.send_json({"type": "management_result", "id": req_id, "status": 200, "body": {"ok": True, "action": action, "builtins": builtins}})
    except Exception as exc:
        log("Management command error: %s" % exc, xbmc.LOGERROR)
        ws.send_json({"type": "management_result", "id": req_id, "status": 500, "body": {"ok": False, "action": action, "error": str(exc)}})


def _safe_member_path(root, member):
    path = os.path.abspath(os.path.join(root, member))
    root_abs = os.path.abspath(root)
    if path != root_abs and not path.startswith(root_abs + os.sep):
        raise ValueError("Unsafe zip path: %s" % member)
    return path


def install_zip_url(url):
    if not url or not isinstance(url, str):
        raise ValueError("Missing zip_url")
    allowed_prefixes = (
        "https://kodifitzwell.github.io/repo/",
        "https://raw.githubusercontent.com/O10X/Main/",
        "https://github.com/O10X/Main/raw/",
    )
    if not url.startswith(allowed_prefixes):
        raise ValueError("zip_url host is not allowlisted")
    if not url.lower().split("?", 1)[0].endswith(".zip"):
        raise ValueError("zip_url must point to a .zip file")
    packages_dir = xbmcvfs.translatePath("special://home/addons/packages")
    addons_dir = xbmcvfs.translatePath("special://home/addons")
    if not os.path.isdir(packages_dir):
        os.makedirs(packages_dir)
    filename = url.rstrip("/").split("/")[-1].split("?", 1)[0]
    local_zip = os.path.join(packages_dir, filename)
    req = urllib.request.Request(url, headers={"User-Agent": "Kodi Xbox Proxy/%s" % ADDON_VERSION})
    with urllib.request.urlopen(req, timeout=60) as resp:
        payload = resp.read()
    with open(local_zip, "wb") as handle:
        handle.write(payload)
    with zipfile.ZipFile(local_zip) as zf:
        names = [name for name in zf.namelist() if name and not name.endswith("/")]
        if not names:
            raise ValueError("Zip is empty")
        roots = sorted(set(name.split("/", 1)[0] for name in names if "/" in name))
        if len(roots) != 1:
            raise ValueError("Zip must contain exactly one top-level add-on folder")
        root = roots[0]
        if (root + "/addon.xml") not in names:
            raise ValueError("Zip root does not contain addon.xml")
        target_root = os.path.join(addons_dir, root)
        if not os.path.isdir(target_root):
            os.makedirs(target_root)
        for member in zf.infolist():
            target = _safe_member_path(addons_dir, member.filename)
            if member.is_dir():
                if not os.path.isdir(target):
                    os.makedirs(target)
                continue
            parent = os.path.dirname(target)
            if not os.path.isdir(parent):
                os.makedirs(parent)
            with zf.open(member) as src, open(target, "wb") as dst:
                dst.write(src.read())
    return {"url": url, "zip_path": local_zip, "addon_id": root, "bytes": len(payload)}


def read_logs(lines):
    lines = max(1, min(int(lines or 200), MAX_LOG_LINES))
    for special in ("special://logpath/kodi.log", "special://home/kodi.log", "special://temp/kodi.log"):
        path = xbmcvfs.translatePath(special)
        if path and os.path.exists(path):
            tail = collections.deque(maxlen=lines)
            with open(path, "r", errors="replace") as handle:
                for line in handle:
                    tail.append(line.rstrip("\n"))
            return {"path": special, "lines": list(tail), "truncated_to": lines}
    return {"path": None, "lines": [], "error": "kodi.log not found in known paths"}


def check_http(cfg):
    try:
        url = "http://%s:%s/jsonrpc" % (cfg["kodi_host"], cfg["kodi_port"])
        body = json.dumps({"jsonrpc": "2.0", "method": "JSONRPC.Ping", "id": "startup"}).encode("utf-8")
        req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=3) as resp:
            return {"ok": True, "status": getattr(resp, "status", resp.getcode())}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def check_execute_jsonrpc():
    try:
        raw = xbmc.executeJSONRPC(json.dumps({"jsonrpc": "2.0", "method": "JSONRPC.Ping", "id": "startup"}))
        return {"ok": True, "response": json.loads(raw) if raw else raw}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def connected_info(cfg):
    return {
        "addon_id": ADDON_ID,
        "addon_name": ADDON_NAME,
        "addon_version": ADDON_VERSION,
        "protocol_version": PROTOCOL_VERSION,
        "python_version": sys.version,
        "platform": sys.platform,
        "build_version": xbmc.getInfoLabel("System.BuildVersion"),
        "friendly_name": xbmc.getInfoLabel("System.FriendlyName"),
        "local_http": check_http(cfg),
        "execute_jsonrpc": check_execute_jsonrpc(),
        "capabilities": {
            "http_proxy": cfg["enable_http_proxy"],
            "management_rpc": cfg["enable_management_rpc"],
            "log_tail": cfg["enable_log_tail"],
            "binary_http_bodies": True,
            "auth_token_present": bool(cfg["auth_token"]),
            "iphone_bridge": cfg["enable_iphone_bridge"],
            "iphone_bridge_host": cfg["iphone_bridge_host"] if cfg["enable_iphone_bridge"] else None,
            "iphone_bridge_port": cfg["iphone_bridge_port"] if cfg["enable_iphone_bridge"] else None,
        },
    }


def telemetry(ws):
    ws.send_json({"type": "telemetry", "time": int(time.time()), "info": {"build_version": xbmc.getInfoLabel("System.BuildVersion"), "free_memory": xbmc.getInfoLabel("System.FreeMemory"), "cpu_usage": xbmc.getInfoLabel("System.CpuUsage"), "screen_resolution": xbmc.getInfoLabel("System.ScreenResolution")}})


def kodi_jsonrpc(method, params=None, req_id="iphone-bridge"):
    raw = xbmc.executeJSONRPC(json.dumps({"jsonrpc": "2.0", "method": method, "params": params or {}, "id": req_id}))
    try:
        return json.loads(raw) if raw else None
    except Exception:
        return raw


def iphone_telemetry_payload():
    active_players = kodi_jsonrpc("Player.GetActivePlayers", req_id="iphone-telemetry-players")
    app_props = kodi_jsonrpc("Application.GetProperties", {"properties": ["volume", "muted"]}, "iphone-telemetry-app")
    active = []
    volume = None
    muted = None
    item = None
    try:
        active = active_players.get("result") or []
    except Exception:
        active = []
    try:
        props = app_props.get("result") or {}
        volume = props.get("volume")
        muted = props.get("muted")
    except Exception:
        pass
    try:
        if active:
            player_id = active[0].get("playerid")
            item_result = kodi_jsonrpc("Player.GetItem", {"playerid": player_id, "properties": ["title", "file", "thumbnail", "artist", "album"]}, "iphone-telemetry-item")
            item = (item_result.get("result") or {}).get("item")
    except Exception:
        item = None
    return {"type": "telemetry", "timestamp": int(time.time()), "active_players": active, "volume": volume, "muted": muted, "item": item}


class IPhoneBridgeClient(object):
    def __init__(self, cfg, monitor):
        self.cfg = cfg
        self.monitor = monitor
        self.sock = None
        self.buffer = b""
        self.authenticated = not bool(cfg.get("iphone_bridge_token"))

    def close(self):
        try:
            if self.sock:
                self.sock.close()
        except Exception:
            pass
        self.sock = None

    def send(self, message):
        if not self.sock:
            return
        self.sock.sendall(encode_json_line(message))

    def connect(self):
        host = self.cfg.get("iphone_bridge_host")
        port = self.cfg.get("iphone_bridge_port")
        if not host:
            raise ValueError("iPhone bridge is enabled but iphone_bridge_host is empty")
        self.sock = socket.create_connection((host, port), timeout=10)
        self.sock.settimeout(1.0)
        log("Connected to iPhone Remote Bridge at %s:%s" % (host, port))
        self.send(make_hello_message(ADDON_ID, ADDON_VERSION, ADDON_NAME, xbmc.getInfoLabel("System.BuildVersion"), sys.platform))
        auth = make_auth_message(self.cfg.get("iphone_bridge_token"))
        if auth:
            self.send(auth)

    def handle_command(self, message):
        req_id = message.get("id") or "iphone-command"
        if not self.authenticated:
            self.send(make_error_message(req_id, "Not authenticated", "not_authenticated"))
            return
        method = message.get("method")
        if not isinstance(method, str) or not method:
            self.send(make_error_message(req_id, "Missing JSON-RPC method", "bad_command"))
            return
        try:
            result = kodi_jsonrpc(method, message.get("params") or {}, req_id)
            self.send(make_result_message(req_id, True, result))
        except Exception as exc:
            log("iPhone bridge command error: %s" % exc, xbmc.LOGERROR)
            self.send(make_result_message(req_id, False, str(exc)))

    def handle_message(self, message):
        kind = message.get("type")
        if kind == "auth_ok":
            self.authenticated = True
            log("iPhone Remote Bridge authentication accepted")
        elif kind == "auth_error":
            self.authenticated = False
            raise BridgeProtocolError("iPhone bridge authentication failed: %s" % message.get("message", "auth_error"))
        elif kind == "command":
            self.handle_command(message)
        elif kind == "ping":
            self.send({"type": "pong", "id": message.get("id")})
        else:
            self.send(make_error_message(message.get("id"), "Unknown message type: %s" % kind, "unknown_type"))

    def run(self):
        self.connect()
        next_telemetry = time.time() + max(5, int(self.cfg.get("telemetry_interval_seconds") or 30))
        while not self.monitor.abortRequested():
            if time.time() >= next_telemetry:
                try:
                    self.send(iphone_telemetry_payload())
                except Exception as exc:
                    log("iPhone bridge telemetry error: %s" % exc, xbmc.LOGWARNING)
                next_telemetry = time.time() + max(5, int(self.cfg.get("telemetry_interval_seconds") or 30))
            try:
                chunk = self.sock.recv(4096)
                if not chunk:
                    raise ProtocolError("iPhone bridge socket closed")
                self.buffer += chunk
                messages, self.buffer = extract_json_lines(self.buffer)
                for message in messages:
                    self.handle_message(message)
            except Exception as exc:
                if is_timeout_error(exc):
                    continue
                raise


def iphone_bridge_loop(monitor, cfg):
    attempt = 0
    client = None
    while not monitor.abortRequested():
        if not cfg.get("enable_iphone_bridge"):
            return
        client = IPhoneBridgeClient(cfg, monitor)
        try:
            client.run()
            attempt = 0
        except Exception as exc:
            log("iPhone bridge loop error: %s" % exc, xbmc.LOGWARNING)
        finally:
            client.close()
        attempt += 1
        delay = min(cfg["iphone_bridge_reconnect_max_seconds"], cfg["iphone_bridge_reconnect_min_seconds"] * (2 ** min(attempt, 5)))
        delay += random.randint(0, max(1, delay // 4))
        log("iPhone bridge disconnected. Reconnecting in %s seconds." % delay, xbmc.LOGWARNING)
        monitor.waitForAbort(delay)


def dispatch(ws, msg, cfg):
    if msg in (None, "", "__ping__", "__pong__"):
        return
    data = json.loads(msg)
    kind = data.get("type")
    if kind in ("request", "http_request"):
        if not cfg["enable_http_proxy"]:
            raise ValueError("HTTP proxy is disabled")
        handle_http(ws, data, cfg)
    elif kind in ("command", "kodi_command", "jsonrpc"):
        handle_rpc(ws, data, cfg)
    elif kind == "management":
        handle_management(ws, data, cfg)
    elif kind in ("get_logs", "logs"):
        if not cfg["enable_log_tail"]:
            raise ValueError("Log tail is disabled")
        ws.send_json({"type": "logs_result", "id": data.get("id"), "status": 200, "body": read_logs(data.get("lines", 200))}, compress=True)
    elif kind == "ping":
        ws.send_json({"type": "pong", "id": data.get("id"), "time": int(time.time())})
    else:
        send_error(ws, data.get("id", "unknown"), "Unknown message type: %s" % kind, 400)


def service_loop():
    monitor = xbmc.Monitor()
    attempt = 0
    iphone_thread = None
    while not monitor.abortRequested():
        cfg = config()
        if cfg["enable_iphone_bridge"] and cfg["iphone_bridge_host"] and (iphone_thread is None or not iphone_thread.is_alive()):
            iphone_thread = threading.Thread(target=iphone_bridge_loop, args=(monitor, cfg))
            iphone_thread.daemon = True
            iphone_thread.start()
        if not cfg["auth_token"]:
            log("No auth token configured. Connecting without bridge authentication.", xbmc.LOGWARNING)
        ws = None
        try:
            ws = SimpleWebSocket(cfg)
            log("Connecting to bridge %s:%s%s" % (cfg["bridge_host"], cfg["bridge_port"], cfg["bridge_path"]))
            ws.connect()
            attempt = 0
            ws.send_json({"type": "connected", "info": connected_info(cfg)})
            next_telemetry = time.time() + cfg["telemetry_interval_seconds"]
            while not monitor.abortRequested() and ws.connected:
                if time.time() >= next_telemetry:
                    telemetry(ws)
                    next_telemetry = time.time() + cfg["telemetry_interval_seconds"]
                try:
                    dispatch(ws, ws.recv(), cfg)
                except Exception as exc:
                    if is_timeout_error(exc):
                        continue
                    raise
        except Exception as exc:
            log("Bridge loop error: %s\n%s" % (exc, traceback.format_exc()), xbmc.LOGERROR)
        finally:
            if ws:
                ws.close()
        attempt += 1
        delay = min(cfg["reconnect_max_seconds"], cfg["reconnect_min_seconds"] * (2 ** min(attempt, 5)))
        delay += random.randint(0, max(1, delay // 4))
        log("Bridge disconnected. Reconnecting in %s seconds." % delay, xbmc.LOGWARNING)
        monitor.waitForAbort(delay)


if __name__ == "__main__":
    service_loop()
