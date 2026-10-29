"""Read back a fabrication bundle (.zip or folder) the way a fab would see it.
Standard-library Python 3.8+ only.

    python gerber_readback.py board-fab.zip
    python gerber_readback.py board-fab.zip --expect-size 100x80 --expect-copper 4 \
        --expect-pth 212 --expect-npth 4 --markdown

Prints:
- every Gerber file with its function taken from the %TF.FileFunction attribute,
- the copper layer order (L1 top ... Ln bottom) mapped to file names: put this table in the
  fab README and the order spec, because inner-layer file extensions differ between CAD
  versions and fabs have swapped inner layers when the order was not stated,
- board size from the outline (Profile) layer, measured on line centres,
- drill counts per file and per diameter: round holes and slots, plated or not.
With --expect-* options it compares against the values from the native board and exits 1 on a
mismatch. --markdown prints the layer table as Markdown for pasting into documents.
"""
from __future__ import annotations

import argparse
import collections
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gerberlib import Excellon, Gerber, kind_of, read_bundle, utf8_stdout  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("bundle")
    parser.add_argument("--expect-size", help="board size W x H in mm, e.g. 100x80")
    parser.add_argument("--expect-copper", type=int, help="number of copper layers")
    parser.add_argument("--expect-pth", type=int, help="plated holes + plated slots")
    parser.add_argument("--expect-npth", type=int, help="non-plated holes + non-plated slots")
    parser.add_argument("--tolerance", type=float, default=0.05, help="size tolerance in mm (default 0.05)")
    parser.add_argument("--markdown", action="store_true")
    args = parser.parse_args()
    utf8_stdout()

    files = read_bundle(args.bundle)
    problems: list[str] = []
    gerbers: dict[str, Gerber] = {}
    drills: dict[str, Excellon] = {}
    for name, text in files.items():
        kind = kind_of(text)
        if kind == "gerber":
            gerbers[name] = Gerber(text)
        elif kind == "excellon":
            drills[name] = Excellon(text)

    print("Gerber files")
    for name, g in sorted(gerbers.items()):
        print(f"  {name:44s} {g.file_function or '(no FileFunction attribute)'}")

    copper = []
    for name, g in gerbers.items():
        m = re.match(r"Copper,L(\d+),(\w+)", g.file_function)
        if m:
            copper.append((int(m.group(1)), m.group(2), name))
    copper.sort()
    print("\nCopper layer order")
    if args.markdown:
        print("| Layer | Position | File |\n|---|---|---|")
    for number, side, name in copper:
        position = {"Top": "top", "Bot": "bottom", "Inr": "inner"}.get(side, side)
        print(f"| L{number} | {position} | `{name}` |" if args.markdown else f"  L{number:<3d} {position:7s} {name}")
    if not copper:
        problems.append("no copper layer carries a FileFunction attribute; enable X2 attributes on export")
    if [c[0] for c in copper] != list(range(1, len(copper) + 1)):
        problems.append(f"copper layer numbers are not continuous: {[c[0] for c in copper]}")
    if args.expect_copper is not None and len(copper) != args.expect_copper:
        problems.append(f"copper layers {len(copper)} != expected {args.expect_copper}")

    outline = [g for g in gerbers.values() if g.file_function.startswith("Profile")]
    print("\nBoard outline")
    if not outline:
        problems.append("no Profile (board outline) layer found")
    else:
        box = outline[0].outline_box_mm()
        if box is None:
            problems.append("outline layer has no drawn segments")
        else:
            width, height = box[2] - box[0], box[3] - box[1]
            print(f"  {width:.3f} x {height:.3f} mm (line centres)")
            if args.expect_size:
                ew, eh = (float(v) for v in args.expect_size.lower().split("x"))
                if abs(width - ew) > args.tolerance or abs(height - eh) > args.tolerance:
                    problems.append(f"outline {width:.3f} x {height:.3f} != expected {ew} x {eh} mm")

    totals = collections.Counter()
    print("\nDrill files")
    for name, d in sorted(drills.items()):
        print(f"  {name}  ({d.file_function or 'no FileFunction attribute'})")
        per = collections.Counter()
        for item, count in d.items.items():
            kind, dia = item[0], item[1]
            if kind == "route-arc-raw":
                problems.append(f"{name}: routed arc not interpreted: {item[2]}")
                continue
            plating = d.plating_of(dia)
            shape = "hole" if kind == "hole" else "slot"
            per[(plating, shape, dia)] += count
            totals[plating] += count
        for (plating, shape, dia), count in sorted(per.items()):
            print(f"    {plating:10s} {shape:5s} Ø{dia / 1e6:.3f} mm  x {count}")
    print(f"\nTotals: plated {totals['Plated']}, non-plated {totals['NonPlated']}"
          + (f", unknown plating {totals['Unknown']}" if totals["Unknown"] else ""))
    if args.expect_pth is not None and totals["Plated"] != args.expect_pth:
        problems.append(f"plated {totals['Plated']} != expected {args.expect_pth}")
    if args.expect_npth is not None and totals["NonPlated"] != args.expect_npth:
        problems.append(f"non-plated {totals['NonPlated']} != expected {args.expect_npth}")
    if totals["Unknown"]:
        problems.append("some drill hits have unknown plating; export PTH and NPTH as separate files")

    print("\n" + ("Readback: PASS" if not problems else "Readback: CHECK\n  - " + "\n  - ".join(problems)))
    return 0 if not problems else 1


if __name__ == "__main__":
    raise SystemExit(main())
