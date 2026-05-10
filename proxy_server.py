import asyncio
import http.server
import json
import os
import sys
import threading
import uuid
import websockets

# --- Config ---
HTTP_HOST = "0.0.0.0"
HTTP_PORT = 8080
WS_PORT = 9191

# Shared state
pending = {}  # {request_id: {"event": threading.Event, "response": dict}}
addon_ws = None
addon_lock = threading.Lock()
addon_info = None  # Kodi system info reported by the add-on


# ============================================================
# Web UI (single-page app, embedded below)
# ============================================================

WEB_UI_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Kodi Xbox Manager</title>
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #0d1117; color: #c9d1d9; min-height: 100vh; }
.header { background: #161b22; border-bottom: 1px solid #30363d; padding: 16px 24px; display: flex; align-items: center; justify-content: space-between; }
.header h1 { font-size: 18px; color: #58a6ff; }
.status-dot { width: 10px; height: 10px; border-radius: 50%; display: inline-block; margin-right: 8px; }
.status-dot.connected { background: #3fb950; box-shadow: 0 0 8px #3fb950; }
.status-dot.disconnected { background: #f85149; }
.tabs { display: flex; background: #161b22; border-bottom: 1px solid #30363d; padding: 0 24px; }
.tab { padding: 12px 20px; cursor: pointer; border-bottom: 2px solid transparent; color: #8b949e; font-size: 14px; transition: all .2s; }
.tab:hover { color: #c9d1d9; }
.tab.active { color: #58a6ff; border-bottom-color: #58a6ff; }
.content { padding: 24px; max-width: 1200px; margin: 0 auto; }
.panel { display: none; }
.panel.active { display: block; }
.card { background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 20px; margin-bottom: 16px; }
.card h3 { font-size: 14px; color: #8b949e; margin-bottom: 12px; text-transform: uppercase; letter-spacing: 0.5px; }
.info-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 12px; }
.info-item { background: #0d1117; padding: 12px; border-radius: 6px; border: 1px solid #21262d; }
.info-item label { display: block; font-size: 11px; color: #8b949e; margin-bottom: 4px; text-transform: uppercase; }
.info-item span { font-size: 14px; color: #c9d1d9; }
.log-viewer { background: #0d1117; border: 1px solid #21262d; border-radius: 6px; padding: 16px; font-family: 'SF Mono', 'Fira Code', monospace; font-size: 12px; line-height: 1.6; max-height: 600px; overflow-y: auto; white-space: pre-wrap; word-break: break-all; color: #c9d1d9; }
.log-viewer .error { color: #f85149; }
.log-viewer .warn { color: #d29922; }
.log-viewer .info { color: #58a6ff; }
.btn { background: #238636; color: white; border: none; padding: 8px 16px; border-radius: 6px; cursor: pointer; font-size: 13px; margin-right: 8px; margin-bottom: 8px; transition: background .2s; }
.btn:hover { background: #2ea043; }
.btn.secondary { background: #21262d; color: #c9d1d9; border: 1px solid #30363d; }
.btn.secondary:hover { background: #30363d; }
.btn.danger { background: #da3633; }
.btn.danger:hover { background: #f85149; }
.btn-row { margin-bottom: 16px; display: flex; flex-wrap: wrap; align-items: center; }
.cmd-input { background: #0d1117; border: 1px solid #30363d; color: #c9d1d9; padding: 8px 12px; border-radius: 6px; font-size: 13px; width: 300px; margin-right: 8px; }
.cmd-input:focus { outline: none; border-color: #58a6ff; }
.result-box { background: #0d1117; border: 1px solid #21262d; border-radius: 6px; padding: 16px; font-family: monospace; font-size: 12px; white-space: pre-wrap; max-height: 400px; overflow-y: auto; margin-top: 12px; }
.toast { position: fixed; bottom: 24px; right: 24px; padding: 12px 20px; border-radius: 6px; font-size: 13px; z-index: 100; transition: opacity .3s; }
.toast.success { background: #238636; color: white; }
.toast.error { background: #da3633; color: white; }
</style>
</head>
<body>
<div class="header">
  <h1>Kodi Xbox Manager</h1>
  <div>
    <span class="status-dot" id="statusDot"></span>
    <span id="statusText">Connecting...</span>
  </div>
</div>
<div class="tabs">
  <div class="tab active" onclick="showTab('status')">Status</div>
  <div class="tab" onclick="showTab('logs')">Debug Logs</div>
  <div class="tab" onclick="showTab('commands')">Commands</div>
  <div class="tab" onclick="showTab('webui')">Kodi Web UI</div>
</div>
<div class="content">

  <!-- Status Panel -->
  <div class="panel active" id="panel-status">
    <div class="card">
      <h3>Connection</h3>
      <div class="info-grid">
        <div class="info-item"><label>Status</label><span id="connStatus">—</span></div>
        <div class="info-item"><label>Last Seen</label><span id="lastSeen">—</span></div>
      </div>
    </div>
    <div class="card">
      <h3>Kodi System Info</h3>
      <div class="info-grid" id="kodiInfo">
        <div class="info-item"><label>Version</label><span>—</span></div>
        <div class="info-item"><label>Platform</label><span>—</span></div>
        <div class="info-item"><label>Device Name</label><span>—</span></div>
      </div>
    </div>
  </div>

  <!-- Logs Panel -->
  <div class="panel" id="panel-logs">
    <div class="card">
      <h3>Kodi Debug Log</h3>
      <div class="btn-row">
        <button class="btn" onclick="fetchLogs(200)">Last 200 lines</button>
        <button class="btn secondary" onclick="fetchLogs(500)">Last 500 lines</button>
        <button class="btn secondary" onclick="fetchLogs(1000)">Last 1000 lines</button>
        <button class="btn secondary" onclick="clearLogs()">Clear</button>
      </div>
      <div style="margin-bottom:8px;font-size:12px;color:#8b949e;" id="logMeta"></div>
      <div class="log-viewer" id="logViewer">Connect to Xbox Kodi to view logs...</div>
    </div>
  </div>

  <!-- Commands Panel -->
  <div class="panel" id="panel-commands">
    <div class="card">
      <h3>Quick Commands</h3>
      <div class="btn-row">
        <button class="btn secondary" onclick="sendCommand('Player.GetActivePlayers')">Active Players</button>
        <button class="btn secondary" onclick="sendCommand('Player.GetItem', {playerid: 1})">Now Playing</button>
        <button class="btn secondary" onclick="sendCommand('Application.GetProperties', {properties: ['volume', 'muted']})">Volume</button>
        <button class="btn secondary" onclick="sendCommand('GUI.GetProperties', {properties: ['fullscreen']})">Fullscreen</button>
        <button class="btn secondary" onclick="sendCommand('System.GetInfoLabels', {labels: ['System.CPUUsage', 'System.Memory(free)', 'System.TotalUptime']})">System Info</button>
      </div>
    </div>
    <div class="card">
      <h3>Custom JSON-RPC Command</h3>
      <div class="btn-row">
        <input class="cmd-input" id="cmdMethod" placeholder="Method (e.g. Player.PlayPause)" />
        <input class="cmd-input" id="cmdParams" placeholder='Params (JSON, e.g. {"playerid": 1})' style="width:250px" />
        <button class="btn" onclick="sendCustomCommand()">Send</button>
      </div>
      <div class="result-box" id="cmdResult">Results will appear here...</div>
    </div>
  </div>

  <!-- Web UI Panel -->
  <div class="panel" id="panel-webui">
    <div class="card">
      <h3>Kodi Web Interface</h3>
      <p style="color:#8b949e;font-size:13px;margin-bottom:12px;">
        This is Kodi's web interface, tunneled through the Xbox. It should work just like connecting directly.
      </p>
      <iframe id="kodiFrame" src="" style="width:100%;height:600px;border:1px solid #30363d;border-radius:6px;background:#0d1117;"></iframe>
    </div>
  </div>

</div>
<div id="toast" class="toast" style="display:none;"></div>

<script>
let connected = false;
let lastSeen = null;

function showTab(name) {
  document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
  document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
  event.target.classList.add('active');
  document.getElementById('panel-' + name).classList.add('active');
  if (name === 'webui') {
    document.getElementById('kodiFrame').src = '/_kodi_/';
  }
}

function showToast(msg, type) {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.className = 'toast ' + type;
  t.style.display = 'block';
  setTimeout(() => { t.style.display = 'none'; }, 3000);
}

function updateStatus(dot, text) {
  const d = document.getElementById('statusDot');
  d.className = 'status-dot ' + dot;
  document.getElementById('statusText').textContent = text;
}

async function api(path, opts = {}) {
  const r = await fetch('/api' + path, {
    headers: { 'Content-Type': 'application/json' },
    ...opts,
  });
  return r.json();
}

async function checkStatus() {
  try {
    const d = await api('/status');
    connected = d.connected;
    if (connected) {
      updateStatus('connected', 'Connected to Xbox Kodi');
      document.getElementById('connStatus').textContent = 'Connected';
      lastSeen = new Date();
      document.getElementById('lastSeen').textContent = lastSeen.toLocaleTimeString();
      if (d.info) {
        const info = d.info;
        const grid = document.getElementById('kodiInfo');
        grid.innerHTML = '';
        for (const [k, v] of Object.entries(info)) {
          grid.innerHTML += `<div class="info-item"><label>${k}</label><span>${v || '—'}</span></div>`;
        }
      }
    } else {
      updateStatus('disconnected', 'Kodi add-on not connected');
      document.getElementById('connStatus').textContent = 'Disconnected';
    }
  } catch (e) {
    updateStatus('disconnected', 'Proxy server unreachable');
  }
}

async function fetchLogs(count) {
  try {
    const d = await api('/logs?lines=' + count);
    if (d.lines) {
      const viewer = document.getElementById('logViewer');
      let html = d.lines
        .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
      html = html.replace(/\b(ERROR)\b/g, '<span class="error">$1</span>');
      html = html.replace(/\b(WARN(?:ING)?)\b/g, '<span class="warn">$1</span>');
      html = html.replace(/\b(INFO|NOTICE)\b/g, '<span class="info">$1</span>');
      viewer.innerHTML = html;
      viewer.scrollTop = viewer.scrollHeight;
      document.getElementById('logMeta').textContent =
        `Showing last ${count} lines | Total: ${d.total_lines || '?'} lines | Path: ${d.path || 'unknown'}`;
      showToast('Logs fetched', 'success');
    } else if (d.error) {
      document.getElementById('logViewer').textContent = 'Error: ' + d.error;
    }
  } catch (e) {
    showToast('Failed to fetch logs: ' + e, 'error');
  }
}

function fetchLines(count) { fetchLines(count); }
function clearLogs() {
  document.getElementById('logViewer').textContent = '';
  document.getElementById('logMeta').textContent = '';
}

async function sendCommand(method, params = {}) {
  try {
    const d = await api('/command', {
      method: 'POST',
      body: JSON.stringify({ method, params }),
    });
    const box = document.getElementById('cmdResult');
    box.textContent = JSON.stringify(d.result ? JSON.parse(d.result) : d, null, 2);
    showToast('Command sent: ' + method, 'success');
  } catch (e) {
    showToast('Command failed: ' + e, 'error');
  }
}

async function sendCustomCommand() {
  const method = document.getElementById('cmdMethod').value.trim();
  const paramsStr = document.getElementById('cmdParams').value.trim();
  if (!method) { showToast('Enter a method name', 'error'); return; }
  let params = {};
  if (paramsStr) {
    try { params = JSON.parse(paramsStr); } catch (e) { showToast('Invalid JSON params: ' + e, 'error'); return; }
  }
  sendCommand(method, params);
}

// Poll status every 5 seconds
checkStatus();
setInterval(checkStatus, 5000);
</script>
</body>
</html>"""


# ============================================================
# HTTP Server
# ============================================================

class ProxyHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def do_GET(self):
        path = self.path

        # Web UI
        if path == "/" or path == "/index.html":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(WEB_UI_HTML.encode())
            return

        # API endpoints
        if path.startswith("/api/"):
            self.handle_api(path[5:])  # Strip /api/
            return

        # Everything else → proxy to Kodi
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

    # --- API handlers ---

    def handle_api(self, path):
        global addon_info

        if path == "status" or path == "status/":
            with addon_lock:
                ws = addon_ws
                info = addon_info
            self.send_json(200, {
                "connected": ws is not None,
                "info": info,
            })

        elif path.startswith("logs"):
            lines = 200
            if "?" in path:
                qs = path.split("?", 1)[1]
                for param in qs.split("&"):
                    if param.startswith("lines="):
                        lines = int(param.split("=", 1)[1])
            self.send_request_to_addon("get_logs", {"lines": lines}, timeout=15)

        elif path == "info" or path == "info/":
            self.send_request_to_addon("get_info", {}, timeout=10)

        elif path == "command" or path == "command/":
            body = self.read_body()
            try:
                data = json.loads(body) if body else {}
            except json.JSONDecodeError:
                self.send_json(400, {"error": "Invalid JSON"})
                return
            self.send_request_to_addon("kodi_command", {
                "method": data.get("method", ""),
                "params": data.get("params", {}),
            }, timeout=15)

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

        headers = {key: self.headers[key] for key in self.headers}

        tunnel_msg = {
            "type": "request",
            "id": request_id,
            "method": method,
            "path": self.path,
            "headers": headers,
            "body": body.decode("utf-8", errors="replace"),
        }

        try:
            future = asyncio.run_coroutine_threadsafe(
                ws.send(json.dumps(tunnel_msg)), ws_loop
            )
            future.result(timeout=5)
        except Exception as e:
            pending.pop(request_id, None)
            self.send_json(502, {"error": f"Failed to reach add-on: {e}"})
            return

        if not event.wait(timeout=15):
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

    def send_request_to_addon(self, msg_type, data, timeout=15):
        """Send a management request to the add-on and wait for response."""
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
                ws.send(json.dumps(msg)), ws_loop
            )
            future.result(timeout=5)
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
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data, default=str).encode("utf-8"))


# ============================================================
# WebSocket Server
# ============================================================

async def addon_handler(websocket):
    global addon_ws, addon_info
    addon_ws = websocket
    print("[proxy] Kodi add-on connected")

    try:
        async for message in websocket:
            try:
                data = json.loads(message)
            except json.JSONDecodeError:
                continue

            msg_type = data.get("type")

            if msg_type == "response":
                req_id = data.get("id")
                if req_id in pending:
                    pending[req_id]["response"] = data
                    pending[req_id]["event"].set()

            elif msg_type == "connected":
                addon_info = data.get("info")
                print(f"[proxy] Add-on ready — Kodi {addon_info.get('version', '?') if addon_info else '?'}")

            elif msg_type == "logs":
                req_id = data.get("id")
                if req_id in pending:
                    pending[req_id]["response"] = {
                        "status": 200,
                        "body": json.dumps(data.get("data", {})),
                    }
                    pending[req_id]["event"].set()

            elif msg_type == "info":
                req_id = data.get("id")
                if req_id in pending:
                    pending[req_id]["response"] = {
                        "status": 200,
                        "body": json.dumps(data.get("data", {})),
                    }
                    pending[req_id]["event"].set()

            elif msg_type == "command_result":
                req_id = data.get("id")
                if req_id in pending:
                    pending[req_id]["response"] = {
                        "status": data.get("status", 200),
                        "body": data.get("body", ""),
                    }
                    pending[req_id]["event"].set()

    except websockets.exceptions.ConnectionClosed:
        pass
    finally:
        addon_ws = None
        addon_info = None
        print("[proxy] Add-on disconnected")


# ============================================================
# Main
# ============================================================

ws_loop = None


async def main():
    global ws_loop
    ws_loop = asyncio.get_event_loop()

    print("=" * 50)
    print("Kodi Xbox Proxy Server")
    print("=" * 50)
    print(f"  Dashboard:   http://localhost:{HTTP_PORT}")
    print(f"  Kodi Web UI: http://localhost:{HTTP_PORT}/_kodi_/")
    print(f"  API:         http://localhost:{HTTP_PORT}/api/")
    print(f"  Add-on WS:   ws://0.0.0.0:{WS_PORT}")
    print()

    # Start HTTP server in a thread
    http_thread = threading.Thread(
        target=lambda: http.server.HTTPServer((HTTP_HOST, HTTP_PORT), ProxyHandler).serve_forever(),
        daemon=True,
    )
    http_thread.start()

    # Start WebSocket server
    print(f"[proxy] WebSocket server listening on port {WS_PORT}")
    async with websockets.serve(addon_handler, "0.0.0.0", WS_PORT):
        await asyncio.Future()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[proxy] Shutting down")
        sys.exit(0)
