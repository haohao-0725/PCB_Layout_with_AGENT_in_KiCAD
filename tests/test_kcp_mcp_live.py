"""Tests for the MCP server (built-in JSON-RPC path, tool schemas, thread safety) and the live IPC
backend (against a stand-in for kipy, so no running KiCad is needed).

    python -m unittest discover -s tests -v
"""
from __future__ import annotations

import io
import json
import sys
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace

SKILL = Path(__file__).resolve().parents[1] / "skills" / "kicad-clean-pcb"
FIXTURES = Path(__file__).resolve().parent / "fixtures"
REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL))

from kcp import cli, mcp_server  # noqa: E402
from kcp.backends.ipc import LiveBoard  # noqa: E402

DEMO = FIXTURES / "lint_demo.kicad_pcb"


class McpTests(unittest.TestCase):
    def test_tools_match_cli_subcommands_and_have_schemas(self):
        tools = {t["name"]: t for t in mcp_server.tool_list()}
        self.assertGreaterEqual(len(tools), 14)
        schema = tools["route_path"]["inputSchema"]
        self.assertEqual(schema["required"], ["board", "net", "layer", "points"])
        self.assertEqual(schema["properties"]["points"], {"type": "array", "items": {"type": "string"}})
        self.assertTrue(tools["inspect_board"]["annotations"]["readOnlyHint"])
        self.assertFalse(tools["place_move"]["annotations"]["readOnlyHint"])

    def test_builtin_server_round_trip(self):
        messages = [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize",
             "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t"}}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
             "params": {"name": "lint_board", "arguments": {"board": str(DEMO), "preset": "C"}}},
            {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "nope", "arguments": {}}},
            {"jsonrpc": "2.0", "id": 5, "method": "unknown/method"},
        ]
        stdin = io.StringIO("\n".join(json.dumps(m) for m in messages) + "\n")
        stdout = io.StringIO()
        mcp_server.serve_builtin(stdin, stdout)
        replies = {r["id"]: r for r in map(json.loads, stdout.getvalue().splitlines())}
        self.assertEqual(set(replies), {1, 2, 3, 4, 5})            # no reply to the notification
        self.assertEqual(replies[1]["result"]["serverInfo"]["name"], "kicad-clean-pcb")
        self.assertIn("lint_board", [t["name"] for t in replies[2]["result"]["tools"]])
        data = replies[3]["result"]["structuredContent"]
        self.assertEqual((data["exit_code"], data["result"]["preset"]), (1, "C"))
        self.assertEqual(replies[4]["error"]["code"], -32602)
        self.assertEqual(replies[5]["error"]["code"], -32601)

    def test_cli_run_is_quiet_and_thread_safe(self):
        results = {}

        def call(name, argv):
            results[name] = cli.run(argv)

        threads = [threading.Thread(target=call, args=("lint", ["lint", str(DEMO)])),
                   threading.Thread(target=call, args=("lane", ["route", "lane", "--lines", '[{"net": "A", "exit": 1}]'])),
                   threading.Thread(target=call, args=("bad", ["inspect"]))]
        out = io.StringIO()
        real = sys.stdout
        sys.stdout = out
        try:
            for t in threads:
                t.start()
            for t in threads:
                t.join()
        finally:
            sys.stdout = real
        self.assertEqual(out.getvalue(), "")
        self.assertEqual(results["lint"][1]["tool"], "kcp lint")
        self.assertEqual(results["lane"], (0, {"tool": "kcp route lane", "order": ["A"]}))
        self.assertEqual(results["bad"][0], 2)

    def test_plugin_declares_the_server(self):
        # Declared in plugin.json, not a root .mcp.json: a root .mcp.json is also read as the project's
        # own MCP config when the repository is opened in Claude Code, where ${CLAUDE_PLUGIN_ROOT}
        # has no value and the server fails to start.
        config = json.loads((REPO / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
        server = config["mcpServers"]["kicad-clean-pcb"]
        self.assertEqual(server["args"][-1], "mcp")
        self.assertIn("${CLAUDE_PLUGIN_ROOT}", server["args"][0])
        script = Path(server["args"][0].replace("${CLAUDE_PLUGIN_ROOT}", str(REPO)))
        self.assertTrue((script / "__main__.py").is_file())
        self.assertFalse((REPO / ".mcp.json").exists())


# ---------------------------------------------------------------- live backend with a fake kipy

class FakeTrack(SimpleNamespace):
    pass


class FakeBoard:
    def __init__(self):
        self.text = DEMO.read_text(encoding="utf-8")
        self.calls = []
        self.fp = SimpleNamespace(reference_field=SimpleNamespace(text=SimpleNamespace(value="R1")),
                                  position=None, orientation=None)

    def get_as_string(self):
        return self.text

    def get_project(self):
        return SimpleNamespace(path=str(FIXTURES))

    def begin_commit(self):
        self.calls.append(("begin",))
        return "commit-1"

    def push_commit(self, commit, message=""):
        self.calls.append(("push", commit, message))

    def drop_commit(self, commit):
        self.calls.append(("drop", commit))

    def create_items(self, items):
        self.calls.append(("create", list(items)))
        return items

    def update_items(self, items):
        self.calls.append(("update", list(items)))
        return items

    def get_footprints(self):
        return [self.fp]


def fake_api():
    return SimpleNamespace(KiCad=None, Track=FakeTrack, Net=lambda name: ("net", name),
                           Angle=SimpleNamespace(from_degrees=lambda d: ("deg", d)),
                           Vector2=SimpleNamespace(from_xy_mm=lambda x, y: (x, y)),
                           from_mm=lambda v: int(round(v * 1e6)), layer=lambda name: ("layer", name))


class LiveBackendTests(unittest.TestCase):
    def live(self):
        board = FakeBoard()
        return LiveBoard(kicad=SimpleNamespace(get_board=lambda: board), api=fake_api()), board

    def test_snapshot_reads_the_open_board_with_project_netclasses(self):
        live, _ = self.live()
        snap = live.snapshot()
        self.assertEqual(len(snap.footprints), 4)
        self.assertEqual(snap.netclasses.of("+5V"), "Power")

    def test_route_path_is_one_commit_and_refuses_conflicts(self):
        live, board = self.live()
        result = live.route_path("SIG_A", "F.Cu", None, ["J1.1", (40, 22)])
        self.assertTrue(result["conflicts"])
        self.assertEqual(board.calls, [])                                     # nothing written
        result = live.route_path("SIG_A", "F.Cu", 0.3, ["R1.2", (10, 2), (30, 2)])
        self.assertEqual((result["conflicts"], result["segments"]), ([], 2))
        kinds = [c[0] for c in board.calls]
        self.assertEqual(kinds, ["begin", "create", "push"])
        self.assertEqual(board.calls[-1][2], "kcp: route SIG_A")
        track = board.calls[1][1][0]
        self.assertEqual((track.start, track.end, track.width, track.layer, track.net),
                         ((10.0, 7.46), (10.0, 2.0), 300000, ("layer", "F.Cu"), ("net", "SIG_A")))

    def test_move_and_drop_on_failure(self):
        live, board = self.live()
        live.move_footprint("R1", 12, 14, 90)
        self.assertEqual(board.fp.position, (12, 14))
        self.assertEqual(board.fp.orientation, ("deg", 90))
        self.assertEqual(board.calls[-1], ("push", "commit-1", "kcp: move R1"))
        with self.assertRaises(RuntimeError):
            with live.commit("kcp: test"):
                raise RuntimeError("boom")
        self.assertEqual(board.calls[-1], ("drop", "commit-1"))
        with self.assertRaises(KeyError):
            live.move_footprint("R99", 0, 0)


if __name__ == "__main__":
    unittest.main()
