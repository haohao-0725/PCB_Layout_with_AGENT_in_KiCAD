"""Estimate voltage drop and temperature rise along the copper tracks of one net in a KiCad board.
Run it with the Python that ships with KiCad (it needs the pcbnew module).

    "<KiCad>/bin/python" trace_drop.py board.kicad_pcb --net +5V --source J1.1 \\
        --load U3.8=0.15 --load J5.1=0.125 --inner-um 17.5 --temp-c 40 --dt-limit 20

Method
- Builds the track graph of the net: straight tracks and arc tracks; a track end that lands in
  the middle of another straight track splits it (T-junction); pads connect the track ends that
  land inside them. Tracks that run in parallel between the same two points (for example on two
  layers between the same THT pads) are combined as parallel resistors.
- Takes the lowest-resistance path from the source pad to each load pad and adds the load
  currents along it; loops are treated as that tree, which over-estimates the drop.
- Segment resistance = rho(T) * length / (width * copper thickness), with
  rho(T) = 1.724e-8 ohm*m * (1 + 0.00393 * (T - 20 C)). --temp-c is the copper temperature you
  expect in operation (default 40 C); --rho overrides it.
- Temperature rise of each segment from the IPC-2221 formula I = k * dT^0.44 * A^0.725
  (A in mil^2, k = 0.048 outer layers, 0.024 inner layers; valid to about 35 A outer / 17.5 A
  inner, dT <= 100 C, width <= 10 mm). IPC-2221 is conservative, especially for inner layers;
  when a result is near the limit, check it with an IPC-2152 calculator before widening.

Limits
- Track copper only: zones/pours, pads, solder joints, connectors, wires and the return path
  are not included. Boards that distribute power through pours will read high.
- Layer connectivity is inferred from coordinates (vias and THT pads are not checked), so run it
  on a board that passes DRC with no unconnected items.
- Arc tracks are not split by T-junctions in their middle.
"""
from __future__ import annotations

import argparse
import heapq
from collections import defaultdict

RHO_20C = 1.724e-8      # annealed copper (IACS), ohm*m at 20 C
ALPHA_CU = 0.00393      # 1/C


def copper_rho(temp_c: float) -> float:
    """Copper resistivity at temp_c (ohm*m)."""
    return RHO_20C * (1 + ALPHA_CU * (temp_c - 20.0))


def ipc2221_delta_t(current_a: float, width_mm: float, thick_um: float, outer: bool) -> float:
    """Temperature rise (C) of a track carrying current_a, from the IPC-2221 design formula."""
    if current_a <= 0:
        return 0.0
    k = 0.048 if outer else 0.024
    area_mil2 = (width_mm / 0.0254) * (thick_um / 25.4)
    return (current_a / (k * area_mil2 ** 0.725)) ** (1 / 0.44)


def parallel(resistances: list[float]) -> float:
    if any(r == 0 for r in resistances):
        return 0.0
    return 1.0 / sum(1.0 / r for r in resistances)


