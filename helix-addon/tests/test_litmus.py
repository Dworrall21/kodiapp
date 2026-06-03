from __future__ import annotations

import sys
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / "src/plugin.video.helix"
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from resources.lib import menus


def _params_from_url(url: str) -> dict[str, str]:
    qs = urlparse(unquote(url)).query
    return {k: v[0] for k, v in parse_qs(qs).items()}


def test_litmus_movie_search_scrape_play(monkeypatch, kodi_env):
    captured = {}

    monkeypatch.setattr(menus.debrid, "_api_key", lambda: False)
    monkeypatch.setattr(menus.trakt, "is_configured", lambda: False)
    monkeypatch.setattr(menus.trakt, "has_token", lambda: True)
    monkeypatch.setattr(
        menus.trakt,
        "scrobble_start",
        lambda media_type, tmdb_id, season=None, episode=None: captured.update(
            {"scrobble": (media_type, tmdb_id, season, episode)}
        ),
    )
    monkeypatch.setattr(menus, "resolve_item", lambda li: captured.update({"resolved_item": li}))

    def fake_play_url(url, li=None):
        captured.update({"play_url": url, "play_item": li})
        if li is not None:
            li.path = url

    monkeypatch.setattr(menus, "play_url", fake_play_url)
    monkeypatch.setattr(menus.m3u, "get_filtered_items", lambda kind="all": [])
    monkeypatch.setattr(
        menus.tmdb,
        "search",
        lambda q: [
            {
                "id": 501,
                "title": "Planet Nine",
                "media_type": "movie",
                "overview": "A movie litmus title.",
                "vote_average": 8.8,
                "release_date": "2024-02-03",
                "poster_path": "/planet-nine.jpg",
            }
        ],
    )

    menus.do_search({"q": "Planet", "media_type": "movie"})

    movie = next(item for item in kodi_env.directory_items if "Planet Nine" in item["label"])
    movie_route = _params_from_url(movie["url"])
    assert movie_route["action"] == "list_tmdb_title"
    assert movie_route["media_type"] == "movie"
    assert movie_route["tmdb_id"] == "501"

    kodi_env.reset()
    monkeypatch.setattr(menus.tmdb, "details", lambda media_type, tmdb_id: {
        "title": "Planet Nine",
        "name": "Planet Nine",
        "overview": "A movie litmus title.",
        "release_date": "2024-02-03",
    })
    monkeypatch.setattr(
        menus.debrid_search,
        "search_by_tmdb",
        lambda media_type, tmdb_id, season=None, episode=None: {
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
    monkeypatch.setattr(menus.m3u, "get_filtered_items", lambda kind="all": [])

    menus.list_tmdb_title({"tmdb_id": "501", "media_type": "movie"})

    stream = next(item for item in kodi_env.directory_items if "Planet Nine WEB-DL" in item["label"])
    stream_route = _params_from_url(stream["url"])
    assert stream_route["action"] == "play"
    assert stream_route["media_type"] == "movie"
    assert stream_route["tmdb_id"] == "501"

    menus.debrid.resolve = lambda url: "http://resolved.invalid/movie.mkv"
    menus.play(stream_route)

    assert captured["play_url"] == "http://resolved.invalid/movie.mkv"
    assert captured["scrobble"] == ("movie", "501", None, None)
    assert captured["play_item"] is captured["resolved_item"]


def test_litmus_tv_episode_search_scrape_play(monkeypatch, kodi_env):
    captured = {}

    monkeypatch.setattr(menus.debrid, "_api_key", lambda: False)
    monkeypatch.setattr(menus.trakt, "is_configured", lambda: False)
    monkeypatch.setattr(menus.trakt, "has_token", lambda: True)
    monkeypatch.setattr(
        menus.trakt,
        "scrobble_start",
        lambda media_type, tmdb_id, season=None, episode=None: captured.update(
            {"scrobble": (media_type, tmdb_id, season, episode)}
        ),
    )
    monkeypatch.setattr(menus, "resolve_item", lambda li: captured.update({"resolved_item": li}))

    def fake_play_url(url, li=None):
        captured.update({"play_url": url, "play_item": li})
        if li is not None:
            li.path = url

    monkeypatch.setattr(menus, "play_url", fake_play_url)
    monkeypatch.setattr(menus.m3u, "get_filtered_items", lambda kind="all": [])
    monkeypatch.setattr(
        menus.tmdb,
        "search",
        lambda q: [
            {
                "id": 602,
                "title": "The Expanse",
                "media_type": "tv",
                "overview": "A tv litmus title.",
                "vote_average": 8.5,
                "first_air_date": "2015-12-14",
                "poster_path": "/expanse.jpg",
            }
        ],
    )

    menus.do_search({"q": "Expanse", "media_type": "tv"})

    show = next(item for item in kodi_env.directory_items if "The Expanse" in item["label"])
    show_route = _params_from_url(show["url"])
    assert show_route["action"] == "list_tmdb_title"
    assert show_route["media_type"] == "tv"
    assert show_route["tmdb_id"] == "602"

    kodi_env.reset()
    monkeypatch.setattr(menus.tmdb, "details", lambda media_type, tmdb_id: {
        "title": "The Expanse",
        "name": "The Expanse",
        "overview": "A tv litmus title.",
        "first_air_date": "2015-12-14",
    })
    season_episode = {}

    def fake_search_by_tmdb(media_type, tmdb_id, season=None, episode=None):
        season_episode.update({"value": (media_type, tmdb_id, season, episode)})
        return {
            "1080p": [
                {
                    "name": "The Expanse S01E01 WEB-DL",
                    "source": "Torrentio",
                    "size_mb": 2048,
                    "cached": True,
                    "infoHash": "beadfeed",
                    "url": "",
                    "_quality": "1080p",
                }
            ]
        }

    monkeypatch.setattr(menus.debrid_search, "search_by_tmdb", fake_search_by_tmdb)
    monkeypatch.setattr(menus.m3u, "get_filtered_items", lambda kind="all": [])

    menus.list_tmdb_title({"tmdb_id": "602", "media_type": "tv", "season": "1", "episode": "1"})

    assert season_episode["value"] == ("tv", "602", "1", "1")
    stream = next(item for item in kodi_env.directory_items if "The Expanse S01E01 WEB-DL" in item["label"])
    stream_route = _params_from_url(stream["url"])
    assert stream_route["action"] == "play"
    assert stream_route["media_type"] == "tv"
    assert stream_route["tmdb_id"] == "602"
    assert stream_route["season"] == "1"
    assert stream_route["episode"] == "1"

    menus.debrid.resolve = lambda url: "http://resolved.invalid/expanse.mkv"
    menus.play(stream_route)

    assert captured["play_url"] == "http://resolved.invalid/expanse.mkv"
    assert captured["scrobble"] == ("tv", "602", "1", "1")
    assert captured["play_item"] is captured["resolved_item"]
