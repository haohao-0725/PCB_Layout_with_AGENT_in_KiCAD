"""`kcp inspect`: the board as JSON, so an agent can read it instead of guessing.

Outline and size, layers and stackup; footprints with position, rotation, side, courtyard box and
pads (number, net, position, shape, size, drill); nets with netclass, pad count and routing stats;
track, via and zone statistics; unconnected items from a kicad-cli DRC run (optional, ~15 s).

(Named `inspection` so it never shadows the standard-library `inspect` module.)
"""
from __future__ import annotations

from collections import Counter, defaultdict
from typing import Dict, Iterable, List, Optional

from .geometry import bbox_of
from .model import Board, Footprint


def _r(value: Optional[float], digits: int = 4) -> Optional[float]:
    return None if value is None else round(value, digits)


def _box(box) -> Optional[List[float]]:
    return None if box is None else [_r(v) for v in box]


def footprint_info(fp: Footprint, pads: bool = True) -> Dict:
    info = {
        "ref": fp.ref, "value": fp.value, "lib_id": fp.lib_id,
        "x": _r(fp.at[0]), "y": _r(fp.at[1]), "rot": _r(fp.angle, 3), "side": fp.side,
        "attributes": fp.attributes, "dnp": fp.dnp,
        "courtyard_bbox": _box(fp.courtyard_bbox()),
        "pad_count": len(fp.pads),
    }
    silk = fp.properties.get("Silk")
    if silk:
        info["silk"] = silk
    if pads:
        info["pads"] = [{
            "number": p.number, "net": p.net, "x": _r(p.at[0]), "y": _r(p.at[1]), "rot": _r(p.angle, 3),
            "type": p.kind, "shape": p.shape_name, "size": [_r(p.size[0]), _r(p.size[1])],
            "drill": None if p.drill is None else ([_r(p.drill[0])] if p.drill[0] == p.drill[1]
                                                   else [_r(p.drill[0]), _r(p.drill[1])]),
        } for p in fp.pads]
    return info


def inspect_board(board: Board, pads: bool = True, refs: Optional[Iterable[str]] = None,
                  drc: Optional[Dict] = None, summary: bool = False) -> Dict:
    box = board.outline_bbox()
    wanted = set(refs) if refs else None
    pad_count: Counter = Counter(p.net for p in board.pads if p.net)
    segs: Counter = Counter()
    length: Dict[str, float] = defaultdict(float)
    for t in board.tracks:
        segs[t.net] += 1
        length[t.net] += t.length
    via_count: Counter = Counter(v.net for v in board.vias)
    zone_nets: Counter = Counter(z.net for z in board.zones if not z.rule_area)
    unconnected = (drc or {}).get("unconnected_by_net", {})

    nets = []
    for name in board.nets():
        entry = {
            "name": name, "netclass": board.netclasses.of(name), "pads": pad_count[name],
            "segments": segs[name], "length_mm": _r(length[name], 2), "vias": via_count[name],
            "zones": zone_nets[name],
        }
        if drc is not None:
            entry["unconnected"] = unconnected.get(name, 0)
            entry["routed"] = entry["pads"] < 2 or entry["unconnected"] == 0
        nets.append(entry)

    by_layer: Dict[str, Dict] = {}
    for t in board.tracks:
        layer = by_layer.setdefault(t.layer, {"segments": 0, "arcs": 0, "length_mm": 0.0, "widths": Counter()})
        layer["arcs" if t.kind == "arc" else "segments"] += 1
        layer["length_mm"] += t.length
        layer["widths"][f"{t.width:g}"] += 1
    for layer in by_layer.values():
        layer["length_mm"] = _r(layer["length_mm"], 2)
        layer["widths"] = dict(sorted(layer["widths"].items(), key=lambda kv: float(kv[0])))

    netclasses = {}
    for net in nets:
        nc = board.netclasses.get(net["netclass"])
        netclasses.setdefault(net["netclass"], {
            "nets": 0, "track_width": nc.track_width if nc else None, "clearance": nc.clearance if nc else None,
            "via_diameter": nc.via_diameter if nc else None, "via_drill": nc.via_drill if nc else None})
        netclasses[net["netclass"]]["nets"] += 1

    result = {
        "tool": "kcp inspect",
        "file": str(board.path) if board.path else None,
        "board": {
            "format_version": board.format_version, "kicad_version": board.generator_version,
            "outline_bbox": _box(box),
            "size_mm": [_r(box[2] - box[0], 3), _r(box[3] - box[1], 3)] if box else None,
            "thickness_mm": board.thickness,
            "copper_layers": board.copper_layers,
            "layers": [l["name"] for l in board.layers],
            "stackup": board.stackup,
        },
        "counts": {
            "footprints": len(board.footprints), "pads": len(board.pads), "nets": len(nets),
            "segments": sum(1 for t in board.tracks if t.kind == "segment"),
            "arcs": sum(1 for t in board.tracks if t.kind == "arc"),
            "track_length_mm": _r(sum(t.length for t in board.tracks), 2),
            "vias": len(board.vias),
            "zones": sum(1 for z in board.zones if not z.rule_area),
            "rule_areas": sum(1 for z in board.zones if z.rule_area),
        },
        "netclasses": netclasses,
        "tracks_by_layer": by_layer,
        "vias": {
            "by_size": dict(Counter(f"{v.size:g}/{v.drill:g}" for v in board.vias)),
            "by_type": dict(Counter(v.via_type for v in board.vias)),
        },
        "zones": [{
            "net": z.net, "layers": z.layers, "name": z.name, "rule_area": z.rule_area, "priority": z.priority,
            "outline_bbox": _box(bbox_of(z.outline)), "filled_area_mm2": _r(z.filled_area(), 1),
        } for z in board.zones],
        "drc": drc,
    }
    if summary:
        result["footprints"] = [{"ref": fp.ref, "value": fp.value, "x": _r(fp.at[0]), "y": _r(fp.at[1]),
                                 "rot": _r(fp.angle, 3), "side": fp.side} for fp in board.footprints
                                if wanted is None or fp.ref in wanted]
        result["nets"] = [n for n in nets if n["pads"] >= 2]
    else:
        result["footprints"] = [footprint_info(fp, pads) for fp in board.footprints
                                if wanted is None or fp.ref in wanted]
        result["nets"] = nets
    return result


