# Native iPhone Remote Bridge — Option B2 Implementation Plan

> **For Hermes:** Use this as a planning/spec document only until David explicitly approves implementation. Do not write implementation code before approval. If implementing later, use `subagent-driven-development` and execute one task at a time with review after each task.

**Created:** 2026-05-11 07:09:13 PDT

**Next step:** Task 5 - Implement Kodi add-on outbound TCP client





**Goal:** Build a custom iPhone remote app that can control Xbox Kodi without a laptop/server proxy by having the iPhone app act as the temporary local bridge/server while it is open, and having the Xbox Kodi add-on connect outbound to it.

**Architecture:** The iPhone app runs a local LAN listener while foregrounded. The Xbox Kodi add-on connects outward to the iPhone, which is allowed by the Xbox Retail Mode sandbox. The app sends simple JSON-line commands over the connection, the add-on executes them with `xbmc.executeJSONRPC`, and the add-on returns results and telemetry to the app. This avoids needing the existing laptop proxy for remote-control use, but the iPhone app must be open for the connection to exist.

**Tech Stack:** Existing Kodi add-on Python stdlib, Kodi JSON-RPC via `xbmc.executeJSONRPC`, raw TCP JSON-lines protocol, Swift/iOS app using Network.framework, optional Bonjour discovery with Network.framework, XCTest for app-level unit tests where practical, Python unit tests for protocol helpers where practical.

---

## Product Summary

Option B2 is a separate route from Option A.

Option A makes the existing laptop proxy discoverable by the official Kodi remote.

Option B2 replaces the laptop proxy for basic remote-control use with a custom iPhone app:

```text
iPhone app, foregrounded
  - local TCP listener
  - remote-control UI
  - optional Bonjour advertisement
        ↑ outbound connection from Xbox add-on
Xbox Kodi add-on
  - connects to iPhone app
  - receives commands
  - executes Kodi JSON-RPC locally
  - sends results/telemetry back
Kodi on Xbox
```

This does not make the official Kodi remote work. It is a custom remote app and custom add-on bridge mode.

---

## Important Constraints

1. Xbox Retail Mode blocks inbound LAN TCP to Kodi.
   - The iPhone cannot directly connect to Xbox Kodi.
   - The add-on must initiate the network connection outward.

2. iOS background networking is limited.
   - The iPhone app should be assumed to work only while open/foregrounded.
   - Do not design MVP around reliable background server behavior.

3. Kodi Xbox add-on dependencies must remain minimal.
   - Use Python stdlib only in the add-on bridge implementation.
   - Avoid third-party Python packages.

4. Raw TCP JSON-lines is preferred for MVP.
   - Simpler than WebSocket on both Swift server and Kodi Python client.
   - Avoids WebSocket masking/ping/pong issues already encountered in the proxy project.

5. Existing laptop proxy support should remain intact.
   - Do not remove or regress current WebSocket proxy mode.
   - Add the iPhone bridge as a separate mode or additional connection target.

---

## MVP Scope

### Included

- iPhone app can start/stop a local listener.
- App displays listener status, IP address, port, and add-on connection status.
- Xbox add-on can connect outbound to the app using configured host/port.
- Basic pairing token or shared secret prevents accidental LAN control.
- App remote UI includes:
  - Up
  - Down
  - Left
  - Right
  - Select/OK
  - Back
  - Home
  - Play/Pause
  - Stop
  - Volume Up
  - Volume Down
  - Mute toggle
- Add-on executes commands through `xbmc.executeJSONRPC`.
- Add-on sends command results and periodic telemetry back to the app.
- App shows basic telemetry:
  - connected/disconnected
  - Kodi version/name if available
  - active player state if available
  - volume/mute if available

### Not Included in MVP

- App Store distribution.
- Full media library browsing.
- Artwork thumbnails.
- Background server operation.
- Cloud relay.
- WebRTC/NAT traversal.
- Official Kodi remote compatibility.
- Replacing the existing laptop proxy dashboard.
- Automatic install/update of the Kodi add-on from the iPhone app.

