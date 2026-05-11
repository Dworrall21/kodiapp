import unittest

from addon.iphone_bridge import (
    BridgeProtocolError,
    decode_json_line,
    encode_json_line,
    extract_json_lines,
    make_auth_message,
    make_error_message,
    make_hello_message,
    make_result_message,
)


class IPhoneBridgeProtocolTests(unittest.TestCase):
    def test_encode_json_line_outputs_compact_utf8_json_with_newline(self):
        payload = {"type": "command", "id": "cmd-1", "method": "Input.Up", "params": {}}

        encoded = encode_json_line(payload)

        self.assertEqual(encoded, b'{"type":"command","id":"cmd-1","method":"Input.Up","params":{}}\n')

    def test_encode_json_line_rejects_non_object_messages(self):
        with self.assertRaisesRegex(BridgeProtocolError, "object"):
            encode_json_line(["not", "an", "object"])

    def test_decode_json_line_parses_single_object_line(self):
        decoded = decode_json_line(b'{"type":"auth_ok"}\n')

        self.assertEqual(decoded, {"type": "auth_ok"})

    def test_decode_json_line_rejects_missing_type(self):
        with self.assertRaisesRegex(BridgeProtocolError, "type"):
            decode_json_line(b'{"id":"cmd-1"}\n')

    def test_extract_json_lines_returns_messages_and_remainder(self):
        data = b'{"type":"hello"}\n{"type":"telemetry","volume":80}\n{"type"'

        messages, remainder = extract_json_lines(data)

        self.assertEqual(messages, [{"type": "hello"}, {"type": "telemetry", "volume": 80}])
        self.assertEqual(remainder, b'{"type"')

    def test_make_hello_message_uses_protocol_and_snake_case_keys(self):
        msg = make_hello_message(
            addon_id="script.xbox.proxy",
            addon_version="1.0.8",
            kodi_name="Kodi",
            kodi_version="21.0",
            platform="Xbox",
        )

        self.assertEqual(msg, {
            "type": "hello",
            "protocol": "iphone-bridge-v1",
            "addon_id": "script.xbox.proxy",
            "addon_version": "1.0.8",
            "kodi_name": "Kodi",
            "kodi_version": "21.0",
            "platform": "Xbox",
        })

    def test_make_auth_message_omits_empty_token(self):
        self.assertIsNone(make_auth_message(""))
        self.assertEqual(make_auth_message("secret"), {"type": "auth", "token": "secret"})

    def test_make_result_message_preserves_json_rpc_body(self):
        body = {"jsonrpc": "2.0", "id": "cmd-1", "result": "OK"}

        self.assertEqual(make_result_message("cmd-1", True, body), {
            "type": "result",
            "id": "cmd-1",
            "ok": True,
            "result": body,
        })

    def test_make_error_message_includes_optional_code(self):
        self.assertEqual(make_error_message("cmd-1", "Nope", "bad_command"), {
            "type": "error",
            "id": "cmd-1",
            "message": "Nope",
            "code": "bad_command",
        })


if __name__ == "__main__":
    unittest.main()
