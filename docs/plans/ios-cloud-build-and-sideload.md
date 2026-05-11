# iOS Cloud Build and SideStore/AltStore Sideload Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task if execution is delegated. For this session, implement directly only after this plan is committed and pushed.

**Goal:** Make the custom KodiXboxRemote iPhone app buildable on a cloud macOS runner, produce an IPA artifact, and document how David can install/refresh it with SideStore or AltStore without owning a Mac.

**Architecture:** Keep the iOS app as a native SwiftUI app under `iphone/KodiXboxRemote/`. Add a real `.xcodeproj` so GitHub Actions macOS can compile it. CI should first produce an unsigned simulator/device build artifact where possible, then evolve toward a sideloadable IPA flow that SideStore/AltStore can sign or install.

**Tech Stack:** SwiftUI, Network.framework, Xcode project files, GitHub Actions macOS runners, optional SideStore/AltStore signing/install flow, existing Python unittest static validation.

---

## Current State

The repo already has:

- Kodi add-on B2 bridge client code:
  - `addon/default.py`
  - `addon/iphone_bridge.py`
  - `addon/resources/settings.xml`
- iPhone Swift source skeleton:
  - `iphone/KodiXboxRemote/KodiXboxRemote/`
- Static tests:
  - `tests/test_iphone_bridge_protocol.py`
  - `tests/test_iphone_swift_static.py`
- Local Kodi package artifact:
  - `addon.zip`
  - `repo_static/script.xbox.proxy/script.xbox.proxy-1.0.8.zip`

The missing pieces are:

- A real Xcode project checked into the repo.
- A GitHub Actions workflow that compiles the app on macOS.
- A repeatable IPA packaging/signing path.
- User-facing instructions for SideStore/AltStore installation.

---

## Acceptance Criteria

1. `iphone/KodiXboxRemote/KodiXboxRemote.xcodeproj` exists and references all Swift app files.
2. GitHub Actions has an iOS build workflow at `.github/workflows/ios-build.yml`.
3. The workflow can be triggered manually with `workflow_dispatch`.
4. The workflow runs Python validation tests on Linux or macOS.
5. The workflow runs `xcodebuild` on macOS for the iOS app.
6. The workflow uploads a downloadable build artifact.
7. The repo documents the no-Mac install path using SideStore/AltStore.
8. Local validation still passes:
   - `python3 -m unittest tests/test_iphone_bridge_protocol.py tests/test_iphone_swift_static.py`
   - `python3 -m py_compile addon/default.py addon/iphone_bridge.py`
9. Existing Kodi add-on packaging remains correct with `script.xbox.proxy/` as the zip root.

---

## Important Constraints

- Linux cannot run `xcodebuild` or produce a fully validated iOS build locally.
- Cloud macOS CI will be the first real compiler check.
- A paid Apple Developer account is not assumed.
- SideStore/AltStore can install/resign IPAs, but they do not compile Swift source.
- Free Apple ID signing may expire after 7 days.
- The iPhone app must stay foregrounded because it runs a local TCP listener.
- Do not change the B2 networking direction: the Xbox add-on connects outbound to the iPhone app.

---

## Phase 1: Save and Push the Plan

### Task 1: Add this implementation plan

**Objective:** Save the agreed step-by-step plan in the repo before implementation.

**Files:**
- Create: `docs/plans/ios-cloud-build-and-sideload.md`

**Steps:**
1. Write this Markdown plan.
2. Run local status check:
   - `git status --short`
3. Commit the plan and current B2 artifacts together if they are still uncommitted:
   - `git add addon addon.zip addons.xml.md5 repo_static iphone tests .hermes docs/plans`
   - `git commit -m "feat: add iPhone remote bridge and build plan"`
4. Push to GitHub:
   - `git push origin master`

**Verification:**
- `git status --short` should be clean immediately after the push, unless new implementation work has started.
- GitHub should show the plan file on `master`.

---

## Phase 2: Create a Real Xcode Project

### Task 2: Add a minimal Xcode project shell

**Objective:** Add `KodiXboxRemote.xcodeproj` so GitHub Actions can open/build the native app.

**Files:**
- Create: `iphone/KodiXboxRemote/KodiXboxRemote.xcodeproj/project.pbxproj`
- Create if needed: `iphone/KodiXboxRemote/KodiXboxRemote.xcodeproj/project.xcworkspace/contents.xcworkspacedata`
- Create if needed: `iphone/KodiXboxRemote/KodiXboxRemote.xcodeproj/xcshareddata/xcschemes/KodiXboxRemote.xcscheme`

**Implementation Notes:**
- Product name: `KodiXboxRemote`
- Bundle identifier placeholder: `com.dworrall21.KodiXboxRemote`
- Deployment target: iOS 16.0 or newer
- App source root: `iphone/KodiXboxRemote/KodiXboxRemote/`
- Include all Swift files:
  - `KodiXboxRemoteApp.swift`
  - `Protocol/BridgeMessage.swift`
  - `Networking/BridgeServer.swift`
  - `Networking/BridgeConnection.swift`
  - `ViewModels/RemoteViewModel.swift`
  - `Views/RemoteView.swift`
  - `Views/ConnectionStatusView.swift`
- Include app Info metadata currently in:
  - `Resources/Info.plist`

**Verification:**
- Local static validation should still pass.
- `git status --short` should show only the new Xcode project files.
- Full `xcodebuild` verification happens in GitHub Actions.

---

## Phase 3: Add GitHub Actions Build Workflow

### Task 3: Add manual iOS build workflow

**Objective:** Add a macOS CI workflow that validates Python/static tests and attempts to build the iOS app.

**Files:**
- Create: `.github/workflows/ios-build.yml`

