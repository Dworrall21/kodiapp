# KodiXboxRemote iOS App — Phase 2 Polish Plan

> **For Hermes:** Planning/spec document only. Do not write implementation code until David explicitly approves. If implementing later, use `subagent-driven-development` and execute one task at a time with review after each task.

**Created:** 2026-05-11

**Current state:** The iPhone app (KodiXboxRemote) is installed via SideStore and working. Basic remote control pad (d-pad, select, back, home, play/pause, stop, mute, volume up/down) is functional. Telemetry (volume, muted, now playing label) is displayed in a minimal text-only section. The app has no custom icon (uses default SwiftUI placeholder).

---

## Goals

1. **In-app debugging panel** — show recent listener/connection/protocol events directly in the app for field testing.
2. **On-screen keyboard** — send text input to Kodi (for search, text entry fields).
3. **Full remote control layout** — dedicated buttons for all common Kodi actions: context menu, info, subtitles, audio track, fullscreen, etc.
4. **Now Playing panel** — rich now-playing display with title/metadata, playback state, volume/mute, and later thumbnail/progress support.
5. **Custom app icon** — a cute, recognizable icon for the home screen.

---

## Scope & Constraints

- iOS only, SwiftUI, Network.framework (existing stack).
- No new native dependencies.
- The bridge protocol (newline-delimited JSON over TCP) stays the same.
- The Kodi add-on already supports all needed JSON-RPC methods; no add-on changes required for keyboard/controls. Now-playing thumbnail may need a small add-on helper (see below).
- App must remain functional when the iPhone is locked/backgrounded is out of scope for this phase.

---

## Task Breakdown

### Task 0 — In-App Debugging Panel

**What:** Add a collapsible debug panel to the iPhone app so field testing does not require Xcode device logs.

**Approach:**
- Add an in-memory ring buffer of recent debug events in `RemoteViewModel`.
- Instrument listener lifecycle, connection lifecycle, protocol decode/send events, telemetry, command results, and errors.
- Add a SwiftUI `DebugLogView` with Show/Hide, enable/disable, latest event preview, and Clear Log.
- Do not log pairing token values or full command payload text.

**Files:**
- `ViewModels/RemoteViewModel.swift` — `DebugLogEntry`, log buffer, clear/toggle helpers.
- `Networking/BridgeServer.swift` — listener/accept/error debug hooks.
- `Networking/BridgeConnection.swift` — send/receive/decode/error debug hooks.
- `Protocol/BridgeMessage.swift` — message debug names.
- `Views/RemoteView.swift` — collapsible debug panel.

---

### Task 1 — On-Screen Keyboard

**What:** Add a keyboard button to the remote control pad that presents a text input UI. Typed text is sent to Kodi as it is entered (character by character) or as a submitted string.

**Approach:**
- Add a `KeyboardView` SwiftUI sheet or overlay with a `TextField` and Send/Dismiss buttons.
- On each character typed, send `Input.SendText` JSON-RPC with the current text buffer, or send on submit only. Start with submit-only for simplicity.
- After sending, clear the field and optionally dismiss.
- Add a keyboard SF Symbol button (`keyboard`) to the control pad row.

**Files:**
- `Views/RemoteView.swift` — add keyboard button + sheet presentation.
- `ViewModels/RemoteViewModel.swift` — add `sendText(_:)` method.

**JSON-RPC used:**
- `Input.SendText` — sends a string to Kodi's active text input.
- `Input.ExecuteAction` with `action: "enter"` — optional, to confirm after text.

---

### Task 2 — Full Remote Control Layout

**What:** Expand the control pad with all standard Kodi remote functions.

**New buttons to add:**

| Button | Label | JSON-RPC |
|--------|-------|----------|
| Context Menu | `Menu` | `Input.ContextMenu` |
| Info | `Info` | `Input.Info` |
| Subtitles | `Subs` | `Input.ExecuteAction` with `action: "nextsubtitle"` |
| Audio | `Audio` | `Input.ExecuteAction` with `action: "audionextlanguage"` |
| Fullscreen | `Full` | `Input.ExecuteAction` with `action: "fullscreen"` |
| OSD | `OSD` | `Input.ShowOSD` |
| Playlist | `List` | `Input.ExecuteAction` with `action: "playlist"` |
| Rewind | `<<` | `Input.ExecuteAction` with `action: "rewind"` |
| Fast Forward | `>>` | `Input.ExecuteAction` with `action: "fastforward"` |
| Chapter Back | `< Chap` | `Input.ExecuteAction` with `action: "chapterorbigstepback"` |
| Chapter Fwd | `Chap >` | `Input.ExecuteAction` with `action: "chapterorbigstepforward"` |

**Layout approach:**
- Reorganize `RemoteControlPad` into logical groups:
  - **Navigation row:** d-pad + select (keep existing layout).
  - **System row:** Back, Home, Context Menu, Info.
  - **Playback row:** Play/Pause, Stop, Rewind, Fast Forward.
  - **Audio/Video row:** Volume down, Mute, Volume up, Subtitles, Audio track, Fullscreen.
  - **Extra row:** OSD, Playlist, Chapter back, Chapter forward.
  - **Keyboard row:** Keyboard button.
