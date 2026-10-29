"""Structured routing on the file backend: the agent chooses the path, this module does the geometry.

    r = Router(builder)
    a, b = r.pad("U1", "3"), r.pad("J1", "2")
    r.path("SIG", "F.Cu", 0.3, [a, (a[0] + 5, a[1]), b])     # pad -> bend points -> pad

Every segment must be 0, 45 or 90 degrees. Before anything is written, each new segment is checked
against other nets' copper on the same layer (tracks, pads, vias; netclass clearance, the larger of
the two nets) and against the board edge. On any conflict nothing is written and RouteConflict lists
every problem, so the caller can change the path instead of guessing.

`lane_order` puts lines leaving a lane in the order that avoids crossings (routing-playbook.md §3).
`cleanup` merges collinear segments and drops zero-length ones.
"""
from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from . import geometry as g
from .board import BoardBuilder
from .footprints import fmt
from .model import Board, NetClasses
from .sexpr import Node

Point = Tuple[float, float]


class RouteConflict(ValueError):
    def __init__(self, net: str, conflicts: List[Dict]):
        self.net = net
        self.conflicts = conflicts
        lines = [f"{c['what']} at {c['near']}: gap {c['gap']:.3f} mm < {c['required']:.3f} mm"
                 for c in conflicts[:8]]
        more = f"\n  ... {len(conflicts) - 8} more" if len(conflicts) > 8 else ""
        super().__init__(f"net {net}: {len(conflicts)} conflict(s)\n  " + "\n  ".join(lines) + more)


@dataclass
class Item:
    net: str
    shape: g.Shape
    kind: str
    label: str


def angle_ok(a: Point, b: Point, tol: float = 0.01) -> bool:
    if g.dist(a, b) < 1e-9:
        return True
    ang = g.seg_angle(a, b)
    return abs(ang - 45.0 * round(ang / 45.0)) <= tol


