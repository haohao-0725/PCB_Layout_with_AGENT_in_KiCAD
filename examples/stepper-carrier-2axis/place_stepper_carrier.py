"""Placement for the 2-axis stepper carrier: board outline, GND planes, every footprint.

Nets, values, fields and schematic paths come from KiCad's own netlist of the schematic, so the
board matches the schematic (parity) the way "Update PCB from schematic" would make it.
Positions are the parameters below; the routing script derives every track from the pads.

Layout (top view, all cables enter from the left edge):
- top: power entry J1 -> F1 -> D1 along the top edge, LM2596 module below it;
- left column: driver X (A1) and driver Y (A2), each with its motor terminal on the left edge,
  bulk + 100 nF capacitors right below the VM pin, EN pull-up beside the control pins;
- bottom left: two limit inputs (connector, pull-up, series R, capacitor at the MCU side);
- right: NUCLEO-F446ZE on two 2x35 Morpho sockets (CN11 faces the drivers), nothing tall in front
  of its USB connectors (top and bottom ends).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "skills" / "kicad-clean-pcb"))
sys.path.insert(0, str(HERE))

from kcp.board import BoardBuilder  # noqa: E402
from kcp.footprints import FootprintLibrary, place_footprint  # noqa: E402
from kcp.place import fit_check, set_text  # noqa: E402
from kcp.wiring import read_netlist  # noqa: E402

import build_stepper_carrier as design  # noqa: E402

BOARD = (0.0, 0.0, 126.0, 146.0)               # outline x0, y0, x1, y1 (mm)
NUCLEO = (53.0, 6.0)                            # Nucleo-144 top-left corner (70 x 133.34 mm)
CN11 = (NUCLEO[0] + 2.77, NUCLEO[1] + 32.27)    # pin 1: housing 1.5 mm from the left edge, row 1 ~31 mm down
CN12 = (CN11[0] + 60.96, CN11[1])               # odd column 60.96 mm right of CN11's (measured grid)
ROW = 2.54
TERMINAL_X = 5.3                                # screw terminals: wire entry flush with the left edge

# Each driver unit: origin = EN pad, rotated 180 so the motor pins face the left edge.
DRIVER_EN = {"A1": (43.0, CN11[1] + 4 * ROW + 17.78), "A2": (43.0, CN11[1] + 20 * ROW + 17.78)}
UNIT = {  # relative to the driver's EN pad
    "bulk": (-12.7, 4.99),        # C1/C3 + pad, 10 mm can kept below the module
    "decoupling": (-5.0, 3.29),   # C2/C4 pad 1, on the VM branch
    "pullup": (4.5, -6.35),       # R1/R2 pad 1 (EN); pad 2 (+3V3) is 2.54 mm above
    "terminal": (-38.0, -16.51),  # J2/J3 pin 1 on the left edge
}

PLACEMENT = {
    # ref: (x, y, rotation)
    "J1": (TERMINAL_X, 10.0, 270), "F1": (12.0, 10.0, 0), "D1": (45.0, 10.0, 180), "U1": (22.0, 29.0, 0),
    "J4": (5.0, CN11[1] + 32 * ROW, 0), "J5": (5.0, CN11[1] + 35 * ROW, 0),
    # Limit inputs: connector -> 1k series -> C to GND -> 10k pull-up -> MCU pin, one lane each.
    "R5": (20.0, CN11[1] + 32 * ROW, 0), "C5": (42.0, CN11[1] + 32 * ROW, 90), "R3": (49.5, CN11[1] + 32 * ROW, 90),
    "R6": (24.0, CN11[1] + 35 * ROW, 0), "C6": (46.0, CN11[1] + 35 * ROW, 270), "R4": (51.5, CN11[1] + 35 * ROW, 90),
    "CN11": (CN11[0], CN11[1], 0), "CN12": (CN12[0], CN12[1], 0),
}
for driver, bulk, dec, pullup, term in (("A1", "C1", "C2", "R1", "J2"), ("A2", "C3", "C4", "R2", "J3")):
    ex, ey = DRIVER_EN[driver]
    PLACEMENT[driver] = (ex, ey, 180)
    PLACEMENT[bulk] = (ex + UNIT["bulk"][0], ey + UNIT["bulk"][1], 270)
    PLACEMENT[dec] = (ex + UNIT["decoupling"][0], ey + UNIT["decoupling"][1], 270)
    PLACEMENT[pullup] = (ex + UNIT["pullup"][0], ey + UNIT["pullup"][1], 90)
    PLACEMENT[term] = (TERMINAL_X, ey + UNIT["terminal"][1], 270)

# Keep-outs checked by the fit check (x0, y0, x1, y1, reason).
KEEPOUTS = [
    (NUCLEO[0] + 7.0, 0.0, NUCLEO[0] + 63.0, NUCLEO[1], "in front of the Nucleo ST-LINK USB"),
    (CN11[0] + 4.6, CN11[1] - 4.0, CN12[0] - 2.0, CN11[1] + 36 * ROW, "under the Nucleo, between the sockets"),
]

# Reference text positions (footprint-local, absolute angle) where the library default collides.
REF_TEXT = {
    "R1": ((1.27, -1.9), 90), "R2": ((1.27, -1.9), 90), "R3": ((1.27, -1.9), 90), "R4": ((1.27, 1.9), 90),
    "R5": ((1.27, -2.3), 0), "R6": ((1.27, -2.3), 0),
    "C2": ((2.5, -2.3), 90), "C4": ((2.5, -2.3), 90), "C5": ((2.5, 2.3), 90), "C6": ((2.5, 2.3), 90),
    "C1": ((2.5, 7.0), 0), "C3": ((2.5, 7.0), 0), "D1": ((2.54, -3.6), 0),
    "J4": ((2.6, 0.0), 0), "J5": ((2.6, 0.0), 0),
}

PIN_LABELS = {"J1": ["+", "-"], "J2": ["1B", "1A", "2A", "2B"], "J3": ["1B", "1A", "2A", "2B"]}


def place(path: Path) -> dict:
    components, pin_nets = read_netlist(HERE / f"{design.PROJECT}.kicad_sch")
    b = BoardBuilder.new(copper=4, thickness=1.6, title=design.DESIGN.title, revision=design.REVISION,
                         date=design.DATE)
    b.outline_rect(*BOARD)
    nucleo = (NUCLEO[0], NUCLEO[1], NUCLEO[0] + 70.0, NUCLEO[1] + 133.34)
    b.add_rect(nucleo[:2], nucleo[2:], "Dwgs.User", 0.15)
    b.add_text("NUCLEO-F446ZE outline (USB at both ends)", (nucleo[0] + 35.0, nucleo[1] + 3.0), "Dwgs.User")
    outline = [(BOARD[0], BOARD[1]), (BOARD[2], BOARD[1]), (BOARD[2], BOARD[3]), (BOARD[0], BOARD[3])]
    for layer in ("In1.Cu", "In2.Cu"):
        b.add_zone("GND", [layer], outline, name=f"GND {layer}", clearance=0.3, thermal_gap=0.5, spoke_width=0.5)

    lib = FootprintLibrary(HERE)
    for ref, comp in components.items():
        x, y, rot = PLACEMENT[ref]
        nets = {pin: net for (r, pin), net in pin_nets.items() if r == ref}
        fp = place_footprint(lib.load(comp.footprint), comp.footprint, ref, (x, y), rot, nets=nets,
                             fields=comp.fields, value=comp.value, path=comp.path, seed=f"{design.PROJECT}/{ref}")
        b.add_footprint(fp)
    for ref, at in design.HOLES.items():
        fp = place_footprint(lib.load(design.HOLE_FP), design.HOLE_FP, ref, at, 0, board_only=True,
                             seed=f"{design.PROJECT}/{ref}")
        b.add_footprint(fp)
        set_text(b, ref, "Reference", (0.0, 0.0), 0, hide=True)

    for ref, (local, angle) in REF_TEXT.items():
        set_text(b, ref, "Reference", local, angle)
    # Pin names inside each terminal's outline, between the pads and the back face.
    for ref, labels in PIN_LABELS.items():
        x, y, _ = PLACEMENT[ref]
        for i, label in enumerate(labels):
            b.add_text(label, (x + 2.3, y + 5.08 * i), "F.SilkS", 1.0, justify="left")
    b.add_text("2-AXIS STEPPER CARRIER  rev " + design.REVISION, (26.0, 140.5), "F.SilkS", 1.2)
    b.add_text("kicad-clean-pcb example", (26.0, 142.8), "F.SilkS", 1.0)

    # Long values clutter the assembly drawing; the silkscreen function names already say what these are.
    for ref in ("CN11", "CN12", "J1", "J2", "J3", *design.HOLES):
        fp = b.footprint(ref)
        value = next(p for p in fp.all("property") if str(p[1]) == "Value")
        set_text(b, ref, "Value", (float(value.get("at")[1]), float(value.get("at")[2])), hide=True)

    b.save(path)
    report = fit_check(b.board(path), keepouts=KEEPOUTS, edge_min=0.0)
    return report


if __name__ == "__main__":
    report = place(HERE / f"{design.PROJECT}.kicad_pcb")
    print(json.dumps(report))
    sys.exit(0 if report["ok"] else 1)
