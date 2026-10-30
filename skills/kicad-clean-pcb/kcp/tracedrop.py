"""Voltage drop and temperature rise along the copper tracks of one net (file backend, no pcbnew).

    python <skill>/kcp tracedrop board.kicad_pcb --net +5V --source J1.1 --load U3.8=0.15 --load J5.1=0.125

Method (same as the original scripts/trace_drop.py):
- Builds the track graph of the net: straight and arc tracks; a track end that lands in the middle
  of another straight track splits it (T-junction); pads connect the track ends that land inside
  them. Tracks in parallel between the same two points (e.g. on two layers between the same THT
  pads) are combined as parallel resistors. Pads that share a number (REF.PAD) are one pin.
- Takes the lowest-resistance path from the source pad to each load pad and adds the load currents
  along it; loops are treated as that tree, which over-estimates the drop.
- Segment resistance = rho(T) * length / (width * copper thickness), rho(T) = 1.724e-8 ohm*m *
  (1 + 0.00393 * (T - 20 C)).
- Temperature rise per segment from IPC-2221: I = k * dT^0.44 * A^0.725 (A in mil^2, k = 0.048
  outer, 0.024 inner). Conservative, especially for inner layers.

Limits: track copper only (pours, pads, joints, connectors and the return path are not included);
layer connectivity is inferred from coordinates, so run it on a board with no unconnected items;
arc tracks are not split by T-junctions in their middle.
"""
from __future__ import annotations

import heapq
from collections import defaultdict
from typing import Dict, List, Optional, Sequence, Tuple

from . import geometry as g
from .model import Board

RHO_20C = 1.724e-8      # annealed copper (IACS), ohm*m at 20 C
ALPHA_CU = 0.00393      # 1/C


def copper_rho(temp_c: float) -> float:
    return RHO_20C * (1 + ALPHA_CU * (temp_c - 20.0))


def ipc2221_delta_t(current_a: float, width_mm: float, thick_um: float, outer: bool) -> float:
    if current_a <= 0:
        return 0.0
    k = 0.048 if outer else 0.024
    area_mil2 = (width_mm / 0.0254) * (thick_um / 25.4)
    return (current_a / (k * area_mil2 ** 0.725)) ** (1 / 0.44)


def parallel(resistances: Sequence[float]) -> float:
    if any(r == 0 for r in resistances):
        return 0.0
    return 1.0 / sum(1.0 / r for r in resistances)


def _key(x: float, y: float) -> Tuple[float, float]:
    return round(x, 3), round(y, 3)


