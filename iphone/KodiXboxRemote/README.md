# KodiXboxRemote iPhone app

This is the custom Option B2 iPhone remote app source.

Architecture:

- The iPhone app opens a local TCP listener while foregrounded.
- The Xbox Kodi add-on connects outbound to the iPhone IP/port.
- Messages are newline-delimited JSON using `iphone-bridge-v1`.
- The app sends remote-control JSON-RPC command messages.
- The add-on executes those commands locally in Kodi and sends results/telemetry back.

Important: this is not official Kore compatibility. It is a custom companion app for the Kodi Xbox Proxy add-on.

## Current source layout

```text
iphone/KodiXboxRemote/KodiXboxRemote/
  KodiXboxRemoteApp.swift
  Protocol/BridgeMessage.swift
  Networking/BridgeServer.swift
  Networking/BridgeConnection.swift
  ViewModels/RemoteViewModel.swift
  Views/RemoteView.swift
  Views/ConnectionStatusView.swift
  Resources/Info.plist
```

## Opening in Xcode

This Linux environment cannot generate or validate an `.xcodeproj` with Xcode. To run on an iPhone:

1. On a Mac, create a new iOS App project in Xcode named `KodiXboxRemote`.
2. Use SwiftUI for the interface and Swift for language.
3. Set the bundle identifier to your preferred development bundle ID.
4. Copy the files from `iphone/KodiXboxRemote/KodiXboxRemote/` into the Xcode app target.
5. Ensure `Resources/Info.plist` values are represented in the target Info settings, especially:
   - `NSLocalNetworkUsageDescription`
   - `NSBonjourServices` with `_kodi-xbox-remote._tcp`
6. Build and run on the iPhone.
7. Tap Start Listening.
8. Enter the displayed iPhone IP and port into the Xbox Kodi add-on settings:
   - Enable iPhone Remote Bridge: true
   - iPhone Bridge Host: displayed iPhone IP
   - iPhone Bridge Port: displayed port, default 9192
   - iPhone Bridge Token: same token as the app, or blank on both sides

## Notes

- The app must stay foregrounded for reliable listener behavior.
- iOS may prompt for Local Network permission on first run.
- If the add-on does not connect, confirm the iPhone and Xbox are on the same LAN and the iPhone has Local Network permission enabled in iOS Settings.
