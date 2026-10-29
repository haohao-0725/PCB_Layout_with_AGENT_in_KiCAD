"""Board model built from a parsed .kicad_pcb file: footprints, pads, tracks, vias, zones, outline.

All coordinates are absolute board millimetres (y down). Footprint children are converted from
footprint-local coordinates; pad and text angles are stored in the file as absolute angles.

Reads KiCad 10 files (nets by name) and the older format with numbered nets.
"""
from __future__ import annotations

import fnmatch
import json
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from . import geometry as g
from .sexpr import Node, QStr

Point = Tuple[float, float]

COPPER_TYPES = ("signal", "power", "mixed", "jumper")


def copper_sort_key(name: str) -> Tuple[int, int]:
    if name == "F.Cu":
        return 0, 0
    if name == "B.Cu":
        return 2, 0
    m = re.match(r"In(\d+)\.Cu$", name)
    return 1, int(m.group(1)) if m else 999


def _xy(node: Optional[Node], name: str) -> Optional[Point]:
    if node is None:
        return None
    values = node.numbers(name)
    return (values[0], values[1]) if len(values) >= 2 else None


def _pts(node: Optional[Node]) -> List[Point]:
    if node is None:
        return []
    pts = node.get("pts")
    if pts is None:
        return []
    out = []
    for item in pts.nodes():
        if item.name == "xy":
            out.append((float(item[1]), float(item[2])))
        elif item.name == "arc":        # arcs inside polygons: keep start, mid, end
            for key in ("start", "mid", "end"):
                p = _xy(item, key)
                if p:
                    out.append(p)
    return out


def _stroke_width(node: Node) -> float:
    stroke = node.get("stroke")
    if stroke is not None and stroke.number("width") is not None:
        return stroke.number("width")
    return node.number("width", 0.0)


def _filled(node: Node) -> bool:
    return node.value("fill") in ("yes", "solid")


def _hidden(node: Node) -> bool:
    if node.flag("hide"):
        return True
    effects = node.get("effects")
    return effects is not None and effects.flag("hide")


# ---------------------------------------------------------------- items

@dataclass
class Graphic:
    kind: str                      # line, rect, circle, arc, poly, curve
    layer: str
    width: float
    filled: bool
    pts: List[Point]               # line: a, b; rect: 4 corners; arc: start, mid, end; poly: vertices
    center: Optional[Point] = None
    radius: float = 0.0
    owner: str = ""                # footprint reference, or "" for board items

    def outline(self) -> List[Point]:
        """Points along the drawn line (closed shapes repeat their first point)."""
        if self.kind == "arc" and len(self.pts) == 3:
            return g.arc_points(*self.pts)
        if self.kind == "circle":
            pts = g.circle_points(self.center, self.radius)
            return pts + pts[:1]
        if self.kind in ("rect", "poly") and self.pts:
            return self.pts + self.pts[:1]
        return list(self.pts)

    def shape(self) -> g.Shape:
        if self.kind == "circle":
            if self.filled:
                return g.Shape("point", [self.center], self.radius + self.width / 2)
            return g.Shape("path", self.outline(), self.width / 2)
        if self.filled and self.kind in ("rect", "poly") and len(self.pts) >= 3:
            return g.Shape("poly", self.pts, self.width / 2)
        pts = self.outline()
        if len(pts) == 1:
            return g.Shape("point", pts, self.width / 2)
        return g.Shape("path", pts, self.width / 2)

    def bbox(self) -> Optional[g.BBox]:
        return g.bbox_of(self.outline())


