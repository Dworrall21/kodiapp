# -*- coding: utf-8 -*-
"""
menus: builds the on-screen directory listings.

Browse home (POV-style):
    Movies | TV Shows | Anime | Discover | Search | Favorites
    Top bar: "Switch to Tools"

Results architecture — debrid-first, M3U fallback:
    For category browse (Movies/TV/Anime):
        1. Debrid Sources section (TMDB discover categories)
        2. Live TV / M3U section (M3U groups at bottom)

    For search:
        1. TMDB results (link to debrid-cached streams with quality badges)
        2. Live TV / M3U section (M3U match groups at bottom)

    For TMDB title detail:
        1. Quality-grouped debrid streams (with green cached badges)
        2. Live TV / M3U section at bottom
"""
from .utils import (
    add_item, url_for, log, notify, get_setting, get_int_setting, addon_info,
    set_content, add_sort_method, play_url, make_item, resolve_item,
    dialog_input, cache_get, cache_set,
)
from .modules.colors import c, b, i
from . import m3u
from . import tmdb
from . import debrid
from . import debrid_search
from . import epg
from . import trakt
import xbmcplugin

SORT_LABEL = xbmcplugin.SORT_METHOD_LABEL
SORT_TITLE = xbmcplugin.SORT_METHOD_TITLE
SORT_DATE = xbmcplugin.SORT_METHOD_DATE

# --- top / bottom bars ---

def _topbar():
    """First item: a non-folder link to switch context."""
    add_item(
        c("gold", b(">>> SWITCH TO TOOLS <<<")),
        url_for("tools"),
        is_folder=True,
        info={"plot": "Open the maintenance toolkit (Account Manager, Maintenance, Backup/Restore, Tools)."},
    )


def _bottombar():
    add_item(
        c("gold", b(">>> SWITCH TO BROWSE <<<")),
        url_for("home"),
        is_folder=True,
        info={"plot": "Open the browse experience (Movies, TV, Anime, Discover, Search, Favorites)."},
    )


def _browse_status():
    """A small status line that shows M3U count + active debrid."""
    src = m3u.get_cached_source()
    n_items = len(src.get("items", [])) if src else 0
    active = debrid.active_provider_name() or "None"
    src_url = get_setting("source.m3u.url") or get_setting("source.m3u.local") or "(no source)"
    add_item(
        c("gray", "[%d items]  [debrid: %s]  [source: %s]" % (n_items, active, _shorten(src_url, 60))),
        url_for("refresh_m3u"),
        is_folder=False,
        info={"plot": "Click to refresh the M3U source."},
    )


def _shorten(s, n):
    s = s or ""
    if len(s) <= n:
        return s
    return s[: n - 1] + "…"


def _fmt_size(size_mb):
    """Format size in MB to a human string."""
    if size_mb >= 1024:
        return "%.1f GB" % (size_mb / 1024.0)
    if size_mb > 0:
        return "%d MB" % size_mb
    return "?"


# --- section separators ---

def _section_header(label):
    """Render a non-interactive section divider."""
    add_item(
        c("dimgray", b("─── %s ───" % label)),
        "",
        is_folder=False,
        info={"plot": ""},
    )


# --- tools / home menus (unchanged) ---

def tools_submenu():
    set_content("files")
    add_sort_method(SORT_LABEL)
    add_item(c("orange", b("Speedtest")),        url_for("speedtest"),       is_folder=False, info={"plot": "Run a quick latency + download check."})
    add_item(c("orange", b("View Logs")),        url_for("view_logs"),       is_folder=False, info={"plot": "Tail the most recent kodi.log."})
    add_item(c("orange", b("Force Update")),     url_for("force_update"),    is_folder=False, info={"plot": "Trigger Kodi's addon repo update."})
    add_item(c("orange", b("Force Close Kodi")), url_for("force_close_kodi"),is_folder=False, info={"plot": "Quit Kodi."})
    add_item(c("orange", b("Whitelist")),        url_for("whitelist"),       is_folder=True,  info={"plot": "Manage the addon-ID whitelist."})


def browse_home(params=None):
    """Browse home: logical grouping — browse, discover, manage."""
    set_content("files")
    add_sort_method(SORT_LABEL)

    _topbar()
    _browse_status()

    _section_header("Browse")
    add_item(c("deepskyblue", b("Movies")), url_for("movies"), is_folder=True,
             info={"plot": "Browse movies from TMDB + debrid, with M3U fallback."},
             art={"icon": "icons/movies.png"})
    add_item(c("deepskyblue", b("TV Shows")), url_for("tv"), is_folder=True,
             info={"plot": "Browse TV shows from TMDB + debrid, with M3U fallback."},
             art={"icon": "icons/tv.png"})
    add_item(c("deepskyblue", b("Anime")), url_for("anime"), is_folder=True,
             info={"plot": "Browse anime from TMDB + debrid, with M3U fallback."},
             art={"icon": "icons/anime.png"})

    _section_header("Discover")
    add_item(c("deepskyblue", b("Trending")), url_for("trending"), is_folder=True,
             info={"plot": "Trending content across movies and TV — from TMDB and Trakt."},
             art={"icon": "icons/trending.png"})
    add_item(c("deepskyblue", b("Popular")), url_for("popular"), is_folder=True,
             info={"plot": "Popular movies and TV shows — from TMDB and Trakt."},
             art={"icon": "icons/popular.png"})
    add_item(c("deepskyblue", b("Genres")), url_for("genres"), is_folder=True,
             info={"plot": "Browse by genre — Movies and TV shows."},
             art={"icon": "icons/genres.png"})
    add_item(c("deepskyblue", b("Discover")), url_for("discover"), is_folder=True,
             info={"plot": "Trending and recommended content from TMDB."},
             art={"icon": "icons/discover.png"})

    _section_header("Search")
    add_item(c("white", b("Search")), url_for("search"), is_folder=True,
             info={"plot": "Search movies, TV, anime across TMDB + Trakt + M3U with debrid cache badges."},
             art={"icon": "icons/search.png"})

    _section_header("Library")
    add_item(c("white", b("Favorites")), url_for("favorites"), is_folder=True,
             info={"plot": "Your saved items."}, art={"icon": "icons/favorites.png"})
    if trakt.has_token():
        add_item(c("orchid", b("Trakt Watchlist")), url_for("trakt_watchlist"), is_folder=True,
                 info={"plot": "Your Trakt watchlist — movies and shows."}, art={"icon": "icons/trakt.png"})

    _section_header("Settings & Tools")
    add_item(c("lightgray", "Helix Settings…"), url_for("open_settings"), is_folder=False,
             info={"plot": "Configure M3U source, TMDB, debrid, news, cache."})
    add_item(c("orchid", b("Dashboard")), url_for("dashboard"), is_folder=True,
             info={"plot": "Debug info, logs, settings editor, and quick actions."},
             art={"icon": "icons/dashboard.png"})

    if trakt.is_authorized():
        add_item(c("orchid", b("Trakt Account")), url_for("trakt_account"), is_folder=False,
                 info={"plot": "Show Trakt account status and authorization."})


