"""Wiring plan for the 2-axis stepper carrier, and everything generated from it.

Writes: the schematic (stepper_carrier.kicad_sch), its symbol library, the custom footprints
(stepper_carrier.pretty), project lib tables, the project file with design rules and netclasses,
bom.csv and design.json. This file is the source of truth for the circuit: change a net, a value
or a footprint here, then run rebuild_stepper_carrier.py.

Measured dimensions (Nucleo-144 Morpho grid, MKS TMC2209 V2.0 18-pin socket layout, 5.08 mm
terminal blocks, 5x20 fuse holder) come from a previous carrier the author measured. The LM2596
module pad positions are ASSUMED (typical 43 x 21 mm module) and must be measured before ordering.
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "skills" / "kicad-clean-pcb"))

from kcp.footprints import tht_footprint  # noqa: E402
from kcp.sexpr import dumps  # noqa: E402
from kcp.wiring import (Design, Part, SymbolDef, bom_rows, write_lib_tables,  # noqa: E402
                        write_schematic, write_symbol_library)

PROJECT = "stepper_carrier"
LIB = "stepper_carrier"
REVISION = "A"
DATE = "2026-10-29"

# ---------------------------------------------------------------- footprints (library ids)

R_FP = "Resistor_THT:R_Axial_DIN0207_L6.3mm_D2.5mm_P2.54mm_Vertical"
C_FP = "Capacitor_THT:C_Disc_D5.0mm_W2.5mm_P5.00mm"
CP_FP = "Capacitor_THT:CP_Radial_D10.0mm_P5.00mm"         # 470 uF / 50 V, 10 mm can: measure yours
D_FP = "Diode_THT:D_DO-201AD_P5.08mm_Vertical_AnodeUp"
HDR2_FP = "Connector_PinHeader_2.54mm:PinHeader_1x02_P2.54mm_Vertical"
HOLE_FP = "MountingHole:MountingHole_3.2mm_M3"
MORPHO_FP = f"{LIB}:Morpho_2x35_P2.54mm_TopView"
TMC_FP = f"{LIB}:MKS_TMC2209_V2_Sockets_18P"
TERM2_FP = f"{LIB}:Terminal_5.08mm_2P"
TERM4_FP = f"{LIB}:Terminal_5.08mm_4P"
FUSE_FP = f"{LIB}:Fuseholder_5x20mm_P23.25mm"
BUCK_FP = f"{LIB}:LM2596_Module_43x21mm"

# ---------------------------------------------------------------- symbols

def two_pin(name, prefix, names=("", "")):
    return SymbolDef(name, {"1": names[0], "2": names[1]}, ["1"], ["2"], width=5.08, prefix=prefix)


TMC_PINS = {"1": "DIR", "2": "STEP", "3": "CLK/NC", "4": "PDN_UART", "5": "UART_R8", "6": "MS2", "7": "MS1",
            "8": "~{EN}", "9": "GND", "10": "VIO", "11": "1B", "12": "1A", "13": "2A", "14": "2B", "15": "GND",
            "16": "VM", "17": "VREF", "18": "DIAG"}

# Morpho pin names: only pins checked against ST UM1974 on a previous build; others stay unnamed.
CN11_NAMES = {6: "E5V", 8: "GND", 9: "PF6", 11: "PF7", 16: "+3V3", 18: "5V_OUT", 19: "GND", 20: "GND", 22: "GND",
              28: "PA0", 30: "PA1", 35: "PC2", 41: "PD5", 43: "PD6", 46: "PE2", 47: "PE3", 48: "PE4", 49: "GND",
              50: "PE5", 51: "PF1", 52: "PF2", 53: "PF0", 54: "PF8", 56: "PF9", 60: "GND", 61: "PE1", 62: "PE6",
              63: "PG9", 65: "PG12", 66: "PG10", 68: "PG13", 70: "PG11"}
CN12_NAMES = {3: "PB8", 4: "PC6", 5: "PB9", 9: "GND", 19: "PC7", 20: "GND", 24: "PB1", 36: "PF5", 38: "PF4",
              39: "GND", 41: "PD13", 43: "PD12", 44: "PE7", 54: "GND", 57: "PF13", 58: "PF3", 59: "PF12",
              63: "GND", 64: "PE0", 66: "PG8"}


def morpho(name, names):
    pins = {str(n): names.get(n, "") for n in range(1, 71)}
    return SymbolDef(name, pins, [str(n) for n in range(1, 71, 2)], [str(n) for n in range(2, 71, 2)],
                     width=15.24, prefix="CN", description="Nucleo-144 Morpho connector, top view")


SYMBOLS = {
    "R": two_pin("R", "R"),
    "C": two_pin("C", "C"),
    "C_Polarized": two_pin("C_Polarized", "C", ("+", "-")),
    "D_Schottky": two_pin("D_Schottky", "D", ("K", "A")),
    "Fuse": two_pin("Fuse", "F"),
    "Conn_01x02": SymbolDef("Conn_01x02", {"1": "", "2": ""}, ["1", "2"], prefix="J", width=5.08),
    "Conn_01x04": SymbolDef("Conn_01x04", {str(i): "" for i in range(1, 5)}, ["1", "2", "3", "4"], prefix="J",
                            width=5.08),
    "LM2596_Module": SymbolDef("LM2596_Module", {"1": "IN+", "2": "IN-", "3": "OUT+", "4": "OUT-"},
                               ["1", "2"], ["3", "4"], width=15.24, prefix="U",
                               description="LM2596 buck module, adjusted to 5.0 V before use"),
    "MKS_TMC2209_V2": SymbolDef("MKS_TMC2209_V2", TMC_PINS, ["8", "7", "6", "5", "4", "3", "2", "1", "17", "18"],
                                ["16", "15", "14", "13", "12", "11", "10", "9"], width=15.24, prefix="A",
                                description="MKS TMC2209 V2.0 StepStick driver module (socketed)"),
    "Morpho_CN11": morpho("Morpho_CN11", CN11_NAMES),
    "Morpho_CN12": morpho("Morpho_CN12", CN12_NAMES),
}

# ---------------------------------------------------------------- parts and nets

GND = "GND"


def driver(ref, axis):
    """One TMC2209 module: standalone mode, 1/8 microstep (MS1 = MS2 = GND), PDN_UART tied low."""
    return Part(ref, "MKS TMC2209 V2.0", "MKS_TMC2209_V2", TMC_FP, {
        "1": f"{axis}_DIR", "2": f"{axis}_STEP", "3": None, "4": GND, "5": None, "6": GND, "7": GND,
        "8": f"{axis}_EN_N", "9": GND, "10": "+3V3", "11": f"{axis}_1B", "12": f"{axis}_1A", "13": f"{axis}_2A",
        "14": f"{axis}_2B", "15": GND, "16": "VM", "17": None, "18": None},
        {"Silk": f"DRIVER {axis}", "Description": "Socketed module; set motor current with its VREF pot"},
        group=f"axis {axis}")


def morpho_part(ref, symbol, nets):
    pins = {str(n): nets.get(n) for n in range(1, 71)}
    return Part(ref, f"NUCLEO-F446ZE {ref} socket 2x35", symbol, MORPHO_FP, pins,
                {"Silk": f"NUCLEO {ref}", "Description": "2x35 female header, >= 8.5 mm"}, group="nucleo")


CN11_NETS = {6: "+5V", 16: "+3V3", 9: "X_DIR", 11: "X_STEP", 28: "X_EN_N", 41: "Y_DIR", 43: "Y_STEP",
             56: "Y_EN_N", 65: "LIM_X", 70: "LIM_Y", **{n: GND for n in (8, 19, 20, 22, 49, 60)}}
CN12_NETS = {n: GND for n in (9, 20, 39, 54, 63)}

PARTS = [
    Part("J1", "VIN 12-24V", "Conn_01x02", TERM2_FP, {"1": "VIN_RAW", "2": GND},
         {"Silk": "12-24V IN", "Description": "5.08 mm screw terminal, 1 = +"}, group="power"),
    Part("F1", "3A slow", "Fuse", FUSE_FP, {"1": "VIN_RAW", "2": "VIN_FUSED"},
         {"Silk": "FUSE", "Description": "5x20 mm fuse holder; size the fuse for the measured supply current"},
         group="power"),
    Part("D1", "SB560", "D_Schottky", D_FP, {"1": "VM", "2": "VIN_FUSED"},
         {"Description": "Series reverse-polarity protection, 5 A 60 V Schottky (1N5822 also fits)"}, group="power"),
    Part("U1", "LM2596 module 5V", "LM2596_Module", BUCK_FP, {"1": "VM", "2": GND, "3": "+5V", "4": GND},
         {"Silk": "5V BUCK", "Description": "Adjust to 5.0 V before fitting the Nucleo"}, group="power"),
    driver("A1", "X"),
    Part("C1", "470uF 50V", "C_Polarized", CP_FP, {"1": "VM", "2": GND},
         {"Description": "Driver X bulk, low ESR, >= 50 V; sized for braking energy (PCB_DECISIONS C6)"}, group="axis X"),
    Part("C2", "100nF 50V", "C", C_FP, {"1": "VM", "2": GND}, {"Description": "Driver X VM decoupling"},
         group="axis X"),
    Part("R1", "10k", "R", R_FP, {"1": "X_EN_N", "2": "+3V3"},
         {"Description": "Driver X disabled until the MCU pulls EN low"}, group="axis X"),
    Part("J2", "MOTOR X", "Conn_01x04", TERM4_FP, {"1": "X_1B", "2": "X_1A", "3": "X_2A", "4": "X_2B"},
         {"Silk": "MOTOR X", "Description": "Two joined 2P 5.08 mm terminals: 1B 1A 2A 2B"}, group="axis X"),
    driver("A2", "Y"),
    Part("C3", "470uF 50V", "C_Polarized", CP_FP, {"1": "VM", "2": GND},
         {"Description": "Driver Y bulk, low ESR, >= 50 V; sized for braking energy (PCB_DECISIONS C6)"}, group="axis Y"),
    Part("C4", "100nF 50V", "C", C_FP, {"1": "VM", "2": GND}, {"Description": "Driver Y VM decoupling"},
         group="axis Y"),
    Part("R2", "10k", "R", R_FP, {"1": "Y_EN_N", "2": "+3V3"},
         {"Description": "Driver Y disabled until the MCU pulls EN low"}, group="axis Y"),
    Part("J3", "MOTOR Y", "Conn_01x04", TERM4_FP, {"1": "Y_1B", "2": "Y_1A", "3": "Y_2A", "4": "Y_2B"},
         {"Silk": "MOTOR Y", "Description": "Two joined 2P 5.08 mm terminals: 1B 1A 2A 2B"}, group="axis Y"),
    Part("J4", "LIMIT X", "Conn_01x02", HDR2_FP, {"1": "LIM_X_IN", "2": GND},
         {"Description": "Normally-open limit switch to GND"}, group="limits"),
    Part("R3", "10k", "R", R_FP, {"1": "LIM_X", "2": "+3V3"}, {"Description": "Limit X pull-up (MCU side)"},
         group="limits"),
    Part("R5", "1k", "R", R_FP, {"1": "LIM_X_IN", "2": "LIM_X"}, {"Description": "Limit X RC filter"},
         group="limits"),
    Part("C5", "10nF", "C", C_FP, {"1": "LIM_X", "2": GND}, {"Description": "Limit X RC filter, ~10 us"},
         group="limits"),
    Part("J5", "LIMIT Y", "Conn_01x02", HDR2_FP, {"1": "LIM_Y_IN", "2": GND},
         {"Description": "Normally-open limit switch to GND"}, group="limits"),
    Part("R4", "10k", "R", R_FP, {"1": "LIM_Y", "2": "+3V3"}, {"Description": "Limit Y pull-up (MCU side)"},
         group="limits"),
    Part("R6", "1k", "R", R_FP, {"1": "LIM_Y_IN", "2": "LIM_Y"}, {"Description": "Limit Y RC filter"},
         group="limits"),
    Part("C6", "10nF", "C", C_FP, {"1": "LIM_Y", "2": GND}, {"Description": "Limit Y RC filter, ~10 us"},
         group="limits"),
    morpho_part("CN11", "Morpho_CN11", CN11_NETS),
    morpho_part("CN12", "Morpho_CN12", CN12_NETS),
]

NOTES = [
    "Operating rules: set the Nucleo power jumper to E5V (UM1974) and never connect the carrier +5V to CN11-18 (5V output).",
    "Adjust the LM2596 module to 5.0 V with no load before fitting the Nucleo. Plug or unplug modules only with power off.",
    "Drivers run standalone: MS1 = MS2 = GND (1/8 step), PDN_UART low; set motor current with each module's VREF pot.",
    "D1 blocks a reversed supply and regenerated current; with small steppers the bus rise is negligible (estimate in PCB_DECISIONS.md).",
]

DESIGN = Design(PROJECT, "2-axis stepper carrier for NUCLEO-F446ZE (kicad-clean-pcb example)", REVISION, DATE,
                LIB, SYMBOLS, PARTS, NOTES, paper="A2")

# Boards-only footprints (no schematic symbol): mounting holes.
HOLES = {"H1": (3.5, 3.5), "H2": (122.5, 3.5), "H3": (3.5, 142.5), "H4": (122.5, 142.5)}

# ---------------------------------------------------------------- netclasses and rules

NETCLASSES = [
    # name, track width, clearance, patterns
    ("Supply", 1.5, 0.3, ["VIN_RAW", "VIN_FUSED", "VM"]),
    ("Motor", 1.0, 0.3, ["*_1A", "*_1B", "*_2A", "*_2B"]),
    ("LogicPower", 0.5, 0.2, ["+5V", "+3V3"]),
]
RULES = {"min_clearance": 0.2, "min_track_width": 0.2, "min_via_diameter": 0.6, "min_via_annular_width": 0.13,
         "min_through_hole_diameter": 0.3, "min_hole_to_hole": 0.25, "min_hole_clearance": 0.25,
         "min_copper_edge_clearance": 0.5, "min_silk_clearance": 0.0, "min_text_height": 0.8,
         "min_text_thickness": 0.15, "solder_mask_to_copper_clearance": 0.0}


def project_json(root_uuid: str) -> dict:
    classes = [{"name": "Default", "clearance": 0.2, "track_width": 0.25, "via_diameter": 0.8, "via_drill": 0.4,
                "priority": 2147483647}]
    patterns = []
    for i, (name, width, clearance, pats) in enumerate(NETCLASSES):
        classes.append({"name": name, "clearance": clearance, "track_width": width, "via_diameter": 1.0,
                        "via_drill": 0.5, "priority": i})
        patterns += [{"netclass": name, "pattern": p} for p in pats]
    return {
        "board": {"design_settings": {"rules": RULES, "defaults": {"silk_line_width": 0.15, "silk_text_size_h": 1.0,
                                                                   "silk_text_size_v": 1.0,
                                                                   "silk_text_thickness": 0.15}}},
        "meta": {"filename": f"{PROJECT}.kicad_pro", "version": 3},
        "net_settings": {"classes": classes, "meta": {"version": 4}, "netclass_assignments": None,
                         "netclass_patterns": patterns},
        "sheets": [[root_uuid, "Root"]],
        "text_variables": {},
    }


# ---------------------------------------------------------------- custom footprints (measured)

def morpho_footprint():
    pads = []
    for n in range(1, 71):
        pads.append({"number": n, "x": 0.0 if n % 2 else 2.54, "y": ((n + 1) // 2 - 1) * 2.54, "size": 1.6,
                     "drill": 1.0, "shape": "rect" if n == 1 else "circle"})
    return tht_footprint("Morpho_2x35_P2.54mm_TopView", pads, (-1.8, -1.8, 4.34, 88.16),
                         fab=[(-1.27, -1.27, 3.81, 87.63)], silk=[(-1.4, -1.4, 3.94, 87.76)],
                         descr="Nucleo-144 Morpho 2x35 socket, top view: odd pins left, pin 1 at the ST-LINK end",
                         ref_at=(1.27, -2.8), value_at=(1.27, 89.5), silk_text=(-2.6, 44.0, 90))


def tmc_footprint():
    grid = {1: (8, 1), 2: (7, 1), 3: (6, 1), 4: (5, 1), 5: (4, 1), 6: (3, 1), 7: (2, 1), 8: (1, 1),
            9: (8, 6), 10: (7, 6), 11: (6, 6), 12: (5, 6), 13: (4, 6), 14: (3, 6), 15: (2, 6), 16: (1, 6),
            17: (1, 2), 18: (1, 3)}
    power = {9, 11, 12, 13, 14, 15, 16}
    pads = [{"number": n, "x": (col - 1) * 2.54, "y": (row - 1) * 2.54, "size": 1.8 if n in power else 1.6,
             "drill": 1.0, "shape": "rect" if n == 1 else "circle"} for n, (row, col) in grid.items()]
    return tht_footprint("MKS_TMC2209_V2_Sockets_18P", pads, (-1.5, -1.56, 14.2, 19.34),
                         fab=[(-1.25, -1.31, 13.95, 19.09)], silk=[(-1.4, -1.46, 14.1, 19.24)],
                         descr="MKS TMC2209 V2.0 StepStick: 2x8 sockets + VREF/DIAG, origin = EN, VM at (12.7, 0); "
                               "module 15.2 x 20.4 mm (measured)",
                         ref_at=(6.35, 9.5), value_at=(6.35, 20.5), silk_text=(6.35, 11.5))


def terminal_footprint(n):
    pitch = 5.08
    pads = [{"number": i + 1, "x": i * pitch, "y": 0.0, "size": 3.2, "drill": 1.6,
             "shape": "roundrect" if i == 0 else "circle"} for i in range(n)]
    x0, x1 = -2.55, (n - 1) * pitch + 2.55
    body = (x0, -4.8, x1, 5.0)          # measured: pin centre to back face 4.8 mm, to wire entry 5.0 mm
    return tht_footprint(f"Terminal_5.08mm_{n}P", pads, (x0 - 0.25, -5.05, x1 + 0.25, 5.25),
                         fab=[body], silk=[(x0 - 0.12, -4.92, x1 + 0.12, 5.12)],
                         descr=f"{n}-pole 5.08 mm screw terminal (measured body), wire entry on +y",
                         ref_at=((n - 1) * pitch / 2, -6.2), value_at=((n - 1) * pitch / 2, 6.5),
                         silk_text=((n - 1) * pitch / 2, 3.4))


def fuse_footprint():
    pitch = 23.25                        # measured: blades 23.7 mm outside, 0.45 mm thick
    pads = [{"number": 1, "x": 0.0, "y": 0.0, "size": 2.5, "drill": 1.6, "shape": "circle"},
            {"number": 2, "x": pitch, "y": 0.0, "size": 2.5, "drill": 1.6, "shape": "circle"}]
    cx = pitch / 2
    body = (cx - 12.25, -5.075, cx + 12.25, 5.075)
    return tht_footprint("Fuseholder_5x20mm_P23.25mm", pads, (-1.55, -5.33, pitch + 1.55, 5.33),
                         fab=[body], silk=[(-1.5, -5.2, pitch + 1.5, 5.2)],
                         descr="5x20 mm fuse holder, 2 flat blades 1.3 mm wide at 23.25 mm (measured)",
                         ref_at=(cx, -6.3), value_at=(cx, 6.3), silk_text=(cx, 0.0))


def buck_footprint():
    # ASSUMED geometry of a common 43 x 21 mm LM2596 module: IN pads on the right short edge,
    # OUT pads on the left, + at the top. Measure the real module and update before ordering.
    pads = [{"number": 1, "x": 19.0, "y": -7.5, "size": 2.5, "drill": 1.3, "shape": "roundrect"},
            {"number": 2, "x": 19.0, "y": 7.5, "size": 2.5, "drill": 1.3},
            {"number": 3, "x": -19.0, "y": 7.5, "size": 2.5, "drill": 1.3, "shape": "roundrect"},
            {"number": 4, "x": -19.0, "y": -7.5, "size": 2.5, "drill": 1.3}]
    return tht_footprint("LM2596_Module_43x21mm", pads, (-21.75, -10.75, 21.75, 10.75),
                         fab=[(-21.5, -10.5, 21.5, 10.5)], silk=[(-21.62, -10.62, 21.62, 10.62)],
                         descr="LM2596 buck module 43 x 21 mm, pads 1 IN+ 2 IN- 3 OUT+ 4 OUT- (ASSUMED, measure)",
                         ref_at=(0.0, -3.0), value_at=(0.0, 3.0), silk_text=(0.0, 0.0))


FOOTPRINTS = {"Morpho_2x35_P2.54mm_TopView": morpho_footprint, "MKS_TMC2209_V2_Sockets_18P": tmc_footprint,
              "Terminal_5.08mm_2P": lambda: terminal_footprint(2), "Terminal_5.08mm_4P": lambda: terminal_footprint(4),
              "Fuseholder_5x20mm_P23.25mm": fuse_footprint, "LM2596_Module_43x21mm": buck_footprint}


def build() -> dict:
    pretty = HERE / f"{LIB}.pretty"
    pretty.mkdir(exist_ok=True)
    for name, make in FOOTPRINTS.items():
        (pretty / f"{name}.kicad_mod").write_text(dumps(make()), encoding="utf-8", newline="\n")
    write_lib_tables(HERE, {LIB: f"{LIB}.kicad_sym"}, {LIB: f"{LIB}.pretty"})
    write_symbol_library(DESIGN, HERE / f"{LIB}.kicad_sym")
    info = write_schematic(DESIGN, HERE / f"{PROJECT}.kicad_sch")
    (HERE / f"{PROJECT}.kicad_pro").write_text(json.dumps(project_json(info["root_uuid"]), indent=2) + "\n", encoding="utf-8",
                                                newline="\n")
    with (HERE / "bom.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["refs", "qty", "value", "footprint"])
        writer.writeheader()
        writer.writerows(bom_rows(DESIGN))
    manifest = {"project": PROJECT, "revision": REVISION, "date": DATE,
                "parts": [{"ref": p.ref, "value": p.value, "footprint": p.footprint, "pins": p.pins,
                           "fields": p.fields, "group": p.group} for p in PARTS],
                "board_only": {ref: {"footprint": HOLE_FP, "at": at} for ref, at in HOLES.items()},
                "netclasses": [{"name": n, "width": w, "clearance": c, "patterns": p} for n, w, c, p in NETCLASSES]}
    (HERE / "design.json").write_text(json.dumps(manifest, indent=1) + "\n", encoding="utf-8", newline="\n")
    return info


if __name__ == "__main__":
    info = build()
    print(json.dumps({"schematic": f"{PROJECT}.kicad_sch", "parts": len(PARTS), "nets": len(DESIGN.nets()),
                      "root_uuid": info["root_uuid"]}))
