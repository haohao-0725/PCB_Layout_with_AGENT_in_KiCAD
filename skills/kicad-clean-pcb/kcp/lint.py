"""`kcp lint`: measure how tidy and readable a layout is, and judge it against a preset.

Metrics: segment counts and density, off-angle segments, zigzag (turns per 10 mm, short jogs),
vias on power and signal nets, layer main-direction conformity (needs a layer plan), tracks on
GND plane layers, copper pours other than GND, dangling track ends, silkscreen over pads (text
boxes approximated), and alignment of same-prefix part rows.

Thresholds live in presets/lint.json (or a file given with --thresholds), never in this code.
Each metric gets pass / warn / fail, or info (no threshold for this preset) / skip (not measurable).
"""
from __future__ import annotations

import fnmatch
import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path
from statistics import median
from typing import Dict, List, Optional, Tuple

from . import geometry as g
from .model import Board, Track

DEFAULT_THRESHOLDS = Path(__file__).resolve().parent / "presets" / "lint.json"
EPS = 1e-3

ROLE_ALIASES = {"h": "horizontal", "horizontal": "horizontal", "x": "horizontal",
                "v": "vertical", "vertical": "vertical", "y": "vertical",
                "plane": "plane", "gnd": "plane", "any": "any", "free": "any", "mixed": "any"}


# ---------------------------------------------------------------- configuration

def load_thresholds(path: Optional[Path] = None) -> Dict:
    path = Path(path) if path else DEFAULT_THRESHOLDS
    return json.loads(path.read_text(encoding="utf-8"))


