"""Wiring plan -> KiCad schematic, and the netlist back from KiCad.

A design is a list of parts. Each part names a symbol (a box with numbered pins), a footprint,
and the net on each pin (None = not connected). `write_schematic` draws one flat sheet: every
pin gets a short wire and a global label with its net name, or a no-connect flag. All pins are
passive, so ERC has no power-driver rules to satisfy, and labels make the wiring plan readable
pin by pin.

`read_netlist` runs `kicad-cli sch export netlist` and returns KiCad's own view of the nets and
symbol paths; `check_against_design` compares it with the plan. The board is then built from
that netlist, the way KiCad's "Update PCB from schematic" does, so schematic parity holds.
"""
from __future__ import annotations

import json
import tempfile
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple, Union

from . import kicad_cli
from .footprints import fmt, stable_uuid
from .sexpr import Node, QStr, dumps, load

GRID = 1.27
PIN_STEP = 2.54
PIN_LEN = 2.54
STUB = 2.54
PathLike = Union[str, Path]


def snap(value: float, grid: float = GRID) -> float:
    return round(round(value / grid) * grid, 4)


@dataclass
class SymbolDef:
    """A rectangular symbol. left / right: pin numbers top to bottom on each side."""
    name: str
    pins: Dict[str, str]                 # number -> pin name ("" for none)
    left: List[str]
    right: List[str] = field(default_factory=list)
    width: float = 10.16
    prefix: str = "U"
    description: str = ""

    @property
    def rows(self) -> int:
        return max(len(self.left), len(self.right), 1)

    @property
    def top(self) -> float:
        return snap((self.rows - 1) * PIN_STEP / 2)

    def pin_points(self) -> Dict[str, Tuple[float, float, int]]:
        """number -> (x, y, side) in symbol coordinates (y up); side -1 left, +1 right."""
        out = {}
        half = snap(self.width / 2)
        for side, numbers in ((-1, self.left), (1, self.right)):
            for i, number in enumerate(numbers):
                out[number] = (side * (half + PIN_LEN), round(self.top - i * PIN_STEP, 4), side)
        return out

    def size(self) -> Tuple[float, float]:
        return self.width + 2 * PIN_LEN, self.rows * PIN_STEP


@dataclass
class Part:
    ref: str
    value: str
    symbol: str
    footprint: str
    pins: Dict[str, Optional[str]]       # pin number -> net (None: not connected)
    fields: Dict[str, str] = field(default_factory=dict)   # Silk, Description, Datasheet ...
    group: str = ""
    dnp: bool = False


@dataclass
class Design:
    project: str
    title: str
    revision: str
    date: str
    library: str                         # symbol library nickname
    symbols: Dict[str, SymbolDef]
    parts: List[Part]
    notes: List[str] = field(default_factory=list)
    paper: str = "A2"

    def part(self, ref: str) -> Part:
        return next(p for p in self.parts if p.ref == ref)

    def nets(self) -> Dict[str, List[Tuple[str, str]]]:
        out: Dict[str, List[Tuple[str, str]]] = defaultdict(list)
        for p in self.parts:
            for number, net in p.pins.items():
                if net:
                    out[net].append((p.ref, number))
        return dict(out)

    def problems(self) -> List[str]:
        """Plan errors found before drawing anything."""
        issues = []
        refs = Counter(p.ref for p in self.parts)
        issues += [f"duplicate reference {r}" for r, n in refs.items() if n > 1]
        for p in self.parts:
            sym = self.symbols.get(p.symbol)
            if sym is None:
                issues.append(f"{p.ref}: unknown symbol {p.symbol}")
                continue
            missing = set(sym.pins) - set(p.pins)
            extra = set(p.pins) - set(sym.pins)
            if missing:
                issues.append(f"{p.ref}: pins without a net or None: {sorted(missing, key=_num)}")
            if extra:
                issues.append(f"{p.ref}: pins not in symbol {p.symbol}: {sorted(extra, key=_num)}")
        for net, nodes in self.nets().items():
            if len(nodes) < 2:
                issues.append(f"net {net} has only one pin ({nodes[0][0]}.{nodes[0][1]}); use None for no connection")
        return issues


def _num(text: str):
    try:
        return (0, int(text))
    except ValueError:
        return (1, text)


# ---------------------------------------------------------------- s-expression builders

def _font(size: float = 1.27) -> Node:
    return Node(["font", Node(["size", fmt(size), fmt(size)])])


def _effects(size: float = 1.27, hide: bool = False, justify: Optional[str] = None) -> Node:
    node = Node(["effects", _font(size)])
    if justify:
        node.append(Node(["justify", justify]))
    if hide:
        node.append(Node(["hide", "yes"]))
    return node


