# -*- coding: utf-8 -*-
"""
indexers: unified torrent stream search across multiple providers.

Queries Torrentio first (primary), then falls back to Comet (Stremio
protocol), then BitMagnet (self-hosted DHT HTTP API). Returns parsed
streams in a consistent format suitable for the debrid layer and menus.

Each indexer's base URL is configurable via addon settings. If the
primary returns no streams, the next provider in the chain is tried.
"""

import json
import re
import time
import hashlib
import urllib.parse
import urllib.request
import urllib.error
import socket

from .utils import get_setting, log, cache_get, cache_set
from . import torrentio as torr

import xbmc

# --- Provider descriptors (in priority order) ---
PROVIDERS = [
    ("torrentio",  "indexers.torrentio_url",  "https://torrentio.strem.fun", "stremio"),
    ("comet",      "indexers.comet_url",      "https://comet.strem.fun",     "stremio"),
    ("bitmagnet",  "indexers.bitmagnet_url",  "",                            "bitmagnet"),
]

# Retry-able HTTP status codes
_RETRY_HTTP = (502, 503, 504, 429)

# --- Regex helpers for Comet & BitMagnet parsing (same format as torrentio) ---
_RE_SEEDERS = re.compile(r"[👤]\s*(\d+)", re.UNICODE)
_RE_SIZE    = re.compile(r"[💾]\s*([\d.,]+)\s*(GB|GiB|MB|MiB|G|M)", re.IGNORECASE | re.UNICODE)

_QUALITY_TAGS = [
    (re.compile(r"\b4k\b", re.I),             "2160p"),
    (re.compile(r"\b2160p\b", re.I),          "2160p"),
    (re.compile(r"\buhd\b", re.I),            "2160p"),
    (re.compile(r"\b1080p\b", re.I),          "1080p"),
    (re.compile(r"\b720p\b", re.I),           "720p"),
    (re.compile(r"\b480p\b", re.I),           "480p"),
    (re.compile(r"\b360p\b", re.I),           "360p"),
]


# --- HTTP helper ---
def _http_get(url, timeout=10, retries=1):
    """GET a URL, return parsed JSON or None."""
    attempt = 0
    last_exc = None
    while attempt <= retries:
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": "Helix/0.1 (+https://github.com/Dworrall21/helix-addon)",
                "Accept": "application/json",
            })
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
                if not raw:
                    return None
                return json.loads(raw)
        except urllib.error.HTTPError as exc:
            last_exc = exc
            if exc.code in _RETRY_HTTP and attempt < retries:
                attempt += 1
                xbmc.sleep(500)
                continue
            log("indexers.http %d %s" % (exc.code, url), "warn")
            return None
        except (urllib.error.URLError, socket.timeout, ConnectionError) as exc:
            last_exc = exc
            if attempt < retries:
                attempt += 1
                xbmc.sleep(500)
                continue
            log("indexers.http %r" % exc, "warn")
            return None
    log("indexers.http giving up: %r" % last_exc, "warn")
    return None


# --- Cache helpers ---
def _clear_internal_cache():
    """Clear indexer-level caches (does NOT touch torrentio's cache)."""
    # No persistent in-memory cache in this module; torrentio has its own.
    pass


def _cache_key(provider, media_type, media_id):
    raw = "%s|%s|%s" % (provider, media_type, media_id)
    return "ix:" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:20]


# --- Comet Stremio protocol query ---
def _query_comet(base_url, media_type, media_id, timeout=10):
    """Query Comet (Stremio protocol) and return parsed streams.

    Returns list of dicts compatible with torrentio.parse_streams() format.
    """
    base = base_url.rstrip("/")
    url = "%s/stream/%s/%s.json" % (base, media_type, media_id)
    log("indexers: query comet %s" % url, "debug")
    data = _http_get(url, timeout=timeout)
    if not data or not isinstance(data, dict):
        return []
    raw_streams = data.get("streams")
    if not raw_streams or not isinstance(raw_streams, list):
        return []
    return _parse_streams_from(raw_streams, "comet")


