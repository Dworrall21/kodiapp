#!/usr/bin/env python3
"""
Helix Kodi add-on automated test suite.

For each test case, walks the Helix menu via:
  - Primary  : Kodi JSON-RPC (Input.Down/Up/Select/Back/Home) via kodi-xbox-proxy
  - Fallback : Xbox Remote Drive keyboard/gamepad via `node xbox-drive.mjs`

Captures one screenshot per button press from the Xbox Remote Play stream
(`/home/david/xbox-remote-drive/xbox-drive.mjs capture`).

Fetches `kodi.log` before and after each test via `/api/logs?lines=N` and
counts new Helix-related errors/exceptions to decide pass/fail.

Usage:
  ./test_suite.py                          # run all tests
  ./test_suite.py --filter browse_movies   # run one test
  ./test_suite.py --list                   # show test plan
  ./test_suite.py --mode keyboard          # force keyboard (no Kodi commands)
  ./test_suite.py --mode auto              # kodi with keyboard fallback on error
  ./test_suite.py --skip-keyboard-launch   # disable keyboard preflight launch
  ./test_suite.py --from browse_movies --to browse_anime
  ./test_suite.py --output-dir /tmp/helix-tests
  ./test_suite.py --dry-run                # print plan, no execution

Screenshots land in <output-dir>/<test>/<NN>_<label>.png and a JSON
report is written to <output-dir>/report.json.
"""

from __future__ import annotations

import argparse
import os
import json
import re
import shlex
import select
import subprocess
import sys
import time
import urllib.error
import urllib.request
from urllib.parse import quote
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional


# ----- paths / defaults -----

PROXY = "http://127.0.0.1:8080"
XBOX_DRIVE = Path("/home/david/xbox-remote-drive/xbox-drive.mjs")
XBOX_KEYBOARD = Path("/home/david/xbox-remote-drive/keyboard.mjs")
XBOX_REMOTE_BASE = "http://127.0.0.1:9222"
# Xbox Remote Play start page. Requires an already logged-in Xbox/Microsoft
# session in the Chrome profile used by the remote-play tooling.
XBOX_REMOTE_URL = "https://www.xbox.com/en-US/play/consoles"
DEFAULT_OUTPUT = Path("/tmp/helix-tests")
CHROME_BIN = "/usr/bin/google-chrome"
CHROME_USER_DATA_DIR = "/home/david/.cache/chrome-remote-play"
CHROME_REMOTE_LOG = "/tmp/helix-xbox-chrome.log"

# Global wait multiplier for live Remote Play steps.
# 1.0 = original pace. Smaller = faster.
STEP_WAIT_SCALE = 0.2

HELIX_ADDON_ID = "plugin.video.helix"

# Log patterns that count as a test failure when NEW after a test runs.
# (Generic Python errors are also caught by the EXCEPTION/Traceback branch below.)
ERROR_PATTERNS = [
    re.compile(r"\[Helix\].*ERROR", re.IGNORECASE),
    re.compile(r"\bHelix.*Exception", re.IGNORECASE),
    re.compile(r"Traceback \(most recent call last\):"),
    re.compile(r"\bXFILE::CDirectory::GetDirectory - Error getting plugin://plugin\.video\.helix"),
    re.compile(r"CGUIMediaWindow::GetDirectory.*plugin\.video\.helix.*failed", re.IGNORECASE),
    re.compile(r"Script error.*plugin\.video\.helix", re.IGNORECASE),
]


# ----- low-level clients -----


