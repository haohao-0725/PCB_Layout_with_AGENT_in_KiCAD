"""Tests for the kcp tools: inspect, lint, decisions and the command line.

The kicad-cli integration test runs only when kicad-cli is installed (set KCP_SKIP_KICAD=1 to skip
it anyway; it takes about 15 s).

    python -m unittest discover -s tests -v
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SKILL = Path(__file__).resolve().parents[1] / "skills" / "kicad-clean-pcb"
FIXTURES = Path(__file__).resolve().parent / "fixtures"
sys.path.insert(0, str(SKILL))

from kcp import cli, kicad_cli  # noqa: E402
from kcp.backends.file import load_board  # noqa: E402
from kcp.decisions import check, check_file, parse  # noqa: E402
from kcp.inspection import inspect_board, to_markdown as inspect_md  # noqa: E402
from kcp.lint import lint_board, load_thresholds, to_markdown as lint_md  # noqa: E402

DEMO = FIXTURES / "lint_demo.kicad_pcb"
PLAN = {"F.Cu": "horizontal", "In1.Cu": "plane", "In2.Cu": "plane", "B.Cu": "vertical"}


def run_cli(*argv):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = cli.main([str(a) for a in argv])
    return code, out.getvalue()


class InspectTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.board = load_board(DEMO)
        cls.data = inspect_board(cls.board)

    def test_board_summary(self):
        d = self.data
        self.assertEqual(d["board"]["size_mm"], [50.0, 30.0])
        self.assertEqual(d["board"]["copper_layers"], ["F.Cu", "In1.Cu", "In2.Cu", "B.Cu"])
        self.assertEqual(d["counts"]["footprints"], 4)
        self.assertEqual(d["counts"]["pads"], 9)
        self.assertEqual(d["counts"]["segments"], 14)
        self.assertEqual(d["counts"]["vias"], 1)
        self.assertEqual(d["counts"]["zones"], 2)
        self.assertAlmostEqual(d["counts"]["track_length_mm"], 109.59, places=1)

    def test_footprints_and_pads(self):
        r1 = next(f for f in self.data["footprints"] if f["ref"] == "R1")
        self.assertEqual((r1["x"], r1["y"], r1["rot"], r1["side"]), (10.0, 10.0, 90.0, "front"))
        self.assertEqual(r1["courtyard_bbox"], [8.7, 6.16, 11.3, 11.3])
        pad2 = r1["pads"][1]
        self.assertEqual((pad2["number"], pad2["net"], pad2["x"], pad2["y"]), ("2", "SIG_A", 10.0, 7.46))
        self.assertEqual((pad2["type"], pad2["shape"], pad2["drill"]), ("thru_hole", "oval", [0.8]))

    def test_nets(self):
        nets = {n["name"]: n for n in self.data["nets"]}
        self.assertEqual(nets["+5V"]["netclass"], "Power")
        self.assertEqual((nets["SIG_A"]["pads"], nets["SIG_A"]["segments"]), (2, 4))
        self.assertEqual(nets["GND"]["pads"], 3)
        self.assertEqual(nets["+5V"]["vias"], 1)
        self.assertNotIn("unconnected", nets["GND"])          # no DRC was run

    def test_summary_filter_and_markdown(self):
        small = inspect_board(self.board, refs=["J1"], summary=True)
        self.assertEqual([f["ref"] for f in small["footprints"]], ["J1"])
        self.assertNotIn("pads", small["footprints"][0])
        md = inspect_md(self.data)
        self.assertIn("| Size | 50 × 30 mm |", md)
        self.assertIn("| GND | In1.Cu |", md)


class LintTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.board = load_board(DEMO)
        cls.result = lint_board(cls.board, "T")
        cls.metrics = {m["id"]: m for m in cls.result["metrics"]}

    def value(self, metric_id):
        return self.metrics[metric_id]["value"]

    def test_counts_on_the_demo_board(self):
        self.assertEqual(self.value("segments_total"), 14)
        self.assertEqual(self.value("off_angle_segments"), 1)
        self.assertEqual(self.value("jogs"), 1)
        self.assertEqual(self.value("max_segments_per_connection"), 7.0)
        self.assertAlmostEqual(self.value("turns_per_10mm"), 9 / 10.959, places=2)
        self.assertEqual(self.value("power_net_vias"), 1)
        self.assertEqual(self.value("signal_nets_over_via_limit"), 0)
        self.assertEqual(self.value("plane_layer_tracks"), 1)
        self.assertEqual(self.value("non_ground_zones"), 1)
        self.assertEqual(self.value("dangling_ends"), 2)
        self.assertEqual(self.value("silk_over_pads"), 1)
        self.assertAlmostEqual(self.value("row_misalignment_max_mm"), 0.3)

    def test_details_point_at_the_problems(self):
        d = self.result["details"]
        self.assertEqual(d["jogs"][0]["start"], [20.0, 6.0])
        self.assertEqual(d["off_angle"][0]["start"], [25.0, 6.5])
        self.assertEqual(sorted(x["at"][0] for x in d["dangling"]), [20.0, 25.0])
        self.assertEqual(d["silk_over_pads"][0]["pad"], "J1.2")
        self.assertEqual(d["rows"][0]["refs"], ["R1", "R2", "R3"])
        self.assertEqual(d["plane_layers"]["layers"], ["In1.Cu"])

    def test_judgement_for_the_tidy_preset(self):
        statuses = {k: m["status"] for k, m in self.metrics.items()}
        self.assertEqual(statuses["segments_per_mm"], "pass")
        self.assertEqual(statuses["off_angle_segments"], "warn")
        self.assertEqual(statuses["power_net_vias"], "warn")
        self.assertEqual(statuses["non_ground_zones"], "fail")
        self.assertEqual(statuses["dangling_ends"], "fail")
        self.assertEqual(statuses["direction_conformity_min_pct"], "skip")    # no layer plan
        self.assertEqual(statuses["segments_total"], "info")
        self.assertEqual(self.result["status"], "fail")
        self.assertIn("| Dangling track ends | 2 |", lint_md(self.result))

    def test_layer_plan(self):
        result = lint_board(self.board, "T", plan=PLAN)
        layers = result["details"]["layers"]
        self.assertAlmostEqual(layers["F.Cu"]["conformity_pct"], 51.9, places=1)
        self.assertAlmostEqual(layers["B.Cu"]["conformity_pct"], 41.1, places=1)
        conf = next(m for m in result["metrics"] if m["id"] == "direction_conformity_min_pct")
        self.assertEqual((conf["value"], conf["status"]), (41.1, "fail"))

    def test_other_presets_and_custom_thresholds(self):
        compact = {m["id"]: m for m in lint_board(self.board, "C")["metrics"]}
        self.assertEqual(compact["power_net_vias"]["status"], "info")
        custom = load_thresholds()
        custom["presets"]["T"]["metrics"]["jogs"] = {"pass_max": 0, "warn_max": 0}
        strict = {m["id"]: m for m in lint_board(self.board, "T", custom)["metrics"]}
        self.assertEqual(strict["jogs"]["status"], "fail")
        with self.assertRaises(ValueError):
            lint_board(self.board, "Z")


DECISIONS_ZH = """# PCB 決策紀錄

