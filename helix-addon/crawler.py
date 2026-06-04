#!/usr/bin/env python3
"""
Helix addon progressive crawler — user-simulation mode.

Discovers menu items via nav.item log lines (now at info level), then
recursively explores folders.  Three behaviour modes:

  explore   — fast DFS, open every folder, skip leaves (default).
  browse    — scroll through lists, sample leaf items, natural pacing.
  consume   — seek playable content, attempt playback, verify stream started.

Captures full diagnostics per page: live stats, screenshot, log errors,
item inventory.

Usage:
  #   ./crawler.py                                          # explore mode
  #   ./crawler.py --mode browse
  #   ./crawler.py --mode consume --max-depth 8
  #   ./crawler.py --via gamepad                            # real Xbox button presses
  #   ./crawler.py --dry-run
  #   ./crawler.py --resume                                 # continue from checkpoint
  #   ./crawler.py --output-dir /tmp/helix-crawl
  #   ./test_suite.py --crawl --crawl-mode consume
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

from test_suite import (
    KodiClient, GamepadClient, RemotePlayClient,
    ERROR_PATTERNS, STEP_WAIT_SCALE, PROXY, XBOX_DRIVE,
    XBOX_REMOTE_BASE, DEFAULT_OUTPUT,
)

# ---------------------------------------------------------------------------
# Error patterns — broader than smoke tests, catches warnings too
# ---------------------------------------------------------------------------

CRAWL_ERROR_PATTERNS = list(ERROR_PATTERNS) + [
    re.compile(r"\[Helix\].*\bfailed\b", re.IGNORECASE),
    re.compile(r"\[Helix\].*\berror\b", re.IGNORECASE),
    re.compile(r"\[Helix\].*\bwarning\b.*\bfailed\b", re.IGNORECASE),
    re.compile(r"indexers\.http.*\bError\b", re.IGNORECASE),
    re.compile(r"indexers\.http.*\bgiving up\b", re.IGNORECASE),
]

# Error category classifiers — groups raw log lines by type for the summary
ERROR_CLASSIFIERS: list[tuple[str, re.Pattern]] = [
    ("tmdb",     re.compile(r"tmdb\s+", re.IGNORECASE)),
    ("dns",      re.compile(r"gaierror|getaddrinfo", re.IGNORECASE)),
    ("http",     re.compile(r"\bHTTPError\b|\bURLError\b", re.IGNORECASE)),
    ("indexer",  re.compile(r"indexers\.http", re.IGNORECASE)),
    ("script",   re.compile(r"Script error|Traceback|Exception", re.IGNORECASE)),
    ("timeout",  re.compile(r"\bTimeout\b|\btimed out\b", re.IGNORECASE)),
    ("addon",    re.compile(r"Addon.*failed|ExecuteAddon", re.IGNORECASE)),
]

# ---------------------------------------------------------------------------
# Regexes for nav.{begin,item,end} log lines  (now at info level)
# ---------------------------------------------------------------------------

_NAV_ITEM_RE = re.compile(
    r"nav\.item\s+"
    r"action='(?P<action>[^']*)'\s+"
    r"content='(?P<content>[^']*)'\s+"
    r"visible=(?P<visible>\d+)\s+"
    r"section='(?P<section>[^']*)'\s+"
    r"section_visible=(?P<section_visible>\d+)\s+"
    r"kind=(?P<kind>\w+)\s+"
    r"label='(?P<label>.*?)'\s+"
    r"folder=(?P<folder>True|False)\s+"
    r"route='(?P<route>[^']*)'\s+"
    r"params=\{(?P<params>.*?)\}\s+"
    r"url='(?P<url>.*?)'"
)

_NAV_BEGIN_RE = re.compile(r"nav\.begin\s+action='(?P<action>[^']*)'")
_NAV_END_RE = re.compile(r"nav\.end\s+action='(?P<action>[^']*)'")


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class PageItem:
    """One menu item on a Helix page, parsed from a nav.item log line."""
    action: str
    content: str
    visible: int
    section: str
    section_visible: int
    kind: str
    label: str
    folder: bool
    route: str
    params: str
    url: str

    def route_key(self) -> str:
        return f"{self.route}|{self.params}"


@dataclass
class PlaybackAttempt:
    """Result of attempting to play a stream."""
    attempted: bool = False
    started: bool = False
    duration_s: float = 0.0
    live_before: dict = field(default_factory=dict)
    live_after: dict = field(default_factory=dict)
    screenshot_before: str = ""
    screenshot_during: str = ""
    error: str = ""


@dataclass
class ActionReaction:
    """What happened after a single button press (before/after tracking)."""
    action: str               # "down", "up", "select", "back", "home"
    via: str                  # "kodi" or "gamepad"
    label: str = ""           # context / target description
    page_before: str = ""     # nav.begin action before press
    page_after: str = ""      # nav.begin action after press
    transition: str = ""      # "no_change", "page_changed", "playback_started", "error_spike"
    ok: bool = True
    duration_s: float = 0.0
    live_before: dict = field(default_factory=dict)
    live_after: dict = field(default_factory=dict)
    screenshot_before: str = ""
    screenshot_after: str = ""
    errors_before: int = 0
    errors_after: int = 0
    new_errors: list[str] = field(default_factory=list)


@dataclass
class PageSnapshot:
    """Snapshot of a page during the crawl."""
    action: str
    items: list[PageItem]
    breadcrumb: str = ""
    live: dict = field(default_factory=dict)
    log_errors: list[str] = field(default_factory=list)
    screenshot: str = ""
    playback: Optional[PlaybackAttempt] = None
    visited_at: float = 0.0


# ---------------------------------------------------------------------------
# Crawler
# ---------------------------------------------------------------------------

class Crawler:
    """Progressive DFS crawler over Helix addon menus with user simulation."""

    PAGE_SETTLE_S = 1.5          # settle after navigation
    SCROLL_ITEMS = 15            # items to scroll past before giving up
    MAX_PLAYBACK_S = 8           # seconds to wait for playback start
    MAX_PLAYBACK_ATTEMPTS = 3    # per crawl

    def __init__(
        self,
        output_dir: Path = DEFAULT_OUTPUT,
        max_depth: int = 20,
        mode: str = "explore",
        via: str = "kodi",
        skip_screenshots: bool = False,
        dry_run: bool = False,
        step_wait_scale: float = STEP_WAIT_SCALE,
    ):
        self.output_dir = Path(output_dir) / "crawl"
        self.max_depth = max_depth
        self.mode = mode
        self.via = via  # "kodi" or "gamepad"
        self.skip_screenshots = skip_screenshots
        self.dry_run = dry_run
        self.step_wait_scale = step_wait_scale

        self.kodi = KodiClient()
        self.gamepad = GamepadClient()
        self.remote = RemotePlayClient()

        # State
        self.visited: set[str] = set()
        self.page_log: list[PageSnapshot] = []
        self.total_items_found = 0
        self.total_folders_entered = 0
        self.total_playback_attempts = 0
        self.total_playback_success = 0
        self._page_error_count = 0
        self._log_baseline: list[str] = []
        self._reaction_log: list[ActionReaction] = []
        self._last_action: str = ""
        self._resume: bool = False

        self.output_dir.mkdir(parents=True, exist_ok=True)

    # -- helpers ----------------------------------------------------------

    def _wait(self, seconds: float = 0.5):
        time.sleep(seconds * self.step_wait_scale)

    def _live(self) -> dict:
        try:
            return self.kodi.live()
        except Exception:
            return {}

    def _logs(self, lines: int = 500) -> list[str]:
        try:
            return self.kodi.logs(lines=lines)
        except Exception:
            return []

    def _capture(self, label: str) -> str:
        if self.skip_screenshots:
            return ""
        try:
            out = str(self.output_dir / f"{label}.png")
            self.gamepad.capture(out)
            return out
        except Exception:
            return ""

    def _is_playing(self, live: dict) -> bool:
        try:
            np = live.get("now_playing", {}) or {}
            return bool(np.get("playing", False))
        except Exception:
            return False

    def _stop_playback(self):
        """Stop any active Kodi player."""
        try:
            active = self.kodi.command("Player.GetActivePlayers")
            if active and isinstance(active, list):
                for p in active:
                    self.kodi.command("Player.Stop", {"playerid": p.get("playerid", 1)})
        except Exception:
            pass

    def _count_errors(self, log_lines: list[str]) -> list[str]:
        return [ln for ln in log_lines if any(p.search(ln) for p in CRAWL_ERROR_PATTERNS)]

    def _diff_errors(self, after: list[str]) -> list[str]:
        baseline_set = set(self._log_baseline)
        new = [ln for ln in after if ln not in baseline_set]
        return self._count_errors(new)

    # -- input (with reaction tracking) ------------------------------------

    def _send_input(self, action: str, label: str = "", count: int = 1) -> ActionReaction:
        """Send a button press, capture before/after, return ActionReaction.

        ``action`` — ``up``/``down``/``select``/``back``/``home``.
        ``via`` route: ``kodi`` uses JSON-RPC, ``gamepad`` uses xbox-drive.mjs.
        """
        t0 = time.time()

        # --- snapshot before ---
        logs_before = self._logs()
        page_before = self._find_action_from_log(logs_before) or self._last_action
        err_before = len(self._count_errors(logs_before))

        live_before = self._live()
        shot_before = self._capture(f"in_{action}_{len(self._reaction_log):04d}_b") if not self.skip_screenshots else ""

        # --- perform the press ---
        via = self.via
        ok = False
        for _ in range(count if action not in ("select", "back", "home") else 1):
            if self.dry_run:
                ok = True
            elif via == "gamepad" and action in GamepadClient._BTN_MAP:
                r = self.gamepad.tap(action)
                ok = r.get("ok", False)
                via = "gamepad"
            else:
                r = self.kodi.input(action)
                ok = r.get("ok", r.get("error") is None) if isinstance(r, dict) else True
                via = "kodi"
            if action in ("select", "back", "home"):
                break  # single press for navigation actions
            self._wait(0.08)

        self._wait(0.15 if action in ("up", "down", "left", "right") else self.PAGE_SETTLE_S)

        # --- snapshot after ---
        logs_after = self._logs()
        page_after = self._find_action_from_log(logs_after) or page_before
        err_after = len(self._count_errors(logs_after))
        new_errs = [ln for ln in logs_after if ln not in set(logs_before) and any(p.search(ln) for p in CRAWL_ERROR_PATTERNS)]

        live_after = self._live()
        shot_after = self._capture(f"in_{action}_{len(self._reaction_log):04d}_a") if not self.skip_screenshots else ""

        # Determine transition
        transition = "no_change"
        if page_after != page_before:
            transition = "page_changed"
        elif self._is_playing(live_after) and not self._is_playing(live_before):
            transition = "playback_started"
        elif len(new_errs) > 0:
            transition = "error_spike"

        elapsed = time.time() - t0
        rxn = ActionReaction(
            action=action,
            via=via,
            label=label,
            page_before=page_before,
            page_after=page_after,
            transition=transition,
            ok=ok,
            duration_s=round(elapsed, 3),
            live_before=live_before,
            live_after=live_after,
            screenshot_before=shot_before,
            screenshot_after=shot_after,
            errors_before=err_before,
            errors_after=err_after,
            new_errors=new_errs,
        )
        self._reaction_log.append(rxn)
        self._last_action = page_after or page_before
        self._page_error_count += len(new_errs)
        return rxn

    def _press(self, action: str, count: int = 1, label: str = "") -> ActionReaction:
        return self._send_input(action, label=label, count=count)

    def _select(self, label: str = "") -> ActionReaction:
        return self._send_input("select", label=label)

    def _back(self, label: str = "") -> ActionReaction:
        return self._send_input("back", label=label)

    # -- checkpoint ---------------------------------------------------------

    CHECKPOINT_FILE = "checkpoint.json"

    def _save_checkpoint(self):
        """Save partial progress so we can resume after interruption."""
        if self.dry_run:
            return
        cp = {
            "visited": sorted(self.visited),
            "total_pages_visited": len(self.page_log),
            "total_items_found": self.total_items_found,
            "total_folders_entered": self.total_folders_entered,
            "total_playback_attempts": self.total_playback_attempts,
            "total_playback_success": self.total_playback_success,
            "_page_error_count": self._page_error_count,
            "_log_baseline": self._log_baseline,
        }
        try:
            (self.output_dir / self.CHECKPOINT_FILE).write_text(json.dumps(cp, indent=2))
        except Exception:
            pass

    def _load_checkpoint(self) -> bool:
        """Load checkpoint if it exists.  Returns True if state was restored."""
        cp_path = self.output_dir / self.CHECKPOINT_FILE
        if not cp_path.is_file():
            return False
        try:
            cp = json.loads(cp_path.read_text())
            self.visited = set(cp.get("visited", []))
            self.total_items_found = cp.get("total_items_found", 0)
            self.total_folders_entered = cp.get("total_folders_entered", 0)
            self.total_playback_attempts = cp.get("total_playback_attempts", 0)
            self.total_playback_success = cp.get("total_playback_success", 0)
            self._page_error_count = cp.get("_page_error_count", 0)
            self._log_baseline = cp.get("_log_baseline", [])
            # If we have pages saved we can't truly replay the stack, but
            # the visited set prevents re-exploring already-covered branches.
            print(f"  Checkpoint loaded: {cp.get('total_pages_visited', '?')} pages already visited")
            return True
        except Exception as exc:
            print(f"  Checkpoint load failed: {exc}")
            return False

    # -- error classification -----------------------------------------------

    def _classify_errors(self, err_lines: list[str]) -> dict[str, int]:
        """Categorise error lines by type.  Returns {category: count}."""
        counts: dict[str, int] = {}
        for line in err_lines:
            matched = False
            for cat, pat in ERROR_CLASSIFIERS:
                if pat.search(line):
                    counts[cat] = counts.get(cat, 0) + 1
                    matched = True
                    break
            if not matched:
                counts["other"] = counts.get("other", 0) + 1
        return counts

    def _stop_playback(self):
        """Stop any active Kodi player."""
        try:
            active = self.kodi.command("Player.GetActivePlayers")
            if active and isinstance(active, list):
                for p in active:
                    self.kodi.command("Player.Stop", {"playerid": p.get("playerid", 1)})
        except Exception:
            pass

    def _parse_nav_items(self, log_lines: list[str]) -> list[PageItem]:
        items: list[PageItem] = []
        in_page = False
        for line in log_lines:
            if _NAV_BEGIN_RE.search(line):
                in_page = True
                items = []
            m = _NAV_ITEM_RE.search(line)
            if m and in_page:
                items.append(PageItem(
                    action=m.group("action"),
                    content=m.group("content"),
                    visible=int(m.group("visible")),
                    section=m.group("section"),
                    section_visible=int(m.group("section_visible")),
                    kind=m.group("kind"),
                    label=m.group("label"),
                    folder=m.group("folder") == "True",
                    route=m.group("route"),
                    params=m.group("params"),
                    url=m.group("url"),
                ))
            if _NAV_END_RE.search(line):
                in_page = False
        return items

    def _find_action_from_log(self, log_lines: list[str]) -> str:
        for line in reversed(log_lines):
            m = _NAV_BEGIN_RE.search(line)
            if m:
                return m.group("action")
        return "?"

    def _has_breadcrumb(self, log_lines: list[str]) -> str:
        for line in reversed(log_lines):
            if "nav.breadcrumb" in line:
                return line.strip()
        return ""

    # -- navigation -------------------------------------------------------

    def _open_helix(self) -> bool:
        if self.dry_run:
            return True
        log_before = self._logs()
        self.kodi.open_addon()
        self._wait(2.0)
        log_after = self._logs()
        items = self._parse_nav_items(log_after)
        errs = self._count_errors(log_after[len(log_before):])
        if items:
            return True
        if errs:
            print(f"  [WARN] open_helix: {len(errs)} new issues")
            return True
        return False

    def _navigate_to_item(self, item: PageItem) -> bool:
        """Move focus to the item's visible index and select it."""
        if item.visible > 0:
            self._press("down", item.visible)
        self._wait(0.2)
        self._select()
        return True

    def _scroll_down(self, steps: int = 3) -> int:
        """Scroll down `steps` times.  Returns total presses sent for
        the caller to reverse on back-out."""
        self._press("down", steps)
        self._wait(0.3)
        return steps

    # -- playback simulation ----------------------------------------------

    def _attempt_playback(self, item: PageItem, depth: int) -> Optional[PlaybackAttempt]:
        """Try to play a non-folder item.  Returns PlaybackAttempt with
        timing diagnostics or None if skipped (mode / limit)."""
        if self.total_playback_attempts >= self.MAX_PLAYBACK_ATTEMPTS:
            return None
        if self.mode == "explore":
            return None
        self.total_playback_attempts += 1

        result = PlaybackAttempt(attempted=True)
        prefix = "  " * depth
        print(f"{prefix}  ▶ playback #{self.total_playback_attempts}: {item.label[:60]}")

        if self.dry_run:
            return result

        # Navigate to the item
        if item.visible > 0:
            self._press("down", item.visible)
        self._wait(0.2)

        live_before = self._live()
        result.live_before = live_before

        if not self.skip_screenshots:
            before_label = f"play_before_{self.total_playback_attempts:03d}"
            result.screenshot_before = self._capture(before_label)

        # Select the item (triggers playback)
        self.kodi.input("select")
        self._wait(0.5)

        # Poll for playback start (up to MAX_PLAYBACK_S)
        deadline = time.time() + self.MAX_PLAYBACK_S
        started = False
        while time.time() < deadline:
            live = self._live()
            if self._is_playing(live):
                started = True
                break
            self._wait(0.3)

        result.started = started
        elapsed = time.time() - (deadline - self.MAX_PLAYBACK_S)
        result.duration_s = elapsed

        if not self.skip_screenshots:
            during_label = f"play_during_{self.total_playback_attempts:03d}"
            result.screenshot_during = self._capture(during_label)

        live_after = self._live()
        result.live_after = live_after

        if started:
            self.total_playback_success += 1
            print(f"{prefix}    ✓ playback started in {elapsed:.1f}s")
            # Let it play for a moment, then stop
            self._wait(1.0)
            self._stop_playback()
            self._wait(0.5)
        else:
            err = live_after.get("error", "playback did not start")
            result.error = str(err)
            print(f"{prefix}    ✗ playback failed: {err}")

        return result

    # -- page diagnostics ------------------------------------------------

    def _snapshot_page(
        self,
        action: str,
        items: list[PageItem],
        log_lines: list[str],
        label_suffix: str = "",
        playback: Optional[PlaybackAttempt] = None,
    ) -> PageSnapshot:
        errs = self._diff_errors(log_lines)
        self._page_error_count += len(errs)
        snap = PageSnapshot(
            action=action,
            items=items,
            breadcrumb=self._has_breadcrumb(log_lines),
            live=self._live(),
            log_errors=errs,
            playback=playback,
            visited_at=time.time(),
        )
        if not self.skip_screenshots and not self.dry_run:
            fname = f"page_{len(self.page_log):04d}_{action}"
            if label_suffix:
                fname += f"_{label_suffix}"
            snap.screenshot = self._capture(fname)
        return snap

    # -- core crawl ------------------------------------------------------

    def crawl(self) -> dict:
        print(f"Crawl output: {self.output_dir}")
        print(f"Mode: {self.mode}  max_depth={self.max_depth}\n")

        if not self.dry_run:
            self._log_baseline = self._logs()

            # Checkpoint restore
            if self._resume:
                self._load_checkpoint()
                print("  (resume mode — visited branches will be skipped)\n")

            ok = self._open_helix()
            if not ok:
                print("ERROR: could not open Helix addon")
                return {"status": "failed", "error": "open_helix failed"}

        try:
            self._crawl_page(depth=0, parent_label="root")
        except KeyboardInterrupt:
            print("\n\n  ⚑ Interrupted — saving checkpoint...")
            self._save_checkpoint()
            print("  Checkpoint saved.  Resume later with --resume.")
            print(f"  Visited {len(self.visited)} route(s), {len(self.page_log)} page(s).\n")

        # Aggregate error categories across all pages
        all_errs: list[str] = []
        for p in self.page_log:
            all_errs.extend(p.log_errors)
        err_categories = self._classify_errors(all_errs)

        report = {
            "status": "complete",
            "mode": self.mode,
            "via": self.via,
            "output_dir": str(self.output_dir),
            "total_pages_visited": len(self.page_log),
            "total_items_found": self.total_items_found,
            "total_folders_entered": self.total_folders_entered,
            "total_playback_attempts": self.total_playback_attempts,
            "total_playback_success": self.total_playback_success,
            "total_diagnostic_errors": self._page_error_count,
            "total_actions": len(self._reaction_log),
            "total_page_transitions": sum(1 for r in self._reaction_log if r.transition == "page_changed"),
            "total_errors_spikes": sum(1 for r in self._reaction_log if r.transition == "error_spike"),
            "error_categories": err_categories,
            "pages": [asdict(p) for p in self.page_log],
            "reactions": [asdict(r) for r in self._reaction_log],
            "visited_keys": sorted(self.visited),
        }
        report_path = self.output_dir / "report.json"
        report_path.write_text(json.dumps(report, indent=2, default=str))

        # Clean up checkpoint when crawl completes normally
        if not self.dry_run:
            try:
                (self.output_dir / self.CHECKPOINT_FILE).unlink(missing_ok=True)
            except Exception:
                pass

        print(f"\n{'='*50}")
        print(f"Report: {report_path}")
        print(f"Pages visited:      {report['total_pages_visited']}")
        print(f"Items found:        {report['total_items_found']}")
        print(f"Folders entered:    {report['total_folders_entered']}")
        print(f"Input via:          {self.via}")
        print(f"Total actions:      {report['total_actions']}")
        print(f"Page transitions:   {report['total_page_transitions']}")
        print(f"Error spikes:       {report['total_errors_spikes']}")
        print(f"Playback attempts:  {report['total_playback_attempts']}")
        if self.total_playback_attempts:
            print(f"Playback success:   {report['total_playback_success']} / {self.total_playback_attempts}")
        print(f"Diagnostic errors:  {report['total_diagnostic_errors']}")
        if err_categories:
            cats = "  ".join(f"{k}={v}" for k, v in sorted(err_categories.items()) if v > 0)
            print(f"Error breakdown:    {cats}")

        issues = []
        if self._page_error_count:
            issues.append(f"{self._page_error_count} diagnostic issue(s) detected")
        if self.total_playback_attempts and self.total_playback_success < self.total_playback_attempts:
            issues.append(f"{self.total_playback_attempts - self.total_playback_success} playback failure(s)")
        if issues:
            print(f"\n  ** {'; '.join(issues)} **")
        print(f"{'='*50}\n")

        return report

    def _crawl_page(self, depth: int, parent_label: str):
        if depth > self.max_depth:
            return

        logs = self._logs()
        items = self._parse_nav_items(logs)
        action = self._find_action_from_log(logs)

        if not items:
            # No nav.item entries — try JSON-RPC container probe as fallback
            self._try_container_probe(depth, action)
            return

        # Snapshot
        snap = self._snapshot_page(action, items, logs)
        self.page_log.append(snap)
        self.total_items_found += len(items)

        folders = [it for it in items if it.folder]
        leaves = [it for it in items if not it.folder]

        # Summary
        fl = ", ".join(it.label[:36] for it in folders[:4])
        if len(folders) > 4:
            fl += f" …(+{len(folders)-4})"
        ll = ", ".join(it.label[:30] for it in leaves[:3])
        if len(leaves) > 3:
            ll += f" …(+{len(leaves)-3})"
        print(
            f"{'  ' * depth}[{action}]  "
            f"{len(items)} items  ({len(folders)}F/{len(leaves)}L)  "
            f"F=[{fl}]  L=[{ll}]"
        )

        # In browse/consume mode: scroll to discover more items
        if self.mode in ("browse", "consume") and len(items) >= 5:
            self._scroll_and_discover(depth, action)

        # Explore folders (all modes)
        for item in folders:
            rk = item.route_key()
            if rk in self.visited:
                continue
            self.visited.add(rk)

            print(f"{'  ' * (depth+1)}→ {item.label[:56]}  route={item.route}")
            if self.dry_run:
                continue

            self._navigate_to_item(item)
            self.total_folders_entered += 1
            self._crawl_page(depth + 1, item.label)
            self._back()

        # Attempt playback on leaf items (consume mode only)
        if self.mode == "consume" and leaves:
            for leaf in leaves[:2]:
                pb = self._attempt_playback(leaf, depth)
                if pb:
                    snap.playback = pb
                    break  # one playback per page

        if snap.log_errors:
            for err in snap.log_errors[:3]:
                print(f"{'  ' * depth}  [ERR] {err[:120]}")

        # Save progress checkpoint
        self._save_checkpoint()

    # -- fallback container probe (no nav.item entries) -------------------

    def _try_container_probe(self, depth: int, action: str):
        """Fallback when nav.item is missing — probe via JSON-RPC info labels
        and walk what we can see."""
        if self.dry_run:
            print(f"{'  ' * depth}[{action}] no nav.item data (debug logging off?)")
            return

        try:
            # Read container count via info labels
            count_data = self.kodi.command("XBMC.GetInfoLabels", {
                "labels": ["Container.NumItems", "Container.CurrentItem"]
            })
            if not isinstance(count_data, dict):
                print(f"{'  ' * depth}[{action}] container probe: no response")
                return
            num = int(count_data.get("Container.NumItems", 0) or 0)
            cur = int(count_data.get("Container.CurrentItem", 0) or 0)
        except Exception:
            print(f"{'  ' * depth}[{action}] container probe failed")
            return

        if num == 0:
            print(f"{'  ' * depth}[{action}]: empty container (leaf)")
            return

        print(f"{'  ' * depth}[{action}] container: ~{num} items  (nav.item unavailable)")

        # In browse/consume mode, scroll a bit and snapshot
        if self.mode in ("browse", "consume") and num > 3:
            scroll = min(num - cur, self.SCROLL_ITEMS)
            self._scroll_down(scroll)
            self._back()

        # Still snapshot with whatever we have
        snap = self._snapshot_page(action, [], self._logs())
        self.page_log.append(snap)

    def _scroll_and_discover(self, depth: int, action: str):
        """Scroll a few items down to discover content not on the first screen.
        Then scroll back up to restore focus."""
        self._press("down", 3)
        self._wait(0.3)
        # Snapshot the "scrolled" state
        logs = self._logs()
        scrolled_items = self._parse_nav_items(logs)
        if scrolled_items:
            snap = self._snapshot_page(action + "_scrolled", scrolled_items, logs)
            self.page_log.append(snap)
            self.total_items_found += len(scrolled_items)
            print(f"{'  ' * depth}  ↕ scrolled → {len(scrolled_items)} more items")
        # Scroll back up
        self._press("up", 3)
        self._wait(0.2)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description="Helix addon progressive crawler")
    ap.add_argument("--output-dir", default=str(DEFAULT_OUTPUT))
    ap.add_argument("--max-depth", type=int, default=20)
    ap.add_argument("--mode", choices=["explore", "browse", "consume"],
                    default="explore", help="crawler behaviour mode")
    ap.add_argument("--via", choices=["kodi", "gamepad"], default="kodi",
                    help="input path: kodi=JSON-RPC (default), gamepad=xbox-drive.mjs")
    ap.add_argument("--skip-screenshots", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--resume", action="store_true", help="resume from checkpoint (loads visited set)")
    args = ap.parse_args()

    c = Crawler(
        output_dir=Path(args.output_dir),
        max_depth=args.max_depth,
        mode=args.mode,
        via=args.via,
        skip_screenshots=args.skip_screenshots,
        dry_run=args.dry_run,
    )
    c._resume = args.resume
    report = c.crawl()
    return 0 if report.get("status") == "complete" else 1


if __name__ == "__main__":
    sys.exit(main())