class KodiClient:
    """Send JSON-RPC commands to Kodi via the kodi-xbox-proxy."""

    def __init__(self, proxy_url: str = PROXY, timeout: float = 8.0):
        self.proxy_url = proxy_url
        self.timeout = timeout

    def command(self, method: str, params: Optional[dict] = None) -> dict:
        body = {"method": method, "params": params or {}}
        req = urllib.request.Request(
            f"{self.proxy_url}/api/command",
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return json.loads(resp.read().decode())
        except (urllib.error.URLError, json.JSONDecodeError, TimeoutError) as exc:
            return {"error": str(exc), "ok": False}

    def input(self, action: str) -> dict:
        """Map short names to JSON-RPC Input.* methods."""
        action_map = {
            "up": ("Input.Up", None),
            "down": ("Input.Down", None),
            "left": ("Input.Left", None),
            "right": ("Input.Right", None),
            "select": ("Input.Select", None),
            "back": ("Input.Back", None),
            "home": ("Input.Home", None),
            "info": ("Input.Info", None),
            "context": ("Input.ContextMenu", None),
            "osd": ("Input.ShowOSD", None),
        }
        if action not in action_map:
            return {"error": f"unknown input action: {action}", "ok": False}
        method, _ = action_map[action]
        return self.command(method)

    def open_addon(self, addon_id: str = HELIX_ADDON_ID) -> dict:
        return self.command("Addons.ExecuteAddon", {"addonid": addon_id})

    def status(self) -> dict:
        try:
            with urllib.request.urlopen(f"{self.proxy_url}/api/status", timeout=3) as resp:
                return json.loads(resp.read().decode())
        except Exception as exc:
            return {"error": str(exc), "connected": False}

    def logs(self, lines: int = 200) -> list[str]:
        try:
            with urllib.request.urlopen(
                f"{self.proxy_url}/api/logs?lines={lines}", timeout=5
            ) as resp:
                data = json.loads(resp.read().decode())
            ls = data.get("lines", [])
            if isinstance(ls, str):
                return ls.splitlines()
            return list(ls)
        except Exception as exc:
            return [f"[log fetch error: {exc}]"]

    def live(self) -> dict:
        try:
            with urllib.request.urlopen(f"{self.proxy_url}/api/live", timeout=5) as resp:
                return json.loads(resp.read().decode())
        except Exception as exc:
            return {"error": str(exc), "ok": False}


class GamepadClient:
    """Send button presses via xbox-remote-drive (keyboard/gamepad shim)."""

    def __init__(self, xbox_drive: Path = XBOX_DRIVE, default_hold_ms: int = 60):
        self.xbox_drive = str(xbox_drive)
        self.default_hold_ms = default_hold_ms

    def _run(self, *args: str, timeout: int = 15) -> dict:
        try:
            env = os.environ.copy()
            env.setdefault("CDP_URL", XBOX_REMOTE_BASE)
            result = subprocess.run(
                ["node", self.xbox_drive, *args],
                capture_output=True, text=True, timeout=timeout, env=env,
            )
            return {"ok": result.returncode == 0, "stdout": result.stdout.strip(), "stderr": result.stderr.strip()}
        except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
            return {"ok": False, "error": str(exc)}

    # Button alias map (matches xbox-drive.mjs aliases).
    # For d-pad, full-word aliases (up/down/left/right) work as tap targets.
    _BTN_MAP = {
        "up": "up", "down": "down", "left": "left", "right": "right",
        "select": "a", "back": "b", "info": "y", "context": "sta",
        "osd": "x", "home": "home", "menu": "sta",
    }

    def tap(self, action: str, hold_ms: Optional[int] = None) -> dict:
        btn = self._BTN_MAP.get(action)
        if not btn:
            return {"ok": False, "error": f"no gamepad mapping for {action}"}
        hold = hold_ms if hold_ms is not None else self.default_hold_ms
        # Long-press Start for ContextMenu (1500ms).
        if action == "context":
            return self._run("hold", btn, "1500")
        if action == "home":
            # 'home' is the Xbox Home button; xbox-drive accepts 'home' alias
            return self._run("tap", btn, str(hold))
        return self._run("tap", btn, str(hold))

    def capture(self, out_path: str, delay_ms: int = 50) -> dict:
        return self._run("capture", out_path, str(delay_ms), timeout=30)


class RemotePlayClient:
    """Launch/focus Xbox Remote Play in Chrome via remote-debugging JSON endpoints.

    Hardened: if 9222 is down, auto-starts Chrome with --remote-debugging-port=9222
    pointing at a stable user-data-dir, then retries the find/open flow.

    Assumption: the target Chrome profile already has an authenticated Xbox
    session; we start from the consoles landing page and then drive the UI via
    the keyboard/gamepad suite in xbox-remote-drive.
    """

    def __init__(self, base_url: str = XBOX_REMOTE_BASE):
        self.base_url = base_url.rstrip("/")
        self.chrome_bin = CHROME_BIN
        self.user_data_dir = CHROME_USER_DATA_DIR
        self.chrome_log = CHROME_REMOTE_LOG

    def _json(self, path: str, method: str = "GET", timeout: float = 8.0) -> Any:
        req = urllib.request.Request(f"{self.base_url}{path}", method=method)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode().strip()
        return json.loads(raw) if raw else None

    def is_up(self, timeout: float = 2.0) -> bool:
        try:
            self._json("/json/version", timeout=timeout)
            return True
        except Exception:
            return False

    def _ensure_chrome(self) -> dict:
        """Start Chrome with remote-debugging on 9222 if it's not already up.

        Returns a status dict describing what happened.
        """
        if self.is_up():
            return {"started": False, "reason": "already-up"}
        Path(self.user_data_dir).mkdir(parents=True, exist_ok=True)
        cmd = [
            self.chrome_bin,
            f"--remote-debugging-port=9222",
            f"--user-data-dir={self.user_data_dir}",
            "--no-first-run",
            "--no-default-browser-check",
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--disable-background-networking",
            "--disable-component-update",
            "--disable-features=Translate,BackForwardCache",
            "--start-maximized",
            "about:blank",
        ]
        try:
            log_fh = open(self.chrome_log, "ab", buffering=0)
        except Exception:
            log_fh = subprocess.DEVNULL
        try:
            subprocess.Popen(
                cmd,
                stdout=log_fh,
                stderr=log_fh,
                stdin=subprocess.DEVNULL,
                start_new_session=True,
            )
        except FileNotFoundError as exc:
            return {"started": False, "reason": f"chrome-missing: {exc}"}
        # wait for 9222 to come up (poll up to ~8s)
        deadline = time.time() + 8.0
        while time.time() < deadline:
            if self.is_up():
                return {"started": True, "reason": "ok"}
            time.sleep(0.3)
        return {"started": True, "reason": "timeout-waiting-for-9222"}

    def list_pages(self) -> list[dict]:
        data = self._json("/json/list")
        return data if isinstance(data, list) else []

    def _find_remote_page(self) -> Optional[dict]:
        pages = self.list_pages()
        for page in pages:
            url = page.get("url", "")
            if "xbox.com/play" in url or "xboxplay" in url:
                return page
        return None

    def _activate(self, page_id: str) -> None:
        try:
            self._json(f"/json/activate/{page_id}")
        except Exception:
            pass

    def launch(self, url: str = XBOX_REMOTE_URL) -> dict:
        # 1) Try to use an existing Xbox tab if DevTools is reachable.
        try:
            page = self._find_remote_page()
            if page:
                self._activate(page["id"])
                return {
                    "ok": True,
                    "mode": "focus-existing",
                    "id": page.get("id"),
                    "url": page.get("url"),
                    "title": page.get("title"),
                }
        except Exception:
            pass

        # 2) If Chrome is not running on 9222, start it.
        chrome_status = {"started": False, "reason": "skipped"}
        try:
            self._find_remote_page()  # probe
        except Exception:
            chrome_status = self._ensure_chrome()

        # 3) Try to focus an existing Xbox tab again after Chrome is up.
        try:
            page = self._find_remote_page()
            if page:
                self._activate(page["id"])
                return {
                    "ok": True,
                    "mode": "focus-existing-after-start",
                    "chrome": chrome_status,
                    "id": page.get("id"),
                    "url": page.get("url"),
                    "title": page.get("title"),
                }
        except Exception:
            pass

        # 4) Open a new tab on the Xbox launch URL.
        try:
            opened = self._json(f"/json/new?{quote(url, safe='')}", method="PUT")
            time.sleep(1.0)
            page = self._find_remote_page()
            if page:
                self._activate(page["id"])
                return {
                    "ok": True,
                    "mode": "open-new",
                    "chrome": chrome_status,
                    "opened": opened,
                    "id": page.get("id"),
                    "url": page.get("url"),
                    "title": page.get("title"),
                }
            return {
                "ok": False,
                "error": "xbox remote play tab not found after open",
                "chrome": chrome_status,
                "opened": opened,
            }
        except Exception as exc:
            return {"ok": False, "error": str(exc), "chrome": chrome_status}


class KeyboardSuiteClient:
    """Launch and monitor xbox-remote-drive/keyboard.mjs.

    This keeps the browser-side keyboard/gamepad bridge alive so Remote Play
    can be driven from the physical keyboard during preflight/manual testing.
    """

    def __init__(self, script: Path = XBOX_KEYBOARD, cdp_url: str = XBOX_REMOTE_BASE):
        self.script = Path(script)
        self.cdp_url = cdp_url
        self.proc: Optional[subprocess.Popen] = None

    def _spawn(self) -> subprocess.Popen:
        env = os.environ.copy()
        env["CDP_URL"] = self.cdp_url
        proc = subprocess.Popen(
            ["node", str(self.script)],
            cwd=str(self.script.parent),
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            start_new_session=True,
        )
        self.proc = proc
        return proc

    def launch(self, timeout_s: float = 15.0) -> dict:
        if self.proc and self.proc.poll() is None:
            return {"ok": True, "started": False, "ready": True, "pid": self.proc.pid, "mode": "already-running"}

        proc = self._spawn()
        if not proc.stdout:
            return {"ok": False, "started": True, "ready": False, "pid": proc.pid, "error": "keyboard stdout unavailable"}

        deadline = time.time() + timeout_s
        seen: list[str] = []
        ready_markers = ("virtual gamepad ready", "key handler installed")

        while time.time() < deadline:
            if proc.poll() is not None:
                break
            remaining = max(0.0, deadline - time.time())
            readable, _, _ = select.select([proc.stdout], [], [], min(0.5, remaining) if remaining else 0)
            if not readable:
                continue
            line = proc.stdout.readline()
            if not line:
                continue
            line = line.rstrip()
            seen.append(line)
            if any(marker in line for marker in ready_markers):
                return {"ok": True, "started": True, "ready": True, "pid": proc.pid, "line": line}

        tail = seen[-10:]
        if proc.poll() is None:
            try:
                proc.terminate()
                proc.wait(timeout=3)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
        return {"ok": False, "started": True, "ready": False, "pid": proc.pid, "error": "keyboard suite did not become ready", "output": tail}

    def stop(self) -> None:
        proc = self.proc
        if not proc:
            return
        if proc.poll() is None:
            try:
                proc.terminate()
                proc.wait(timeout=3)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
        self.proc = None


# ----- screenshot/log helpers -----


def fetch_log_lines(proxy_url: str = PROXY, lines: int = 200) -> list[str]:
    try:
        with urllib.request.urlopen(f"{proxy_url}/api/logs?lines={lines}", timeout=5) as resp:
            data = json.loads(resp.read().decode())
        ls = data.get("lines", [])
        return ls if isinstance(ls, list) else str(ls).splitlines()
    except Exception as exc:
        return [f"[log fetch error: {exc}]"]


def count_new_errors(before: list[str], after: list[str]) -> tuple[int, list[str]]:
    """Return (count, sample_lines) for new Helix errors after the test."""
    before_set = set(before)
    new = [ln for ln in after if ln not in before_set]
    matches = [ln for ln in new if any(p.search(ln) for p in ERROR_PATTERNS)]
    return len(matches), matches


def summarize_live_snapshot(snapshot: dict) -> str:
    """Compact one-line summary for stdout."""
    if not isinstance(snapshot, dict):
        return "<no snapshot>"
    if snapshot.get("ok") is False:
        return f"live error: {snapshot.get('error', 'unknown')}"
    parts = []
    connected = snapshot.get("connected")
    if connected is not None:
        parts.append(f"connected={connected}")
    now = snapshot.get("now_playing") or {}
    if isinstance(now, dict) and now.get("playing"):
        title = now.get("title") or "Unknown"
        subtitle = now.get("subtitle") or ""
        progress = now.get("progress")
        frag = title
        if subtitle:
            frag += f" · {subtitle}"
        if progress not in (None, ""):
            frag += f" · {progress}%"
        parts.append(f"now_playing={frag}")
    else:
        parts.append("now_playing=idle")
    stats = snapshot.get("stats") or {}
    if isinstance(stats, dict):
        for key in ("cpu", "memory_free", "uptime", "temperature", "screen_resolution"):
            val = stats.get(key)
            if val not in (None, ""):
                parts.append(f"{key}={val}")
    volume = snapshot.get("volume") or {}
    if isinstance(volume, dict):
        vol = volume.get("volume")
        muted = volume.get("muted")
        if vol not in (None, ""):
            parts.append(f"volume={vol}{' muted' if muted else ''}")
    return " | ".join(parts) if parts else "<empty snapshot>"



# ----- test runner -----


@dataclass
class Step:
    """A single navigation or verification step inside a test."""
    action: str  # "open_helix" | "up" | "down" | "select" | "back" | "home" | "wait" | "screenshot"
    label: str = ""  # short description used in screenshot filename
    count: int = 1  # for repeated actions (e.g. down 3 times)
    hold_ms: Optional[int] = None  # for keyboard context menu
    mode: str = "kodi"  # "kodi" | "keyboard" | "auto"
    pre_wait: float = 0.05  # wait BEFORE the action (let UI settle)
    post_wait: float = 0.15  # wait AFTER the action (let UI render)


@dataclass
class TestResult:
    name: str
    description: str
    status: str  # "PASS" | "FAIL" | "WARN" | "ERROR"
    steps: list[dict] = field(default_factory=list)
    new_errors: int = 0
    error_samples: list[str] = field(default_factory=list)
    screenshots: list[str] = field(default_factory=list)
    duration_s: float = 0.0
    notes: str = ""


class TestRunner:
    def __init__(
        self,
        output_dir: Path,
        mode: str = "auto",  # "kodi" | "keyboard" | "auto"
        proxy_url: str = PROXY,
    ):
        self.output_dir = output_dir
        self.mode = mode
        self.wait_scale = STEP_WAIT_SCALE
        self.kodi = KodiClient(proxy_url)
        self.pad = GamepadClient()
        self.remote = RemotePlayClient()
        self.keyboard = KeyboardSuiteClient(cdp_url=XBOX_REMOTE_BASE)
        self.results: list[TestResult] = []
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def _sleep(self, seconds: float) -> None:
        if seconds <= 0:
            return
        time.sleep(seconds * self.wait_scale)

    # --- input dispatch ---

    def _do_input(self, step: Step, status: dict) -> tuple[dict, str]:
        """Send a single input action. Returns (response, used_mode)."""
        if step.action in ("open_helix", "wait", "screenshot"):
            return ({"ok": True, "skipped": True}, step.mode)

        # Determine the mode to use
        if step.mode == "auto":
            use_mode = "kodi" if status.get("connected") else "keyboard"
        else:
            use_mode = step.mode

        if use_mode == "kodi":
            resp = self.kodi.input(step.action)
            used = "kodi"
            # Auto-fallback on kodi error
            if not resp.get("ok", True) and self.mode == "auto":
                pad_resp = self.pad.tap(step.action, step.hold_ms)
                if pad_resp.get("ok"):
                    resp = {"ok": True, "via": "keyboard_fallback"}
                    used = "keyboard_fallback"
        else:
            resp = self.pad.tap(step.action, step.hold_ms)
            used = "keyboard"
        return resp, used

    def _screenshot(self, test_dir: Path, idx: int, label: str) -> str:
        """Capture one screenshot. Returns the file path (or '' on failure)."""
        safe = re.sub(r"[^a-zA-Z0-9_-]+", "_", label)[:50].strip("_") or "shot"
        fname = f"{idx:02d}_{safe}.png"
        out = test_dir / fname
        resp = self.pad.capture(str(out), delay_ms=200)
        return str(out) if resp.get("ok") else ""

    # --- test execution ---

    def run(self, test: dict) -> TestResult:
        name = test["name"]
        desc = test.get("description", name)
        result = TestResult(name=name, description=desc, status="PASS")
        test_dir = self.output_dir / name
        test_dir.mkdir(parents=True, exist_ok=True)
        t0 = time.time()

        # Pre-test status / logs
        status = self.kodi.status()
        before_logs = self.kodi.logs(300)

        # Step 0: open Helix at root (unless the test starts differently)
        if test.get("start", "open_helix") == "open_helix":
            before_live = self.kodi.live()
            print(f"    [live before] {summarize_live_snapshot(before_live)}")
            self._sleep(0.1)
            self.kodi.open_addon()
            self._sleep(1.0)  # addon load
            after_live = self.kodi.live()
            print(f"    [live after ] {summarize_live_snapshot(after_live)}")
            shot = self._screenshot(test_dir, 0, "open_helix_root")
            if shot:
                result.screenshots.append(shot)
            result.steps.append({
                "n": 0,
                "action": "open_helix",
                "label": "Open Helix at root",
                "screenshot": shot,
                "live_before": before_live,
                "live_after": after_live,
            })

        idx = 1
        for raw in test["steps"]:
            if isinstance(raw, dict):
                step = Step(**raw)
            else:
                step = Step(action=raw)
            if not step.label:
                step.label = step.action

            self._sleep(step.pre_wait)
            before_live = self.kodi.live()
            print(f"    [step {idx:02d} before] {summarize_live_snapshot(before_live)}")
            resp, used_mode = self._do_input(step, status)
            self._sleep(step.post_wait)
            after_live = self.kodi.live()
            print(f"    [step {idx:02d} after ] {summarize_live_snapshot(after_live)}")
            shot = self._screenshot(test_dir, idx, f"{step.action}_{step.label}")
            if shot:
                result.screenshots.append(shot)

            step_record = {
                "n": idx,
                "action": step.action,
                "count": step.count if step.action in ("up", "down", "left", "right") else 1,
                "label": step.label,
                "via": used_mode,
                "ok": resp.get("ok", True),
                "screenshot": shot,
                "live_before": before_live,
                "live_after": after_live,
            }
            if not resp.get("ok", True):
                step_record["error"] = resp.get("error") or resp.get("stderr") or "unknown"
                result.status = "WARN"
            result.steps.append(step_record)
            idx += 1

            # Repeat action N times if count > 1
            for _ in range(step.count - 1):
                self._sleep(min(step.pre_wait, 0.03))
                cont_before = self.kodi.live()
                print(f"    [step {idx:02d} before] {summarize_live_snapshot(cont_before)}")
                _resp, _used = self._do_input(step, status)
                self._sleep(min(step.post_wait, 0.08))
                cont_after = self.kodi.live()
                print(f"    [step {idx:02d} after ] {summarize_live_snapshot(cont_after)}")
                shot = self._screenshot(test_dir, idx, f"{step.action}_cont")
                if shot:
                    result.screenshots.append(shot)
                result.steps.append({
                    "n": idx,
                    "action": step.action,
                    "label": f"{step.label} (cont)",
                    "via": _used,
                    "ok": _resp.get("ok", True),
                    "screenshot": shot,
                    "live_before": cont_before,
                    "live_after": cont_after,
                })
                idx += 1

        # Post-test: fetch fresh logs and diff for new errors
        self._sleep(0.15)
        after_logs = self.kodi.logs(120)
        new_err_count, err_samples = count_new_errors(before_logs, after_logs)
        result.new_errors = new_err_count
        result.error_samples = err_samples[:5]
        if new_err_count > 0:
            result.status = "FAIL" if result.status == "PASS" else result.status
            if not result.notes:
                result.notes = f"{new_err_count} new Helix error(s) in kodi.log"
        result.duration_s = round(time.time() - t0, 2)

        self.results.append(result)
        return result

    def launch_remote_play(self) -> TestResult:
        """Setup step: ensure Xbox Remote Play is open/focused before menu tests."""
        result = TestResult(
            name="launch_xbox_remote_play",
            description="Launch/focus Xbox Remote Play before menu navigation tests",
            status="PASS",
        )
        t0 = time.time()
        setup_dir = self.output_dir / "_setup" / "launch_xbox_remote_play"
        setup_dir.mkdir(parents=True, exist_ok=True)

        resp = self.remote.launch()
        if not resp.get("ok", True):
            result.status = "WARN"
            result.notes = resp.get("error", "remote play launch failed")
        else:
            result.notes = f"{resp.get('mode')} | {resp.get('title') or resp.get('url') or 'Xbox Remote Play'}"

        # Capture one screenshot of the remote play surface after launch/focus.
        self._sleep(0.5)
        shot_path = setup_dir / "00_remote_play.png"
        shot = self.pad.capture(str(shot_path), delay_ms=250)
        if shot.get("ok"):
            result.screenshots.append(str(shot_path))
        else:
            result.status = "WARN" if result.status == "PASS" else result.status
            result.notes = (result.notes + " | " if result.notes else "") + "screenshot failed"

        result.steps.append({
            "n": 0,
            "action": "launch_remote_play",
            "label": "Launch Xbox Remote Play",
            "via": "cdp",
            "ok": resp.get("ok", True),
            "response": resp,
            "screenshot": str(shot_path) if shot.get("ok") else "",
        })
        result.duration_s = round(time.time() - t0, 2)
        self.results.append(result)
        return result

    def launch_keyboard_suite(self) -> TestResult:
        """Start browser-side keyboard/gamepad bridge for Remote Play."""
        result = TestResult(
            name="launch_keyboard_suite",
            description="Launch keyboard suite for Xbox Remote Play",
            status="PASS",
        )
        t0 = time.time()
        setup_dir = self.output_dir / "_setup" / "launch_keyboard_suite"
        setup_dir.mkdir(parents=True, exist_ok=True)

        resp = self.keyboard.launch()
        if not resp.get("ok", True):
            result.status = "WARN"
            result.notes = resp.get("error", "keyboard suite launch failed")
            output = resp.get("output") or []
            if output:
                result.notes += " | " + " ; ".join(output[-3:])
        else:
            result.notes = f"pid={resp.get('pid')} | {resp.get('line') or 'keyboard ready'}"

        result.steps.append({
            "n": 0,
            "action": "launch_keyboard_suite",
            "label": "Launch keyboard suite",
            "via": "cdp",
            "ok": resp.get("ok", True),
            "response": resp,
        })
        result.duration_s = round(time.time() - t0, 2)
        self.results.append(result)
        return result

    def shutdown(self) -> None:
        self.keyboard.stop()

    def preflight_checklist(self, remote_setup: Optional[dict] = None, keyboard_setup: Optional[dict] = None) -> list[dict]:
        """Return compact ready/not-ready state for Remote Play preflight."""
        remote_up = self.remote.is_up()
        pages = self.remote.list_pages() if remote_up else []
        xbox_page = next(
            (page for page in pages if "xbox.com/play" in page.get("url", "") or "xboxplay" in page.get("url", "")),
            None,
        )
        consoles_page = next(
            (page for page in pages if XBOX_REMOTE_URL in page.get("url", "")),
            None,
        )
        keyboard_proc = self.keyboard.proc
        keyboard_ready = bool(keyboard_proc and keyboard_proc.poll() is None)
        keyboard_pid = getattr(keyboard_proc, "pid", None) if keyboard_proc else None
        if keyboard_setup and keyboard_setup.get("pid"):
            keyboard_pid = keyboard_setup["pid"]

        chrome_ok = bool(remote_setup and remote_setup.get("chrome", {}).get("started")) or remote_up
        xbox_ok = bool(remote_setup and remote_setup.get("ok")) or xbox_page is not None
        consoles_ok = bool(remote_setup and remote_setup.get("url") == XBOX_REMOTE_URL) or consoles_page is not None
        bridge_ok = bool(keyboard_setup and keyboard_setup.get("ok")) or keyboard_ready
        shim_ok = bridge_ok and keyboard_ready

        return [
            {
                "label": "Chrome/CDP",
                "ok": chrome_ok,
                "detail": remote_setup.get("mode") if remote_setup else ("9222 up" if remote_up else "9222 down"),
            },
            {
                "label": "Xbox session",
                "ok": xbox_ok,
                "detail": (xbox_page or {}).get("title") or (remote_setup or {}).get("title") or "no Xbox tab",
            },
            {
                "label": "consoles page",
                "ok": consoles_ok,
                "detail": (consoles_page or {}).get("url") or (remote_setup or {}).get("url") or XBOX_REMOTE_URL,
            },
            {
                "label": "keyboard bridge",
                "ok": bridge_ok,
                "detail": f"pid={keyboard_pid}" if keyboard_pid else "not launched",
            },
            {
                "label": "gamepad shim",
                "ok": shim_ok,
                "detail": "virtual gamepad ready" if shim_ok else "not ready",
            },
        ]

    def print_preflight_checklist(self, remote_setup: Optional[dict] = None, keyboard_setup: Optional[dict] = None) -> None:
        items = self.preflight_checklist(remote_setup=remote_setup, keyboard_setup=keyboard_setup)
        print("[preflight] checklist")
        for item in items:
            mark = "OK" if item["ok"] else "NO"
            print(f"  - {item['label']:<16} {mark:<2}  {item['detail']}")

    def report(self) -> dict:
        out = {
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "output_dir": str(self.output_dir),
            "mode": self.mode,
            "summary": {
                "total": len(self.results),
                "pass": sum(1 for r in self.results if r.status == "PASS"),
                "warn": sum(1 for r in self.results if r.status == "WARN"),
                "fail": sum(1 for r in self.results if r.status == "FAIL"),
            },
            "tests": [
                {
                    "name": r.name, "description": r.description, "status": r.status,
                    "duration_s": r.duration_s, "new_errors": r.new_errors,
                    "error_samples": r.error_samples, "screenshots": r.screenshots,
                    "notes": r.notes, "steps": r.steps,
                }
                for r in self.results
            ],
        }
        return out


# ----- test definitions -----
#
# Each test: dict with `name`, optional `description`, optional `start`, and `steps`.
# Steps are dicts matching Step fields, or short strings ("up", "down", "select", etc.).
#
# Browse home layout (with section headers as positions):
#   1: SWITCH TO TOOLS   2: ── Browse ──   3: Movies   4: TV Shows   5: Anime
#   6: ── Discover ──    7: Trending   8: Popular   9: Genres   10: Discover
#   11: ── Search ──     12: Search
#   13: ── Library ──    14: Favorites   15: Trakt Watchlist (conditional)
#   16: ── Settings & Tools ──  17: Helix Settings…  18: Dashboard  19: Trakt Account (cond)
#
# Tools home layout:
#   1: SWITCH TO BROWSE   2: ── Accounts ──   3: Account Manager
#   4: ── Scrapers & Indexers ──   5: Test All Indexers   6: Indexer Status
#   7: ── Maintenance ──   8: Maintenance   9: Backup/Restore   10: Tools   11: Notifications
#   12: ── Settings ──   13: Helix Settings…
#
# Indices use the `down` count from the STARTING row.


TESTS: list[dict] = [
    # ---------- ADDON LOAD ----------
    {
        "name": "open_addon",
        "description": "Open Helix at root — verify add-on loads without errors",
        "steps": [],
    },

    # ---------- BROWSE: Movies / TV / Anime (positions 3,4,5) ----------
    {
        "name": "browse_movies",
        "description": "Navigate Browse → Movies and confirm the screen renders",
        # Topbar (1) → ── Browse ── (2) → Movies (3) = 2 downs
        "steps": [
            {"action": "down", "label": "skip_topbar", "count": 2},
            {"action": "select", "label": "open_movies", "post_wait": 0.5},
            {"action": "back", "label": "back_to_root", "post_wait": 0.75},
        ],
    },
    {
        "name": "browse_tv",
        "description": "Navigate Browse → TV Shows and confirm the screen renders",
        # Topbar (1) → ── Browse ── (2) → Movies (3) → TV (4) = 3 downs
        "steps": [
            {"action": "down", "label": "skip_to_tv", "count": 3},
            {"action": "select", "label": "open_tv", "post_wait": 0.5},
            {"action": "back", "label": "back_to_root", "post_wait": 0.75},
        ],
    },
    {
        "name": "browse_anime",
        "description": "Navigate Browse → Anime and confirm the screen renders",
        # 4 downs
        "steps": [
            {"action": "down", "label": "skip_to_anime", "count": 4},
            {"action": "select", "label": "open_anime", "post_wait": 0.5},
            {"action": "back", "label": "back_to_root", "post_wait": 0.75},
        ],
    },

    # ---------- DISCOVER: Trending / Popular / Genres / Discover ----------
    {
        "name": "browse_trending",
        "description": "Navigate Discover → Trending and confirm screen renders",
        # 5: Anime. 6: ── Discover ──. 7: Trending = 6 downs
        "steps": [
            {"action": "down", "label": "skip_to_trending", "count": 6},
            {"action": "select", "label": "open_trending", "post_wait": 0.5},
            {"action": "back", "label": "back_to_root", "post_wait": 0.75},
        ],
    },
    {
        "name": "browse_popular",
        "description": "Navigate Discover → Popular and confirm screen renders",
        "steps": [
            {"action": "down", "label": "skip_to_popular", "count": 7},
            {"action": "select", "label": "open_popular", "post_wait": 0.5},
            {"action": "back", "label": "back_to_root", "post_wait": 0.75},
        ],
    },
    {
        "name": "browse_genres",
        "description": "Navigate Discover → Genres and confirm screen renders",
        "steps": [
            {"action": "down", "label": "skip_to_genres", "count": 8},
            {"action": "select", "label": "open_genres", "post_wait": 0.5},
            {"action": "back", "label": "back_to_root", "post_wait": 0.75},
        ],
    },
    {
        "name": "browse_discover",
        "description": "Navigate Discover → Discover (TMDB) and confirm screen renders",
        "steps": [
            {"action": "down", "label": "skip_to_discover", "count": 9},
            {"action": "select", "label": "open_discover", "post_wait": 0.5},
            {"action": "back", "label": "back_to_root", "post_wait": 0.75},
        ],
    },

    # ---------- SEARCH ----------
    {
        "name": "browse_search",
        "description": "Open the search dialog (no text input)",
        # 10: Discover. 11: ── Search ──. 12: Search = 11 downs
        "steps": [
            {"action": "down", "label": "skip_to_search", "count": 11},
            {"action": "select", "label": "open_search", "post_wait": 0.5},
            {"action": "back", "label": "close_keyboard", "post_wait": 1.5},
            {"action": "back", "label": "back_to_root", "post_wait": 1.0},
        ],
    },

    # ---------- LIBRARY ----------
    {
        "name": "browse_favorites",
        "description": "Open Library → Favorites",
        # 12: Search. 13: ── Library ──. 14: Favorites = 13 downs
        "steps": [
            {"action": "down", "label": "skip_to_favorites", "count": 13},
            {"action": "select", "label": "open_favorites", "post_wait": 0.5},
            {"action": "back", "label": "back_to_root", "post_wait": 0.75},
        ],
    },

    # ---------- SETTINGS / DASHBOARD (no auth required) ----------
    {
        "name": "open_helix_settings",
        "description": "Open Helix Settings dialog",
        # ── Settings & Tools ── section header is around pos 15, Helix Settings at 16
        # (Favorites 14, Trakt Watchlist 15 if present, ── Settings ── 16, Helix Settings 17)
        # Without trakt: 14 Favorites, 15 ── Settings ──, 16 Helix Settings = 15 downs
        "steps": [
            {"action": "down", "label": "skip_to_settings", "count": 15},
            {"action": "select", "label": "open_settings", "post_wait": 0.5},
            {"action": "back", "label": "close_settings", "post_wait": 0.5},
            {"action": "back", "label": "back_to_root", "post_wait": 0.75},
        ],
    },
    {
        "name": "open_dashboard",
        "description": "Open Helix Dashboard (debug, logs, settings editor)",
        "steps": [
            {"action": "down", "label": "skip_to_dashboard", "count": 16},
            {"action": "select", "label": "open_dashboard", "post_wait": 0.5},
            {"action": "back", "label": "back_to_root", "post_wait": 0.75},
        ],
    },

    # ---------- TOOLS: Account Manager / Test Indexers / Indexer Status / Maintenance ----------
    {
        "name": "switch_to_tools",
        "description": "Switch from Browse to Tools home via top-bar action",
        "start": "open_helix",
        "steps": [
            {"action": "select", "label": "switch_to_tools", "post_wait": 0.5},
        ],
    },
    {
        "name": "tools_account_manager",
        "description": "Tools → Account Manager — render and back out",
        "start": "open_helix",  # root
        "steps": [
            {"action": "select", "label": "switch_to_tools", "post_wait": 0.5},
            # Tools layout: 1 SWITCH TO BROWSE, 2 ── Accounts ──, 3 Account Manager = 2 downs
            {"action": "down", "label": "skip_to_accounts", "count": 2},
            {"action": "select", "label": "open_account_manager", "post_wait": 0.5},
            {"action": "back", "label": "back_to_tools", "post_wait": 0.75},
            {"action": "select", "label": "switch_back_to_browse", "post_wait": 0.5},
        ],
    },
    {
        "name": "tools_test_indexers",
        "description": "Tools → Test All Indexers — runs network tests on Torrentio/Comet/BitMagnet",
        "start": "open_helix",
        "steps": [
            {"action": "select", "label": "switch_to_tools", "post_wait": 0.5},
            # 4: ── Scrapers ──, 5: Test All Indexers = 4 downs
            {"action": "down", "label": "skip_to_test_indexers", "count": 4},
            {"action": "select", "label": "run_test_indexers", "post_wait": 6.0},
            # text_viewer result is on screen; take a few more shots to capture results text
            {"action": "screenshot", "label": "indexer_results", "post_wait": 0.5},
            {"action": "back", "label": "back_to_tools", "post_wait": 0.75},
            {"action": "select", "label": "switch_back_to_browse", "post_wait": 0.5},
        ],
    },
    {
        "name": "tools_indexer_status",
        "description": "Tools → Indexer Status — display current indexer configuration",
        "start": "open_helix",
        "steps": [
            {"action": "select", "label": "switch_to_tools", "post_wait": 0.5},
            # 5: Test All Indexers, 6: Indexer Status = 5 downs
            {"action": "down", "label": "skip_to_indexer_status", "count": 5},
            {"action": "select", "label": "show_indexer_status", "post_wait": 5.0},
            {"action": "screenshot", "label": "indexer_status_results", "post_wait": 0.5},
            {"action": "back", "label": "back_to_tools", "post_wait": 0.75},
            {"action": "select", "label": "switch_back_to_browse", "post_wait": 0.5},
        ],
    },
    {
        "name": "tools_maintenance",
        "description": "Tools → Maintenance — render and back out",
        "start": "open_helix",
        "steps": [
            {"action": "select", "label": "switch_to_tools", "post_wait": 0.5},
            # 7: ── Maintenance ──, 8: Maintenance = 7 downs
            {"action": "down", "label": "skip_to_maintenance", "count": 7},
            {"action": "select", "label": "open_maintenance", "post_wait": 0.5},
            {"action": "back", "label": "back_to_tools", "post_wait": 0.75},
            {"action": "select", "label": "switch_back_to_browse", "post_wait": 0.5},
        ],
    },
    {
        "name": "tools_backup_restore",
        "description": "Tools → Backup / Restore — render and back out",
        "start": "open_helix",
        "steps": [
            {"action": "select", "label": "switch_to_tools", "post_wait": 0.5},
            # 8: Maintenance, 9: Backup / Restore = 8 downs
            {"action": "down", "label": "skip_to_backup", "count": 8},
            {"action": "select", "label": "open_backup", "post_wait": 0.5},
            {"action": "back", "label": "back_to_tools", "post_wait": 0.75},
            {"action": "select", "label": "switch_back_to_browse", "post_wait": 0.5},
        ],
    },
    {
        "name": "tools_submenu",
        "description": "Tools → Tools (submenu: speedtest, view logs, force update)",
        "start": "open_helix",
        "steps": [
            {"action": "select", "label": "switch_to_tools", "post_wait": 0.5},
            # 9: Backup, 10: Tools = 9 downs
            {"action": "down", "label": "skip_to_tools_sub", "count": 9},
            {"action": "select", "label": "open_tools_sub", "post_wait": 0.5},
            {"action": "back", "label": "back_to_tools", "post_wait": 0.75},
            {"action": "select", "label": "switch_back_to_browse", "post_wait": 0.5},
        ],
    },
    {
        "name": "tools_notifications",
        "description": "Tools → Notifications — render and back out",
        "start": "open_helix",
        "steps": [
            {"action": "select", "label": "switch_to_tools", "post_wait": 0.5},
            # 10: Tools, 11: Notifications = 10 downs
            {"action": "down", "label": "skip_to_notifications", "count": 10},
            {"action": "select", "label": "open_notifications", "post_wait": 0.5},
            {"action": "back", "label": "back_to_tools", "post_wait": 0.75},
            {"action": "select", "label": "switch_back_to_browse", "post_wait": 0.5},
        ],
    },
]


# ----- CLI -----


def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Helix Kodi add-on automated test suite")
    p.add_argument("--proxy", default=PROXY, help="kodi-xbox-proxy URL")
    p.add_argument("--xbox-drive", default=str(XBOX_DRIVE), help="path to xbox-drive.mjs")
    p.add_argument("--output-dir", default=str(DEFAULT_OUTPUT), help="where to save screenshots + report")
    p.add_argument("--mode", choices=["kodi", "keyboard", "auto"], default="auto",
                   help="primary navigation mode (default: kodi with keyboard fallback)")
    p.add_argument("--filter", dest="filter_re", default=None,
                   help="run only tests whose name matches this regex")
    p.add_argument("--from", dest="from_test", default=None, help="start from this test name")
    p.add_argument("--to", dest="to_test", default=None, help="stop after this test name")
    p.add_argument("--list", action="store_true", help="print the test plan and exit")
    p.add_argument("--dry-run", action="store_true", help="print plan, don't execute")
    p.add_argument("--skip-remote-play-launch", action="store_true",
                   help="do not launch/focus Xbox Remote Play before tests")
    p.add_argument("--skip-keyboard-launch", action="store_true",
                   help="do not auto-launch keyboard suite after Remote Play setup")
    p.add_argument("--status", action="store_true", help="print proxy + xbox status and exit")
    return p.parse_args(argv)


def print_plan(tests: list[dict], runner: TestRunner) -> None:
    print(f"\nPlan: {len(tests)} test(s)  mode={runner.mode}  output={runner.output_dir}\n")
    for i, t in enumerate(tests, 1):
        n_steps = len(t.get("steps", []))
        print(f"  {i:2d}. {t['name']:30s}  {n_steps} step(s)  — {t.get('description','')}")


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    output_dir = Path(args.output_dir)

    # Filter tests
    tests = list(TESTS)
    if args.from_test:
        idx = next((i for i, t in enumerate(tests) if t["name"] == args.from_test), 0)
        tests = tests[idx:]
    if args.to_test:
        idx = next((i for i, t in enumerate(tests) if t["name"] == args.to_test), len(tests))
        tests = tests[: idx + 1]
    if args.filter_re:
        rx = re.compile(args.filter_re)
        tests = [t for t in tests if rx.search(t["name"])]

    runner = TestRunner(output_dir=output_dir, mode=args.mode, proxy_url=args.proxy)

    if args.status:
        st = runner.kodi.status()
        print("Proxy status:")
        print(json.dumps(st, indent=2))
        return 0

    if args.list or args.dry_run:
        print_plan(tests, runner)
        if args.dry_run:
            print("\n(dry run, no actions taken)")
        return 0

    if not tests:
        print("No tests matched the filter.", file=sys.stderr)
        return 2

    # Verify proxy reachable
    status = runner.kodi.status()
    if not status.get("connected"):
        print(f"⚠️  kodi-xbox-proxy not connected: {status.get('error','unknown')}", file=sys.stderr)
        print(f"   continuing in mode={args.mode} (fallback to keyboard may engage)")

    print_plan(tests, runner)
    print()

    report = None
    remote_result = None
    keyboard_result = None
    remote_setup = None
    keyboard_setup = None
    try:
        if not args.skip_remote_play_launch:
            remote_result = runner.launch_remote_play()
            remote_setup = remote_result.steps[0].get("response") if remote_result.steps else None
            tag = {"PASS": "✓", "WARN": "⚠", "FAIL": "✗", "ERROR": "!"}[remote_result.status]
            print(f"[setup] xbox remote play ... {tag} {remote_result.status}  {remote_result.duration_s:.1f}s")
            if remote_result.notes:
                print(f"        {remote_result.notes}")
            print()

            if not args.skip_keyboard_launch:
                keyboard_result = runner.launch_keyboard_suite()
                keyboard_setup = keyboard_result.steps[0].get("response") if keyboard_result.steps else None
                ktag = {"PASS": "✓", "WARN": "⚠", "FAIL": "✗", "ERROR": "!"}[keyboard_result.status]
                print(f"[setup] keyboard suite ... {ktag} {keyboard_result.status}  {keyboard_result.duration_s:.1f}s")
                if keyboard_result.notes:
                    print(f"        {keyboard_result.notes}")
                print()

        runner.print_preflight_checklist(remote_setup=remote_setup, keyboard_setup=keyboard_setup)
        print()

        for i, t in enumerate(tests, 1):
            print(f"[{i:2d}/{len(tests):2d}] {t['name']} ...", end=" ", flush=True)
            try:
                r = runner.run(t)
                tag = {"PASS": "✓", "WARN": "⚠", "FAIL": "✗", "ERROR": "!"}[r.status]
                extra = f"  (+{r.new_errors} err)" if r.new_errors else ""
                print(f"{tag} {r.status}  {r.duration_s:.1f}s  shots={len(r.screenshots)}{extra}")
                if r.error_samples:
                    for ln in r.error_samples[:2]:
                        print(f"      ↳ {ln[:160]}")
            except KeyboardInterrupt:
                print("\ninterrupted")
                break
            except Exception as exc:
                print(f"ERROR  {exc!r}")
                runner.results.append(TestResult(
                    name=t["name"], description=t.get("description", ""), status="ERROR",
                    notes=repr(exc),
                ))

        # Final report
        report = runner.report()
        report_path = output_dir / "report.json"
        report_path.write_text(json.dumps(report, indent=2))

        s = report["summary"]
        print()
        print(f"Summary: {s['pass']} PASS  {s['warn']} WARN  {s['fail']} FAIL  /  {s['total']} total")
        print(f"Report: {report_path}")
        print(f"Screenshots: {output_dir}/<test>/<NN>_<action>.png")
    finally:
        runner.shutdown()

    if report is None:
        return 1
    return 0 if report["summary"]["fail"] == 0 else 1



if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
