# -*- coding: utf-8 -*-
"""Protocol helpers for the Option B2 iPhone Remote Bridge.

The bridge uses newline-delimited UTF-8 JSON over raw TCP.  This module is kept
free of Kodi/xbmc imports so it can be unit-tested outside Kodi.
"""
from __future__ import unicode_literals

import json

PROTOCOL = "iphone-bridge-v1"
MAX_LINE_BYTES = 256 * 1024


class BridgeProtocolError(ValueError):
    pass


def _validate_message(message):
    if not isinstance(message, dict):
        raise BridgeProtocolError("Bridge message must be a JSON object")
    msg_type = message.get("type")
    if not isinstance(msg_type, str) or not msg_type:
        raise BridgeProtocolError("Bridge message missing string type")
    return message


def encode_json_line(message):
    _validate_message(message)
    raw = json.dumps(message, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    if len(raw) > MAX_LINE_BYTES:
        raise BridgeProtocolError("Bridge message too large")
    return raw + b"\n"


def decode_json_line(line):
    if isinstance(line, str):
        line = line.encode("utf-8")
    line = line.rstrip(b"\r\n")
    if not line:
        raise BridgeProtocolError("Empty bridge message")
    if len(line) > MAX_LINE_BYTES:
        raise BridgeProtocolError("Bridge message too large")
    try:
        message = json.loads(line.decode("utf-8"))
    except Exception as exc:
        raise BridgeProtocolError("Invalid bridge JSON: %s" % exc)
    return _validate_message(message)


def extract_json_lines(buffer):
    messages = []
    while b"\n" in buffer:
        line, buffer = buffer.split(b"\n", 1)
        if not line.strip():
            continue
        messages.append(decode_json_line(line))
    if len(buffer) > MAX_LINE_BYTES:
        raise BridgeProtocolError("Bridge message too large")
    return messages, buffer


def make_hello_message(addon_id, addon_version, kodi_name, kodi_version, platform):
    return {
        "type": "hello",
        "protocol": PROTOCOL,
        "addon_id": addon_id,
        "addon_version": addon_version,
        "kodi_name": kodi_name,
        "kodi_version": kodi_version,
        "platform": platform,
    }


def make_auth_message(token):
    if not token:
        return None
    return {"type": "auth", "token": token}


def make_result_message(req_id, ok, result):
    message = {"type": "result", "id": req_id, "ok": bool(ok)}
    if ok:
        message["result"] = result
    else:
        message["error"] = result
    return message


def make_error_message(req_id, message, code=None):
    out = {"type": "error", "id": req_id, "message": str(message)}
    if code:
        out["code"] = code
    return out