def tools_home(params=None):
    """Tools home: utilities organized by category."""
    set_content("files")
    add_sort_method(SORT_LABEL)

    _bottombar()
    _section_header("Accounts")
    add_item(c("orange", b("Account Manager")), url_for("account_manager"), is_folder=True,
             info={"plot": "Authorize debrid providers (RD/AD/PM/TB) and Trakt."},
             art={"icon": "icons/account.png"})

    _section_header("Scrapers & Indexers")
    add_item(c("gold", b("Test All Indexers")), url_for("test_indexers"), is_folder=False,
             info={"plot": "Run connection tests on all configured indexers (Torrentio, Comet, BitMagnet)."},
             art={"icon": "icons/discover.png"})
    add_item(c("gold", b("Indexer Status")), url_for("indexer_status"), is_folder=False,
             info={"plot": "View current indexer configuration and health."},
             art={"icon": "icons/discover.png"})

    _section_header("Maintenance")
    add_item(c("orange", b("Maintenance")), url_for("maintenance"), is_folder=True,
             info={"plot": "Clear packages, clear thumbnails, clear cache, fresh start."},
             art={"icon": "icons/maintenance.png"})
    add_item(c("orange", b("Backup / Restore")), url_for("backup_restore"), is_folder=True,
             info={"plot": "Back up your Kodi userdata; restore from a previous backup."},
             art={"icon": "icons/backup.png"})
    add_item(c("orange", b("Tools")), url_for("tools_menu"), is_folder=True,
             info={"plot": "Speedtest, View Logs, Force Update, Force Close, Whitelist."},
             art={"icon": "icons/tools.png"})
    add_item(c("orange", b("Notifications")), url_for("notifications"), is_folder=True,
             info={"plot": "Read the latest announcement from the maintainer."})

    _section_header("Settings")
    add_item(c("lightgray", "Helix Settings…"), url_for("open_settings"), is_folder=False,
             info={"plot": "Configure M3U source, TMDB, debrid, indexers, news, cache."})


# =========================================================================
# Browse: category listings — debrid discover first, M3U fallback
# =========================================================================

def list_movies(params):
    """Movies: debrid discover categories + M3U groups at bottom."""
    set_content("movies")
    add_sort_method(SORT_LABEL)
    add_sort_method(SORT_TITLE)

    add_item(c("gold", b("[ Refresh M3U ]")), url_for("refresh_m3u"), is_folder=False)
    _section_header("Debrid Sources")
    _add_discover_categories("movie")

    _section_header("Live TV / M3U")
    items = m3u.get_filtered_items(kind="movie")
    for it in items:
        _render_title_item(it)


def list_tv(params):
    """TV Shows: debrid discover categories + M3U groups at bottom."""
    set_content("tvshows")
    add_sort_method(SORT_LABEL)
    add_sort_method(SORT_TITLE)

    add_item(c("gold", b("[ Refresh M3U ]")), url_for("refresh_m3u"), is_folder=False)
    _section_header("Debrid Sources")
    _add_discover_categories("tv")

    _section_header("Live TV / M3U")
    items = m3u.get_filtered_items(kind="tv")
    for it in items:
        _render_title_item(it)


def list_anime(params):
    """Anime: debrid discover categories + M3U groups at bottom."""
    set_content("tvshows")
    add_sort_method(SORT_LABEL)
    add_sort_method(SORT_TITLE)

    add_item(c("gold", b("[ Refresh M3U ]")), url_for("refresh_m3u"), is_folder=False)
    _section_header("Debrid Sources")
    _add_discover_categories("tv")

    _section_header("Live TV / M3U")
    items = m3u.get_filtered_items(kind="anime")
    for it in items:
        _render_title_item(it)


def _add_discover_categories(media_type="movie"):
    """Add TMDB discover category links that route to list_tmdb_title."""
    categories = [
        ("Trending (week)",   "trending_week"),
        ("Popular (day)",     "popular_day"),
        ("Top Rated",         "top_rated"),
        ("Now Playing",       "now_playing") if media_type == "movie" else ("Airing Today", "airing_today"),
        ("Upcoming",          "upcoming") if media_type == "movie" else ("On The Air", "on_the_air"),
    ]
    for label, kind in categories:
        if label is None:
            continue
        info = {"plot": "Browse %s from TMDB — debrid streams + M3U fallback." % kind.replace("_", " ")}
        add_item(
            c("gold", b(label)),
            url_for("list_tmdb_titles", media_type=media_type, discover_kind=kind),
            is_folder=True,
            info=info,
        )


# =========================================================================
# TMDB result listing — shows quality-grouped debrid streams + M3U at bottom
# =========================================================================

def list_tmdb_titles(params):
    """Show TMDB discover results → each item links to debrid-quality detail view.

    Built as a two-level flow:
        Level 1 (this function): TMDB discover items (posters, title, year)
        Level 2 (via list_tmdb_title): quality-grouped debrid streams + M3U
    """
    media_type = params.get("media_type", "movie")
    discover_kind = params.get("discover_kind")

    if discover_kind:
        results = _get_discover_results(media_type, discover_kind)
    else:
        # If called without discover_kind, show discover categories
        set_content("files")
        add_sort_method(SORT_LABEL)
        _add_discover_categories(media_type)
        return

    if not results:
        notify("Helix", "No results from TMDB.", "warn")
        return

    if media_type == "movie":
        set_content("movies")
    else:
        set_content("tvshows")
    add_sort_method(SORT_LABEL)
    add_sort_method(SORT_TITLE)

    for r in results:
        _render_tmdb_result_item(r, media_type)


def _get_discover_results(media_type, discover_kind):
    """Fetch TMDB discover results for the given kind."""
    if media_type == "movie":
        tmdb_kinds = {
            "trending_week": "trending_week",
            "popular_day": "popular_day",
            "top_rated": "top_rated",
            "now_playing": "now_playing",
            "upcoming": "upcoming",
        }
    else:
        tmdb_kinds = {
            "trending_week": "trending_week",
            "popular_day": "popular_day",
            "top_rated": "top_rated",
            "airing_today": "airing_today",
            "on_the_air": "on_the_air",
        }
    kind = tmdb_kinds.get(discover_kind)
    if not kind:
        return []
    return tmdb.discover(kind)


def _render_tmdb_result_item(r, media_type="movie"):
    """Render a single TMDB result as a folder that opens debrid quality view."""
    label = r.get("title") or r.get("name") or "(untitled)"
    tmdb_id = r.get("id")
    year = (r.get("release_date") or r.get("first_air_date") or "0000")[:4]

    info = {
        "title": label,
        "plot": r.get("overview", "") or "",
        "year": int(year) if year.isdigit() else 0,
        "rating": float(r.get("vote_average") or 0),
        "mediatype": "movie" if media_type == "movie" else "tvshow",
    }
    art = None
    if r.get("poster_path"):
        art = {"poster": tmdb.image(r.get("poster_path"))}

    # Check if this item is already in favorites
    favs = _load_favorites()
    is_fav = any(f.get("tmdb_id") == str(tmdb_id) for f in favs) if tmdb_id else False

    ctx = [
        (
            "Remove from Favorites" if is_fav else "Add to Favorites",
            "RunPlugin(" + url_for("remove_favorite_tmdb" if is_fav else "add_favorite_tmdb",
                                   tmdb_id=str(tmdb_id), media_type=media_type,
                                   title=label, year=year) + ")",
        ),
    ]

    add_item(
        c("white", b(label)) + c("gray", "  %s" % year if year else ""),
        url_for("list_tmdb_title", tmdb_id=str(tmdb_id), media_type=media_type),
        is_folder=True,
        info=info,
        art=art,
        context=ctx,
    )


# =========================================================================
# Title detail — quality-grouped debrid streams + M3U fallback
# =========================================================================

