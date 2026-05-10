# -*- coding: utf-8 -*-
"""Robust Xbox Web Proxy service for Kodi.

Protocol v2:
- Client opens an outbound WebSocket to the bridge.
- Text frames are plain JSON.
- Binary frames use a one-byte envelope: 0x00 raw JSON bytes, 0x01 zlib JSON bytes.
- HTTP bodies are returned as utf-8 text or base64 binary using body_encoding.
"""
from __future__ import unicode_literals

import base64
import collections
import hashlib
import json
import os
import random
import socket
import ssl
import struct
import sys
import time
import traceback
import urllib.request
import zlib

import xbmc
import xbmcaddon
import xbmcvfs

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
        "capabilities": {"http_proxy": cfg["enable_http_proxy"], "management_rpc": cfg["enable_management_rpc"], "log_tail": cfg["enable_log_tail"], "binary_http_bodies": True, "auth_token_present": bool(cfg["auth_token"])}
    }


def telemetry(ws):
    ws.send_json({"type": "telemetry", "time": int(time.time()), "info": {"build_version": xbmc.getInfoLabel("System.BuildVersion"), "free_memory": xbmc.getInfoLabel("System.FreeMemory"), "cpu_usage": xbmc.getInfoLabel("System.CpuUsage"), "screen_resolution": xbmc.getInfoLabel("System.ScreenResolution")}})


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
    while not monitor.abortRequested():
        cfg = config()
        if not cfg["auth_token"]:
            log("No auth token configured. Refusing to connect to bridge.", xbmc.LOGERROR)
            monitor.waitForAbort(30)
            continue
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
                except socket.timeout:
                    continue
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
