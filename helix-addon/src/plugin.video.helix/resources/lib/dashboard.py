# -*- coding: utf-8 -*-
"""
dashboard: an in-addon settings / debug / logs / actions panel.

A single mode (action=dashboard) that opens a sub-menu of:
  - Debug     : read-only diagnostic info
  - Logs      : tail, filter, helix-only, download kodi.log
  - Settings  : list of every addon setting with an Edit action
  - Actions   : clear cache, force update, speedtest, test keys, etc.
  - About     : version, repo, credits

Each sub-page is just a directory built with add_item + url_for. The router
dispatches ?action=dashboard_xxx with optional params (key=..., filter=...).

All xbmc imports are lazy (utils pattern) so the module is importable in
plain Python for unit testing.
"""
import os
import sys
import time
import json
import shutil
import urllib.request
import urllib.error
import re

# Make `resources.lib` importable when this file is loaded as a top-level module
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, os.path.dirname(_HERE))

from .utils import (
    log, notify, yesno, dialog_input, dialog_select, text_viewer,
    get_setting, set_setting, get_int_setting, get_bool_setting,
    add_item, url_for, set_content, add_sort_method, make_item,
    addon_info, addon_profile_path, cache_clear, get_addon,
)
from .modules.colors import c, b


# --- kodi.log path candidates (matches tools.py view_logs) ---
_KODI_LOG_PATHS = [
    "/storage/.kodi/temp/kodi.log",                          # LibreELEC / CoreELEC
    os.path.expanduser("~/.kodi/temp/kodi.log"),              # Linux desktop
    "/root/.kodi/temp/kodi.log",                             # alt Linux
    "special://logpath/kodi.log",                            # Kodi 18+ logpath
    os.path.expanduser("~/Library/Logs/kodi.log"),           # macOS
]


def _resolve_kodi_log():
    """Return the path to kodi.log, trying each known location."""
    for p in _KODI_LOG_PATHS:
        if not p:
            continue
        if p.startswith("special://"):
            try:
                import xbmcvfs
                p = xbmcvfs.translatePath(p)
            except Exception:
                continue
        if p and os.path.exists(p):
            return p
    return None


def _read_log_tail(path, max_bytes=200 * 1024):
    """Return last `max_bytes` of the log as a string."""
    try:
        with open(path, "rb") as fh:
            fh.seek(0, 2)
            size = fh.tell()
            fh.seek(max(0, size - max_bytes))
            data = fh.read().decode("utf-8", errors="replace")
        return data
    except Exception as exc:
        return "[unable to read log: %s]" % exc


def _filter_log(text, helix_only=False, errors_only=False, query=""):
    """Apply the requested filters to a log string, return filtered lines."""
    lines = text.splitlines()
    out = []
    q = (query or "").lower().strip()
    rx_err = re.compile(r"\b(ERROR|FATAL|CRITICAL)\b", re.IGNORECASE)
    rx_warn = re.compile(r"\b(WARNING|WARN)\b", re.IGNORECASE)
    for ln in lines:
        if helix_only and "[Helix]" not in ln and "[plugin.video.helix]" not in ln:
            continue
        if errors_only and not (rx_err.search(ln) or rx_warn.search(ln)):
            continue
        if q and q not in ln.lower():
            continue
        out.append(ln)
    return out


def _safe_info_label(label, default=""):
    try:
        import xbmc
        return xbmc.getInfoLabel(label) or default
    except Exception:
        return default


def _safe_cond(expr):
    try:
        import xbmc
        return bool(xbmc.getCondVisibility(expr))
    except Exception:
        return False