# --- BitMagnet HTTP API query ---
def _query_bitmagnet(base_url, query, timeout=10):
    """Query BitMagnet DHT indexer REST API.

    BitMagnet v0.3+: GET /api/v1/torrents/search?query=...&limit=20

    Returns list of stream dicts in torrentio-compatible format.
    """
    base = base_url.rstrip("/")
    params = urllib.parse.urlencode({"query": query, "limit": 20})
    url = "%s/api/v1/torrents/search?%s" % (base, params)
    log("indexers: query bitmagnet %s" % url, "debug")
    data = _http_get(url, timeout=timeout)
    if not data:
        return []

    # BitMagnet returns paginated results in various shapes
    results = []
    if isinstance(data, list):
        results = data
    elif isinstance(data, dict):
        results = data.get("results") or data.get("torrents") or []

    # Normalise to torrentio-style stream dicts
    out = []
    for r in results:
        info_hash = r.get("info_hash") or r.get("infohash") or ""
        if not info_hash:
            continue
        name = r.get("name") or r.get("title") or "BitMagnet"
        size_bytes = r.get("size", 0) or 0
        seeders = r.get("seeders", 0) or r.get("seed_count", 0)

        # Build a torrentio-style title line for compatibility
        size_label = ""
        if size_bytes:
            size_mb = size_bytes / (1024 * 1024)
            if size_mb >= 1024:
                size_label = "💾 %.2f GB" % (size_mb / 1024)
            else:
                size_label = "💾 %d MB" % int(size_mb)

        title = name
        if seeders:
            title += " 👤 %d" % seeders
        if size_label:
            title += " " + size_label

        out.append({
            "infoHash": info_hash,
            "name": name,
            "title": title,
            "quality": _detect_quality(name, title),
            "size": int(size_bytes / (1024 * 1024)) if size_bytes else 0,
            "seeders": seeders,
            "magnet": _build_magnet(info_hash, name),
            "fileIdx": r.get("file_index", 0) if "file_index" in r else 0,
            "language": "en",
            "provider": "bitmagnet",
        })

    # Sort by quality (highest first) then seeders
    quality_order = {"2160p": 4, "1080p": 3, "720p": 2, "480p": 1, "unknown": 0}
    out.sort(key=lambda x: (quality_order.get(x["quality"], 0), x["seeders"]),
             reverse=True)
    return out


# --- Shared parsing helpers ---
def _parse_streams_from(raw_streams, provider_label):
    """Parse a list of raw Stremio-style stream dicts from a generic provider."""
    out = []
    for entry in raw_streams:
        try:
            info_hash = entry.get("infoHash", "")
            if not info_hash:
                continue
            name_raw = entry.get("name", "")
            title_raw = entry.get("title", "")
            title_lines = title_raw.split("\n")
            clean_name = title_lines[0].strip() if title_lines else name_raw.strip()
            if not clean_name:
                clean_name = provider_label.capitalize()

            quality = _detect_quality(name_raw, title_raw)
            size_mb = _parse_size(title_raw)
            seeders = _parse_seeders(title_raw)
            magnet = _build_magnet(info_hash, clean_name)

            out.append({
                "infoHash": info_hash,
                "name": clean_name,
                "title": title_raw.strip(),
                "quality": quality,
                "size": size_mb,
                "seeders": seeders,
                "magnet": magnet,
                "fileIdx": entry.get("fileIdx"),
                "language": "en",
                "provider": provider_label,
            })
        except Exception as exc:
            log("indexers parse_streams [%s]: %r" % (provider_label, exc), "warn")
            continue

    quality_order = {"2160p": 4, "1080p": 3, "720p": 2, "480p": 1, "unknown": 0}
    out.sort(key=lambda x: (quality_order.get(x["quality"], 0), x["seeders"]),
             reverse=True)
    return out


def _detect_quality(name, title):
    combined = (name or "") + " " + (title or "")
    for pattern, label in _QUALITY_TAGS:
        if pattern.search(combined):
            return label
    return "unknown"


def _parse_size(s):
    if not s:
        return 0
    m = _RE_SIZE.search(s)
    if not m:
        return 0
    num = float(m.group(1).replace(",", "."))
    unit = m.group(2).upper()
    if unit.startswith("G"):
        return int(num * 1024)
    return int(num)


def _parse_seeders(s):
    if not s:
        return 0
    m = _RE_SEEDERS.search(s)
    if m:
        try:
            return int(m.group(1))
        except ValueError:
            return 0
    return 0


def _build_magnet(info_hash, display_name):
    name_enc = urllib.parse.quote(display_name or "video")
    return "magnet:?xt=urn:btih:%s&dn=%s" % (info_hash, name_enc)