---

## Proposed Repository Layout

Assuming this work stays in the existing repo:

```text
/home/david/kodi-xbox-proxy/
  addon/
    default.py
    resources/settings.xml
  iphone/
    KodiXboxRemote/
      KodiXboxRemote.xcodeproj or Package.swift structure
      KodiXboxRemote/
        App entry files
        Networking/
        Protocol/
        Views/
        ViewModels/
      KodiXboxRemoteTests/
  docs/
    iphone-remote-bridge.md
  tests/
    test_phone_bridge_protocol.py
```

If David prefers a separate GitHub repo for the iPhone app, keep the Kodi add-on changes here and create/link the iPhone app repo separately. For MVP planning, keeping an `iphone/` directory in this repo is acceptable because the app and add-on protocol evolve together.

---

## Protocol Design

Use newline-delimited JSON over TCP.

Each message is one UTF-8 JSON object followed by `\n`.

All messages include:

```json
{
  "type": "...",
  "id": "optional request id"
}
```

### Connection Flow

1. iPhone app starts TCP listener.
2. Xbox add-on connects to configured host/port.
3. Add-on sends `hello`.
4. App sends `auth_required` or `auth_ok` depending on config.
5. Add-on sends `auth` if required.
6. App sends `auth_ok`.
7. App can send `command` messages.
8. Add-on sends `result`, `error`, and `telemetry` messages.

### Message: hello

Direction: add-on → app

```json
{
  "type": "hello",
  "protocol": "iphone-bridge-v1",
  "addon_id": "script.xbox.proxy",
  "addon_version": "1.0.8",
  "kodi_name": "Kodi",
  "kodi_version": "21.x",
  "platform": "Xbox"
}
```

### Message: auth

Direction: add-on → app

```json
{
  "type": "auth",
  "token": "shared-token-from-settings"
}
```

### Message: auth_ok

Direction: app → add-on

```json
{
  "type": "auth_ok"
}
```

### Message: auth_error

Direction: app → add-on

```json
{
  "type": "auth_error",
  "message": "Invalid token"
}
```

### Message: command

Direction: app → add-on

```json
{
  "type": "command",
  "id": "cmd-0001",
  "method": "Input.Up",
  "params": {}
}
```

### Message: result

Direction: add-on → app

```json
{
  "type": "result",
  "id": "cmd-0001",
  "ok": true,
  "result": "OK or JSON-RPC result object"
}
```

### Message: error

Direction: either direction

```json
{
  "type": "error",
  "id": "cmd-0001",
  "message": "Human-readable error",
  "code": "optional_machine_code"
}
```

### Message: telemetry

Direction: add-on → app

```json
{
  "type": "telemetry",
  "timestamp": 1778508553,
  "active_players": [],
  "volume": 80,
  "muted": false,
  "item": null
}
```

---

## Command Mapping

The iPhone UI should map buttons to these Kodi JSON-RPC methods:

```text
Up:          Input.Up
Down:        Input.Down
Left:        Input.Left
Right:       Input.Right
Select:      Input.Select
Back:        Input.Back
Home:        Input.Home
Play/Pause:  Player.PlayPause with active playerid, or Input.ExecuteAction(playpause) fallback
Stop:        Player.Stop with active playerid, or Input.ExecuteAction(stop) fallback
Volume Up:   Application.SetVolume after reading current volume, or Input.ExecuteAction(volumeup)
Volume Down: Application.SetVolume after reading current volume, or Input.ExecuteAction(volumedown)
Mute:        Application.SetMute with toggle, or Input.ExecuteAction(mute)
```

For MVP simplicity, prefer JSON-RPC methods that do not require pre-reading state when possible:

```json
{"method":"Input.ExecuteAction","params":{"action":"volumeup"}}
{"method":"Input.ExecuteAction","params":{"action":"volumedown"}}
{"method":"Input.ExecuteAction","params":{"action":"mute"}}
{"method":"Input.ExecuteAction","params":{"action":"playpause"}}
{"method":"Input.ExecuteAction","params":{"action":"stop"}}
```