def _collect_gui_snapshot():
    """Grab live Kodi GUI state: system, container, and focused list item."""
    labels = [
        ("system_time", "System.Time"),
        ("system_date", "System.Date"),
        ("system_window", "System.CurrentWindow"),
        ("system_control", "System.CurrentControl"),
        ("system_build", "System.BuildVersion"),
        ("system_build_date", "System.BuildDate"),
        ("system_os", "System.OSVersionInfo"),
        ("system_platform", "System.Platform"),
        ("system_cpu", "System.CpuUsage"),
        ("system_free_mem", "System.FreeMemory"),
        ("system_screen_w", "System.ScreenWidth"),
        ("system_screen_h", "System.ScreenHeight"),
        ("container_path", "Container.FolderPath"),
        ("container_content", "Container.Content"),
        ("container_num_items", "Container.NumItems"),
        ("container_position", "Container.Position"),
        ("container_current_item", "Container.CurrentItem"),
        ("container_view_mode", "Container.ViewMode"),
        ("container_sort_method", "Container.SortMethod"),
        ("container_folder_name", "Container.FolderName"),
        ("item_label", "Container.ListItem.Label"),
        ("item_label2", "Container.ListItem.Label2"),
        ("item_path", "Container.ListItem.Path"),
        ("item_title", "Container.ListItem.Title"),
        ("item_plot", "Container.ListItem.Plot"),
        ("item_thumb", "Container.ListItem.Art(thumb)"),
        ("item_icon", "Container.ListItem.Art(icon)"),
        ("item_fanart", "Container.ListItem.Art(fanart)"),
        ("item_is_playable", "Container.ListItem.Property(IsPlayable)"),
        ("item_is_folder", "Container.ListItem.Property(IsFolder)"),
        ("item_mimetype", "Container.ListItem.Property(mimetype)"),
        ("item_folderpath", "Container.ListItem.Property(FolderPath)"),
        ("item_foldername", "Container.ListItem.Property(FolderName)"),
    ]
    out = {}
    for key, label in labels:
        val = _safe_info_label(label)
        if val:
            out[key] = str(val)
    flags = [
        ("video_playing", "VideoPlayer.IsPlaying"),
        ("picture_showing", "PicturePlayer.IsShowing"),
        ("container_has_focus", "Container.HasFocus"),
    ]
    for key, expr in flags:
        try:
            out[key] = "true" if _safe_cond(expr) else "false"
        except Exception:
            pass
    return out


def home(params=None):
    set_content("files")
    add_sort_method(0)  # default sort
    add_item(c("deepskyblue", b("Debug")),         url_for("dashboard_debug"),
             is_folder=True, info={"plot": "Read-only diagnostic info: version, paths, debrid, TMDB, M3U, cache."})
    add_item(c("deepskyblue", b("Logs")),          url_for("dashboard_logs"),
             is_folder=True, info={"plot": "Tail kodi.log, filter, download. Helix-only / errors-only modes."})
    add_item(c("deepskyblue", b("Settings")),      url_for("dashboard_settings"),
             is_folder=True, info={"plot": "Edit every Helix setting from a flat list."})
    add_item(c("deepskyblue", b("Actions")),       url_for("dashboard_actions"),
             is_folder=True, info={"plot": "Clear cache, force update, speedtest, test keys, refresh M3U, restart service."})
    add_item(c("deepskyblue", b("About")),         url_for("dashboard_about"),
             is_folder=True, info={"plot": "Version, repo URL, credits."})