def list_tmdb_title(params):
    """Show quality-grouped debrid streams for a TMDB title + M3U at bottom.

    URL args:
        tmdb_id: numeric TMDB ID
        media_type: "movie" or "tv"
    """
    tmdb_id = params.get("tmdb_id")
    media_type = params.get("media_type", "movie")
    season = params.get("season")
    episode = params.get("episode")
    if not tmdb_id:
        notify("Helix", "Missing TMDB ID.", "error")
        return

    set_content("videos")
    add_sort_method(SORT_LABEL)

    # Mark-as-watched action (if Trakt is configured)
    if trakt.has_token():
        trakt_type = "movie" if media_type == "movie" else "tv"
        mark_url = url_for("trakt_mark_watched", tmdb_id=tmdb_id, media_type=trakt_type)
        add_item(
            c("lime", b("✓ Mark Watched on Trakt")),
            mark_url,
            is_folder=False,
            info={"plot": "Mark this title as watched on Trakt.tv."},
        )

    # 1. Fetch TMDB metadata for the title label
    meta = _get_tmdb_metadata(media_type, tmdb_id)
    if season is not None:
        meta["season"] = season
    if episode is not None:
        meta["episode"] = episode

    # 2. Query debrid search provider for cached streams
    grouped = debrid_search.search_by_tmdb(media_type, tmdb_id, season=season, episode=episode)

    if grouped:
        _section_header("Debrid Streams")
        # Quality tiers in display order
        for tier in ("4K", "1080p", "720p", "480p", "Other"):
            streams = grouped.get(tier)
            if not streams:
                continue
            cached_count = sum(1 for s in streams if s.get("cached"))
            _render_quality_header(tier, cached_count, len(streams))
            for s in streams:
                _render_debrid_stream(s, meta)

    # 3. M3U matches at bottom
    _render_m3u_matches_section(meta, media_type)

    # 4. If nothing at all, show notice
    if not grouped:
        title = meta.get("title") or "this title"
        add_item(
            c("gray", "(no debrid streams found for \"%s\")" % title),
            "",
            is_folder=False,
            info={"plot": "Try a different search or check your debrid provider."},
        )


def _get_tmdb_metadata(media_type, tmdb_id):
    """Fetch metadata for a single TMDB ID. Returns dict with title, year, plot, tmdb_id, media_type."""
    data = tmdb.details(media_type, tmdb_id)
    if data:
        return {
            "title": data.get("title") or data.get("name") or "",
            "year": (data.get("release_date") or data.get("first_air_date") or "")[:4],
            "plot": data.get("overview", ""),
            "tmdb_id": tmdb_id,
            "media_type": media_type,
        }
    return {"tmdb_id": tmdb_id, "media_type": media_type}


def _render_quality_header(tier, cached_count, total):
    """Quality section header with cached count."""
    badge = c("lime", " [%d cached]" % cached_count) if cached_count else ""
    add_item(
        c("white", b("── %s ──" % tier)) + c("gray", "  (%d streams)" % total) + badge,
        "",
        is_folder=False,
        info={"plot": "%s quality tier — %d streams, %d cached" % (tier, total, cached_count)},
    )


def _render_debrid_stream(stream, meta=None):
    """Render a single debrid stream as a playable item."""
    label = stream.get("name", "(stream)")
    source = stream.get("source", "?")
    size = stream.get("size_mb", 0)
    cached = stream.get("cached", False)

    # Build display label: green badge + quality + source + size
    badge = c("lime", "\u25cf ") if cached else c("gray", "\u25cb ")
    size_str = " | %.1f GB" % (size / 1024.0) if size > 1024 else (" | %d MB" % size) if size > 0 else ""
    display = badge + c("white", label) + c("gray", "  [%s%s]" % (source, size_str))

    # Build URL: infoHash → magnet → debrid resolve, or direct URL
    play_url_val = _build_play_url(stream)
    play_params = {
        "url": play_url_val,
        "cached": "1" if cached else "0",
        "tmdb_id": meta.get("tmdb_id", "") if meta else "",
        "media_type": meta.get("media_type", "movie") if meta else "movie",
    }
    if meta and meta.get("season") is not None:
        play_params["season"] = meta.get("season")
    if meta and meta.get("episode") is not None:
        play_params["episode"] = meta.get("episode")
    info = {
        "title": label,
        "size": size * 1024 * 1024 if size else 0,  # MB → bytes
        "plot": "Source: %s | Size: %s | Cached: %s" % (
            source, _fmt_size(size), "yes" if cached else "no"
        ),
    }
    add_item(
        display,
        url_for("play", **play_params),
        is_folder=False,
        info=info,
        properties={"IsPlayable": "true"},
    )


def _build_play_url(stream):
    """Build a URL for the play action from a debrid stream entry.

    Precedence:
        1. direct URL (already resolved)
        2. infoHash → magnet link
        3. fallback to empty
    """
    url = stream.get("url", "")
    if url:
        return url
    info_hash = stream.get("infoHash", "")
    if info_hash:
        # Construct magnet link
        magnet = "magnet:?xt=urn:btih:%s" % info_hash
        dn = stream.get("name", "").replace(" ", "+")
        if dn:
            magnet += "&dn=" + dn
        return magnet
    return ""


def _render_m3u_matches_section(meta, media_type):
    """Show M3U groups that match the current TMDB title at the bottom."""
    title = (meta.get("title") or "").lower()
    if not title:
        return

    all_items = m3u.get_filtered_items(kind="all")
    # Fuzzy match: M3U group title contains the TMDB title or vice versa
    matches = []
    for g in all_items:
        gt = (g.get("title") or "").lower()
        # Token overlap: any word from title appears in gt (length > 3)
        title_words = set(w for w in title.split() if len(w) > 3)
        if title_words:
            gt_words = set(gt.split())
            if title_words & gt_words:
                matches.append(g)

    if not matches:
        return

    _section_header("Live TV / M3U")
    for g in matches:
        _render_title_item(g)


# =========================================================================
# M3U title / stream helpers (shared with search results)
# =========================================================================

def _render_title_item(it):
    """A title (group) row. Opening it shows the streams under that title.

    If EPG data is available for this channel's tvg-id, now/next programme
    info is appended to the label.
    """
    label = it.get("title", "(untitled)")
    n = it.get("count", 0)
    tvg_id = it.get("tvg_id", "")
    art = {"poster": it.get("poster", ""), "fanart": it.get("backdrop", "")} if it.get("poster") else None
    info = {
        "title": label,
        "plot": it.get("plot", ""),
        "year": it.get("year", 0),
        "rating": float(it.get("rating", 0) or 0),
        "genre": it.get("genres", ""),
        "mediatype": "movie" if it.get("kind") == "movie" else "tvshow",
    }

    # EPG now/next overlay
    epg_str = ""
    if tvg_id:
        nn = epg.get_now_next(tvg_id)
        if nn["now"]:
            start = epg.epoch_to_time_str(nn["now"]["start"])
            epg_str = " %s%s %s" % (c("lime", b("Now:")), c("lime", "%s" % nn["now"]["title"]),
                                     c("gray", "  %s" % start) if start else "")
        if nn["next"]:
            nstart = epg.epoch_to_time_str(nn["next"]["start"])
            epg_str += " %s%s %s" % (c("gray", "Next:"), c("white", "%s" % nn["next"]["title"]),
                                      c("gray", "@%s" % nstart) if nstart else "")
        if nn["now"] and nn["next"]:
            info["plot"] = "Now: %s\nNext: %s\n\n%s" % (
                nn["now"]["title"], nn["next"]["title"], info.get("plot", "")
            )

    add_item(
        c("white", b(label)) + c("gray", "  (%d streams)" % n) + epg_str,
        url_for("list_titles", group=it.get("id", "")),
        is_folder=True,
        info=info,
        art=art,
        context=[(
            "Add to Favorites",
            "RunPlugin(" + url_for("add_favorite", group=it.get("id", "")) + ")",
        )] if it.get("id") else None,
    )