Navigation methods can use direct `Input.*` calls.

---

## Add-on Settings

Modify `addon/resources/settings.xml` to add an iPhone bridge section.

Proposed settings:

```xml
<category label="iPhone Remote Bridge">
    <setting id="enable_iphone_bridge" type="bool" label="Enable iPhone Remote Bridge" default="false"/>
    <setting id="iphone_bridge_host" type="text" label="iPhone Bridge Host" default=""/>
    <setting id="iphone_bridge_port" type="number" label="iPhone Bridge Port" default="9192"/>
    <setting id="iphone_bridge_token" type="text" label="iPhone Bridge Token" default=""/>
    <setting id="iphone_bridge_reconnect_min_seconds" type="number" label="Minimum Reconnect Delay Seconds" default="3"/>
    <setting id="iphone_bridge_reconnect_max_seconds" type="number" label="Maximum Reconnect Delay Seconds" default="30"/>
</category>
```

MVP manual setup:
1. User opens iPhone app.
2. App shows IP and port.
3. User enters those values in Kodi add-on settings.
4. Add-on connects.

Later enhancement:
- iPhone app advertises `_kodi-xbox-remote._tcp.local.` via Bonjour.
- Add-on discovers the phone automatically if Kodi Python APIs permit or if a simple UDP discovery mechanism is implemented.

---

## Implementation Tasks

[x] ### Task 1: Confirm iOS listener feasibility with Network.framework spike

**Objective:** Verify a Swift iOS app can run a foreground TCP listener suitable for the bridge.

**Files:**
- Create spike under `iphone/SpikeTCPListener/` or document outside main app if preferred.

**Steps:**
1. Create minimal Swift app or Swift package using `NWListener`.
2. Listen on port `9192`.
3. Accept one TCP connection.
4. Read newline-delimited text.
5. Echo a JSON-line response.

**Verification:**
- From another LAN machine, connect with `nc <iphone-ip> 9192` and send a JSON line.
- App receives and echoes the message.
- iOS Local Network permission prompt appears and is handled.

**Stop Condition:**
- If iOS foreground TCP listening is not practical, stop and redesign before touching the Kodi add-on.

---

[x] ### Task 2: Define shared protocol constants and examples

**Objective:** Freeze the MVP protocol shape before coding both ends.

**Files:**
- Create: `docs/iphone-remote-bridge.md`
- Optional create: `tests/fixtures/iphone_bridge_messages/*.jsonl`

**Content:**
- Message framing: one JSON object per line.
- Message types: `hello`, `auth`, `auth_ok`, `auth_error`, `command`, `result`, `error`, `telemetry`, `ping`, `pong`.
- Required/optional fields.
- Command mapping table.
- Version string: `iphone-bridge-v1`.

**Verification:**
- The document has enough detail for an LLM or developer to implement either side without guessing.

---

[ ] ### Task 3: Add protocol parsing helpers to the Kodi add-on

**Objective:** Add safe JSON-lines parsing/serialization helpers in Python stdlib.

**Files:**
- Modify: `addon/default.py`
- Test if possible: `tests/test_phone_bridge_protocol.py`

**Implementation Requirements:**
- Function to encode JSON message to bytes with trailing newline.
- Function or loop to buffer bytes and split on newline.
- Reject messages over a reasonable max size, e.g. 256 KB.
- Handle invalid JSON by sending an `error` message, not crashing the service loop.

**Verification:**
- Tests cover single message, multiple messages in one chunk, partial messages across chunks, invalid JSON, and oversized message.

---

[ ] ### Task 4: Add add-on iPhone bridge configuration loading

**Objective:** Read new settings without affecting existing proxy mode.

**Files:**
- Modify: `addon/resources/settings.xml`
- Modify: `addon/default.py`

**Implementation Requirements:**
- Add `enable_iphone_bridge` boolean.
- Add `iphone_bridge_host`, `iphone_bridge_port`, `iphone_bridge_token`.
- Add reconnect delay settings.
- Existing bridge settings for laptop proxy remain unchanged.