- Use a scrollable VStack or LazyVGrid so all buttons fit on smaller screens.
- Keep existing button styling (rounded rectangles, SF Symbols, color coding).

**Files:**
- `Views/RemoteView.swift` — reorganize `RemoteControlPad`, add new button methods.
- `ViewModels/RemoteViewModel.swift` — no changes needed (existing `sendCommand` handles all methods).

---

### Task 3 — Now Playing Panel

**What:** Replace the minimal telemetry text section with a rich Now Playing card.

**Current state:** The app receives `telemetry` messages with `item` (label, title, artist, album, thumbnail), `volume`, `muted`, `active_players`.

**New Now Playing panel design:**
- Album artwork thumbnail on the left (loaded from URL or base64).
- Title, artist, album text stacked on the right.
- Progress bar (if playback position data is available).
- Time elapsed / time remaining labels below the progress bar.
- Play state icon (playing / paused).

**Thumbnail approach:**
- The add-on sends a base64-encoded thumbnail in the telemetry message. This avoids a second HTTP connection from the app.
- The add-on resolves Kodi's thumbnail path to raw image data via `xbmcvfs.FileRead`, base64-encodes it, and includes it as `thumbnail_b64` in the telemetry payload.
- The iPhone app decodes the base64 data and displays it as `Image(uiImage:)`.

**Progress bar approach:**
- Use `Player.GetProperties` to fetch `percentage` or `time` + `totaltime`.
- The add-on can include these fields in the telemetry payload, or the app can request them on demand.
- **Preferred:** Add `time` and `totaltime` to the telemetry payload in the add-on's `iphone_telemetry_payload()` function. This is a small add-on change.

**Files:**
- `Views/RemoteView.swift` — replace telemetry text section with `NowPlayingView`.
- `ViewModels/RemoteViewModel.swift` — add computed properties for formatted time, progress fraction.
- `Models/TelemetryMessage.swift` — add optional `time`, `totaltime` fields.
- `addon/default.py` — update `iphone_telemetry_payload()` to include `time` and `totaltime` from `Player.GetProperties`.

**Now Playing view layout:**
```
┌──────────────────────────────────────────┐
│  [artwork]  Title                        │
│             Artist                       │
│             Album                        │
│             ═══════●══════════           │
│             1:23:45      -0:45:12        │
│             ▶ (or ⏸)                     │
└──────────────────────────────────────────┘
```

---

### Task 4 — Custom App Icon

**What:** Design and add a custom app icon to replace the default SwiftUI placeholder.

**Approach:**
- Create an `AppIcon.appiconset` in `Assets.xcassets` (or create `Assets.xcassets` if it doesn't exist).
- Provide all required iOS icon sizes (or use a single 1024x1024 and let Xcode generate the rest).
- The icon should be cute and recognizable — a Kodi-like "K" or a gamepad + screen motif, in the app's accent color (orange/blue theme).

**Icon concept:** A "K" lettermark in a rounded rectangle (Kodi-inspired), in the app's accent color (orange/blue theme).

**Implementation:**
- Generate the icon as a 1024x1024 PNG.
- Add to `KodiXboxRemote/Assets.xcassets/AppIcon.appiconset/`.
- Update `Contents.json` with all required sizes.
- The CI build (GitHub Actions) will pick it up automatically since it's part of the Xcode project.

**Files to create/modify:**
- `iphone/KodiXboxRemote/KodiXboxRemote/Assets.xcassets/AppIcon.appiconset/Contents.json`
- `iphone/KodiXboxRemote/KodiXboxRemote/Assets.xcassets/AppIcon.appiconset/icon-1024.png` (and other sizes, or just 1024 for Xcode to scale).

---

## Execution Order

1. Task 0 (Debugging Panel) — first, so field-testing has visibility while later polish is tested.
2. Task 1 (Keyboard) — self-contained, adds text send flow.
3. Task 2 (Full Controls) — reorganizes existing view, no new protocol logic.
4. Task 3 (Now Playing) — start with local UI using existing telemetry; add artwork/progress add-on payload later.
5. Task 4 (App Icon) — independent visual polish.

---

## Decisions

- **Debugging:** In-app collapsible event log with listener/connection/send/receive/decode/result/error events. Keep token/payload values out of logs.
- **Thumbnail:** Add-on eventually sends base64-encoded image data in telemetry payload (`thumbnail_b64` field).
- **Progress data:** Add `time`/`totaltime` to telemetry payload (small add-on change).
- **Icon:** K-lettermark in rounded rectangle, orange/blue Kodi theme.

---

## Verification

After all tasks:
- [ ] Debug panel shows listener, connection, send/receive/decode, command result, telemetry, and error events without exposing tokens.
- [ ] Keyboard button appears on remote pad, presents text input, sends `Input.SendText`.
- [ ] All new control buttons appear and send correct JSON-RPC.
- [ ] Now Playing panel shows artwork, title, artist, album, progress bar, time.
- [ ] Custom icon appears on iPhone home screen.
- [ ] App builds cleanly in CI (GitHub Actions iOS build passes).
- [ ] No regressions in existing remote control functionality.