def load_layer_plan(path: Path) -> Dict[str, str]:
    """{"F.Cu": "horizontal", "B.Cu": "vertical", "In1.Cu": "plane"}, optionally under "layers".
    Roles: horizontal (h), vertical (v), plane, any."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    layers = data.get("layers", data) if isinstance(data, dict) else {}
    plan = {}
    for layer, role in layers.items():
        if isinstance(role, dict):
            role = role.get("role") or role.get("direction") or "any"
        key = str(role).strip().lower()
        if key not in ROLE_ALIASES:
            raise ValueError(f"layer plan: unknown role {role!r} for {layer} "
                             f"(use horizontal, vertical, plane or any)")
        plan[layer] = ROLE_ALIASES[key]
    return plan


def _matches(name: str, patterns) -> bool:
    base = name.rsplit("/", 1)[-1].upper()
    return any(fnmatch.fnmatchcase(base, p.upper()) or fnmatch.fnmatchcase(name.upper(), p.upper())
               for p in patterns)


class NetRoles:
    def __init__(self, board: Board, settings: Dict):
        self.board = board
        self.ground = settings.get("ground_nets", [])
        self.power = settings.get("power_nets", [])
        self.power_classes = settings.get("power_netclasses", [])

    def is_ground(self, net: str) -> bool:
        return bool(net) and _matches(net, self.ground)

    def is_power(self, net: str) -> bool:
        if not net or self.is_ground(net):
            return False
        return _matches(net, self.power) or _matches(self.board.netclasses.of(net), self.power_classes)

    def role(self, net: str) -> str:
        return "ground" if self.is_ground(net) else "power" if self.is_power(net) else "signal"


# ---------------------------------------------------------------- connectivity helpers

def _key(p) -> Tuple[float, float]:
    return round(p[0], 3), round(p[1], 3)


class CopperIndex:
    """Spatial lookup of pads, vias, tracks and zone fills per copper layer."""

    def __init__(self, board: Board):
        self.board = board
        self.pads = g.GridIndex(5.0)
        for pad in board.pads:
            shape = pad.shape()
            self.pads.add(shape.bbox, (pad, shape))
        self.vias = g.GridIndex(5.0)
        for via in board.vias:
            shape = via.shape()
            self.vias.add(shape.bbox, (via, shape))
        self.tracks: Dict[str, g.GridIndex] = defaultdict(lambda: g.GridIndex(5.0))
        for i, t in enumerate(board.tracks):
            shape = t.shape()
            self.tracks[t.layer].add(shape.bbox, (i, t, shape))

    def pad_at(self, p, layer: str):
        point = g.Shape("point", [p])
        for pad, shape in self.pads.query(point.bbox, EPS):
            if pad.on_layer(layer) and g.gap(point, shape) <= EPS:
                return pad
        return None

    def via_at(self, p, layer: str):
        point = g.Shape("point", [p])
        for via, shape in self.vias.query(point.bbox, EPS):
            if via.spans(layer, self.board.copper_layers) and g.gap(point, shape) <= EPS:
                return via
        return None

    def other_track_at(self, p, layer: str, skip: int) -> bool:
        point = g.Shape("point", [p])
        for i, _t, shape in self.tracks[layer].query(point.bbox, EPS):
            if i != skip and g.gap(point, shape) <= EPS:
                return True
        return False

    def zone_at(self, p, layer: str, net: str) -> bool:
        return any(z.net == net and not z.rule_area and z.contains(p, layer) for z in self.board.zones)


def _direction(t: Track, at_start: bool) -> Tuple[float, float]:
    """Unit vector leaving the track end (start or end) along the track."""
    node = t.start if at_start else t.end
    if t.kind == "arc" and t.mid:
        c = g.arc_center(t.start, t.mid, t.end)
        if c:
            r = (node[0] - c[0], node[1] - c[1])
            v = (-r[1], r[0])
            if v[0] * (t.mid[0] - node[0]) + v[1] * (t.mid[1] - node[1]) < 0:
                v = (-v[0], -v[1])
            n = math.hypot(*v) or 1.0
            return v[0] / n, v[1] / n
    other = t.end if at_start else t.start
    dx, dy = other[0] - node[0], other[1] - node[1]
    n = math.hypot(dx, dy) or 1.0
    return dx / n, dy / n


def _turn(u, v) -> float:
    """Turn angle in degrees at a node where two tracks leave along u and v (0 = straight on)."""
    dot = max(-1.0, min(1.0, u[0] * v[0] + u[1] * v[1]))
    return 180.0 - math.degrees(math.acos(dot))


def _turn_sign(heading_in, heading_out) -> int:
    """+1 / -1 for the side a path turns to, 0 when it goes straight on."""
    cross = heading_in[0] * heading_out[1] - heading_in[1] * heading_out[0]
    return 0 if abs(cross) < 1e-9 else (1 if cross > 0 else -1)


# ---------------------------------------------------------------- measurement

def measure(board: Board, settings: Dict, plan: Optional[Dict[str, str]] = None) -> Dict:
    roles = NetRoles(board, settings)
    index = CopperIndex(board)
    tracks = board.tracks
    total_len = sum(t.length for t in tracks)
    m: Dict[str, object] = {}
    d: Dict[str, object] = {}

    # segments
    pads_per_net = Counter(p.net for p in board.pads if p.net)
    segs_per_net, len_per_net = Counter(), defaultdict(float)
    for t in tracks:
        segs_per_net[t.net] += 1
        len_per_net[t.net] += t.length
    m["segments_total"] = len(tracks)
    m["track_length_mm"] = round(total_len, 1)
    m["segments_per_mm"] = round(len(tracks) / total_len, 4) if total_len > 0 else None
    per_connection = []
    for net, count in segs_per_net.items():
        if pads_per_net[net] >= 2:
            per_connection.append({"net": net, "segments": count, "pads": pads_per_net[net],
                                   "length_mm": round(len_per_net[net], 1),
                                   "per_connection": round(count / (pads_per_net[net] - 1), 2)})
    per_connection.sort(key=lambda x: -x["per_connection"])
    m["max_segments_per_connection"] = per_connection[0]["per_connection"] if per_connection else None
    d["segments_per_net"] = per_connection[:10]

    # angles
    tol = settings.get("angle_tolerance_deg", 0.1)
    min_len = settings.get("min_segment_mm_for_angle", 0.05)
    off, tiny = [], 0
    for t in tracks:
        if t.kind != "segment":
            continue
        if t.length < min_len:
            tiny += 1
            continue
        a = g.seg_angle(t.start, t.end)
        deviation = abs(a - 45.0 * round(a / 45.0))
        if deviation > tol:
            off.append({"net": t.net, "layer": t.layer, "start": list(t.start), "end": list(t.end),
                        "angle_deg": round(a, 2)})
    m["off_angle_segments"] = len(off)
    m["arcs"] = sum(1 for t in tracks if t.kind == "arc")
    m["tiny_segments"] = tiny
    d["off_angle"] = off[:20]

    # turns, jogs, collinear joints
    ends = defaultdict(list)              # (net, layer, node) -> [(track index, at_start)]
    for i, t in enumerate(tracks):
        ends[(t.net, t.layer, _key(t.start))].append((i, True))
        ends[(t.net, t.layer, _key(t.end))].append((i, False))
    turn_min = settings.get("turn_min_deg", 1.0)
    turns_per_net, turn_nodes, collinear = Counter(), set(), 0
    for (net, layer, node), items in ends.items():
        if len(items) != 2:
            continue
        if index.pad_at(node, layer) or index.via_at(node, layer):
            continue
        (i, si), (j, sj) = items
        angle = _turn(_direction(tracks[i], si), _direction(tracks[j], sj))
        if angle > turn_min:
            turns_per_net[net] += 1
            turn_nodes.add((net, layer, node))
        elif angle < 0.01 and tracks[i].kind == tracks[j].kind == "segment" \
                and abs(tracks[i].width - tracks[j].width) < 1e-9:
            collinear += 1
    total_turns = sum(turns_per_net.values())
    m["turns_per_10mm"] = round(total_turns / (total_len / 10.0), 3) if total_len > 0 else None
    m["collinear_joints"] = collinear
    zig = [{"net": n, "turns": c, "length_mm": round(len_per_net[n], 1),
            "turns_per_10mm": round(c / (len_per_net[n] / 10.0), 2)}
           for n, c in turns_per_net.items() if len_per_net[n] >= settings.get("zigzag_min_net_mm", 20.0)]
    zig.sort(key=lambda x: -x["turns_per_10mm"])
    d["zigzag_nets"] = zig[:10]
    jog_factor = settings.get("jog_width_factor", 2.0)
    jogs = []
    for i, t in enumerate(tracks):
        if t.kind != "segment" or t.length >= jog_factor * t.width:
            continue
        a_key, b_key = (t.net, t.layer, _key(t.start)), (t.net, t.layer, _key(t.end))
        if a_key not in turn_nodes or b_key not in turn_nodes:
            continue
        # A jog is an S-bend: the path turns one way and then back. Two turns the same way are a
        # chamfered corner, which is fine on wide tracks.
        (j, sj), = [e for e in ends[a_key] if e[0] != i]
        (k, sk), = [e for e in ends[b_key] if e[0] != i]
        before = _direction(tracks[j], sj)
        own = _direction(t, True)
        after = _direction(tracks[k], sk)
        if _turn_sign((-before[0], -before[1]), own) * _turn_sign(own, after) < 0:
            jogs.append({"net": t.net, "layer": t.layer, "start": list(t.start), "end": list(t.end),
                         "length_mm": round(t.length, 3), "width_mm": t.width})
    m["jogs"] = len(jogs)
    d["jogs"] = jogs[:20]

    # vias
    vias_per_net = Counter(v.net for v in board.vias)
    limit = settings.get("max_vias_per_signal_net")
    m["vias_total"] = len(board.vias)
    m["power_net_vias"] = sum(c for n, c in vias_per_net.items() if roles.is_power(n))
    m["ground_net_vias"] = sum(c for n, c in vias_per_net.items() if roles.is_ground(n))
    # The limit is per pad-to-pad connection: a 3-pad net may use one via on each of its 2 links.
    over = [{"net": n, "vias": c, "connections": max(1, pads_per_net[n] - 1)} for n, c in vias_per_net.items()
            if roles.role(n) == "signal" and limit is not None and c > limit * max(1, pads_per_net[n] - 1)]
    m["signal_nets_over_via_limit"] = len(over) if limit is not None else None
    d["vias_by_net"] = [{"net": n, "role": roles.role(n), "netclass": board.netclasses.of(n), "vias": c}
                        for n, c in vias_per_net.most_common(15)]
    d["signal_nets_over_via_limit"] = sorted(over, key=lambda x: -x["vias"])[:15]

    # layer directions
    layers = {}
    for t in tracks:
        entry = layers.setdefault(t.layer, {"horizontal": 0.0, "vertical": 0.0, "diagonal": 0.0, "other": 0.0})
        if t.kind != "segment":
            entry["other"] += t.length
            continue
        a = g.seg_angle(t.start, t.end)
        if min(a, 180 - a) <= tol:
            entry["horizontal"] += t.length
        elif abs(a - 90) <= tol:
            entry["vertical"] += t.length
        elif abs(a - 45) <= tol or abs(a - 135) <= tol:
            entry["diagonal"] += t.length
        else:
            entry["other"] += t.length
    for name, entry in layers.items():
        total = sum(entry.values())
        role = (plan or {}).get(name)
        if role in ("horizontal", "vertical") and total >= 1.0:
            entry["conformity_pct"] = round(100.0 * entry[role] / total, 1)
        for k in ("horizontal", "vertical", "diagonal", "other"):
            entry[k] = round(entry[k], 1)
        entry["total_mm"] = round(total, 1)
        entry["role"] = role
    planned = [e["conformity_pct"] for e in layers.values() if "conformity_pct" in e]
    m["direction_conformity_min_pct"] = min(planned) if planned else None
    d["layers"] = {k: layers[k] for k in sorted(layers, key=lambda n: board.copper_layers.index(n)
                                                 if n in board.copper_layers else 99)}

    # plane layers
    if plan:
        plane_layers = [layer for layer, role in plan.items() if role == "plane"]
        plane_source = "layer plan"
    else:
        box = board.outline_bbox()
        board_area = (box[2] - box[0]) * (box[3] - box[1]) if box else 0
        coverage = settings.get("plane_coverage_min", 0.5)
        plane_layers = sorted({layer for z in board.zones if not z.rule_area and roles.is_ground(z.net)
                               for layer in z.layers if layer.startswith("In")
                               and board_area > 0 and g.polygon_area(z.outline) >= coverage * board_area})
        plane_source = "inner layers with a GND zone covering the board"
    on_planes = [t for t in tracks if t.layer in plane_layers]
    m["plane_layer_tracks"] = len(on_planes)
    d["plane_layers"] = {"layers": plane_layers, "source": plane_source,
                         "tracks": len(on_planes), "length_mm": round(sum(t.length for t in on_planes), 1),
                         "nets": dict(Counter(t.net for t in on_planes).most_common(10))}

    # zones
    zones = [z for z in board.zones if not z.rule_area]
    m["zones_total"] = len(zones)
    non_ground = [z for z in zones if not roles.is_ground(z.net)]
    m["non_ground_zones"] = len(non_ground)
    d["zones"] = [{"net": z.net or "(no net)", "layers": z.layers, "name": z.name,
                   "role": roles.role(z.net) if z.net else "none",
                   "filled_area_mm2": round(z.filled_area(), 1)} for z in zones]

    # dangling track ends
    dangling = []
    for i, t in enumerate(tracks):
        for p in (t.start, t.end):
            if (index.other_track_at(p, t.layer, i) or index.pad_at(p, t.layer)
                    or index.via_at(p, t.layer) or index.zone_at(p, t.layer, t.net)):
                continue
            dangling.append({"net": t.net, "layer": t.layer, "at": list(p)})
    m["dangling_ends"] = len(dangling)
    d["dangling"] = dangling[:20]

    # silkscreen over pads
    silk = []
    for fp in board.footprints:
        silk += [(fp.ref, f"text '{t.text}'", t.layer, t.shape()) for t in fp.texts
                 if t.layer.endswith(".SilkS") and not t.hidden and t.text.strip()]
        silk += [(fp.ref, gr.kind, gr.layer, gr.shape()) for gr in fp.graphics if gr.layer.endswith(".SilkS")]
    silk += [("", f"text '{t.text}'", t.layer, t.shape()) for t in board.texts
             if t.layer.endswith(".SilkS") and not t.hidden and t.text.strip()]
    silk += [("", gr.kind, gr.layer, gr.shape()) for gr in board.graphics if gr.layer.endswith(".SilkS")]
    overlaps = []
    for owner, what, layer, shape in silk:
        copper = "F.Cu" if layer.startswith("F.") else "B.Cu"
        for pad, pad_shape in index.pads.query(shape.bbox):
            if pad.on_layer(copper) and g.gap(shape, pad_shape) < -EPS:
                overlaps.append({"silk": what, "silk_owner": owner or "board", "layer": layer,
                                 "pad": f"{pad.owner}.{pad.number}"})
    m["silk_over_pads"] = len(overlaps)
    d["silk_over_pads"] = overlaps[:20]

    # aligned rows of same-prefix parts
    rows = _rows(board, settings)
    worst = max((r["deviation_mm"] for r in rows), default=None)
    m["row_misalignment_max_mm"] = worst
    m["misaligned_rows"] = sum(1 for r in rows if r["deviation_mm"] > settings.get("row_align_tolerance_mm", 0.01))
    d["rows"] = sorted(rows, key=lambda r: -r["deviation_mm"])[:15]
    return {"metrics": m, "details": d}


def _prefix(ref: str) -> str:
    m = re.match(r"[A-Za-z_]+", ref)
    return m.group(0) if m else ""


def _rows(board: Board, settings: Dict) -> List[Dict]:
    prefixes = set(settings.get("row_prefixes", ["R"]))
    capture = settings.get("row_capture_mm", 2.0)
    max_gap = settings.get("row_max_gap_mm", 12.0)
    min_parts = settings.get("row_min_parts", 3)
    groups = defaultdict(list)
    for fp in board.footprints:
        prefix = _prefix(fp.ref)
        if prefix in prefixes and fp.pads:
            groups[(prefix, fp.side, round(fp.angle % 180.0, 1))].append(fp)
    rows = []
    for (prefix, side, angle), parts in groups.items():
        for axis in (1, 0):               # axis 1: parts side by side along x (same y); axis 0: stacked
            pts = sorted(((fp.pad_center(), fp.ref) for fp in parts), key=lambda x: x[0][axis])
            clusters, current = [], []
            for item in pts:
                if current and item[0][axis] - current[0][0][axis] > capture:
                    clusters.append(current)
                    current = []
                current.append(item)
            if current:
                clusters.append(current)
            other = 1 - axis
            for cluster in clusters:
                cluster.sort(key=lambda x: x[0][other])
                run = [cluster[0]]
                for item in cluster[1:] + [None]:
                    if item is not None and item[0][other] - run[-1][0][other] <= max_gap:
                        run.append(item)
                        continue
                    if len(run) >= min_parts:
                        values = [p[0][axis] for p in run]
                        mid = median(values)
                        steps = [b[0][other] - a[0][other] for a, b in zip(run, run[1:])]
                        rows.append({"refs": [p[1] for p in run], "prefix": prefix, "side": side,
                                     "angle": angle, "direction": "along x" if axis == 1 else "along y",
                                     "deviation_mm": round(max(abs(v - mid) for v in values), 3),
                                     "pitch_spread_mm": round(max(steps) - min(steps), 3) if steps else 0.0})
                    run = [item] if item is not None else []
    return rows


# ---------------------------------------------------------------- judgement

METRICS = [
    # id, label, unit
    ("segments_total", "Track segments (incl. arcs)", ""),
    ("track_length_mm", "Total track length", "mm"),
    ("segments_per_mm", "Segments per mm of track", "1/mm"),
    ("max_segments_per_connection", "Worst net: segments per pad-to-pad connection", ""),
    ("off_angle_segments", "Segments not at 0/45/90°", ""),
    ("arcs", "Arc tracks", ""),
    ("turns_per_10mm", "Turns per 10 mm of track (zigzag)", "1/10mm"),
    ("jogs", "Short S-bend jogs (< 2 × width)", ""),
    ("collinear_joints", "Collinear joints (segments that could be merged)", ""),
    ("vias_total", "Vias", ""),
    ("power_net_vias", "Vias on power / high-current nets", ""),
    ("ground_net_vias", "Vias on GND nets", ""),
    ("signal_nets_over_via_limit", "Signal nets above the via limit (per connection)", ""),
    ("direction_conformity_min_pct", "Lowest layer main-direction conformity", "%"),
    ("plane_layer_tracks", "Tracks on GND plane layers", ""),
    ("zones_total", "Copper zones", ""),
    ("non_ground_zones", "Zones on nets other than GND", ""),
    ("dangling_ends", "Dangling track ends", ""),
    ("silk_over_pads", "Silkscreen over pads (approx.)", ""),
    ("row_misalignment_max_mm", "Worst part-row misalignment", "mm"),
    ("misaligned_rows", "Misaligned part rows", ""),
]


def _status(value, rule: Optional[Dict]) -> Tuple[str, str]:
    if value is None:
        return "skip", ""
    if not rule:
        return "info", ""
    if "pass_max" in rule:
        target = f"≤ {rule['pass_max']:g}" + (f" (warn ≤ {rule['warn_max']:g})" if rule.get("warn_max") is not None else "")
        if value <= rule["pass_max"]:
            return "pass", target
        if rule.get("warn_max") is not None and value <= rule["warn_max"]:
            return "warn", target
        return "fail", target
    if "pass_min" in rule:
        target = f"≥ {rule['pass_min']:g}" + (f" (warn ≥ {rule['warn_min']:g})" if rule.get("warn_min") is not None else "")
        if value >= rule["pass_min"]:
            return "pass", target
        if rule.get("warn_min") is not None and value >= rule["warn_min"]:
            return "warn", target
        return "fail", target
    return "info", ""


def lint_board(board: Board, preset: str = "T", thresholds: Optional[Dict] = None,
               plan: Optional[Dict[str, str]] = None, thresholds_file: Optional[str] = None) -> Dict:
    thresholds = thresholds or load_thresholds()
    presets = thresholds.get("presets", {})
    if preset not in presets:
        raise ValueError(f"unknown preset {preset!r}; available: {', '.join(presets)}")
    settings = dict(thresholds.get("settings", {}))
    settings.update(presets[preset].get("settings", {}))
    rules = presets[preset].get("metrics", {})
    measured = measure(board, settings, plan)
    rows = []
    notes = {
        "direction_conformity_min_pct": "pass --layer-plan to judge layer directions" if not plan else "",
        "silk_over_pads": "text boxes are estimated from the font size",
    }
    for metric_id, label, unit in METRICS:
        value = measured["metrics"].get(metric_id)
        status, target = _status(value, rules.get(metric_id))
        rows.append({"id": metric_id, "label": label, "value": value, "unit": unit,
                     "target": target, "status": status, "note": notes.get(metric_id, "")})
    statuses = {r["status"] for r in rows}
    overall = "fail" if "fail" in statuses else "warn" if "warn" in statuses else "pass"
    return {
        "tool": "kcp lint", "file": str(board.path) if board.path else None, "preset": preset,
        "preset_name": presets[preset].get("name", preset),
        "thresholds_file": thresholds_file or str(DEFAULT_THRESHOLDS),
        "layer_plan": plan, "status": overall,
        "summary": dict(Counter(r["status"] for r in rows)),
        "metrics": rows, "details": measured["details"],
    }


ICON = {"pass": "pass", "warn": "WARN", "fail": "FAIL", "info": "info", "skip": "skip"}


def to_markdown(result: Dict) -> str:
    lines = [f"# Tidiness lint: {result['status'].upper()} (preset {result['preset']}: {result['preset_name']})", "",
             f"Board: `{result.get('file') or ''}`", "",
             "| Metric | Value | Target | Status |", "|---|---:|---|---|"]
    for r in result["metrics"]:
        value = "—" if r["value"] is None else f"{r['value']:g}" if isinstance(r["value"], (int, float)) else r["value"]
        unit = f" {r['unit']}" if r["unit"] and r["value"] is not None else ""
        note = f" ({r['note']})" if r["note"] else ""
        lines.append(f"| {r['label']}{note} | {value}{unit} | {r['target']} | {ICON[r['status']]} |")
    d = result["details"]
    if d.get("layers"):
        lines += ["", "## Layers", "", "| Layer | Role | H mm | V mm | 45° mm | Other mm | Conformity |",
                  "|---|---|---:|---:|---:|---:|---:|"]
        for name, e in d["layers"].items():
            conf = f"{e['conformity_pct']:g} %" if "conformity_pct" in e else "—"
            lines.append(f"| {name} | {e['role'] or '—'} | {e['horizontal']:g} | {e['vertical']:g} | {e['diagonal']:g} "
                         f"| {e['other']:g} | {conf} |")
    sections = [
        ("Worst nets by segments per connection", "segments_per_net", ["net", "segments", "pads", "per_connection"]),
        ("Zigzag nets", "zigzag_nets", ["net", "turns", "length_mm", "turns_per_10mm"]),
        ("Off-angle segments", "off_angle", ["net", "layer", "start", "end", "angle_deg"]),
        ("Short jogs", "jogs", ["net", "layer", "start", "length_mm", "width_mm"]),
        ("Signal nets above the via limit", "signal_nets_over_via_limit", ["net", "vias", "connections"]),
        ("Zones", "zones", ["net", "layers", "role", "filled_area_mm2"]),
        ("Dangling track ends", "dangling", ["net", "layer", "at"]),
        ("Silkscreen over pads", "silk_over_pads", ["silk_owner", "silk", "layer", "pad"]),
        ("Part rows (worst first)", "rows", ["refs", "direction", "deviation_mm", "pitch_spread_mm"]),
    ]
    for title, key, cols in sections:
        items = d.get(key) or []
        if not items:
            continue
        lines += ["", f"## {title}", "", "| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
        for item in items[:10]:
            cells = []
            for c in cols:
                v = item.get(c)
                if isinstance(v, list):
                    v = ", ".join(f"{x:g}" if isinstance(x, float) else str(x) for x in v)
                cells.append(str(v))
            lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"