**Verification:**
- Add-on can still load config if iPhone bridge settings are absent or disabled.
- Existing laptop proxy mode still behaves as before.

---

[ ] ### Task 5: Implement Kodi add-on outbound TCP client

**Objective:** Add a separate client loop that connects from Xbox Kodi to the iPhone app.

**Files:**
- Modify: `addon/default.py`

**Implementation Requirements:**
- Use Python stdlib `socket` only.
- Connect to configured iPhone host/port.
- Send `hello` after connection.
- If token configured, send `auth`.
- Read JSON-lines in a loop.
- Reconnect with exponential backoff when disconnected.
- Do not block the existing add-on service loop permanently.
- Respect Kodi monitor abort/shutdown.

**Design Choice:**
- Prefer running the iPhone bridge loop in a separate thread so existing laptop proxy behavior can remain available.
- If supporting both loops simultaneously is too risky for MVP, use a mode setting:
  - `proxy` mode
  - `iphone_bridge` mode
  - Later: `both`

**Verification:**
- A simple Python TCP server on the laptop can accept the add-on connection and receive `hello`.
- Disconnecting the server causes the add-on to reconnect without crashing.

---

[ ] ### Task 6: Implement add-on command execution

**Objective:** Execute commands received from the iPhone app via Kodi JSON-RPC.

**Files:**
- Modify: `addon/default.py`

**Implementation Requirements:**
- Accept only allowlisted methods/actions for MVP.
- Prevent arbitrary JSON-RPC execution unless David explicitly approves it.
- Map safe UI commands to `xbmc.executeJSONRPC`.
- Send `result` or `error` with matching request `id`.

**Initial allowlist:**

```text
Input.Up
Input.Down
Input.Left
Input.Right
Input.Select
Input.Back
Input.Home
Input.ExecuteAction with actions:
  playpause
  stop
  volumeup
  volumedown
  mute
Application.GetProperties
Player.GetActivePlayers
Player.GetItem
Player.GetProperties
```

**Verification:**
- Sending each command from a test TCP server changes Kodi behavior or returns expected JSON-RPC result.
- Unknown method returns an error and does not execute.

---

[ ] ### Task 7: Implement add-on telemetry loop

**Objective:** Send basic Kodi state to the iPhone app periodically.

**Files:**
- Modify: `addon/default.py`

**Implementation Requirements:**
- Every 2-5 seconds while connected, gather:
  - active players
  - application volume/mute
  - current item if a player is active
  - player speed/time if available
- Send as `telemetry` message.
- Failures should be included as partial telemetry or logged; do not disconnect solely because telemetry fails.

**Verification:**
- Test server receives telemetry while Kodi is idle.
- Test server receives updated telemetry during playback if media is playing.

---

[x] ### Task 8: Create iPhone app skeleton

**Objective:** Create the native app project with basic structure.

**Files:**
- Create under: `iphone/KodiXboxRemote/`

**Suggested modules:**

```text
KodiXboxRemoteApp.swift
Views/RemoteView.swift
Views/ConnectionStatusView.swift
ViewModels/RemoteViewModel.swift
Networking/BridgeServer.swift
Networking/BridgeConnection.swift
Protocol/BridgeMessage.swift
Protocol/KodiCommand.swift
```

**Implementation Requirements:**
- SwiftUI app.
- App requests/uses Local Network permission via required Info.plist descriptions.
- App can start listener on configurable/default port `9192`.
- App displays listener status and local IP if available.

**Verification:**
- App builds in Xcode.
- App launches on simulator/device.
- Listener start/stop state updates in UI.

---

[x] ### Task 9: Implement iPhone TCP bridge server

**Objective:** Accept one add-on connection and exchange JSON-lines messages.

