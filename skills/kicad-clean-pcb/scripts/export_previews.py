"""Board previews for review: routing / assembly / inner-plane PDFs (+ PNG) and a 1:1 fit-check
PDF on A4 (A3 when A4 is too small). Run it with the Python that ships with KiCad.

    "<KiCad>/bin/python" export_previews.py board.kicad_pcb --out previews

- kicad-cli is taken from the same bin folder (or PATH). PNG output needs Poppler's pdftoppm on
  PATH; without it only PDFs are written.
- `kicad-cli pcb export pdf` crops anything at negative coordinates (for example a module outline
  drawn above the board edge), so a shifted copy of the board is exported. The original board
  file is never modified; coordinates printed on the drawing stay the original ones.
- Preview pages are sized to fit every object. The fit-check PDF is portrait A4 (or A3): print it
  at "Actual size / 100 %", measure the board outline on paper first, then lay the real parts on
  it.
- Tested with KiCad 10.0.x. Older kicad-cli versions may lack some options (e.g. --scale);
  check `kicad-cli pcb export pdf --help`.
"""
from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

MARGIN = 8.0          # mm from the outermost object to the page edge
PAPERS = (("A4", 210.0, 297.0), ("A3", 297.0, 420.0))


def item_boxes(board, pcbnew):
    """(x0, y0, x1, y1) in mm for every object. Empty boxes are skipped: geometry operations on an
    empty BOX2I raise a KiCad assert dialog on the desktop and block the script."""
    items = list(board.GetDrawings()) + list(board.GetFootprints()) + list(board.GetTracks())
    for item in items:
        box = item.GetBoundingBox()
        if box.GetWidth() <= 0 and box.GetHeight() <= 0:
            continue
        yield (pcbnew.ToMM(box.GetLeft()), pcbnew.ToMM(box.GetTop()),
               pcbnew.ToMM(box.GetRight()), pcbnew.ToMM(box.GetBottom()))


def set_paper(text: str, paper: str) -> str:
    """The page size (PAGE_INFO) cannot be set from Python; edit the saved file text instead."""
    return re.sub(r'\(paper "[^"]*"[^)]*\)', paper, text, count=1)


def run(cmd: list[str]) -> None:
    result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if result.returncode:
        raise SystemExit(f"failed: {' '.join(cmd[:4])} ...\n{result.stderr or result.stdout}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("board", type=Path)
    parser.add_argument("--out", type=Path, default=Path("previews"))
    parser.add_argument("--dpi", type=int, default=150)
    parser.add_argument("--extra-layers", default="User.Drawings",
                        help="reference layers drawn on every preview (e.g. module outlines), comma separated")
    parser.add_argument("--fit-layers", default="F.Cu,F.SilkS,F.Fab,Edge.Cuts",
                        help="layers on the 1:1 fit-check page, comma separated")
    args = parser.parse_args()

    import pcbnew  # KiCad's Python only

    cli = Path(sys.executable).resolve().parent / ("kicad-cli.exe" if sys.platform == "win32" else "kicad-cli")
    if not cli.is_file():
        cli = Path(shutil.which("kicad-cli") or "")
    if not cli.is_file():
        raise SystemExit("kicad-cli not found; run this script with the Python that ships with KiCad")
    pdftoppm = shutil.which("pdftoppm")
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)

    board = pcbnew.LoadBoard(str(args.board.resolve()))
    boxes = list(item_boxes(board, pcbnew))
    if not boxes:
        raise SystemExit("the board has no objects")
    x0, y0 = min(b[0] for b in boxes), min(b[1] for b in boxes)
    x1, y1 = max(b[2] for b in boxes), max(b[3] for b in boxes)
    dx, dy = MARGIN - x0, MARGIN - y0
    width, height = x1 - x0 + 2 * MARGIN, y1 - y0 + 2 * MARGIN
    offset = pcbnew.VECTOR2I(pcbnew.FromMM(dx), pcbnew.FromMM(dy))
    for item in list(board.GetDrawings()) + list(board.GetFootprints()) + list(board.GetTracks()) + list(board.Zones()):
        item.Move(offset)

    copper = [board.GetLayerName(layer) for layer in board.GetEnabledLayers().CuStack()]
    inner = [name for name in copper if name.startswith("In")]
    zoned = {board.GetLayerName(zone.GetLayer()) for zone in board.Zones() if not zone.GetIsRuleArea()}
    tracked = {board.GetLayerName(t.GetLayer()) for t in board.GetTracks() if t.GetClass() == "PCB_TRACK"}
    extra = [name for name in args.extra_layers.split(",") if name]
    presets = {
        "routing": ([name for name in copper if name in ("F.Cu", "B.Cu") or name in tracked]
                    + ["F.SilkS", "Edge.Cuts"] + extra, []),
        "assembly": (["F.SilkS", "F.Fab", "Edge.Cuts"] + extra, ["--black-and-white", "--sketch-pads-on-fab-layers"]),
    }
    for name in inner:
        if name in zoned:
            presets[f"plane_{name.replace('.', '')}"] = ([name, "Edge.Cuts"], [])
    stem = args.board.stem
    with tempfile.TemporaryDirectory(prefix="kicad_preview_") as tmp:
        saved = Path(tmp) / "shifted.kicad_pcb"
        pcbnew.SaveBoard(str(saved), board, True)   # True: do not rewrite the project file
        text = saved.read_text(encoding="utf-8")
        preview_board = Path(tmp) / "preview.kicad_pcb"
        preview_board.write_text(set_paper(text, f'(paper "User" {width:.2f} {height:.2f})'), encoding="utf-8")
        for name, (layers, options) in presets.items():
            pdf = out / f"{stem}_{name}.pdf"
            run([str(cli), "pcb", "export", "pdf", "--mode-single", "--scale", "1", "--layers", ",".join(layers),
                 *options, "--output", str(pdf), str(preview_board)])
            if pdftoppm:
                run([pdftoppm, "-r", str(args.dpi), "-png", "-singlefile", str(pdf), str(out / pdf.stem)])
            print(pdf.name + (" + .png" if pdftoppm else ""))
        paper = next(((n, w, h) for n, w, h in PAPERS if width <= w and height <= h), None)
        if paper is None:
            print(f"board plus reference outlines is {width:.0f} x {height:.0f} mm; too large for A3, "
                  "fit-check page skipped (print the routing preview in tiles instead)")
        else:
            fit_board = Path(tmp) / "fit.kicad_pcb"
            fit_board.write_text(set_paper(text, f'(paper "{paper[0]}" portrait)'), encoding="utf-8")
            pdf = out / f"{stem}_fit_check_1to1_{paper[0]}.pdf"
            layers = [name for name in args.fit_layers.split(",") if name] + extra
            run([str(cli), "pcb", "export", "pdf", "--mode-single", "--scale", "1", "--black-and-white",
                 "--sketch-pads-on-fab-layers", "--layers", ",".join(layers), "--output", str(pdf), str(fit_board)])
            print(f"{pdf.name} ({paper[0]} portrait; print at Actual size / 100 %, measure the outline first)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
