"""WebSocket server for Xbox add-on connections."""

import asyncio
import json

import websockets

from .compression import ws_compress, ws_decompress
from .state import addon_info, addon_lock, addon_ws, broadcast_event

ws_loop = None


async def ws_send_compressed(websocket, data_dict: dict) -> None:
    """Send a JSON dict through the WebSocket with compression."""
    raw = json.dumps(data_dict).encode("utf-8")
    compressed = ws_compress(raw)
    if compressed[:1] == b"\x01":
        await websocket.send(compressed[1:])
    else:
        await websocket.send(raw.decode("utf-8", errors="replace"))


async def addon_handler(websocket) -> None:
    """Handle the Xbox add-on WebSocket connection."""
    global addon_ws, addon_info
    addon_ws = websocket
    print("[proxy] Kodi add-on connected")

    try:
        async for message in websocket:
            try:
                if isinstance(message, bytes):
                    message = ws_decompress(message)
                    if isinstance(message, bytes):
                        message = message.decode("utf-8", errors="replace")
                data = json.loads(message)
            except (json.JSONDecodeError, UnicodeDecodeError):
                continue

            msg_type = data.get("type")

            if msg_type == "response":
                req_id = data.get("id")
                if req_id in pending:
                    pending[req_id]["response"] = data
                    pending[req_id]["event"].set()

            elif msg_type == "connected":
                addon_info = data.get("info")
                ver = addon_info.get("version", "?") if addon_info else "?"
                print(f"[proxy] Add-on ready — Kodi {ver}")

            elif msg_type == "event":
                event_type = data.get("event", "unknown")
                event_data = data.get("data", {})
                broadcast_event(event_type, event_data)

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
