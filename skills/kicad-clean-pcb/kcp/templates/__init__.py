"""`kcp new`: a project skeleton that runs end to end, from wiring plan to fab zip.

    python <skill>/kcp new my_board --copper 2
    python my_board/rebuild_my_board.py

Files (my_board stands for the name):
  build_my_board.py    wiring plan -> schematic, symbol library, lib tables, project file, bom.csv
  place_my_board.py    outline, ground pour, footprints from KiCad's netlist, fit check
  route_my_board.py    one function per routing group, checked 0/45/90 paths
  rebuild_my_board.py  every step in order, stops at the first failure
  kcp_path.py          finds kcp (this skill) for the scripts
  layer_plan.json      layer roles for `kcp lint` (2L-a or 4L-S1)
The circuit is a placeholder (input, capacitor, LED and resistor) that passes ERC, DRC, parity,
lint and the Gerber readback, so a fresh project starts from a working pipeline.
"""
from __future__ import annotations

import datetime
import json
import re
from pathlib import Path
from typing import Dict, Optional, Union

HERE = Path(__file__).resolve().parent
SKILL = HERE.parents[1]
FILES = {"kcp_path.py": "kcp_path.py.tmpl", "build_{name}.py": "build.py.tmpl", "place_{name}.py": "place.py.tmpl",
         "route_{name}.py": "route.py.tmpl", "rebuild_{name}.py": "rebuild.py.tmpl"}
LAYER_PLANS = {
    2: {"description": "2L-a: routing on top (horizontal main direction), bottom a GND pour with short "
                      "crossings, so it has no main direction.",
        "layers": {"F.Cu": "horizontal", "B.Cu": "any"}},
    4: {"description": "4L-S1: top horizontal, two GND planes, bottom vertical.",
        "layers": {"F.Cu": "horizontal", "In1.Cu": "plane", "In2.Cu": "plane", "B.Cu": "vertical"}},
}


def create(folder: Union[str, Path], name: Optional[str] = None, copper: int = 2, force: bool = False) -> Dict:
    folder = Path(folder)
    name = name or folder.name
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", name):
        raise ValueError(f"project name {name!r}: use letters, digits and _ (it becomes a Python module name)")
    if copper not in LAYER_PLANS:
        raise ValueError("copper must be 2 or 4")
    targets = {target.format(name=name): source for target, source in FILES.items()}
    targets["layer_plan.json"] = None
    existing = [t for t in targets if (folder / t).exists()]
    if existing and not force:
        raise FileExistsError(f"{', '.join(existing)} already exist in {folder}; use --force to overwrite")
    from .. import __version__
    values = {"__NAME__": name, "__COPPER__": str(copper), "__KCP_SKILL__": str(SKILL),
              "__KCP_VERSION__": __version__, "__DATE__": datetime.date.today().isoformat()}
    folder.mkdir(parents=True, exist_ok=True)
    for target, source in targets.items():
        if source is None:
            text = json.dumps(LAYER_PLANS[copper], indent=2) + "\n"
        else:
            text = (HERE / source).read_text(encoding="utf-8")
            for key, value in values.items():
                text = text.replace(key, value)
        (folder / target).write_text(text, encoding="utf-8", newline="\n")
    return {"tool": "kcp new", "folder": str(folder), "name": name, "copper": copper,
            "files": sorted(targets), "kcp": str(SKILL),
            "next": [f"python {folder / f'rebuild_{name}.py'}  (the placeholder board, end to end)",
                     f"replace PARTS in build_{name}.py with the confirmed wiring plan, then PLACEMENT "
                     f"and EDGE in place_{name}.py and the groups in route_{name}.py",
                     f"the scripts need kcp {__version__} or newer: kcp_path.py finds it, or set KCP_SKILL "
                     f"to the skill folder (python {folder / 'kcp_path.py'} prints the copy in use)"]}
