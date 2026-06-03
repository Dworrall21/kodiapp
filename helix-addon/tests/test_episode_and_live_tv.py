from __future__ import annotations

import sys
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / "src/plugin.video.helix"
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from resources.lib import epg
from resources.lib import indexers
from resources.lib import menus


def _labels(kodi_env):
    return [item["label"] for item in kodi_env.directory_items]


def test_fetch_streams_uses_episode_specific_torrentio_lookup(monkeypatch):
    captured = {}

    monkeypatch.setattr(indexers, "_tmdb_to_imdb", lambda tmdb_id, media_type: "tt0903747")
    monkeypatch.setattr(indexers, "cache_get", lambda *args, **kwargs: None)
    monkeypatch.setattr(indexers, "cache_set", lambda *args, **kwargs: None)

    def fake_fetch_episode_streams(imdb_id, season, episode):
        captured["episode_lookup"] = (imdb_id, season, episode)
        return [
            {
                "infoHash": "abc123",
                "name": "Episode Stream",
                "quality": "1080p",
                "size": 123,
                "seeders": 9,
                "magnet": "magnet:?xt=urn:btih:abc123",
                "fileIdx": 0,
                "provider": "torrentio",
            }
        ]

    monkeypatch.setattr(indexers.torr, "fetch_episode_streams", fake_fetch_episode_streams)

    streams = indexers.fetch_streams("501", "tv", season=4, episode=7)

    assert captured["episode_lookup"] == ("tt0903747", 4, 7)
    assert streams[0]["infoHash"] == "abc123"
    assert streams[0]["provider"] == "torrentio"


def test_epg_grid_renders_channel_rows_and_orphan_channels(kodi_env, monkeypatch):
    monkeypatch.setattr(
        menus.m3u,
        "get_filtered_items",
        lambda kind="all": [
            {
                "id": "grp1",
                "title": "Channel One",
                "tvg_id": "chan-1",
                "poster": "https://example.invalid/poster.jpg",
                "backdrop": "https://example.invalid/backdrop.jpg",
            },
        ],
    )
    monkeypatch.setattr(
        epg,
        "get_grid",
        lambda hours_ahead, channel_ids: {
            "channels": [
                {
                    "tvg_id": "chan-1",
                    "display_name": "Channel One",
                    "programmes": [
                        {"start": 100, "stop": 200, "title": "Now Show"},
                        {"start": 250, "stop": 300, "title": "Next Show"},
                    ],
                },
                {
                    "tvg_id": "chan-2",
                    "display_name": "Orphan Channel",
                    "programmes": [
                        {"start": 120, "stop": 180, "title": "Orphan Now"},
                    ],
                },
            ]
        },
    )
    monkeypatch.setattr(epg, "now_epoch", lambda: 150)
    monkeypatch.setattr(epg, "epoch_to_time_str", lambda ts: f"T{ts}")

    menus.list_epg_grid({"hours": "4", "kind": "all"})

    labels = _labels(kodi_env)
    assert any("EPG Guide — Next 4 hours" in label for label in labels)
    assert any("Channel One" in label and "Now Show" in label and "Next Show" in label for label in labels)
    assert any("Orphan Channel" in label and "Orphan Now" in label for label in labels)

    channel_one = next(item for item in kodi_env.directory_items if "Channel One" in item["label"])
    assert channel_one["isFolder"] is True
    assert "action=list_titles" in unquote(channel_one["url"])
    assert channel_one["item"].art["poster"] == "https://example.invalid/poster.jpg"

    orphan = next(item for item in kodi_env.directory_items if "Orphan Channel" in item["label"])
    assert orphan["isFolder"] is False
    assert orphan["url"] == ""
