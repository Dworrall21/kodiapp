import SwiftUI

struct RemoteView: View {
    @EnvironmentObject var viewModel: RemoteViewModel

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
                            Text("Volume: \(telemetry.volume.map(String.init) ?? "—")")
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

                RemoteControlPad()
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
    }
}

private struct RemoteControlPad: View {
    @EnvironmentObject var viewModel: RemoteViewModel

    var body: some View {
        VStack(spacing: 14) {
            HStack {
                Spacer()
                remoteButton(systemName: "chevron.up", method: "Input.Up")
                Spacer()
            }
            HStack {
                remoteButton(systemName: "chevron.left", method: "Input.Left")
                remoteButton(systemName: "circle.fill", method: "Input.Select")
                remoteButton(systemName: "chevron.right", method: "Input.Right")
            }
            HStack {
                Spacer()
                remoteButton(systemName: "chevron.down", method: "Input.Down")
                Spacer()
            }
            HStack(spacing: 12) {
                textButton("Back", method: "Input.Back")
                textButton("Home", method: "Input.Home")
            }
            HStack(spacing: 12) {
                actionButton("speaker.wave.1", action: "volumedown")
                actionButton("playpause.fill", action: "playpause")
                actionButton("stop.fill", action: "stop")
                actionButton("speaker.slash", action: "mute")
                actionButton("speaker.wave.3", action: "volumeup")
            }
        }
        .padding()
        .background(.thinMaterial)
        .clipShape(RoundedRectangle(cornerRadius: 14))
    }

    private func remoteButton(systemName: String, method: String) -> some View {
        Button { viewModel.sendCommand(method) } label: {
            Image(systemName: systemName)
                .font(.title2)
                .frame(width: 64, height: 54)
                .background(Color.blue.opacity(0.18))
                .clipShape(RoundedRectangle(cornerRadius: 12))
        }
    }

    private func textButton(_ title: String, method: String) -> some View {
        Button { viewModel.sendCommand(method) } label: {
            Text(title)
                .frame(maxWidth: .infinity)
                .padding()
                .background(Color.blue.opacity(0.18))
                .clipShape(RoundedRectangle(cornerRadius: 12))
        }
    }

    private func actionButton(_ systemName: String, action: String) -> some View {
        Button {
            viewModel.sendCommand("Input.ExecuteAction", params: ["action": action])
        } label: {
            Image(systemName: systemName)
                .frame(width: 44, height: 44)
                .background(Color.orange.opacity(0.2))
                .clipShape(Circle())
        }
    }
}