def _prop(name: str, value: str, at: Tuple[float, float], hide: bool = False, angle: float = 0.0) -> Node:
    return Node(["property", QStr(name), QStr(value), Node(["at", fmt(at[0]), fmt(at[1]), fmt(angle)]),
                 _effects(hide=hide)])


def _stroke(width: float = 0.254) -> Node:
    return Node(["stroke", Node(["width", fmt(width)]), Node(["type", "default"])])


def symbol_node(sym: SymbolDef, full_name: str) -> Node:
    """The library definition of a symbol (used in lib_symbols and in the .kicad_sym file)."""
    w, h = sym.size()
    half = snap(sym.width / 2)
    top = sym.top + PIN_STEP / 2
    bottom = sym.top - (sym.rows - 1) * PIN_STEP - PIN_STEP / 2
    short = full_name.split(":")[-1]
    body = Node(["symbol", QStr(f"{short}_0_1"),
                 Node(["rectangle", Node(["start", fmt(-half), fmt(top)]), Node(["end", fmt(half), fmt(bottom)]),
                       _stroke(), Node(["fill", Node(["type", "background"])])])])
    pins = Node(["symbol", QStr(f"{short}_1_1")])
    for number, (x, y, side) in sym.pin_points().items():
        pins.append(Node(["pin", "passive", "line", Node(["at", fmt(x), fmt(y), "0" if side < 0 else "180"]),
                          Node(["length", fmt(PIN_LEN)]),
                          Node(["name", QStr(sym.pins[number] or "~"), _effects(1.0)]),
                          Node(["number", QStr(number), _effects(1.0)])]))
    return Node(["symbol", QStr(full_name),
                 Node(["pin_names", Node(["offset", "0.508"])]),
                 Node(["exclude_from_sim", "no"]), Node(["in_bom", "yes"]), Node(["on_board", "yes"]),
                 _prop("Reference", sym.prefix, (0, top + 1.27)),
                 _prop("Value", sym.name, (0, bottom - 1.27)),
                 _prop("Footprint", "", (0, 0), hide=True),
                 _prop("Datasheet", "", (0, 0), hide=True),
                 _prop("Description", sym.description, (0, 0), hide=True),
                 body, pins, Node(["embedded_fonts", "no"])])


def write_symbol_library(design: Design, path: PathLike) -> Path:
    lib = Node(["kicad_symbol_lib", Node(["version", "20241209"]), Node(["generator", QStr("kcp")]),
                Node(["generator_version", QStr("10.0")])])
    for name in sorted({p.symbol for p in design.parts}):
        lib.append(symbol_node(design.symbols[name], name))
    path = Path(path)
    path.write_text(dumps(lib, indent="  "), encoding="utf-8", newline="\n")
    return path


def write_lib_tables(folder: PathLike, symbol_libs: Dict[str, str], footprint_libs: Dict[str, str]) -> None:
    """Project sym-lib-table and fp-lib-table; values are paths relative to the project folder."""
    folder = Path(folder)
    for table, libs in (("sym_lib_table", symbol_libs), ("fp_lib_table", footprint_libs)):
        lines = [f"({table}", "  (version 7)"]
        for nick, rel in libs.items():
            lines.append(f'  (lib (name "{nick}")(type "KiCad")(uri "${{KIPRJMOD}}/{rel}")(options "")(descr ""))')
        lines.append(")")
        name = "sym-lib-table" if table == "sym_lib_table" else "fp-lib-table"
        (folder / name).write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def _label_length(net: str) -> float:
    return 1.27 * 0.75 * len(net) + 4.0


def _layout(design: Design, page: Tuple[float, float]) -> Dict[str, Tuple[float, float]]:
    """Flow the parts into columns, group by group, top to bottom then left to right."""
    margin, gap = 25.4, 7.62
    positions = {}
    x, y = margin, margin
    column_width = 0.0
    for part in design.parts:
        sym = design.symbols[part.symbol]
        w, h = sym.size()
        nets = [n for n in part.pins.values() if n]
        label = max((_label_length(n) for n in nets), default=0.0) + STUB
        total_w = w + 2 * label
        total_h = h + 2 * PIN_STEP + 5.08
        if y + total_h > page[1] - margin and y > margin:
            x += column_width + gap
            y = margin
            column_width = 0.0
        cx = snap(x + total_w / 2, PIN_STEP)
        cy = snap(y + 2 * PIN_STEP + sym.top + PIN_STEP / 2, PIN_STEP)
        positions[part.ref] = (cx, cy)
        y += total_h
        column_width = max(column_width, total_w)
    return positions