@dataclass
class Text:
    text: str
    layer: str
    at: Point
    angle: float
    size: Tuple[float, float]       # height, width (font size)
    thickness: float
    justify: List[str]
    hidden: bool
    kind: str                       # reference, value, property, user, board
    owner: str = ""

    # Stroke-font advance per character as a fraction of the font width. KiCad 10's rendered
    # boxes measure 0.81-1.05 x chars x width (median 0.95) including the stroke; 0.9 + stroke fits.
    CHAR_WIDTH = 0.9

    def box(self) -> List[Point]:
        """Approximate corners of the rendered text (stroke font, no exact glyph metrics)."""
        lines = self.text.split("\n") or [""]
        h, w = self.size
        width = max(len(line) for line in lines) * w * self.CHAR_WIDTH
        height = h * (1 + 1.6 * (len(lines) - 1))
        x0, x1 = -width / 2, width / 2
        y0, y1 = -height / 2, height / 2
        if "left" in self.justify:
            x0, x1 = 0.0, width
        elif "right" in self.justify:
            x0, x1 = -width, 0.0
        if "top" in self.justify:
            y0, y1 = 0.0, height
        elif "bottom" in self.justify:
            y0, y1 = -height, 0.0
        if "mirror" in self.justify:
            x0, x1 = -x1, -x0
        corners = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
        return [g.to_board(self.at, self.angle, c) for c in corners]

    def shape(self) -> g.Shape:
        return g.Shape("poly", self.box(), self.thickness / 2)


@dataclass
class Pad:
    owner: str                      # footprint reference
    number: str
    kind: str                       # thru_hole, smd, connect, np_thru_hole
    shape_name: str                 # circle, rect, oval, roundrect, trapezoid, custom
    at: Point
    angle: float
    size: Tuple[float, float]
    drill: Optional[Tuple[float, float]]
    layers: List[str]
    net: str
    extent: Optional[Tuple[float, float, float, float]] = None   # custom pads: local bbox

    def on_layer(self, layer: str) -> bool:
        for spec in self.layers:
            if spec == layer:
                return True
            if spec == "*.Cu" and layer.endswith(".Cu"):
                return True
            if spec == "F&B.Cu" and layer in ("F.Cu", "B.Cu"):
                return True
            if spec.startswith("*.") and layer.endswith(spec[1:]):
                return True
        return False

    @property
    def through(self) -> bool:
        return self.kind in ("thru_hole", "np_thru_hole")

    def shape(self) -> g.Shape:
        w, h = self.size
        if self.shape_name == "circle" or (self.shape_name == "oval" and abs(w - h) < 1e-9):
            return g.Shape("point", [self.at], w / 2)
        if self.shape_name == "oval":
            half = abs(w - h) / 2
            local = [(-half, 0.0), (half, 0.0)] if w > h else [(0.0, -half), (0.0, half)]
            return g.Shape("seg", [g.to_board(self.at, self.angle, p) for p in local], min(w, h) / 2)
        if self.shape_name == "custom" and self.extent:
            x0, y0, x1, y1 = self.extent
            corners = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
            return g.Shape("poly", [g.to_board(self.at, self.angle, c) for c in corners])
        return g.Shape("poly", g.rect_polygon(self.at[0], self.at[1], w, h, self.angle))


@dataclass
class Footprint:
    ref: str
    value: str
    lib_id: str
    at: Point
    angle: float
    layer: str
    properties: Dict[str, str]
    attributes: List[str]
    pads: List[Pad] = field(default_factory=list)
    graphics: List[Graphic] = field(default_factory=list)
    texts: List[Text] = field(default_factory=list)
    uuid: str = ""

    @property
    def side(self) -> str:
        return "back" if self.layer.startswith("B.") else "front"

    @property
    def dnp(self) -> bool:
        return "dnp" in self.attributes

    def courtyard_bbox(self) -> Optional[g.BBox]:
        return g.bbox_union(gr.bbox() for gr in self.graphics if gr.layer.endswith(".CrtYd"))

    def pad_center(self) -> Point:
        if not self.pads:
            return self.at
        box = g.bbox_of(p.at for p in self.pads)
        return round((box[0] + box[2]) / 2, 6), round((box[1] + box[3]) / 2, 6)


@dataclass
class Track:
    kind: str                       # segment or arc
    start: Point
    end: Point
    width: float
    layer: str
    net: str
    mid: Optional[Point] = None
    locked: bool = False
    uuid: str = ""

    @property
    def length(self) -> float:
        if self.kind == "arc" and self.mid:
            return g.arc_length(self.start, self.mid, self.end)
        return g.dist(self.start, self.end)

    def path(self) -> List[Point]:
        if self.kind == "arc" and self.mid:
            return g.arc_points(self.start, self.mid, self.end)
        return [self.start, self.end]

    def shape(self) -> g.Shape:
        pts = self.path()
        if len(pts) == 2:
            return g.Shape("seg", pts, self.width / 2)
        return g.Shape("path", pts, self.width / 2)


