from __future__ import annotations

from pathlib import Path

import pytest

from resources.lib import dashboard
from resources.lib import utils


def test_dashboard_pages_show_expected_entries(kodi_env, monkeypatch):
    monkeypatch.setattr(dashboard, "_collect_debug_info", lambda: {
        "version": "0.4.1",
        "id": "plugin.video.helix",
        "name": "Helix",
        "path": "/opt/helix",
        "profile": "/tmp/helix-profile",
        "kodi_version": "21.2",
        "kodi_build": "Kodi-21",
        "repo_url": "https://github.com/Dworrall21/kodiapp",
        "service_alive": "yes",
        "m3u_source": "https://example.invalid/list.m3u",
        "m3u_count": 7,
        "debrid": "Real-Debrid",
        "debrid_key": "abcd1234",
        "tmdb_key": "efgh5678",
        "indexers": "Torrentio, Comet",
        "indexers_enabled": "true",
        "news_url": "https://example.invalid/news",
        "cache_threshold": 500,
        "packages_mb": 12,
        "temp_mb": 34,
    })
    monkeypatch.setattr(dashboard, "_collect_gui_snapshot", lambda: {
        "system_time": "12:34",
        "system_date": "2026-06-03",
        "container_path": "plugin://plugin.video.helix/?action=dashboard",
        "container_content": "files",
        "container_num_items": "5",
        "container_position": "0",
        "item_label": "Helix",
        "item_path": "plugin://plugin.video.helix/?action=dashboard",
        "video_playing": "false",
        "container_has_focus": "true",
    })

    dashboard.home()
    dashboard.debug()
    dashboard.logs_menu()
    dashboard.settings_list()
    dashboard.actions_menu()
    dashboard.about()

    labels = [item["label"] for item in kodi_env.directory_items]
    for needle in [
        "Debug",
        "Logs",
        "Settings",
        "Actions",
        "About",
        "Helix v0.4.1",
        "Tail last 200 lines",
        "Helix Settings",
        "Clear Helix cache",
        "Helix — About",
    ]:
        assert any(needle in label for label in labels), needle

    assert any(call[0] == "setContent" for call in kodi_env.calls)
    assert any(call[0] == "addSortMethod" for call in kodi_env.calls)


def test_dashboard_log_view_and_actions(kodi_env, monkeypatch, tmp_path):
    log_path = tmp_path / "kodi.log"
    log_path.write_text("[Helix] ok\nWARNING something\nERROR boom\nother\n", encoding="utf-8")

    monkeypatch.setattr(dashboard, "_resolve_kodi_log", lambda: str(log_path))
    monkeypatch.setattr(dashboard, "_read_log_tail", lambda path, max_bytes=0: log_path.read_text(encoding="utf-8"))

    dashboard.log_view({"mode": "errors", "n": "2"})
    assert kodi_env.dialogs[-1][0] == "textviewer"
    assert "kodi.log (errors, 2 lines)" in kodi_env.dialogs[-1][1][0]
    assert "ERROR boom" in kodi_env.dialogs[-1][1][1]

    monkeypatch.setattr(dashboard, "cache_clear", lambda: 3)
    dashboard.action_clear_cache()
    assert kodi_env.notifications[-1]["message"] == "Cache cleared (3 files)."

    monkeypatch.setattr(dashboard, "log_export", lambda params=None: kodi_env.calls.append(("log_export", (), {})))
    dashboard.action_save_log()
    assert ("log_export", (), {}) in kodi_env.calls

    monkeypatch.setattr(dashboard, "_collect_debug_info", lambda: {"alpha": "1", "beta": "2"})
    monkeypatch.setattr(dashboard, "_collect_gui_snapshot", lambda: {"gamma": "3"})
    dashboard.action_dump_debug()
    assert any("DASHBOARD DEBUG DUMP" in msg for _, msg in kodi_env.logs)
    assert kodi_env.notifications[-1]["message"] == "Dumped to kodi.log."

    kodi_env.yesno_result = True
    restart_file = Path("/tmp/.helix_service_restart")
    if restart_file.exists():
        restart_file.unlink()
    dashboard.action_restart_service()
    assert restart_file.exists()
    assert "EnableAddon(plugin.video.helix)" in kodi_env.builtin_calls
