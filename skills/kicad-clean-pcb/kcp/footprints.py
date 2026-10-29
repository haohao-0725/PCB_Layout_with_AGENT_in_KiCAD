"""Footprints: find them in libraries, place them on a board, and build simple custom ones.

Placing works like KiCad's "update PCB from schematic": the library geometry is copied in
footprint-local coordinates, pad and text angles get the footprint rotation added (the board
file stores them as absolute angles), and each footprint gets its reference, fields, nets and
schematic path.
"""
from __future__ import annotations

import os
import re
import sys
import uuid as uuidlib
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple, Union

from .sexpr import Node, QStr, load

PathLike = Union[str, Path]
NAMESPACE = uuidlib.UUID("6f2b8c1e-4d3a-4b5c-9e7f-0a1b2c3d4e5f")


def stable_uuid(*parts: object) -> str:
    """Deterministic UUID, so rebuilding a board gives the same file."""
    return str(uuidlib.uuid5(NAMESPACE, "/".join(str(p) for p in parts)))


def fmt(value: float) -> str:
    """Number as KiCad writes it: no trailing zeros, at most 6 decimals."""
    text = f"{value:.6f}".rstrip("0").rstrip(".")
    return "0" if text in ("-0", "") else text


def norm_deg(angle: float) -> float:
    angle = angle % 360.0
    return 0.0 if abs(angle) < 1e-9 or abs(angle - 360.0) < 1e-9 else angle


# ---------------------------------------------------------------- library lookup

def stock_footprint_dirs() -> List[Path]:
    dirs = []
    env = [v for k, v in os.environ.items() if re.fullmatch(r"KICAD\d*_FOOTPRINT_DIR", k)]
    dirs += [Path(v) for v in env]
    if sys.platform == "win32":
        root = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "KiCad"
        dirs += sorted(root.glob("*/share/kicad/footprints"), reverse=True)
    elif sys.platform == "darwin":
        dirs.append(Path("/Applications/KiCad/KiCad.app/Contents/SharedSupport/footprints"))
    else:
        dirs += [Path("/usr/share/kicad/footprints"), Path("/usr/local/share/kicad/footprints")]
    return [d for d in dirs if d.is_dir()]


def project_libraries(project_dir: PathLike) -> Dict[str, Path]:
    """Nickname -> .pretty folder from a project's fp-lib-table (${KIPRJMOD} expanded)."""
    table = Path(project_dir) / "fp-lib-table"
    if not table.is_file():
        return {}
    out = {}
    for m in re.finditer(r'\(lib\s+\(name\s+"?([^")\s]+)"?\).*?\(uri\s+"([^"]+)"\)', table.read_text(encoding="utf-8"), re.S):
        uri = m.group(2).replace("${KIPRJMOD}", str(Path(project_dir).resolve()))
        out[m.group(1)] = Path(uri)
    return out


class FootprintLibrary:
    """Resolves 'Nickname:Name' to a .kicad_mod file: project libraries first, then KiCad's own."""

    def __init__(self, project_dir: Optional[PathLike] = None, extra: Optional[Dict[str, PathLike]] = None):
        self.project = project_libraries(project_dir) if project_dir else {}
        self.extra = {k: Path(v) for k, v in (extra or {}).items()}
        self.stock = stock_footprint_dirs()
        self._cache: Dict[str, Node] = {}

    def path(self, lib_id: str) -> Path:
        nickname, _, name = lib_id.partition(":")
        for table in (self.extra, self.project):
            if nickname in table:
                candidate = table[nickname] / f"{name}.kicad_mod"
                if candidate.is_file():
                    return candidate
        for root in self.stock:
            candidate = root / f"{nickname}.pretty" / f"{name}.kicad_mod"
            if candidate.is_file():
                return candidate
        raise FileNotFoundError(f"footprint {lib_id} not found (project libraries: {sorted(self.project)}; "
                                f"KiCad libraries: {[str(s) for s in self.stock]})")

    def load(self, lib_id: str) -> Node:
        if lib_id not in self._cache:
            self._cache[lib_id] = load(self.path(lib_id))
        return self._cache[lib_id]


# ---------------------------------------------------------------- placing