@dataclass
class Via:
    at: Point
    size: float
    drill: float
    layers: List[str]               # the two end layers, as written
    net: str
    via_type: str = "through"       # through, blind, buried, micro
    uuid: str = ""

    def spans(self, layer: str, copper_order: Sequence[str]) -> bool:
        if self.via_type == "through" or len(self.layers) < 2:
            return layer.endswith(".Cu")
        try:
            i, j = sorted((copper_order.index(self.layers[0]), copper_order.index(self.layers[1])))
            return i <= copper_order.index(layer) <= j
        except ValueError:
            return False

    def shape(self) -> g.Shape:
        return g.Shape("point", [self.at], self.size / 2)


@dataclass
class Zone:
    net: str
    layers: List[str]
    name: str
    rule_area: bool
    priority: int
    outline: List[Point]
    filled: Dict[str, List[List[Point]]]     # layer -> polygons

    def filled_area(self) -> float:
        return sum(g.polygon_area(poly) for polys in self.filled.values() for poly in polys)

    def contains(self, p: Point, layer: str) -> bool:
        return any(g.point_in_polygon(p, poly) for poly in self.filled.get(layer, []))


# ---------------------------------------------------------------- netclasses (.kicad_pro)

@dataclass
class NetClass:
    name: str
    track_width: Optional[float] = None
    clearance: Optional[float] = None
    via_diameter: Optional[float] = None
    via_drill: Optional[float] = None


class NetClasses:
    """Net -> netclass from the project file: explicit assignments first, then patterns."""

    def __init__(self, classes: Optional[List[NetClass]] = None,
                 assignments: Optional[Dict[str, object]] = None,
                 patterns: Optional[List[Tuple[str, str]]] = None):
        self.classes = {c.name: c for c in (classes or [NetClass("Default")])}
        self.assignments = assignments or {}
        self.patterns = patterns or []

    @classmethod
    def from_project(cls, path: Optional[Path]) -> "NetClasses":
        if not path or not Path(path).is_file():
            return cls()
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return cls()
        ns = data.get("net_settings") or {}
        classes = [NetClass(c.get("name", "?"), c.get("track_width"), c.get("clearance"),
                            c.get("via_diameter"), c.get("via_drill")) for c in ns.get("classes") or []]
        patterns = [(p.get("pattern", ""), p.get("netclass", "")) for p in ns.get("netclass_patterns") or []]
        return cls(classes or None, ns.get("netclass_assignments") or {}, patterns)

    def of(self, net: str) -> str:
        assigned = self.assignments.get(net)
        if isinstance(assigned, list) and assigned:
            return str(assigned[0])
        if isinstance(assigned, str) and assigned:
            return assigned
        for pattern, name in self.patterns:
            if fnmatch.fnmatchcase(net, pattern):
                return name
            try:
                if re.fullmatch(pattern, net):
                    return name
            except re.error:
                pass
        return "Default"

    def get(self, name: str) -> Optional[NetClass]:
        return self.classes.get(name)


# ---------------------------------------------------------------- board

@dataclass
class Board:
    path: Optional[Path]
    root: Node
    format_version: str
    generator_version: str
    thickness: Optional[float]
    layers: List[Dict[str, str]]
    copper_layers: List[str]
    stackup: List[Dict[str, object]]
    footprints: List[Footprint]
    tracks: List[Track]
    vias: List[Via]
    zones: List[Zone]
    graphics: List[Graphic]
    texts: List[Text]
    netclasses: NetClasses

    @property
    def pads(self) -> List[Pad]:
        return [p for fp in self.footprints for p in fp.pads]

    def footprint(self, ref: str) -> Optional[Footprint]:
        return next((fp for fp in self.footprints if fp.ref == ref), None)

    def nets(self) -> List[str]:
        names = {p.net for p in self.pads} | {t.net for t in self.tracks} | {v.net for v in self.vias}
        names |= {z.net for z in self.zones if not z.rule_area}
        names.discard("")
        return sorted(names)

    def edge_graphics(self) -> List[Graphic]:
        out = [gr for gr in self.graphics if gr.layer == "Edge.Cuts"]
        for fp in self.footprints:
            out += [gr for gr in fp.graphics if gr.layer == "Edge.Cuts"]
        return out

    def outline_bbox(self) -> Optional[g.BBox]:
        """Board outline measured on line centres (not including the line width)."""
        pts = []
        for gr in self.edge_graphics():
            if gr.kind == "circle":
                c, r = gr.center, gr.radius
                pts += [(c[0] - r, c[1] - r), (c[0] + r, c[1] + r)]
            elif gr.kind == "arc" and len(gr.pts) == 3:
                pts += g.arc_points(*gr.pts, max_step_deg=1.0)
            else:
                pts += gr.pts
        return g.bbox_of(pts)