def _tmdb_to_imdb(tmdb_id, media_type):
    """Resolve a TMDB ID to an IMDB ID via the TMDB /find endpoint.

    Returns IMDB ID string (e.g. "tt1375666") or None.
    """
    if not tmdb_id:
        return None
    try:
        from . import tmdb as tmdb_mod
        endpoint = f"/{('movie' if media_type == 'movie' else 'tv')}/{tmdb_id}/external_ids"
        data = tmdb_mod._get(endpoint, {}, ttl=86400)
        if data:
            imdb = data.get("imdb_id")
            if imdb and imdb.startswith("tt"):
                return imdb
    except Exception as exc:
        log("indexers: tmdb_to_imdb failed: %r" % exc, "warn")
    return None


# --- Public API ---

def fetch_streams(tmdb_id, media_type, season=None, episode=None):
    """Fetch torrent streams from all indexers, cascading on empty results.

    ``tmdb_id``: integer or string TMDB ID
    ``media_type``: "movie" or "series" / "tv"
    ``season`` / ``episode``: optional TV episode coordinates for episode-specific lookup.

    Returns list of stream dicts:
        { infoHash, name, quality, size, seeders, magnet, fileIdx,
          language, provider }

    Empty list if no results from any indexer.
    """
    # Normalise media_type
    mtype = "movie" if media_type in ("movie", "movies") else "series"

    # Resolve IMDB ID if possible
    imdb_id = _tmdb_to_imdb(tmdb_id, media_type)
    tid_str = str(tmdb_id)

    streams = []

    # 1. Try Torrentio (primary) via existing torrentio module
    log("indexers: trying Torrentio (tmdb=%s media=%s imdb=%s season=%s episode=%s)" % (tid_str, mtype, imdb_id or "?", season or "?", episode or "?"), "debug")
    if imdb_id:
        if mtype == "movie":
            streams = torr.fetch_movie_streams(imdb_id)
        elif season is not None and episode is not None:
            streams = torr.fetch_episode_streams(imdb_id, season, episode)
        else:
            # For generic series search, Torrentio needs specific season/episode.
            # Fall through to direct providers below.
            streams = []

    # Torrentio doesn't have a generic series handler that returns ALL episodes;
    # the menus layer handles per-episode. For the "find streams" use-case
    # (discover/search results), we just try the Stremio protocol directly
    # which handles series as "series/{imdb_id}:1:1" at minimum.

    if streams:
        log("indexers: Torrentio returned %d streams" % len(streams), "info")
        return streams

    # 2. Fallback: try Torrentio via direct Stremio protocol
    torr_url = (get_setting("indexers.torrentio_url") or "https://torrentio.strem.fun").rstrip("/")
    stremio_id = imdb_id or ("tmdb:%s" % tid_str)
    if torr_url and stremio_id:
        ck = _cache_key("torrentio_direct", mtype, stremio_id)
        cached = cache_get(ck, ttl_seconds=1800)
        if cached is not None:
            if cached:
                return cached
        else:
            data = _http_get("%s/stream/%s/%s.json" % (torr_url, mtype, stremio_id))
            if data and isinstance(data, dict):
                raw = data.get("streams") or []
                streams = _parse_streams_from(raw, "torrentio")
                cache_set(ck, streams)
                if streams:
                    log("indexers: Torrentio (direct) returned %d streams" % len(streams), "info")
                    return streams
            cache_set(ck, [])  # cache empty so we don't hammer it

    # 3. Try Comet (first fallback)
    comet_url = (get_setting("indexers.comet_url") or "https://comet.strem.fun").strip()
    if comet_url and stremio_id:
        ck = _cache_key("comet", mtype, stremio_id)
        cached = cache_get(ck, ttl_seconds=1800)
        if cached is not None:
            if cached:
                return cached
        else:
            streams = _query_comet(comet_url, mtype, stremio_id)
            cache_set(ck, streams)
            if streams:
                log("indexers: Comet returned %d streams" % len(streams), "info")
                return streams

    # 4. Try BitMagnet (second fallback)
    bm_url = (get_setting("indexers.bitmagnet_url") or "").strip()
    if bm_url:
        bm_query = tmdb_id or imdb_id or ""
        if bm_query:
            ck = _cache_key("bitmagnet", mtype, str(bm_query))
            cached = cache_get(ck, ttl_seconds=1800)
            if cached is not None:
                if cached:
                    return cached
            else:
                streams = _query_bitmagnet(bm_url, str(bm_query))
                cache_set(ck, streams)
                if streams:
                    log("indexers: BitMagnet returned %d streams" % len(streams), "info")
                    return streams

    log("indexers: no streams found from any provider", "info")
    return []


