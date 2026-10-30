"""Tests for kcp's building tools: footprints, board builder, placement, routing, wiring plan,
voltage drop. No KiCad needed, except the integration class at the end (skipped without kicad-cli).

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

from kcp import cli, kicad_cli, previews  # noqa: E402
from kcp import place as pl  # noqa: E402
from kcp.lint import load_layer_plan  # noqa: E402
from kcp.project import write_project  # noqa: E402
from kcp.templates import create  # noqa: E402
from kcp.backends.file import load_board  # noqa: E402
from kcp.board import BoardBuilder, translate_tree  # noqa: E402
from kcp.footprints import place_footprint, stable_uuid, tht_footprint  # noqa: E402
from kcp.model import NetClass, NetClasses  # noqa: E402
from kcp.route import Router, RouteConflict, bus, cleanup, lane_order  # noqa: E402
from kcp.sexpr import loads  # noqa: E402
from kcp.tracedrop import analyse  # noqa: E402
from kcp.wiring import Design, Part, SymbolDef, write_schematic  # noqa: E402

DEMO = FIXTURES / "lint_demo.kicad_pcb"


def two_pin_fp():
    return tht_footprint("TwoPin", [{"number": 1, "x": 0, "y": 0, "size": 1.6, "drill": 0.8, "shape": "rect"},
                                    {"number": 2, "x": 2.54, "y": 0, "size": 1.6, "drill": 0.8}],
                         (-1.5, -1.5, 4.04, 1.5), silk_text=(1.27, 2.5))


def small_board():
    """30 x 20 mm, 2 layers, R1 at (10,10) and R2 at (10,15), both horizontal."""
    b = BoardBuilder.new(copper=2)
    b.outline_rect(0, 0, 30, 20)
    lib = two_pin_fp()
    b.add_footprint(place_footprint(lib, "Test:TwoPin", "R1", (10, 10), 0, nets={"1": "A", "2": "B"}))
    b.add_footprint(place_footprint(lib, "Test:TwoPin", "R2", (10, 15), 0, nets={"1": "C", "2": "D"}))
    return b


class FootprintTests(unittest.TestCase):
    def test_place_adds_rotation_to_pad_and_text_angles(self):
        fp = place_footprint(two_pin_fp(), "Test:TwoPin", "R7", (5, 6), 90, nets={"1": "N1"},
                             fields={"Silk": "PULL-UP", "Description": "x"}, value="10k", path="/abc")
        self.assertEqual(fp[1], "Test:TwoPin")
        self.assertEqual(fp.numbers("at"), [5.0, 6.0, 90.0])
        pads = fp.all("pad")
        self.assertEqual([p.numbers("at")[2] for p in pads], [90.0, 90.0])
        self.assertEqual(pads[0].value("net"), "N1")
        self.assertIsNone(pads[1].get("net"))
        props = {str(p[1]): p for p in fp.all("property")}
        self.assertEqual((str(props["Reference"][2]), str(props["Value"][2]), str(props["Silk"][2])),
                         ("R7", "10k", "PULL-UP"))
        self.assertEqual(props["Reference"].numbers("at")[2], 90.0)
        self.assertEqual(fp.value("path"), "/abc")
        self.assertIsNone(fp.get("version"))

    def test_board_position_matches_the_model(self):
        b = BoardBuilder.new(copper=2)
        b.add_footprint(place_footprint(two_pin_fp(), "Test:TwoPin", "R1", (10, 10), 90))
        r1 = b.board().footprint("R1")
        self.assertEqual([p.at for p in r1.pads], [(10.0, 10.0), (10.0, 7.46)])
        self.assertEqual(stable_uuid("a", 1), stable_uuid("a", 1))


class BoardBuilderTests(unittest.TestCase):
    def test_new_four_layer_board_round_trip(self):
        b = BoardBuilder.new(copper=4, title="t")
        b.outline_rect(0, 0, 40, 30, corner=2)
        b.add_zone("GND", ["In1.Cu"], [(0, 0), (40, 0), (40, 30), (0, 30)])
        b.add_track((1, 1), (5, 1), 0.3, "F.Cu", "S")
        b.add_via((5, 1), "S")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "x.kicad_pcb"
            b.save(path)
            board = load_board(path)
        self.assertEqual(board.copper_layers, ["F.Cu", "In1.Cu", "In2.Cu", "B.Cu"])
        x0, y0, x1, y1 = board.outline_bbox()
        self.assertAlmostEqual(x1 - x0, 40.0, places=3)
        self.assertAlmostEqual(y1 - y0, 30.0, places=3)
        self.assertEqual((len(board.tracks), len(board.vias), len(board.zones)), (1, 1, 1))
        self.assertTrue(any(s["name"] == "dielectric 1" for s in board.stackup))
        with self.assertRaises(ValueError):
            BoardBuilder.new(copper=3)

    def test_translate_moves_items_but_not_footprint_children(self):
        b = small_board()
        b.add_track((1, 1), (5, 1), 0.3, "F.Cu", "A")
        translate_tree(b.tree, 10, 5)
        board = b.board()
        self.assertEqual(board.footprint("R1").pads[0].at, (20.0, 15.0))
        self.assertEqual(board.tracks[0].start, (11.0, 6.0))
        self.assertEqual(board.outline_bbox(), (10.0, 5.0, 40.0, 25.0))


class PlaceTests(unittest.TestCase):
    def test_row_and_array(self):
        self.assertEqual(pl.row(["R1", "R2", "R3"], (1, 2), 2.54, "x", 90),
                         {"R1": (1, 2, 90), "R2": (3.54, 2, 90), "R3": (6.08, 2, 90)})
        copies = pl.array({"A": (0, 0, 180), "C": (1, 2, 0)}, 2, (0, 10), rename=lambda r, i: f"{r}{i + 1}")
        self.assertEqual(copies["C2"], (1, 12, 0))

    def test_move_rotates_pads_with_the_footprint(self):
        b = small_board()
        pl.move(b, "R1", 20, 5, 90)
        r1 = b.board().footprint("R1")
        self.assertEqual([p.at for p in r1.pads], [(20.0, 5.0), (20.0, 2.46)])
        self.assertEqual([p.angle for p in r1.pads], [90.0, 90.0])

    def test_fit_check_finds_overlaps_edges_and_keepouts(self):
        b = small_board()
        self.assertTrue(pl.fit_check(b.board())["ok"])
        pl.move(b, "R2", 11, 11)
        report = pl.fit_check(b.board(), keepouts=[(0, 0, 9, 20, "connector clearance")], edge_min=1.0)
        self.assertEqual(report["overlaps"], [["R1", "R2"]])
        self.assertEqual({k["ref"] for k in report["keepouts"]}, {"R1"})
        pl.move(b, "R2", 29, 15)
        self.assertEqual(pl.fit_check(b.board())["edge"][0]["ref"], "R2")

    def test_edge_placement(self):
        b = small_board()
        fp = b.board().footprint("R1")
        x, y = pl.at_edge(fp, (0, 0, 30, 20), "left")
        self.assertAlmostEqual(x, 1.5)          # courtyard starts 1.5 mm left of pad 1

    def test_edge_placement_and_fit_check_count_silkscreen(self):
        # Like many library terminals: a pin-1 mark drawn 0.3 mm outside the courtyard.
        part = tht_footprint("Term", [{"number": 1, "x": 0, "y": 0, "size": 2, "drill": 1}], (-2, -2, 2, 2),
                             silk=[(-2.3, -1.0, -2.1, 1.0)])
        b = BoardBuilder.new(copper=2)
        b.outline_rect(0, 0, 30, 20)
        b.add_footprint(place_footprint(part, "Test:Term", "J1", (10, 10), 0, nets={"1": "A"}))
        fp = b.board().footprint("J1")
        self.assertAlmostEqual(pl.at_edge(fp, (0, 0, 30, 20), "left", silk=False)[0], 2.0)
        x, _ = pl.at_edge(fp, (0, 0, 30, 20), "left")
        self.assertAlmostEqual(x, 2.36)         # silk line 2.3 mm left of the origin + 0.06 mm half stroke
        pl.move(b, "J1", 2.0, 10)
        report = pl.fit_check(b.board())
        self.assertFalse(report["ok"])
        self.assertEqual(report["silk_edge"], [{"ref": "J1", "margin_mm": -0.36}])
        pl.move(b, "J1", x, 10)
        self.assertTrue(pl.fit_check(b.board())["ok"])

    def test_entry_sides_and_facing_rotation(self):
        # Rotation 90 turns a part's bottom (+y) side to the right, 180 to the top, 270 to the left.
        self.assertEqual([pl.facing_rotation("bottom", s) for s in ("bottom", "right", "top", "left")],
                         [0.0, 90.0, 180.0, 270.0])
        self.assertEqual(pl.facing_rotation("left", "bottom"), 90.0)      # a barrel jack on the bottom edge
        b = BoardBuilder.new(copper=2)
        part = tht_footprint("X", [{"number": 1, "x": 0, "y": 0, "size": 2, "drill": 1}], (-2, -2, 2, 2))
        for ref, lib_id in (("J1", "TerminalBlock_Phoenix:TerminalBlock_Phoenix_MKDS-1,5-2-5.08_1x02_P5.08mm_Horizontal"),
                            ("J2", "Connector_JST:JST_EH_S3B-EH_1x03_P2.50mm_Horizontal"),
                            ("J3", "Connector_JST:JST_XH_S2B-XH-A_1x02_P2.50mm_Horizontal"),
                            ("J4", "Connector_PinHeader_2.54mm:PinHeader_1x02_P2.54mm_Vertical")):
            b.add_footprint(place_footprint(part, lib_id, ref, (10, 10), 0))
        board = b.board()
        self.assertEqual([(pl.entry_side(board.footprint(r)) or (None,))[0] for r in ("J1", "J2", "J3", "J4")],
                         ["bottom", "top", "bottom", None])     # JST EH faces the other way from XH

    def test_to_edge_turns_a_terminal_so_the_wire_goes_in_from_outside(self):
        # A terminal whose wire entry is at the bottom (+y) at rotation 0, put on the top edge.
        part = tht_footprint("Term", [{"number": 1, "x": 0, "y": 0, "size": 2, "drill": 1},
                                      {"number": 2, "x": 5.08, "y": 0, "size": 2, "drill": 1}], (-3, -5.7, 8.1, 5.1))
        b = BoardBuilder.new(copper=2)
        b.outline_rect(0, 0, 40, 30)
        lib_id = "TerminalBlock_Phoenix:TerminalBlock_Phoenix_MKDS-1,5-2-5.08_1x02_P5.08mm_Horizontal"
        b.add_footprint(place_footprint(part, lib_id, "J1", (20, 15), 0, nets={"1": "A", "2": "B"}))
        result = pl.to_edge(b, "J1", "top", entry="auto")
        self.assertEqual(result["at"][2], 180.0)
        self.assertEqual(result["entry"]["at_rotation_0"], "bottom")
        fp = b.board().footprint("J1")
        self.assertAlmostEqual(fp.courtyard_bbox()[1], 0.0, places=4)        # flush with the top edge
        self.assertAlmostEqual(fp.at[0], 20.0)                                # x unchanged
        self.assertGreater(min(p.at[1] for p in fp.pads), 5.0)               # pins inside, entry at the edge
        result = pl.to_edge(b, "J1", "left", entry="left")                   # the side it enters from, given
        self.assertEqual(result["at"][2], 0.0)
        self.assertAlmostEqual(b.board().footprint("J1").courtyard_bbox()[0], 0.0, places=4)
        b.add_footprint(place_footprint(part, "Odd:Connector", "J2", (20, 20), 90))
        with self.assertRaises(ValueError):
            pl.to_edge(b, "J2", "bottom", entry="auto")                     # unknown: asks for the side
        pl.to_edge(b, "J2", "bottom")                                         # entry None keeps the rotation
        self.assertEqual(b.board().footprint("J2").angle, 90.0)

    def test_to_edge_reports_the_makers_pcb_edge_mark(self):
        # Like USB footprints: a "PCB Edge" text on Dwgs.User 1 mm inside the courtyard's bottom edge.
        part = tht_footprint("Usb", [{"number": 1, "x": 0, "y": 0, "size": 1, "drill": 0.6}], (-4, -2.5, 4, 3.5))
        part.append(loads('(fp_text user "PCB Edge" (at 0 2.5 0) (layer "Dwgs.User") '
                          '(effects (font (size 0.5 0.5) (thickness 0.08))))'))
        b = BoardBuilder.new(copper=2)
        b.outline_rect(0, 0, 40, 30)
        b.add_footprint(place_footprint(part, "Connector_USB:Some_Receptacle", "J4", (20, 15), 0))
        result = pl.to_edge(b, "J4", "right", entry="auto")
        self.assertEqual((result["at"][2], result["entry"]["source"]), (90.0, "the footprint's PCB Edge mark"))
        self.assertEqual(result["edge_mark"]["from"], "text")
        self.assertAlmostEqual(result["edge_mark"]["inside_mm"], 1.0, places=3)


class DrcDetailsTests(unittest.TestCase):
    def test_items_are_named_from_the_board_in_any_ui_language(self):
        root = load_board(DEMO).root
        report = {"violations": [
            {"type": "silk_over_copper", "severity": "warning", "description": "絲印被防焊裁切",
             "items": [{"description": "R1 的參考標示", "pos": {"x": 10.0, "y": 10.0},
                        "uuid": "00000000-0000-4000-8000-000000000102"},
                       {"description": "焊盤 1", "pos": {"x": 10.0, "y": 10.0}, "uuid": "00000000-0000-4000-8000-000000000105"}]},
            {"type": "clearance", "severity": "error", "excluded": True, "items": []},
            {"type": "clearance", "severity": "error",
             "items": [{"description": "zone", "pos": {"x": 0, "y": 0}, "uuid": "00000000-0000-4000-8000-000000001001"},
                       {"description": "track", "pos": {"x": 12.5, "y": 20.0},
                        "uuid": "00000000-0000-4000-8000-000000000601"}]}],
            "unconnected_items": [{"type": "unconnected_items", "severity": "error",
                                   "items": [{"pos": {"x": 1, "y": 2}, "uuid": "00000000-0000-4000-8000-000000000405"},
                                             {"pos": {"x": 3, "y": 4}, "uuid": "unknown", "description": "raw text"}]}]}
        details = kicad_cli.list_violations(report, root)
        self.assertEqual(len(details), 3)                                   # the excluded one is left out
        self.assertEqual([i["item"] for i in details[0]["items"]],
                         ["R1 Reference text (F.Fab)", "R1 pad 1 [GND]"])
        self.assertEqual((details[0]["refs"], details[0]["at"]), (["R1"], [10.0, 10.0]))
        self.assertEqual(details[1]["items"][0]["item"], "zone 'GND plane' [GND]")
        self.assertEqual(details[1]["at"], [12.5, 20.0])                    # zones report 0,0: skipped
        self.assertEqual(details[2]["kind"], "unconnected")
        self.assertEqual([i["item"] for i in details[2]["items"]], ["J1 pad 1 [SIG_A]", "raw text"])
        self.assertIn("| 1 | violation | silk_over_copper | warning | R1 | 10.0, 10.0 |",
                      kicad_cli.violations_markdown(details))
        self.assertEqual(len(kicad_cli.list_violations(report, root, limit=1)), 1)


class RouteTests(unittest.TestCase):
    def router(self, b=None):
        nc = NetClasses([NetClass("Default", 0.25, 0.2)], {}, [])
        return Router(b or small_board(), nc)

    def test_path_writes_only_safe_45_degree_tracks(self):
        r = self.router()
        r.path("B", "F.Cu", 0.3, [r.pad("R1", 2), (15, 10), (17, 8), (25, 8)])
        self.assertEqual(len(r.builder.tree.all("segment")), 3)

    def test_conflicts_are_listed_and_nothing_is_written(self):
        r = self.router()
        with self.assertRaises(RouteConflict) as ctx:
            r.path("A", "F.Cu", 0.3, [r.pad("R1", 1), (10, 15), (10, 18)])      # through R2 pad 1 (net C)
        self.assertTrue(any("R2.1" in c["what"] for c in ctx.exception.conflicts))
        with self.assertRaises(RouteConflict) as ctx:
            r.path("A", "F.Cu", 0.3, [r.pad("R1", 1), (4, 7)])                  # not 0/45/90
        self.assertIn("only 0/45/90", ctx.exception.conflicts[0]["what"])
        with self.assertRaises(RouteConflict):
            r.path("A", "F.Cu", 0.3, [r.pad("R1", 1), (0.2, 10)])               # into the board edge
        self.assertEqual(r.builder.tree.all("segment"), [])

    def test_bus_refuses_lines_that_would_cross(self):
        r = self.router()
        with self.assertRaises(RouteConflict):
            bus(r, [("A", (5, 2), (25, 4)), ("B", (5, 4), (25, 2))], "F.Cu", bend=15)
        paths = bus(r, [("A", (5, 2), (25, 3)), ("B", (5, 4.5), (25, 6))], "F.Cu", bend=15)
        self.assertEqual(paths[0], [(5, 2), (15, 2), (16.0, 3), (25, 3)])

    def test_lane_order(self):
        lines = [{"net": "A", "exit": 5, "turn": "right"}, {"net": "B", "exit": 10, "turn": "right"},
                 {"net": "C", "exit": 3, "turn": "left"}]
        result = lane_order(lines, ["C", "B", "A"])
        self.assertEqual(result["order"], ["C", "B", "A"])
        self.assertEqual(result["crossings"], [])
        self.assertEqual(lane_order(lines, ["A", "B", "C"])["crossings"], [["A", "B"], ["A", "C"], ["B", "C"]])

    def test_cleanup_merges_collinear_segments(self):
        b = small_board()
        b.add_track((14, 3), (18, 3), 0.3, "F.Cu", "B")
        b.add_track((18, 3), (22, 3), 0.3, "F.Cu", "B")
        b.add_track((22, 3), (22, 3), 0.3, "F.Cu", "B")
        stats = cleanup(b)
        self.assertEqual(stats, {"removed_zero_length": 1, "merged_collinear": 1})
        seg = b.tree.all("segment")[0]
        self.assertEqual((seg.numbers("start"), seg.numbers("end")), ([14.0, 3.0], [22.0, 3.0]))


class WiringTests(unittest.TestCase):
    def design(self, pins_r2=None):
        symbols = {"R": SymbolDef("R", {"1": "", "2": ""}, ["1"], ["2"], width=5.08, prefix="R")}
        parts = [Part("R1", "10k", "R", "Test:TwoPin", {"1": "A", "2": "B"}),
                 Part("R2", "1k", "R", "Test:TwoPin", pins_r2 or {"1": "A", "2": "B"})]
        return Design("t", "Test", "A", "2026-10-29", "test", symbols, parts)

    def test_plan_problems(self):
        self.assertEqual(self.design().problems(), [])
        problems = self.design({"1": "A", "2": "LONELY"}).problems()
        self.assertTrue(any("LONELY has only one pin" in p for p in problems))
        self.assertTrue(any("pins without a net" in p for p in self.design({"1": "A"}).problems()))

    def test_schematic_has_a_label_per_connected_pin_on_grid(self):
        design = self.design()
        design.parts[0].pins["2"] = None
        design.parts[1].pins["2"] = None
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "t.kicad_sch"
            info = write_schematic(design, path)
            tree = loads(path.read_text(encoding="utf-8"))
        labels = tree.all("global_label")
        self.assertEqual(sorted(str(l[1]) for l in labels), ["A", "A"])
        self.assertEqual(len(tree.all("no_connect")), 2)
        for label in labels:
            x, y = label.numbers("at")[:2]
            self.assertAlmostEqual(x / 1.27, round(x / 1.27), places=6)
            self.assertAlmostEqual(y / 1.27, round(y / 1.27), places=6)
        self.assertEqual(set(info["symbol_uuids"]), {"R1", "R2"})
        with self.assertRaises(ValueError):
            write_schematic(self.design({"1": "A", "2": "LONELY"}), Path(tempfile.gettempdir()) / "never.kicad_sch")


class TraceDropTests(unittest.TestCase):
    def test_drop_through_a_via_and_two_layers(self):
        result = analyse(load_board(DEMO), "+5V", "J1.3", {"R3.1": 0.5})
        row = result["loads"][0]
        # 10 mm F.Cu + 14 + 9.78 mm B.Cu, all 0.8 mm x 35 um, copper at 40 C.
        expected = 1.86e-8 * (10 + 14 + 9.78) * 1e-3 / (0.8e-3 * 35e-6)
        self.assertAlmostEqual(row["path_mohm"], expected * 1e3, delta=0.2)
        self.assertAlmostEqual(row["drop_mv"], expected * 0.5 * 1e3, delta=0.1)
        self.assertFalse(result["above_limit"])
        with self.assertRaises(ValueError):
            analyse(load_board(DEMO), "+5V", "J1.9", {"R3.1": 0.5})

    def test_pads_sharing_a_number_are_one_pin(self):
        # A fuse holder: two clips per side, both numbered 1 (and 2). Only the first clip of side 1
        # has a track; the source is named by number, so every clip of that number must count.
        holder = tht_footprint("Clips", [{"number": 1, "x": 0, "y": 0, "size": 2, "drill": 1},
                                         {"number": 1, "x": 0, "y": 5, "size": 2, "drill": 1},
                                         {"number": 2, "x": 20, "y": 0, "size": 2, "drill": 1},
                                         {"number": 2, "x": 20, "y": 5, "size": 2, "drill": 1}], (-2, -2, 22, 7))
        b = BoardBuilder.new(copper=2)
        b.add_footprint(place_footprint(holder, "Test:Clips", "F1", (10, 30), 0, nets={"1": "VIN", "2": "VF"}))
        b.add_footprint(place_footprint(two_pin_fp(), "Test:TwoPin", "R1", (10, 10), 0, nets={"1": "VIN", "2": "X"}))
        b.add_track((10, 10), (10, 30), 1.0, "F.Cu", "VIN")
        board = b.board()
        result = analyse(board, "VIN", "F1.1", {"R1.1": 1.0})
        self.assertGreater(result["loads"][0]["drop_mv"], 0)
        self.assertEqual(analyse(board, "VIN", "R1.1", {"F1.1": 1.0})["loads"][0]["load"], "F1.1")


class PreviewPagesTests(unittest.TestCase):
    def test_top_layer_drawn_last_and_outer_pours_get_their_own_page(self):
        b = BoardBuilder.new(copper=2)
        b.outline_rect(0, 0, 30, 20)
        b.add_track((1, 1), (5, 1), 0.3, "F.Cu", "S")
        self.assertEqual(previews.pages(b.board())["routing"][0][:2], ["B.Cu", "F.Cu"])
        self.assertEqual(set(previews.pages(b.board())), {"routing", "assembly"})
        b.add_zone("GND", ["B.Cu"], [(0, 0), (30, 0), (30, 20), (0, 20)])
        pages = previews.pages(b.board())
        self.assertEqual(pages["routing_FCu"][0][:2], ["F.Cu", "F.SilkS"])
        self.assertEqual(pages["routing_BCu"][0][:2], ["B.Cu", "B.SilkS"])


class ProjectFileTests(unittest.TestCase):
    def test_netclasses_and_rules_read_back(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_project(Path(tmp) / "demo.kicad_pro", "root-uuid",
                                 [("Power", 1.0, 0.3, ["+12V", "VIN*"]),
                                  {"name": "Motor", "track_width": 0.8, "clearance": 0.25, "patterns": ["M_*"]}],
                                 rules={"min_copper_edge_clearance": 0.3})
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(data["meta"]["filename"], "demo.kicad_pro")
            self.assertEqual(data["sheets"], [["root-uuid", "Root"]])
            rules = data["board"]["design_settings"]["rules"]
            self.assertEqual((rules["min_copper_edge_clearance"], rules["min_clearance"]), (0.3, 0.2))
            classes = NetClasses.from_project(path)
            self.assertEqual(classes.of("+12V"), "Power")
            self.assertEqual(classes.of("VIN_RAW"), "Power")
            self.assertEqual(classes.of("M_A"), "Motor")
            self.assertEqual(classes.get("Motor").track_width, 0.8)


class NewProjectTests(unittest.TestCase):
    def test_writes_the_skeleton_and_refuses_to_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / "led_board"
            result = create(folder, copper=4)
            self.assertEqual(result["name"], "led_board")
            for name in ("build_led_board.py", "place_led_board.py", "route_led_board.py", "rebuild_led_board.py",
                         "kcp_path.py", "layer_plan.json"):
                self.assertTrue((folder / name).is_file(), name)
            for script in folder.glob("*.py"):
                text = script.read_text(encoding="utf-8")
                self.assertNotIn("__NAME__", text)
                compile(text, str(script), "exec")
            self.assertIn("COPPER = 4", (folder / "place_led_board.py").read_text(encoding="utf-8"))
            self.assertEqual(load_layer_plan(folder / "layer_plan.json")["In1.Cu"], "plane")
            with self.assertRaises(FileExistsError):
                create(folder)
            with self.assertRaises(ValueError):
                create(Path(tmp) / "bad-name")
            # kcp_path finds this kcp from the folder recorded at creation, with nothing on sys.path
            env = {k: v for k, v in os.environ.items() if k not in ("KCP_SKILL", "PYTHONPATH")}
            probe = subprocess.run([sys.executable, "-c", "import kcp_path, kcp; print(kcp.__file__)"], cwd=folder,
                                   capture_output=True, text=True, env=env)
            self.assertEqual(probe.returncode, 0, probe.stderr)
            self.assertEqual(Path(probe.stdout.strip()).resolve().parent, (SKILL / "kcp").resolve())
            from kcp import __version__
            shown = subprocess.run([sys.executable, "kcp_path.py"], cwd=folder, capture_output=True, text=True, env=env)
            self.assertTrue(shown.stdout.startswith(f"kcp {__version__} at "), shown.stdout + shown.stderr)
            # An older copy is refused with a message naming it, not imported silently
            old = Path(tmp) / "old_skill"
            (old / "kcp").mkdir(parents=True)
            (old / "kcp" / "__init__.py").write_text('__version__ = "0.2.0"\n', encoding="utf-8")
            refused = subprocess.run([sys.executable, "kcp_path.py"], cwd=folder, capture_output=True, text=True,
                                     env={**env, "KCP_SKILL": str(old)})
            self.assertEqual(refused.returncode, 1)
            self.assertIn(f"needs kcp {__version__} or newer; found 0.2.0", refused.stderr)


class CliBuildTests(unittest.TestCase):
    def run_cli(self, *argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = cli.main([str(a) for a in argv])
        return code, json.loads(out.getvalue())

    def test_route_path_dry_run_reports_conflicts(self):
        code, data = self.run_cli("route", "path", DEMO, "--net", "SIG_A", "--layer", "F.Cu",
                                  "--points", "J1.1 40,22", "--dry-run")
        self.assertEqual(code, 1)
        self.assertTrue(any("J1.2" in c["what"] for c in data["conflicts"]))
        self.assertFalse(data["written"])

    def test_place_fit_check_and_lane(self):
        code, data = self.run_cli("place", "fit-check", DEMO, "--keepout", "35,10,45,25,header area")
        self.assertEqual((code, data["keepouts"][0]["ref"]), (1, "J1"))
        code, data = self.run_cli("route", "lane", "--lines", '[{"net": "A", "exit": 1}, {"net": "B", "exit": 2}]',
                                  "--entry", "B,A")
        self.assertEqual((code, data["crossings"]), (0, []))

    def test_writes_refuse_while_kicad_is_open(self):
        with tempfile.TemporaryDirectory() as tmp:
            board = Path(tmp) / "demo.kicad_pcb"
            board.write_text(DEMO.read_text(encoding="utf-8"), encoding="utf-8")
            (Path(tmp) / "~demo.kicad_pcb.lck").write_text("lock")
            code, data = self.run_cli("place", "move", board, "R1", "12", "12")
            self.assertEqual(code, 2)
            self.assertIn("BoardLockedError", data["error"])
            code, data = cli.run(["drc", board, "--refill", "--save"])
            self.assertEqual(code, 2)
            self.assertIn("BoardLockedError", data["error"])
            code, data = cli.run(["drc", board, "--save"])
            self.assertIn("--refill", data["error"])


@unittest.skipIf(os.environ.get("KCP_SKIP_KICAD") or kicad_cli.find_kicad_cli() is None,
                 "kicad-cli not installed (or KCP_SKIP_KICAD set)")
class WiringIntegrationTests(unittest.TestCase):
    def test_generated_schematic_passes_erc_and_reads_back(self):
        from kcp.wiring import check_against_design, read_netlist
        design = WiringTests().design()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "t.kicad_sch"
            write_schematic(design, path)
            from kcp.wiring import write_lib_tables, write_symbol_library
            write_symbol_library(design, Path(tmp) / "test.kicad_sym")
            write_lib_tables(tmp, {"test": "test.kicad_sym"}, {})
            erc = kicad_cli.summarize_erc(kicad_cli.erc(path))
            components, pins = read_netlist(path)
        self.assertEqual(erc["errors"], 0)
        self.assertEqual(check_against_design(design, components, pins), [])
        self.assertTrue(components["R1"].path.endswith(stable_uuid("t", "symbol", "R1")))

    def test_new_project_runs_end_to_end(self):
        # `kcp new` -> rebuild script: ERC, netlist, fit check, routing, refill, DRC + parity, lint,
        # previews, Gerber zip and readback all pass on the placeholder board.
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / "demo"
            create(folder, copper=2)
            run = subprocess.run([sys.executable, str(folder / "rebuild_demo.py")], capture_output=True, text=True,
                                 encoding="utf-8", errors="replace", timeout=600)
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
            self.assertNotIn("[FAIL]", run.stdout)
            self.assertIn("readback matches 45x30 mm, 2 copper layers", run.stdout)
            code, data = cli.run(["fab", folder / "demo.kicad_pcb", "--out-dir", Path(tmp) / "fab2", "--zip", "x.zip"])
            self.assertEqual(code, 0, data)
            self.assertTrue(data["readback"]["ok"])
            self.assertEqual(data["expected"]["npth"], 4)


if __name__ == "__main__":
    unittest.main()