def list_titles(params):
    """Show all streams in an M3U group, then play the chosen one.

    If EPG data is available for the group's tvg-id, programme info is shown
    as context items above the stream list.
    """
    group_id = params.get("group")
    items = m3u.get_filtered_items(kind="all")
    group = next((g for g in items if g.get("id") == group_id), None)
    if not group:
        notify("Helix", "Group not found (refresh M3U and try again).", "warn")
        return
    set_content("videos")
    add_sort_method(SORT_LABEL)

    # EPG programme header
    tvg_id = group.get("tvg_id", "")
    if tvg_id:
        epg_data = epg.get_data()
        progs = epg_data.get("programmes", {}).get(tvg_id, [])
        now = epg.now_epoch()
        current_progs = [p for p in progs if p["start"] <= now < p["stop"]]
        if current_progs:
            p = current_progs[0]
            start = epg.epoch_to_time_str(p["start"])
            stop = epg.epoch_to_time_str(p["stop"])
            label = c("lime", b("Now: %s" % p["title"]))
            desc = p.get("desc", "")
            epg_plot = "%s - %s" % (start, stop)
            if p.get("category"):
                epg_plot += " [%s]" % p["category"]
            if p.get("sub_title"):
                epg_plot += "\n%s" % p["sub_title"]
            if desc:
                epg_plot += "\n\n%s" % desc
            add_item(
                label + c("gray", "  %s-%s" % (start, stop)),
                "",
                is_folder=False,
                info={"title": "Now: " + p["title"], "plot": epg_plot},
            )
        # Show next programme(s)
        upcoming = [p for p in progs if p["start"] > now]
        if upcoming:
            n = upcoming[0]
            nstart = epg.epoch_to_time_str(n["start"])
            nstop = epg.epoch_to_time_str(n["stop"])
            ndesc = n.get("desc", "")
            add_item(
                c("gray", b("Next: %s" % n["title"])) + c("gray", "  %s-%s" % (nstart, nstop)),
                "",
                is_folder=False,
                info={"title": "Next: " + n["title"], "plot": ndesc or ""},
            )

    for s in group.get("streams", []):
        label = s.get("name") or s.get("title") or s.get("url", "(stream)")
        # Try to find EPG for this specific stream's tvg-id
        stream_tvg = s.get("tvg_id", "") or tvg_id
        stream_epg = ""
        if stream_tvg:
            nn = epg.get_now_next(stream_tvg)
            if nn["now"]:
                stream_epg = " %s@%s" % (c("lime", nn["now"]["title"]),
                                          epg.epoch_to_time_str(nn["now"]["start"]))
        info = {
            "title": label,
            "size": int(s.get("size", 0) or 0) * 1024 * 1024,  # MB -> bytes
            "plot": "Stream: %s" % s.get("url", ""),
        }
        add_item(
            c("white", label) + stream_epg,
            url_for("play", url=s.get("url", ""), group=group_id),
            is_folder=False,
            info=info,
            properties={"IsPlayable": "true"},
        )


def list_m3u(params):
    """List all M3U groups (no category filter)."""
    set_content("files")
    add_sort_method(SORT_LABEL)
    add_sort_method(SORT_TITLE)
    # EPG / Refresh buttons
    add_item(c("lime", b("[ EPG Guide ]")), url_for("epg_grid"), is_folder=True,
             info={"plot": "Show EPG grid guide for Live TV channels (requires XMLTV URL in Settings)."})
    add_item(c("gold", b("[ Refresh EPG ]")), url_for("refresh_epg"), is_folder=False,
             info={"plot": "Fetch fresh XMLTV guide data."})
    add_item(c("gold", b("[ Refresh M3U ]")), url_for("refresh_m3u"), is_folder=False)
    all_items = m3u.get_filtered_items(kind="all")
    for it in all_items:
        _render_title_item(it)


def list_m3u_kind(params):
    """List M3U groups filtered by a specific kind from params."""
    kind = params.get("kind", "all")
    set_content("files")
    add_sort_method(SORT_LABEL)
    add_sort_method(SORT_TITLE)
    # EPG / Refresh buttons
    add_item(c("lime", b("[ EPG Guide ]")), url_for("epg_grid"), is_folder=True,
             info={"plot": "Show EPG grid guide for Live TV channels."})
    add_item(c("gold", b("[ Refresh EPG ]")), url_for("refresh_epg"), is_folder=False,
             info={"plot": "Fetch fresh XMLTV guide data."})
    items = m3u.get_filtered_items(kind=kind)
    for it in items:
        _render_title_item(it)


# =========================================================================
# EPG / XMLTV guide
# =========================================================================

def refresh_epg(params=None):
    """Force refresh of EPG XMLTV data, then return to the caller's listing."""
    quiet = bool(params and params.get("quiet"))
    epg.refresh(quiet=quiet)
    # Redirect back to M3U listing
    from . import m3u as _m3u
    list_m3u({})


def list_epg_grid(params):
    """Grid-style EPG guide view.

    Shows channels vertically with time slots across the top.
    Each channel row lists the upcoming programmes in chronological order.
    """
    hours_ahead = int(params.get("hours", "4"))
    kind = params.get("kind", "all")
    set_content("files")
    add_sort_method(SORT_LABEL)
    add_sort_method(SORT_DATE)

    # Get M3U items for channel IDs + display names
    m3u_items = m3u.get_filtered_items(kind=kind) if kind != "all_epg" else m3u.get_filtered_items(kind="all")

    # Fetch EPG grid
    channel_ids = [it.get("tvg_id", "") for it in m3u_items if it.get("tvg_id")]
    grid = epg.get_grid(hours_ahead=hours_ahead, channel_ids=channel_ids)

    if not grid["channels"]:
        # No EPG data — offer to refresh
        add_item(
            c("gray", "(no EPG data — click to refresh)"),
            url_for("refresh_epg"),
            is_folder=False,
            info={"plot": "Fetch XMLTV guide data from EPG URL."},
        )
        return

    # Show timeslot headers
    _section_header("EPG Guide — Next %d hours" % hours_ahead)

    for ch in grid["channels"]:
        # Find the matching M3U item for poster/context
        m3u_match = next((it for it in m3u_items if it.get("tvg_id") == ch["tvg_id"]), None)
        display = ch["display_name"] or (m3u_match.get("title", "") if m3u_match else ch["tvg_id"])
        display_short = _shorten(display, 50)
        art = None
        if m3u_match and m3u_match.get("poster"):
            art = {"poster": m3u_match["poster"]}

        # Build programme list with times
        prog_labels = []
        now = epg.now_epoch()
        for p in ch["programmes"]:
            start = epg.epoch_to_time_str(p["start"])
            stop = epg.epoch_to_time_str(p["stop"])
            is_now = p["start"] <= now < p["stop"]
            if is_now:
                prog_labels.append(c("lime", "%s %s" % (start, p["title"])))
            else:
                t = start or "??:??"
                prog_labels.append(c("white", "%s %s" % (t, p["title"])))

        all_progs = " | ".join(prog_labels) if prog_labels else "(no upcoming)"
        plot_parts = []
        for p in ch["programmes"][:5]:
            ts = epg.epoch_to_time_str(p["start"])
            te = epg.epoch_to_time_str(p["stop"])
            plot_parts.append("%s-%s %s" % (ts, te, p["title"]))
        plot = "\n".join(plot_parts) if plot_parts else ""

        add_item(
            c("white", b(display_short)) + c("lightgray", "  %s" % all_progs),
            url_for("list_titles", group=m3u_match.get("id", "")) if m3u_match else "",
            is_folder=bool(m3u_match),
            info={"title": display, "plot": plot},
            art=art,
        )


