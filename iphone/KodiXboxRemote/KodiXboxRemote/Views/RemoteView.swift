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

                VStack(alignment: .leading, spacing: 8) {
                    Text("Xbox add-on")
                        .font(.headline)
                    Text(viewModel.addonSummary)
                        .font(.subheadline)
                    if let telemetry = viewModel.telemetry {
                        HStack {
                            Text("Volume: \(telemetry.volume.map(String.init) ?? "\u{2014}")")
                            Spacer()
                            Text("Muted: \(telemetry.muted == true ? "Yes" : "No")")
                        }
                        .font(.caption)
                        if let label = telemetry.item["label"] as? String {
                            Text("Now: \(label)")
                                .font(.caption)
                                .lineLimit(1)
                        }
                    }
                    if !viewModel.lastResult.isEmpty {
                        Text(viewModel.lastResult)
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                }
                .padding()
                .background(.thinMaterial)
                .clipShape(RoundedRectangle(cornerRadius: 14))

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
                viewModel.sendCommand("Input.SendText", params: ["text": text])
            }
        }
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
                textButton("Info", method: "Input.Info")
                textButton("Context", method: "Input.ContextMenu")
            }
            HStack(spacing: 12) {
                Button {
                    UIImpactFeedbackGenerator(style: .light).impactOccurred()
                    showKeyboard = true
                } label: {
                    Image(systemName: "keyboard")
                        .frame(maxWidth: .infinity)
                        .padding()
                        .background(Color.blue.opacity(0.18))
                        .clipShape(RoundedRectangle(cornerRadius: 12))
                }
                textButton("OK", method: "Input.Select")
            }
            HStack(spacing: 12) {
                textButton("Back", method: "Input.Back")
                textButton("Home", method: "Input.Home")
            }

            // Playback + volume row
            HStack(spacing: 12) {
                actionButton("speaker.wave.1", action: "volumedown", label: "Vol-")
                actionButton("playpause.fill", action: "playpause", label: nil)
                actionButton("stop.fill", action: "stop", label: nil)
                actionButton("speaker.slash", action: "mute", label: nil)
                actionButton("speaker.wave.3", action: "volumeup", label: "Vol+")
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
                .frame(maxWidth: .infinity)
                .padding()
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
