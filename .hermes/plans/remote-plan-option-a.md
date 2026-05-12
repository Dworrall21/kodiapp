# Zeroconf Discovery for Official Kodi Remote — Option A

> **For Hermes:** This is a planning document only. Do not implement code until David explicitly approves this plan or a revised plan.

**Created:** 2026-05-11 06:51:40 PDT

**Goal:** Make the existing Kodi Xbox Proxy discoverable by the official Kodi phone remote by advertising the proxy on the LAN as a Kodi JSON-RPC service via Zeroconf/Bonjour/mDNS.

**Architecture:** The Xbox Kodi add-on continues to connect outbound to the laptop proxy over WebSocket, avoiding the Xbox Retail Mode inbound TCP restriction. The laptop proxy advertises itself on the LAN as a Kodi instance. The phone remote discovers the laptop proxy, connects to its HTTP JSON-RPC endpoint, and the existing proxy code tunnels those JSON-RPC requests back to Kodi on the Xbox.

**Tech Stack:** Python 3.10+, existing `kodi-xbox-proxy` package, `websockets`, proposed `zeroconf` Python package, Kodi JSON-RPC over HTTP, Bonjour/mDNS.

---

## Current Context

Xbox Kodi in Retail Mode cannot expose normal inbound LAN services because of the Xbox/UWP sandbox. Kodi's built-in Zeroconf option is unavailable or locked down, so the phone remote cannot discover the Xbox directly.

The existing proxy already solves the inbound-control problem:

```text
Phone/browser → laptop proxy HTTP :8080 → WebSocket tunnel :9191 → Xbox add-on → Kodi localhost JSON-RPC
```

The missing piece is discovery. The proxy should advertise itself as the Kodi instance the phone should connect to.

---

## Proposed Approach

Implement mDNS/Zeroconf advertisement in the laptop proxy server.

Advertise:

```text
Service name:  Kodi Xbox via Proxy
Service type:  _kodi-jsonrpc._tcp.local.
Host/IP:       laptop LAN IPv4 address, e.g. 10.0.0.4
Port:          8080
```

The phone remote should then see the proxy as a Kodi instance and send JSON-RPC requests to:

```text
http://<laptop-lan-ip>:8080/jsonrpc
```

The existing `http_handler.py` already routes `/jsonrpc` through the Xbox add-on tunnel, so no Xbox add-on changes should be needed for Option A unless validation proves otherwise.

---

## Acceptance Criteria

- Proxy starts normally with Zeroconf enabled.
- Proxy continues to work if Zeroconf fails; discovery failure must not kill HTTP/WebSocket proxying.
- The advertised address is reachable from phones on the LAN, not `127.0.0.1` or `0.0.0.0`.
- An mDNS browser can see the advertised Kodi service.
- The official Kodi phone remote discovers `Kodi Xbox via Proxy`.
- The phone remote can connect and issue at least one basic command through the proxy, such as navigation or play/pause.

---

## Likely Files to Change

- Modify: `pyproject.toml`
  - Add `zeroconf>=0.132.0` dependency.

- Modify: `src/kodi_xbox_proxy/config.py`
  - Add Zeroconf configuration constants and/or environment overrides.

- Create: `src/kodi_xbox_proxy/zeroconf_advertiser.py`
  - Own IP selection, service-info construction, registration, and cleanup.

- Modify: `src/kodi_xbox_proxy/__main__.py`
  - Start the advertiser after the HTTP server starts.
  - Stop/unregister the advertiser during shutdown.

- Optional modify: `src/kodi_xbox_proxy/http_handler.py`
  - Add discovery status to `/api/status` or expose a separate `/api/discovery` endpoint.

- Optional modify: `src/kodi_xbox_proxy/web_ui.py`
  - Display discovery status in the dashboard.

- Create: `tests/test_zeroconf_advertiser.py`
  - Cover deterministic helper logic.

- Modify: `README.md` or project docs
  - Document phone remote discovery setup and troubleshooting.

---

## Open Questions Before Implementation