def list_epg_programmes(params):
    """Show all programmes for a specific channel from EPG data."""
    tvg_id = params.get("tvg_id", "")
    if not tvg_id:
        notify("Helix", "Missing tvg-id for EPG view.", "warn")
        return

    set_content("files")
    add_sort_method(SORT_LABEL)
    add_sort_method(SORT_DATE)

    data = epg.get_data()
    progs = data.get("programmes", {}).get(tvg_id, [])
    ch_info = data.get("channels", {}).get(tvg_id, {})
    now = epg.now_epoch()

    if not progs:
        add_item(c("gray", "(no EPG data for this channel)"), "", is_folder=False)
        return

    _section_header("EPG: %s" % (ch_info.get("display_name", tvg_id)))

    for p in progs:
        start = epg.epoch_to_time_str(p["start"])
        stop = epg.epoch_to_time_str(p["stop"])
        start_date = epg.epoch_to_date_str(p["start"])
        is_now = p["start"] <= now < p["stop"]
        if is_now:
            label = c("lime", b("%s %s-%s" % (start_date, start, stop))) + c("lime", "  %s" % p["title"])
        else:
            label = c("white", "%s %s-%s" % (start_date, start, stop)) + c("gray", "  %s" % p["title"])
        plot = p.get("desc", "")
        if p.get("sub_title"):
            plot = p["sub_title"] + ("\n\n" + plot if plot else "")
        if p.get("category"):
            plot = "[%s] %s" % (p["category"], plot) if plot else "[%s]" % p["category"]

        add_item(
            label,
            "",
            is_folder=False,
            info={"title": p["title"], "plot": plot or ""},
        )


def torrentio_search_results(params):
    """Render a flat list of Torrentio-scraped results."""
    # Delegates to the new debrid-search flow via TMDB ID.
    tmdb_id = params.get("tmdb_id")
    media_type = params.get("media_type", "movie")
    if tmdb_id:
        list_tmdb_title(params)
    else:
        notify("Helix", "Missing TMDB ID for torrentio search.", "warn")


# =========================================================================
# Play
# =========================================================================

def play(params):
    """Resolve and play a stream URL through debrid if configured.
    Also sends a scrobble-start to Trakt when tmdb_id is present."""
    url = params.get("url")
    if not url:
        notify("Helix", "No URL provided.", "error")
        return
    log("play: %s" % _shorten(url, 100))
    resolved = debrid.resolve(url) or url
    li = make_item("Stream", resolved, is_folder=False, info={"title": "Stream"}, art={"icon": "DefaultVideo.png"})
    li.setProperty("IsPlayable", "true")
    resolve_item(li)
    play_url(resolved, li)

    # Scrobble start if we have Trakt metadata
    tmdb_id = params.get("tmdb_id")
    media_type = params.get("media_type", "movie")
    season = params.get("season")
    episode = params.get("episode")
    if tmdb_id and trakt.has_token():
        if media_type == "tv" and season is not None and episode is not None:
            trakt.scrobble_start(media_type, tmdb_id, season, episode)
        else:
            trakt.scrobble_start(media_type, tmdb_id)


# =========================================================================
# Search / Discover / Favorites
# =========================================================================

def _tmdb_to_result(r, index):
    """Normalise a single TMDB search result into our unified result format."""
    label = r.get("title") or r.get("name") or "(untitled)"
    tmdb_id = r.get("id")
    media_type = r.get("media_type", "movie")
    if media_type == "person":
        return None
    mtype = "movie" if media_type == "movie" else "tv"
    year = (r.get("release_date") or r.get("first_air_date") or "0000")[:4]
    # Score: position-based, top result ~95, linear decay by 4 per rank
    score = max(10, 95 - index * 4)
    return {
        "_score": float(score),
        "_source": "tmdb",
        "title": label,
        "year": int(year) if year.isdigit() else 0,
        "overview": r.get("overview", "") or "",
        "rating": float(r.get("vote_average") or 0),
        "poster_path": r.get("poster_path"),
        "tmdb_id": str(tmdb_id),
        "media_type": mtype,
    }


def _trakt_to_list_trakt_results(trakt_results):
    """Convert Trakt normalised results to unified format, linking via TMDB ID."""
    out = []
    for r in trakt_results:
        if not r.get("tmdb_id") and not r.get("title"):
            continue
        # Build debrid link if we have a TMDB ID
        url_params = {}
        mt = r.get("media_type", "movie")
        if r.get("tmdb_id"):
            url_params = {"tmdb_id": str(r["tmdb_id"]), "media_type": mt}
        else:
            # No TMDB ID — make it a non-folder info item
            url_params = None
        out.append({
            "_score": float(r.get("_score", 0)),
            "_source": "trakt",
            "title": r.get("title", ""),
            "year": r.get("year", 0),
            "overview": r.get("overview", ""),
            "rating": r.get("rating", 0),
            "poster_path": r.get("poster", ""),
            "tmdb_id": str(r["tmdb_id"]) if r.get("tmdb_id") else None,
            "media_type": mt,
            "url_params": url_params,
        })
    return out


def _m3u_to_results(query, m3u_items):
    """Score M3U items against query and return unified results."""
    q_lower = query.lower()
    q_words = set(w for w in q_lower.split() if len(w) > 2)
    if not q_words:
        q_words = set(q_lower.split())
    out = []
    for g in m3u_items:
        gt = (g.get("title") or "").lower()
        if q_lower in gt:
            score = 70.0
        elif q_words & set(gt.split()):
            gt_words = set(gt.split())
            overlap = len(q_words & gt_words)
            score = 30.0 * (overlap / max(len(q_words), 1))
        else:
            continue
        out.append({
            "_score": score,
            "_source": "m3u",
            "title": g.get("title", "(untitled)"),
            "year": g.get("year", 0),
            "m3u_item": g,
        })
    return out


def _batch_check_debrid_cache(results):
    """Batch-check debrid cache for TMDB/Trakt results.
    
    Sets _cached=True/False on each result that has a tmdb_id.
    Uses debrid_search to find streams and marks cached status.
    """
    from . import debrid_search
    has_key = debrid._api_key()
    if not has_key:
        return
    for r in results:
        tmdb_id = r.get("tmdb_id")
        if not tmdb_id or r["_source"] == "m3u":
            continue
        try:
            streams = debrid_search.search(tmdb_id, r.get("media_type", "movie"))
            r["_cached"] = len(streams) > 0
        except Exception:
            r["_cached"] = False


def _render_search_result(r, cached=None):
    """Render a TMDB/Trakt unified result row (links to debrid stream view).
    
    Args:
        r: Unified result dict
        cached: Optional bool — whether debrid has cached streams for this title.
                If None, no badge shown. If True/False, shows cached/uncached badge.
    """
    title = r.get("title", "(untitled)")
    year = r.get("year", 0)
    source = r.get("_source", "tmdb")
    tmdb_id = r.get("tmdb_id")
    media_type = r.get("media_type", "movie")

    # Source badge color
    badge = {"tmdb": c("skyblue", "[TMDB] "), "trakt": c("orchid", "[Trakt] ")}.get(source, "")

    # Debrid availability badge
    avail = ""
    if cached is True:
        avail = c("ok", " ✓ Cached  ")
    elif cached is False:
        avail = c("dim-gray", " ○ Unchecked  ")

    info = {
        "title": title,
        "plot": r.get("overview", ""),
        "year": year,
        "rating": r.get("rating", 0),
        "mediatype": "movie" if media_type == "movie" else "tvshow",
    }
    art = None
    poster = r.get("poster_path") or ""
    if poster:
        if poster.startswith("http"):
            art = {"poster": poster}
        else:
            art = {"poster": tmdb.image(poster)}

    if tmdb_id:
        favs = _load_favorites()
        is_fav = any(f.get("tmdb_id") == str(tmdb_id) for f in favs) if tmdb_id else False
        ctx = [
            (
                "Remove from Favorites" if is_fav else "Add to Favorites",
                "RunPlugin(" + url_for("remove_favorite_tmdb" if is_fav else "add_favorite_tmdb",
                                       tmdb_id=str(tmdb_id), media_type=media_type,
                                       title=title, year=str(year)) + ")",
            ),
        ]
        add_item(
            avail + badge + c("white", b(title)) + (c("gray", "  %s" % year) if year else ""),
            url_for("list_tmdb_title", tmdb_id=tmdb_id, media_type=media_type),
            is_folder=True,
            info=info,
            art=art,
            context=ctx,
        )
    else:
        add_item(
            badge + c("white", title) + c("gray", "  (no TMDB ID)" if not year else "  %s" % year),
            "",
            is_folder=False,
            info=info,
            art=art,
        )


