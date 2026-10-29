"""2-D geometry in millimetres, KiCad conventions (y points down, angles in degrees).

Copper and silkscreen shapes are modelled as a *core* plus a *radius*:

- a pad circle or a via is a point core with radius r,
- a track or an oval pad is a segment core with radius w/2,
- a rectangular pad or a text box is a polygon core with radius 0 (or the stroke half-width).

Two shapes overlap when the distance between their cores is below the sum of their radii.
"""
from __future__ import annotations

import math
from collections import defaultdict
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

Point = Tuple[float, float]
BBox = Tuple[float, float, float, float]          # x0, y0, x1, y1
EPS = 1e-6


def rotate(x: float, y: float, angle_deg: float) -> Point:
    """Rotate a point the way KiCad rotates footprint children (RotatePoint)."""
    if not angle_deg:
        return x, y
    a = math.radians(angle_deg)
    c, s = math.cos(a), math.sin(a)
    return x * c + y * s, -x * s + y * c


def to_board(origin: Point, angle_deg: float, local: Point) -> Point:
    """Footprint-local coordinates -> board coordinates."""
    rx, ry = rotate(local[0], local[1], angle_deg)
    return round(origin[0] + rx, 6), round(origin[1] + ry, 6)


def dist(a: Point, b: Point) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def norm_angle(deg: float) -> float:
    """Angle folded into [0, 180): a track has no direction."""
    return deg % 180.0


def seg_angle(a: Point, b: Point) -> float:
    return norm_angle(math.degrees(math.atan2(b[1] - a[1], b[0] - a[0])))


def point_seg_dist(p: Point, a: Point, b: Point) -> float:
    dx, dy = b[0] - a[0], b[1] - a[1]
    length2 = dx * dx + dy * dy
    if length2 <= 0:
        return dist(p, a)
    t = max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / length2))
    return math.hypot(p[0] - a[0] - t * dx, p[1] - a[1] - t * dy)


def _orient(a: Point, b: Point, c: Point) -> float:
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def segs_intersect(a: Point, b: Point, c: Point, d: Point) -> bool:
    d1, d2 = _orient(c, d, a), _orient(c, d, b)
    d3, d4 = _orient(a, b, c), _orient(a, b, d)
    if ((d1 > EPS and d2 < -EPS) or (d1 < -EPS and d2 > EPS)) and \
       ((d3 > EPS and d4 < -EPS) or (d3 < -EPS and d4 > EPS)):
        return True
    return (point_seg_dist(a, c, d) <= EPS or point_seg_dist(b, c, d) <= EPS
            or point_seg_dist(c, a, b) <= EPS or point_seg_dist(d, a, b) <= EPS)


def seg_seg_dist(a: Point, b: Point, c: Point, d: Point) -> float:
    if segs_intersect(a, b, c, d):
        return 0.0
    return min(point_seg_dist(a, c, d), point_seg_dist(b, c, d),
               point_seg_dist(c, a, b), point_seg_dist(d, a, b))


def point_in_polygon(p: Point, poly: Sequence[Point]) -> bool:
    x, y = p
    inside = False
    n = len(poly)
    j = n - 1
    for i in range(n):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if (yi > y) != (yj > y):
            if x < (xj - xi) * (y - yi) / (yj - yi) + xi:
                inside = not inside
        j = i
    return inside


def polygon_edges(poly: Sequence[Point]) -> Iterable[Tuple[Point, Point]]:
    n = len(poly)
    for i in range(n):
        yield poly[i], poly[(i + 1) % n]


def polygon_area(poly: Sequence[Point]) -> float:
    return abs(sum(a[0] * b[1] - b[0] * a[1] for a, b in polygon_edges(poly))) / 2.0


def rect_polygon(cx: float, cy: float, w: float, h: float, angle_deg: float = 0.0) -> List[Point]:
    """Corners of a w x h rectangle centred on (cx, cy), rotated like a KiCad pad."""
    corners = [(-w / 2, -h / 2), (w / 2, -h / 2), (w / 2, h / 2), (-w / 2, h / 2)]
    return [to_board((cx, cy), angle_deg, c) for c in corners]


def bbox_of(points: Iterable[Point], grow: float = 0.0) -> Optional[BBox]:
    pts = list(points)
    if not pts:
        return None
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    return min(xs) - grow, min(ys) - grow, max(xs) + grow, max(ys) + grow


def bbox_union(boxes: Iterable[Optional[BBox]]) -> Optional[BBox]:
    boxes = [b for b in boxes if b]
    if not boxes:
        return None
    return (min(b[0] for b in boxes), min(b[1] for b in boxes),
            max(b[2] for b in boxes), max(b[3] for b in boxes))


# ---------------------------------------------------------------- arcs