PAPERS = {"A4": (297.0, 210.0), "A3": (420.0, 297.0), "A2": (594.0, 420.0), "A1": (841.0, 594.0)}


def write_schematic(design: Design, path: PathLike) -> Dict[str, object]:
    """Write the flat schematic. Returns {root_uuid, symbol_uuids: {ref: uuid}}."""
    problems = design.problems()
    if problems:
        raise ValueError("wiring plan has problems:\n  " + "\n  ".join(problems))
    path = Path(path)
    root_uuid = stable_uuid(design.project, "root")
    page = PAPERS[design.paper]
    sch = Node(["kicad_sch", Node(["version", "20250114"]), Node(["generator", QStr("kcp")]),
                Node(["generator_version", QStr("10.0")]), Node(["uuid", QStr(root_uuid)]),
                Node(["paper", QStr(design.paper)]),
                Node(["title_block", Node(["title", QStr(design.title)]), Node(["date", QStr(design.date)]),
                      Node(["rev", QStr(design.revision)])])])
    lib_symbols = Node(["lib_symbols"])
    used = sorted({p.symbol for p in design.parts})
    for name in used:
        lib_symbols.append(symbol_node(design.symbols[name], f"{design.library}:{name}"))
    sch.append(lib_symbols)

    positions = _layout(design, page)
    symbol_uuids = {}
    for part in design.parts:
        sym = design.symbols[part.symbol]
        sx, sy = positions[part.ref]
        uid = stable_uuid(design.project, "symbol", part.ref)
        symbol_uuids[part.ref] = uid
        top = sym.top + PIN_STEP / 2
        bottom = sym.top - (sym.rows - 1) * PIN_STEP - PIN_STEP / 2
        node = Node(["symbol", Node(["lib_id", QStr(f"{design.library}:{part.symbol}")]),
                     Node(["at", fmt(sx), fmt(sy), "0"]), Node(["unit", "1"]),
                     Node(["exclude_from_sim", "no"]), Node(["in_bom", "yes"]), Node(["on_board", "yes"]),
                     Node(["dnp", "yes" if part.dnp else "no"]), Node(["uuid", QStr(uid)]),
                     _prop("Reference", part.ref, (sx, snap(sy - top - 1.27))),
                     _prop("Value", part.value, (sx, snap(sy - bottom + 1.27))),
                     _prop("Footprint", part.footprint, (sx, sy), hide=True),
                     _prop("Datasheet", part.fields.get("Datasheet", ""), (sx, sy), hide=True),
                     _prop("Description", part.fields.get("Description", sym.description), (sx, sy), hide=True)])
        for name, value in part.fields.items():
            if name not in ("Datasheet", "Description"):
                node.append(_prop(name, value, (sx, sy), hide=True))
        for number in sorted(sym.pins, key=_num):
            node.append(Node(["pin", QStr(number), Node(["uuid", QStr(stable_uuid(uid, "pin", number))])]))
        node.append(Node(["instances", Node(["project", QStr(design.project),
                                             Node(["path", QStr(f"/{root_uuid}"), Node(["reference", QStr(part.ref)]),
                                                   Node(["unit", "1"])])])]))
        sch.append(node)
        for number, (px, py, side) in sym.pin_points().items():
            point = (round(sx + px, 4), round(sy - py, 4))
            net = part.pins.get(number)
            if not net:
                sch.append(Node(["no_connect", Node(["at", fmt(point[0]), fmt(point[1])]),
                                 Node(["uuid", QStr(stable_uuid(uid, "nc", number))])]))
                continue
            end = (round(point[0] + side * STUB, 4), point[1])
            sch.append(Node(["wire", Node(["pts", Node(["xy", fmt(point[0]), fmt(point[1])]),
                                           Node(["xy", fmt(end[0]), fmt(end[1])])]),
                             _stroke(0), Node(["uuid", QStr(stable_uuid(uid, "wire", number))])]))
            sch.append(Node(["global_label", QStr(net), Node(["shape", "passive"]),
                             Node(["at", fmt(end[0]), fmt(end[1]), "180" if side < 0 else "0"]),
                             Node(["fields_autoplaced", "yes"]),
                             _effects(1.27, justify="right" if side < 0 else "left"),
                             Node(["uuid", QStr(stable_uuid(uid, "label", number))]),
                             Node(["property", QStr("Intersheetrefs"), QStr("${INTERSHEET_REFS}"),
                                   Node(["at", fmt(end[0]), fmt(end[1]), "0"]), _effects(1.27, hide=True)])]))
    y = page[1] - 12.7 - 5.08 * len(design.notes)
    for i, note in enumerate(design.notes):
        sch.append(Node(["text", QStr(note), Node(["exclude_from_sim", "no"]),
                         Node(["at", fmt(25.4), fmt(snap(y + 5.08 * i)), "0"]),
                         _effects(1.5, justify="left"), Node(["uuid", QStr(stable_uuid(design.project, "note", i))])]))
    sch.append(Node(["sheet_instances", Node(["path", QStr("/"), Node(["page", QStr("1")])])]))
    sch.append(Node(["embedded_fonts", "no"]))
    path.write_text(dumps(sch, indent="  "), encoding="utf-8", newline="\n")
    return {"root_uuid": root_uuid, "symbol_uuids": symbol_uuids}


