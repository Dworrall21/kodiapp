# Kodi Xbox Proxy

Kodi Xbox Proxy lets Kodi on Xbox Retail Mode work around inbound LAN restrictions by connecting outward to a bridge running on another device.

The repo contains three related pieces:

- Python proxy server: local web dashboard, HTTP/JSON-RPC tunnel, static Kodi repository serving, and management endpoints.
- Kodi add-on: `script.xbox.proxy`, installed on Xbox Kodi. It connects outbound to the proxy and can also connect outbound to the custom iPhone remote app.
- iPhone remote app: `KodiXboxRemote`, a SwiftUI app that listens on the iPhone while foregrounded and sends JSON-line remote-control commands to the add-on.

## Current versions

- Kodi add-on: `script.xbox.proxy` v1.0.10
- Python package: `kodi-xbox-proxy` v1.0.10
- iPhone app: built by GitHub Actions as an unsigned IPA artifact

## Repository layout

```text
addon/                         Kodi add-on source for script.xbox.proxy
src/kodi_xbox_proxy/            Python proxy server package
iphone/KodiXboxRemote/          SwiftUI iPhone app and Xcode project
repo_static/                    Static Kodi repository published to gh-pages
tests/                          Python protocol tests and Swift static checks
docs/                           Plans and project documentation
diagnostics/                    Historical diagnostic add-on source
.github/workflows/ios-build.yml GitHub Actions unsigned iOS IPA build
```

`repo_static/` is the published Kodi repository source of truth. GitHub Pages serves it at:

```text
https://dworrall21.github.io/kodiapp/
```

The local proxy also serves the same tree at:

```text
http://<laptop-lan-ip>:8080/repo/
```

## Quick start: Python proxy server

Install and start with the helper script:

```bash
./install-server.sh
```

Or run directly from a development checkout:

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e .
kodi-xbox-proxy
```

Then open:

```text
http://127.0.0.1:8080/
```

Important local testing note: prefer `127.0.0.1` over `localhost` on this machine because the proxy binds IPv4.

## Kodi add-on setup

Install/update `script.xbox.proxy` from one of these sources:

- Local source while the proxy is running: `http://<laptop-lan-ip>:8080/repo/`
- GitHub Pages source: `https://dworrall21.github.io/kodiapp/`

Normal bridge settings should point at the laptop proxy:

```text
Bridge Host: <laptop-lan-ip>
Bridge Port: 9191
Bridge Path: /
Use TLS: false
```

## iPhone remote setup

The iPhone app is built by the `iOS Build` GitHub Actions workflow. Download the `KodiXboxRemote-unsigned-ipa` artifact, then sign/install it with SideStore/AltStore/iLoader.

For iPhone Remote Bridge mode:

1. Open the iPhone app and tap Start Listening.
2. In the Kodi add-on settings, keep the normal Bridge section pointed at the laptop proxy.
3. In the iPhone Remote Bridge section, set:
   - Enable iPhone Remote Bridge: true
   - iPhone Bridge Host: the iPhone IP shown in the app
   - iPhone Bridge Port: default 9192
   - iPhone Bridge Token: same token as the app, or blank on both sides
4. Restart the add-on/Kodi if needed.

The iPhone app must remain foregrounded for the listener to stay reliable.

## Development checks

Run the available Linux-side checks:

```bash
python3 -m unittest tests/test_iphone_bridge_protocol.py tests/test_iphone_swift_static.py
python3 -m py_compile addon/default.py addon/iphone_bridge.py
```

A real Swift compile requires macOS/Xcode, so the repo uses GitHub Actions for the iOS build.

## Packaging the Kodi add-on

Use the repository manager or deterministic zip layout. The zip root must be exactly `script.xbox.proxy/`:

```text
script.xbox.proxy/addon.xml
script.xbox.proxy/default.py
script.xbox.proxy/resources/settings.xml
```

Never publish a zip rooted as `addon/`; Kodi may fail to install or crash.

## Deploying the static Kodi repository

The `gh-pages` branch is managed via the worktree at:

```text
/tmp/kodiapp-gh-pages-wt/
```

Do not check out `gh-pages` in the main worktree. Pull/rebase the gh-pages worktree before pushing published repo changes.

## More docs

- `iphone/KodiXboxRemote/README.md` — iPhone app details
- `docs/plans/ios-cloud-build-and-sideload.md` — cloud build/sideload plan
- `.hermes/plans/remote-plan-option-b2.md` — iPhone bridge implementation plan
- `.hermes/plans/remote-plan-phase2.md` — remote polish/debug panel plan