def to_markdown(data: Dict) -> str:
    b, c = data["board"], data["counts"]
    size = b["size_mm"]
    lines = [f"# Board: {data.get('file') or ''}", "",
             "| Item | Value |", "|---|---|",
             f"| Size | {size[0]:g} × {size[1]:g} mm |" if size else "| Size | no Edge.Cuts outline |",
             f"| Copper layers | {len(b['copper_layers'])}: {', '.join(b['copper_layers'])} |",
             f"| Thickness | {b['thickness_mm']} mm |",
             f"| Footprints / pads / nets | {c['footprints']} / {c['pads']} / {c['nets']} |",
             f"| Segments / arcs / length | {c['segments']} / {c['arcs']} / {c['track_length_mm']:g} mm |",
             f"| Vias | {c['vias']} |",
             f"| Zones (rule areas) | {c['zones']} ({c['rule_areas']}) |"]
    if data.get("drc"):
        d = data["drc"]
        lines.append(f"| DRC | {d['violations']} violations, {d['unconnected']} unconnected |")
    lines += ["", "## Tracks by layer", "", "| Layer | Segments | Arcs | Length (mm) | Widths (mm: count) |",
              "|---|---:|---:|---:|---|"]
    for name, layer in data["tracks_by_layer"].items():
        widths = ", ".join(f"{w}: {n}" for w, n in layer["widths"].items())
        lines.append(f"| {name} | {layer['segments']} | {layer['arcs']} | {layer['length_mm']:g} | {widths} |")
    if data["zones"]:
        lines += ["", "## Zones", "", "| Net | Layers | Name | Rule area | Filled area (mm²) |", "|---|---|---|---|---:|"]
        for z in data["zones"]:
            lines.append(f"| {z['net']} | {', '.join(z['layers'])} | {z['name']} | {'yes' if z['rule_area'] else 'no'} "
                         f"| {z['filled_area_mm2']:g} |")
    lines += ["", "## Footprints", "", "| Ref | Value | Footprint | x | y | Rot | Side |", "|---|---|---|---:|---:|---:|---|"]
    for fp in data["footprints"]:
        lines.append(f"| {fp['ref']} | {fp['value']} | {fp.get('lib_id', '')} | {fp['x']:g} | {fp['y']:g} "
                     f"| {fp['rot']:g} | {fp['side']} |")
    lines += ["", "## Nets", "", "| Net | Class | Pads | Segments | Length (mm) | Vias |"
              + (" Unconnected |" if data.get("drc") else ""),
              "|---|---|---:|---:|---:|---:|" + ("---:|" if data.get("drc") else "")]
    for n in data["nets"]:
        row = f"| {n['name']} | {n['netclass']} | {n['pads']} | {n['segments']} | {n['length_mm']:g} | {n['vias']} |"
        if data.get("drc"):
            row += f" {n.get('unconnected', '')} |"
        lines.append(row)
    return "\n".join(lines) + "\n"