def _set_child(node: Node, name: str, values: Sequence[str], after: Sequence[str] = ()) -> None:
    child = node.get(name)
    new = Node([name, *values])
    if child is not None:
        node[node.index(child)] = new
        return
    index = 1
    for key in after:
        found = node.get(key)
        if found is not None:
            index = max(index, node.index(found) + 1)
    node.insert(index, new)


def _rotate_at(item: Node, rotation: float, always: bool = False) -> None:
    at = item.get("at")
    if at is None:
        return
    values = [a for a in at[1:]]
    angle = float(values[2]) if len(values) > 2 else 0.0
    new_angle = norm_deg(angle + rotation)
    if new_angle or always or len(values) > 2:
        at[1:] = [values[0], values[1], fmt(new_angle)]


def _property(name: str, value: str, layer: str, at=(0.0, 0.0), rotation: float = 0.0, hidden: bool = True,
              seed: str = "", size: float = 1.27, thickness: Optional[float] = None) -> Node:
    font = Node(["font", Node(["size", fmt(size), fmt(size)])])
    if thickness:
        font.append(Node(["thickness", fmt(thickness)]))
    node = Node(["property", QStr(name), QStr(value),
                 Node(["at", fmt(at[0]), fmt(at[1]), fmt(norm_deg(rotation))]),
                 Node(["layer", QStr(layer)])])
    if hidden:
        node.append(Node(["hide", "yes"]))
    node += [Node(["uuid", QStr(stable_uuid(seed, "property", name))]),
             Node(["effects", font])]
    return node


def place_footprint(lib_fp: Node, lib_id: str, ref: str, at: Tuple[float, float], rotation: float = 0.0,
                    nets: Optional[Dict[str, str]] = None, fields: Optional[Dict[str, str]] = None,
                    value: Optional[str] = None, path: Optional[str] = None, board_only: bool = False,
                    seed: Optional[str] = None) -> Node:
    """A board footprint from a library footprint.

    nets: pad number -> net name (pads not listed get no net). fields: extra properties from the
    symbol (Datasheet, Description, Silk ...), written hidden on the fab layer.
    """
    import copy
    seed = seed or ref
    fp = copy.deepcopy(lib_fp)
    fp[1] = QStr(lib_id)
    for drop in ("version", "generator", "generator_version"):
        child = fp.get(drop)
        if child is not None:
            fp.remove(child)
    layer = fp.value("layer", "F.Cu") or "F.Cu"
    _set_child(fp, "layer", [QStr(layer)])
    _set_child(fp, "uuid", [QStr(stable_uuid(seed, "footprint"))], after=("layer",))
    _set_child(fp, "at", [fmt(at[0]), fmt(at[1])] + ([fmt(norm_deg(rotation))] if norm_deg(rotation) else []),
               after=("uuid",))
    fab = "F.Fab" if layer.startswith("F") else "B.Fab"
    existing = {str(p[1]): p for p in fp.all("property")}
    if "Reference" in existing:
        existing["Reference"][2] = QStr(ref)
    if "Value" in existing and value is not None:
        existing["Value"][2] = QStr(value)
    last_prop = fp.all("property")[-1] if fp.all("property") else fp.get("at")
    insert_at = fp.index(last_prop) + 1
    for name, text in (fields or {}).items():
        if name in ("Reference", "Value", "Footprint"):
            continue
        if name in existing:
            existing[name][2] = QStr(text)
            continue
        fp.insert(insert_at, _property(name, text, fab, seed=seed))
        insert_at += 1
    for prop in fp.all("property"):
        _rotate_at(prop, rotation, always=True)
        if prop.get("uuid") is None:
            prop.insert(prop.index(prop.get("layer")) + 1 if prop.get("layer") is not None else 3,
                        Node(["uuid", QStr(stable_uuid(seed, "property", str(prop[1])))]))
    if path:
        _set_child(fp, "path", [QStr(path)], after=("property",))
    if board_only:
        attr = fp.get("attr")
        if attr is None:
            fp.insert(fp.index(fp.get("at")) + 1, Node(["attr", "board_only"]))
        elif "board_only" not in attr:
            attr.append("board_only")
    counter = 0
    for child in fp.nodes():
        name = child.name
        if name.startswith("fp_") or name == "pad" or name == "zone":
            counter += 1
            if name in ("fp_text", "fp_text_box"):
                _rotate_at(child, rotation, always=True)
            if name == "pad":
                _rotate_at(child, rotation, always=True)
                number = str(child[1]) if len(child) > 1 else ""
                if nets and number in nets and nets[number]:
                    net = Node(["net", QStr(nets[number])])
                    old = child.get("net")
                    if old is not None:
                        child[child.index(old)] = net
                    else:
                        child.append(net)
            if child.get("uuid") is None:
                child.append(Node(["uuid", QStr(stable_uuid(seed, name, counter))]))
    return fp


