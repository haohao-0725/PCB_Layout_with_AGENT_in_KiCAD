"""Placement helpers on the file backend: move parts, line them up, put connectors on the edge,
and check the fit (courtyard overlaps, distance to the board edge, keep-out areas).

    positions = row(["R1", "R2", "R3"], start=(20, 30), pitch=2.54, axis="x", angle=90)
    for ref, (x, y, a) in positions.items():
        move(builder, ref, x, y, a)
    report = fit_check(builder.board(), keepouts=[(60, 40, 75, 52, "USB plug")])
"""
from __future__ import annotations

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