def analyse(board: Board, net: str, source: str, loads: Dict[str, float], outer_um: float = 35.0,
            inner_um: float = 17.5, temp_c: float = 40.0, rho: Optional[float] = None,
            dt_limit: float = 20.0) -> Dict:
    rho = rho if rho else copper_rho(temp_c)
    outer_layers = {"F.Cu", "B.Cu"}
    tracks = []
    for t in board.tracks:
        if t.net != net:
            continue
        outer = t.layer in outer_layers
        tracks.append({"a": _key(*t.start), "b": _key(*t.end), "arc": t.kind == "arc", "length": t.length,
                       "width": t.width, "thick": outer_um if outer else inner_um, "outer": outer, "layer": t.layer})
    if not tracks:
        raise ValueError(f"net {net} has no tracks")

    ends = {t[e] for t in tracks for e in ("a", "b")}
    links = defaultdict(list)
    for t in tracks:
        a, b = t["a"], t["b"]
        if t["length"] <= 0:
            continue
        cuts = [(0.0, a), (t["length"], b)]
        if not t["arc"]:
            for e in ends:
                if e in (a, b):
                    continue
                cross = (b[0] - a[0]) * (e[1] - a[1]) - (b[1] - a[1]) * (e[0] - a[0])
                along = ((e[0] - a[0]) * (b[0] - a[0]) + (e[1] - a[1]) * (b[1] - a[1])) / t["length"]
                if abs(cross) / t["length"] < 0.02 and 0 < along < t["length"]:
                    cuts.append((along, e))
        cuts.sort()
        for (s0, n0), (s1, n1) in zip(cuts, cuts[1:]):
            if n0 == n1:
                continue
            seg = dict(t, length=s1 - s0)
            seg["r"] = rho * (s1 - s0) * 1e-3 / (t["width"] * 1e-3 * t["thick"] * 1e-6)
            links[frozenset((n0, n1))].append(seg)

    # Several pads can share one number (both clips of a fuse holder, a connector's shell tabs):
    # they are one pin, joined inside the part, so all of them connect to the same node.
    pads: Dict[str, List] = defaultdict(list)
    for p in board.pads:
        if p.net == net:
            pads[f"{p.owner}.{p.number}"].append(p)
    nodes = {n for pair in links for n in pair}
    for group in pads.values():
        first = _key(*group[0].at)
        for p in group:
            centre = _key(*p.at)
            shape = p.shape()
            for n in nodes:
                if n != centre and g.gap(g.Shape("point", [n]), shape) <= 1e-6:
                    links[frozenset((centre, n))].append({"r": 0.0})
            if centre != first:
                links[frozenset((first, centre))].append({"r": 0.0})

    graph = defaultdict(list)
    for pair, segs in links.items():
        u, v = tuple(pair)
        r = parallel([s["r"] for s in segs])
        graph[u].append((v, r))
        graph[v].append((u, r))

    def node(name: str):
        if name not in pads:
            raise ValueError(f"{name} is not a pad on net {net} (use REF.PAD)")
        return _key(*pads[name][0].at)

    src = node(source)
    dist, prev = {src: 0.0}, {}
    queue = [(0.0, src)]
    while queue:
        d, u = heapq.heappop(queue)
        if d > dist[u]:
            continue
        for v, r in graph[u]:
            if d + r < dist.get(v, float("inf")):
                dist[v], prev[v] = d + r, u
                heapq.heappush(queue, (d + r, v))

    current = defaultdict(float)
    for name, amps in loads.items():
        v = node(name)
        if v not in dist:
            raise ValueError(f"{name} is not connected to {source} by tracks")
        while v != src:
            current[frozenset((prev[v], v))] += amps
            v = prev[v]

    def link_heat(pair):
        segs = [s for s in links[pair] if s["r"] > 0]
        r_par = parallel([s["r"] for s in links[pair]])
        best = (0.0, None)
        for s in segs:
            amps = current[pair] * (r_par / s["r"]) if r_par > 0 else 0.0
            dt = ipc2221_delta_t(amps, s["width"], s["thick"], s["outer"])
            if best[1] is None or dt > best[0]:
                best = (dt, dict(s, amps=amps))
        return best

    rows: List[Dict] = []
    hottest = (0.0, None)
    for name in loads:
        v, drop, worst = node(name), 0.0, (0.0, None)
        while v != src:
            pair = frozenset((prev[v], v))
            drop += parallel([s["r"] for s in links[pair]]) * current[pair]
            heat = link_heat(pair)
            if heat[1] is not None and (worst[1] is None or heat[0] > worst[0]):
                worst = heat
            v = prev[v]
        if worst[1] is not None and (hottest[1] is None or worst[0] > hottest[0]):
            hottest = worst
        rows.append({"load": name, "amps": loads[name], "path_mohm": round(dist[node(name)] * 1e3, 2),
                     "drop_mv": round(drop * 1e3, 1), "max_dt_c": round(worst[0], 1)})
    total_len = defaultdict(float)
    for t in tracks:
        total_len[t["layer"]] += t["length"]
    hot = hottest[1]
    return {
        "tool": "kcp tracedrop", "net": net, "source": source, "total_load_a": round(sum(loads.values()), 4),
        "tracks_mm": {k: round(v, 1) for k, v in sorted(total_len.items())},
        "copper_um": {"outer": outer_um, "inner": inner_um}, "rho_ohm_m": rho,
        "temp_c": None if rho != copper_rho(temp_c) else temp_c,
        "loads": rows,
        "hottest": None if hot is None else {"layer": hot["layer"], "width_mm": hot["width"], "thick_um": hot["thick"],
                                             "amps": round(hot["amps"], 3), "dt_c": round(hottest[0], 1)},
        "dt_limit_c": dt_limit, "above_limit": bool(hot) and hottest[0] > dt_limit,
        "method": "IPC-2221 track rise; tracks only (no pours, pads or connectors); estimate",
    }


def to_text(result: Dict) -> str:
    lines = [f"net {result['net']}: tracks " + ", ".join(f"{k} {v:.0f} mm" for k, v in result["tracks_mm"].items())
             + f"; copper outer {result['copper_um']['outer']} um / inner {result['copper_um']['inner']} um; "
             f"rho {result['rho_ohm_m']:.3e} ohm*m" + (f" ({result['temp_c']:g} C)" if result["temp_c"] else "")
             + f"; total load {result['total_load_a']:.3f} A",
             f"{'load':18s}{'path mOhm':>10s}{'drop mV':>9s}{'max dT C':>10s}"]
    for row in result["loads"]:
        lines.append(f"{row['load']:18s}{row['path_mohm']:10.1f}{row['drop_mv']:9.1f}{row['max_dt_c']:10.1f}")
    hot = result["hottest"]
    if hot:
        flag = "  ABOVE LIMIT" if result["above_limit"] else ""
        lines.append(f"hottest segment: {hot['layer']} {hot['width_mm']:.2f} mm, {hot['thick_um']:g} um, "
                     f"{hot['amps']:.2f} A -> dT {hot['dt_c']:.1f} C (IPC-2221, limit {result['dt_limit_c']:g} C){flag}")
    return "\n".join(lines) + "\n"
