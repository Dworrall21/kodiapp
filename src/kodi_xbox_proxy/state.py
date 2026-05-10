"""Shared state for the proxy server."""

import threading
import time

# Pending requests awaiting add-on responses: {request_id: {"event": Event, "response": dict}}
pending = {}

# WebSocket connection to the Xbox add-on
addon_ws = None
addon_lock = threading.Lock()
addon_info = None

# SSE clients: list of (queue, event) tuples for real-time event delivery
sse_clients = []
sse_lock = threading.Lock()

# Latest telemetry cache
latest_stats = None
latest_event_log = []
MAX_EVENTS = 100


def broadcast_event(event_type: str, data: dict) -> None:
    """Push a real-time event to all SSE clients and cache it."""
    global latest_stats, latest_event_log

    event = {
        "type": event_type,
        "data": data,
        "timestamp": time.time(),
    }

    if event_type == "stats_update":
        latest_stats = event

    latest_event_log.append(event)
    if len(latest_event_log) > MAX_EVENTS:
        latest_event_log = latest_event_log[-MAX_EVENTS:]

    with sse_lock:
        dead = []
        for i, (queue, ready_event) in enumerate(sse_clients):
            try:
                queue.append(event)
                ready_event.set()
            except Exception:
                dead.append(i)
        for i in reversed(dead):
            sse_clients.pop(i)