def arc_center(a: Point, m: Point, b: Point) -> Optional[Point]:
    d = 2 * (a[0] * (m[1] - b[1]) + m[0] * (b[1] - a[1]) + b[0] * (a[1] - m[1]))
    if abs(d) < 1e-12:
        return None
    a2, m2, b2 = a[0] ** 2 + a[1] ** 2, m[0] ** 2 + m[1] ** 2, b[0] ** 2 + b[1] ** 2
    ux = (a2 * (m[1] - b[1]) + m2 * (b[1] - a[1]) + b2 * (a[1] - m[1])) / d
    uy = (a2 * (b[0] - m[0]) + m2 * (a[0] - b[0]) + b2 * (m[0] - a[0])) / d
    return ux, uy


def arc_points(a: Point, m: Point, b: Point, max_step_deg: float = 10.0) -> List[Point]:
    """Polyline through an arc given by start, mid and end points."""
    c = arc_center(a, m, b)
    if c is None:
        return [a, b]
    r = dist(a, c)
    t0 = math.atan2(a[1] - c[1], a[0] - c[0])
    tm = math.atan2(m[1] - c[1], m[0] - c[0])
    t1 = math.atan2(b[1] - c[1], b[0] - c[0])

    def ccw(x: float, y: float) -> float:
        return (y - x) % (2 * math.pi)

    sweep = ccw(t0, t1)
    if ccw(t0, tm) > sweep:          # the mid point is on the other way round
        sweep -= 2 * math.pi
    steps = max(2, int(abs(math.degrees(sweep)) / max_step_deg) + 1)
    pts = [(c[0] + r * math.cos(t0 + sweep * i / steps), c[1] + r * math.sin(t0 + sweep * i / steps))
           for i in range(steps + 1)]
    pts[0], pts[-1] = a, b
    return pts


def arc_length(a: Point, m: Point, b: Point) -> float:
    pts = arc_points(a, m, b, 2.0)
    return sum(dist(p, q) for p, q in zip(pts, pts[1:]))


def circle_points(c: Point, r: float, steps: int = 32) -> List[Point]:
    return [(c[0] + r * math.cos(2 * math.pi * i / steps), c[1] + r * math.sin(2 * math.pi * i / steps))
            for i in range(steps)]


# ---------------------------------------------------------------- shapes (core + radius)

class Shape:
    """kind: 'point' (pts = [p]), 'seg' (pts = [a, b]), 'poly' (filled polygon), 'path'
    (open polyline). radius: half the stroke width, or the circle radius."""

    __slots__ = ("kind", "pts", "radius", "_bbox")

    def __init__(self, kind: str, pts: Sequence[Point], radius: float = 0.0):
        self.kind = kind
        self.pts = list(pts)
        self.radius = radius
        self._bbox = bbox_of(self.pts, radius)

    @property
    def bbox(self) -> BBox:
        return self._bbox

    def segments(self) -> List[Tuple[Point, Point]]:
        if self.kind == "point":
            return [(self.pts[0], self.pts[0])]
        if self.kind == "poly":
            return list(polygon_edges(self.pts))
        return list(zip(self.pts, self.pts[1:])) or [(self.pts[0], self.pts[0])]

    def __repr__(self) -> str:
        return f"Shape({self.kind}, {len(self.pts)} pts, r={self.radius:g})"


def core_distance(s: Shape, t: Shape) -> float:
    """Distance between the cores (0 when they touch or one polygon contains the other)."""
    if s.kind == "poly" and any(point_in_polygon(p, s.pts) for p in t.pts):
        return 0.0
    if t.kind == "poly" and any(point_in_polygon(p, t.pts) for p in s.pts):
        return 0.0
    best = math.inf
    for a, b in s.segments():
        for c, d in t.segments():
            best = min(best, seg_seg_dist(a, b, c, d))
            if best <= 0:
                return 0.0
    return best


def gap(s: Shape, t: Shape) -> float:
    """Edge-to-edge distance; negative when the shapes overlap."""
    return core_distance(s, t) - s.radius - t.radius


def boxes_touch(a: BBox, b: BBox, grow: float = 0.0) -> bool:
    return not (a[2] + grow < b[0] or b[2] + grow < a[0] or a[3] + grow < b[1] or b[3] + grow < a[1])


class GridIndex:
    """Bucket items by bounding box for fast neighbour queries."""

    def __init__(self, cell: float = 5.0):
        self.cell = cell
        self.buckets: Dict[Tuple[int, int], List[int]] = defaultdict(list)
        self.items: List[Tuple[BBox, object]] = []

    def _cells(self, box: BBox):
        c = self.cell
        for ix in range(int(math.floor(box[0] / c)), int(math.floor(box[2] / c)) + 1):
            for iy in range(int(math.floor(box[1] / c)), int(math.floor(box[3] / c)) + 1):
                yield ix, iy

    def add(self, box: BBox, item: object) -> None:
        index = len(self.items)
        self.items.append((box, item))
        for key in self._cells(box):
            self.buckets[key].append(index)

    def query(self, box: BBox, grow: float = 0.0) -> List[object]:
        box = (box[0] - grow, box[1] - grow, box[2] + grow, box[3] + grow)
        seen, out = set(), []
        for key in self._cells(box):
            for index in self.buckets.get(key, ()):
                if index in seen:
                    continue
                seen.add(index)
                item_box, item = self.items[index]
                if boxes_touch(item_box, box):
                    out.append(item)
        return out
