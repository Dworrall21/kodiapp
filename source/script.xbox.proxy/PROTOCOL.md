# Xbox Web Proxy protocol v2

This document describes the expected bridge protocol for `script.xbox.proxy` version `1.0.4` and later.

## Connection

The Kodi add-on is the WebSocket client. The bridge is the WebSocket server.

The add-on sends these handshake headers:

- `X-Kodi-Proxy-Protocol: 2`
- `X-Kodi-Proxy-Addon: script.xbox.proxy/<version>`
- `Authorization: Bearer <auth_token>` when an auth token is configured

The add-on refuses to connect when `auth_token` is blank.

## Frame encoding

Text frames are plain UTF-8 JSON.

Binary frames use a one-byte envelope:

- `0x00` = raw UTF-8 JSON bytes
- `0x01` = zlib-compressed UTF-8 JSON bytes

Any other binary prefix is a protocol error.

The add-on rejects frames larger than 4 MiB.

## Initial message from add-on

```json
{
  "type": "connected",
  "info": {
    "addon_id": "script.xbox.proxy",
    "addon_version": "1.0.4",
    "protocol_version": 2,
    "local_http": {"ok": true, "status": 200},
    "execute_jsonrpc": {"ok": true},
    "capabilities": {
      "http_proxy": true,
      "management_rpc": true,
      "log_tail": true,
      "binary_http_bodies": true,
      "auth_token_present": true
    }
  }
}
```

## HTTP proxy request from bridge

```json
{
  "type": "http_request",
  "id": "req-1",
  "method": "GET",
  "path": "/",
  "headers": {}
}
```

Allowed methods: `GET`, `POST`, `HEAD`, `OPTIONS`.

The path must start with `/` and must not contain CR/LF characters.

## HTTP proxy response from add-on

Text body:

```json
{
  "type": "response",
  "id": "req-1",
  "status": 200,
  "headers": {"Content-Type": "text/html"},
  "body_encoding": "utf-8",
  "body": "<html>...</html>"
}
```

Binary body:

```json
{
  "type": "response",
  "id": "req-2",
  "status": 200,
  "headers": {"Content-Type": "image/png"},
  "body_encoding": "base64",
  "body": "iVBORw0KGgo..."
}
```

The bridge must decode `base64` before sending the response to the browser.

## Kodi management JSON-RPC request

```json
{
  "type": "jsonrpc",
  "id": "rpc-1",
  "method": "Application.GetProperties",
  "params": {"properties": ["name", "version"]}
}
```

The add-on routes these calls through `xbmc.executeJSONRPC()` instead of HTTP.

## Log tail request

```json
{
  "type": "get_logs",
  "id": "logs-1",
  "lines": 200
}
```

The add-on caps log output at 1000 lines.

## Telemetry

The add-on periodically sends:

```json
{
  "type": "telemetry",
  "time": 1770000000,
  "info": {
    "build_version": "...",
    "free_memory": "...",
    "cpu_usage": "...",
    "screen_resolution": "..."
  }
}
```

## Security notes

The bridge is a privileged Kodi management surface. Do not expose it without authentication. Prefer TLS when the bridge is not on a trusted local network.
