# -*- coding: utf-8 -*-
"""
Kodi-safe utilities.

These helpers isolate xbmc imports so the rest of the codebase can be
unit-tested in plain Python.
"""
import os
import sys
import time
import json
import hashlib
import re
from urllib.parse import parse_qs, urlparse

# Lazy xbmc imports - resolved at runtime inside Kodi only.
def _xbmc():
    import xbmc  # noqa: F401
    return sys.modules["xbmc"]


def _xbmcvfs():
    import xbmcvfs
    return xbmcvfs


def _xbmcaddon():
    import xbmcaddon
    return xbmcaddon


def _xbmcgui():
    import xbmcgui
    return xbmcgui


def _xbmcplugin():
    import xbmcplugin
    return xbmcplugin


# --- setting / addon accessor (single source of truth) ---
_addon_handle = None
_addon_obj = None
_nav_state = {
    "action": "",
    "params": {},
    "content": "",
    "visible_index": 0,
    "section": "",
    "section_visible_index": 0,
    "sort_methods": [],
    "groups": [],
    "current_group": None,
}

_ROUTE_LABELS = {
    "home": "Browse Home",
    "tools": "Tools Home",
    "movies": "Movies",
    "tv": "TV Shows",
    "anime": "Anime",
    "discover": "Discover",
    "search": "Search",
    "favorites": "Favorites",
    "list_m3u": "M3U List",
    "list_m3u_kind": "M3U Kind",
    "list_titles": "Titles",
    "list_tmdb_titles": "TMDB Titles",
    "list_tmdb_title": "TMDB Title",
    "trending": "Trending",
    "popular": "Popular",
    "genres": "Genres",
    "genre_items": "Genre Items",
    "test_indexers": "Test Indexers",
    "indexer_status": "Indexer Status",
    "play": "Play",
    "add_favorite": "Add Favorite",
    "remove_favorite": "Remove Favorite",
    "add_favorite_tmdb": "Add TMDB Favorite",
    "remove_favorite_tmdb": "Remove TMDB Favorite",
    "search_menu": "Search Filter Menu",
    "trakt_lists": "Trakt Lists",
    "trakt_list_items": "Trakt List Items",
    "trakt_sync_favorites": "Sync Trakt Favorites",
    "epg_grid": "EPG Grid",
    "epg_programmes": "EPG Programmes",
    "refresh_epg": "Refresh EPG",
    "account_manager": "Account Manager",
    "check_all_debrid": "Test All Providers",
    "trakt_revoke": "Revoke Trakt",
    "authorize_debrid": "Authorize Debrid",
    "check_debrid": "Check Debrid",
    "trakt_device": "Trakt Device Flow",
    "trakt_watchlist": "Trakt Watchlist",
    "trakt_watchlist_remove": "Remove Trakt Watchlist Item",
    "trakt_mark_watched": "Mark Watched",
    "trakt_account": "Trakt Account",
    "maintenance": "Maintenance",
    "maint_clear_packages": "Clear Packages",
    "maint_clear_thumbnails": "Clear Thumbnails",
    "maint_clear_cache": "Clear Cache",
    "maint_fresh_start": "Fresh Start",
    "maint_cache_settings": "Cache Settings",
    "backup_restore": "Backup / Restore",
    "backup_run": "Run Backup",
    "restore_run": "Run Restore",
    "backup_set_folder": "Set Backup Folder",
    "backup_reset_folder": "Reset Backup Folder",
    "speedtest": "Speedtest",
    "view_logs": "View Logs",
    "force_update": "Force Update",
    "force_close_kodi": "Force Close Kodi",
    "whitelist": "Whitelist",
    "whitelist_add": "Whitelist Add",
    "whitelist_remove": "Whitelist Remove",
    "notifications": "Notifications",
    "tools_menu": "Tools Submenu",
    "refresh_m3u": "Refresh M3U",
    "test_tmdb": "Test TMDB",
    "test_debrid": "Test Debrid",
    "dashboard": "Dashboard",
    "dashboard_debug": "Dashboard Debug",
    "dashboard_logs": "Dashboard Logs",
    "dashboard_log_view": "Dashboard Log View",
    "dashboard_log_filter": "Dashboard Log Filter",
    "dashboard_log_export": "Dashboard Log Export",
    "dashboard_log_path": "Dashboard Log Path",
    "dashboard_settings": "Dashboard Settings",
    "dashboard_setting_edit": "Dashboard Setting Edit",
    "dashboard_actions": "Dashboard Actions",
    "dashboard_action_clear_cache": "Dashboard Clear Cache",
    "dashboard_action_force_update": "Dashboard Force Update",
    "dashboard_action_refresh_m3u": "Dashboard Refresh M3U",
    "dashboard_action_refresh_epg": "Dashboard Refresh EPG",
    "dashboard_action_speedtest": "Dashboard Speedtest",
    "dashboard_action_test_tmdb": "Dashboard Test TMDB",
    "dashboard_action_test_debrid": "Dashboard Test Debrid",
    "dashboard_action_restart_service": "Dashboard Restart Service",
    "dashboard_action_save_log": "Dashboard Save Log",
    "dashboard_action_dump_debug": "Dashboard Dump Debug",
    "dashboard_about": "Dashboard About",
    "dashboard_changelog": "Dashboard Changelog",
}