def _net_name(node: Node, numbers: Dict[str, str]) -> str:
    child = node.get("net")
    if child is None:
        return node.value("net_name", "") or ""
    atoms = child.atoms()
    if not atoms:
        return ""
    if len(atoms) >= 2:
        return atoms[1]
    if isinstance(atoms[0], QStr):
        return atoms[0]
    name = node.value("net_name")
    return name if name is not None else numbers.get(atoms[0], "")


def _graphic(node: Node, origin: Optional[Point] = None, angle: float = 0.0, owner: str = "") -> Optional[Graphic]:
    kind = node.name.split("_", 1)[1]
    layer = node.value("layer", "") or ""
    width = _stroke_width(node)

    def place(p: Optional[Point]) -> Optional[Point]:
        if p is None:
            return None
        return g.to_board(origin, angle, p) if origin is not None else p

    if kind == "line":
        a, b = place(_xy(node, "start")), place(_xy(node, "end"))
        if a is None or b is None:
            return None
        return Graphic("line", layer, width, False, [a, b], owner=owner)
    if kind == "rect":
        s, e = _xy(node, "start"), _xy(node, "end")
        if s is None or e is None:
            return None
        corners = [(s[0], s[1]), (e[0], s[1]), (e[0], e[1]), (s[0], e[1])]
        return Graphic("rect", layer, width, _filled(node), [place(c) for c in corners], owner=owner)
    if kind == "circle":
        c, e = _xy(node, "center"), _xy(node, "end")
        if c is None or e is None:
            return None
        return Graphic("circle", layer, width, _filled(node), [], center=place(c), radius=g.dist(c, e), owner=owner)
    if kind == "arc":
        s, m, e = _xy(node, "start"), _xy(node, "mid"), _xy(node, "end")
        if s is None or e is None:
            return None
        if m is None:                    # very old files: (start centre) (end start) (angle)
            return Graphic("line", layer, width, False, [place(s), place(e)], owner=owner)
        return Graphic("arc", layer, width, False, [place(s), place(m), place(e)], owner=owner)
    if kind == "poly":
        pts = [place(p) for p in _pts(node)]
        return Graphic("poly", layer, width, _filled(node), pts, owner=owner) if pts else None
    if kind == "curve":
        pts = [place(p) for p in _pts(node)]
        return Graphic("curve", layer, width, False, pts, owner=owner) if pts else None
    return None


def _text(node: Node, text: str, kind: str, frame: Optional[Tuple[Point, float]] = None,
          owner: str = "") -> Optional[Text]:
    """frame: (footprint origin, footprint angle) for footprint texts; positions are local, angles absolute."""
    at = node.numbers("at")
    if len(at) < 2:
        return None
    pos = (at[0], at[1])
    if frame is not None:
        pos = g.to_board(frame[0], frame[1], pos)
    effects = node.get("effects")
    font = effects.get("font") if effects is not None else None
    size = font.numbers("size") if font is not None else []
    thickness = font.number("thickness", 0.15) if font is not None else 0.15
    justify = effects.get("justify").atoms() if effects is not None and effects.get("justify") is not None else []
    return Text(text, node.value("layer", "") or "", pos, at[2] if len(at) > 2 else 0.0,
                (size[0], size[1]) if len(size) >= 2 else (1.0, 1.0), thickness or 0.15,
                [str(j) for j in justify], _hidden(node), kind, owner)


_VAR = re.compile(r"\$\{([^}]+)\}")


