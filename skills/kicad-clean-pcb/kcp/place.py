"""Placement helpers on the file backend: move parts, line them up, put connectors on the edge,
and check the fit (courtyard overlaps, distance to the board edge, keep-out areas).

    positions = row(["R1", "R2", "R3"], start=(20, 30), pitch=2.54, axis="x", angle=90)
    for ref, (x, y, a) in positions.items():
        move(builder, ref, x, y, a)
    report = fit_check(builder.board(), keepouts=[(60, 40, 75, 52, "USB plug")])
"""
from __future__ import annotations

import re
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from . import geometry as g
from .board import BoardBuilder
from .footprints import fmt, norm_deg
from .model import Board, Footprint
from .sexpr import Node

Placement = Tuple[float, float, float]


# ---------------------------------------------------------------- arrangement (pure geometry)

def row(refs: Sequence[str], start: Tuple[float, float], pitch: float, axis: str = "x",
        angle: float = 0.0) -> Dict[str, Placement]:
    """Parts in one line at a fixed pitch, all at the same angle (an aligned resistor row)."""
    out = {}
    for i, ref in enumerate(refs):
        dx, dy = (i * pitch, 0.0) if axis == "x" else (0.0, i * pitch)
        out[ref] = (round(start[0] + dx, 6), round(start[1] + dy, 6), angle)
    return out


def array(template: Dict[str, Placement], count: int, offset: Tuple[float, float],
          rename=lambda ref, i: ref) -> Dict[str, Placement]:
    """Repeat a unit (ref -> placement relative to the unit origin) count times at a fixed offset.
    rename(ref, i) gives the reference used in copy i."""
    out = {}
    for i in range(count):
        for ref, (x, y, a) in template.items():
            out[rename(ref, i)] = (round(x + i * offset[0], 6), round(y + i * offset[1], 6), a)
    return out


# ---------------------------------------------------------------- editing footprints in the tree

def _ref_of(fp: Node) -> str:
    for prop in fp.all("property"):
        if str(prop[1]) == "Reference":
            return str(prop[2])
    return ""


def move(builder: BoardBuilder, ref: str, x: float, y: float, angle: Optional[float] = None) -> Node:
    """Move (and optionally rotate) a placed footprint; pad and text angles follow the rotation."""
    fp = builder.footprint(ref)
    if fp is None:
        raise KeyError(f"no footprint {ref}")
    at = fp.get("at")
    old = float(at[3]) if len(at) > 3 else 0.0
    new = old if angle is None else norm_deg(angle)
    at[1:] = [fmt(x), fmt(y)] + ([fmt(new)] if new else [])
    delta = new - old
    if delta:
        for child in fp.nodes():
            if child.name in ("pad", "property", "fp_text", "fp_text_box"):
                cat = child.get("at")
                if cat is not None:
                    a = float(cat[3]) if len(cat) > 3 else 0.0
                    cat[1:] = [cat[1], cat[2], fmt(norm_deg(a + delta))]
    return fp


def set_text(builder: BoardBuilder, ref: str, field: str, local: Tuple[float, float], angle: Optional[float] = None,
             layer: Optional[str] = None, hide: Optional[bool] = None) -> None:
    """Position a footprint field (e.g. the reference) in footprint-local coordinates; angle is absolute."""
    fp = builder.footprint(ref)
    if fp is None:
        raise KeyError(f"no footprint {ref}")
    for prop in fp.all("property"):
        if str(prop[1]) == field:
            at = prop.get("at")
            a = angle if angle is not None else (float(at[3]) if len(at) > 3 else 0.0)
            at[1:] = [fmt(local[0]), fmt(local[1]), fmt(norm_deg(a))]
            if layer:
                prop.get("layer")[1] = layer
            if hide is not None:
                h = prop.get("hide")
                if hide and h is None:
                    prop.insert(prop.index(prop.get("layer")) + 1, Node(["hide", "yes"]))
                elif not hide and h is not None:
                    prop.remove(h)
            return
    raise KeyError(f"{ref} has no field {field}")


def _silk_layer(fp: Footprint) -> str:
    return "B.SilkS" if fp.side == "back" else "F.SilkS"


