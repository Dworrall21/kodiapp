"""Repository and add-on package management helpers."""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import socket
import subprocess
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

PACKAGE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_DIR.parents[1]
ADDON_ID = "script.xbox.proxy"
REPOSITORY_ID = "repository.dworrall21"
GH_PAGES_URL = "https://dworrall21.github.io/kodiapp/"

ADDON_DIR = PROJECT_ROOT / "addon"
ADDON_XML = ADDON_DIR / "addon.xml"
ADDONS_XML = PROJECT_ROOT / "addons.xml"
ADDON_ZIP = PROJECT_ROOT / "addon.zip"
REPO_STATIC = PROJECT_ROOT / "repo_static"
REPO_ADDON_DIR = REPO_STATIC / ADDON_ID
GH_PAGES_WORKTREE = Path("/tmp/kodiapp-gh-pages-wt")


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def get_lan_ip() -> str:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 80))
        return sock.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        sock.close()


def addon_version() -> str:
    root = ET.parse(ADDON_XML).getroot()
    return root.attrib.get("version", "unknown")


def repo_version(addons_xml: Path = ADDONS_XML) -> str | None:
    if not addons_xml.exists():
        return None
    root = ET.parse(addons_xml).getroot()
    for addon in root.findall("addon"):
        if addon.attrib.get("id") == ADDON_ID:
            return addon.attrib.get("version")
    return None


def latest_repo_zip() -> dict:
    REPO_ADDON_DIR.mkdir(parents=True, exist_ok=True)
    pattern = re.compile(rf"{re.escape(ADDON_ID)}-(.+)\.zip$")
    items = []
    for path in REPO_ADDON_DIR.glob(f"{ADDON_ID}-*.zip"):
        match = pattern.match(path.name)
        items.append({
            "name": path.name,
            "version": match.group(1) if match else "unknown",
            "path": str(path),
            "size": path.stat().st_size,
        })
    items.sort(key=lambda x: x["name"], reverse=True)
    return items[0] if items else {}


def status() -> dict:
    lan_ip = get_lan_ip()
    return {
        "addon_id": ADDON_ID,
        "repository_id": REPOSITORY_ID,
        "source_label": "kodiapp",
        "local_source_url": f"http://{lan_ip}:8080/repo/",
        "gh_pages_url": GH_PAGES_URL,
        "source_candidates": [f"http://{lan_ip}:8080/repo/", GH_PAGES_URL],
        "source_addon_version": addon_version(),
        "local_metadata_version": repo_version(ADDONS_XML),
        "static_metadata_version": repo_version(REPO_STATIC / "addons.xml"),
        "latest_static_zip": latest_repo_zip(),
        "addon_zip_exists": ADDON_ZIP.exists(),
        "addon_zip_size": ADDON_ZIP.stat().st_size if ADDON_ZIP.exists() else 0,
        "gh_pages_worktree": str(GH_PAGES_WORKTREE),
        "gh_pages_worktree_exists": GH_PAGES_WORKTREE.exists(),
    }


def set_version(version: str) -> dict:
    if not re.match(r"^\d+\.\d+\.\d+(?:[-+][A-Za-z0-9_.-]+)?$", version):
        raise ValueError("Version must look like 1.2.3")

    text = _read_text(ADDON_XML)
    text = re.sub(r'(<addon\b[^>]*\bversion=")[^"]+("[^>]*>)', rf'\g<1>{version}\2', text, count=1)
    _write_text(ADDON_XML, text)

    default_py = ADDON_DIR / "default.py"
    py_text = _read_text(default_py)
    py_text = re.sub(r'(info\["addon_version"\]\s*=\s*")[^"]+(")', rf'\g<1>{version}\2', py_text, count=1)
    _write_text(default_py, py_text)
    update_addons_xml(version)
    return status()


def update_addons_xml(version: str | None = None) -> None:
    version = version or addon_version()
    for path in (ADDONS_XML, REPO_STATIC / "addons.xml"):
        if not path.exists():
            continue
        text = _read_text(path)
        text = re.sub(
            rf'(<addon id="{re.escape(ADDON_ID)}"[^>]*\bversion=")[^"]+("[^>]*>)',
            rf'\g<1>{version}\2',
            text,
            count=1,
        )
        # Keep dependencies minimal and aligned with addon/addon.xml. The proxy add-on
        # only needs xbmc.python; stale script.module.six imports previously broke updates.
        text = re.sub(r'\n\s*<import addon="script\.module\.six"[^>]*/>', "", text)
        _write_text(path, text)
        write_md5(path)


