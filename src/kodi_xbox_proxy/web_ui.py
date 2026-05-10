"""Web UI HTML for Kodi Xbox Manager dashboard."""

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
.tabs { display: flex; background: #161b22; border-bottom: 1px solid #30363d; padding: 0 24px; overflow-x: auto; }
.tab { padding: 12px 20px; cursor: pointer; border-bottom: 2px solid transparent; color: #8b949e; font-size: 14px; transition: all .2s; white-space: nowrap; }
.tab:hover { color: #c9d1d9; }
.tab.active { color: #58a6ff; border-bottom-color: #58a6ff; }
.content { padding: 24px; max-width: 1200px; margin: 0 auto; }
.panel { display: none; }
.panel.active { display: block; }
.card { background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 20px; margin-bottom: 16px; }
.card h3 { font-size: 14px; color: #8b949e; margin-bottom: 12px; text-transform: uppercase; letter-spacing: 0.5px; }
.info-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px; }
.info-item { background: #0d1117; padding: 12px; border-radius: 6px; border: 1px solid #21262d; }
.info-item label { display: block; font-size: 11px; color: #8b949e; margin-bottom: 4px; text-transform: uppercase; }
.info-item span { font-size: 14px; color: #c9d1d9; }
.info-item .big { font-size: 24px; font-weight: 600; color: #58a6ff; }
.progress-bar { background: #21262d; border-radius: 4px; height: 8px; margin-top: 8px; overflow: hidden; }
.progress-bar .fill { background: #58a6ff; height: 100%; border-radius: 4px; transition: width .5s; }
.now-playing { display: flex; align-items: center; gap: 16px; }
.now-playing .icon { font-size: 48px; }
.now-playing .meta { flex: 1; }
.now-playing .title { font-size: 18px; font-weight: 600; color: #e6edf3; }
.now-playing .sub { font-size: 13px; color: #8b949e; margin-top: 4px; }
.log-viewer { background: #0d1117; border: 1px solid #21262d; border-radius: 6px; padding: 16px; font-family: 'SF Mono', 'Fira Code', monospace; font-size: 12px; line-height: 1.6; max-height: 500px; overflow-y: auto; white-space: pre-wrap; word-break: break-all; color: #c9d1d9; }
.log-viewer .error { color: #f85149; }
.log-viewer .warn { color: #d29922; }
.log-viewer .info { color: #58a6ff; }
.event-log { background: #0d1117; border: 1px solid #21262d; border-radius: 6px; padding: 12px; max-height: 400px; overflow-y: auto; }
.event-item { padding: 6px 0; border-bottom: 1px solid #21262d; font-size: 12px; display: flex; gap: 12px; }
.event-item:last-child { border-bottom: none; }
.event-time { color: #8b949e; font-family: monospace; white-space: nowrap; }
.event-type { color: #58a6ff; font-weight: 600; min-width: 140px; }
.event-data { color: #c9d1d9; flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
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
.live-indicator { display: inline-flex; align-items: center; gap: 6px; font-size: 12px; color: #3fb950; }
.live-dot { width: 6px; height: 6px; border-radius: 50%; background: #3fb950; animation: pulse 1.5s infinite; }
@keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.3; } }
</style>
</head>
<body>
<div class="header">
  <h1>Kodi Xbox Manager</h1>
  <div style="display:flex;align-items:center;gap:16px;">
    <div class="live-indicator" id="liveIndicator" style="display:none;">
      <span class="live-dot"></span> LIVE
    </div>
    <span class="status-dot" id="statusDot"></span>
    <span id="statusText">Connecting...</span>
  </div>
</div>
<div class="tabs">
  <div class="tab active" onclick="showTab('live')">Live</div>
  <div class="tab" onclick="showTab('status')">System</div>
  <div class="tab" onclick="showTab('logs')">Debug Logs</div>
  <div class="tab" onclick="showTab('events')">Event Log</div>
  <div class="tab" onclick="showTab('commands')">Commands</div>
  <div class="tab" onclick="showTab('webui')">Kodi Web UI</div>
</div>
<div class="content">
  <div class="panel active" id="panel-live">
    <div class="card">
      <h3>Now Playing</h3>
      <div class="now-playing" id="nowPlaying">
        <div class="icon">📺</div>
        <div class="meta">
          <div class="title" id="npTitle">Nothing playing</div>
          <div class="sub" id="npSub">—</div>
          <div class="progress-bar" id="npProgress" style="display:none;">
            <div class="fill" id="npFill" style="width:0%"></div>
          </div>
        </div>
      </div>
    </div>
    <div class="card">
      <h3>System Stats</h3>
      <div class="info-grid" id="sysStats">
        <div class="info-item"><label>CPU</label><span id="statCpu">—</span></div>
        <div class="info-item"><label>Memory Free</label><span id="statMemFree">—</span></div>
        <div class="info-item"><label>Memory Total</label><span id="statMemTotal">—</span></div>
        <div class="info-item"><label>Uptime</label><span id="statUptime">—</span></div>
        <div class="info-item"><label>Temperature</label><span id="statTemp">—</span></div>
        <div class="info-item"><label>Volume</label><span id="statVol">—</span></div>
      </div>
    </div>
  </div>
  <div class="panel" id="panel-status">
    <div class="card">
      <h3>Connection</h3>
      <div class="info-grid">
        <div class="info-item"><label>Status</label><span id="connStatus">—</span></div>
        <div class="info-item"><label>Last Seen</label><span id="lastSeen">—</span></div>
        <div class="info-item"><label>Events Received</label><span id="eventCount">0</span></div>
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
  <div class="panel" id="panel-events">
    <div class="card">
      <h3>Real-Time Event Stream</h3>
      <div class="btn-row">
        <button class="btn secondary" onclick="clearEvents()">Clear</button>
        <span style="font-size:12px;color:#8b949e;">Events are captured in real-time when connected</span>
      </div>
      <div class="event-log" id="eventLog">
        <div style="color:#8b949e;font-size:13px;padding:20px;text-align:center;">
          Waiting for events... play something on Kodi to see telemetry.
        </div>
      </div>
    </div>
  </div>
  <div class="panel" id="panel-commands">
    <div class="card">
      <h3>Quick Commands</h3>
      <div class="btn-row">
        <button class="btn secondary" onclick="sendCommand('Player.GetActivePlayers')">Active Players</button>
        <button class="btn secondary" onclick="sendCommand('Player.GetItem', {playerid: 1})">Now Playing</button>
        <button class="btn secondary" onclick="sendCommand('Application.GetProperties', {properties: ['volume', 'muted']})">Volume</button>
        <button class="btn secondary" onclick="sendCommand('GUI.GetProperties', {properties: ['fullscreen']})">Fullscreen</button>
        <button class="btn secondary" onclick="sendCommand('Player.PlayPause', {playerid: 1})">Play/Pause</button>
        <button class="btn secondary" onclick="sendCommand('Player.Stop', {playerid: 1})">Stop</button>
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
  <div class="panel" id="panel-webui">
    <div class="card">
      <h3>Kodi Web Interface</h3>
      <p style="color:#8b949e;font-size:13px;margin-bottom:12px;">
        Kodi's web interface, tunneled through the Xbox.
      </p>
      <iframe id="kodiFrame" src="" style="width:100%;height:600px;border:1px solid #30363d;border-radius:6px;background:#0d1117;"></iframe>
    </div>
  </div>
</div>
<div id="toast" class="toast" style="display:none;"></div>
<script>
let connected = false;
let eventCount = 0;
let sseConnected = false;

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
      document.getElementById('lastSeen').textContent = new Date().toLocaleTimeString();
      document.getElementById('liveIndicator').style.display = 'inline-flex';
      if (d.info) {
        const info = d.info;
        const grid = document.getElementById('kodiInfo');
        grid.innerHTML = '';
        for (const [k, v] of Object.entries(info)) {
          grid.innerHTML += `<div class="info-item"><label>${k}</label><span>${v || '—'}</span></div>`;
        }
      }
      if (!sseConnected) { connectSSE(); }
    } else {
      updateStatus('disconnected', 'Kodi add-on not connected');
      document.getElementById('connStatus').textContent = 'Disconnected';
      document.getElementById('liveIndicator').style.display = 'none';
      sseConnected = false;
    }
  } catch (e) {
    updateStatus('disconnected', 'Proxy server unreachable');
    document.getElementById('liveIndicator').style.display = 'none';
  }
}

function connectSSE() {
  if (sseConnected) return;
  sseConnected = true;
  const es = new EventSource('/api/events');
  es.onmessage = function(e) {
    try { handleRealtimeEvent(JSON.parse(e.data)); } catch (err) {}
  };
  es.onerror = function() { sseConnected = false; };
}

function handleRealtimeEvent(event) {
  eventCount++;
  document.getElementById('eventCount').textContent = eventCount;
  const type = event.type || '';
  const data = event.data || {};
  if (type === 'stats_update' || type.startsWith('playback_')) {
    if (data.now_playing) updateNowPlaying(data.now_playing);
    if (data.stats) updateStats(data.stats);
    if (data.volume) updateVolume(data.volume);
  }
  if (type === 'volume_changed' && data.volume !== undefined) {
    document.getElementById('statVol').textContent = data.volume + (data.muted ? ' (muted)' : '');
  }
  if (type === 'screensaver_on') {
    document.getElementById('npTitle').textContent = 'Screensaver Active';
    document.getElementById('npSub').textContent = '';
    document.getElementById('npProgress').style.display = 'none';
  }
  if (type === 'screensaver_off') {
    document.getElementById('npTitle').textContent = 'Nothing playing';
    document.getElementById('npSub').textContent = '—';
  }
  addEventToLog(event);
}

function updateNowPlaying(np) {
  if (!np.playing) {
    document.getElementById('npTitle').textContent = 'Nothing playing';
    document.getElementById('npSub').textContent = '—';
    document.getElementById('npProgress').style.display = 'none';
    return;
  }
  document.getElementById('npTitle').textContent = np.title || 'Unknown';
  const dur = np.duration ? formatTime(np.duration) : '—';
  const cur = np.time ? formatTime(np.time) : '—';
  document.getElementById('npSub').textContent = `${cur} / ${dur} (${np.player_type || 'media'})`;
  document.getElementById('npProgress').style.display = 'block';
  document.getElementById('npFill').style.width = (np.progress || 0) + '%';
}

function updateStats(stats) {
  if (stats.cpu) document.getElementById('statCpu').textContent = stats.cpu;
  if (stats.memory_free) document.getElementById('statMemFree').textContent = stats.memory_free;
  if (stats.memory_total) document.getElementById('statMemTotal').textContent = stats.memory_total;
  if (stats.uptime) document.getElementById('statUptime').textContent = stats.uptime;
  if (stats.temperature) document.getElementById('statTemp').textContent = stats.temperature;
}

function updateVolume(vol) {
  if (vol.volume !== undefined) {
    document.getElementById('statVol').textContent = vol.volume + (vol.muted ? ' (muted)' : '');
  }
}

function formatTime(seconds) {
  if (!seconds) return '0:00';
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = Math.floor(seconds % 60);
  if (h > 0) return `${h}:${m.toString().padStart(2,'0')}:${s.toString().padStart(2,'0')}`;
  return `${m}:${s.toString().padStart(2,'0')}`;
}

function addEventToLog(event) {
  const log = document.getElementById('eventLog');
  if (log.querySelector('div[style]')) log.innerHTML = '';
  const div = document.createElement('div');
  div.className = 'event-item';
  const ts = new Date((event.timestamp || Date.now()/1000) * 1000);
  const timeStr = ts.toLocaleTimeString() + '.' + ts.getMilliseconds().toString().padStart(3, '0');
  const dataStr = JSON.stringify(event.data || {}).substring(0, 100);
  div.innerHTML = `<span class="event-time">${timeStr}</span><span class="event-type">${event.type}</span><span class="event-data">${dataStr}</span>`;
  log.insertBefore(div, log.firstChild);
  while (log.children.length > 50) log.removeChild(log.lastChild);
}

function clearEvents() {
  document.getElementById('eventLog').innerHTML = '<div style="color:#8b949e;font-size:13px;padding:20px;text-align:center;">Events cleared. New events will appear here.</div>';
  eventCount = 0;
  document.getElementById('eventCount').textContent = '0';
}

async function fetchLogs(count) {
  try {
    const d = await api('/logs?lines=' + count);
    if (d.lines) {
      const viewer = document.getElementById('logViewer');
      let html = d.lines.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
      html = html.replace(/\b(ERROR)\b/g, '<span class="error">$1</span>');
      html = html.replace(/\b(WARN(?:ING)?)\b/g, '<span class="warn">$1</span>');
      html = html.replace(/\b(INFO|NOTICE)\b/g, '<span class="info">$1</span>');
      viewer.innerHTML = html;
      viewer.scrollTop = viewer.scrollHeight;
      document.getElementById('logMeta').textContent = `Showing last ${count} lines | Total: ${d.total_lines || '?'} lines | Path: ${d.path || 'unknown'}`;
      showToast('Logs fetched', 'success');
    } else if (d.error) {
      document.getElementById('logViewer').textContent = 'Error: ' + d.error;
    }
  } catch (e) {
    showToast('Failed to fetch logs: ' + e, 'error');
  }
}

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

checkStatus();
setInterval(checkStatus, 5000);
</script>
</body>
</html>"""
