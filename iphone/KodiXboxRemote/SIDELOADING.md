# KodiXboxRemote Sideloading Without a Mac

This app is built in GitHub Actions on a cloud macOS runner. The laptop can download the resulting IPA, and SideStore/AltStore can install or re-sign it on the iPhone.

## Current expected flow

1. Push iOS source/project changes to GitHub.
2. Open the GitHub repo in a browser.
3. Go to Actions → iOS Build.
4. Click Run workflow, or use the run created by a push to `master`.
5. Wait for the workflow to finish.
6. Download the `KodiXboxRemote-unsigned-ipa` artifact.
7. Extract the downloaded artifact zip; inside is:
   - `KodiXboxRemote-unsigned.ipa`
8. Move the IPA somewhere the iPhone can open from Files:
   - iCloud Drive
   - local file server
   - direct download from GitHub Actions on the phone
9. Open SideStore or AltStore.
10. Tap `+` / add app.
11. Select `KodiXboxRemote-unsigned.ipa`.
12. Let SideStore/AltStore sign/install it.

## First-run phone setup

1. Launch KodiXboxRemote.
2. When iOS asks for Local Network permission, allow it.
3. If needed, confirm permission manually:
   - Settings → Privacy & Security → Local Network → KodiXboxRemote enabled
4. Leave Pairing Token blank for the first test.
5. Tap Start Listening.
6. Note the displayed iPhone IP and port. The default port is `9192`.

## Xbox Kodi add-on setup

In Kodi on Xbox:

1. Install/update `script.xbox.proxy` to version `1.0.8` or newer.
2. Go to Settings → Add-ons → My add-ons → Services → Kodi Xbox Proxy → Configure.
3. Set:
   - Enable iPhone Remote Bridge: true
   - iPhone Bridge Host: the IP shown in KodiXboxRemote
   - iPhone Bridge Port: 9192 unless the app shows a different port
   - iPhone Bridge Token: blank for first test
4. Restart Kodi or restart the add-on after changing settings.

## Expected success state

- KodiXboxRemote shows connected/authenticated.
- The app displays add-on/Kodi information from the `hello` message.
- Direction buttons move Kodi focus.
- Select/Back/Home work.
- Play/pause and volume buttons send JSON-RPC commands.
- Telemetry eventually appears in the app.

## Important limitations

- The IPA produced by CI is currently unsigned. SideStore/AltStore may be able to sign it; if not, the workflow needs a signing step.
- Free Apple ID signing normally expires after about 7 days.
- The app must remain foregrounded for the TCP listener to stay reliable.
- This is the custom B2 bridge app, not official Kore compatibility.

## If SideStore/AltStore rejects the IPA

Capture the exact error text. Likely next steps are one of:

1. Adjust the unsigned IPA package layout.
2. Add a CI signing path using Apple Developer credentials.
3. Use TestFlight with a paid Apple Developer account.
4. Fall back to a mobile web remote served by the laptop proxy for immediate testing.
