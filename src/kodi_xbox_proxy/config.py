"""Configuration for Kodi Xbox Proxy Server."""

import os

# --- Network ---
HTTP_HOST = "0.0.0.0"
HTTP_PORT = 8080
WS_PORT = 9191

# --- Compression ---
COMPRESSION_ENABLED = True
COMPRESSION_LEVEL = 6
COMPRESSION_MIN_SIZE = 64

# --- Paths ---
PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_STATIC_DIR = os.path.join(PROJECT_DIR, "..", "..", "repo_static")

# --- Timeouts ---
ADDON_REQUEST_TIMEOUT = 15  # seconds waiting for add-on response
WS_SEND_TIMEOUT = 5         # seconds waiting for WS send to complete
SSE_KEEPALIVE = 30          # seconds between SSE keepalive pings
