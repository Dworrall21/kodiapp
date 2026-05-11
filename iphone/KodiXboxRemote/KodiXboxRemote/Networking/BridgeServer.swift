import Foundation
import Network
import Darwin

@MainActor
final class BridgeServer: ObservableObject {
    @Published private(set) var isListening = false
    @Published private(set) var port: UInt16
    @Published private(set) var localAddress: String = "0.0.0.0"
    @Published private(set) var lastError: String?
    @Published private(set) var currentConnection: BridgeConnection?

    private var listener: NWListener?
    private let queue = DispatchQueue(label: "KodiXboxRemote.BridgeServer")

    var onConnectionEstablished: ((BridgeConnection) -> Void)?
    var onConnectionLost: (() -> Void)?
    var onError: ((String) -> Void)?

    init(port: UInt16 = 9192) {
        self.port = port
        self.localAddress = Self.firstWiFiIPv4Address() ?? "0.0.0.0"
    }

    func startListening(port newPort: UInt16? = nil) {
        if let newPort { port = newPort }
        guard listener == nil else { return }
        do {
            let parameters = NWParameters.tcp
            parameters.allowLocalEndpointReuse = true
            parameters.requiredInterfaceType = .wifi
            let endpointPort = NWEndpoint.Port(rawValue: port) ?? 9192
            let listener = try NWListener(using: parameters, on: endpointPort)
            listener.stateUpdateHandler = { [weak self] state in
                Task { @MainActor in self?.handleListenerState(state) }
            }
            listener.newConnectionHandler = { [weak self] connection in
                Task { @MainActor in self?.handleNewConnection(connection) }
            }
            self.listener = listener
            localAddress = Self.firstWiFiIPv4Address() ?? "0.0.0.0"
            listener.start(queue: queue)
        } catch {
            reportError("Failed to start listener: \(error.localizedDescription)")
            isListening = false
        }
    }

    func stopListening() {
        listener?.cancel()
        listener = nil
        currentConnection?.disconnect()
        currentConnection = nil
        isListening = false
        onConnectionLost?()
    }

    private func handleListenerState(_ state: NWListener.State) {
        switch state {
        case .ready:
            isListening = true
            lastError = nil
        case .failed(let error):
            reportError("Listener failed: \(error.localizedDescription)")
            stopListening()
        case .cancelled:
            isListening = false
        default:
            break
        }
    }

    private func handleNewConnection(_ nwConnection: NWConnection) {
        currentConnection?.disconnect()
        let connection = BridgeConnection(connection: nwConnection)
        connection.onConnectionStateChanged = { [weak self] connected in
            guard let self else { return }
            if !connected {
                self.currentConnection = nil
                self.onConnectionLost?()
            }
        }
        connection.onError = { [weak self] error in self?.reportError(error) }
        currentConnection = connection
        onConnectionEstablished?(connection)
        connection.start()
    }

    private func reportError(_ message: String) {
        lastError = message
        onError?(message)
    }

    static func firstWiFiIPv4Address() -> String? {
        var interfaces: UnsafeMutablePointer<ifaddrs>?
        guard getifaddrs(&interfaces) == 0, let first = interfaces else { return nil }
        defer { freeifaddrs(interfaces) }

        var pointer: UnsafeMutablePointer<ifaddrs>? = first
        while let current = pointer {
            defer { pointer = current.pointee.ifa_next }
            let interface = current.pointee
            guard let addressPointer = interface.ifa_addr else { continue }
            let family = addressPointer.pointee.sa_family
            guard family == UInt8(AF_INET) else { continue }
            let name = String(cString: interface.ifa_name)
            guard name == "en0" || name.hasPrefix("en") else { continue }

            var hostname = [CChar](repeating: 0, count: Int(NI_MAXHOST))
            let result = getnameinfo(
                addressPointer,
                socklen_t(addressPointer.pointee.sa_len),
                &hostname,
                socklen_t(hostname.count),
                nil,
                0,
                NI_NUMERICHOST
            )
            if result == 0 {
                let address = String(cString: hostname)
                if address != "127.0.0.1" && !address.hasPrefix("169.254") {
                    return address
                }
            }
        }
        return nil
    }
}
