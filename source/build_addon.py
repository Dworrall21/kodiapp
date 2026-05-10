#!/usr/bin/env python3
"""Build Kodi add-on zip and repository metadata from source/.

Run from the repository root on the gh-pages branch:

    python3 source/build_addon.py

This creates/updates:

- script.xbox.proxy/script.xbox.proxy-<version>.zip
- addons.xml
- addons.xml.md5

The script preserves the existing diagnostic add-on entries and updates the
script.xbox.proxy entry from source/script.xbox.proxy/addon.xml.
"""
from __future__ import annotations

import hashlib
import os
import shutil
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = ROOT / "source" / "script.xbox.proxy"
OUT_DIR = ROOT / "script.xbox.proxy"
ADDONS_XML = ROOT / "addons.xml"
ADDONS_MD5 = ROOT / "addons.xml.md5"


def read_addon_id_version(addon_xml: Path) -> tuple[str, str]:
    tree = ET.parse(addon_xml)
    root = tree.getroot()
    addon_id = root.attrib["id"]
    version = root.attrib["version"]
    return addon_id, version


def build_zip(addon_id: str, version: str) -> Path:
    OUT_DIR.mkdir(exist_ok=True)
    zip_path = OUT_DIR / f"{addon_id}-{version}.zip"
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(SOURCE_DIR.rglob("*")):
            if path.is_dir():
                continue
            rel = path.relative_to(SOURCE_DIR)
            zf.write(path, f"{addon_id}/{rel.as_posix()}")
    return zip_path


def indent(elem: ET.Element, level: int = 0) -> None:
    i = "\n" + level * "    "
    if len(elem):
        if not elem.text or not elem.text.strip():
            elem.text = i + "    "
        for child in elem:
            indent(child, level + 1)
        if not child.tail or not child.tail.strip():
            child.tail = i
    if level and (not elem.tail or not elem.tail.strip()):
        elem.tail = i


def update_addons_xml(new_addon_xml: Path) -> None:
    new_addon = ET.parse(new_addon_xml).getroot()
    if ADDONS_XML.exists():
        root = ET.parse(ADDONS_XML).getroot()
    else:
        root = ET.Element("addons")

    new_id = new_addon.attrib["id"]
    for existing in list(root):
        if existing.tag == "addon" and existing.attrib.get("id") == new_id:
            root.remove(existing)
    root.append(new_addon)
    indent(root)
    data = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    ADDONS_XML.write_bytes(data + b"\n")
    ADDONS_MD5.write_text(hashlib.md5(ADDONS_XML.read_bytes()).hexdigest(), encoding="utf-8")


def main() -> None:
    addon_id, version = read_addon_id_version(SOURCE_DIR / "addon.xml")
    zip_path = build_zip(addon_id, version)
    update_addons_xml(SOURCE_DIR / "addon.xml")
    print(f"Built {zip_path.relative_to(ROOT)}")
    print(f"Updated {ADDONS_XML.relative_to(ROOT)}")
    print(f"Updated {ADDONS_MD5.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
