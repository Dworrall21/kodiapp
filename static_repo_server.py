#!/usr/bin/env python3
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
import os, sys, time
ROOT = Path(__file__).resolve().parent / "repo_static"
LOG = Path(__file__).resolve().parent / "static_repo_access.log"
class Handler(SimpleHTTPRequestHandler):
    # Kodi on Xbox has been flaky with Python's persistent HTTP/1.1
    # connections when installing add-on zips from a local source.  The
    # official Kodi mirrors respond with `Connection: close` and
    # `Accept-Ranges: bytes`, so mimic that conservative shape.
    protocol_version = "HTTP/1.0"
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)
    def log_message(self, fmt, *args):
        line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {self.client_address[0]} {self.command} {self.path} - {fmt % args}\n"
        with LOG.open('a', encoding='utf-8') as f:
            f.write(line)
        sys.stderr.write(line)
    def end_headers(self):
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Connection", "close")
        super().end_headers()
if __name__ == "__main__":
    print("Static Kodi repo server on http://0.0.0.0:8081/", flush=True)
    ThreadingHTTPServer(("0.0.0.0", 8081), Handler).serve_forever()