class Router:
    def __init__(self, builder: BoardBuilder, netclasses: Optional[NetClasses] = None,
                 default_clearance: float = 0.2, edge_clearance: float = 0.5, hole_clearance: float = 0.25):
        self.builder = builder
        self.netclasses = netclasses or NetClasses()
        self.default_clearance = default_clearance
        self.edge_clearance = edge_clearance
        self.hole_clearance = hole_clearance
        self.board: Board = builder.board(netclasses=self.netclasses)
        self.copper = self.board.copper_layers
        self.index: Dict[str, g.GridIndex] = defaultdict(lambda: g.GridIndex(5.0))
        self.pads: Dict[Tuple[str, str], List] = defaultdict(list)
        for pad in self.board.pads:
            self.pads[(pad.owner, pad.number)].append(pad)
            shape = pad.shape()
            label = f"pad {pad.owner}.{pad.number}"
            if pad.kind == "np_thru_hole":
                hole = g.Shape("point", [pad.at], (pad.drill or pad.size)[0] / 2)
                for layer in self.copper:
                    self.index[layer].add(hole.bbox, Item("", hole, "hole", label))
                continue
            for layer in self.copper:
                if pad.on_layer(layer):
                    self.index[layer].add(shape.bbox, Item(pad.net, shape, "pad", label))
        for t in self.board.tracks:
            self._add_track_item(t.net, t.layer, t.shape())
        for v in self.board.vias:
            for layer in self.copper:
                if v.spans(layer, self.copper):
                    self.index[layer].add(v.shape().bbox, Item(v.net, v.shape(), "via", f"via {v.net}"))
        self.edges = [gr.shape() for gr in self.board.edge_graphics()]
        self.log: List[Dict] = []

    # ------------------------------------------------------------ lookups

    def pad(self, ref: str, number: str, pick: int = 0) -> Point:
        pads = self.pads.get((ref, str(number)))
        if not pads:
            raise KeyError(f"no pad {ref}.{number}")
        return pads[pick].at

    def net_of(self, ref: str, number: str) -> str:
        return self.pads[(ref, str(number))][0].net

    def clearance(self, net_a: str, net_b: str) -> float:
        values = [self.default_clearance]
        for net in (net_a, net_b):
            if net:
                nc = self.netclasses.get(self.netclasses.of(net))
                if nc and nc.clearance:
                    values.append(nc.clearance)
        return max(values)

    def width(self, net: str, fallback: float = 0.25) -> float:
        nc = self.netclasses.get(self.netclasses.of(net))
        return nc.track_width if nc and nc.track_width else fallback

    def _add_track_item(self, net: str, layer: str, shape: g.Shape) -> None:
        self.index[layer].add(shape.bbox, Item(net, shape, "track", f"track {net}"))

    # ------------------------------------------------------------ checks

    def conflicts(self, shape: g.Shape, layer: str, net: str) -> List[Dict]:
        found = []
        reach = 2.0
        for item in self.index[layer].query(shape.bbox, reach):
            if item.net == net and item.kind != "hole":
                continue
            required = self.hole_clearance if item.kind == "hole" else self.clearance(net, item.net)
            gap = g.gap(shape, item.shape)
            if gap < required - 1e-4:
                c = g.bbox_of(item.shape.pts)
                found.append({"what": item.label, "net": item.net, "layer": layer,
                              "near": [round((c[0] + c[2]) / 2, 3), round((c[1] + c[3]) / 2, 3)],
                              "gap": round(gap, 4), "required": required})
        for edge in self.edges:
            gap = g.gap(shape, edge)
            if gap < self.edge_clearance - 1e-4:
                found.append({"what": "board edge", "net": "", "layer": layer, "near": list(shape.pts[0]),
                              "gap": round(gap, 4), "required": self.edge_clearance})
        return found

    def check_path(self, net: str, layer: str, width: float, points: Sequence[Point],
                   any_angle: bool = False) -> List[Dict]:
        problems = []
        if layer not in self.copper:
            return [{"what": f"layer {layer} is not a copper layer", "net": net, "layer": layer,
                     "near": list(points[0]), "gap": 0.0, "required": 0.0}]
        for a, b in zip(points, points[1:]):
            if not any_angle and not angle_ok(a, b):
                problems.append({"what": f"segment at {g.seg_angle(a, b):.2f} deg (only 0/45/90 allowed)",
                                 "net": net, "layer": layer, "near": list(a), "gap": 0.0, "required": 0.0})
            if g.dist(a, b) < 1e-6:
                continue
            problems += self.conflicts(g.Shape("seg", [a, b], width / 2), layer, net)
        return problems

    # ------------------------------------------------------------ writing

    def path(self, net: str, layer: str, width: Optional[float], points: Sequence[Point],
             any_angle: bool = False, check: bool = True) -> List[Node]:
        """Write tracks along the points; zero-length steps are skipped."""
        width = width if width is not None else self.width(net)
        points = [(round(p[0], 6), round(p[1], 6)) for p in points]
        if check:
            problems = self.check_path(net, layer, width, points, any_angle)
            if problems:
                raise RouteConflict(net, problems)
        nodes = []
        for a, b in zip(points, points[1:]):
            if g.dist(a, b) < 1e-6:
                continue
            nodes.append(self.builder.add_track(a, b, width, layer, net))
            self._add_track_item(net, layer, g.Shape("seg", [a, b], width / 2))
        self.log.append({"net": net, "layer": layer, "width": width, "points": [list(p) for p in points]})
        return nodes

    def via(self, at: Point, net: str, size: float = 0.8, drill: float = 0.4, check: bool = True) -> Node:
        shape = g.Shape("point", [at], size / 2)
        if check:
            problems = []
            for layer in self.copper:
                problems += self.conflicts(shape, layer, net)
            if problems:
                raise RouteConflict(net, problems)
        node = self.builder.add_via(at, net, size, drill)
        for layer in self.copper:
            self.index[layer].add(shape.bbox, Item(net, shape, "via", f"via {net}"))
        return node


