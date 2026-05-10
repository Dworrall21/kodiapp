import json
import os
import threading
import time
import xbmc
import xbmcaddon

ADDON = xbmcaddon.Addon()
ADDON_NAME = ADDON.getAddonInfo("id")

SERVER_HOST = ADDON.getSetting("server_host") or "10.0.0.4"
SERVER_PORT = int(ADDON.getSetting("server_port") or "9191")
KODI_PORT = 8080


def log(msg):
    xbmc.log(f"[{ADDON_NAME}] {msg}", xbmc.LOGINFO)


def get_kodi_log_path():
    """Find Kodi's log file path. Varies by platform."""
    # Xbox UWP Kodi log locations
    candidates = [
        os.path.join(xbmc.translatepath("special://logpath"), "kodi.log"),
        os.path.join(xbmc.translatepath("special://home"), "temp", "kodi.log"),
        os.path.join(xbmc.translatepath("special://temp"), "kodi.log"),
        # Windows/UWP specific
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "Packages"),
    ]
    for path in candidates:
        if path and os.path.isfile(path):
            return path
    # Try to find it
    home = xbmc.translatepath("special://home")
    for root, dirs, files in os.walk(home):
        if "kodi.log" in files:
            return os.path.join(root, "kodi.log")
    return None


def read_kodi_logs(lines=200):
    """Read the last N lines of kodi.log."""
    log_path = get_kodi_log_path()
    if not log_path:
        return {"error": "Could not find kodi.log", "path": None}

    try:
        with open(log_path, "r", errors="replace") as f:
            all_lines = f.readlines()
            last_lines = all_lines[-lines:] if len(all_lines) > lines else all_lines
            return {
                "path": log_path,
                "total_lines": len(all_lines),
                "lines": "".join(last_lines),
            }
    except Exception as e:
        return {"error": str(e), "path": log_path}


def get_kodi_info():
    """Get Kodi version and system info."""
    try:
        return {
            "version": xbmc.getInfoLabel("System.BuildVersion"),
            "name": xbmc.getInfoLabel("System.FriendlyName"),
            "platform": xbmc.getInfoLabel("System.OSVersionInfo"),
        }
    except:
        return {"version": "unknown"}