# --- Debug page ---
def debug(params=None):
    set_content("files")
    add_sort_method(0)

    # Collect diagnostics
    info = _collect_debug_info()

    # Title
    add_item(c("gold", b("Helix v%s — Debug Info" % info.get("version", "?"))),
             "", is_folder=False,
             info={"plot": "Read-only. No items are clickable."})

    # Pairs of (label, value)
    rows = [
        ("Addon ID",       info.get("id", "")),
        ("Addon name",     info.get("name", "")),
        ("Version",        info.get("version", "")),
        ("Install path",   info.get("path", "")),
        ("Profile path",   info.get("profile", "")),
        ("Kodi version",   info.get("kodi_version", "")),
        ("Kodi build",     info.get("kodi_build", "")),
        ("Repo URL",       info.get("repo_url", "")),
        ("Service alive",  info.get("service_alive", "?")),
        ("M3U source",     info.get("m3u_source", "(none)")),
        ("M3U items",      info.get("m3u_count", "0")),
        ("Debrid provider", info.get("debrid", "None")),
        ("Debrid key",     info.get("debrid_key", "(not set)")),
        ("TMDB key",       info.get("tmdb_key", "(not set)")),
        ("Indexers",       info.get("indexers", "None")),
        ("Indexers enabled", info.get("indexers_enabled", "?")),
        ("News URL",       info.get("news_url", "(not set)")),
        ("Cache threshold", info.get("cache_threshold", "?")),
        ("Packages dir size", str(info.get("packages_mb", "?")) + " MB"),
        ("Temp dir size",     str(info.get("temp_mb", "?")) + " MB"),
    ]
    for label, val in rows:
        display = c("white", b(label) + ":  ") + c("gray", str(val))
        add_item(display, "", is_folder=False, info={"plot": str(val)})

    # Live GUI snapshot
    add_item(c("gold", b("Live GUI Snapshot")), "", is_folder=False,
             info={"plot": "Current Kodi GUI/container/list-item state captured live."})
    gui_rows = [
        ("System time", info.get("system_time", "")),
        ("System date", info.get("system_date", "")),
        ("Current window", info.get("system_window", "")),
        ("Current control", info.get("system_control", "")),
        ("Container path", info.get("container_path", "")),
        ("Container content", info.get("container_content", "")),
        ("Container items", info.get("container_num_items", "")),
        ("Container position", info.get("container_position", "")),
        ("Container current item", info.get("container_current_item", "")),
        ("ListItem label", info.get("item_label", "")),
        ("ListItem label2", info.get("item_label2", "")),
        ("ListItem path", info.get("item_path", "")),
        ("ListItem title", info.get("item_title", "")),
        ("ListItem plot", info.get("item_plot", "")),
        ("ListItem thumb", info.get("item_thumb", "")),
        ("ListItem playable", info.get("item_is_playable", "")),
        ("ListItem folder", info.get("item_is_folder", "")),
        ("ListItem mimetype", info.get("item_mimetype", "")),
        ("Video playing", info.get("video_playing", "")),
        ("Container has focus", info.get("container_has_focus", "")),
    ]
    for label, val in gui_rows:
        if val not in ("", None):
            display = c("white", b(label) + ":  ") + c("gray", str(val))
            add_item(display, "", is_folder=False, info={"plot": str(val)})

    # Footer: refresh / dump to log
    add_item(c("gold", b("[ Refresh ]")), url_for("dashboard_debug"), is_folder=True,
             info={"plot": "Re-collect debug info."})
    add_item(c("lightgray", "Dump debug to kodi.log"), url_for("dashboard_action_dump_debug"),
             is_folder=False, info={"plot": "Write all values to kodi.log as a single block."})


