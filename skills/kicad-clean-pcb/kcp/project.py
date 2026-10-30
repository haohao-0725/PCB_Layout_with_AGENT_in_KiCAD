"""The KiCad project file (.kicad_pro): design rules, netclasses and the root sheet.

    info = write_schematic(design, folder / "board.kicad_sch")
    write_project(folder / "board.kicad_pro", info["root_uuid"],
                  netclasses=[("Power", 1.0, 0.3, ["+12V", "VIN*"])], rules={"min_copper_edge_clearance": 0.5})

Netclasses: (name, track width, clearance, net patterns) tuples, or dicts with those keys plus
optional via_diameter / via_drill. KiCad matches the patterns against net names ("*" wildcards).
DEFAULT_RULES are minimums a typical 2-4 layer prototype fab (e.g. JLCPCB, PCBWay standard) can
make; pass rules= to override single values. Rules are checked by DRC, so never loosen them to make
a check pass.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple, Union

PathLike = Union[str, Path]
NetClassSpec = Union[Tuple[str, float, float, Sequence[str]], Mapping]

DEFAULT_RULES: Dict[str, float] = {
    "min_clearance": 0.2, "min_track_width": 0.2, "min_via_diameter": 0.6, "min_via_annular_width": 0.13,
    "min_through_hole_diameter": 0.3, "min_hole_to_hole": 0.25, "min_hole_clearance": 0.25,
    "min_copper_edge_clearance": 0.5, "min_silk_clearance": 0.0, "min_text_height": 0.8,
    "min_text_thickness": 0.15, "solder_mask_to_copper_clearance": 0.0,
}
SILK_DEFAULTS = {"silk_line_width": 0.15, "silk_text_size_h": 1.0, "silk_text_size_v": 1.0,
                 "silk_text_thickness": 0.15}
DEFAULT_CLASS = {"name": "Default", "clearance": 0.2, "track_width": 0.25, "via_diameter": 0.8, "via_drill": 0.4,
                 "priority": 2147483647}


def _spec(item: NetClassSpec) -> Dict:
    if isinstance(item, Mapping):
        return {"name": item["name"], "track_width": item["track_width"], "clearance": item["clearance"],
                "patterns": list(item.get("patterns", [])), "via_diameter": item.get("via_diameter", 1.0),
                "via_drill": item.get("via_drill", 0.5)}
    name, width, clearance, patterns = item
    return {"name": name, "track_width": width, "clearance": clearance, "patterns": list(patterns),
            "via_diameter": 1.0, "via_drill": 0.5}


def project_json(name: str, root_uuid: str, netclasses: Iterable[NetClassSpec] = (),
                 rules: Optional[Mapping[str, float]] = None, default_class: Optional[Mapping] = None) -> Dict:
    """The .kicad_pro content. name: the project name (file stem); root_uuid: from write_schematic."""
    classes: List[Dict] = [dict(DEFAULT_CLASS, **(default_class or {}))]
    patterns: List[Dict] = []
    for i, item in enumerate(netclasses):
        spec = _spec(item)
        classes.append({"name": spec["name"], "clearance": spec["clearance"], "track_width": spec["track_width"],
                        "via_diameter": spec["via_diameter"], "via_drill": spec["via_drill"], "priority": i})
        patterns += [{"netclass": spec["name"], "pattern": p} for p in spec["patterns"]]
    return {
        "board": {"design_settings": {"rules": dict(DEFAULT_RULES, **(rules or {})), "defaults": dict(SILK_DEFAULTS)}},
        "meta": {"filename": f"{name}.kicad_pro", "version": 3},
        "net_settings": {"classes": classes, "meta": {"version": 4}, "netclass_assignments": None,
                         "netclass_patterns": patterns},
        "sheets": [[root_uuid, "Root"]],
        "text_variables": {},
    }


def write_project(path: PathLike, root_uuid: str, netclasses: Iterable[NetClassSpec] = (),
                  rules: Optional[Mapping[str, float]] = None, default_class: Optional[Mapping] = None) -> Path:
    """Write the .kicad_pro next to the schematic and board (same stem)."""
    path = Path(path)
    data = project_json(path.stem, root_uuid, netclasses, rules, default_class)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8", newline="\n")
    return path