class SimpleWSClient:
    """Minimal WebSocket client using only Python stdlib."""

    def __init__(self, host, port, path="/"):
        self.host = host
        self.port = port
        self.path = path
        self.sock = None
        self.connected = False
        self._on_open = None
        self._on_message = None
        self._on_close = None
        self._on_error = None
        self._running = False

    def on_open(self, cb):
        self._on_open = cb

    def on_message(self, cb):
        self._on_message = cb

    def on_close(self, cb):
        self._on_close = cb

    def on_error(self, cb):
        self._on_error = cb

    def connect(self):
        import socket
        import base64

        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.settimeout(10)
            self.sock.connect((self.host, self.port))

            key = base64.b64encode(os.urandom(16)).decode()
            handshake = (
                f"GET {self.path} HTTP/1.1\r\n"
                f"Host: {self.host}:{self.port}\r\n"
                f"Upgrade: websocket\r\n"
                f"Connection: Upgrade\r\n"
                f"Sec-WebSocket-Key: {key}\r\n"
                f"Sec-WebSocket-Version: 13\r\n"
                f"\r\n"
            )
            self.sock.sendall(handshake.encode())

            response = b""
            while b"\r\n\r\n" not in response:
                chunk = self.sock.recv(4096)
                if not chunk:
                    raise ConnectionError("Connection closed during handshake")
                response += chunk

            if b"101" not in response.split(b"\r\n")[0]:
                raise ConnectionError(f"Handshake failed: {response[:200]}")

            self.connected = True
            self._running = True
            self.sock.settimeout(None)

            if self._on_open:
                self._on_open(self)

            self._receive_loop()

        except Exception as e:
            self.connected = False
            if self._on_error:
                self._on_error(self, str(e))
            raise

    def _receive_loop(self):
        try:
            while self._running:
                data = self._recv_frame()
                if data is None:
                    break
                if self._on_message:
                    self._on_message(self, data)
        except Exception as e:
            if self._running and self._on_error:
                self._on_error(self, str(e))
        finally:
            self.connected = False
            if self._on_close:
                self._on_close(self)

    def _recv_frame(self):
        import struct

        header = self._recv_exact(2)
        if not header:
            return None

        fin_op = header[0]
        opcode = fin_op & 0x0F
        payload_len = header[1] & 0x7F
        masked = bool(header[1] & 0x80)

        if opcode == 0x8:
            return None
        if opcode == 0x9:
            pong = bytes([0x8A, 0x00])
            self.sock.sendall(pong)
            return self._recv_frame()

        if payload_len == 126:
            ext = self._recv_exact(2)
            payload_len = struct.unpack("!H", ext)[0]
        elif payload_len == 127:
            ext = self._recv_exact(8)
            payload_len = struct.unpack("!Q", ext)[0]

        if masked:
            mask_key = self._recv_exact(4)
        else:
            mask_key = None

        payload = self._recv_exact(payload_len)
        if payload is None:
            return None

        if mask_key:
            payload = bytes(b ^ mask_key[i % 4] for i, b in enumerate(payload))

        if opcode == 0x1:
            return payload.decode("utf-8", errors="replace")
        return ""

    def _recv_exact(self, n):
        data = b""
        while len(data) < n:
            try:
                chunk = self.sock.recv(n - len(data))
                if not chunk:
                    return None
                data += chunk
            except socket.timeout:
                continue
            except OSError:
                return None
        return data

    def send(self, message):
        import struct
        if isinstance(message, str):
            message = message.encode("utf-8")

        mask_key = os.urandom(4)
        masked = bytes(b ^ mask_key[i % 4] for i, b in enumerate(message))

        length = len(masked)
        if length < 126:
            header = bytes([0x81, 0x80 | length])
        elif length < 65536:
            header = bytes([0x81, 0x80 | 126]) + struct.pack("!H", length)
        else:
            header = bytes([0x81, 0x80 | 127]) + struct.pack("!Q", length)

        self.sock.sendall(header + mask_key + masked)

    def close(self):
        self._running = False
        self.connected = False
        if self.sock:
            try:
                self.sock.sendall(bytes([0x88, 0x00]))
                self.sock.close()
            except:
                pass


