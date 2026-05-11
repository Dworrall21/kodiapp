import Foundation
import Network

@MainActor
final class BridgeConnection: ObservableObject {
    @Published private(set) var isConnected = false
    @Published private(set) var lastError: String?

    let endpointDescription: String

    private let connection: NWConnection
    private let queue = DispatchQueue(label: "KodiXboxRemote.BridgeConnection")
    private var buffer = Data()
    private let newline = Data([0x0A])

    var onMessageReceived: ((BridgeMessage) -> Void)?
    var onConnectionStateChanged: ((Bool) -> Void)?
    var onError: ((String) -> Void)?

    init(connection: NWConnection) {
        self.connection = connection
        self.endpointDescription = String(describing: connection.endpoint)
    }

    func start() {
        connection.stateUpdateHandler = { [weak self] state in
            Task { @MainActor in self?.handleState(state) }
        }
        connection.start(queue: queue)
        receiveNext()
    }

    func disconnect() {
        connection.cancel()
        isConnected = false
        onConnectionStateChanged?(false)
    }

    func send(command: CommandMessage) {
        sendJSON(command.jsonObject())
    }

    func sendAuthOK() {
        sendJSON(AuthResponseMessage(type: "auth_ok", message: nil).jsonObject())
    }

    func sendAuthError(_ message: String) {
        sendJSON(AuthResponseMessage(type: "auth_error", message: message).jsonObject())
    }

    func sendPong(id: String?) {
        var object: [String: Any] = ["type": "pong"]
        if let id { object["id"] = id }
        sendJSON(object)
    }

    private func sendJSON(_ object: [String: Any]) {
        do {
            let data = try JSONObject.encodeLine(object)
            connection.send(content: data, completion: .contentProcessed { [weak self] error in
                if let error {
                    Task { @MainActor in self?.reportError("Send failed: \(error.localizedDescription)") }
                }
            })
        } catch {
            reportError("Encode failed: \(error.localizedDescription)")
        }
    }

    private func receiveNext() {
        connection.receive(minimumIncompleteLength: 1, maximumLength: bridgeMaxMessageBytes) { [weak self] data, _, isComplete, error in
            guard let self else { return }
            if let error {
                Task { @MainActor in self.reportError("Receive failed: \(error.localizedDescription)") }
                return
            }
            if let data, !data.isEmpty {
                Task { @MainActor in self.consume(data) }
            }
            if isComplete {
                Task { @MainActor in
                    self.isConnected = false
                    self.onConnectionStateChanged?(false)
                }
                return
            }
            Task { @MainActor in self.receiveNext() }
        }
    }

    private func consume(_ data: Data) {
        buffer.append(data)
        while let range = buffer.range(of: newline) {
            let line = buffer.subdata(in: buffer.startIndex..<range.lowerBound)
            buffer.removeSubrange(buffer.startIndex..<range.upperBound)
            guard !line.isEmpty else { continue }
            do {
                let message = try BridgeMessage.decode(line)
                onMessageReceived?(message)
            } catch {
                reportError("Decode failed: \(error.localizedDescription)")
            }
        }
        if buffer.count > bridgeMaxMessageBytes {
            buffer.removeAll()
            reportError("Incoming bridge message exceeded size limit")
        }
    }

    private func handleState(_ state: NWConnection.State) {
        switch state {
        case .ready:
            isConnected = true
            lastError = nil
            onConnectionStateChanged?(true)
        case .failed(let error):
            isConnected = false
            reportError("Connection failed: \(error.localizedDescription)")
            onConnectionStateChanged?(false)
        case .cancelled:
            isConnected = false
            onConnectionStateChanged?(false)
        default:
            break
        }
    }

    private func reportError(_ message: String) {
        lastError = message
        onError?(message)
    }
}
