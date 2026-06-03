from __future__ import annotations

import re
import sys
from pathlib import Path

from resources.lib import router


MODULE_CALL_RE = re.compile(
    r"\b((?:menus|account_manager|maintenance|backup|speedtest|tools_mod|dashboard|m3u|tmdb|debrid|indexers|trakt)\.[A-Za-z_][A-Za-z0-9_]*)\s*\("
)


def _dispatch(action: str | None):
    sys.argv = ["plugin.video.helix/default.py", "7"]
    if action is None:
        router.dispatch("")
    else:
        router.dispatch(f"action={action}")


def _extract_route_bodies():
    src = Path(router.__file__).read_text(encoding="utf-8")
    routes: dict[str, str] = {}

    home_match = re.search(
        r'if action is None or action == "home":\s*(?P<body>.*?)^\s*elif action == "tools":',
        src,
        flags=re.S | re.M,
    )
    if home_match:
        routes["home"] = home_match.group("body")

    split = re.split(r'^\s*elif action == "([^"]+)":\s*$', src, flags=re.M)
    for idx in range(1, len(split), 2):
        action = split[idx]
        body = split[idx + 1].split("\n    else:", 1)[0]
        routes.setdefault(action, body)
    return routes


def test_router_dispatch_reaches_every_page_entrypoint(monkeypatch, kodi_env):
    routes = _extract_route_bodies()

    # Patch every direct module call the router makes so each branch becomes a
    # cheap, deterministic contract test.
    seen: list[str] = []

    def recorder(name):
        def _call(*args, **kwargs):
            seen.append(name)
        return _call

    for action, body in routes.items():
        module_calls = MODULE_CALL_RE.findall(body)
        for call in module_calls:
            mod_name, func_name = call.split(".", 1)
            monkeypatch.setattr(getattr(router, mod_name), func_name, recorder(call))

        if "get_addon().openSettings()" in body:
            class _Addon:
                def openSettings(self):
                    seen.append("get_addon.openSettings")

            monkeypatch.setattr(router, "get_addon", lambda: _Addon())

        _dispatch(None if action == "home" else action)

        expected = set(module_calls)
        if "get_addon().openSettings()" in body:
            expected.add("get_addon.openSettings")
        assert expected.issubset(set(seen)), f"route {action} missed {expected - set(seen)}"
        seen.clear()

    # Unknown route falls back to browse home.
    monkeypatch.setattr(router.menus, "browse_home", recorder("menus.browse_home"))
    _dispatch("does_not_exist")
    assert seen == ["menus.browse_home"]
