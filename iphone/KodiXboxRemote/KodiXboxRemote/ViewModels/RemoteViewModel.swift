import Combine
import Foundation
import SwiftUI

@MainActor
final class RemoteViewModel: ObservableObject {
    @Published var connectionStatus: ConnectionStatus = .disconnected
    @Published var localIP: String = "0.0.0.0"
    @Published var localPortString: String = "9192"
    @Published var pairingToken: String = ""
    @Published var isListening: Bool = false
    @Published var telemetry: TelemetryMessage?
    @Published var addonSummary: String = "No Xbox add-on connected"
    @Published var lastResult: String = ""
    @Published var lastError: String?
    @Published var showError = false

    private let bridgeServer = BridgeServer(port: 9192)
    private var activeConnection: BridgeConnection?
    private var commandCounter = 0
    private var cancellables = Set<AnyCancellable>()

    var localPort: UInt16 { UInt16(localPortString) ?? 9192 }
    var canSendCommands: Bool { connectionStatus == .connected || connectionStatus == .authenticated }

    init() {
        localIP = bridgeServer.localAddress
        bindServer()
    }

    func toggleListening() {
        if isListening {
            bridgeServer.stopListening()
        } else {
            bridgeServer.startListening(port: localPort)
        }
    }

    func sendCommand(_ method: String, params: [String: Any] = [:]) {
        guard canSendCommands, let connection = activeConnection else {
            setError("Not connected to Xbox add-on")
            return
        }
        let command = CommandMessage(id: nextCommandID(), method: method, params: params)
        connection.send(command: command)
    }

    private func bindServer() {
        bridgeServer.$isListening
            .receive(on: DispatchQueue.main)
            .sink { [weak self] listening in
                self?.isListening = listening
                if listening && self?.activeConnection == nil {
                    self?.connectionStatus = .listening
                }
                if !listening {
                    self?.connectionStatus = .disconnected
                    self?.activeConnection = nil
                }
            }
            .store(in: &cancellables)

        bridgeServer.$localAddress
            .receive(on: DispatchQueue.main)
            .assign(to: &$localIP)

        bridgeServer.$lastError
            .receive(on: DispatchQueue.main)
            .sink { [weak self] error in
                if let error { self?.setError(error) }
            }
            .store(in: &cancellables)

        bridgeServer.onConnectionEstablished = { [weak self] connection in
            self?.attach(connection)
        }
        bridgeServer.onConnectionLost = { [weak self] in
            self?.activeConnection = nil
            self?.telemetry = nil
            self?.addonSummary = "No Xbox add-on connected"
            self?.connectionStatus = self?.isListening == true ? .listening : .disconnected
        }
    }

    private func attach(_ connection: BridgeConnection) {
        activeConnection = connection
        connectionStatus = .waitingForHello
        addonSummary = "Xbox add-on connected; waiting for hello"

        connection.onMessageReceived = { [weak self, weak connection] message in
            guard let self, let connection else { return }
            self.handle(message, from: connection)
        }
        connection.onError = { [weak self] error in self?.setError(error) }
        connection.onConnectionStateChanged = { [weak self] connected in
            if !connected {
                self?.activeConnection = nil
                self?.telemetry = nil
                self?.connectionStatus = self?.isListening == true ? .listening : .disconnected
            }
        }
    }

    private func handle(_ message: BridgeMessage, from connection: BridgeConnection) {
        switch message {
        case .hello(let hello):
            addonSummary = "\(hello.kodiName) \(hello.kodiVersion) via \(hello.addonID) \(hello.addonVersion)"
            if pairingToken.isEmpty {
                connection.sendAuthOK()
                connectionStatus = .authenticated
            } else {
                connectionStatus = .authenticating
            }
        case .auth(let auth):
            if pairingToken.isEmpty || auth.token == pairingToken {
                connection.sendAuthOK()
                connectionStatus = .authenticated
            } else {
                connection.sendAuthError("Invalid token")
                connectionStatus = .authFailed
                setError("Invalid iPhone bridge token from Xbox add-on")
            }
        case .result(let result):
            if result.ok {
                lastResult = "Command \(result.id ?? "?") OK"
            } else {
                lastResult = "Command \(result.id ?? "?") failed: \(result.error ?? "Unknown error")"
            }
        case .error(let error):
            setError(error.message)
        case .telemetry(let telemetry):
            self.telemetry = telemetry
            if connectionStatus == .authenticated { connectionStatus = .connected }
        case .ping(let id):
            connection.sendPong(id: id)
        case .authOK:
            connectionStatus = .authenticated
        case .authError(let message):
            connectionStatus = .authFailed
            setError(message ?? "Authentication failed")
        case .pong:
            break
        case .command, .unknown:
            break
        }
    }

    private func nextCommandID() -> String {
        commandCounter += 1
        return String(format: "cmd-%04d", commandCounter)
    }

    private func setError(_ message: String) {
        lastError = message
        showError = true
    }
}

enum ConnectionStatus: String, CaseIterable {
    case disconnected = "Disconnected"
    case listening = "Listening"
    case waitingForHello = "Waiting for hello"
    case authenticating = "Authenticating"
    case authenticated = "Authenticated"
    case connected = "Connected"
    case authFailed = "Auth failed"

    var color: Color {
        switch self {
        case .disconnected: return .gray
        case .listening: return .blue
        case .waitingForHello, .authenticating: return .orange
        case .authenticated, .connected: return .green
        case .authFailed: return .red
        }
    }
}