**Preset chosen:** T

## 範圍檢查
| ID | 問題 | 決定 (Yes/No) | 備註 |
|---|---|---|---|
| S1 | 接市電？ | No | |
| S2 | 超過 60 V？ | No | |

## Part A：偏好
| ID | 軸 | 選項 | 決定 |
|---|---|---|---|
| A1 | 誰畫 | a · b · c | a |
| A2 | 擺放 | a · b · c | **a** |

## Part B
| ID | 項目 | 解決的問題 | 成本 | 類別 | Agent 建議 | 決定 (Yes/No) | 備註 |
|---|---|---|---|---|---|---|---|
| B1 | 保險絲 | 短路燒線 | 1 顆 | A | Yes | Yes | |
| B2 | 反接保護 | 接反燒模組 | 1 顆 | A | Yes |  | |

## Part C
| ID | 檢查 | 為什麼 | 工時 | Agent 建議 | 決定 (Yes/No) | 結果 |
|---|---|---|---|---|---|---|
| C1 | 壓降 | 遠端負載電壓 | 分鐘 | Yes | Yes | |
| C2 | 3D 檢查 | 高度 | 中 | No | No | |

## Part D
| 確認點 | 使用者確認 | 日期 | 已確認 (Yes/No) | 備註 |
|---|---|---|---|---|
| CP0 | 範圍與 Part A | 2026-10-29 | Yes | |
| CP1 | 專案簡報 | | | |
| CP2 | BOM 與 B、C | | | |
| CP4 | 擺放 | | | |
"""


class DecisionsTests(unittest.TestCase):
    def test_parse_in_chinese(self):
        parsed = parse(DECISIONS_ZH)
        self.assertEqual(parsed["preset"], "T")
        ids = {r["id"]: r for r in parsed["rows"]}
        self.assertEqual(ids["A2"]["answer"], "a")
        self.assertTrue(ids["B2"]["blank"])
        self.assertEqual(ids["B1"]["answer"], "Yes")          # not the "Agent 建議" column
        self.assertEqual(parsed["warnings"], [])

    def test_checkpoints(self):
        parsed = parse(DECISIONS_ZH)
        self.assertTrue(check(parsed, "CP0")["checkpoint"]["ok"])
        cp2 = check(parsed, "CP2")["checkpoint"]
        self.assertFalse(cp2["ok"])
        self.assertIn("B2", cp2["missing"])
        self.assertIn("CP1 not confirmed in Part D", cp2["missing"])
        done = DECISIONS_ZH.replace("| 1 顆 | A | Yes |  | |", "| 1 顆 | A | Yes | Yes | |") \
                           .replace("| CP1 | 專案簡報 | | | |", "| CP1 | 專案簡報 | 2026-10-29 | 是 | |")
        self.assertTrue(check(parse(done), "CP2")["checkpoint"]["ok"])
        cp6 = check(parse(done), "CP6")["checkpoint"]["missing"]
        self.assertIn("C1 answered Yes but has no result", cp6)
        self.assertIn("CP4 not confirmed in Part D", cp6)

    def test_blank_template_and_unknown_checkpoint(self):
        result = check_file(SKILL / "assets" / "PCB_DECISIONS.template.md", "CP0")
        self.assertEqual(result["parts"]["A"]["rows"], 17)
        self.assertEqual(result["parts"]["B"]["answered"], 0)
        self.assertIn("preset chosen", result["checkpoint"]["missing"])
        with self.assertRaises(ValueError):
            check(parse(DECISIONS_ZH), "CP9")


class CliTests(unittest.TestCase):
    def test_lint_exit_code_and_json(self):
        code, out = run_cli("lint", DEMO)
        self.assertEqual(code, 1)                                   # the demo board fails preset T
        self.assertEqual(json.loads(out)["status"], "fail")

    def test_decisions_exit_code(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "PCB_DECISIONS.md"
            path.write_text(DECISIONS_ZH, encoding="utf-8")
            self.assertEqual(run_cli("decisions", path, "--checkpoint", "CP0")[0], 0)
            self.assertEqual(run_cli("decisions", path, "--checkpoint", "CP2")[0], 1)

    def test_errors_are_json_with_exit_2(self):
        code, out = run_cli("inspect", FIXTURES / "missing.kicad_pcb")
        self.assertEqual(code, 2)
        self.assertIn("FileNotFoundError", json.loads(out)["error"])

    def test_inspect_writes_markdown_to_a_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "board.md"
            code, _ = run_cli("inspect", DEMO, "--summary", "--markdown", "--out", out)
            self.assertEqual(code, 0)
            self.assertIn("# Board:", out.read_text(encoding="utf-8"))

    def test_running_the_package_folder_directly(self):
        result = subprocess.run([sys.executable, str(SKILL / "kcp"), "lint", str(DEMO), "--preset", "C"],
                                capture_output=True, text=True, encoding="utf-8")
        self.assertIn('"tool": "kcp lint"', result.stdout)


@unittest.skipIf(os.environ.get("KCP_SKIP_KICAD") or kicad_cli.find_kicad_cli() is None,
                 "kicad-cli not installed (or KCP_SKIP_KICAD set)")
class KiCadCliIntegrationTests(unittest.TestCase):
    def test_kicad_agrees_with_the_demo_board_design(self):
        before = sorted(p.name for p in FIXTURES.iterdir())
        summary = kicad_cli.summarize_drc(kicad_cli.drc(DEMO, refill=True))
        self.assertEqual(sorted(p.name for p in FIXTURES.iterdir()), before)   # nothing written next to it
        self.assertEqual(summary["unconnected_by_net"], {"SIG_A": 1})            # the dangling stub
        for kind in ("track_dangling", "isolated_copper", "silk_over_copper"):
            self.assertIn(kind, summary["by_type"])
        for kind in ("shorting_items", "clearance"):
            self.assertNotIn(kind, summary["by_type"])


if __name__ == "__main__":
    unittest.main()
