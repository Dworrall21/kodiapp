import Foundation
import Network

@MainActor
final class BridgeConnection: ObservableObject {
    @Published private(set) var isConnected = false
    @Published private(set) var lastError: String?

    let endpointDescription: String

    private let connection: NWConnection
    private let queue = DispatchQueue(label: "KodiXboxRemote.BridgeConnection", qos: .userInitiated)
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
            switch state {
            case .ready:
                Task { @MainActor in
                    self?.isConnected = true
                    self?.lastError = nil
                    self?.onConnectionStateChanged?(true)
                }
            case .failed(let error):
                Task { @MainActor in
                    self?.isConnected = false
                    self?.reportError("Connection failed: \(error.localizedDescription)")
                    self?.onConnectionStateChanged?(false)
                }
            case .cancelled:
                Task { @MainActor in
                    self?.isConnected = false
                    self?.onConnectionStateChanged?(false)
                }
            case .waiting, .preparing, .setup:
                break
            @unknown default:
                break
            }
        }
        connection.start(queue: queue)
        beginReceiveNext()
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

    // MARK: - Send

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

    // MARK: - Receive (recursive queue loop)

    /// Schedule the next receive callback on our dedicated queue.
    /// This is NOT MainActor-bound — it runs immediately, so no data is lost between messages.
    private func beginReceiveNext() {
        connection.receive(minimumIncompleteLength: 1, maximumLength: bridgeMaxMessageBytes) { [weak self] data, context, isComplete, error in
            guard let self else { return }

            if let error {
                Task { @MainActor in self.reportError("Receive failed: \(error.localizedDescription)") }
                return
            }

            if isComplete {
                Task { @MainActor in
                    self.isConnected = false
                    self.onConnectionStateChanged?(false)
                }
                return
            }

            if let data, !data.isEmpty {
                self.consume(data)
            }

            // IMMEDIATELY schedule the next receive — must be the LAST thing we do
            // so no data is delivered between receiving and rescheduling.
            self.beginReceiveNext()
        }
    }

    // MARK: - Message parsing

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

    // MARK: - Error reporting

    private func reportError(_ message: String) {
        lastError = message
        onError?(message)
    }
}