def write_md5(addons_xml: Path) -> None:
    digest = hashlib.md5(addons_xml.read_bytes()).hexdigest()
    _write_text(addons_xml.with_suffix(addons_xml.suffix + ".md5"), digest)


def build_package(version: str | None = None) -> dict:
    if version:
        set_version(version)
    version = addon_version()
    build_dir = PROJECT_ROOT / "build_pkg"
    if build_dir.exists():
        shutil.rmtree(build_dir)
    package_root = build_dir / ADDON_ID
    shutil.copytree(ADDON_DIR, package_root)
    for pycache in package_root.rglob("__pycache__"):
        shutil.rmtree(pycache, ignore_errors=True)
    for pyc in package_root.rglob("*.pyc"):
        pyc.unlink(missing_ok=True)
    if ADDON_ZIP.exists():
        ADDON_ZIP.unlink()
    with zipfile.ZipFile(ADDON_ZIP, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(package_root.rglob("*")):
            if path.is_file():
                zf.write(path, path.relative_to(build_dir))
    validation = validate_zip(ADDON_ZIP)
    if not validation["ok"]:
        raise RuntimeError(validation["error"])
    return {"version": version, "zip": str(ADDON_ZIP), "validation": validation, "size": ADDON_ZIP.stat().st_size}


def validate_zip(path: Path = ADDON_ZIP) -> dict:
    try:
        with zipfile.ZipFile(path) as zf:
            bad = zf.testzip()
            names = zf.namelist()
            root_ok = f"{ADDON_ID}/addon.xml" in names
            internal_xml = zf.read(f"{ADDON_ID}/addon.xml").decode("utf-8") if root_ok else ""
            internal_version = None
            if internal_xml:
                internal_version = ET.fromstring(internal_xml).attrib.get("version")
            if bad:
                return {"ok": False, "error": f"Corrupt zip member: {bad}", "entries": len(names)}
            if not root_ok:
                return {"ok": False, "error": f"Missing {ADDON_ID}/addon.xml", "entries": len(names)}
            return {"ok": True, "entries": len(names), "internal_version": internal_version, "root": ADDON_ID}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def publish_local() -> dict:
    version = addon_version()
    if not ADDON_ZIP.exists():
        build_package(version)
    update_addons_xml(version)
    REPO_ADDON_DIR.mkdir(parents=True, exist_ok=True)
    target = REPO_ADDON_DIR / f"{ADDON_ID}-{version}.zip"
    shutil.copy2(ADDON_ZIP, target)
    shutil.copy2(ADDON_ZIP, REPO_STATIC / "addon.zip")
    update_package_index()
    return {"version": version, "target": str(target), "status": status()}


def update_package_index() -> None:
    REPO_ADDON_DIR.mkdir(parents=True, exist_ok=True)
    zips = sorted(REPO_ADDON_DIR.glob(f"{ADDON_ID}-*.zip"), reverse=True)
    rows = "\n".join(f'  <li><a href="{p.name}">{p.name}</a></li>' for p in zips)
    _write_text(REPO_ADDON_DIR / "index.html", f"<!DOCTYPE html>\n<html><head><title>{ADDON_ID}</title></head>\n<body>\n<h1>{ADDON_ID}</h1>\n<ul>\n{rows}\n</ul>\n</body></html>\n")


def deploy_gh_pages() -> dict:
    if not GH_PAGES_WORKTREE.exists():
        raise RuntimeError(f"gh-pages worktree not found: {GH_PAGES_WORKTREE}")
    subprocess.run(["git", "pull", "--rebase", "origin", "gh-pages"], cwd=GH_PAGES_WORKTREE, check=True, capture_output=True, text=True)
    for item in REPO_STATIC.iterdir():
        dest = GH_PAGES_WORKTREE / item.name
        if item.is_dir():
            if dest.exists():
                shutil.rmtree(dest)
            shutil.copytree(item, dest)
        else:
            shutil.copy2(item, dest)
    subprocess.run(["git", "add", "-A"], cwd=GH_PAGES_WORKTREE, check=True, capture_output=True, text=True)
    diff = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=GH_PAGES_WORKTREE)
    if diff.returncode == 0:
        return {"changed": False, "message": "No gh-pages changes", "url": GH_PAGES_URL}
    version = addon_version()
    subprocess.run(["git", "commit", "-m", f"Deploy {ADDON_ID} v{version}"], cwd=GH_PAGES_WORKTREE, check=True, capture_output=True, text=True)
    push = subprocess.run(["git", "push", "origin", "gh-pages"], cwd=GH_PAGES_WORKTREE, check=True, capture_output=True, text=True)
    return {"changed": True, "version": version, "url": GH_PAGES_URL, "push": push.stdout + push.stderr}
