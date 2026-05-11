import SwiftUI

struct RemoteView: View {
    @EnvironmentObject var viewModel: RemoteViewModel
    @State private var showKeyboard = false
    @State private var keyboardText = ""

    var body: some View {
        ScrollView {
            VStack(spacing: 18) {
                ConnectionStatusView()

                VStack(alignment: .leading, spacing: 8) {
                    Text("iPhone listener")
                        .font(.headline)
                    HStack {
                        Label(viewModel.localIP, systemImage: "wifi")
                        Spacer()
                        TextField("Port", text: $viewModel.localPortString)
                            .keyboardType(.numberPad)
                            .multilineTextAlignment(.trailing)
                            .frame(width: 90)
                            .textFieldStyle(.roundedBorder)
                    }
                    Text("Enter this IP and port in the Xbox Kodi add-on iPhone Remote Bridge settings.")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                .padding()
                .background(.thinMaterial)
                .clipShape(RoundedRectangle(cornerRadius: 14))

                VStack(alignment: .leading, spacing: 8) {
                    Text("Pairing token")
                        .font(.headline)
                    SecureField("Optional shared token", text: $viewModel.pairingToken)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                        .textFieldStyle(.roundedBorder)
                    Text("If set here, use the same token in the Kodi add-on settings.")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                .padding()
                .background(.thinMaterial)
                .clipShape(RoundedRectangle(cornerRadius: 14))

                Button {
                    viewModel.toggleListening()
                } label: {
                    Text(viewModel.isListening ? "Stop Listening" : "Start Listening")
                        .font(.headline)
                        .frame(maxWidth: .infinity)
                        .padding()
                        .background(viewModel.isListening ? Color.red : Color.green)
                        .foregroundStyle(.white)
                        .clipShape(RoundedRectangle(cornerRadius: 12))
                }

                NowPlayingView()

                DebugLogView()

                RemoteControlPad(showKeyboard: $showKeyboard)
                    .disabled(!viewModel.canSendCommands)
                    .opacity(viewModel.canSendCommands ? 1.0 : 0.45)
            }
            .padding()
        }
        .navigationTitle("Kodi Xbox Remote")
        .alert("Error", isPresented: $viewModel.showError) {
            Button("OK", role: .cancel) {}
        } message: {
            Text(viewModel.lastError ?? "Unknown error")
        }
        .sheet(isPresented: $showKeyboard) {
            KeyboardSheet(text: $keyboardText) { text in
                viewModel.sendText(text)
            }
        }
    }
}

private struct NowPlayingView: View {
    @EnvironmentObject var viewModel: RemoteViewModel

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                Text("Xbox add-on")
                    .font(.headline)
                Spacer()
                if let telemetry = viewModel.telemetry {
                    HStack(spacing: 8) {
                        Label(telemetry.volume.map(String.init) ?? "\u{2014}", systemImage: telemetry.muted == true ? "speaker.slash.fill" : "speaker.wave.2.fill")
                        Text(telemetry.activePlayers.isEmpty ? "Idle" : "Active")
                    }
                    .font(.caption)
                    .foregroundStyle(.secondary)
                }
            }

            Text(viewModel.addonSummary)
                .font(.subheadline)
                .foregroundStyle(.secondary)

            HStack(alignment: .top, spacing: 12) {
                RoundedRectangle(cornerRadius: 12)
                    .fill(Color.blue.opacity(0.16))
                    .frame(width: 72, height: 72)
                    .overlay {
                        Image(systemName: viewModel.telemetry?.activePlayers.isEmpty == false ? "play.tv.fill" : "tv.fill")
                            .font(.title)
                            .foregroundStyle(.blue)
                    }

                VStack(alignment: .leading, spacing: 4) {
                    Text(nowPlayingTitle)
                        .font(.headline)
                        .lineLimit(2)
                    if let subtitle = nowPlayingSubtitle {
                        Text(subtitle)
                            .font(.caption)
                            .foregroundStyle(.secondary)
                            .lineLimit(1)
                    }
                    if !viewModel.lastResult.isEmpty {
                        Text(viewModel.lastResult)
                            .font(.caption2)
                            .foregroundStyle(.secondary)
                            .lineLimit(1)
                    }
                }
                Spacer()
            }
        }
        .padding()
        .background(.thinMaterial)
        .clipShape(RoundedRectangle(cornerRadius: 14))
    }

    private var nowPlayingTitle: String {
        guard let item = viewModel.telemetry?.item else { return "Nothing playing yet" }
        return firstString(in: item, keys: ["title", "label", "file"]) ?? "Unknown title"
    }

    private var nowPlayingSubtitle: String? {
        guard let item = viewModel.telemetry?.item else { return nil }
        return firstString(in: item, keys: ["artist", "album", "showtitle", "genre"])
    }

    private func firstString(in item: [String: Any], keys: [String]) -> String? {
        for key in keys {
            if let value = item[key] as? String, !value.isEmpty { return value }
            if let values = item[key] as? [String], let first = values.first, !first.isEmpty { return first }
        }
        return nil
    }
}

private struct DebugLogView: View {
    @EnvironmentObject var viewModel: RemoteViewModel
    @State private var isExpanded = false

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                Label("Debug log", systemImage: "ladybug")
                    .font(.headline)
                Spacer()
                Toggle("", isOn: $viewModel.debugLoggingEnabled)
                    .labelsHidden()
                Button(isExpanded ? "Hide" : "Show") {
                    isExpanded.toggle()
                }
                .font(.caption)
            }

            if let latest = viewModel.debugEntries.first {
                Text("\(latest.displayTime)  \(latest.message)")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .lineLimit(2)
            } else {
                Text("No debug events yet")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }

            if isExpanded {
                Divider()
                ForEach(viewModel.debugEntries.prefix(25)) { entry in
                    Text("\(entry.displayTime)  \(entry.message)")
                        .font(.caption2.monospaced())
                        .foregroundStyle(.secondary)
                        .lineLimit(2)
                }
                Button("Clear log") {
                    viewModel.clearDebugLog()
                }
                .font(.caption)
            }
        }
        .padding()
        .background(.thinMaterial)
        .clipShape(RoundedRectangle(cornerRadius: 14))
    }
}

