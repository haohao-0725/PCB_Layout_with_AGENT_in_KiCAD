"""Routing for the 2-axis stepper carrier, one function per group (routing-playbook.md §2).

Layer plan (4L-S1): F.Cu horizontal (signals, phases, +5V/+3V3 lanes), In1.Cu and In2.Cu solid
GND planes (no tracks), B.Cu vertical (VM and +3V3 trunks). Every layer change happens on a
through-hole pad, so the board has no vias. Every path is pad -> bend points -> pad, computed
from the pad coordinates of the placed board; kcp's router refuses any path that is not
0/45/90 degrees or that comes closer to other copper than the netclass clearance.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "skills" / "kicad-clean-pcb"))
sys.path.insert(0, str(HERE))

from kcp.board import BoardBuilder  # noqa: E402
from kcp.model import NetClasses  # noqa: E402
from kcp.route import Router, cleanup  # noqa: E402

import build_stepper_carrier as design  # noqa: E402

PHASE_BEND_X = 20.0        # phases turn toward their terminal pins here
VM_TRUNK_X = 45.0          # B.Cu, from D1 cathode down past both drivers
V3_TRUNK_X = 49.5          # B.Cu, from CN11-16 down to the limit pull-ups
ROW = 2.54


def between_rows(y: float) -> float:
    """The lane between a header row and the next one down (for threading past outer pins)."""
    return round(y + ROW / 2, 4)


def power(r: Router) -> None:
    """Supply: J1 -> F1 -> D1 on F.Cu; VM trunk on B.Cu with a branch to each driver; +5V and +3V3."""
    p = r.pad
    r.path("VIN_RAW", "F.Cu", None, [p("J1", 1), p("F1", 1)])
    r.path("VIN_FUSED", "F.Cu", None, [p("F1", 2), p("D1", 2)])
    k = p("D1", 1)
    in_plus = p("U1", 1)
    branch = {a: p(c, 1)[1] for a, c in (("A1", "C2"), ("A2", "C4"))}       # branch y = decoupling pad 1
    trunk = [k, (VM_TRUNK_X, in_plus[1]), (VM_TRUNK_X, branch["A1"]), (VM_TRUNK_X, branch["A2"])]
    r.path("VM", "B.Cu", None, trunk)
    r.path("VM", "B.Cu", None, [(VM_TRUNK_X, in_plus[1]), in_plus])
    for driver, dec, bulk in (("A1", "C2", "C1"), ("A2", "C4", "C3")):
        vm = p(driver, 16)
        y = branch[driver]
        r.path("VM", "B.Cu", None, [(VM_TRUNK_X, y), p(dec, 1), (vm[0], y)])
        r.path("VM", "B.Cu", None, [vm, (vm[0], y), p(bulk, 1)])

    # +5V: buck output along the top of driver X, threading between CN11 rows 2 and 3 to E5V.
    out = p("U1", 3)
    e5v = p("CN11", 6)
    lane = between_rows(e5v[1] - ROW)
    r.path("+5V", "F.Cu", None, [out, (out[0], lane), (e5v[0] - 1.27, lane), e5v])

    # +3V3 from CN11-16: on F.Cu to each driver's VIO through its EN pull-up, on B.Cu down the trunk.
    v3 = p("CN11", 16)
    lane1 = between_rows(v3[1])
    start = [v3, (v3[0] - 1.27, lane1)]
    vio1 = p("A1", 10)
    r.path("+3V3", "F.Cu", None, start + [p("R1", 2)])
    r.path("+3V3", "F.Cu", None, [p("R1", 2), (vio1[0] + (lane1 - vio1[1]), lane1), vio1])
    r2 = p("R2", 2)
    r3, r4 = p("R3", 2), p("R4", 2)
    r.path("+3V3", "B.Cu", None, start + [(V3_TRUNK_X, lane1), (V3_TRUNK_X, r2[1]), r3])
    r.path("+3V3", "B.Cu", None, [(V3_TRUNK_X, r2[1]), r2])
    vio2 = p("A2", 10)
    r.path("+3V3", "F.Cu", None, [r2, (vio2[0] + (r2[1] - vio2[1]), r2[1]), vio2])
    r.path("+3V3", "B.Cu", None, [r3, (r4[0], r3[1] + (r4[0] - r3[0])), r4])


def phases(r: Router) -> None:
    """Motor phases on F.Cu: straight out of the driver, one 45-degree fan-out to the terminal."""
    for driver, term, axis in (("A1", "J2", "X"), ("A2", "J3", "Y")):
        for pin, tpin, coil in ((11, 1, "1B"), (12, 2, "1A"), (13, 3, "2A"), (14, 4, "2B")):
            a, b = r.pad(driver, pin), r.pad(term, tpin)
            dy = b[1] - a[1]
            r.path(f"{axis}_{coil}", "F.Cu", None, [a, (PHASE_BEND_X, a[1]), (PHASE_BEND_X - abs(dy), b[1]), b])


def mcu(r: Router) -> None:
    """DIR and STEP straight across to CN11; EN through the pull-up junction to an inner-row pin."""
    p = r.pad
    for driver, axis, dir_pin, step_pin in (("A1", "X", 9, 11), ("A2", "Y", 41, 43)):
        r.path(f"{axis}_DIR", "F.Cu", None, [p(driver, 1), p("CN11", dir_pin)])
        r.path(f"{axis}_STEP", "F.Cu", None, [p(driver, 2), p("CN11", step_pin)])
    # X_EN_N: EN -> junction under R1 -> 45 degrees down to the gap above CN11-27 -> CN11-28.
    en, pull, target = p("A1", 8), p("R1", 1), p("CN11", 28)
    lane = between_rows(target[1] - ROW)
    junction = (pull[0], en[1])
    r.path("X_EN_N", "F.Cu", None, [en, junction])
    r.path("X_EN_N", "F.Cu", None, [pull, junction])
    r.path("X_EN_N", "F.Cu", None, [junction, (junction[0] + (lane - en[1]), lane), (target[0] - 1.27, lane), target])
    # Y_EN_N: same pin row as CN11-56, so it steps up one half row to pass CN11-55.
    en, pull, target = p("A2", 8), p("R2", 1), p("CN11", 56)
    lane = between_rows(target[1] - ROW)
    junction = (pull[0], en[1])
    r.path("Y_EN_N", "F.Cu", None, [en, junction])
    r.path("Y_EN_N", "F.Cu", None, [pull, junction])
    step = en[1] - lane
    r.path("Y_EN_N", "F.Cu", None, [junction, (junction[0] + 1.77, en[1]), (junction[0] + 1.77 + step, lane),
                                    (target[0] - 1.27, lane), target])


def limits(r: Router) -> None:
    """Each limit input is one horizontal lane: connector, series R, C to GND, pull-up, MCU pin."""
    p = r.pad
    r.path("LIM_X_IN", "F.Cu", None, [p("J4", 1), p("R5", 1)])
    r.path("LIM_X", "F.Cu", None, [p("R5", 2), p("C5", 1), p("R3", 1), p("CN11", 65)])
    r.path("LIM_Y_IN", "F.Cu", None, [p("J5", 1), p("R6", 1)])
    target = p("CN11", 70)
    below = p("CN11", 69)
    lane_y = p("R4", 1)[1]
    r.path("LIM_Y", "F.Cu", None, [p("R6", 2), p("C6", 1), p("R4", 1), (below[0], lane_y), target])


GROUPS = [("power", power), ("phases", phases), ("mcu", mcu), ("limits", limits)]


def route(path: Path) -> dict:
    b = BoardBuilder.open(path)
    b.remove(["segment", "arc", "via"])
    netclasses = NetClasses.from_project(path.with_suffix(".kicad_pro"))
    r = Router(b, netclasses)
    done = []
    for name, group in GROUPS:
        group(r)
        done.append(name)
    stats = cleanup(b)
    b.save(path)
    return {"groups": done, "paths": len(r.log), "segments": len(b.tree.all("segment")), "vias": 0, **stats}


if __name__ == "__main__":
    print(json.dumps(route(HERE / f"{design.PROJECT}.kicad_pcb")))
