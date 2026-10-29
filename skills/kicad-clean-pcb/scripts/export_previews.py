"""Board previews for review: routing / assembly / inner-plane PDFs (+ PNG) and a 1:1 fit-check
PDF on A4 (A3 when A4 is too small). Runs with any Python 3.9+ (no pcbnew); needs kicad-cli.

    python export_previews.py board.kicad_pcb --out previews

Same options as before; the work is done by kcp.previews (also `python <skill>/kcp previews ...`).
- kicad-cli is found from $KICAD_CLI, PATH or the usual install folders. PNG output needs Poppler's
  pdftoppm on PATH; without it only PDFs are written.
- `kicad-cli pcb export pdf` crops anything at negative coordinates, so a shifted copy of the board
  is exported. The original board file is never modified.
- The fit-check PDF is portrait A4 (or A3): print it at "Actual size / 100 %", measure the board
  outline on paper first, then lay the real parts on it.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


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

    from kcp.previews import export
    aliases = {"User.Drawings": "Dwgs.User", "User.Comments": "Cmts.User", "User.Eco1": "Eco1.User",
               "User.Eco2": "Eco2.User"}
    extra = [aliases.get(l, l) for l in args.extra_layers.split(",") if l]
    result = export(args.board, args.out, args.dpi, extra, [l for l in args.fit_layers.split(",") if l])
    for name in result["files"]:
        print(name)
    print(result["fit_check_note"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
