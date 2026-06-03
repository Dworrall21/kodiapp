from __future__ import annotations

from urllib.parse import unquote

from resources.lib import indexers
from resources.lib import menus


def _m3u_group(title: str, group_id: str = "m3u-1"):
    return {
        "id": group_id,
        "title": title,
        "group": title,
        "count": 2,
        "kind": "tv",
        "streams": [
            {"name": title + " Stream 1", "url": "http://example.invalid/live1"},
            {"name": title + " Stream 2", "url": "http://example.invalid/live2"},
        ],
        "tvg_id": "",
    }


def test_indexers_falls_back_from_torrentio_to_comet(monkeypatch, kodi_env):
    monkeypatch.setattr(indexers, "_tmdb_to_imdb", lambda tmdb_id, media_type: None)
    monkeypatch.setattr(indexers, "cache_get", lambda *args, **kwargs: None)
    monkeypatch.setattr(indexers, "cache_set", lambda *args, **kwargs: True)
    monkeypatch.setattr(indexers, "get_setting", lambda key, default="": {"indexers.comet_url": "http://comet.local"}.get(key, default))
    monkeypatch.setattr(indexers, "_http_get", lambda url, timeout=10, retries=1: {"streams": []})

    def fake_comet(base_url, media_type, media_id, timeout=10):
        assert base_url == "http://comet.local"
        assert media_type == "movie"
        assert media_id == "tmdb:1234"
        return indexers._parse_streams_from(
            [
                {
                    "infoHash": "c0ffee",
                    "name": "Comet Release 1080p",
                    "title": "Comet Release 👤 9 💾 1.5 GB /EN",
                    "fileIdx": 2,
                }
            ],
            "comet",
        )

    monkeypatch.setattr(indexers, "_query_comet", fake_comet)
    monkeypatch.setattr(indexers, "_query_bitmagnet", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("bitmagnet should not be used")))

    streams = indexers.fetch_streams(1234, "movie")

    assert len(streams) == 1
    stream = streams[0]
    assert stream["provider"] == "comet"
    assert stream["quality"] == "1080p"
    assert stream["seeders"] == 9
    assert stream["size"] == 1536
    assert stream["infoHash"] == "c0ffee"


def test_search_merges_tmdb_trakt_and_m3u_results(monkeypatch, kodi_env):
    monkeypatch.setattr(menus, "_load_favorites", lambda: [])
    monkeypatch.setattr(menus.debrid, "_api_key", lambda: "key")
    monkeypatch.setattr(
        menus.debrid_search,
        "search",
        lambda tmdb_id, media_type="movie": [{"infoHash": "cached"}] if str(tmdb_id) in {"101", "202"} else [],
        raising=False,
    )

    monkeypatch.setattr(
        menus.tmdb,
        "search",
        lambda q: [
            {
                "id": 101,
                "title": "Planet Nine",
                "media_type": "movie",
                "overview": "Lost world on edge of the solar system.",
                "vote_average": 8.3,
                "release_date": "2024-01-20",
                "poster_path": "/planet-nine.jpg",
            }
        ],
    )
    monkeypatch.setattr(menus.trakt, "is_configured", lambda: True)
    monkeypatch.setattr(
        menus.trakt,
        "search",
        lambda q: [
            {
                "_score": 88.0,
                "title": "Planet Nine",
                "year": 2023,
                "overview": "A Trakt-backed version of the same title.",
                "rating": 7.7,
                "tmdb_id": 202,
                "media_type": "movie",
                "poster": "/trakt-planet-nine.jpg",
            }
        ],
    )
    monkeypatch.setattr(menus.m3u, "get_filtered_items", lambda kind="all": [_m3u_group("Planet Nine Live")])

    menus.do_search({"q": "Planet"})

    labels = [item["label"] for item in kodi_env.directory_items]
    assert any("Search Results — TMDB:1  Trakt:1  M3U:1" in label for label in labels)

    result_labels = [label for label in labels if "Planet" in label and "Search Results" not in label]
    assert len(result_labels) == 3
    assert "[TMDB]" in result_labels[0]
    assert "✓ Cached" in result_labels[0]
    assert "[Trakt]" in result_labels[1]
    assert "Planet Nine Live" in result_labels[2]

    tmdb_item = kodi_env.directory_items[1]["item"]
    assert tmdb_item.info["title"] == "Planet Nine"
    assert tmdb_item.info["plot"] == "Lost world on edge of the solar system."
    assert tmdb_item.info["year"] == 2024
    assert tmdb_item.info["rating"] == 8.3
    assert tmdb_item.art["poster"].endswith("/planet-nine.jpg")


def test_discover_titles_and_title_page_show_rich_metadata(monkeypatch, kodi_env):
    monkeypatch.setattr(menus, "_load_favorites", lambda: [])
    monkeypatch.setattr(menus.trakt, "has_token", lambda: False)

    monkeypatch.setattr(
        menus.tmdb,
        "discover",
        lambda kind: [
            {
                "id": 501,
                "title": "Planet Nine",
                "release_date": "2024-02-03",
                "overview": "A richly described discovery result.",
                "vote_average": 8.8,
                "poster_path": "/discover-poster.jpg",
            }
        ],
    )
    menus.list_tmdb_titles({"media_type": "movie", "discover_kind": "trending_week"})

    discover_item = next(item for item in kodi_env.directory_items if "Planet Nine" in item["label"])
    assert discover_item["item"].info["title"] == "Planet Nine"
    assert discover_item["item"].info["plot"] == "A richly described discovery result."
    assert discover_item["item"].info["year"] == 2024
    assert discover_item["item"].info["rating"] == 8.8
    assert discover_item["item"].art["poster"].endswith("/discover-poster.jpg")

    kodi_env.reset()
    monkeypatch.setattr(
        menus.tmdb,
        "details",
        lambda media_type, tmdb_id: {
            "title": "Planet Nine",
            "name": "Planet Nine",
            "overview": "Long-form title metadata.",
            "release_date": "2024-02-03",
        },
    )
    monkeypatch.setattr(
        menus.debrid_search,
        "search_by_tmdb",
        lambda media_type, tmdb_id: {
            "1080p": [
                {
                    "name": "Planet Nine WEB-DL",
                    "source": "Torrentio",
                    "size_mb": 1536,
                    "cached": True,
                    "infoHash": "deadbeef",
                    "url": "",
                    "_quality": "1080p",
                }
            ]
        },
    )
    monkeypatch.setattr(menus.m3u, "get_filtered_items", lambda kind="all": [_m3u_group("Planet Nine Live")])

    menus.list_tmdb_title({"tmdb_id": "501", "media_type": "movie"})

    labels = [item["label"] for item in kodi_env.directory_items]
    assert any("Debrid Streams" in label for label in labels)
    assert any("1080p" in label for label in labels)
    assert any("Planet Nine WEB-DL" in label for label in labels)
    assert any("Live TV / M3U" in label for label in labels)
    assert any("Planet Nine Live" in label for label in labels)

    stream_item = next(item for item in kodi_env.directory_items if "Planet Nine WEB-DL" in item["label"])
    assert stream_item["item"].properties["IsPlayable"] == "true"
    assert "Source: Torrentio" in stream_item["item"].info["plot"]
    assert unquote(stream_item["item"].path).startswith("plugin://plugin.video.helix/?action=play&url=magnet:?xt=urn:btih:deadbeef")
