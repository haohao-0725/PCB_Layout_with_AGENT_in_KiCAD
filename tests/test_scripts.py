"""Unit tests for the parts of the bundled scripts that run without KiCad.

    python -m unittest discover -s tests -v
"""
from __future__ import annotations

import contextlib
import io
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "skills" / "kicad-clean-pcb" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import compare_gerbers  # noqa: E402
import gerberlib  # noqa: E402
import trace_drop  # noqa: E402  (pcbnew is imported lazily, inside main)

COPPER_A = """%TF.FileFunction,Copper,L1,Top*%
%FSLAX46Y46*%
%MOMM*%
%ADD10C,0.250000*%
%ADD11R,1.000000X1.000000*%
G01*
D10*
X0Y0D02*
X10000000Y0D01*
D11*
X5000000Y5000000D03*
M02*
"""

# Same geometry: other aperture numbers, other coordinate format, reversed draw, other order.
COPPER_B = """%TF.FileFunction,Copper,L1,Top*%
%FSLAX35Y35*%
%MOMM*%
%ADD10R,1.000000X1.000000*%
%ADD11C,0.250000*%
D10*
X500000Y500000D03*
G01*
D11*
X1000000Y0D02*
X0Y0D01*
M02*
"""

ARC_CCW = """%FSLAX46Y46*%
%MOMM*%
%ADD10C,0.200000*%
D10*
G75*
X10000000Y0D02*
G03X0Y10000000I-10000000J0D01*
M02*
"""

ARC_CW_REVERSED = """%FSLAX46Y46*%
%MOMM*%
%ADD10C,0.200000*%
D10*
G75*
X0Y10000000D02*
G02X10000000Y0I0J-10000000D01*
M02*
"""

ARC_OTHER_CENTRE = ARC_CCW.replace("I-10000000J0", "I-5000000J5000000")

OUTLINE = """%TF.FileFunction,Profile,NP*%
%FSLAX46Y46*%
%MOMM*%
%ADD10C,0.100000*%
D10*
G01*
X0Y0D02*
X100000000Y0D01*
X100000000Y30000000D01*
G75*
G03X100000000Y50000000I0J10000000D01*
G01*
X100000000Y80000000D01*
X0Y80000000D01*
X0Y0D01*
M02*
"""

DRILL_G85 = """M48
; #@! TF.FileFunction,Plated,1,4,PTH
METRIC
T1C0.800
T2C1.000
%
G90
G05
T1
X1.0Y2.0
X3.0Y4.0
T2
X5.0Y5.0G85X7.0Y5.0
M30
"""

DRILL_ROUTED = """M48
; #@! TF.FileFunction,NonPlated,1,4,NPTH
METRIC
T1C1.000
%
G90
T1
G00X5.0Y5.0
M15
G01X7.0Y5.0
M16
G05
X9.0Y9.0
M30
"""


def make_zip(folder: Path, name: str, files: dict[str, str]) -> Path:
    path = folder / name
    with zipfile.ZipFile(path, "w") as archive:
        for file_name, text in files.items():
            archive.writestr(file_name, text)
    return path


class GerberTests(unittest.TestCase):
    def test_same_geometry_ignores_numbering_format_and_order(self):
        self.assertEqual(gerberlib.Gerber(COPPER_A).items, gerberlib.Gerber(COPPER_B).items)

    def test_file_function_attribute(self):
        self.assertEqual(gerberlib.Gerber(COPPER_A).file_function, "Copper,L1,Top")

    def test_cw_arc_equals_reversed_ccw_arc(self):
        self.assertEqual(gerberlib.Gerber(ARC_CCW).items, gerberlib.Gerber(ARC_CW_REVERSED).items)

    def test_arc_centre_change_is_detected(self):
        self.assertNotEqual(gerberlib.Gerber(ARC_CCW).items, gerberlib.Gerber(ARC_OTHER_CENTRE).items)

    def test_outline_box_includes_arc_bulge(self):
        x0, y0, x1, y1 = gerberlib.Gerber(OUTLINE).outline_box_mm()
        self.assertAlmostEqual(x1 - x0, 110.0, places=2)
        self.assertAlmostEqual(y1 - y0, 80.0, places=2)


class ExcellonTests(unittest.TestCase):
    def test_holes_and_g85_slot(self):
        drill = gerberlib.Excellon(DRILL_G85)
        kinds = sorted(item[0] for item in drill.items.elements())
        self.assertEqual(kinds, ["hole", "hole", "slot"])
        self.assertEqual(drill.plating_of(800_000), "Plated")

    def test_slot_change_is_detected(self):
        moved = DRILL_G85.replace("G85X7.0", "G85X8.0")
        self.assertNotEqual(gerberlib.Excellon(DRILL_G85).items, gerberlib.Excellon(moved).items)

    def test_routed_slot_and_hole(self):
        drill = gerberlib.Excellon(DRILL_ROUTED)
        kinds = sorted(item[0] for item in drill.items.elements())
        self.assertEqual(kinds, ["hole", "route"])
        self.assertEqual(drill.plating_of(1_000_000), "NonPlated")


class CompareTests(unittest.TestCase):
    def run_compare(self, files_a, files_b) -> int:
        with tempfile.TemporaryDirectory() as tmp:
            a = make_zip(Path(tmp), "a.zip", files_a)
            b = make_zip(Path(tmp), "b.zip", files_b)
            with contextlib.redirect_stdout(io.StringIO()):
                return compare_gerbers.main(["compare_gerbers.py", str(a), str(b)])

    def test_identical_geometry_returns_0(self):
        self.assertEqual(self.run_compare({"b-F_Cu.gtl": COPPER_A, "b.drl": DRILL_G85},
                                          {"b-F_Cu.gtl": COPPER_B, "b.drl": DRILL_G85, "README.txt": "x"}), 0)

    def test_changed_slot_returns_1(self):
        self.assertEqual(self.run_compare({"b.drl": DRILL_G85},
                                          {"b.drl": DRILL_G85.replace("G85X7.0", "G85X8.0")}), 1)

    def test_missing_file_returns_1(self):
        self.assertEqual(self.run_compare({"b-F_Cu.gtl": COPPER_A, "b.drl": DRILL_G85},
                                          {"b-F_Cu.gtl": COPPER_A}), 1)


class TraceMathTests(unittest.TestCase):
    def test_copper_resistivity(self):
        self.assertAlmostEqual(trace_drop.copper_rho(20.0), 1.724e-8, delta=1e-12)
        self.assertAlmostEqual(trace_drop.copper_rho(40.0) / trace_drop.copper_rho(20.0), 1.0786, places=4)

    def test_ipc2221_reference_point(self):
        # IPC-2221 chart: about 1 A in a 0.30 mm, 1 oz outer track gives about 10 C rise.
        self.assertAlmostEqual(trace_drop.ipc2221_delta_t(1.0, 0.30, 35.0, True), 10.0, delta=1.0)

    def test_inner_layer_runs_hotter(self):
        outer = trace_drop.ipc2221_delta_t(2.0, 1.0, 35.0, True)
        inner = trace_drop.ipc2221_delta_t(2.0, 1.0, 35.0, False)
        self.assertGreater(inner, outer)

    def test_parallel(self):
        self.assertAlmostEqual(trace_drop.parallel([2.0, 2.0]), 1.0)
        self.assertEqual(trace_drop.parallel([0.0, 5.0]), 0.0)


if __name__ == "__main__":
    unittest.main()