def get_addon():
    """Return the live xbmcaddon.Addon() instance (cached)."""
    global _addon_obj
    if _addon_obj is None:
        _addon_obj = _xbmcaddon().Addon()
    return _addon_obj


def get_setting(key, default=""):
    """Safe setting getter with fallback default."""
    try:
        v = get_addon().getSetting(key)
        return v if v else default
    except Exception:
        return default


def set_setting(key, value):
    try:
        get_addon().setSetting(key, str(value))
        return True
    except Exception:
        return False


def get_int_setting(key, default=0):
    try:
        return int(float(get_setting(key, str(default))))
    except Exception:
        return default


def get_bool_setting(key, default=False):
    v = get_setting(key, "false" if not default else "true").lower()
    return v in ("true", "1", "yes", "on")


# --- handle / content helpers ---
def set_handle(handle):
    global _addon_handle
    _addon_handle = handle


def get_handle():
    return _addon_handle or 0


def _strip_kodi_markup(text):
    """Best-effort cleanup for Kodi markup so logs stay readable."""
    if text is None:
        return ""
    s = str(text)
    s = re.sub(r"\[/?B\]", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\[/?I\]", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\[/?U\]", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\[COLOR(?: [^\]]+)?\]", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\[/COLOR\]", "", s, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", s).strip()


def _shorten(text, limit=140):
    text = _strip_kodi_markup(text)
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def _describe_url(url):
    if not url:
        return {"kind": "none", "route": "", "params": {}}
    if not str(url).startswith("plugin://"):
        return {"kind": "external", "route": "", "params": {}, "url": _shorten(url, 180)}
    try:
        q = urlparse(url).query
        params = parse_qs(q, keep_blank_values=True)
        flat = {k: (v[0] if len(v) == 1 else v) for k, v in params.items()}
        return {
            "kind": "plugin",
            "route": flat.get("action", ""),
            "params": {k: v for k, v in flat.items() if k != "action"},
            "url": _shorten(url, 180),
        }
    except Exception:
        return {"kind": "plugin", "route": "", "params": {}, "url": _shorten(url, 180)}


def _page_label(action, content=""):
    label = _ROUTE_LABELS.get(action, "") or str(action or "").replace("_", " ").strip().title()
    content = _shorten(content, 80)
    if content and content.lower() != label.lower():
        return "%s (%s)" % (label, content)
    return label


def _match_nav_selection(action, params=None):
    """Best-effort match for currently selected item on previous page."""
    params = dict(params or {})
    state = _nav_state
    groups = state.get("groups", []) or []
    for group in groups:
        items = group.get("items", []) or []
        for item in items:
            if not isinstance(item, dict):
                continue
            if item.get("route", "") != (action or ""):
                continue
            if dict(item.get("params", {}) or {}) != params:
                continue
            row_index = int(item.get("visible_index", 0) or 0)
            section_row_index = int(item.get("section_visible_index", 0) or 0)
            selected_label = item.get("label", "")
            return {
                "matched": True,
                "parent_page": _page_label(state.get("action", ""), state.get("content", "")),
                "group_label": group.get("label", ""),
                "group_kind": group.get("kind", ""),
                "row_index": row_index,
                "section_row_index": section_row_index,
                "focus_row": row_index,
                "focus_label": selected_label,
                "selected_label": selected_label,
            }
    return {
        "matched": False,
        "parent_page": _page_label(state.get("action", ""), state.get("content", "")),
        "group_label": "",
        "group_kind": "",
        "row_index": 0,
        "section_row_index": 0,
        "focus_row": 0,
        "focus_label": "",
        "selected_label": "",
    }


