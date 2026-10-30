"""Fab output: Gerbers and drill files, a zip with README.txt and SHA256SUMS.txt, and a readback of
the zip against the board (size, copper layer count, PTH and NPTH holes), like a fab would read it.

    python <skill>/kcp fab board.kicad_pcb --out-dir fab [--refill] [--readme notes.txt]

- Gerbers: every copper layer, both masks, both silkscreens and Edge.Cuts (no paste: bare boards).
- Drill: Excellon, mm, absolute origin, PTH and NPTH in separate files.
- README.txt: the text you pass (board spec for the fab, e.g. thickness, copper weight, finish),
  then the board size and copper count, then the copper layer order read back from the files.
- refill=True refills the zones and saves the board first (KiCad writes the board file), so the
  Gerbers carry filled pours. It refuses while KiCad has the project open.
The board file is otherwise only read. Ordering stays with the user: nothing is uploaded.
"""
from __future__ import annotations

import hashlib
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Union

from . import kicad_cli
from .backends.file import BoardLockedError, load_board, lock_files
from .model import Board

PathLike = Union[str, Path]
NON_COPPER = ["F.Mask", "B.Mask", "F.SilkS", "B.SilkS", "Edge.Cuts"]
READBACK = Path(__file__).resolve().parents[1] / "scripts" / "gerber_readback.py"


def gerber_layers(board: Board) -> List[str]:
    return list(board.copper_layers) + NON_COPPER


def expected(board: Board) -> Dict:
    """What the fab files must show: outline size (mm), copper layers, plated and non-plated holes."""
    box = board.outline_bbox()
    if box is None:
        raise ValueError("the board has no Edge.Cuts outline")
    pth = sum(1 for p in board.pads if p.kind == "thru_hole") + len(board.vias)
    npth = sum(1 for p in board.pads if p.kind == "np_thru_hole")
    return {"size": f"{box[2] - box[0]:g}x{box[3] - box[1]:g}", "copper": len(board.copper_layers),
            "pth": pth, "npth": npth}


def readback(bundle: PathLike, expect: Optional[Dict] = None) -> Dict:
    """Run scripts/gerber_readback.py on a zip or folder; ok=False if anything differs from expect."""
    if not READBACK.is_file():
        return {"ok": None, "skipped": f"{READBACK} not found (the skill's scripts folder is missing)"}
    argv = [sys.executable, str(READBACK), str(bundle), "--markdown"]
    for key, flag in (("size", "--expect-size"), ("copper", "--expect-copper"), ("pth", "--expect-pth"),
                      ("npth", "--expect-npth")):
        if expect and expect.get(key) is not None:
            argv += [flag, str(expect[key])]
    result = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", errors="replace")
    return {"ok": result.returncode == 0, "expected": expect, "markdown": result.stdout,
            **({"stderr": result.stderr.strip()[-2000:]} if result.stderr.strip() else {})}


def export(board_path: PathLike, out_dir: PathLike, zip_name: Optional[str] = None,
           layers: Optional[Sequence[str]] = None, readme: str = "", refill: bool = False, check: bool = True,
           force: bool = False) -> Dict:
    """Write <out_dir>/gerber/ (cleared first) and <out_dir>/<zip_name>, then read the zip back."""
    board_path = Path(board_path)
    if refill:
        locks = lock_files(board_path)
        if locks and not force:
            raise BoardLockedError(f"KiCad has the project open ({', '.join(p.name for p in locks)}); close it first")
        kicad_cli.refill_zones(board_path)
    board = load_board(board_path)
    layers = list(layers) if layers else gerber_layers(board)
    out = Path(out_dir)
    gerber_dir = out / "gerber"
    if gerber_dir.exists():
        shutil.rmtree(gerber_dir)
    gerber_dir.mkdir(parents=True)
    kicad_cli.export_gerbers(board_path, gerber_dir, layers)
    kicad_cli.export_drill(board_path, gerber_dir)
    files = sorted(p for p in gerber_dir.iterdir() if p.is_file() and p.suffix.lower() != ".gbrjob")
    expect = expected(board)
    order = readback(gerber_dir)
    order_lines = [line for line in order.get("markdown", "").splitlines() if line.startswith("| L")]
    zip_path = out / (zip_name or f"{board_path.stem}_fab.zip")
    head = readme.rstrip("\n") + "\n" if readme.strip() else (
        f"{board_path.stem} - bare boards only, no assembly\n"
        f"Size {expect['size'].replace('x', ' x ')} mm, {expect['copper']} copper layers\n"
        "PTH and NPTH drill files are separate.\n")
    sums = []
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
        for f in files:
            archive.write(f, f.name)
            sums.append(f"{hashlib.sha256(f.read_bytes()).hexdigest()}  {f.name}")
        archive.writestr("README.txt", head + "\nLAYER_ORDER\n" + "\n".join(order_lines) + "\n")
        archive.writestr("SHA256SUMS.txt", "\n".join(sums) + "\n")
    result = {"tool": "kcp fab", "board": str(board_path), "zip": str(zip_path), "gerber_dir": str(gerber_dir),
              "layers": layers, "files": [f.name for f in files], "refilled": refill, "expected": expect}
    if check:
        back = readback(zip_path, expect)
        result["readback"] = back
        result["ok"] = back["ok"] is not False
    else:
        result["ok"] = True
    return result
