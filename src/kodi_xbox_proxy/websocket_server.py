"""WebSocket server for Xbox add-on connections."""

import json

import websockets

from .compression import ws_compress, ws_decompress
from . import state


async def ws_send_compressed(websocket, data_dict: dict) -> None:
    """Send a JSON dict through the WebSocket using protocol-v2 framing.

    Text frames are plain JSON. Binary frames retain the one-byte envelope:
    0x00 raw JSON bytes, 0x01 zlib-compressed JSON bytes.
    """
    raw = json.dumps(data_dict, separators=(",", ":"), default=str).encode("utf-8")
    framed = ws_compress(raw)
    if framed[:1] == b"\x01":
        await websocket.send(framed)
    else:
        await websocket.send(raw.decode("utf-8", errors="replace"))


def _decode_message(message):
    if isinstance(message, bytes):
        decoded = ws_decompress(message)
        if isinstance(decoded, bytes):
            return decoded.decode("utf-8", errors="replace")
        return decoded
    return message


def _complete_pending(req_id, response):
    if req_id in state.pending:
        state.pending[req_id]["response"] = response
        state.pending[req_id]["event"].set()


async def addon_handler(websocket) -> None:
    """Handle the Xbox add-on WebSocket connection."""
    with state.addon_lock:
        state.addon_ws = websocket
        state.addon_info = None
    print("[proxy] Kodi add-on connected")
    state.broadcast_event("addon_connected", {})

    try:
        async for message in websocket:
            try:
                data = json.loads(_decode_message(message))
            except (json.JSONDecodeError, UnicodeDecodeError, TypeError) as exc:
                print(f"[proxy] Ignoring malformed add-on message: {exc}")
                continue

            msg_type = data.get("type")

            if msg_type == "response":
                _complete_pending(data.get("id"), data)

            elif msg_type == "connected":
                with state.addon_lock:
                    state.addon_info = data.get("info") or {}
                info = state.addon_info or {}
                kodi_ver = info.get("version") or "?"
                addon_ver = info.get("addon_version") or "?"
                platform = info.get("name") or info.get("platform") or "?"
                print(f"[proxy] Add-on ready — addon v{addon_ver}, Kodi {kodi_ver} ({platform})")
                state.broadcast_event("addon_ready", info)

            elif msg_type == "telemetry":
                state.broadcast_event("telemetry", data.get("info") or data)
                # Some UI code expects stats_update.
                state.broadcast_event("stats_update", {"stats": data.get("info") or data})

            elif msg_type == "event":
                event_type = data.get("event") or data.get("event_type") or "unknown"
                print(f"[proxy] Add-on event: {event_type}")
                state.broadcast_event(event_type, data.get("data", {}))

            elif msg_type == "logs_result":
                _complete_pending(data.get("id"), {
                    "status": data.get("status", 200),
                    "body": data.get("body", {}),
                })

            elif msg_type == "info":
                _complete_pending(data.get("id"), {
                    "status": 200,
                    "body": data.get("data", {}),
                })

            elif msg_type == "command_result":
                _complete_pending(data.get("id"), {
                    "status": data.get("status", 200),
                    "body": data.get("body", {}),
                })

            elif msg_type == "error":
                _complete_pending(data.get("id"), {
                    "status": data.get("status", 500),
                    "body": {"error": data.get("error", "Unknown add-on error")},
                })
                state.broadcast_event("addon_error", data)

            else:
                print(f"[proxy] Unhandled add-on message type: {msg_type}")
                state.broadcast_event("addon_message", data)

    except websockets.exceptions.ConnectionClosed:
        pass
    finally:
        with state.addon_lock:
            if state.addon_ws is websocket:
                state.addon_ws = None
                state.addon_info = None
        state.broadcast_event("addon_disconnected", {})
        print("[proxy] Add-on disconnected")