def do_search(params):
    """Multi-source search: TMDB + Trakt + M3U, merged and sorted by relevance.
    
    Accepts optional 'media_type' filter: movie, tv, anime, or empty for all.
    Results show debrid cache availability badges and release year.
    """
    media_type = params.get("media_type", "")
    q = params.get("q")
    if not q:
        prompt = "Search %s" % {"movie": "Movies", "tv": "TV Shows", "anime": "Anime"}.get(media_type, "movies & TV")
        q = dialog_input(prompt)
    if not q:
        return

    set_content("files")
    add_sort_method(SORT_LABEL)

    all_results = []
    tmdb_results = []
    trakt_results = []

    # 1a. TMDB search (filtered by media_type if set)
    tmdb_results = tmdb.search(q)
    for i, r in enumerate(tmdb_results or []):
        normalised = _tmdb_to_result(r, i)
        if not normalised:
            continue
        # Apply media_type filter
        if media_type and normalised["media_type"] != media_type:
            if media_type == "anime" and normalised.get("genre_ids") and 16 not in normalised.get("genre_ids", []):
                continue
            if media_type in ("movie", "tv") and normalised["media_type"] != media_type:
                continue
        all_results.append(normalised)

    # 1b. Trakt (only if configured)
    if trakt.is_configured():
        try:
            trakt_results = trakt.search(q)
            for tr in _trakt_to_list_trakt_results(trakt_results):
                if media_type:
                    mt = tr.get("media_type", "")
                    if media_type == "anime" and mt not in ("tv", "movie"):
                        continue
                    if media_type in ("movie", "tv") and mt != media_type:
                        continue
                all_results.append(tr)
        except Exception as exc:
            log("Trakt search failed: %r" % exc, "warn")

    # 1c. M3U (fuzzy title match)
    m3u_items = m3u.get_filtered_items(kind="all")
    all_results.extend(_m3u_to_results(q, m3u_items))

    # 2. Batch-check debrid cache for TMDB/Trakt results
    _batch_check_debrid_cache(all_results)

    # 3. Sort by score descending
    all_results.sort(key=lambda r: r["_score"], reverse=True)

    if not all_results:
        if not tmdb_results and not trakt_results:
            notify("Helix", "Search returned no results. Check:\n  1. TMDB API key in Settings\n  2. Internet connection\n  3. Try a different query", "warn", 7000)
        else:
            notify("Helix", "No results matched your filter.", "warn")
        return

    tmdb_count = sum(1 for r in all_results if r["_source"] == "tmdb")
    trakt_count = sum(1 for r in all_results if r["_source"] == "trakt")
    m3u_count = sum(1 for r in all_results if r["_source"] == "m3u")
    _section_header("Search Results — TMDB:%d  Trakt:%d  M3U:%d" % (tmdb_count, trakt_count, m3u_count))

    for r in all_results:
        if r["_source"] == "m3u":
            _render_title_item(r["m3u_item"])
        else:
            _render_search_result(r, cached=r.get("_cached"))


def _search_menu(params):
    """Search with a media-type filter step before the query prompt."""
    set_content("files")
    add_sort_method(SORT_LABEL)
    
    _section_header("Search — pick category")
    add_item(c("white", b("All")), url_for("search", media_type=""), is_folder=True,
             info={"plot": "Search all categories (movies, TV, anime)."})
    add_item(c("white", b("Movies")), url_for("search", media_type="movie"), is_folder=True,
             info={"plot": "Search movies only."})
    add_item(c("white", b("TV Shows")), url_for("search", media_type="tv"), is_folder=True,
             info={"plot": "Search TV shows only."})
    add_item(c("white", b("Anime")), url_for("search", media_type="anime"), is_folder=True,
             info={"plot": "Search anime only."})


def list_discover(params):
    """TMDB discover hub + results. Results route to debrid detail view."""
    set_content("movies")
    add_sort_method(SORT_LABEL)

    _section_header("Debrid Sources — Movies")
    _add_discover_categories("movie")

    _section_header("Debrid Sources — TV")
    _add_discover_categories("tv")

    # Check for kind param (legacy direct-discover support)
    kind = params.get("kind")
    if kind:
        results = tmdb.discover(kind)
        for r in results:
            label = r.get("title") or r.get("name")
            tmdb_id = r.get("id")
            year = (r.get("release_date") or r.get("first_air_date") or "0000")[:4]
            info = {
                "title": label,
                "plot": r.get("overview", ""),
                "year": int(year) if year.isdigit() else 0,
                "rating": float(r.get("vote_average") or 0),
            }
            art = {"poster": tmdb.image(r.get("poster_path"))} if r.get("poster_path") else None
            add_item(
                c("white", b(label or "(untitled)")) + c("gray", "  %s" % year),
                url_for("list_tmdb_title", tmdb_id=str(tmdb_id), media_type="movie"),
                is_folder=True,
                info=info,
                art=art,
            )


# =========================================================================
# Trakt Watchlist + Account
# =========================================================================

def list_trakt_watchlist(params):
    """Browse the authenticated user's Trakt watchlist."""
    set_content("files")
    add_sort_method(SORT_LABEL)

    media_type = params.get("media_type", "movies")  # "movies" or "shows"
    items = trakt.get_watchlist(media_type)

    if not items:
        add_item(c("gray", "(Trakt watchlist is empty — add items on trakt.tv)"), "", is_folder=False)
        return

    # Build a toggle between Movies and Shows
    add_item(
        c("orchid", b("Movies") if media_type == "shows" else c("dim-gray", b("Movies"))),
        url_for("trakt_watchlist", media_type="movies"),
        is_folder=True,
        info={"plot": "Show movies in your Trakt watchlist."},
    )
    add_item(
        c("orchid", b("Shows") if media_type == "movies" else c("dim-gray", b("Shows"))),
        url_for("trakt_watchlist", media_type="shows"),
        is_folder=True,
        info={"plot": "Show shows in your Trakt watchlist."},
    )
    _section_header("Watchlist — %s" % media_type.title())

    for item in items:
        label = item.get("title", "?")
        year = item.get("year", 0)
        tmdb_id = item.get("tmdb_id")
        # Build a detail view URL that opens debrid streams for this title
        tmdb_type = "movie" if media_type == "movies" else "tv"
        info = {
            "title": label,
            "year": year or 0,
            "plot": item.get("overview", ""),
            "mediatype": "movie" if media_type == "movies" else "tvshow",
        }
        add_item(
            c("white", b(label)) + c("gray", "  %s" % year if year else ""),
            url_for("list_tmdb_title", tmdb_id=str(tmdb_id), media_type=tmdb_type),
            is_folder=True,
            info=info,
            context=[(
                "Remove from Trakt Watchlist",
                "RunPlugin(" + url_for("trakt_watchlist_remove", tmdb_id=str(tmdb_id), media_type=media_type) + ")",
            )],
        )