def _resolve(text: str, props: Dict[str, str]) -> str:
    lower = {k.lower(): v for k, v in props.items()}
    return _VAR.sub(lambda m: lower.get(m.group(1).lower(), m.group(0)), text)


def _pad(node: Node, origin: Point, fp_angle: float, owner: str, numbers: Dict[str, str]) -> Pad:
    atoms = node.atoms()
    number = atoms[0] if atoms else ""
    kind = atoms[1] if len(atoms) > 1 else ""
    shape = atoms[2] if len(atoms) > 2 else ""
    at = node.numbers("at")
    local = (at[0], at[1]) if len(at) >= 2 else (0.0, 0.0)
    angle = at[2] if len(at) > 2 else fp_angle
    size = node.numbers("size") or [0.0, 0.0]
    drill = None
    drill_node = node.get("drill")
    if drill_node is not None:
        values = []
        for item in drill_node[1:]:
            if isinstance(item, Node):
                continue
            try:
                values.append(float(item))
            except ValueError:
                pass
        if values:
            drill = (values[0], values[1] if len(values) > 1 else values[0])
    layers_node = node.get("layers")
    layers = [str(x) for x in layers_node.atoms()] if layers_node is not None else []
    extent = None
    if shape == "custom":
        primitives = node.get("primitives")
        pts = [(-size[0] / 2, -size[1] / 2), (size[0] / 2, size[1] / 2)]
        grow = 0.0
        if primitives is not None:
            for prim in primitives.nodes():
                pts += _pts(prim)
                for key in ("start", "end", "mid"):
                    p = _xy(prim, key)
                    if p:
                        pts.append(p)
                c, e = _xy(prim, "center"), _xy(prim, "end")
                if c and e and prim.name == "gr_circle":
                    r = g.dist(c, e)
                    pts += [(c[0] - r, c[1] - r), (c[0] + r, c[1] + r)]
                grow = max(grow, _stroke_width(prim) / 2)
        extent = g.bbox_of(pts, grow)
    return Pad(owner, str(number), str(kind), str(shape), g.to_board(origin, fp_angle, local), angle,
               (size[0], size[1] if len(size) > 1 else size[0]), drill, layers, _net_name(node, numbers), extent)


def _footprint(node: Node, numbers: Dict[str, str]) -> Footprint:
    at = node.numbers("at")
    origin = (at[0], at[1]) if len(at) >= 2 else (0.0, 0.0)
    angle = at[2] if len(at) > 2 else 0.0
    props: Dict[str, str] = {}
    for prop in node.all("property"):
        atoms = prop.atoms()
        if len(atoms) >= 2:
            props[str(atoms[0])] = str(atoms[1])
    for fp_text in node.all("fp_text"):      # KiCad 6/7: reference and value are fp_text
        atoms = fp_text.atoms()
        if len(atoms) >= 2 and atoms[0] in ("reference", "value"):
            props.setdefault(atoms[0].capitalize(), str(atoms[1]))
    ref = props.get("Reference", "")
    attr = node.get("attr")
    attributes = [str(a) for a in attr.atoms()] if attr is not None else []
    if node.flag("dnp") and "dnp" not in attributes:
        attributes.append("dnp")
    fp = Footprint(ref, props.get("Value", ""), str(node[1]) if len(node) > 1 else "", origin, angle,
                   node.value("layer", "F.Cu") or "F.Cu", props, attributes, uuid=node.value("uuid", "") or "")
    for child in node.nodes():
        name = child.name
        if name == "pad":
            fp.pads.append(_pad(child, origin, angle, ref, numbers))
        elif name.startswith("fp_") and name not in ("fp_text", "fp_text_box"):
            gr = _graphic(child, origin, angle, ref)
            if gr:
                fp.graphics.append(gr)
        elif name == "fp_text":
            atoms = child.atoms()
            if len(atoms) >= 2:
                kind = str(atoms[0])
                text = _resolve(str(atoms[1]), props)
                t = _text(child, text, kind, (origin, angle), ref)
                if t:
                    fp.texts.append(t)
        elif name == "property":
            atoms = child.atoms()
            if len(atoms) >= 2 and child.get("layer") is not None:
                kind = {"Reference": "reference", "Value": "value"}.get(str(atoms[0]), "property")
                t = _text(child, _resolve(str(atoms[1]), props), kind, (origin, angle), ref)
                if t:
                    fp.texts.append(t)
    return fp


