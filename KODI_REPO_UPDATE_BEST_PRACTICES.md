# Kodi Repository Update Best Practices

This checklist captures what has worked while troubleshooting the Dworrall21 Kodi repository and Xbox Web Proxy add-on.

## 1. Treat repository updates and add-on zip updates as separate things

Kodi does not install from source folders. Kodi reads:

- `addons.xml`
- `addons.xml.md5`
- the add-on package zip referenced by `addons.xml`

For `script.xbox.proxy`, the installable zip must live at a path matching the add-on id and version, for example:

```text
script.xbox.proxy/script.xbox.proxy-1.0.6.zip
```

Updating files under `source/script.xbox.proxy/` is not enough. Those files must be packaged into a zip and the repo metadata must be updated.

## 2. Always build the zip with the correct Kodi layout

The zip must contain a top-level folder named exactly like the add-on id:

```text
script.xbox.proxy/addon.xml
script.xbox.proxy/default.py
script.xbox.proxy/resources/settings.xml
```

This layout fails:

```text
addon.xml
default.py
resources/settings.xml
```

Kodi may show the version in the repository but fail during install if the zip layout is wrong.

## 3. The internal `addon.xml` version must match the repo version

The version in the packaged file:

```text
script.xbox.proxy/addon.xml
```

must match the version advertised in root `addons.xml`.

Example:

```xml
<addon id="script.xbox.proxy" version="1.0.6" ...>
```

If root `addons.xml` says `1.0.6` but the zip contains `1.0.5` or `1.0.4`, Kodi can fail or behave unpredictably.

## 4. Keep dependencies minimal and valid

Only list dependencies that the add-on actually needs.

For the robust proxy version, this is enough:

```xml
<requires>
    <import addon="xbmc.python" version="3.0.0"/>
</requires>
```

Avoid unnecessary vendored dependencies such as `script.module.six` unless the package actually imports them. Nonstandard version strings like `1.16.0+matrix.1` can also create dependency-resolution problems.

## 5. Keep `addons.xml` simple while debugging

During active troubleshooting, publish only:

- `repository.dworrall21`
- `script.xbox.proxy`

Remove old diagnostic packages and unused dependency packages from `addons.xml` unless they are currently needed. The cleaner the repo index, the easier it is to tell what Kodi is trying to install.

## 6. `addons.xml.md5` should be hash-only

Kodi expects `addons.xml.md5` to contain just the MD5 hash of the exact current `addons.xml` bytes.

Good:

```text
f3338bfbf3d126e65dd74b8572e9aed9
```

Risky/bad:

```text
f3338bfbf3d126e65dd74b8572e9aed9  addons.xml
```

After every `addons.xml` edit, regenerate `addons.xml.md5`.

## 7. Do not rely on folder index pages for repository installs

Kodi repository updates use `addons.xml`, not the HTML folder index.

However, if using **Install from zip file**, Kodi may show the generated/static folder page. Therefore, keep these pages current too:

- root `index.html`
- `script.xbox.proxy/index.html`
- `repository.dworrall21/index.html`

The package folder index should not advertise old versions that you do not want users to install.

## 8. Remove old zips when you want only one version shown manually

If old zips remain in the package folder, they may still show when browsing manually through **Install from zip file**.

For a single current version, keep only:

```text
script.xbox.proxy/script.xbox.proxy-<current>.zip
```

Delete older packages or remove them from `index.html`.

## 9. Bump the version to escape Kodi's cache when a package was broken

If a bad package was already advertised or downloaded, do not keep trying to fix the same version. Bump the version:

```text
1.0.5 broken -> publish 1.0.6
```

Kodi may cache the old broken zip or metadata. A new version is easier for Kodi to discover and avoids fighting stale cache state.

## 10. Validate before publishing

Before committing a package, validate locally:

```bash
python3 - <<'PY'
import zipfile
from pathlib import Path

zip_path = Path('script.xbox.proxy/script.xbox.proxy-1.0.6.zip')
with zipfile.ZipFile(zip_path) as z:
    print(z.namelist())
    bad = z.testzip()
    assert bad is None, f'Bad zip member: {bad}'
    addon_xml = z.read('script.xbox.proxy/addon.xml').decode('utf-8')
    assert 'id="script.xbox.proxy"' in addon_xml
    assert 'version="1.0.6"' in addon_xml
print('OK')
PY
```

Then verify:

```bash
md5sum addons.xml
cat addons.xml.md5
```

The values must match, ignoring the filename that `md5sum` prints.

## 11. Publish order

Best order for a release:

1. Update source files.
2. Update internal `source/script.xbox.proxy/addon.xml` version.
3. Build the zip with the correct top-level folder.
4. Validate the zip.
5. Commit the zip.
6. Update root `addons.xml` to advertise the same version.
7. Regenerate `addons.xml.md5` as hash-only.
8. Update folder `index.html` pages if manual zip install is supported.
9. Push `gh-pages`.
10. Confirm GitHub Pages is serving the new metadata.

## 12. Kodi-side refresh steps that have worked

When Kodi keeps showing an old version:

1. Back out of the add-on folder and re-enter it.
2. Use **Check for updates** on the repository if available.
3. Restart Kodi.
4. If the old version still appears, uninstall the repository add-on and reinstall `repository.dworrall21-1.0.0.zip`.
5. If repository metadata still appears stale, install directly from zip as a temporary workaround:

```text
Install from zip file -> kodiapp -> script.xbox.proxy -> script.xbox.proxy-<current>.zip
```

## 13. Do not confuse these three paths

Repository add-on zip:

```text
repository.dworrall21-1.0.0.zip
```

Repository metadata:

```text
addons.xml
addons.xml.md5
```

Actual proxy add-on package:

```text
script.xbox.proxy/script.xbox.proxy-<version>.zip
```

Installing the repository add-on only teaches Kodi where to find `addons.xml`. It does not install the proxy itself.

## 14. Current known-good target shape

A clean repo state should look like this:

```text
addons.xml
addons.xml.md5
index.html
repository.dworrall21-1.0.0.zip
repository.dworrall21/addon.xml
repository.dworrall21/index.html
script.xbox.proxy/index.html
script.xbox.proxy/script.xbox.proxy-<current>.zip
```

Root `addons.xml` should advertise only the current `script.xbox.proxy` version during active debugging.
