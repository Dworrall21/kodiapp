from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

from resources.lib import utils
from resources.lib import torrentio
from resources.lib import trakt


def test_url_helpers_and_title_cleanup(kodi_env):
    assert utils.parse_query("action=home&tmdb_id=42&multi=a&multi=b&empty=") == {
        "action": "home",
        "tmdb_id": "42",
        "multi": ["a", "b"],
        "empty": "",
    }

    url = utils.url_for("movies", tmdb_id=42, page=2)
    assert url == "plugin://plugin.video.helix/?action=movies&tmdb_id=42&page=2"

    assert utils.clean_title("The.Show.(2024)[1080p].mkv") == "The Show  mkv"
    assert utils.clean_title(None) == ""

    sid = utils.short_id("alpha", 99, length=12)
    assert len(sid) == 12
    assert sid == utils.short_id("alpha", 99, length=12)


def test_cache_round_trip_and_expiry(kodi_env, tmp_path, monkeypatch):
    base = tmp_path / "helix-profile"
    base.mkdir()
    monkeypatch.setattr(utils, "addon_profile_path", lambda *parts: base.joinpath(*parts) if parts else base)

    payload = {"alpha": 1, "beta": [1, 2, 3]}
    assert utils.cache_set("key-1", payload) is True
    assert utils.cache_get("key-1", ttl_seconds=300) == payload

    cache_file = next((base / "cache").glob("*.json"))
    stale = time.time() - 9999
    os.utime(cache_file, (stale, stale))
    assert utils.cache_get("key-1", ttl_seconds=1) is None

    assert utils.cache_clear() == 1
    assert not any((base / "cache").iterdir())


@pytest.mark.parametrize(
    "name,title,quality,size,seeders",
    [
        ("4k HDR", "Release Name 👤 122 💾 8.91 GB ⚙️ 1337x", "2160p", 9123, 122),
        ("1080p", "Release Name 👤 4 💾 700 MB ⚙️ 900x", "1080p", 700, 4),
        ("unknown", "Release Name 👤 40 ⚙️ 100x", "unknown", 0, 40),
    ],
)
def test_torrentio_parsers(name, title, quality, size, seeders):
    assert torrentio._detect_quality(name, title) == quality
    assert torrentio._parse_size(title) == size
    assert torrentio._parse_seeders(title) == seeders


def test_torrentio_parse_streams_and_filtering():
    raw = {
        "streams": [
            {
                "infoHash": "abc123",
                "name": "release 1080p",
                "title": "Episode One\n👤 42 💾 1.4 GB /EN ⚙️ 900x",
                "fileIdx": 3,
            },
            {
                "infoHash": "def456",
                "name": "release 720p",
                "title": "Episode Two\n720p /FR 900 MB 10 seeds",
                "fileIdx": 7,
            },
        ]
    }
    streams = torrentio.parse_streams(raw, filter_lang="en")
    assert len(streams) == 1
    s = streams[0]
    assert s["infoHash"] == "abc123"
    assert s["quality"] == "1080p"
    assert s["size"] == 1433
    assert s["seeders"] == 42
    assert s["fileIdx"] == 3
    assert s["provider"] == "torrentio"
    assert s["magnet"].startswith("magnet:?xt=urn:btih:abc123&dn=Episode%20One")


def test_trakt_normalise_and_token_expiry(monkeypatch):
    token = {"created_at": 10, "expires_in": 20}
    monkeypatch.setattr(trakt.time, "time", lambda: 31)
    assert trakt._token_expired(token) is True
    monkeypatch.setattr(trakt.time, "time", lambda: 25)
    assert trakt._token_expired(token) is False

    result = trakt._normalise(
        {
            "score": 87.5,
            "movie": {
                "title": "Example",
                "year": 2024,
                "overview": "x" * 600,
                "rating": 8.9,
                "ids": {"tmdb": 123, "imdb": "tt123", "trakt": 999},
            },
        },
        "movie",
    )
    assert result == {
        "_score": 87.5,
        "_source": "trakt",
        "title": "Example",
        "year": 2024,
        "overview": "x" * 500,
        "poster": "https://image.tmdb.org/t/p/w500123",
        "rating": 8.9,
        "tmdb_id": 123,
        "imdb_id": "tt123",
        "media_type": "movie",
        "trakt_id": 999,
    }