**Files:**
- Modify: `iphone/KodiXboxRemote/KodiXboxRemote/Networking/BridgeServer.swift`
- Modify: `iphone/KodiXboxRemote/KodiXboxRemote/Networking/BridgeConnection.swift`
- Modify: `iphone/KodiXboxRemote/KodiXboxRemote/Protocol/BridgeMessage.swift`

**Implementation Requirements:**
- Use `NWListener` with TCP.
- Accept at least one connection; MVP can reject or replace additional connections.
- Buffer incoming bytes and split on newline.
- Decode JSON into typed messages.
- Publish connection state to `RemoteViewModel`.
- Send messages with trailing newline.
- Handle disconnect and listener restart cleanly.

**Verification:**
- Python test client can connect to the app and exchange `hello`, `auth`, and `telemetry` messages.

---

[x] ### Task 10: Implement iPhone command sender

**Objective:** Send Kodi commands from view model to connected add-on.

**Files:**
- Modify: `iphone/KodiXboxRemote/KodiXboxRemote/ViewModels/RemoteViewModel.swift`
- Modify: `iphone/KodiXboxRemote/KodiXboxRemote/Protocol/KodiCommand.swift`

**Implementation Requirements:**
- Generate unique command IDs.
- Send `command` messages.
- Track pending command results for debugging.
- Surface command errors in UI or logs.

**Verification:**
- Pressing a test button sends a JSON command to a Python test client.
- Test client response clears or updates pending state.

---

[x] ### Task 11: Build MVP remote UI

**Objective:** Provide usable remote controls.

**Files:**
- Modify: `iphone/KodiXboxRemote/KodiXboxRemote/Views/RemoteView.swift`
- Modify: `iphone/KodiXboxRemote/KodiXboxRemote/Views/ConnectionStatusView.swift`
- Modify: `iphone/KodiXboxRemote/KodiXboxRemote/ViewModels/RemoteViewModel.swift`

**UI Requirements:**
- Connection banner:
  - listener stopped/running
  - waiting for Xbox
  - connected
  - auth failed
- Show local IP and port.
- D-pad layout.
- Playback controls row.
- Volume controls row.
- Disable command buttons when no add-on is connected.

**Verification:**
- UI is usable on an iPhone screen.
- Button taps generate correct protocol messages.

---

[x] ### Task 12: Add pairing token support

**Objective:** Prevent accidental LAN clients from controlling Kodi.

**Files:**
- Modify: app networking/view model files.
- Modify: `addon/default.py`
- Modify: `addon/resources/settings.xml`

**Implementation Requirements:**
- App has a configurable token displayed or generated in settings.
- Add-on stores same token.
- App accepts commands only after valid `auth`.
- If token is blank, app may allow unauthenticated mode for debugging with a visible warning.

**Verification:**
- Correct token connects.
- Wrong token gets `auth_error` and cannot send commands.

---

[x] ### Task 13: Add optional Bonjour advertisement from iPhone app

**Objective:** Prepare for easier future discovery by the add-on or companion tooling.

**Files:**
- Modify: iPhone networking module.

**Service Type:**

```text
_kodi-xbox-remote._tcp.local.
```

**Properties:**

```text
protocol=iphone-bridge-v1
name=David's iPhone Kodi Remote
```

**MVP Note:**
- The add-on does not need to consume this in the first implementation.
- This is useful for diagnostics and future automatic discovery.

**Verification:**
- `dns-sd -B _kodi-xbox-remote._tcp local` or `avahi-browse -rt _kodi-xbox-remote._tcp` sees the iPhone app while open.

---

[ ] ### Task 14: Integration test with desktop simulator components

**Objective:** Test protocol behavior before installing on Xbox/iPhone.

**Files:**
- Create optional scripts under `tools/iphone_bridge/`:
  - `mock_iphone_bridge_server.py`
  - `mock_kodi_addon_client.py`

**Tests:**
1. Mock iPhone server accepts add-on connection.
2. Mock server sends commands.
3. Add-on/client returns results.
4. Disconnect/reconnect works.
5. Invalid command is rejected.

**Verification:**
- Local tests pass without requiring Xbox or iPhone.

