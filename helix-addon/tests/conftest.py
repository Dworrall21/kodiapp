from __future__ import annotations

import os
import sys
import types
from dataclasses import dataclass, field
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / "src/plugin.video.helix"
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))


@dataclass
class Harness:
    logs: list[tuple[int, str]] = field(default_factory=list)
    calls: list[tuple[str, tuple, dict]] = field(default_factory=list)
    directory_items: list[dict] = field(default_factory=list)
    resolved_urls: list[dict] = field(default_factory=list)
    notifications: list[dict] = field(default_factory=list)
    dialogs: list[tuple[str, tuple, dict]] = field(default_factory=list)
    builtin_calls: list[str] = field(default_factory=list)
    settings: dict[str, str] = field(default_factory=dict)
    addon_info: dict[str, str] = field(default_factory=lambda: {
        "id": "plugin.video.helix",
        "name": "Helix",
        "version": "0.4.1",
        "profile": "/tmp/helix-profile",
        "path": str(APP_ROOT),
        "icon": "icon.png",
        "fanart": "fanart.jpg",
    })
    info_labels: dict[str, str] = field(default_factory=dict)
    cond_visibility: dict[str, bool] = field(default_factory=dict)
    yesno_result: bool = True
    select_result: int = 0
    input_result: str = ""

    def reset(self) -> None:
        self.logs.clear()
        self.calls.clear()
        self.directory_items.clear()
        self.resolved_urls.clear()
        self.notifications.clear()
        self.dialogs.clear()
        self.builtin_calls.clear()
        self.settings.clear()
        self.info_labels.clear()
        self.cond_visibility.clear()
        self.yesno_result = True
        self.select_result = 0
        self.input_result = ""


HARNESS = Harness()


class FakeListItem:
    def __init__(self, label=""):
        self.label = label
        self.info = {}
        self.info_type = None
        self.art = {}
        self.properties = {}
        self.context = []
        self.path = ""
        self.mime = ""

    def setInfo(self, info_type, info):
        self.info_type = info_type
        self.info.update(info or {})

    def setArt(self, art):
        self.art.update(art or {})

    def setProperty(self, key, value):
        self.properties[key] = value

    def addContextMenuItems(self, items):
        self.context.extend(items or [])

    def setPath(self, path):
        self.path = path

    def setMimeType(self, mime):
        self.mime = mime


class FakeDialog:
    def notification(self, title, message, icon, duration_ms, level):
        HARNESS.notifications.append({
            "title": title,
            "message": message,
            "icon": icon,
            "duration": duration_ms,
            "level": level,
        })

    def yesno(self, title, message, nolabel="No", yeslabel="Yes"):
        HARNESS.dialogs.append(("yesno", (title, message), {"nolabel": nolabel, "yeslabel": yeslabel}))
        return HARNESS.yesno_result

    def textviewer(self, title, body):
        HARNESS.dialogs.append(("textviewer", (title, body), {}))

    def select(self, title, options):
        HARNESS.dialogs.append(("select", (title, tuple(options)), {}))
        return HARNESS.select_result

    def input(self, title, default=""):
        HARNESS.dialogs.append(("input", (title, default), {}))
        return HARNESS.input_result


class FakeAddon:
    def __init__(self):
        self.info = HARNESS.addon_info

    def getAddonInfo(self, key):
        return self.info.get(key, "")

    def getSetting(self, key):
        return HARNESS.settings.get(key, "")

    def setSetting(self, key, value):
        HARNESS.settings[key] = str(value)

    def openSettings(self):
        HARNESS.calls.append(("openSettings", (), {}))


xbmc = types.ModuleType("xbmc")
xbmc.LOGDEBUG = 0
xbmc.LOGINFO = 1
xbmc.LOGWARNING = 2
xbmc.LOGERROR = 3
xbmc.log = lambda message, level=0: HARNESS.logs.append((level, str(message)))
xbmc.executebuiltin = lambda command: HARNESS.builtin_calls.append(command)
xbmc.getInfoLabel = lambda label: HARNESS.info_labels.get(label, "")
xbmc.getCondVisibility = lambda expr: HARNESS.cond_visibility.get(expr, False)

xbmcgui = types.ModuleType("xbmcgui")
xbmcgui.NOTIFICATION_INFO = 10
xbmcgui.NOTIFICATION_WARNING = 11
xbmcgui.NOTIFICATION_ERROR = 12
xbmcgui.Dialog = lambda: FakeDialog()
xbmcgui.ListItem = FakeListItem

xbmcplugin = types.ModuleType("xbmcplugin")
xbmcplugin.SORT_METHOD_LABEL = 0
xbmcplugin.SORT_METHOD_TITLE = 1
xbmcplugin.SORT_METHOD_DATE = 2
xbmcplugin.addDirectoryItem = lambda handle, url, li, isFolder=True: HARNESS.directory_items.append({
    "handle": handle,
    "url": url,
    "isFolder": isFolder,
    "label": getattr(li, "label", ""),
    "item": li,
}) or True
xbmcplugin.endOfDirectory = lambda handle, succeeded=True, updateListing=False: HARNESS.calls.append(("endOfDirectory", (handle,), {"succeeded": succeeded, "updateListing": updateListing}))
xbmcplugin.setContent = lambda handle, content: HARNESS.calls.append(("setContent", (handle, content), {}))
xbmcplugin.addSortMethod = lambda handle, sort: HARNESS.calls.append(("addSortMethod", (handle, sort), {}))
xbmcplugin.setResolvedUrl = lambda handle, succeeded, li: HARNESS.resolved_urls.append({"handle": handle, "succeeded": succeeded, "item": li})

xbmcaddon = types.ModuleType("xbmcaddon")
xbmcaddon.Addon = lambda *args, **kwargs: FakeAddon()

xbmcvfs = types.ModuleType("xbmcvfs")
xbmcvfs.translatePath = lambda path: path
xbmcvfs.exists = lambda path: os.path.exists(path)

sys.modules.update({
    "xbmc": xbmc,
    "xbmcgui": xbmcgui,
    "xbmcplugin": xbmcplugin,
    "xbmcaddon": xbmcaddon,
    "xbmcvfs": xbmcvfs,
})


@pytest.fixture(autouse=True)
def kodi_env():
    HARNESS.reset()
    if "resources.lib.utils" in sys.modules:
        import resources.lib.utils as utils
        utils._addon_handle = 0
        utils._addon_obj = None
        utils._nav_state = {
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
    yield HARNESS