def _preview_mapping(mapping, limit=8, value_limit=80):
    if not isinstance(mapping, dict) or not mapping:
        return ""
    parts = []
    for idx, (key, value) in enumerate(mapping.items()):
        if idx >= limit:
            parts.append("…")
            break
        if value in (None, "", [], {}, ()):
            continue
        parts.append("%s=%s" % (key, _shorten(value, value_limit)))
    return ", ".join(parts)


def nav_snapshot():
    snap = dict(_nav_state)
    snap["breadcrumb"] = nav_breadcrumb()
    return snap


def _log_gui_snapshot(prefix="nav.gui"):
    """Best-effort live GUI snapshot for testing and log-based navigation."""
    try:
        xbmc = _xbmc()
    except Exception:
        return

    labels = [
        ("system.time", "System.Time"),
        ("system.date", "System.Date"),
        ("system.window", "System.CurrentWindow"),
        ("system.control", "System.CurrentControl"),
        ("system.build", "System.BuildVersion"),
        ("system.build_date", "System.BuildDate"),
        ("system.os", "System.OSVersionInfo"),
        ("system.platform", "System.Platform"),
        ("system.cpu", "System.CpuUsage"),
        ("system.free_mem", "System.FreeMemory"),
        ("system.screen_w", "System.ScreenWidth"),
        ("system.screen_h", "System.ScreenHeight"),
        ("container.path", "Container.FolderPath"),
        ("container.content", "Container.Content"),
        ("container.num_items", "Container.NumItems"),
        ("container.position", "Container.Position"),
        ("container.current_item", "Container.CurrentItem"),
        ("container.view_mode", "Container.ViewMode"),
        ("container.sort_method", "Container.SortMethod"),
        ("container.folder_name", "Container.FolderName"),
        ("item.label", "Container.ListItem.Label"),
        ("item.label2", "Container.ListItem.Label2"),
        ("item.path", "Container.ListItem.Path"),
        ("item.title", "Container.ListItem.Title"),
        ("item.plot", "Container.ListItem.Plot"),
        ("item.is_playable", "Container.ListItem.Property(IsPlayable)"),
        ("item.is_folder", "Container.ListItem.Property(IsFolder)"),
        ("item.mimetype", "Container.ListItem.Property(mimetype)"),
        ("item.thumb", "Container.ListItem.Art(thumb)"),
    ]
    out = {}
    for key, label in labels:
        try:
            value = xbmc.getInfoLabel(label) or ""
        except Exception:
            value = ""
        if value:
            out[key] = _shorten(value, 180)
    if out:
        log("%s %s" % (prefix, _preview_mapping(out, limit=32, value_limit=180)), "debug")


def nav_begin(action, params=None):
    """Reset navigation context for a new Kodi directory render."""
    global _nav_state
    _nav_state = {
        "action": action or "",
        "params": dict(params or {}),
        "content": "",
        "visible_index": 0,
        "section": "",
        "section_visible_index": 0,
        "sort_methods": [],
        "groups": [],
        "current_group": None,
    }
    log("nav.begin action=%r params=%s" % (_nav_state["action"], _nav_state["params"]), "debug")


def nav_end(succeeded=True, update_listing=False):
    state = _nav_state
    log(
        "nav.end action=%r content=%r section=%r visible=%d section_visible=%d succeeded=%s updateListing=%s"
        % (
            state.get("action", ""),
            state.get("content", ""),
            state.get("section", ""),
            state.get("visible_index", 0),
            state.get("section_visible_index", 0),
            succeeded,
            update_listing,
        ),
        "debug",
    )
    crumb = nav_breadcrumb()
    if crumb:
        log("nav.breadcrumb action=%r path=%s" % (state.get("action", ""), crumb), "debug")
    _log_gui_snapshot()