def trakt_mark_watched(params):
    """Mark a movie or show as watched on Trakt via RunPlugin."""
    tmdb_id = params.get("tmdb_id")
    media_type = params.get("media_type", "movie")
    if not tmdb_id:
        return
    season = params.get("season")
    episode = params.get("episode")
    ok = trakt.mark_as_watched(media_type, tmdb_id, season, episode)
    if ok:
        notify("Helix", "Marked as watched on Trakt.", "info", 3000)
    else:
        notify("Helix", "Trakt mark-watched returned no changes (may already be watched).", "warn", 3000)


def list_trakt_watchlist_remove(params):
    """Remove an item from the Trakt watchlist via RunPlugin action."""
    tmdb_id = params.get("tmdb_id")
    media_type = params.get("media_type", "movies")
    if not tmdb_id:
        return
    ok = trakt.remove_from_watchlist(media_type, tmdb_id)
    if ok:
        notify("Helix", "Removed from Trakt watchlist.", "info", 3000)
        import xbmc
        xbmc.executebuiltin("Container.Refresh")
    else:
        notify("Helix", "Failed to remove from Trakt watchlist.", "warn", 3000)


def trakt_account(params):
    """Show Trakt account info: authorization status, token age."""
    cid = get_setting("trakt.client_id", "")
    token_raw = get_setting("trakt.token", "")
    lines = []
    lines.append("[B]Client ID:[/B] %s" % (cid[:8] + "..." if len(cid) > 8 else "(not set)"))
    if token_raw:
        import time
        try:
            import json
            token_info = json.loads(token_raw)
            created = token_info.get("created_at", 0)
            age_days = int((time.time() - created) / 86400) if created else 0
            lines.append("[B]Access token:[/B] set (%d days old)" % age_days)
            lines.append("[B]Refresh token:[/B] %s" % ("set" if token_info.get("refresh_token") else "missing"))
        except Exception:
            lines.append("[B]Access token:[/B] stored (invalid JSON)")
    else:
        lines.append("[B]Access token:[/B] not set — run Trakt Device Flow from Account Manager")
    text = "\n".join(lines)

    from .utils import text_viewer
    text_viewer("Helix — Trakt Account", text)


def list_favorites(params):
    set_content("files")
    add_sort_method(SORT_LABEL)
    favs = _load_favorites()
    if not favs:
        add_item(c("gray", "(no favorites yet — long-press a title to add)"), "", is_folder=False)
        return
    for fav in favs:
        info = {
            "title": fav.get("title"),
            "plot": fav.get("plot", ""),
            "year": fav.get("year", 0),
        }
        tmdb_id = fav.get("tmdb_id")
        if tmdb_id:
            # TMDB item — link to debrid stream view
            mtype = "tv" if fav.get("media_type") in ("tv", "show") else "movie"
            url = url_for("list_tmdb_title", tmdb_id=str(tmdb_id), media_type=mtype)
            ctx = [(
                "Remove from Favorites",
                "RunPlugin(" + url_for("remove_favorite_tmdb", tmdb_id=str(tmdb_id)) + ")",
            )]
        else:
            # M3U group item
            url = url_for("list_titles", group=fav.get("id", ""))
            ctx = [(
                "Remove from Favorites",
                "RunPlugin(" + url_for("remove_favorite", group=fav.get("id", "")) + ")",
            )]
        add_item(
            c("white", b(fav.get("title") or "(untitled)")),
            url,
            is_folder=True,
            info=info,
            context=ctx,
        )


# --- favorites: stored as JSON in addon profile ---
_FAV_PATH = None
def _fav_path():
    global _FAV_PATH
    if _FAV_PATH is None:
        _FAV_PATH = addon_info("profile")
        if not _FAV_PATH:
            _FAV_PATH = "/tmp/helix_profile"
        import os
        try:
            os.makedirs(_FAV_PATH, exist_ok=True)
        except Exception:
            pass
        _FAV_PATH = os.path.join(_FAV_PATH, "favorites.json")
    return _FAV_PATH


