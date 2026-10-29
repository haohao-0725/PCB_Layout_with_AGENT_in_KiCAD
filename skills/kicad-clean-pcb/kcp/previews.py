"""Board previews for review: routing / assembly / inner-plane PDFs (+ PNG) and a 1:1 fit-check
PDF on A4 (A3 when A4 is too small). File backend + kicad-cli; no pcbnew.

- `kicad-cli pcb export pdf` crops anything at negative coordinates, so a shifted copy of the
  board is exported. The original board file is never modified.
- PNG output needs Poppler's pdftoppm on PATH; without it only PDFs are written.
- The fit-check PDF is portrait A4 (or A3): print it at "Actual size / 100 %", measure the board
  outline on paper first, then lay the real parts on it.
"""
from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Union

from . import kicad_cli
from . import geometry as g
from .board import translate_tree
from .model import board_from_tree
from .sexpr import Node, QStr, dumps, load

MARGIN = 8.0
PAPERS = (("A4", 210.0, 297.0), ("A3", 297.0, 420.0))
PathLike = Union[str, Path]


def content_bbox(tree: Node) -> Optional[g.BBox]:
    board = board_from_tree(tree)
    boxes = []
    for fp in board.footprints:
        boxes.append(fp.courtyard_bbox())
        boxes += [p.shape().bbox for p in fp.pads]
        boxes += [gr.bbox() for gr in fp.graphics]
    boxes += [gr.bbox() for gr in board.graphics]
    boxes += [t.shape().bbox for t in board.tracks]
    boxes += [g.bbox_of(z.outline) for z in board.zones]
    return g.bbox_union(boxes)


def _set_paper(tree: Node, paper: str, width: Optional[float] = None, height: Optional[float] = None,
               portrait: bool = False) -> None:
    node = Node(["paper", QStr(paper)])
    if width and height:
        node += [f"{width:.2f}", f"{height:.2f}"]
    if portrait:
        node.append("portrait")
    old = tree.get("paper")
    if old is not None:
        tree[tree.index(old)] = node
    else:
        tree.insert(5, node)


def export(board_path: PathLike, out_dir: PathLike, dpi: int = 150, extra_layers: Sequence[str] = ("Dwgs.User",),
           fit_layers: Sequence[str] = ("F.Cu", "F.SilkS", "F.Fab", "Edge.Cuts"), png: bool = True) -> Dict:
    board_path = Path(board_path)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    tree = load(board_path)
    box = content_bbox(tree)
    if box is None:
        raise ValueError("the board has no objects")
    translate_tree(tree, MARGIN - box[0], MARGIN - box[1])
    width, height = box[2] - box[0] + 2 * MARGIN, box[3] - box[1] + 2 * MARGIN
    board = board_from_tree(tree)
    copper = board.copper_layers
    tracked = {t.layer for t in board.tracks}
    zoned = {layer for z in board.zones if not z.rule_area for layer in z.layers}
    extra = [l for l in extra_layers if l]
    presets: Dict[str, tuple] = {
        "routing": ([l for l in copper if l in ("F.Cu", "B.Cu") or l in tracked] + ["F.SilkS", "Edge.Cuts"] + extra, []),
        "assembly": (["F.SilkS", "F.Fab", "Edge.Cuts"] + extra, ["--black-and-white", "--sketch-pads-on-fab-layers"]),
    }
    for layer in copper[1:-1]:
        if layer in zoned or layer in tracked:
            presets[f"inner_{layer.replace('.', '')}"] = ([layer, "Edge.Cuts"], [])
    pdftoppm = shutil.which("pdftoppm") if png else None
    written: List[str] = []
    stem = board_path.stem
    with tempfile.TemporaryDirectory(prefix="kcp_preview_") as tmp:
        tmp = Path(tmp)
        for side in (".kicad_pro", ".kicad_dru"):
            if board_path.with_suffix(side).is_file():
                shutil.copy2(board_path.with_suffix(side), tmp / f"preview{side}")
        preview = tmp / "preview.kicad_pcb"
        _set_paper(tree, "User", width, height)
        preview.write_text(dumps(tree), encoding="utf-8")
        for name, (layers, options) in presets.items():
            pdf = out / f"{stem}_{name}.pdf"
            result = kicad_cli.run(["pcb", "export", "pdf", "--mode-single", "--scale", "1", "--layers",
                                    ",".join(layers), *options, "--output", str(pdf), str(preview)])
            if not pdf.is_file():
                raise kicad_cli.KiCadCliError(f"pdf export failed: {(result.stderr or result.stdout).strip()}")
            written.append(pdf.name)
            if pdftoppm:
                subprocess.run([pdftoppm, "-r", str(dpi), "-png", "-singlefile", str(pdf), str(out / pdf.stem)],
                               check=True, capture_output=True)
                written.append(pdf.stem + ".png")
        paper = next(((n, w, h) for n, w, h in PAPERS if width <= w and height <= h), None)
        fit = None
        if paper:
            _set_paper(tree, paper[0], portrait=True)
            fit_board = tmp / "fit.kicad_pcb"
            fit_board.write_text(dumps(tree), encoding="utf-8")
            fit = out / f"{stem}_fit_check_1to1_{paper[0]}.pdf"
            kicad_cli.run(["pcb", "export", "pdf", "--mode-single", "--scale", "1", "--black-and-white",
                           "--sketch-pads-on-fab-layers", "--layers", ",".join(list(fit_layers) + extra),
                           "--output", str(fit), str(fit_board)])
            written.append(fit.name)
    return {"tool": "kcp previews", "board": str(board_path), "out": str(out), "files": written,
            "page_mm": [round(width, 1), round(height, 1)], "fit_check": fit.name if fit else None,
            "fit_check_note": ("print at Actual size / 100 %, measure the outline first" if fit
                               else f"{width:.0f} x {height:.0f} mm does not fit A3; print the routing preview in tiles")}
