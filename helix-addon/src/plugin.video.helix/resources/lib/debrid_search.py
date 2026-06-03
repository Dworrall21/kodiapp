# -*- coding: utf-8 -*-
"""
debrid_search: orchestrate indexer search + debrid cache check.

This module is the bridge menus.py calls directly. It:
  1. Searches indexers (Torrentio, Comet, BitMagnet) for torrents by TMDB ID.
  2. Checks each info_hash against the active debrid provider's cache.
  3. Groups results by quality tier (2160p, 1080p, 720p, 480p, unknown).
  4. Returns structured dict for _render_quality_header + _render_debrid_stream.

The heavy lifting is split:
  - indexers.search() handles multi-provider search with fallbacks.
  - debrid.check_cache() handles the provider-specific cache-check API calls.
"""

from .utils import log, cache_get, cache_set
from . import debrid
from . import indexers

_CACHE_PREFIX = "debrid_search:"
_CACHE_TTL = 600  # 10 minutes


def _stream_to_display(s):
    """Convert an indexers stream dict into the format menus.py expects.

    Indexers stream format (from indexers.search / torrentio):
        {
            "infoHash": str,
            "name": str,
            "quality": str,    # 2160p / 1080p / 720p / unknown
            "size": int,       # MB
            "seeders": int,
            "magnet": str,
            "fileIdx": int or None,
            "provider": "torrentio",
        }

    menus.py format for _render_debrid_stream:
        {
            "name": str,
            "source": str,
            "size_mb": int,
            "cached": bool,
            "infoHash": str,
            "url": str,        # magnet link
            "_quality": str,
        }
    """
    return {
        "name": s.get("name", ""),
        "source": s.get("provider", "?").capitalize(),
        "size_mb": s.get("size", 0),
        "cached": False,  # filled after cache check
        "infoHash": s.get("infoHash", ""),
        "url": s.get("magnet", ""),
        "_quality": s.get("quality", "unknown"),
    }


def search_by_tmdb(media_type, tmdb_id, season=None, episode=None):
    """Search for debrid-cached streams by TMDB ID, grouped by quality.

    Args:
        media_type: "movie" or "tv"
        tmdb_id: numeric TMDB ID (str or int)
        season / episode: optional episode coordinates for TV detail flows.

    Returns:
        dict mapping quality tier -> list of stream dicts.
        Returns empty dict if no results or indexer unavailable.
    """
    tid = str(tmdb_id).strip()

    # Check cache first
    cache_key = _CACHE_PREFIX + "%s:%s:%s:%s" % (media_type, tid, season or "", episode or "")
    cached = cache_get(cache_key, ttl_seconds=_CACHE_TTL)
    if cached is not None and isinstance(cached, dict):
        log("debrid_search: cache hit %s/%s s=%s e=%s" % (media_type, tid, season or "?", episode or "?"))
        return cached

    # 1. Search indexers for streams
    streams = indexers.fetch_streams(tid, media_type, season=season, episode=episode)
    if not streams:
        log("debrid_search: no streams from indexers for %s/%s" % (media_type, tid))
        return {}

    # 2. Check debrid cache for all unique hashes
    unique_hashes = list({s.get("infoHash", "") for s in streams if s.get("infoHash")})
    cache_map = debrid.check_cache(unique_hashes) if unique_hashes else {}
    log("debrid_search: checked %d hashes, %d cached" % (
        len(unique_hashes), sum(1 for v in cache_map.values() if v)
    ))

    # 3. Convert to display format and group by quality
    grouped = {}
    for s in streams:
        d = _stream_to_display(s)
        ih = d.get("infoHash", "").lower()
        if ih:
            d["cached"] = cache_map.get(ih, False)
        quality = d.get("_quality", "unknown")
        grouped.setdefault(quality, []).append(d)

    # Sort within each tier: cached first, then by size (desc)
    for tier in grouped:
        grouped[tier].sort(key=lambda x: (not x.get("cached"), -(x.get("size_mb") or 0)))

    # Cache the result
    cache_set(cache_key, grouped)
    total = sum(len(v) for v in grouped.values())
    log("debrid_search: %d streams in %d tiers for %s/%s" % (
        total, len(grouped), media_type, tid
    ))
    return grouped


def search_by_query(query, media_type="movie"):
    """Future: direct text search via indexers."""
    return {}


def check_cache_for_streams(streams):
    """Convenience: check debrid cache for a list of stream dicts.

    Adds/updates 'cached' key on each stream dict in-place and returns
    a dict with cached_count, total_count, and the streams list.
    """
    if not streams:
        return {"streams": [], "cached_count": 0, "total_count": 0}
    hashes = list({s.get("infoHash", "") for s in streams if s.get("infoHash")})
    cache_map = debrid.check_cache(hashes) if hashes else {}
    cached_count = 0
    for s in streams:
        ih = (s.get("infoHash") or "").lower()
        s["cached"] = cache_map.get(ih, False)
        if s["cached"]:
            cached_count += 1
    return {"streams": streams, "cached_count": cached_count, "total_count": len(streams)}