def silk_bbox(fp: Footprint, texts: bool = False) -> Optional[g.BBox]:
    """Outer bounds of the footprint's silkscreen lines (stroke included); with texts=True also its
    visible silkscreen texts (estimated boxes). Library parts often draw a pin-1 mark or the body
    outline outside the courtyard."""
    boxes = []
    for gr in fp.graphics:
        if gr.layer == _silk_layer(fp):
            box = gr.bbox()
            if box:
                w = gr.width / 2
                boxes.append((box[0] - w, box[1] - w, box[2] + w, box[3] + w))
    if texts:
        for t in fp.texts:
            if t.layer == _silk_layer(fp) and not t.hidden and t.text:
                box = g.bbox_of(t.box())
                w = t.thickness / 2
                boxes.append((box[0] - w, box[1] - w, box[2] + w, box[3] + w))
    return g.bbox_union(boxes)


# Where the wire or plug goes in, for stock KiCad 10 footprints at rotation 0, as drawn in the
# footprint editor (KiCad's y axis points down, so "bottom" is +y). Checked with 3D renders
# (kicad-cli pcb render, front and back) for every family marked "render"; the others from the
# footprint body (pins at the back of the housing). Families differ even within one maker:
# JST EH faces the other way from PH and XH. Footprints not listed here: see entry_side().
ENTRY_SIDES: List[Tuple[str, str, str]] = [
    (r"TerminalBlock_Phoenix_(MKDS-1,5|MKDS-3|MPT-0,5)-.*_Horizontal$", "bottom", "render"),
    (r"TerminalBlock_Phoenix_PT-1,5-.*-H_.*_Horizontal$", "bottom", "render"),
    (r"PhoenixContact_MSTBA_2,5_\d+-G(-5,08)?_.*_Horizontal$", "bottom", "render"),
    (r"JST_(PH|XH)_S\d+B-.*_Horizontal$", "bottom", "render"),
    (r"JST_EH_S\d+B-EH_.*_Horizontal$", "top", "render"),
    (r"BarrelJack_Horizontal$", "left", "render"),
    (r"USB_B_OST_USB-B1HSxx_Horizontal$", "right", "body"),
    (r"USB_C_Receptacle_HRO_TYPE-C-31-M-12$", "bottom", "body"),
]
SIDES = ("left", "right", "top", "bottom")
_OUTWARD = {"left": (-1.0, 0.0), "right": (1.0, 0.0), "top": (0.0, -1.0), "bottom": (0.0, 1.0)}


def _local(fp: Footprint, p: Tuple[float, float]) -> Tuple[float, float]:
    """Board point -> footprint-local coordinates."""
    return g.rotate(p[0] - fp.at[0], p[1] - fp.at[1], -fp.angle)


def _side_of(vec: Tuple[float, float]) -> str:
    if abs(vec[0]) >= abs(vec[1]):
        return "right" if vec[0] > 0 else "left"
    return "bottom" if vec[1] > 0 else "top"


def edge_mark(fp: Footprint) -> Optional[Dict]:
    """The "PCB Edge" mark that many KiCad connector footprints draw on Dwgs.User (USB, FFC,
    D-sub, coax): {"side": side at rotation 0, "local": the mark's local x or y, "from": "line" or
    "text"}. With a line the value is exact; from the text it is approximate."""
    text = next((t for t in fp.texts if t.text.strip().lower() == "pcb edge"), None)
    box = fp.courtyard_bbox()
    if text is None or box is None:
        return None
    centre = _local(fp, ((box[0] + box[2]) / 2, (box[1] + box[3]) / 2))
    pos = _local(fp, text.at)
    side = _side_of((pos[0] - centre[0], pos[1] - centre[1]))
    axis = 0 if side in ("left", "right") else 1
    value, source = pos[axis], "text"
    best = None
    for gr in fp.graphics:                 # a line across the part, near the text, on the same axis
        if gr.layer != text.layer or gr.kind != "line":
            continue
        a, b = _local(fp, gr.pts[0]), _local(fp, gr.pts[1])
        if abs(a[axis] - b[axis]) < 1e-3 and (best is None or abs(a[axis] - pos[axis]) < abs(best - pos[axis])):
            best = a[axis]
    if best is not None:
        value, source = best, "line"
    return {"side": side, "local": round(value, 4), "from": source}


def entry_side(fp: Footprint) -> Optional[Tuple[str, str]]:
    """(side the wire or plug enters from at rotation 0, how it is known), or None if unknown."""
    name = fp.lib_id.split(":")[-1]
    for pattern, side, how in ENTRY_SIDES:
        if re.search(pattern, name):
            return side, f"kcp.place.ENTRY_SIDES ({how})"
    mark = edge_mark(fp)
    if mark:
        return mark["side"], "the footprint's PCB Edge mark"
    return None


