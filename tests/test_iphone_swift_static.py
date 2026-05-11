from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
IPHONE_ROOT = ROOT / "iphone" / "KodiXboxRemote"
APP = IPHONE_ROOT / "KodiXboxRemote"


class IPhoneSwiftStaticTests(unittest.TestCase):
    def read(self, relative):
        return (APP / relative).read_text()

    def test_protocol_uses_jsonserialization_not_codable_any_or_existential_decode(self):
        text = self.read("Protocol/BridgeMessage.swift")
        self.assertIn("enum BridgeMessage", text)
        self.assertIn("JSONSerialization", text)
        self.assertNotIn("[String: Any]?", text)
        self.assertNotIn("JSONDecoder().decode(BridgeMessage.self", text)
        self.assertIn("case hello(HelloMessage)", text)
        self.assertIn("case telemetry(TelemetryMessage)", text)

    def test_bridge_connection_wraps_accepted_nwconnection_and_decodes_json_lines(self):
        text = self.read("Networking/BridgeConnection.swift")
        self.assertIn("init(connection: NWConnection)", text)
        self.assertIn("send(command: CommandMessage)", text)
        self.assertIn("Data([0x0A])", text)
        self.assertIn("BridgeMessage.decode", text)
        self.assertIn("self.beginReceiveNext()", text)
        self.assertNotIn("init(host: String", text)
        self.assertNotIn("decode(BridgeMessage.self", text)

    def test_bridge_server_exposes_current_connection_and_gets_ip_with_getifaddrs(self):
        text = self.read("Networking/BridgeServer.swift")
        self.assertIn("private(set) var currentConnection", text)
        self.assertIn("getifaddrs", text)
        self.assertIn("guard let addressPointer = interface.ifa_addr", text)
        self.assertIn("NWListener", text)
        self.assertNotIn("hostInterfaceNames", text)
        self.assertNotIn("hostAddress", text)

    def test_viewmodel_imports_swiftui_and_auth_flow_matches_addon(self):
        text = self.read("ViewModels/RemoteViewModel.swift")
        self.assertIn("import SwiftUI", text)
        self.assertIn("connection.sendAuthOK()", text)
        self.assertIn("connection.sendAuthError(\"Invalid token\")", text)
        self.assertNotIn("authRequest", text)
        self.assertIn("sendCommand", text)

    def test_remote_view_uses_bool_alert_and_does_not_reach_private_server_state(self):
        text = self.read("Views/RemoteView.swift")
        self.assertIn("alert(\"Error\"", text)
        self.assertIn("viewModel.canSendCommands", text)
        self.assertNotIn("viewModel.bridgeServer", text)
        self.assertNotIn("alert(item:", text)

    def test_no_duplicate_connectionstatus_color_extension(self):
        combined = "\n".join(p.read_text() for p in APP.rglob("*.swift"))
        self.assertEqual(combined.count("var color: Color"), 1)

    def test_xcode_project_and_ci_workflow_reference_app_files(self):
        project = IPHONE_ROOT / "KodiXboxRemote.xcodeproj" / "project.pbxproj"
        scheme = IPHONE_ROOT / "KodiXboxRemote.xcodeproj" / "xcshareddata" / "xcschemes" / "KodiXboxRemote.xcscheme"
        workflow = ROOT / ".github" / "workflows" / "ios-build.yml"
        self.assertTrue(project.exists())
        self.assertTrue(scheme.exists())
        self.assertTrue(workflow.exists())
        project_text = project.read_text()
        workflow_text = workflow.read_text()
        for name in [
            "KodiXboxRemoteApp.swift",
            "BridgeMessage.swift",
            "BridgeServer.swift",
            "BridgeConnection.swift",
            "RemoteViewModel.swift",
            "RemoteView.swift",
            "ConnectionStatusView.swift",
            "Resources/Info.plist",
        ]:
            self.assertIn(name, project_text)
        self.assertIn("xcodebuild", workflow_text)
        self.assertIn("KodiXboxRemote-unsigned.ipa", workflow_text)
        self.assertIn("CODE_SIGNING_ALLOWED=NO", workflow_text)


if __name__ == "__main__":
    unittest.main()