private struct RemoteControlPad: View {
    @EnvironmentObject var viewModel: RemoteViewModel
    @Binding var showKeyboard: Bool

    var body: some View {
        VStack(spacing: 14) {
            // D-pad
            HStack {
                Spacer()
                dpadButton(systemName: "chevron.up", method: "Input.Up")
                Spacer()
            }
            HStack {
                dpadButton(systemName: "chevron.left", method: "Input.Left")
                dpadButton(systemName: "circle.fill", method: "Input.Select")
                dpadButton(systemName: "chevron.right", method: "Input.Right")
            }
            HStack {
                Spacer()
                dpadButton(systemName: "chevron.down", method: "Input.Down")
                Spacer()
            }

            // Navigation / utility buttons
            HStack(spacing: 12) {
                textButton("Back", method: "Input.Back")
                textButton("Home", method: "Input.Home")
                textButton("Menu", method: "Input.ContextMenu")
                textButton("Info", method: "Input.Info")
            }

            HStack(spacing: 12) {
                keyboardButton()
                textButton("OK", method: "Input.Select")
                textButton("OSD", method: "Input.ShowOSD")
            }

            // Playback row
            HStack(spacing: 12) {
                actionButton("backward.fill", action: "rewind", label: "<<")
                actionButton("playpause.fill", action: "playpause", label: nil)
                actionButton("stop.fill", action: "stop", label: nil)
                actionButton("forward.fill", action: "fastforward", label: ">>")
            }

            // Audio / video row
            HStack(spacing: 12) {
                actionButton("speaker.wave.1", action: "volumedown", label: "Vol-")
                actionButton("speaker.slash", action: "mute", label: nil)
                actionButton("speaker.wave.3", action: "volumeup", label: "Vol+")
                actionButton("captions.bubble", action: "nextsubtitle", label: "Subs")
                actionButton("waveform", action: "audionextlanguage", label: "Audio")
            }

            // Extra row
            HStack(spacing: 12) {
                actionButton("arrow.down.left.and.arrow.up.right", action: "fullscreen", label: "Full")
                actionButton("list.bullet", action: "playlist", label: "List")
                actionButton("backward.end.fill", action: "chapterorbigstepback", label: "Chap-")
                actionButton("forward.end.fill", action: "chapterorbigstepforward", label: "Chap+")
            }
        }
        .padding()
        .background(.thinMaterial)
        .clipShape(RoundedRectangle(cornerRadius: 14))
    }

    private func dpadButton(systemName: String, method: String) -> some View {
        Button {
            UIImpactFeedbackGenerator(style: .light).impactOccurred()
            viewModel.sendCommand(method)
        } label: {
            Image(systemName: systemName)
                .font(.title2)
                .frame(width: 64, height: 54)
                .background(Color.blue.opacity(0.18))
                .clipShape(RoundedRectangle(cornerRadius: 12))
        }
    }

    private func textButton(_ title: String, method: String) -> some View {
        Button {
            UIImpactFeedbackGenerator(style: .light).impactOccurred()
            viewModel.sendCommand(method)
        } label: {
            Text(title)
                .font(.caption)
                .frame(maxWidth: .infinity)
                .padding(.vertical, 12)
                .background(Color.blue.opacity(0.18))
                .clipShape(RoundedRectangle(cornerRadius: 12))
        }
    }

    private func keyboardButton() -> some View {
        Button {
            UIImpactFeedbackGenerator(style: .light).impactOccurred()
            showKeyboard = true
        } label: {
            VStack(spacing: 2) {
                Image(systemName: "keyboard")
                    .font(.title3)
                Text("Keys")
                    .font(.caption2)
            }
            .frame(maxWidth: .infinity)
            .padding(.vertical, 8)
            .background(Color.blue.opacity(0.18))
            .clipShape(RoundedRectangle(cornerRadius: 12))
        }
    }

    private func actionButton(_ systemName: String, action: String, label: String?) -> some View {
        Button {
            UIImpactFeedbackGenerator(style: .light).impactOccurred()
            viewModel.sendCommand("Input.ExecuteAction", params: ["action": action])
        } label: {
            VStack(spacing: 2) {
                Image(systemName: systemName)
                    .font(.title3)
                if let label {
                    Text(label)
                        .font(.caption2)
                }
            }
            .frame(width: 44, height: 44)
            .background(Color.orange.opacity(0.2))
            .clipShape(Circle())
        }
    }
}

// MARK: - Keyboard sheet for text input

struct KeyboardSheet: View {
    @Binding var text: String
    let onSubmit: (String) -> Void
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            VStack(spacing: 16) {
                TextField("Type text to send…", text: $text)
                    .textFieldStyle(.roundedBorder)
                    .padding(.horizontal)

                Text("Tap Send to type this into Kodi's active text field.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .multilineTextAlignment(.center)
                    .padding(.horizontal)

                Spacer()
            }
            .padding(.top)
            .navigationTitle("Send Text")
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button("Send") {
                        let value = text
                        text = ""
                        onSubmit(value)
                    }
                    .disabled(text.isEmpty)
                }
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancel") { dismiss() }
                }
            }
        }
    }
}