# ---------------------------------------------------------------- helpers for planning paths

def bend(a: Point, b: Point, first: str = "h") -> List[Point]:
    """Points from a to b with one 45-degree section: straight first along `first` ('h' or 'v'),
    then the diagonal. Returns [a, corner..., b]."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    if abs(dx) < 1e-9 or abs(dy) < 1e-9 or abs(abs(dx) - abs(dy)) < 1e-9:
        return [a, b]
    d = min(abs(dx), abs(dy))
    sx, sy = math.copysign(1, dx), math.copysign(1, dy)
    if first == "h":
        corner = (b[0] - sx * d, a[1]) if abs(dx) > abs(dy) else None
        if corner is None:          # mostly vertical: diagonal then vertical
            return [a, (a[0] + sx * d, a[1] + sy * d), b]
        return [a, corner, b]
    corner = (a[0], b[1] - sy * d) if abs(dy) > abs(dx) else None
    if corner is None:
        return [a, (a[0] + sx * d, a[1] + sy * d), b]
    return [a, corner, b]


def lane_order(exits: Dict[str, float], direction: int = 1) -> List[str]:
    """Order of lines in a lane so none crosses another when it turns off.

    exits: line -> position where it leaves the lane, measured along the lane.
    For lines that turn the same way, the one leaving first must be on the outside of the turn
    (playbook: the line furthest right turns off first). direction=+1 lists them outside-in for
    turns to the right of travel."""
    return sorted(exits, key=lambda k: exits[k] * direction)


def cleanup(builder: BoardBuilder, nets: Optional[Iterable[str]] = None) -> Dict[str, int]:
    """Drop zero-length segments and merge collinear same-width segments that meet end to end
    at a point no other track, pad or via touches."""
    wanted = set(nets) if nets else None
    board = builder.board()
    pad_points = [(p, p.shape()) for p in board.pads]
    via_points = {(round(v.at[0], 4), round(v.at[1], 4)) for v in board.vias}
    segs = [n for n in builder.tree.all("segment") if wanted is None or str(n.value("net")) in wanted]
    removed = 0
    for n in list(segs):
        a, b = tuple(n.numbers("start")), tuple(n.numbers("end"))
        if g.dist(a, b) < 1e-6:
            builder.tree.remove(n)
            segs.remove(n)
            removed += 1
    merged = 0
    changed = True
    while changed:
        changed = False
        ends = defaultdict(list)
        for n in segs:
            for which in ("start", "end"):
                p = tuple(round(v, 4) for v in n.numbers(which))
                ends[(str(n.value("layer")), str(n.value("net")), p)].append((n, which))
        for (layer, net, p), items in ends.items():
            if len(items) != 2 or p in via_points:
                continue
            (n1, w1), (n2, w2) = items
            if abs(n1.number("width") - n2.number("width")) > 1e-9:
                continue
            if any(pad.on_layer(layer) and g.gap(g.Shape("point", [p]), shape) <= 0 for pad, shape in pad_points
                   if abs(pad.at[0] - p[0]) < 5 and abs(pad.at[1] - p[1]) < 5):
                continue
            o1 = tuple(n1.numbers("end" if w1 == "start" else "start"))
            o2 = tuple(n2.numbers("end" if w2 == "start" else "start"))
            v1 = (p[0] - o1[0], p[1] - o1[1])
            v2 = (o2[0] - p[0], o2[1] - p[1])
            if abs(v1[0] * v2[1] - v1[1] * v2[0]) > 1e-6 or v1[0] * v2[0] + v1[1] * v2[1] <= 0:
                continue
            start = n1.get("start")
            end = n1.get("end")
            start[1:3] = [fmt(o1[0]), fmt(o1[1])]
            end[1:3] = [fmt(o2[0]), fmt(o2[1])]
            builder.tree.remove(n2)
            segs.remove(n2)
            merged += 1
            changed = True
            break
    return {"removed_zero_length": removed, "merged_collinear": merged}