def _load_favorites():
    import os, json
    p = _fav_path()
    if not os.path.exists(p):
        return []
    try:
        with open(p, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return []


def _save_favorites(items):
    import os, json
    with open(_fav_path(), "w", encoding="utf-8") as fh:
        json.dump(items, fh, ensure_ascii=False, indent=2)


def add_favorite(params):
    import json
    group_id = params.get("group")
    if not group_id:
        return
    items = m3u.get_filtered_items(kind="all")
    g = next((g for g in items if g.get("id") == group_id), None)
    if not g:
        notify("Helix", "Could not add favorite (group missing).", "warn")
        return
    favs = _load_favorites()
    if not any(f.get("id") == group_id for f in favs):
        favs.append({
            "id": group_id,
            "title": g.get("title"),
            "plot": g.get("plot", ""),
            "year": g.get("year", 0),
        })
        _save_favorites(favs)
        notify("Helix", "Added: " + (g.get("title") or ""), "info", 2500)


def remove_favorite(params):
    group_id = params.get("group")
    if not group_id:
        return
    favs = _load_favorites()
    favs = [f for f in favs if f.get("id") != group_id]
    _save_favorites(favs)
    notify("Helix", "Removed.", "info", 2000)


# =========================================================================
# TMDB Favorites — add/remove items by TMDB ID (from browse/search)
# =========================================================================


def add_favorite_tmdb(params):
    """Add a TMDB item to favorites."""
    tmdb_id = params.get("tmdb_id")
    if not tmdb_id:
        return
    # Build entry from params
    fav = {
        "id": "tmdb_%s" % tmdb_id,
        "tmdb_id": tmdb_id,
        "media_type": params.get("media_type", "movie"),
        "title": params.get("title", ""),
        "plot": params.get("plot", ""),
        "year": int(params.get("year", 0)) if params.get("year") else 0,
    }
    favs = _load_favorites()
    if not any(f.get("tmdb_id") == tmdb_id for f in favs):
        favs.append(fav)
        _save_favorites(favs)
        notify("Helix", "Added favorite.", "info", 2500)


def remove_favorite_tmdb(params):
    """Remove a TMDB item from favorites."""
    tmdb_id = params.get("tmdb_id")
    if not tmdb_id:
        return
    favs = _load_favorites()
    favs = [f for f in favs if f.get("tmdb_id") != tmdb_id]
    _save_favorites(favs)
    notify("Helix", "Removed.", "info", 2000)


# =========================================================================
# Trakt lists browsing
# =========================================================================


def list_trakt_lists(params):
    """Browse the user's Trakt custom lists."""
    if not trakt.is_authorized():
        notify("Helix", "Trakt not authorized — use Account Manager.", "warn", 5000)
        add_item(c("gray", "(Trakt not authorized — set up in Account Manager)"), "", is_folder=False)
        return

    set_content("files")
    add_sort_method(SORT_LABEL)

    # Sync favorites action
    add_item(
        c("lime", b("[ Sync Favorites to Trakt ]")),
        url_for("trakt_sync_favorites"),
        is_folder=False,
        info={"plot": "Push local favorites to a 'Helix Favorites' list on Trakt."},
    )

    lists = trakt.get_user_lists()
    if not lists:
        add_item(c("gray", "(no custom lists found on Trakt)"), "", is_folder=False)
        return

    for lst in lists:
        label = lst.get("name", "(unnamed)")
        n = lst.get("item_count", 0)
        desc = lst.get("description", "") or ""
        display = c("white", b(label))
        if desc:
            display += c("gray", "  —  %s" % desc[:60])
        add_item(
            display + c("gray", "  (%d items)" % n),
            url_for("trakt_list_items", list_id=lst["id"], list_name=lst.get("name", label)),
            is_folder=True,
            info={"plot": "Trakt list: %s (%d items)" % (label, n)},
        )


def list_trakt_list_items(params):
    """Show items in a specific Trakt list."""
    list_id = params.get("list_id")
    list_name = params.get("list_name", "List")
    if not list_id:
        notify("Helix", "Missing list ID.", "error")
        return

    set_content("files")
    add_sort_method(SORT_LABEL)

    # Show movie items then TV items
    all_items = []
    for lt in ("movies", "shows"):
        items = trakt.get_list_items(list_id, lt) or []
        all_items.extend(items)

    if not all_items:
        add_item(c("gray", "(list is empty)"), "", is_folder=False)
        return

    for item in all_items:
        title = item.get("title", "(untitled)")
        year = item.get("year") or ""
        tmdb_id = item.get("tmdb_id")
        t = item.get("type", "movie")

        info = {
            "title": title,
            "year": year,
            "mediatype": "movie" if t == "movie" else "tvshow",
        }

        if tmdb_id:
            mtype = "tv" if t == "show" else "movie"
            add_item(
                c("white", b(title)) + (c("gray", "  %s" % year) if year else ""),
                url_for("list_tmdb_title", tmdb_id=str(tmdb_id), media_type=mtype),
                is_folder=True,
                info=info,
                context=[(
                    "Add to Favorites",
                    "RunPlugin(" + url_for("add_favorite_tmdb",
                                           tmdb_id=str(tmdb_id), media_type=mtype,
                                           title=title, year=str(year)) + ")",
                )],
            )
        else:
            add_item(
                c("gray", title) + (c("dimgray", "  %s" % year) if year else ""),
                "",
                is_folder=False,
                info=info,
            )


def trakt_sync_favorites(params):
    """Push local favorites to Trakt as 'Helix Favorites' list."""
    if not trakt.is_authorized():
        notify("Helix", "Trakt not authorized — use Account Manager.", "warn", 5000)
        return

    favs = _load_favorites()
    if not favs:
        notify("Helix", "No favorites to sync.", "info", 3000)
        return

    # Only sync items with TMDB IDs
    syncable = [f for f in favs if f.get("tmdb_id")]
    if not syncable:
        notify("Helix", "No TMDB-linked favorites to sync (add via TMDB browse).", "warn", 4000)
        return

    result = trakt.sync_favorites_to_trakt(syncable)
    n_added = result.get("added", 0)
    n_total = result.get("total", 0)
    if n_added > 0:
        notify("Helix", "Synced %d of %d favorites to Trakt." % (n_total, n_total), "info", 4000)
    else:
        notify("Helix", "All %d favorites already on Trakt." % n_total, "info", 3000)


# =========================================================================
# Trending / Popular / Genres
# =========================================================================

def list_trending(params):
    """Show trending content (TMDB trending week + Trakt trending)."""
    set_content("files")
    add_sort_method(SORT_LABEL)

    _section_header("Trending — Movies")
    results = tmdb.trending("movie", "week")
    for i, r in enumerate(results or []):
        _render_tmdb_result_item(r, "movie")

    _section_header("Trending — TV")
    results = tmdb.trending("tv", "week")
    for i, r in enumerate(results or []):
        _render_tmdb_result_item(r, "tv")

    if trakt.is_configured():
        try:
            _section_header("Trending — Trakt")
            for mt in ("movies", "shows"):
                trakt_items = trakt.get_trending(mt) or []
                for item in trakt_items[:10]:
                    _render_trakt_list_item(item, mt)
        except Exception as exc:
            log("Trakt trending failed: %r" % exc, "warn")


def list_popular(params):
    """Show popular content (TMDB popular + Trakt popular)."""
    set_content("files")
    add_sort_method(SORT_LABEL)

    _section_header("Popular — Movies")
    results = tmdb.popular("movie")
    for i, r in enumerate(results or []):
        _render_tmdb_result_item(r, "movie")

    _section_header("Popular — TV")
    results = tmdb.popular("tv")
    for i, r in enumerate(results or []):
        _render_tmdb_result_item(r, "tv")

    if trakt.is_configured():
        try:
            _section_header("Popular — Trakt")
            for mt in ("movies", "shows"):
                trakt_items = trakt.get_popular(mt) or []
                for item in trakt_items[:10]:
                    _render_trakt_list_item(item, mt)
        except Exception as exc:
            log("Trakt popular failed: %r" % exc, "warn")


def list_genres_home(params):
    """Genre selection: pick a media type, then genre, then see titles."""
    set_content("files")
    add_sort_method(SORT_LABEL)

    for media_type, label in [("movie", "Movie Genres"), ("tv", "TV Genres")]:
        _section_header(label)
        genres = tmdb.genres(media_type) or []
        for g in genres:
            gid = g.get("id")
            gname = g.get("name", "?")
            if gid:
                add_item(
                    c("white", b(gname)),
                    url_for("genre_items", genre_id=str(gid), media_type=media_type, genre_name=gname),
                    is_folder=True,
                    info={"plot": "Browse %s %s titles with debrid + M3U." % (gname, media_type)},
                )


def list_genre_items(params):
    """Show TMDB titles for a specific genre."""
    genre_id = params.get("genre_id", "")
    media_type = params.get("media_type", "movie")
    genre_name = params.get("genre_name", "Genre")

    results = tmdb.discover_by_genre(media_type, genre_id)
    if not results:
        notify("Helix", "No results for %s genre." % genre_name, "warn")
        return

    if media_type == "movie":
        set_content("movies")
    else:
        set_content("tvshows")
    add_sort_method(SORT_LABEL)
    add_sort_method(SORT_TITLE)

    _section_header("%s — %s" % (genre_name, media_type.title()))
    for r in results:
        _render_tmdb_result_item(r, media_type)


def _render_trakt_list_item(item, media_type="movies"):
    """Render a single Trakt list/watchlist item linking to debrid view."""
    title = item.get("title", "(untitled)")
    year = item.get("year", 0)
    tmdb_id = item.get("tmdb_id")
    if not tmdb_id:
        return
    mtype = "tv" if media_type in ("shows", "show") else "movie"
    add_item(
        c("orchid", "[Trakt] ") + c("white", b(title)) + (c("gray", "  %s" % year) if year else ""),
        url_for("list_tmdb_title", tmdb_id=str(tmdb_id), media_type=mtype),
        is_folder=True,
        info={
            "title": title,
            "year": year or 0,
            "mediatype": "movie" if mtype == "movie" else "tvshow",
            "plot": item.get("overview", ""),
        },
    )


# =========================================================================
# Indexer management UI
# =========================================================================

def test_indexers(params):
    """Run all indexer tests and show results in a text viewer."""
    from . import indexers as idx_mod
    from .utils import text_viewer
    results = idx_mod.test_indexers()
    lines = ["=== Indexer Test Results ==="]
    passed = 0
    for name, ok, detail in results:
        status = "✓ PASS" if ok else "✗ FAIL"
        if ok: passed += 1
        lines.append("  %s  %s: %s" % (status, name, detail))
    lines.append("")
    lines.append("%d/%d passed" % (passed, len(results)))
    text_viewer("Indexer Test Results", "\n".join(lines))


def indexer_status(params):
    """Show current indexer configuration."""
    from . import indexers as idx_mod
    from .utils import text_viewer
    lines = idx_mod.indexer_status()
    text_viewer("Indexer Status", "\n".join(lines))
