"""Unit tests for kcp's core: s-expression reader/writer, geometry, board model, file backend.
No KiCad needed.

    python -m unittest discover -s tests -v
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

SKILL = Path(__file__).resolve().parents[1] / "skills" / "kicad-clean-pcb"
FIXTURES = Path(__file__).resolve().parent / "fixtures"
sys.path.insert(0, str(SKILL))

from kcp import geometry as g  # noqa: E402
from kcp import sexpr  # noqa: E402
from kcp.backends.file import BoardLockedError, load_board, save_tree  # noqa: E402
from kcp.model import board_from_tree  # noqa: E402

DEMO = FIXTURES / "lint_demo.kicad_pcb"

# KiCad 7/8-style board: numbered nets, a footprint rotated 180 degrees, an arc in the outline.
OLD_FORMAT = """(kicad_pcb (version 20240108) (generator "pcbnew")
  (layers (0 "F.Cu" signal) (31 "B.Cu" signal) (44 "Edge.Cuts" user))
  (net 0 "") (net 1 "GND") (net 2 "VCC")
  (footprint "X:Y" (layer "F.Cu") (at 5 5 180)
    (property "Reference" "U1" (at 0 -2 0) (layer "F.SilkS") (effects (font (size 1 1) (thickness 0.15))))
    (pad "1" smd rect (at 1 0 180) (size 1 0.5) (layers "F.Cu") (net 1 "GND")))
  (segment (start 0 0) (end 4 5) (width 0.2) (layer "F.Cu") (net 1))
  (zone (net 2) (net_name "VCC") (layer "B.Cu") (polygon (pts (xy 0 0) (xy 1 0) (xy 1 1))))
  (gr_line (start 0 0) (end 10 0) (layer "Edge.Cuts") (width 0.05))
  (gr_arc (start 10 0) (mid 15 5) (end 10 10) (layer "Edge.Cuts") (width 0.05))
  (gr_line (start 10 10) (end 0 10) (layer "Edge.Cuts") (width 0.05))
  (gr_line (start 0 10) (end 0 0) (layer "Edge.Cuts") (width 0.05))
)
"""


class SexprTests(unittest.TestCase):
    def test_round_trip_of_a_board(self):
        tree = sexpr.load(DEMO)
        again = sexpr.loads(sexpr.dumps(tree))
        self.assertEqual(again, tree)
        self.assertIsInstance(again.value("generator"), sexpr.QStr)

    def test_quoted_strings_keep_their_type_and_escapes(self):
        node = sexpr.loads(r'(gr_text "a \"b\" \\ c" (layer F.SilkS) (hide yes))')
        self.assertEqual(node[1], 'a "b" \\ c')
        self.assertIsInstance(node[1], sexpr.QStr)
        self.assertNotIsInstance(node.value("layer"), sexpr.QStr)
        self.assertTrue(node.flag("hide"))
        self.assertEqual(sexpr.loads(sexpr.dumps(node)), node)

    def test_bare_flag_and_numbers(self):
        node = sexpr.loads("(effects (font (size 1.27 1.0)) hide)")
        self.assertTrue(node.flag("hide"))
        self.assertEqual(node.get("font").numbers("size"), [1.27, 1.0])
        self.assertIsNone(node.number("missing"))

    def test_atoms_after_lists_keep_their_order(self):
        node = sexpr.loads("(effects (font (size 1 1)) hide)")
        self.assertEqual(sexpr.loads(sexpr.dumps(node)), node)

    def test_errors(self):
        for text in ("(a (b)", "(a))", '(a "unterminated)', "", "(a) (b)"):
            with self.assertRaises(sexpr.SexprError, msg=text):
                sexpr.loads(text)


class GeometryTests(unittest.TestCase):
    def test_rotation_follows_kicad(self):
        # A pad 2.54 mm along +x in a footprint rotated 90 degrees ends up 2.54 mm *up* (y down).
        x, y = g.rotate(2.54, 0, 90)
        self.assertAlmostEqual(x, 0.0)
        self.assertAlmostEqual(y, -2.54)
        self.assertEqual(g.to_board((10, 10), 90, (2.54, 0)), (10.0, 7.46))

    def test_arc_length_and_points(self):
        self.assertAlmostEqual(g.arc_length((10, 0), (7.0710678, 7.0710678), (0, 10)), 15.708, places=2)
        pts = g.arc_points((10, 0), (15, 5), (10, 10), max_step_deg=1.0)
        self.assertAlmostEqual(max(p[0] for p in pts), 15.0, places=2)

    def test_gap_between_shapes(self):
        pad = g.Shape("point", [(0, 0)], 0.8)
        track = g.Shape("seg", [(2, -5), (2, 5)], 0.25)
        self.assertAlmostEqual(g.gap(pad, track), 0.95)
        rect = g.Shape("poly", g.rect_polygon(0, 0, 2, 2))
        inside = g.Shape("point", [(0.2, 0.3)])
        self.assertEqual(g.core_distance(rect, inside), 0.0)
        self.assertLess(g.gap(rect, g.Shape("seg", [(0.9, -3), (0.9, 3)], 0.1)), 0)

    def test_grid_index(self):
        index = g.GridIndex(5.0)
        index.add((0, 0, 1, 1), "a")
        index.add((20, 20, 21, 21), "b")
        self.assertEqual(index.query((0.5, 0.5, 0.6, 0.6)), ["a"])
        self.assertEqual(index.query((10, 10, 11, 11)), [])


class ModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.board = load_board(DEMO)

    def test_layers_and_outline(self):
        b = self.board
        self.assertEqual(b.copper_layers, ["F.Cu", "In1.Cu", "In2.Cu", "B.Cu"])
        self.assertEqual(b.outline_bbox(), (0.0, 0.0, 50.0, 30.0))
        self.assertEqual(b.format_version, "20260206")
        self.assertEqual(len(b.stackup), 7)

    def test_footprint_children_are_placed_like_kicad(self):
        r1 = self.board.footprint("R1")
        self.assertEqual([(p.number, p.at) for p in r1.pads], [("1", (10.0, 10.0)), ("2", (10.0, 7.46))])
        self.assertEqual(r1.pads[1].angle, 90.0)
        self.assertEqual(r1.pads[1].net, "SIG_A")
        box = r1.courtyard_bbox()
        for got, want in zip(box, (8.7, 6.16, 11.3, 11.3)):
            self.assertAlmostEqual(got, want)
        j1 = self.board.footprint("J1")
        ref = next(t for t in j1.texts if t.kind == "reference")
        self.assertEqual((ref.text, ref.layer, ref.at), ("J1", "F.SilkS", (40.0, 17.54)))

    def test_nets_tracks_vias_zones_and_netclasses(self):
        b = self.board
        self.assertEqual(b.nets(), ["+5V", "GND", "SIG_A", "SIG_B"])
        self.assertEqual(len(b.tracks), 14)
        self.assertEqual(len(b.vias), 1)
        self.assertEqual([(z.net, z.layers) for z in b.zones], [("GND", ["In1.Cu"]), ("+5V", ["B.Cu"])])
        self.assertEqual(b.netclasses.of("+5V"), "Power")
        self.assertEqual(b.netclasses.of("SIG_A"), "Default")
        self.assertTrue(b.zones[0].contains((25, 15), "In1.Cu"))

    def test_old_numbered_net_format(self):
        b = board_from_tree(sexpr.loads(OLD_FORMAT))
        self.assertEqual(b.tracks[0].net, "GND")
        self.assertEqual(b.zones[0].net, "VCC")
        pad = b.footprint("U1").pads[0]
        self.assertEqual((pad.net, pad.at), ("GND", (4.0, 5.0)))
        x0, y0, x1, y1 = b.outline_bbox()
        self.assertAlmostEqual(x1, 15.0, places=2)      # the arc bulges past the straight edges
        self.assertEqual((x0, y0, y1), (0.0, 0.0, 10.0))


class FileBackendTests(unittest.TestCase):
    def test_refuses_to_write_while_kicad_has_the_project_open(self):
        tree = sexpr.load(DEMO)
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "demo.kicad_pcb"
            save_tree(tree, target)
            self.assertEqual(sexpr.load(target), tree)
            (Path(tmp) / "~demo.kicad_pcb.lck").write_text("lock")
            with self.assertRaises(BoardLockedError):
                save_tree(tree, target)
            save_tree(tree, target, force=True)


if __name__ == "__main__":
    unittest.main()
