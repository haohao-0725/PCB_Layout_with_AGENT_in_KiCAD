"""Single entry point: rebuild the whole example from the wiring plan to the fab zip.

    python rebuild_stepper_carrier.py            # everything
    python rebuild_stepper_carrier.py --until pcb  # stop after the board checks

Steps (one line each, stops at the first failure):
  schematic: build -> ERC 0/0 -> KiCad netlist == wiring plan
  pcb:       place + fit check -> route -> refill planes -> DRC + parity 0 -> lint (preset T) -> drop/rise
  fab:       previews + 1:1 fit check -> Gerber + drill -> zip -> readback against the board

Refuses to run while KiCad has the project open (~*.lck), because KiCad would overwrite the result.
Any Python 3.9+; needs kicad-cli (KiCad 10) and, for PNG previews, Poppler's pdftoppm.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILL = HERE.parents[1] / "skills" / "kicad-clean-pcb"
sys.path.insert(0, str(SKILL))
sys.path.insert(0, str(HERE))

from kcp import kicad_cli  # noqa: E402
from kcp.backends.file import load_board, lock_files  # noqa: E402
from kcp.lint import lint_board, load_layer_plan, to_markdown as lint_md  # noqa: E402
from kcp.previews import export as export_previews  # noqa: E402
from kcp.tracedrop import analyse, to_text  # noqa: E402
from kcp.wiring import check_against_design, read_netlist  # noqa: E402

import build_stepper_carrier as design  # noqa: E402
import place_stepper_carrier as placement  # noqa: E402
import route_stepper_carrier as routing  # noqa: E402

PROJECT = design.PROJECT
SCH = HERE / f"{PROJECT}.kicad_sch"
PCB = HERE / f"{PROJECT}.kicad_pcb"
REPORTS = HERE / "reports"
REVIEW = HERE / "review"
FAB = HERE / "fab"
LAYER_PLAN = HERE.parents[0] / "layer-plans" / "4L-S1.json"
GERBER_LAYERS = ["F.Cu", "In1.Cu", "In2.Cu", "B.Cu", "F.Mask", "B.Mask", "F.SilkS", "B.SilkS", "Edge.Cuts"]
ZIP = FAB / f"{PROJECT}_rev{design.REVISION}_fab.zip"

# Current targets for the drop / rise check (Part A: 2 x measured; no measurement yet, so these are
# design assumptions recorded in PCB_DECISIONS.md, rows C1/C2).
DROP_CHECKS = [
    ("VM", "D1.1", {"A1.16": 1.0, "A2.16": 1.0, "U1.1": 0.3}),
    ("+5V", "U1.3", {"CN11.6": 0.5}),
]


class Failed(RuntimeError):
    pass


def step(name: str, func):
    try:
        detail = func()
    except Failed as exc:
        print(f"[FAIL] {name}: {exc}")
        raise SystemExit(1)
    print(f"[OK]   {name}" + (f": {detail}" if detail else ""))


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")


def schematic_steps() -> None:
    step("build schematic, libraries, rules", lambda: f"{len(design.PARTS)} parts" if design.build() else "")

    def erc():
        summary = kicad_cli.summarize_erc(kicad_cli.erc(SCH))
        write_json(REPORTS / "erc.json", summary)
        if summary["violations"]:
            raise Failed(f"{summary['errors']} errors, {summary['warnings']} warnings: {summary['by_type']}")
        return "0 errors, 0 warnings"
    step("ERC", erc)

    def netlist():
        components, pins = read_netlist(SCH)
        issues = check_against_design(design.DESIGN, components, pins)
        write_json(REPORTS / "netlist_check.json", {"components": len(components), "issues": issues})
        if issues:
            raise Failed("; ".join(issues[:5]))
        return f"{len(components)} components, every pin matches the wiring plan"
    step("netlist vs wiring plan", netlist)


def pcb_steps() -> None:
    def place():
        report = placement.place(PCB)
        write_json(REPORTS / "fit_check.json", report)
        if not report["ok"]:
            raise Failed(json.dumps(report))
        return "no courtyard overlaps, keep-outs clear"
    step("place + fit check", place)
    step("route", lambda: json.dumps(routing.route(PCB)))

    def refill():
        result = kicad_cli.run(["pcb", "drc", "--refill-zones", "--save-board", "--format", "json",
                                "--output", str(REPORTS / "drc_refill.json"), str(PCB)])
        (REPORTS / "drc_refill.json").unlink(missing_ok=True)
        if result.returncode not in (0, 5):
            raise Failed(result.stderr or result.stdout)
        return "GND planes filled, board saved by KiCad"
    step("refill planes", refill)

    def drc():
        summary = kicad_cli.summarize_drc(kicad_cli.drc(PCB, parity=True))
        write_json(REPORTS / "drc.json", summary)
        bad = summary["violations"] + summary["unconnected"] + summary["schematic_parity"]
        if bad:
            raise Failed(json.dumps(summary))
        return "0 violations, 0 unconnected, parity 0"
    step("DRC + schematic parity", drc)

    def lint():
        result = lint_board(load_board(PCB), "T", plan=load_layer_plan(LAYER_PLAN))
        write_json(REPORTS / "lint.json", result)
        (REPORTS / "lint.md").write_text(lint_md(result).replace(str(HERE) + "\\", "").replace(str(HERE) + "/", ""),
                                         encoding="utf-8", newline="\n")
        if result["status"] == "fail":
            raise Failed(", ".join(m["id"] for m in result["metrics"] if m["status"] == "fail"))
        return f"{result['status']} ({result['summary']})"
    step("tidiness lint (preset T)", lint)

    def drop():
        board = load_board(PCB)
        texts, results = [], []
        for net, source, loads in DROP_CHECKS:
            result = analyse(board, net, source, loads, temp_c=40.0, dt_limit=20.0)
            results.append(result)
            texts.append(to_text(result))
        write_json(REPORTS / "trace_drop.json", results)
        (REPORTS / "trace_drop.txt").write_text("\n".join(texts), encoding="utf-8", newline="\n")
        worst = max(results, key=lambda r: r["hottest"]["dt_c"] if r["hottest"] else 0)
        if any(r["above_limit"] for r in results):
            raise Failed("track temperature rise above 20 C")
        return ", ".join(f"{r['net']} max drop {max(x['drop_mv'] for x in r['loads']):.0f} mV" for r in results) \
            + f"; hottest dT {worst['hottest']['dt_c']} C"
    step("voltage drop / temperature rise", drop)


def fab_steps() -> None:
    def previews():
        result = export_previews(PCB, REVIEW)
        return ", ".join(result["files"])
    step("previews + 1:1 fit check", previews)

    def fab():
        gerber_dir = FAB / "gerber"
        if gerber_dir.exists():
            shutil.rmtree(gerber_dir)
        gerber_dir.mkdir(parents=True)
        kicad_cli.export_gerbers(PCB, gerber_dir, GERBER_LAYERS)
        kicad_cli.export_drill(PCB, gerber_dir)
        files = sorted(p for p in gerber_dir.iterdir() if p.is_file() and p.suffix.lower() != ".gbrjob")
        board = load_board(PCB)
        box = board.outline_bbox()
        readme = (f"{PROJECT} rev {design.REVISION} - bare boards only, no assembly\n"
                  f"Size {box[2] - box[0]:g} x {box[3] - box[1]:g} mm, 4 layers, 1.6 mm FR-4, "
                  "outer 1 oz, inner 0.5 oz, HASL\n"
                  "Layer order: see LAYER_ORDER below (read back from the X2 attributes)\n"
                  "Min track 0.25 mm, min space 0.2 mm, min hole 0.8 mm; no vias\n"
                  "PTH and NPTH drill files are separate.\n")
        sums = []
        with zipfile.ZipFile(ZIP, "w", zipfile.ZIP_DEFLATED) as archive:
            for f in files:
                archive.write(f, f.name)
                sums.append(f"{hashlib.sha256(f.read_bytes()).hexdigest()}  {f.name}")
            readback = subprocess.run([sys.executable, str(SKILL / "scripts" / "gerber_readback.py"), str(gerber_dir),
                                       "--markdown"], capture_output=True, text=True, encoding="utf-8")
            order = [line for line in readback.stdout.splitlines() if line.startswith("| L")]
            archive.writestr("README.txt", readme + "\nLAYER_ORDER\n" + "\n".join(order) + "\n")
            archive.writestr("SHA256SUMS.txt", "\n".join(sums) + "\n")
        return f"{ZIP.relative_to(HERE)} ({len(files)} files)"
    step("Gerber + drill + zip", fab)

    def readback():
        board = load_board(PCB)
        box = board.outline_bbox()
        pth = sum(1 for p in board.pads if p.kind == "thru_hole") + len(board.vias)
        npth = sum(1 for p in board.pads if p.kind == "np_thru_hole")
        result = subprocess.run([sys.executable, str(SKILL / "scripts" / "gerber_readback.py"), str(ZIP),
                                 "--expect-size", f"{box[2] - box[0]:g}x{box[3] - box[1]:g}", "--expect-copper",
                                 str(len(board.copper_layers)), "--expect-pth", str(pth), "--expect-npth", str(npth),
                                 "--markdown"], capture_output=True, text=True, encoding="utf-8")
        (REPORTS / "readback.md").write_text(result.stdout, encoding="utf-8", newline="\n")
        if result.returncode:
            raise Failed(result.stdout[-400:])
        return f"size, 4 copper layers, {pth} PTH, {npth} NPTH match the board"
    step("Gerber readback", readback)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--until", choices=["schematic", "pcb", "fab"], default="fab")
    args = parser.parse_args()
    locks = lock_files(PCB)
    if locks:
        print(f"[FAIL] KiCad has the project open ({', '.join(p.name for p in locks)}); close it first")
        return 1
    REPORTS.mkdir(exist_ok=True)
    schematic_steps()
    if args.until in ("pcb", "fab"):
        pcb_steps()
    if args.until == "fab":
        fab_steps()
    return 0


if __name__ == "__main__":
    sys.exit(main())