1. Confirm the exact service type and TXT record shape required by the iPhone remote.
   - Likely service type: `_kodi-jsonrpc._tcp.local.`
   - Need to verify whether TXT fields such as `uuid`, `version`, `name`, or `txtvers` are required.

2. Confirm whether the iPhone app needs only HTTP JSON-RPC or also expects a WebSocket/event endpoint.
   - Option A assumes HTTP JSON-RPC on port 8080 is enough.
   - If the app discovers the proxy but cannot fully connect, a later option may need a WebSocket compatibility layer.

3. Confirm desired display name.
   - Proposed: `Kodi Xbox via Proxy`

4. Confirm whether discovery should be enabled by default.
   - Proposed: enabled by default, with environment/config override to disable.

---

## Step-by-Step Plan

### Task 1: Verify Kodi remote discovery requirements

**Objective:** Confirm the minimum Bonjour/mDNS service shape required by the official phone remote before implementation.

**Files:**
- No project files modified.
- Notes may be added to this plan or a follow-up plan revision.

**Steps:**
1. Inspect official Kodi remote/Kore source or docs for Zeroconf discovery.
2. Identify service type, port expectations, and TXT fields.
3. Record the minimum compatible advertisement shape.

**Verification:**
- We can state the exact service type and any required TXT keys before coding.

---

### Task 2: Add dependency and configuration

**Objective:** Add explicit project support for Zeroconf without changing runtime behavior yet.

**Files:**
- Modify: `pyproject.toml`
- Modify: `src/kodi_xbox_proxy/config.py`

**Proposed config values:**

```python
ZEROCONF_ENABLED = True
ZEROCONF_NAME = os.environ.get("KODI_PROXY_ZEROCONF_NAME", "Kodi Xbox via Proxy")
ZEROCONF_SERVICE_TYPE = os.environ.get("KODI_PROXY_ZEROCONF_TYPE", "_kodi-jsonrpc._tcp.local.")
ZEROCONF_ADVERTISE_HOST = os.environ.get("KODI_PROXY_ADVERTISE_HOST", "")
```

**Verification:**
- Existing package imports still work.
- Proxy can still start with discovery disabled.

---

### Task 3: Implement LAN IP selection helper

**Objective:** Safely choose the address that should be advertised to the phone.

**Files:**
- Create: `src/kodi_xbox_proxy/zeroconf_advertiser.py`
- Test: `tests/test_zeroconf_advertiser.py`

**Behavior:**
- If `KODI_PROXY_ADVERTISE_HOST` is set, use it after validation.
- Reject `127.0.0.1`, `localhost`, and `0.0.0.0` for advertisement.
- Otherwise derive the LAN IPv4 address using a UDP socket route check.
- Fall back gracefully with a clear error if no usable address is found.

**Verification:**
- Unit tests cover loopback rejection, override handling, and fallback behavior.

---

### Task 4: Implement service-info construction

**Objective:** Build a Kodi-compatible Zeroconf service record.

**Files:**
- Modify: `src/kodi_xbox_proxy/zeroconf_advertiser.py`
- Test: `tests/test_zeroconf_advertiser.py`

**Proposed service data:**

```text
name:       Kodi Xbox via Proxy._kodi-jsonrpc._tcp.local.
type:       _kodi-jsonrpc._tcp.local.
address:    laptop LAN IPv4
port:       8080
properties: minimal Kodi-compatible TXT fields confirmed in Task 1
```

**Verification:**
- Unit tests assert service type, name, port, address bytes, and TXT fields.

---

### Task 5: Implement advertiser lifecycle wrapper

**Objective:** Provide start/stop registration logic with safe error handling.

**Files:**
- Modify: `src/kodi_xbox_proxy/zeroconf_advertiser.py`

**Behavior:**
- `start()` registers the service and records status.
- `stop()` unregisters and closes Zeroconf resources.
- Registration exceptions are caught and logged; they should not crash the proxy.
- Status is available for API/dashboard reporting.