def _collect_debug_info():
    """Pull diagnostic info from xbmc + addon state."""
    out = {
        "id": addon_info("id"),
        "name": addon_info("name"),
        "version": addon_info("version"),
        "path": addon_info("path"),
        "profile": addon_info("profile"),
        "repo_url": get_setting("repo.url") or "https://dworrall21.github.io/kodiapp/",
    }
    out.update(_collect_gui_snapshot())
    # Kodi version
    try:
        import xbmc
        out["kodi_version"] = xbmc.getInfoLabel("System.BuildVersion") or "?"
        out["kodi_build"] = xbmc.getInfoLabel("System.BuildDate") or "?"
    except Exception:
        out["kodi_version"] = "?"
        out["kodi_build"] = "?"
    # Service alive flag
    out["service_alive"] = "yes" if os.path.exists("/tmp/.helix_service_alive") else "no"
    # M3U
    from . import m3u
    src = m3u.get_cached_source()
    out["m3u_source"] = (src.get("source") if src else "") or "(no cached source)"
    out["m3u_count"] = str(len(src.get("items", []))) if src else "0"
    # Debrid
    from . import debrid
    out["debrid"] = debrid.active_provider_name() or "None"
    key_setting = debrid.active_provider()[1]
    if key_setting:
        key = get_setting(key_setting)
        out["debrid_key"] = "(set, %d chars)" % len(key) if key else "(not set)"
    else:
        out["debrid_key"] = "n/a"
    # TMDB
    tmdb_key = get_setting("tmdb.api_key")
    out["tmdb_key"] = "(set, %d chars)" % len(tmdb_key) if tmdb_key else "(not set)"
    # News
    news_url = get_setting("news.url")
    out["news_url"] = news_url or "(not set)"
    # Cache
    out["cache_threshold"] = str(get_int_setting("cache.threshold_mb", 500))
    # Indexers
    from . import indexers as idx_mod
    out["indexers"] = ", ".join(idx_mod.active_indexer_names()) or "None"
    out["indexers_enabled"] = "yes" if get_bool_setting("indexers.enabled", True) else "no"
    try:
        import xbmcvfs
        home = xbmcvfs.translatePath("special://home")
    except Exception:
        home = ""
    for d, key in [("packages", "packages_mb"), ("temp", "temp_mb")]:
        p = os.path.join(home, d) if home else ""
        total = 0
        if p and os.path.isdir(p):
            for root, _, files in os.walk(p):
                for f in files:
                    try:
                        total += os.path.getsize(os.path.join(root, f))
                    except Exception:
                        pass
        out[key] = str(total // (1024 * 1024))
    return out


# --- Logs page ---
def logs_menu(params=None):
    set_content("files")
    add_sort_method(0)
    add_item(c("orange", b("Tail last 200 lines")),  url_for("dashboard_log_view", mode="tail", n="200"),
             is_folder=False, info={"plot": "Show the last 200 lines of kodi.log."})
    add_item(c("orange", b("Tail last 1000 lines")), url_for("dashboard_log_view", mode="tail", n="1000"),
             is_folder=False, info={"plot": "Show the last 1000 lines of kodi.log."})
    add_item(c("orange", b("Helix-only (last 500)")), url_for("dashboard_log_view", mode="helix", n="500"),
             is_folder=False, info={"plot": "Only show lines that contain [Helix] or [plugin.video.helix]."})
    add_item(c("orange", b("Errors & Warnings (last 1000)")), url_for("dashboard_log_view", mode="errors", n="1000"),
             is_folder=False, info={"plot": "Filter for ERROR / WARNING / FATAL / CRITICAL."})
    add_item(c("orange", b("Filter by text…")),      url_for("dashboard_log_filter"),
             is_folder=True, info={"plot": "Search kodi.log for a custom substring."})
    add_item(c("orange", b("Download full log")),     url_for("dashboard_log_export"),
             is_folder=False, info={"plot": "Copy kodi.log to Helix profile (addon_data)."})
    add_item(c("lightgray", "Open kodi.log location"), url_for("dashboard_log_path"),
             is_folder=False, info={"plot": "Show the absolute path of kodi.log."})


def log_view(params=None):
    mode = (params or {}).get("mode", "tail")
    try:
        n = int((params or {}).get("n", "200"))
    except Exception:
        n = 200
    query = (params or {}).get("q", "")
    p = _resolve_kodi_log()
    if not p:
        notify("Helix — Dashboard", "kodi.log not found.", "warn", 4000)
        return
    text = _read_log_tail(p, max_bytes=1024 * 1024)  # 1MB cap
    if mode == "helix":
        lines = _filter_log(text, helix_only=True)
    elif mode == "errors":
        lines = _filter_log(text, errors_only=True)
    elif mode == "filter":
        lines = _filter_log(text, helix_only=False, errors_only=False, query=query)
    else:
        lines = text.splitlines()
    if n > 0 and len(lines) > n:
        lines = lines[-n:]
    body = "\n".join(lines) if lines else "(no matching lines)"
    text_viewer("Helix — kodi.log (%s, %d lines)" % (mode, len(lines)), body)


def log_filter_prompt(params=None):
    q = dialog_input("Filter text (case-insensitive)")
    if not q:
        return
    # Re-enter the view with mode=filter&q=q
    li = make_item("Open", url_for("dashboard_log_view", mode="filter", q=q),
                   is_folder=False, info={"plot": "Apply filter."})
    try:
        import xbmcplugin
        xbmcplugin.addDirectoryItem(0, url_for("dashboard_log_view", mode="filter", q=q), li, isFolder=False)
        xbmcplugin.endOfDirectory(0, succeeded=True, updateListing=False)
    except Exception:
        # Fallback: just open the view directly
        log_view({"mode": "filter", "q": q})


def log_export(params=None):
    p = _resolve_kodi_log()
    if not p:
        notify("Helix — Dashboard", "kodi.log not found.", "warn", 4000)
        return
    text = _read_log_tail(p, max_bytes=2 * 1024 * 1024)
    out_dir = addon_profile_path("logs")
    try:
        os.makedirs(out_dir, exist_ok=True)
    except Exception:
        pass
    stamp = time.strftime("%Y%m%d-%H%M%S")
    out = os.path.join(out_dir, "kodi-%s.log" % stamp)
    try:
        with open(out, "w", encoding="utf-8") as fh:
            fh.write(text)
        notify("Helix — Dashboard", "Saved: %s" % out, "info", 5000)
    except Exception as exc:
        notify("Helix — Dashboard", "Save failed: %s" % exc, "error", 5000)


def log_path(params=None):
    p = _resolve_kodi_log() or "(not found)"
    text_viewer("Helix — kodi.log path", p)


# --- Settings page ---
# (key, label, kind, options-or-None)
# kind in: text, int, bool, enum, slider
_SETTINGS = [
    # M3U
    ("source.m3u.url",          "M3U URL",                "text",  None),
    ("source.m3u.local",        "Local M3U file path",    "text",  None),
    ("source.m3u.refresh",      "Refresh interval (h)",   "slider", "1,1,168"),
    ("source.m3u.auto_refresh", "Auto-refresh via service", "bool", None),
    ("source.m3u.group_by",     "Group by (0=auto)",      "enum",  "Auto|Title|Group"),
    # TMDB
    ("tmdb.api_key",            "TMDB API key (v3)",      "text",  None),
    ("tmdb.lang",               "TMDB language",          "text",  None),
    ("tmdb.region",             "TMDB region",            "text",  None),
    # Debrid
    ("debrid.provider",         "Active debrid (0=None)", "enum",  "None|Real-Debrid|AllDebrid|Premiumize|TorBox"),
    ("debrid.real_debrid.key",  "Real-Debrid API key",    "text",  None),
    ("debrid.all_debrid.key",   "AllDebrid API key",      "text",  None),
    ("debrid.premiumize.key",   "Premiumize API key",     "text",  None),
    ("debrid.torbox.key",       "TorBox API key",         "text",  None),
    # Trakt
    ("trakt.client_id",         "Trakt Client ID",        "text",  None),
    ("trakt.client_secret",     "Trakt Client Secret",    "text",  None),
    ("trakt.token",             "Trakt Token (JSON)",     "text",  None),
    # News
    ("news.url",                "Remote news URL",        "text",  None),
    ("news.check_hours",        "News check (hours)",     "slider", "1,1,168"),
    # Cache
    ("cache.threshold_mb",      "Cache threshold (MB)",   "slider", "50,50,5000"),
    ("cache.auto_clean",        "Auto-clean cache",       "bool",  None),
    # Repo / advanced
    ("repo.url",                "Repo URL",               "text",  None),
    # Indexers
    ("indexers.enabled",        "Indexer fallbacks",      "bool",  None),
    ("indexers.torrentio_url",  "Torrentio base URL",     "text",  None),
    ("indexers.comet_url",      "Comet base URL",         "text",  None),
    ("indexers.bitmagnet_url",  "BitMagnet base URL",     "text",  None),
    ("indexers.hide_non_cached","Hide non-cached torrents","bool",  None),
]


def settings_list(params=None):
    set_content("files")
    add_sort_method(0)
    add_item(c("gold", b("Helix Settings — click any to edit")), "", is_folder=False,
             info={"plot": "All settings are stored in addon_data and persist across Kodi restarts."})
    for key, label, kind, options in _SETTINGS:
        val = get_setting(key)
        if kind == "bool":
            disp_val = "true" if get_bool_setting(key, False) else "false"
        elif kind == "slider" or kind == "enum":
            disp_val = val or "(unset)"
        else:
            disp_val = val if val else "(unset)"
        # Mask long secrets
        if "key" in key.lower() and disp_val not in ("(unset)", "") and len(disp_val) > 8:
            disp_val = disp_val[:4] + "…" + disp_val[-4:] + "  (%d chars)" % len(val)
        display = c("white", b(label)) + c("gray", "  =  " + disp_val)
        add_item(display, url_for("dashboard_setting_edit", key=key, kind=kind, options=options or ""),
                 is_folder=True, info={"plot": "Click to edit this setting."})


def setting_edit(params=None):
    key = (params or {}).get("key")
    kind = (params or {}).get("kind", "text")
    options = (params or {}).get("options", "")
    if not key:
        notify("Helix — Dashboard", "Missing setting key.", "error", 3000)
        return
    cur = get_setting(key)
    if kind == "bool":
        # Toggle current
        new = "false" if get_bool_setting(key, False) else "true"
        set_setting(key, new)
        notify("Helix — Dashboard", "%s = %s" % (key, new), "info", 2500)
        return
    if kind in ("enum", "slider"):
        # For enum: present options. For slider: present numeric options.
        if options and "|" in options:
            choices = options.split("|")
        else:
            # slider: parse range "min,step,max" or default 1..100
            try:
                lo, step, hi = (int(x) for x in options.split(","))
                choices = [str(v) for v in range(lo, hi + 1, step)]
            except Exception:
                choices = [str(i) for i in range(0, 11)]
        sel = dialog_select("%s (current: %s)" % (key, cur or "(unset)"), choices)
        if sel < 0 or sel >= len(choices):
            return
        set_setting(key, choices[sel])
        notify("Helix — Dashboard", "%s = %s" % (key, choices[sel]), "info", 2500)
        return
    # text input
    new = dialog_input("Edit: %s" % key, cur)
    if new is None:
        return
    set_setting(key, new)
    notify("Helix — Dashboard", "%s saved." % key, "info", 2500)


# --- Actions page ---
def actions_menu(params=None):
    set_content("files")
    add_sort_method(0)
    add_item(c("orange", b("Open Helix Settings (native)")), url_for("open_settings"),
             is_folder=False, info={"plot": "Open Kodi's standard addon settings dialog."})
    add_item(c("orange", b("Force update repos")),          url_for("dashboard_action_force_update"),
             is_folder=False, info={"plot": "Run UpdateAddonRepos + UpdateLocalAddons."})
    add_item(c("orange", b("Refresh M3U now")),              url_for("dashboard_action_refresh_m3u"),
             is_folder=False, info={"plot": "Re-parse the M3U source."})
    add_item(c("lime", b("Refresh EPG / XMLTV now")),        url_for("dashboard_action_refresh_epg"),
             is_folder=False, info={"plot": "Fetch fresh XMLTV guide data from EPG URL."})
    add_item(c("orange", b("Clear Helix cache")),            url_for("dashboard_action_clear_cache"),
             is_folder=False, info={"plot": "Wipe Helix's JSON cache files."})
    add_item(c("orange", b("Run speedtest")),                url_for("dashboard_action_speedtest"),
             is_folder=False, info={"plot": "Latency + download check."})
    add_item(c("orange", b("Test TMDB key")),                url_for("dashboard_action_test_tmdb"),
             is_folder=False, info={"plot": "Hit TMDB /configuration to validate."})
    add_item(c("orange", b("Test active debrid")),           url_for("dashboard_action_test_debrid"),
             is_folder=False, info={"plot": "Hit provider /user to validate the key."})
    add_item(c("orange", b("Restart Helix service")),        url_for("dashboard_action_restart_service"),
             is_folder=False, info={"plot": "Set a sentinel — the service will exit and Kodi respawns it."})
    add_item(c("orange", b("Test Indexers")),                 url_for("dashboard_action_test_indexers"),
             is_folder=False, info={"plot": "Check connectivity for Torrentio, Comet, and BitMagnet."})
    add_item(c("orange", b("Save kodi.log to profile")),     url_for("dashboard_action_save_log"),
             is_folder=False, info={"plot": "Write the current log to addon_data/helix/logs/."})
    add_item(c("red",     b("Force close Kodi")),            url_for("force_close_kodi"),
             is_folder=False, info={"plot": "Quit Kodi (confirmation dialog)."})


def action_clear_cache():
    n = cache_clear()
    notify("Helix — Dashboard", "Cache cleared (%d files)." % n, "info", 3000)


def action_force_update():
    try:
        import xbmc
        xbmc.executebuiltin("UpdateAddonRepos")
        xbmc.executebuiltin("UpdateLocalAddons")
        notify("Helix — Dashboard", "Update triggered.", "info", 3000)
    except Exception as exc:
        notify("Helix — Dashboard", "Update failed: %s" % exc, "error", 4000)


def action_refresh_m3u():
    from . import m3u
    n = m3u.clear_cache_and_refresh()
    if n:
        notify("Helix — Dashboard", "M3U refreshed: %d groups." % len(n.get("items", [])), "info", 4000)
    else:
        notify("Helix — Dashboard", "M3U refresh returned nothing (check source).", "warn", 4000)


def action_refresh_epg():
    from . import epg
    result = epg.refresh()
    if result:
        n_ch = len(result.get("channels", {}))
        n_pg = sum(len(v) for v in result.get("programmes", {}).values())
        notify("Helix — Dashboard", "EPG refreshed: %d channels, %d programmes." % (n_ch, n_pg), "info", 4000)
    else:
        notify("Helix — Dashboard", "EPG refresh failed (check URL in Settings).", "warn", 4000)


def action_speedtest():
    from . import speedtest
    speedtest.run()


def action_test_tmdb():
    from . import tmdb
    tmdb.test_key()


def action_test_debrid():
    from . import debrid
    debrid.test_active()


def action_restart_service():
    if not yesno("Helix — Dashboard", "Restart the Helix background service?",
                 nolabel="Cancel", yeslabel="Restart"):
        return
    try:
        # Set sentinel — service_core checks for this on next tick and exits.
        with open("/tmp/.helix_service_restart", "w") as fh:
            fh.write("1")
        # Also nudge Kodi to re-evaluate the service by re-enabling the addon
        import xbmc
        xbmc.executebuiltin("EnableAddon(plugin.video.helix)")
        notify("Helix — Dashboard", "Service will restart on next tick.", "info", 4000)
    except Exception as exc:
        notify("Helix — Dashboard", "Restart request failed: %s" % exc, "error", 4000)


def action_test_indexers():
    from . import indexers
    indexers.test_indexers()


def action_save_log():
    log_export({})


def action_dump_debug():
    info = _collect_debug_info()
    gui = _collect_gui_snapshot()
    log("=== DASHBOARD DEBUG DUMP ===", "info")
    for k, v in info.items():
        log("  %s = %s" % (k, v), "info")
    log("=== GUI SNAPSHOT ===", "info")
    for k, v in gui.items():
        log("  %s = %s" % (k, v), "info")
    log("=== END DUMP ===", "info")
    notify("Helix — Dashboard", "Dumped to kodi.log.", "info", 3000)


# --- About page ---
def about(params=None):
    set_content("files")
    add_sort_method(0)
    info = _collect_debug_info()
    rows = [
        ("Helix",                "%s v%s" % (info.get("name", "Helix"), info.get("version", "?"))),
        ("Install path",         info.get("path", "")),
        ("Profile path",         info.get("profile", "")),
        ("Kodi",                 "%s (%s)" % (info.get("kodi_version", "?"), info.get("kodi_build", "?"))),
        ("Repo",                 info.get("repo_url", "")),
        ("Source",               "https://github.com/Dworrall21/kodiapp"),
        ("Provider",             "Helix / Dworrall21"),
        ("License",              "MIT"),
    ]
    add_item(c("gold", b("Helix — About")), "", is_folder=False)
    for label, val in rows:
        add_item(c("white", b(label) + ":  ") + c("gray", str(val)), "", is_folder=False,
                 info={"plot": str(val)})
    add_item(c("lightgray", "View full changelog"), url_for("dashboard_changelog"),
             is_folder=False, info={"plot": "Read the addon changelog."})


def changelog(params=None):
    addons_root = os.path.dirname(addon_info("path") or "")
    candidates = [
        os.path.join(addons_root, "changelog.txt"),
        os.path.join(addons_root, "CHANGELOG.md"),
    ]
    body = ""
    for p in candidates:
        if os.path.exists(p):
            try:
                with open(p, "r", encoding="utf-8", errors="replace") as fh:
                    body = fh.read()
                break
            except Exception:
                continue
    if not body:
        body = "No changelog found at " + ", ".join(candidates)
    text_viewer("Helix — Changelog", body)
