import Foundation

let bridgeProtocolVersion = "iphone-bridge-v1"
let bridgeMaxMessageBytes = 256 * 1024

struct HelloMessage {
    let protocolVersion: String
    let addonID: String
    let addonVersion: String
    let kodiName: String
    let kodiVersion: String
    let platform: String
}

struct AuthMessage {
    let token: String
}

struct AuthResponseMessage {
    let type: String
    let message: String?

    func jsonObject() -> [String: Any] {
        var object: [String: Any] = ["type": type]
        if let message { object["message"] = message }
        return object
    }
}

struct CommandMessage {
    let id: String
    let method: String
    let params: [String: Any]

    func jsonObject() -> [String: Any] {
        ["type": "command", "id": id, "method": method, "params": params]
    }
}

struct ResultMessage {
    let id: String?
    let ok: Bool
    let result: Any?
    let error: String?
}

struct ErrorMessage {
    let id: String?
    let message: String
    let code: String?
}

struct TelemetryMessage {
    let timestamp: TimeInterval?
    let activePlayers: [[String: Any]]
    let volume: Int?
    let muted: Bool?
    let item: [String: Any]
}

enum BridgeMessage {
    case hello(HelloMessage)
    case auth(AuthMessage)
    case authOK
    case authError(String?)
    case command(CommandMessage)
    case result(ResultMessage)
    case error(ErrorMessage)
    case telemetry(TelemetryMessage)
    case ping(String?)
    case pong(String?)
    case unknown(String, [String: Any])

    static func decode(_ data: Data) throws -> BridgeMessage {
        let object = try JSONObject.decode(data)
        guard let type = object["type"] as? String, !type.isEmpty else {
            throw BridgeMessageError.missingType
        }

        switch type {
        case "hello":
            return .hello(HelloMessage(
                protocolVersion: object["protocol"] as? String ?? "",
                addonID: object["addon_id"] as? String ?? "",
                addonVersion: object["addon_version"] as? String ?? "",
                kodiName: object["kodi_name"] as? String ?? "Kodi",
                kodiVersion: object["kodi_version"] as? String ?? "",
                platform: object["platform"] as? String ?? ""
            ))
        case "auth":
            return .auth(AuthMessage(token: object["token"] as? String ?? ""))
        case "auth_ok":
            return .authOK
        case "auth_error":
            return .authError(object["message"] as? String)
        case "result":
            return .result(ResultMessage(
                id: object["id"] as? String,
                ok: object["ok"] as? Bool ?? false,
                result: object["result"],
                error: object["error"] as? String
            ))
        case "error":
            return .error(ErrorMessage(
                id: object["id"] as? String,
                message: object["message"] as? String ?? "Unknown error",
                code: object["code"] as? String
            ))
        case "telemetry":
            return .telemetry(TelemetryMessage(
                timestamp: object["timestamp"] as? TimeInterval,
                activePlayers: object["active_players"] as? [[String: Any]] ?? [],
                volume: object["volume"] as? Int,
                muted: object["muted"] as? Bool,
                item: object["item"] as? [String: Any] ?? [:]
            ))
        case "ping":
            return .ping(object["id"] as? String)
        case "pong":
            return .pong(object["id"] as? String)
        case "command":
            return .command(CommandMessage(
                id: object["id"] as? String ?? UUID().uuidString,
                method: object["method"] as? String ?? "",
                params: object["params"] as? [String: Any] ?? [:]
            ))
        default:
            return .unknown(type, object)
        }
    }
}

enum BridgeMessageError: Error, LocalizedError {
    case missingType
    case notJSONObject
    case messageTooLarge

    var errorDescription: String? {
        switch self {
        case .missingType: return "Bridge message missing type"
        case .notJSONObject: return "Bridge message was not a JSON object"
        case .messageTooLarge: return "Bridge message exceeded size limit"
        }
    }
}

enum JSONObject {
    static func encode(_ object: [String: Any]) throws -> Data {
        guard JSONSerialization.isValidJSONObject(object) else { throw BridgeMessageError.notJSONObject }
        let data = try JSONSerialization.data(withJSONObject: object, options: [])
        if data.count > bridgeMaxMessageBytes { throw BridgeMessageError.messageTooLarge }
        return data
    }

    static func encodeLine(_ object: [String: Any]) throws -> Data {
        var data = try encode(object)
        data.append(0x0A)
        return data
    }

    static func decode(_ data: Data) throws -> [String: Any] {
        if data.count > bridgeMaxMessageBytes { throw BridgeMessageError.messageTooLarge }
        let json = try JSONSerialization.jsonObject(with: data, options: [])
        guard let object = json as? [String: Any] else { throw BridgeMessageError.notJSONObject }
        return object
    }
}