**Verification:**
- Manual test can instantiate, start, and stop the advertiser without leaving stale registration state.

---

### Task 6: Hook advertiser into proxy startup/shutdown

**Objective:** Start discovery as part of normal proxy startup.

**Files:**
- Modify: `src/kodi_xbox_proxy/__main__.py`

**Behavior:**
- Start HTTP server first.
- Start Zeroconf advertisement for the HTTP port.
- Start WebSocket server as before.
- On KeyboardInterrupt or shutdown, unregister the service.

**Important:**
- Do not use `localhost` in advertised records.
- Do not let discovery failure prevent the proxy from serving HTTP/WebSocket.

**Verification:**
- `curl -s http://127.0.0.1:8080/api/status` still responds.
- Proxy still listens on 8080 and 9191.

---

### Task 7: Add discovery status endpoint or status field

**Objective:** Make discovery state visible for debugging.

**Files:**
- Modify: `src/kodi_xbox_proxy/http_handler.py`
- Optional modify: `src/kodi_xbox_proxy/web_ui.py`

**Proposed JSON shape:**

```json
{
  "zeroconf": {
    "enabled": true,
    "registered": true,
    "name": "Kodi Xbox via Proxy",
    "service_type": "_kodi-jsonrpc._tcp.local.",
    "host": "10.0.0.4",
    "port": 8080,
    "error": null
  }
}
```

**Verification:**
- API reports registered status and advertised address.

---

### Task 8: Add documentation

**Objective:** Document how David should use the official phone remote with Xbox Kodi through the proxy.

**Files:**
- Modify: `README.md` or project docs.

**Content:**
- Start the proxy.
- Ensure the Xbox add-on is connected.
- Open the phone remote and scan for Kodi instances.
- Select `Kodi Xbox via Proxy`.
- If it does not appear, verify mDNS with `avahi-browse`/`dns-sd` and check firewall/LAN isolation.

**Verification:**
- Documentation includes exact commands and expected results.

---

### Task 9: Manual validation

**Objective:** Prove discovery and control work end to end.

**Commands:**

```bash
curl -s http://127.0.0.1:8080/api/status | python3 -m json.tool
```

Use one of these depending on availability:

```bash
avahi-browse -rt _kodi-jsonrpc._tcp
```

```bash
dns-sd -B _kodi-jsonrpc._tcp local
```

Phone validation:
1. Start proxy.
2. Confirm Xbox add-on connected.
3. Open official Kodi remote on iPhone.
4. Run discovery.
5. Select `Kodi Xbox via Proxy`.
6. Test navigation, select, back, play/pause, and volume.

**Verification:**
- The phone discovers the proxy.
- Commands sent from the phone affect Xbox Kodi.

---

## Risks and Tradeoffs

### Risk: The phone app requires more than HTTP JSON-RPC

If discovery works but control fails, the app may expect WebSocket events or specific Kodi endpoints beyond `/jsonrpc`.

Mitigation:
- Keep Option A small.
- Treat WebSocket/event compatibility as a separate follow-up option only if needed.

### Risk: TXT records are stricter than expected

The service may be visible in generic mDNS tools but ignored by the app.

Mitigation:
- Verify the official discovery code before implementing.
- Add TXT fields to match real Kodi advertisements.

### Risk: Wrong IP advertised

Advertising `127.0.0.1` or `0.0.0.0` would make discovery appear but connection fail.

Mitigation:
- Validate and test IP selection.
- Add an override env var for David’s LAN if automatic detection is wrong.

### Risk: LAN/firewall/multicast issues

mDNS uses multicast UDP 5353. Some networks isolate clients or block multicast.

Mitigation:
- Provide manual IP fallback instructions.
- Provide mDNS browser validation steps.

---

## Out of Scope for Option A

- No Xbox add-on protocol changes.
- No new phone app.
- No WebSocket JSON-RPC event facade unless testing proves required.
- No attempt to modify Xbox/Kodi Zeroconf settings directly.
- No implementation before explicit approval.