**Workflow Requirements:**
- Trigger: `workflow_dispatch` and optionally pushes affecting `iphone/**`, `addon/**`, `tests/**`, `.github/workflows/ios-build.yml`.
- Use a macOS runner, for example `macos-15` or `macos-14`.
- Print Xcode version:
  - `xcodebuild -version`
- Run Python tests:
  - `python3 -m unittest tests/test_iphone_bridge_protocol.py tests/test_iphone_swift_static.py`
- Run Python syntax checks:
  - `python3 -m py_compile addon/default.py addon/iphone_bridge.py`
- Build app:
  - `xcodebuild -project iphone/KodiXboxRemote/KodiXboxRemote.xcodeproj -scheme KodiXboxRemote -destination 'generic/platform=iOS Simulator' build`
- Upload build logs/artifacts for debugging.

**Initial Expected Result:**
- First CI run may fail because manually-authored Xcode project files are fragile.
- Failure logs should be used to patch the project iteratively.

---

## Phase 4: Add IPA Packaging Path

### Task 4: Produce a CI artifact suitable for SideStore/AltStore iteration

**Objective:** Generate a downloadable artifact from the macOS workflow that can evolve into a sideloadable IPA.

**Files:**
- Modify: `.github/workflows/ios-build.yml`
- Create: `iphone/KodiXboxRemote/scripts/package-unsigned-ipa.sh` if needed

**Steps:**
1. First make simulator/device build pass.
2. Add an unsigned archive/package step only after compile succeeds.
3. Package the `.app` into IPA layout:
   - `Payload/KodiXboxRemote.app`
   - zip to `KodiXboxRemote-unsigned.ipa`
4. Upload the IPA as a GitHub Actions artifact.

**Verification:**
- GitHub Actions artifact contains an `.ipa` file.
- `unzip -l KodiXboxRemote-unsigned.ipa` shows `Payload/KodiXboxRemote.app/`.

**Risk:**
- SideStore/AltStore may reject an unsigned IPA depending on its signing expectations.
- If rejected, add a signing-specific follow-up using either SideStore-compatible signing or Apple Developer credentials.

---

## Phase 5: Document SideStore/AltStore Install Flow

### Task 5: Add no-Mac install documentation

**Objective:** Give David exact install steps once CI produces an IPA.

**Files:**
- Create: `iphone/KodiXboxRemote/SIDELOADING.md`
- Modify: `iphone/KodiXboxRemote/README.md`

**Documentation Must Include:**
1. Download the latest GitHub Actions artifact.
2. Put the IPA into iCloud Drive / Files / local web server / phone-accessible location.
3. Open SideStore or AltStore.
4. Install the IPA from Files.
5. Confirm iOS Local Network permission:
   - Settings → Privacy & Security → Local Network → KodiXboxRemote enabled
6. Launch KodiXboxRemote.
7. Tap Start Listening.
8. Configure Xbox Kodi add-on:
   - Enable iPhone Remote Bridge: true
   - iPhone Bridge Host: iPhone IP shown in app
   - iPhone Bridge Port: 9192
   - Token blank for first test
9. Restart Kodi/add-on if it does not connect.

---

## Phase 6: CI Iteration Loop

### Task 6: Run and fix GitHub Actions build

**Objective:** Use the cloud macOS compiler feedback to fix the Xcode project and Swift source.

**Steps:**
1. Push the Xcode project and workflow.
2. Trigger `iOS Build` workflow manually in GitHub Actions.
3. Read CI logs.
4. Fix the first concrete failure only.
5. Commit and push.
6. Repeat until the workflow compiles.

**Verification:**
- GitHub Actions shows a successful `iOS Build` run.
- Build artifact is available to download.

---

## Phase 7: Phone Test

### Task 7: Install and test on iPhone

**Objective:** Validate the real device networking path.

**Steps:**
1. Install the IPA with SideStore/AltStore.
2. Open app and grant Local Network permission.
3. Tap Start Listening.
4. Install/update Kodi add-on 1.0.8 on Xbox.
5. Configure add-on to point at the iPhone IP and port.
6. Restart Kodi or the add-on.
7. Confirm the app sees `hello` and authenticated connection.
8. Test buttons:
   - Up
   - Down
   - Left
   - Right
   - Select
   - Back
   - Home
   - Play/Pause
   - Volume Up/Down

**Success Criteria:**
- iPhone app shows connected/authenticated.
- Xbox Kodi responds to remote commands.
- Telemetry appears in the app.

---

## Fallback Plan

If SideStore/AltStore cannot install the CI-produced IPA:

1. Keep the cloud macOS build workflow for compiler validation.
2. Add a web mobile remote to the existing laptop proxy for immediate iPhone testing.
3. Revisit iOS signing options:
   - Paid Apple Developer account + TestFlight
   - Paid Apple Developer account + CI-signed development/ad-hoc IPA
   - Temporary third-party signing only if David accepts the trust/revocation risk

---

## Commands Reference

Local validation:

```bash
cd ~/kodi-xbox-proxy
python3 -m unittest tests/test_iphone_bridge_protocol.py tests/test_iphone_swift_static.py
python3 -m py_compile addon/default.py addon/iphone_bridge.py
```

Commit and push:

```bash
cd ~/kodi-xbox-proxy
git add addon addon.zip addons.xml.md5 repo_static iphone tests .hermes docs/plans
git commit -m "feat: add iPhone remote bridge and build plan"
git push origin master
```

Manual workflow trigger after workflow exists:

```bash
gh workflow run ios-build.yml
```

If `gh` is unavailable, trigger from GitHub web UI:

```text
GitHub repo → Actions → iOS Build → Run workflow
```
