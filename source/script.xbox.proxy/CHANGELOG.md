# Changelog

## 1.0.4 - Robust proxy source candidate

This version is added as unpacked source under `source/script.xbox.proxy/` so future agents can inspect and modify it safely before packaging.

### Added

- Protocol v2 documentation.
- Required shared auth token before connecting to the bridge.
- Outbound WebSocket handshake headers for protocol and add-on version.
- Binary WebSocket frame envelope:
  - `0x00` raw JSON bytes.
  - `0x01` zlib-compressed JSON bytes.
- 4 MiB maximum WebSocket frame size.
- 4 MiB maximum proxied request body size.
- Binary-safe HTTP proxy responses using `body_encoding`:
  - `utf-8` for text-like content.
  - `base64` for binary content.
- Message validation for proxied HTTP requests.
- Kodi management JSON-RPC through `xbmc.executeJSONRPC()`.
- Startup diagnostics for local HTTP JSON-RPC and Python JSON-RPC.
- Capped log tailing with known-path lookup instead of broad recursive scans.
- Reconnect backoff with jitter.
- Reproducible build script at `source/build_addon.py`.

### Changed

- Removed the unused `script.module.six` dependency from the source candidate metadata.
- Normalized provider name to `Dworrall21`.
- Split reviewable source from generated installable packages.

### Bridge compatibility impact

The bridge server must understand protocol v2:

- Authenticate the add-on with the `Authorization: Bearer <token>` header.
- Accept plain JSON text frames.
- Decode binary frames using the v2 one-byte envelope.
- Decode HTTP responses where `body_encoding` is `base64`.
- Send management calls as `type: jsonrpc` or `type: kodi_command`.

### Not yet done

- The installable `script.xbox.proxy-1.0.4.zip` has not been committed here.
- `addons.xml` and `addons.xml.md5` have not been regenerated in this commit set.
- Run `python3 source/build_addon.py` from a real checkout to generate those artifacts.
- Test on Kodi Xbox before promoting 1.0.4 in the repository index.