def nav_breadcrumb():
    """Compact one-line breadcrumb summary for current menu."""
    groups = _nav_state.get("groups", []) or []
    parts = []
    for g in groups:
        label = g.get("label", "").strip() or "(unnamed)"
        items = g.get("items", []) or []
        labels = []
        for item in items:
            if isinstance(item, dict):
                labels.append(_shorten(item.get("label", ""), 60))
            else:
                labels.append(_shorten(item, 60))
        if not items:
            parts.append(label)
            continue
        if len(labels) <= 4:
            parts.append("%s[%d]: %s" % (label, len(labels), ", ".join(labels)))
        else:
            parts.append("%s[%d]: %s … %s" % (label, len(labels), ", ".join(labels[:3]), labels[-1]))
    return " > ".join(parts)


def nav_select(action, params=None):
    """Log the selected route/label when Kodi opens a new page."""
    params = dict(params or {})
    label = _ROUTE_LABELS.get(action, "") or action.replace("_", " ").strip().title()
    selection = _match_nav_selection(action, params)
    route_info = "action=%r label=%r parent_page=%r row_index=%r section_row_index=%r focus_row=%r focus_label=%r selected_label=%r params=%s" % (
        action,
        label,
        selection.get("parent_page", ""),
        selection.get("row_index", 0),
        selection.get("section_row_index", 0),
        selection.get("focus_row", selection.get("row_index", 0)),
        selection.get("focus_label", selection.get("selected_label", "")),
        selection.get("selected_label", ""),
        params,
    )
    if selection.get("group_label"):
        route_info += " group=%r group_kind=%r matched=%s" % (
            selection.get("group_label", ""),
            selection.get("group_kind", ""),
            selection.get("matched", False),
        )
    breadcrumb = nav_breadcrumb()
    if breadcrumb:
        route_info += " breadcrumb=%s" % breadcrumb
    log("nav.select %s" % route_info, "info")


def end_of_directory(succeeded=True, update_listing=False):
    try:
        nav_end(succeeded=succeeded, update_listing=update_listing)
        _xbmcplugin().endOfDirectory(get_handle(), succeeded=succeeded, updateListing=update_listing)
    except Exception:
        pass


def set_content(content):
    _nav_state["content"] = content or ""
    log("nav.content action=%r content=%r" % (_nav_state.get("action", ""), content), "debug")
    try:
        _xbmcplugin().setContent(get_handle(), content)
    except Exception:
        pass


def add_sort_method(sort):
    try:
        _nav_state.setdefault("sort_methods", []).append(sort)
    except Exception:
        pass
    log("nav.sort action=%r sort=%r" % (_nav_state.get("action", ""), sort), "debug")
    try:
        _xbmcplugin().addSortMethod(get_handle(), sort)
    except Exception:
        pass


# --- path / url helpers ---
def translate_path(path):
    if path.startswith("special://"):
        try:
            return _xbmcvfs().translatePath(path)
        except Exception:
            return path
    return path


def addon_info(name):
    """name in: id, name, version, profile, path, icon, fanart"""
    try:
        a = get_addon()
        return {
            "id": a.getAddonInfo("id"),
            "name": a.getAddonInfo("name"),
            "version": a.getAddonInfo("version"),
            "profile": translate_path(a.getAddonInfo("profile")),
            "path": translate_path(a.getAddonInfo("path")),
            "icon": a.getAddonInfo("icon"),
            "fanart": a.getAddonInfo("fanart"),
        }.get(name, "")
    except Exception:
        return ""


def addon_profile_path(*parts):
    base = addon_info("profile") or os.path.join("/tmp", "helix_profile")
    if not os.path.isdir(base):
        try:
            os.makedirs(base)
        except Exception:
            pass
    return os.path.join(base, *parts) if parts else base


# --- logging ---
def log(msg, level="info"):
    try:
        xbmc = _xbmc()
        level_map = {
            "debug": xbmc.LOGDEBUG,
            "info": xbmc.LOGINFO,
            "warn": xbmc.LOGWARNING,
            "error": xbmc.LOGERROR,
        }
        xbmc.log("[Helix] " + str(msg), level_map.get(level, xbmc.LOGINFO))
    except Exception:
        print("[Helix] " + str(msg))