def facing_rotation(entry: str, side: str) -> float:
    """Footprint rotation (degrees) that turns its entry side (at rotation 0) toward a board side."""
    if entry not in _OUTWARD or side not in _OUTWARD:
        raise ValueError(f"sides are {', '.join(SIDES)}")
    want = _OUTWARD[side]
    for angle in (0.0, 90.0, 180.0, 270.0):
        x, y = g.rotate(*_OUTWARD[entry], angle)
        if abs(x - want[0]) < 1e-6 and abs(y - want[1]) < 1e-6:
            return angle
    raise AssertionError("unreachable")


def at_edge(fp: Footprint, outline: g.BBox, side: str, inset: float = 0.0, silk: bool = True) -> Tuple[float, float]:
    """Footprint origin that puts the part flush with a board edge (minus inset). The part's extent
    is its courtyard plus, with silk=True, its silkscreen lines: KiCad's DRC flags silkscreen that
    crosses the board edge (silk_edge_clearance), touching is fine."""
    box = fp.courtyard_bbox() or g.bbox_of(p.at for p in fp.pads)
    if silk:
        box = g.bbox_union([box, silk_bbox(fp)])
    x, y = fp.at
    if side == "left":
        return x + (outline[0] + inset - box[0]), y
    if side == "right":
        return x + (outline[2] - inset - box[2]), y
    if side == "top":
        return x, y + (outline[1] + inset - box[1])
    return x, y + (outline[3] - inset - box[3])


def to_edge(builder: BoardBuilder, ref: str, side: str, inset: float = 0.0, silk: bool = True,
            entry: Optional[str] = None) -> Dict:
    """Put a placed part flush with a board edge, in the builder's tree; the other coordinate is kept.

    entry=None keeps the rotation. entry="auto" turns a known connector so its wire or plug entry
    faces out of the board (ENTRY_SIDES, or the footprint's PCB Edge mark); entry="left", "right",
    "top" or "bottom" names the side it enters from at rotation 0 (see it in KiCad's 3D viewer).
    Returns {"ref", "at": [x, y, rotation], "entry", "edge_mark"?}. edge_mark is set when the
    footprint marks where its maker wants the board edge: "inside_mm" > 0 means the mark lies that
    far inside the board edge, so the plug may not seat; pass inset=-inside_mm (and accept the
    overhang) to follow the maker."""
    if side not in SIDES:
        raise ValueError(f"side must be one of {', '.join(SIDES)}")
    board = builder.board()
    fp = board.footprint(ref)
    if fp is None:
        raise KeyError(f"no footprint {ref}")
    outline = board.outline_bbox()
    if outline is None:
        raise ValueError("the board has no Edge.Cuts outline yet")
    info: Dict = {"ref": ref, "entry": None}
    if entry is not None:
        if entry == "auto":
            found = entry_side(fp)
            if found is None:
                raise ValueError(f"{ref} ({fp.lib_id}): wire/plug entry side unknown. Look at the part in KiCad's "
                                 f"3D viewer at rotation 0 and pass entry='left', 'right', 'top' or 'bottom'")
            local_entry, how = found
        elif entry in SIDES:
            local_entry, how = entry, "given"
        else:
            raise ValueError("entry must be auto, left, right, top or bottom")
        angle = facing_rotation(local_entry, side)
        move(builder, ref, fp.at[0], fp.at[1], angle)
        fp = builder.board().footprint(ref)
        info["entry"] = {"at_rotation_0": local_entry, "source": how}
    x, y = at_edge(fp, outline, side, inset, silk)
    move(builder, ref, x, y)
    fp = builder.board().footprint(ref)
    info["at"] = [round(fp.at[0], 4), round(fp.at[1], 4), fp.angle]
    mark = edge_mark(fp)
    if mark:
        faces = _side_of(g.rotate(*_OUTWARD[mark["side"]], fp.angle))
        if faces != side:
            info["edge_mark"] = {"faces": faces, "note": f"the footprint's PCB Edge mark faces {faces}, not {side}: "
                                                         f"use entry='auto' to turn it"}
        else:
            axis = 0 if side in ("left", "right") else 1
            lx, ly = (mark["local"], 0.0) if mark["side"] in ("left", "right") else (0.0, mark["local"])
            pos = g.to_board(fp.at, fp.angle, (lx, ly))[axis]
            edge = {"left": outline[0], "right": outline[2], "top": outline[1], "bottom": outline[3]}[side]
            inside = (pos - edge) if side in ("left", "top") else (edge - pos)
            info["edge_mark"] = {"inside_mm": round(inside, 3), "from": mark["from"]}
    return info