---

[ ] ### Task 15: Package and deploy updated Kodi add-on

**Objective:** Build an installable add-on package after implementation is approved and complete.

**Files:**
- Existing package/repo files per current project workflow.

**Important Existing Project Rules:**
- Zip root must be `script.xbox.proxy/`, not `addon/`.
- Keep dependency imports minimal and exactly matching repo metadata.
- Use the deterministic packaging process from the `kodi-xbox-proxy` skill.
- Do not regress existing laptop proxy mode.

**Verification:**
- `unzip -l addon.zip` shows `script.xbox.proxy/addon.xml`.
- Add-on installs/updates on Xbox Kodi.
- Existing proxy mode still connects to laptop proxy.

---

[ ] ### Task 16: End-to-end validation on real devices

**Objective:** Confirm the custom iPhone remote controls Xbox Kodi without the laptop proxy running.

**Preconditions:**
- iPhone and Xbox are on the same LAN.
- iPhone app is installed and open.
- Updated add-on is installed on Xbox Kodi.
- Add-on iPhone bridge settings point to iPhone IP/port or auto-discovery is implemented.
- Existing laptop proxy is stopped to prove it is not required.

**Validation Steps:**
1. Stop laptop proxy.
2. Open iPhone app.
3. Start listener.
4. Confirm app shows IP/port.
5. Start or restart Kodi on Xbox.
6. Confirm add-on connects to iPhone app.
7. Press Up/Down/Left/Right/Select/Back.
8. Test Play/Pause/Stop if media is active.
9. Test Volume Up/Down/Mute.
10. Confirm telemetry updates.
11. Close iPhone app and confirm add-on disconnects/retries gracefully.
12. Reopen app and confirm reconnect.

**Acceptance:**
- Xbox Kodi is controllable from the iPhone app while the app is open.
- The laptop proxy is not running during the test.

---

## Risks and Mitigations

### Risk: iOS foreground listener is unreliable or blocked

Mitigation:
- Run Task 1 as a spike before touching the Kodi add-on.
- If blocked, pivot to app-as-client with a lightweight always-on relay/proxy.

### Risk: iPhone IP changes frequently

Mitigation:
- MVP shows IP prominently for manual configuration.
- Later add Bonjour discovery or UDP beacon so the add-on can find the app.

### Risk: Background operation is expected but not feasible

Mitigation:
- Set product expectation clearly: app must be open.
- Do not promise background server operation for MVP.

### Risk: Raw TCP protocol grows into a custom ad hoc mess

Mitigation:
- Version the protocol from day one.
- Keep all messages documented in `docs/iphone-remote-bridge.md`.
- Add typed Swift models and Python helper functions.

### Risk: Security on LAN

Mitigation:
- Add shared pairing token in MVP.
- Restrict command allowlist.
- Do not allow arbitrary JSON-RPC unless explicitly approved later.

### Risk: Existing proxy mode regresses

Mitigation:
- Keep bridge modes separated.
- Add tests and manual validation for existing proxy status after changes.
- Package only after both modes are checked.

---

## Recommended Build Order

1. iOS TCP listener spike.
2. Protocol document.
3. Add-on protocol parser helpers.
4. Add-on outbound TCP client to mock server.
5. Add-on command execution allowlist.
6. iPhone app skeleton.
7. iPhone bridge server.
8. iPhone remote UI.
9. Pairing token.
10. End-to-end real-device test.
11. Optional Bonjour discovery from iPhone app.
12. Package and publish add-on update.

---

## Definition of Done

Option B2 is done when:

- The iPhone app can run a local listener while open.
- The Xbox add-on can connect outbound to the iPhone app.
- The app can send remote-control commands.
- Kodi executes those commands on Xbox.
- Basic telemetry returns to the app.
- A shared token prevents unauthenticated control when configured.
- The laptop proxy is not running during the successful end-to-end validation.
- Existing laptop proxy mode still works after the add-on changes.
- The protocol and setup are documented well enough for future LLM/developer continuation.