# --- URL builders ---
def build_url(action=None, **kwargs):
    """Build a plugin://... URL with query params (dict-friendly)."""
    from urllib.parse import urlencode
    params = {}
    if action is not None:
        params["action"] = action
    params.update({k: v for k, v in kwargs.items() if v is not None})
    return "plugin://" + ADDON_ID + "/?" + urlencode(params)


ADDON_ID = "plugin.video.helix"


def url_for(action, **kwargs):
    return build_url(action, **kwargs)


# --- common url parsing helpers ---
def parse_query(qs):
    """Parse a query string ('a=b&c=d') into a dict (values are str)."""
    from urllib.parse import parse_qs
    out = {}
    for k, v in parse_qs(qs, keep_blank_values=True).items():
        out[k] = v[0] if len(v) == 1 else v
    return out


# --- hashing / id helpers ---
def short_id(*parts, length=10):
    h = hashlib.sha1("|".join(str(p) for p in parts).encode("utf-8")).hexdigest()
    return h[:length]


# --- string cleanup ---
def clean_title(s):
    if s is None:
        return ""
    s = str(s)
    s = re.sub(r"[\s.\-_]+", " ", s)
    s = re.sub(r"\[[^\]]*\]", "", s)
    s = re.sub(r"\([^)]*\)", "", s)
    return s.strip()


