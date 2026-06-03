from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import test_suite


def test_keyboard_suite_launch_uses_keyboard_script_and_cdp_env(monkeypatch):
    launched = {}

    class FakeStdout:
        def __init__(self):
            self.lines = ["[kb] virtual gamepad ready. type 'help' for commands.\n"]

        def readline(self):
            return self.lines.pop(0) if self.lines else ""

    class FakeProc:
        def __init__(self):
            self.stdout = FakeStdout()
            self.pid = 4242
            self.returncode = None
            self.terminated = False
            self.killed = False

        def poll(self):
            return self.returncode

        def terminate(self):
            self.terminated = True
            self.returncode = 0

        def kill(self):
            self.killed = True
            self.returncode = 1

    fake_proc = FakeProc()

    def fake_popen(cmd, **kwargs):
        launched["cmd"] = cmd
        launched["kwargs"] = kwargs
        return fake_proc

    monkeypatch.setattr(test_suite.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(test_suite.select, "select", lambda r, w, x, timeout=None: (r, [], []))

    client = test_suite.KeyboardSuiteClient(cdp_url="http://127.0.0.1:9222")
    resp = client.launch(timeout_s=1.0)

    assert resp["ok"] is True
    assert resp["started"] is True
    assert resp["ready"] is True
    assert launched["cmd"][0] == "node"
    assert launched["cmd"][1].endswith("keyboard.mjs")
    assert launched["kwargs"]["cwd"].endswith("/home/david/xbox-remote-drive")
    assert launched["kwargs"]["env"]["CDP_URL"] == "http://127.0.0.1:9222"

    client.stop()
    assert fake_proc.terminated is True


def test_preflight_checklist_prints_ready_state(monkeypatch, capsys, tmp_path):
    runner = test_suite.TestRunner(output_dir=tmp_path, mode="auto", proxy_url="http://proxy")

    class FakeProc:
        pid = 4242

        def poll(self):
            return None

    runner.keyboard.proc = FakeProc()  # type: ignore[assignment]
    monkeypatch.setattr(runner.remote, "is_up", lambda timeout=2.0: True)
    monkeypatch.setattr(
        runner.remote,
        "list_pages",
        lambda: [{"url": test_suite.XBOX_REMOTE_URL, "title": "Xbox Remote Play - Consoles"}],
    )

    remote_setup = {
        "ok": True,
        "chrome": {"started": True},
        "url": test_suite.XBOX_REMOTE_URL,
        "title": "Xbox Remote Play - Consoles",
        "mode": "open-new",
    }
    keyboard_setup = {"ok": True, "pid": 4242, "line": "[kb] virtual gamepad ready"}

    items = runner.preflight_checklist(remote_setup=remote_setup, keyboard_setup=keyboard_setup)
    assert [item["label"] for item in items] == ["Chrome/CDP", "Xbox session", "consoles page", "keyboard bridge", "gamepad shim"]
    assert all(item["ok"] for item in items)

    runner.print_preflight_checklist(remote_setup=remote_setup, keyboard_setup=keyboard_setup)
    out = capsys.readouterr().out
    assert "[preflight] checklist" in out
    assert "Chrome/CDP" in out
    assert "virtual gamepad ready" in out