def board_from_tree(root: Node, path: Optional[Path] = None, netclasses: Optional[NetClasses] = None) -> Board:
    if root.name != "kicad_pcb":
        raise ValueError(f"not a KiCad board file (top-level is {root.name!r})")
    numbers = {}
    for net in root.all("net"):
        atoms = net.atoms()
        if len(atoms) >= 2:
            numbers[str(atoms[0])] = str(atoms[1])

    layers = []
    layers_node = root.get("layers")
    if layers_node is not None:
        for entry in layers_node.nodes():
            atoms = [str(a) for a in entry]
            layers.append({"id": atoms[0], "name": atoms[1] if len(atoms) > 1 else "",
                           "type": atoms[2] if len(atoms) > 2 else "",
                           "user_name": atoms[3] if len(atoms) > 3 else ""})
    copper = sorted((l["name"] for l in layers if l["type"] in COPPER_TYPES or l["name"].endswith(".Cu")),
                    key=copper_sort_key)

    stackup = []
    setup = root.get("setup")
    stack = setup.get("stackup") if setup is not None else None
    if stack is not None:
        for layer in stack.all("layer"):
            stackup.append({"name": str(layer[1]) if len(layer) > 1 else "",
                            "type": layer.value("type"),
                            "thickness_mm": layer.number("thickness"),
                            "material": layer.value("material")})

    general = root.get("general")
    footprints, tracks, vias, zones, graphics, texts = [], [], [], [], [], []
    for child in root.nodes():
        name = child.name
        if name == "footprint" or name == "module":
            footprints.append(_footprint(child, numbers))
        elif name in ("segment", "arc"):
            start, end = _xy(child, "start"), _xy(child, "end")
            if start is None or end is None:
                continue
            tracks.append(Track(name, start, end, child.number("width", 0.0), child.value("layer", "") or "",
                                _net_name(child, numbers), _xy(child, "mid") if name == "arc" else None,
                                child.flag("locked"), child.value("uuid", "") or ""))
        elif name == "via":
            at = _xy(child, "at") or (0.0, 0.0)
            layer_node = child.get("layers")
            via_type = "through"
            for token in ("blind", "buried", "micro"):
                if token in child.atoms() or child.value("type") == token:
                    via_type = token
            vias.append(Via(at, child.number("size", 0.0), child.number("drill", 0.0),
                            [str(a) for a in layer_node.atoms()] if layer_node is not None else [],
                            _net_name(child, numbers), via_type, child.value("uuid", "") or ""))
        elif name == "zone":
            layer_node = child.get("layers")
            zone_layers = ([str(a) for a in layer_node.atoms()] if layer_node is not None
                           else [child.value("layer", "") or ""])
            if zone_layers == ["*.Cu"] or zone_layers == ["F&B.Cu"]:
                zone_layers = copper if zone_layers == ["*.Cu"] else ["F.Cu", "B.Cu"]
            filled: Dict[str, List[List[Point]]] = {}
            for fp_node in child.all("filled_polygon"):
                filled.setdefault(fp_node.value("layer", zone_layers[0]) or zone_layers[0], []).append(_pts(fp_node))
            outline = _pts(child.get("polygon"))
            zones.append(Zone(_net_name(child, numbers), zone_layers, child.value("name", "") or "",
                              child.get("keepout") is not None, int(child.number("priority", 0) or 0),
                              outline, filled))
        elif name.startswith("gr_") and name not in ("gr_text", "gr_text_box"):
            gr = _graphic(child)
            if gr:
                graphics.append(gr)
        elif name == "gr_text":
            atoms = child.atoms()
            if atoms:
                t = _text(child, str(atoms[0]), "board")
                if t:
                    texts.append(t)

    if netclasses is None:
        project = path.with_suffix(".kicad_pro") if path else None
        netclasses = NetClasses.from_project(project)
    return Board(path, root, root.value("version", "") or "", root.value("generator_version", "") or "",
                 general.number("thickness") if general is not None else None,
                 layers, copper, stackup, footprints, tracks, vias, zones, graphics, texts, netclasses)