# --- simple cache helpers ---
def cache_get(key, ttl_seconds=300):
    """JSON cache file in addon profile dir, with TTL."""
    p = addon_profile_path("cache", short_id(key, length=20) + ".json")
    if not os.path.exists(p):
        return None
    try:
        age = time.time() - os.path.getmtime(p)
        if age > ttl_seconds:
            return None
        with open(p, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return None


def cache_set(key, value):
    p = addon_profile_path("cache", short_id(key, length=20) + ".json")
    try:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as fh:
            json.dump(value, fh)
        return True
    except Exception:
        return False


def cache_clear():
    base = addon_profile_path("cache")
    if not os.path.isdir(base):
        return 0
    n = 0
    for f in os.listdir(base):
        try:
            os.unlink(os.path.join(base, f))
            n += 1
        except Exception:
            pass
    return n


# --- toast / dialog ---
def notify(title, message, level="info", duration_ms=4000):
    levels = {
        "info": _xbmcgui().NOTIFICATION_INFO,
        "warn": _xbmcgui().NOTIFICATION_WARNING,
        "error": _xbmcgui().NOTIFICATION_ERROR,
    }
    try:
        _xbmcgui().Dialog().notification(title, message, addon_info("icon"), duration_ms, levels.get(level, levels["info"]))
    except Exception:
        pass


def yesno(title, message, nolabel="No", yeslabel="Yes"):
    try:
        return _xbmcgui().Dialog().yesno(title, message, nolabel=nolabel, yeslabel=yeslabel)
    except Exception:
        return False


def text_viewer(title, body):
    try:
        _xbmcgui().Dialog().textviewer(title, body)
    except Exception:
        notify(title, body[:200] + ("..." if len(body) > 200 else ""))


def dialog_select(title, options):
    try:
        return _xbmcgui().Dialog().select(title, options)
    except Exception:
        return -1


def dialog_input(title, default=""):
    try:
        kb = _xbmcgui().Dialog().input(title, default)
        return kb or ""
    except Exception:
        return ""


# --- list item builder ---
def make_item(label, url=None, is_folder=True, info=None, art=None, properties=None, context=None, mime=None):
    """Build a xbmcgui.ListItem (the unit Kodi shows in a directory)."""
    li = _xbmcgui().ListItem(label=label)
    if info:
        li.setInfo("video", info) if "video" in str(info) or any(k in info for k in ("title", "plot", "year", "genre", "rating", "duration", "season", "episode", "tvshowtitle", "mediatype")) else li.setInfo("general", info)
    if art:
        li.setArt(art)
    if properties:
        for k, v in properties.items():
            li.setProperty(k, str(v))
    if context:
        li.addContextMenuItems(context)
    if not is_folder and url:
        li.setPath(url)
        if mime:
            li.setMimeType(mime)
    elif is_folder and url:
        li.setPath(url)
    return li


def add_item(label, url=None, is_folder=True, info=None, art=None, properties=None, context=None, mime=None):
    """Add a list item to the current plugin handle."""
    raw_label = _strip_kodi_markup(label)
    desc = _describe_url(url)
    _nav_state["visible_index"] = int(_nav_state.get("visible_index", 0)) + 1
    visible_index = _nav_state["visible_index"]
    kind = "item"
    if raw_label.startswith("─── ") and raw_label.endswith(" ───"):
        kind = "section"
        _nav_state["section"] = raw_label[4:-4].strip()
        _nav_state["section_visible_index"] = 0
        _nav_state["groups"].append({"label": _nav_state["section"], "kind": "section", "items": []})
        _nav_state["current_group"] = _nav_state["groups"][-1]
    elif raw_label in (">>> SWITCH TO TOOLS <<<", ">>> SWITCH TO BROWSE <<<"):
        kind = "switch"
        _nav_state["section"] = raw_label.replace(">>>", "").replace("<<<", "").strip()
        _nav_state["section_visible_index"] = 0
        _nav_state["groups"].append({"label": _nav_state["section"], "kind": "switch", "items": []})
        _nav_state["current_group"] = _nav_state["groups"][-1]
    else:
        _nav_state["section_visible_index"] = int(_nav_state.get("section_visible_index", 0)) + 1
        if _nav_state.get("current_group") is None:
            fallback = _nav_state.get("action", "ROOT") or "ROOT"
            _nav_state["groups"].append({"label": fallback, "kind": "page", "items": []})
            _nav_state["current_group"] = _nav_state["groups"][-1]
        try:
            _nav_state["current_group"].setdefault("items", []).append({
                "label": raw_label,
                "kind": kind,
                "visible_index": visible_index,
                "section_visible_index": _nav_state.get("section_visible_index", 0),
                "route": desc.get("route", ""),
                "params": desc.get("params", {}),
            })
        except Exception:
            pass

    plot = ""
    try:
        plot = info.get("plot", "") if isinstance(info, dict) else ""
    except Exception:
        plot = ""
    art_hint = ""
    try:
        if isinstance(art, dict):
            art_hint = ", ".join("%s=%s" % (k, _strip_kodi_markup(v)) for k, v in art.items() if v)
    except Exception:
        art_hint = ""
    info_hint = _preview_mapping(info, limit=10, value_limit=120)
    prop_hint = _preview_mapping(properties, limit=10, value_limit=120)
    log(
        "nav.item action=%r content=%r visible=%d section=%r section_visible=%d kind=%s label=%r folder=%s route=%r params=%s url=%r info=%r plot=%r art=%r properties=%r"
        % (
            _nav_state.get("action", ""),
            _nav_state.get("content", ""),
            visible_index,
            _nav_state.get("section", ""),
            _nav_state.get("section_visible_index", 0),
            kind,
            raw_label,
            bool(is_folder),
            desc.get("route", ""),
            desc.get("params", {}),
            desc.get("url", url or ""),
            _shorten(info_hint, 220),
            _shorten(plot, 220),
            _shorten(art_hint, 180),
            _shorten(prop_hint, 220),
        ),
        "info",
    )
    li = make_item(label, url, is_folder, info, art, properties, context, mime)
    ok = True
    try:
        _xbmcplugin().addDirectoryItem(get_handle(), url or "", li, isFolder=is_folder)
    except Exception as exc:
        log("add_item failed: %r" % exc, "error")
        ok = False
    return ok


def resolve_item(li):
    try:
        _xbmcplugin().setResolvedUrl(get_handle(), True, li)
    except Exception as e:
        log("setResolvedUrl failed: %r" % e, "error")


def play_url(url, listitem=None):
    """Hand a URL to the Kodi player."""
    try:
        pl = _xbmcplugin().Player()
        if listitem is not None:
            pl.play(url, listitem)
        else:
            pl.play(url)
    except Exception:
        try:
            _xbmcplayer = _xbmcplugin()
            _xbmcplayer.setResolvedUrl(get_handle(), True, make_item("Stream", url, is_folder=False))
        except Exception as e:
            log("play_url fallback failed: %r" % e, "error")