def key(x: float, y: float) -> tuple[float, float]:
    return round(x, 3), round(y, 3)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("board")
    parser.add_argument("--net", required=True)
    parser.add_argument("--source", required=True, help="source pad as REF.PAD, e.g. J1.1")
    parser.add_argument("--load", action="append", default=[], help="load pad and current, REF.PAD=AMPS; repeat")
    parser.add_argument("--outer-um", type=float, default=35.0, help="outer copper thickness, default 35 (1 oz)")
    parser.add_argument("--inner-um", type=float, default=17.5, help="inner copper thickness, default 17.5 (0.5 oz)")
    parser.add_argument("--temp-c", type=float, default=40.0, help="copper temperature for resistivity, default 40")
    parser.add_argument("--rho", type=float, help="override resistivity in ohm*m")
    parser.add_argument("--dt-limit", type=float, default=20.0, help="flag segments whose rise exceeds this (C)")
    args = parser.parse_args()

    import pcbnew  # imported here so the math above can be tested without KiCad

    rho = args.rho if args.rho else copper_rho(args.temp_c)
    board = pcbnew.LoadBoard(args.board)
    tracks = []
    for t in board.GetTracks():
        if t.GetNetname() != args.net or t.GetClass() not in ("PCB_TRACK", "PCB_ARC"):
            continue
        a, b = t.GetStart(), t.GetEnd()
        outer = t.GetLayer() in (pcbnew.F_Cu, pcbnew.B_Cu)
        tracks.append({
            "a": key(pcbnew.ToMM(a.x), pcbnew.ToMM(a.y)),
            "b": key(pcbnew.ToMM(b.x), pcbnew.ToMM(b.y)),
            "arc": t.GetClass() == "PCB_ARC",
            "length": pcbnew.ToMM(t.GetLength()),
            "width": pcbnew.ToMM(t.GetWidth()),
            "thick": args.outer_um if outer else args.inner_um,
            "outer": outer,
            "layer": board.GetLayerName(t.GetLayer()),
        })
    if not tracks:
        raise SystemExit(f"net {args.net} has no tracks")

    ends = {t[e] for t in tracks for e in ("a", "b")}
    links = defaultdict(list)   # frozenset({u, v}) -> list of segment dicts (with resistance)
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

    pads = {}
    for fp in board.GetFootprints():
        for p in fp.Pads():
            if p.GetNetname() == args.net:
                pads[f"{fp.GetReference()}.{p.GetNumber()}"] = p
    nodes = {n for pair in links for n in pair}
    for p in pads.values():
        centre = key(pcbnew.ToMM(p.GetPosition().x), pcbnew.ToMM(p.GetPosition().y))
        for n in nodes:
            if n != centre and p.HitTest(pcbnew.VECTOR2I(pcbnew.FromMM(n[0]), pcbnew.FromMM(n[1]))):
                links[frozenset((centre, n))].append({"r": 0.0})

    graph = defaultdict(list)
    for pair, segs in links.items():
        u, v = tuple(pair)
        r = parallel([s["r"] for s in segs])
        graph[u].append((v, r))
        graph[v].append((u, r))

    def node(name: str):
        if name not in pads:
            raise SystemExit(f"{name} is not a pad on net {args.net} (use REF.PAD)")
        p = pads[name]
        return key(pcbnew.ToMM(p.GetPosition().x), pcbnew.ToMM(p.GetPosition().y))

    src = node(args.source)
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

    loads = {}
    for item in args.load:
        name, _, amps = item.partition("=")
        loads[name] = float(amps)
    current = defaultdict(float)   # frozenset pair -> current through the link
    for name, amps in loads.items():
        v = node(name)
        if v not in dist:
            raise SystemExit(f"{name} is not connected to {args.source} by tracks")
        while v != src:
            current[frozenset((prev[v], v))] += amps
            v = prev[v]

    def link_heat(pair):
        """Hottest member of a link: (delta T, segment) with current split by conductance."""
        segs = [s for s in links[pair] if s["r"] > 0]
        r_par = parallel([s["r"] for s in links[pair]])
        best = (0.0, None)
        for s in segs:
            amps = current[pair] * (r_par / s["r"]) if r_par > 0 else 0.0
            dt = ipc2221_delta_t(amps, s["width"], s["thick"], s["outer"])
            best = max(best, (dt, dict(s, amps=amps)), key=lambda x: x[0])
        return best

    total_len = defaultdict(float)
    for t in tracks:
        total_len[t["layer"]] += t["length"]
    print(f"net {args.net}: tracks " + ", ".join(f"{k} {v:.0f} mm" for k, v in sorted(total_len.items()))
          + f"; copper outer {args.outer_um} um / inner {args.inner_um} um; rho {rho:.3e} ohm*m"
          + (f" ({args.temp_c:g} C)" if not args.rho else "") + f"; total load {sum(loads.values()):.3f} A")
    print(f"{'load':18s}{'path mOhm':>10s}{'drop mV':>9s}{'max dT C':>10s}")
    hottest = (0.0, None)
    for name in loads:
        v, drop, worst = node(name), 0.0, (0.0, None)
        while v != src:
            pair = frozenset((prev[v], v))
            drop += parallel([s["r"] for s in links[pair]]) * current[pair]
            worst = max(worst, link_heat(pair), key=lambda x: x[0])
            v = prev[v]
        hottest = max(hottest, worst, key=lambda x: x[0])
        print(f"{name:18s}{dist[node(name)] * 1e3:10.1f}{drop * 1e3:9.1f}{worst[0]:10.1f}")
    if hottest[1]:
        s = hottest[1]
        flag = "  ABOVE LIMIT" if hottest[0] > args.dt_limit else ""
        print(f"hottest segment: {s['layer']} {s['width']:.2f} mm, {s['thick']:g} um, {s['amps']:.2f} A"
              f" -> dT {hottest[0]:.1f} C (IPC-2221, limit {args.dt_limit:g} C){flag}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