# ---------------------------------------------------------------- fit check

def courtyard_shapes(fp: Footprint) -> List[g.Shape]:
    shapes = []
    for gr in fp.graphics:
        if not gr.layer.endswith(".CrtYd"):
            continue
        if gr.kind == "rect":
            shapes.append(g.Shape("poly", gr.pts))
        elif gr.kind == "circle":
            shapes.append(g.Shape("point", [gr.center], gr.radius))
        elif gr.kind == "poly" and len(gr.pts) >= 3:
            shapes.append(g.Shape("poly", gr.pts))
    if not shapes:
        box = fp.courtyard_bbox()
        if box:
            shapes.append(g.Shape("poly", [(box[0], box[1]), (box[2], box[1]), (box[2], box[3]), (box[0], box[3])]))
    return shapes


def _project(points, axis):
    values = [p[0] * axis[0] + p[1] * axis[1] for p in points]
    return min(values), max(values)


def overlaps(a: g.Shape, b: g.Shape, eps: float = 1e-3) -> bool:
    """True when two courtyard shapes overlap by more than eps (touching is fine).
    Polygons are treated as convex (separating-axis test); circles are point shapes with a radius."""
    if a.kind == "point" and b.kind == "point":
        return g.dist(a.pts[0], b.pts[0]) < a.radius + b.radius - eps
    if a.kind == "point" or b.kind == "point":
        circle, poly = (a, b) if a.kind == "point" else (b, a)
        c = circle.pts[0]
        if g.point_in_polygon(c, poly.pts):
            return True
        edge = min(g.point_seg_dist(c, p, q) for p, q in g.polygon_edges(poly.pts))
        return edge < circle.radius - eps
    for poly in (a, b):
        for p, q in g.polygon_edges(poly.pts):
            axis = (q[1] - p[1], p[0] - q[0])
            length = (axis[0] ** 2 + axis[1] ** 2) ** 0.5
            if length < 1e-12:
                continue
            axis = (axis[0] / length, axis[1] / length)
            a0, a1 = _project(a.pts, axis)
            b0, b1 = _project(b.pts, axis)
            if a1 <= b0 + eps or b1 <= a0 + eps:
                return False
    return True


def fit_check(board: Board, keepouts: Iterable[Tuple[float, float, float, float, str]] = (),
              edge_min: float = 0.0, ignore: Iterable[str] = ()) -> Dict:
    """Courtyard overlaps between parts on the same side, parts closer than edge_min to the board
    edge (or outside it), silkscreen that crosses the board edge (lines, and texts by estimated
    box), and parts inside keep-out rectangles (x0, y0, x1, y1, reason)."""
    skip = set(ignore)
    parts = [fp for fp in board.footprints if fp.ref not in skip]
    shapes = {fp.ref: courtyard_shapes(fp) for fp in parts}
    overlaps_ = overlaps
    found = []
    for i, a in enumerate(parts):
        for b in parts[i + 1:]:
            if a.side != b.side or not shapes[a.ref] or not shapes[b.ref]:
                continue
            if any(overlaps_(s, t) for s in shapes[a.ref] for t in shapes[b.ref]):
                found.append([a.ref, b.ref])
    outline = board.outline_bbox()
    edge = []
    if outline:
        for fp in parts:
            box = g.bbox_union(s.bbox for s in shapes[fp.ref])
            if not box or "board_only" in fp.attributes:
                continue
            margin = min(box[0] - outline[0], box[1] - outline[1], outline[2] - box[2], outline[3] - box[3])
            if margin < edge_min - 1e-4:
                edge.append({"ref": fp.ref, "margin_mm": round(margin, 3)})
    silk = []
    if outline:
        for fp in parts:
            box = silk_bbox(fp, texts=True)
            if not box:
                continue
            margin = min(box[0] - outline[0], box[1] - outline[1], outline[2] - box[2], outline[3] - box[3])
            if margin < -1e-4:
                silk.append({"ref": fp.ref, "margin_mm": round(margin, 3)})
    blocked = []
    for x0, y0, x1, y1, reason in keepouts:
        zone = g.Shape("poly", [(x0, y0), (x1, y0), (x1, y1), (x0, y1)])
        for fp in parts:
            if any(overlaps_(zone, s) for s in shapes[fp.ref]):
                blocked.append({"ref": fp.ref, "keepout": reason})
    return {"ok": not (found or edge or silk or blocked), "overlaps": found, "edge": edge, "silk_edge": silk,
            "keepouts": blocked}