class ProxyService:
    def __init__(self):
        self.ws = None
        self.running = True
        self.connected = False
        self._reconnect_delay = 5

    def connect(self):
        log(f"Connecting to proxy at {SERVER_HOST}:{SERVER_PORT}")
        while self.running:
            try:
                self.ws = SimpleWSClient(SERVER_HOST, SERVER_PORT)
                self.ws.on_open = self.on_open
                self.ws.on_message = self.on_message
                self.ws.on_close = self.on_close
                self.ws.on_error = self.on_error
                self.ws.connect()
                # If connect() returns, connection was lost
            except Exception as e:
                log(f"Connection error: {e}")

            self.connected = False
            if not self.running:
                break
            log(f"Reconnecting in {self._reconnect_delay}s...")
            time.sleep(self._reconnect_delay)
            # Exponential backoff up to 60s
            self._reconnect_delay = min(self._reconnect_delay * 2, 60)

    def on_open(self, ws):
        self.connected = True
        self._reconnect_delay = 5  # Reset backoff
        log("Connected to proxy server")
        # Send hello with Kodi info
        info = get_kodi_info()
        ws.send(json.dumps({"type": "connected", "info": info}))

    def on_message(self, ws, message):
        try:
            data = json.loads(message)
        except json.JSONDecodeError:
            return

        msg_type = data.get("type")

        if msg_type == "request":
            self.handle_request(ws, data)
        elif msg_type == "get_logs":
            self.handle_get_logs(ws, data)
        elif msg_type == "get_info":
            self.handle_get_info(ws, data)
        elif msg_type == "kodi_command":
            self.handle_kodi_command(ws, data)

    def handle_request(self, ws, data):
        """Proxy HTTP request to Kodi's local web interface."""
        import urllib.request
        import urllib.error

        req_id = data["id"]
        method = data["method"]
        path = data["path"]
        body = data.get("body", "")
        headers = data.get("headers", {})

        url = f"http://127.0.0.1:{KODI_PORT}{path}"
        log(f"Proxying {method} {path}")

        try:
            req_data = body.encode("utf-8") if body else None
            req = urllib.request.Request(url, data=req_data, method=method)

            for key, val in headers.items():
                if key.lower() not in ("host", "connection"):
                    req.add_header(key, val)

            with urllib.request.urlopen(req, timeout=10) as resp:
                resp_body = resp.read()
                resp_headers = dict(resp.getheaders())

            response = {
                "type": "response",
                "id": req_id,
                "status": resp.status,
                "headers": resp_headers,
                "body": resp_body.decode("utf-8", errors="replace"),
            }

        except urllib.error.HTTPError as e:
            response = {
                "type": "response",
                "id": req_id,
                "status": e.code,
                "headers": dict(e.headers.items()),
                "body": e.read().decode("utf-8", errors="replace"),
            }
        except Exception as e:
            response = {
                "type": "response",
                "id": req_id,
                "status": 502,
                "headers": {"Content-Type": "text/plain"},
                "body": f"Proxy error: {e}",
            }

        try:
            ws.send(json.dumps(response))
        except Exception as e:
            log(f"Failed to send response: {e}")

    def handle_get_logs(self, ws, data):
        """Read and return Kodi's debug log."""
        req_id = data.get("id", "0")
        lines = data.get("lines", 200)
        log(f"Reading last {lines} lines of kodi.log")
        result = read_kodi_logs(lines)
        response = {
            "type": "logs",
            "id": req_id,
            "data": result,
        }
        try:
            ws.send(json.dumps(response))
        except Exception as e:
            log(f"Failed to send logs: {e}")

    def handle_get_info(self, ws, data):
        """Return Kodi system info."""
        req_id = data.get("id", "0")
        info = get_kodi_info()
        response = {
            "type": "info",
            "id": req_id,
            "data": info,
        }
        try:
            ws.send(json.dumps(response))
        except Exception as e:
            log(f"Failed to send info: {e}")

    def handle_kodi_command(self, ws, data):
        """Execute a Kodi JSON-RPC command directly."""
        req_id = data.get("id", "0")
        method = data.get("method", "")
        params = data.get("params", {})

        import urllib.request
        import urllib.error

        url = f"http://127.0.0.1:{KODI_PORT}/jsonrpc"
        rpc_body = json.dumps({
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
            "id": 1,
        })

        try:
            req = urllib.request.Request(
                url,
                data=rpc_body.encode("utf-8"),
                method="POST",
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                resp_body = resp.read()

            response = {
                "type": "command_result",
                "id": req_id,
                "status": resp.status,
                "body": resp_body.decode("utf-8", errors="replace"),
            }
        except Exception as e:
            response = {
                "type": "command_result",
                "id": req_id,
                "status": 500,
                "body": f"Command error: {e}",
            }

        try:
            ws.send(json.dumps(response))
        except Exception as e:
            log(f"Failed to send command result: {e}")

    def on_close(self, ws):
        self.connected = False
        log("Disconnected from proxy")

    def on_error(self, ws, error):
        log(f"WebSocket error: {error}")
        self.connected = False

    def stop(self):
        self.running = False
        if self.ws:
            self.ws.close()


def run():
    log("Xbox Web Proxy add-on starting")
    log(f"Proxy server: {SERVER_HOST}:{SERVER_PORT}")
    log(f"Kodi local port: {KODI_PORT}")

    service = ProxyService()
    conn_thread = threading.Thread(target=service.connect, daemon=True)
    conn_thread.start()

    monitor = xbmc.Monitor()
    while not monitor.abortRequested():
        if monitor.waitForAbort(30):
            break

    service.stop()
    log("Xbox Web Proxy add-on stopped")


if __name__ == "__main__":
    run()
