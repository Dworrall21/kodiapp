"""Compression helpers for WebSocket and HTTP transport."""

import gzip
import zlib

from .config import COMPRESSION_ENABLED, COMPRESSION_LEVEL, COMPRESSION_MIN_SIZE


def ws_compress(data: bytes) -> bytes:
    """Compress bytes for WebSocket transport. Returns bytes with 1-byte flag prefix."""
    if not COMPRESSION_ENABLED or len(data) < COMPRESSION_MIN_SIZE:
        return b"\x00" + data
    compressed = zlib.compress(data, COMPRESSION_LEVEL)
    if len(compressed) < len(data):
        return b"\x01" + compressed
    return b"\x00" + data


def ws_decompress(data: bytes) -> bytes:
    """Decompress bytes from WebSocket transport. First byte is compression flag."""
    if not data:
        return data
    flag = data[0:1]
    payload = data[1:]
    if flag == b"\x01":
        try:
            return zlib.decompress(payload)
        except zlib.error:
            return payload
    return payload


def gzip_compress(data: bytes) -> tuple:
    """Compress bytes with gzip for HTTP responses. Returns (data, was_compressed)."""
    if not COMPRESSION_ENABLED or len(data) < COMPRESSION_MIN_SIZE:
        return data, False
    compressed = gzip.compress(data, compresslevel=COMPRESSION_LEVEL)
    if len(compressed) < len(data):
        return compressed, True
    return data, False