# ---------------------------------------------------------------- netlist back from KiCad

@dataclass
class NetlistComponent:
    ref: str
    value: str
    footprint: str
    fields: Dict[str, str]
    path: str                            # footprint path for the board: sheet tstamps + symbol tstamp


def read_netlist(schematic: PathLike) -> Tuple[Dict[str, NetlistComponent], Dict[Tuple[str, str], str]]:
    """(components by reference, {(ref, pin): net}) from kicad-cli's netlist export."""
    schematic = Path(schematic).resolve()
    with tempfile.TemporaryDirectory(prefix="kcp_net_") as tmp:
        out = Path(tmp) / "netlist.net"
        result = kicad_cli.run(["sch", "export", "netlist", "--format", "kicadsexpr", "--output", str(out),
                                str(schematic)])
        if not out.is_file():
            raise kicad_cli.KiCadCliError(f"netlist export failed: {(result.stderr or result.stdout).strip()}")
        tree = load(out)
    components = {}
    comps = tree.get("components")
    for comp in comps.all("comp") if comps is not None else []:
        ref = comp.value("ref", "") or ""
        fields = {}
        fields_node = comp.get("fields")
        if fields_node is not None:
            for f in fields_node.all("field"):
                name = f.value("name", "")
                atoms = [a for a in f[1:] if not isinstance(a, Node)]
                fields[str(name)] = str(atoms[-1]) if atoms else ""
        for prop in comp.all("property"):
            name, value = prop.value("name"), prop.value("value")
            if name and value is not None and name not in ("Sheetname", "Sheetfile"):
                fields.setdefault(str(name), str(value))
        sheet = comp.get("sheetpath")
        sheet_tstamps = (sheet.value("tstamps", "/") if sheet is not None else "/") or "/"
        tstamp = comp.value("tstamps", "") or comp.value("tstamp", "") or ""
        if not sheet_tstamps.endswith("/"):
            sheet_tstamps += "/"
        components[ref] = NetlistComponent(ref, comp.value("value", "") or "", comp.value("footprint", "") or "",
                                           fields, sheet_tstamps + tstamp)
    pins: Dict[Tuple[str, str], str] = {}
    nets = tree.get("nets")
    for net in nets.all("net") if nets is not None else []:
        name = net.value("name", "") or ""
        for node in net.all("node"):
            pins[(node.value("ref", "") or "", node.value("pin", "") or "")] = name
    return components, pins


def check_against_design(design: Design, components: Dict[str, NetlistComponent],
                         pins: Dict[Tuple[str, str], str]) -> List[str]:
    """Differences between the wiring plan and KiCad's netlist. Empty list = they agree."""
    issues = []
    for part in design.parts:
        comp = components.get(part.ref)
        if comp is None:
            issues.append(f"{part.ref} missing from the netlist")
            continue
        if comp.footprint != part.footprint:
            issues.append(f"{part.ref}: footprint {comp.footprint} != {part.footprint}")
        for number, net in part.pins.items():
            got = pins.get((part.ref, number))
            if net and got != net:
                issues.append(f"{part.ref}.{number}: netlist {got!r}, plan {net!r}")
            if not net and got and not got.startswith("unconnected-"):
                issues.append(f"{part.ref}.{number}: should be unconnected, netlist has {got!r}")
    extra = set(components) - {p.ref for p in design.parts}
    issues += [f"{ref} in the netlist but not in the plan" for ref in sorted(extra)]
    return issues


def bom_rows(design: Design) -> List[Dict[str, str]]:
    groups: Dict[Tuple[str, str], List[str]] = defaultdict(list)
    for p in design.parts:
        if not p.dnp:
            groups[(p.value, p.footprint)].append(p.ref)
    return [{"refs": " ".join(sorted(refs, key=lambda r: (len(r), r))), "qty": str(len(refs)),
             "value": value, "footprint": fp} for (value, fp), refs in sorted(groups.items())]