def check_stream_cache(streams):
    """Check each stream's infoHash against the active debrid provider's cache.

    Returns:
        dict: { "streams": [stream+{cached: bool}], "cached_count": N, "total_count": N }
    """
    out = []
    cached = 0

    # For now, mark all streams as "unknown cache status" since the debrid
    # cache-check API is provider-specific and typically async.
    # In a future iteration this can call Real-Debrid /torrents/instantAvailability
    # or AllDebrid /magnet/status to determine if a hash is cached.
    for s in (streams or []):
        s["cached"] = None  # unknown
        out.append(s)

    return {
        "streams": out,
        "cached_count": cached,
        "total_count": len(out),
    }


def render_stream(stream):
    """Build a human-readable label for a stream dict.

    Matches the format used by Torrentio: quality, size, seeders, provider.
    """
    q = stream.get("quality", "?")
    sz = stream.get("size", 0)
    sz_label = ""
    if sz >= 1024:
        sz_label = "%.2f GB" % (sz / 1024.0)
    elif sz > 0:
        sz_label = "%d MB" % sz

    se = stream.get("seeders", 0)
    prov = stream.get("provider", "?")
    name = stream.get("name", "Stream")
    cached = stream.get("cached")

    parts = []
    if q:
        parts.append("[%s]" % q.upper())
    if sz_label:
        parts.append(sz_label)
    if se > 0:
        parts.append("S:%d" % se)
    parts.append("\n" + name)
    parts.append("[%s]" % prov)

    label = " ".join(parts)
    if cached is True:
        label = "✔ " + label
    elif cached is False:
        label = "⏳ " + label

    return label


def active_indexer_names():
    """Return list of configured indexer labels."""
    names = []
    for name, setting_key, default_url, protocol in PROVIDERS:
        url = (get_setting(setting_key) or "").strip()
        if name == "torrentio" and (url or default_url):
            names.append("Torrentio")
        elif name == "comet" and (url or default_url):
            names.append("Comet")
        elif name == "bitmagnet" and url:
            names.append("BitMagnet")
    return names


def test_indexers():
    """Test connectivity for each configured indexer.

    Returns list of (name, ok, detail) tuples and shows a notification.
    """
    from .utils import notify

    results = []
    test_id = "tt0111161"  # The Shawshank Redemption
    test_type = "movie"

    for name, setting_key, default_url, protocol in PROVIDERS:
        url = (get_setting(setting_key) or "").strip()
        base_url = url or default_url
        if not base_url and name == "bitmagnet":
            results.append(("BitMagnet", False, "not configured"))
            continue
        if not base_url:
            results.append((name.capitalize(), False, "not configured"))
            continue
        try:
            if name == "torrentio":
                streams = torr.fetch_movie_streams(test_id)
                ok = len(streams) > 0
                detail = "%d streams" % len(streams) if ok else "no streams"
            elif protocol == "stremio":
                streams = _query_comet(base_url, test_type, test_id, timeout=5)
                ok = len(streams) > 0
                detail = "%d streams" % len(streams) if ok else "no streams"
            elif protocol == "bitmagnet":
                streams = _query_bitmagnet(base_url, "The Shawshank Redemption", timeout=5)
                ok = len(streams) > 0
                detail = "%d results" % len(streams) if ok else "no results"
            else:
                ok = False
                detail = "unknown protocol"
            results.append((name.capitalize(), ok, detail))
        except Exception as exc:
            results.append((name.capitalize(), False, str(exc)))

    passed = sum(1 for _, ok, _ in results if ok)
    total = len(results)
    lines = ["Indexer test results:"]
    for name, ok, detail in results:
        status = "OK" if ok else "FAIL"
        lines.append("  %s: %s — %s" % (name, status, detail))
    log("indexers: " + " | ".join(lines), "info")
    notify("Helix — Indexers", "%d/%d passed" % (passed, total), "info" if passed > 0 else "warn", 5000)
    return results


def indexer_status():
    """Return a human-readable string of indexer configuration status."""
    from .utils import notify
    lines = ["Indexer Status:"]
    for name, setting_key, default_url, protocol in PROVIDERS:
        url = (get_setting(setting_key) or "").strip()
        base_url = url or default_url
        if not base_url:
            lines.append("  %s: disabled (no URL)" % name.capitalize())
        else:
            lines.append("  %s: configured (%s)" % (name.capitalize(), base_url))
    return lines
