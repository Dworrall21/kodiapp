from __future__ import annotations

import json
import sys
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / "src/plugin.video.helix"
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from resources.lib import menus


def test_play_route_resolves_debrid_and_trakt_scrobbles(monkeypatch, kodi_env):
    captured = {}

    monkeypatch.setattr(menus.debrid, "resolve", lambda url: "http://resolved.invalid/stream.mkv")
    monkeypatch.setattr(menus.trakt, "has_token", lambda: True)
    monkeypatch.setattr(
        menus.trakt,
        "scrobble_start",
        lambda media_type, tmdb_id: captured.update({"scrobble": (media_type, tmdb_id)}),
    )
    monkeypatch.setattr(menus, "resolve_item", lambda li: captured.update({"resolved_item": li}))

    def fake_play_url(url, li=None):
        captured.update({"play_url": url, "play_item": li})
        if li is not None:
            li.path = url

    monkeypatch.setattr(menus, "play_url", fake_play_url)

    menus.play({"url": "magnet:?xt=urn:btih:deadbeef", "tmdb_id": "501", "media_type": "movie"})

    assert captured["play_url"] == "http://resolved.invalid/stream.mkv"
    assert captured["scrobble"] == ("movie", "501")
    assert captured["play_item"] is captured["resolved_item"]
    assert captured["play_item"].label == "Stream"
    assert captured["play_item"].properties["IsPlayable"] == "true"
    assert captured["play_item"].path == "http://resolved.invalid/stream.mkv"


def test_play_route_passes_season_and_episode_to_trakt(monkeypatch, kodi_env):
    captured = {}

    monkeypatch.setattr(menus.debrid, "resolve", lambda url: url)
    monkeypatch.setattr(menus.trakt, "has_token", lambda: True)
    monkeypatch.setattr(
        menus.trakt,
        "scrobble_start",
        lambda *args: captured.update({"scrobble": args}),
    )
    monkeypatch.setattr(menus, "resolve_item", lambda li: captured.update({"resolved_item": li}))

    def fake_play_url(url, li=None):
        captured.update({"play_url": url, "play_item": li})
        if li is not None:
            li.path = url

    monkeypatch.setattr(menus, "play_url", fake_play_url)

    menus.play({
        "url": "http://example.invalid/episode.mkv",
        "tmdb_id": "600",
        "media_type": "tv",
        "season": "4",
        "episode": "7",
    })

    assert captured["scrobble"] == ("tv", "600", "4", "7")
    assert captured["play_url"] == "http://example.invalid/episode.mkv"
    assert captured["play_item"] is captured["resolved_item"]


def test_tmdb_favorites_round_trip_persists_to_profile(monkeypatch, kodi_env, tmp_path):
    fav_file = tmp_path / "favorites.json"
    monkeypatch.setattr(menus, "_fav_path", lambda: str(fav_file))
    monkeypatch.setattr(
        menus.m3u,
        "get_filtered_items",
        lambda kind="all": [
            {
                "id": "grp1",
                "title": "Planet Nine",
                "plot": "A title worth saving.",
                "year": 2024,
            }
        ],
    )

    menus.add_favorite_tmdb({
        "tmdb_id": "501",
        "media_type": "movie",
        "title": "Planet Nine",
        "plot": "A title worth saving.",
        "year": "2024",
    })
    menus.add_favorite({"group": "grp1"})

    stored = json.loads(Path(fav_file).read_text(encoding="utf-8"))
    assert [item["tmdb_id"] for item in stored if item.get("tmdb_id")] == ["501"]
    assert any(item["id"] == "grp1" for item in stored)
    assert any(n["message"] == "Added favorite." for n in kodi_env.notifications)
    assert any(n["message"] == "Added: Planet Nine" for n in kodi_env.notifications)

    menus.remove_favorite_tmdb({"tmdb_id": "501"})
    menus.remove_favorite({"group": "grp1"})

    stored = json.loads(Path(fav_file).read_text(encoding="utf-8"))
    assert stored == []
    assert any(n["message"] == "Removed." for n in kodi_env.notifications)


def test_trakt_lists_and_items_render_tmdb_links(monkeypatch, kodi_env):
    monkeypatch.setattr(menus.trakt, "is_authorized", lambda: True)
    monkeypatch.setattr(
        menus.trakt,
        "get_user_lists",
        lambda: [
            {
                "id": "list-1",
                "name": "Helix Watchlist",
                "item_count": 2,
                "description": "Movies + shows",
            }
        ],
    )

    def fake_list_items(list_id, kind):
        if list_id != "list-1":
            return []
        if kind == "movies":
            return [{"type": "movie", "title": "Tron", "year": 1982, "tmdb_id": 11}]
        if kind == "shows":
            return [{"type": "show", "title": "The Expanse", "year": 2015, "tmdb_id": 22}]
        return []

    monkeypatch.setattr(menus.trakt, "get_list_items", fake_list_items)

    menus.list_trakt_lists({})
    labels = [item["label"] for item in kodi_env.directory_items]
    assert any("[ Sync Favorites to Trakt ]" in label for label in labels)
    assert any("Helix Watchlist" in label for label in labels)

    kodi_env.reset()
    monkeypatch.setattr(menus.trakt, "is_authorized", lambda: True)
    monkeypatch.setattr(menus.trakt, "get_list_items", fake_list_items)

    menus.list_trakt_list_items({"list_id": "list-1", "list_name": "Helix Watchlist"})
    labels = [item["label"] for item in kodi_env.directory_items]
    assert any("Tron" in label for label in labels)
    assert any("The Expanse" in label for label in labels)

    tron = next(item for item in kodi_env.directory_items if "Tron" in item["label"])
    expanse = next(item for item in kodi_env.directory_items if "The Expanse" in item["label"])
    assert "action=list_tmdb_title" in unquote(tron["url"])
    assert "media_type=movie" in unquote(tron["url"])
def test_tmdb_episode_detail_passes_episode_coordinates_into_debrid_search(monkeypatch, kodi_env):
    captured = {}

    monkeypatch.setattr(
        menus.tmdb,
        "details",
        lambda media_type, tmdb_id: {
            "title": "Planet Nine",
            "name": "Planet Nine",
            "overview": "Episode detail metadata.",
            "first_air_date": "2024-02-03",
        },
    )
    monkeypatch.setattr(
        menus.debrid_search,
        "search_by_tmdb",
        lambda media_type, tmdb_id, season=None, episode=None: captured.update({
            "search": (media_type, tmdb_id, season, episode)
        }) or {
            "1080p": [
                {
                    "name": "Planet Nine S04E07 WEB-DL",
                    "source": "Torrentio",
                    "size_mb": 1536,
                    "cached": True,
                    "infoHash": "feedface",
                    "url": "",
                    "_quality": "1080p",
                }
            ]
        },
    )
    monkeypatch.setattr(menus.m3u, "get_filtered_items", lambda kind="all": [])

    menus.list_tmdb_title({"tmdb_id": "501", "media_type": "tv", "season": "4", "episode": "7"})

    assert captured["search"] == ("tv", "501", "4", "7")
    item = next(item for item in kodi_env.directory_items if "Planet Nine S04E07 WEB-DL" in item["label"])
    assert "season=4" in unquote(item["url"])
    assert "episode=7" in unquote(item["url"])