# ---------------------------------------------------------------- simple custom footprints

def tht_footprint(name: str, pads: Iterable[Dict], courtyard: Tuple[float, float, float, float],
                  fab: Optional[Iterable[Tuple[float, float, float, float]]] = None,
                  silk: Optional[Iterable[Tuple[float, float, float, float]]] = None,
                  descr: str = "", ref_at: Tuple[float, float] = (0.0, -2.5),
                  value_at: Tuple[float, float] = (0.0, 2.5), silk_text: Optional[Tuple[float, ...]] = None,
                  attr: str = "through_hole") -> Node:
    """A library footprint (.kicad_mod tree) for through-hole parts.

    pads: dicts with number, x, y, size (or w/h), drill, shape (circle, rect, oval, roundrect).
    courtyard, fab and silk rectangles: (x0, y0, x1, y1) in footprint coordinates.
    silk_text: (x, y[, angle]) of a ${Silk} text, for the functional name.
    """
    fp = Node(["footprint", QStr(name), Node(["version", "20260206"]), Node(["generator", QStr("kcp")]),
               Node(["layer", QStr("F.Cu")])])
    if descr:
        fp.append(Node(["descr", QStr(descr)]))
    fp.append(_property("Reference", "REF**", "F.SilkS", ref_at, hidden=False, seed=name, size=1.0, thickness=0.15))
    fp.append(_property("Value", name, "F.Fab", value_at, hidden=False, seed=name, size=1.0, thickness=0.15))
    for prop in fp.all("property"):
        prop.remove(prop.get("uuid"))
    fp.append(Node(["attr", *attr.split()]))

    def rect(box, layer, width):
        return Node(["fp_rect", Node(["start", fmt(box[0]), fmt(box[1])]), Node(["end", fmt(box[2]), fmt(box[3])]),
                     Node(["stroke", Node(["width", fmt(width)]), Node(["type", "solid"])]),
                     Node(["fill", "no"]), Node(["layer", QStr(layer)])])

    for box in silk or ():
        fp.append(rect(box, "F.SilkS", 0.12))
    fp.append(rect(courtyard, "F.CrtYd", 0.05))
    for box in fab or ():
        fp.append(rect(box, "F.Fab", 0.1))
    if silk_text:
        angle = silk_text[2] if len(silk_text) > 2 else 0.0
        fp.append(Node(["fp_text", "user", QStr("${Silk}"),
                        Node(["at", fmt(silk_text[0]), fmt(silk_text[1]), fmt(angle)]),
                        Node(["layer", QStr("F.SilkS")]),
                        Node(["effects", Node(["font", Node(["size", "1", "1"]), Node(["thickness", "0.15"])])])]))
    for pad in pads:
        w = pad.get("w", pad.get("size"))
        h = pad.get("h", pad.get("size"))
        shape = pad.get("shape", "circle")
        node = Node(["pad", QStr(str(pad["number"])), pad.get("type", "thru_hole"), shape,
                     Node(["at", fmt(pad["x"]), fmt(pad["y"])]), Node(["size", fmt(w), fmt(h)]),
                     Node(["drill", fmt(pad["drill"])]),
                     Node(["layers", QStr("*.Cu"), QStr("*.Mask")])])
        if shape == "roundrect":
            node.append(Node(["roundrect_rratio", "0.25"]))
        fp.append(node)
    fp.append(Node(["embedded_fonts", "no"]))
    return fp
