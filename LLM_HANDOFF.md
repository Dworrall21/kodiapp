# LLM handoff: Kodi Xbox proxy robust version

This repository is a static Kodi add-on repository served from `gh-pages`.

Current public add-on entry of interest:

- `script.xbox.proxy` — Xbox Web Proxy service add-on.
- Latest reviewed package before this note: `script.xbox.proxy/script.xbox.proxy-1.0.3.zip`.

## Review findings

The following edits should be implemented before promoting the proxy as robust:

1. Keep add-on metadata consistent.
   - `addons.xml` advertises `script.xbox.proxy` as version `1.0.3` and includes a `script.module.six` dependency.
   - The packaged add-on should match repository metadata exactly.
   - Remove `script.module.six` if it is not imported by the service.

2. Make the WebSocket protocol explicit and versioned.
   - Current behavior appears to use a custom compression prefix for all payloads.
   - Safer protocol: text frames are plain JSON; binary frames use a one-byte prefix: `0x00` raw payload, `0x01` zlib payload.
   - The initial `connected` message should include `protocol_version`, `compression`, `addon_version`, and telemetry capabilities.

3. Preserve binary HTTP responses.
   - The proxy must not decode every HTTP body as UTF-8.
   - Use `body_encoding: utf-8` for text-like content types and `body_encoding: base64` for binary assets.
   - The remote web bridge must decode base64 before returning responses to the browser.

4. Add authentication.
   - The add-on should have an `auth_token` setting.
   - Include the token in the WebSocket handshake or, preferably, use HMAC challenge/response.
   - Do not allow an unauthenticated remote server to proxy Kodi web UI or run Kodi management commands.

5. Use Kodi Python JSON-RPC for management commands.
   - For Kodi control calls, prefer `xbmc.executeJSONRPC()`.
   - Keep HTTP proxying for web UI assets and browser-facing endpoints.

6. Validate all remote messages.
   - Require `id`, `type`, and expected fields.
   - Limit HTTP methods to `GET`, `POST`, `HEAD`, and `OPTIONS` unless more are intentionally supported.
   - Reject paths that do not start with `/` or include CR/LF characters.

7. Add frame and telemetry limits.
   - Cap WebSocket frame payloads, for example at 4 MiB.
   - Cap log tail requests to a maximum, for example 1000 lines.
   - Avoid recursive scanning of `special://home` for `kodi.log` on Xbox unless explicitly requested.

8. Add diagnostics on startup.
   - Send Kodi version/build/platform.
   - Test local HTTP JSON-RPC reachability at `127.0.0.1:<configured port>/jsonrpc`.
   - Include whether `xbmc.executeJSONRPC()` works.

## Suggested commit sequence

1. `docs: add proxy handoff notes`
2. `chore: unpack script.xbox.proxy source for reviewable changes`
3. `fix(proxy): add safe websocket framing and request validation`
4. `fix(proxy): preserve binary HTTP response bodies`
5. `security(proxy): require auth token for bridge connection`
6. `fix(proxy): route Kodi management commands through executeJSONRPC`
7. `chore(repo): regenerate addons.xml and checksum for 1.0.4`

## Testing checklist

- Install repository on Kodi Xbox.
- Install/update `script.xbox.proxy`.
- Confirm service connects to the bridge.
- Confirm `connected` event includes startup diagnostics.
- Load Kodi web UI through the remote bridge.
- Confirm static assets load: CSS, JS, images, fonts.
- Run read-only JSON-RPC command, such as `Application.GetProperties`.
- Request Kodi log tail and confirm the response is capped.
- Stop bridge server and confirm reconnect backoff does not spam logs.
- Test bad server messages and oversized frame rejection.

## Important caution

This proxy intentionally bypasses Xbox/UWP inbound port restrictions by creating an outbound connection. That makes authentication and strict message validation mandatory. Treat the remote bridge as a privileged management surface for the Kodi instance.
