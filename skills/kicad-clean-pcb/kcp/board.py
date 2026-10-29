"""Build and edit a .kicad_pcb tree directly (file backend), without pcbnew.

    b = BoardBuilder.new(copper=4, thickness=1.6, title="My board")
    b.outline_rect(0, 0, 100, 80)
    b.add_footprint(node)                      # from footprints.place_footprint
    b.add_track((0, 0), (10, 0), 0.3, "F.Cu", "SIG")
    b.add_zone("GND", ["In1.Cu"], [(0, 0), (100, 0), (100, 80), (0, 80)])
    b.save("board.kicad_pcb")                  # refuses while KiCad has the project open

Zones are written unfilled; `kicad-cli pcb drc --refill-zones --save-board` fills them and saves
the board in KiCad's own formatting.
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple, Union

from .backends.file import save_tree
from .footprints import fmt, stable_uuid
from .model import Board, board_from_tree, NetClasses
from .sexpr import Node, QStr, load

Point = Tuple[float, float]
PathLike = Union[str, Path]

USER_LAYERS = [
    (9, "F.Adhes", "user", "F.Adhesive"), (11, "B.Adhes", "user", "B.Adhesive"),
    (13, "F.Paste", "user", None), (15, "B.Paste", "user", None),
    (5, "F.SilkS", "user", "F.Silkscreen"), (7, "B.SilkS", "user", "B.Silkscreen"),
    (1, "F.Mask", "user", None), (3, "B.Mask", "user", None),
    (17, "Dwgs.User", "user", "User.Drawings"), (19, "Cmts.User", "user", "User.Comments"),
    (21, "Eco1.User", "user", "User.Eco1"), (23, "Eco2.User", "user", "User.Eco2"),
    (25, "Edge.Cuts", "user", None), (27, "Margin", "user", None),
    (31, "F.CrtYd", "user", "F.Courtyard"), (29, "B.CrtYd", "user", "B.Courtyard"),
    (35, "F.Fab", "user", None), (33, "B.Fab", "user", None),
]


def copper_names(copper: int) -> List[str]:
    return ["F.Cu"] + [f"In{i}.Cu" for i in range(1, copper - 1)] + ["B.Cu"]


def _copper_ids(copper: int) -> List[int]:
    # KiCad 9+ numbering: F.Cu 0, B.Cu 2, In1.Cu 4, In2.Cu 6, ...
    return [0] + [4 + 2 * (i - 1) for i in range(1, copper - 1)] + [2]


def _stackup(copper: int, thickness: float, outer_cu: float, inner_cu: float) -> Node:
    names = copper_names(copper)
    cu_total = 2 * outer_cu + (copper - 2) * inner_cu
    dielectric = (thickness - cu_total - 0.02) / (copper - 1)
    stack = Node(["stackup",
                  Node(["layer", QStr("F.SilkS"), Node(["type", QStr("Top Silk Screen")])]),
                  Node(["layer", QStr("F.Mask"), Node(["type", QStr("Top Solder Mask")]), Node(["thickness", "0.01"])])])
    for i, name in enumerate(names):
        cu = outer_cu if name in ("F.Cu", "B.Cu") else inner_cu
        stack.append(Node(["layer", QStr(name), Node(["type", QStr("copper")]), Node(["thickness", fmt(cu)])]))
        if i < len(names) - 1:
            kind = "core" if i % 2 else "prepreg"
            stack.append(Node(["layer", QStr(f"dielectric {i + 1}"), Node(["type", QStr(kind)]),
                               Node(["thickness", fmt(round(dielectric, 4))]), Node(["material", QStr("FR4")]),
                               Node(["epsilon_r", "4.5"]), Node(["loss_tangent", "0.02"])]))
    stack += [Node(["layer", QStr("B.Mask"), Node(["type", QStr("Bottom Solder Mask")]), Node(["thickness", "0.01"])]),
              Node(["layer", QStr("B.SilkS"), Node(["type", QStr("Bottom Silk Screen")])]),
              Node(["copper_finish", QStr("HAL SnPb")]), Node(["dielectric_constraints", "no"])]
    return stack


class BoardBuilder:
    def __init__(self, tree: Node):
        self.tree = tree
        self._serial = 0

    # ------------------------------------------------------------ creation

    @classmethod
    def new(cls, copper: int = 2, thickness: float = 1.6, title: str = "", revision: str = "", date: str = "",
            outer_cu: float = 0.035, inner_cu: float = 0.0175, paper: str = "A4") -> "BoardBuilder":
        if copper < 2 or copper % 2:
            raise ValueError("copper layer count must be an even number >= 2")
        layers = Node(["layers"])
        for lid, name in zip(_copper_ids(copper), copper_names(copper)):
            layers.append(Node([str(lid), QStr(name), "signal"]))
        for lid, name, kind, user in USER_LAYERS:
            layers.append(Node([str(lid), QStr(name), kind] + ([QStr(user)] if user else [])))
        title_block = Node(["title_block"])
        for key, value in (("title", title), ("date", date), ("rev", revision)):
            if value:
                title_block.append(Node([key, QStr(value)]))
        tree = Node(["kicad_pcb", Node(["version", "20260206"]), Node(["generator", QStr("pcbnew")]),
                     Node(["generator_version", QStr("10.0")]),
                     Node(["general", Node(["thickness", fmt(thickness)]), Node(["legacy_teardrops", "no"])]),
                     Node(["paper", QStr(paper)]), title_block, layers,
                     Node(["setup", _stackup(copper, thickness, outer_cu, inner_cu),
                           Node(["pad_to_mask_clearance", "0"]),
                           Node(["allow_soldermask_bridges_in_footprints", "no"]),
                           Node(["tenting", Node(["front", "yes"]), Node(["back", "yes"])])])])
        return cls(tree)

    @classmethod
    def open(cls, path: PathLike) -> "BoardBuilder":
        return cls(load(path))

    def board(self, path: Optional[PathLike] = None, netclasses: Optional[NetClasses] = None) -> Board:
        """The board model of the current tree (for inspect, lint, clearance checks)."""
        return board_from_tree(self.tree, Path(path) if path else None, netclasses)

    def save(self, path: PathLike, force: bool = False) -> Path:
        return save_tree(self.tree, path, force)

    # ------------------------------------------------------------ items

    def _uuid(self, kind: str, *key) -> QStr:
        self._serial += 1
        return QStr(stable_uuid("board", kind, *key, self._serial))

    def add_footprint(self, fp: Node) -> Node:
        self.tree.append(fp)
        return fp

    def footprints(self) -> List[Node]:
        return self.tree.all("footprint")

    def footprint(self, ref: str) -> Optional[Node]:
        for fp in self.tree.all("footprint"):
            for prop in fp.all("property"):
                if str(prop[1]) == "Reference" and str(prop[2]) == ref:
                    return fp
        return None

    def remove(self, kinds: Sequence[str], predicate=None) -> int:
        """Remove top-level items of these kinds (e.g. segment, via, zone) matching predicate(node)."""
        keep, removed = [], 0
        for item in self.tree:
            if isinstance(item, Node) and item.name in kinds and (predicate is None or predicate(item)):
                removed += 1
                continue
            keep.append(item)
        self.tree[:] = keep
        return removed

    def add_track(self, start: Point, end: Point, width: float, layer: str, net: str) -> Node:
        node = Node(["segment", Node(["start", fmt(start[0]), fmt(start[1])]),
                     Node(["end", fmt(end[0]), fmt(end[1])]), Node(["width", fmt(width)]),
                     Node(["layer", QStr(layer)]), Node(["net", QStr(net)]),
                     Node(["uuid", self._uuid("segment", net, start, end, layer)])])
        self.tree.append(node)
        return node

    def add_via(self, at: Point, net: str, size: float = 0.8, drill: float = 0.4,
                layers: Tuple[str, str] = ("F.Cu", "B.Cu")) -> Node:
        node = Node(["via", Node(["at", fmt(at[0]), fmt(at[1])]), Node(["size", fmt(size)]),
                     Node(["drill", fmt(drill)]), Node(["layers", QStr(layers[0]), QStr(layers[1])]),
                     Node(["net", QStr(net)]), Node(["uuid", self._uuid("via", net, at)])])
        self.tree.append(node)
        return node

    def add_zone(self, net: str, layers: Sequence[str], outline: Sequence[Point], name: str = "",
                 clearance: float = 0.3, min_width: float = 0.25, thermal_gap: float = 0.5,
                 spoke_width: float = 0.5, priority: int = 0) -> Node:
        layer_node = (Node(["layer", QStr(layers[0])]) if len(layers) == 1
                      else Node(["layers", *[QStr(l) for l in layers]]))
        node = Node(["zone", Node(["net", QStr(net)]), layer_node, Node(["uuid", self._uuid("zone", net, *layers)]),
                     Node(["name", QStr(name)]), Node(["hatch", "edge", "0.5"])])
        if priority:
            node.append(Node(["priority", str(priority)]))
        node += [Node(["connect_pads", Node(["clearance", fmt(clearance)])]),
                 Node(["min_thickness", fmt(min_width)]),
                 Node(["filled_areas_thickness", "no"]),
                 Node(["fill", "yes", Node(["thermal_gap", fmt(thermal_gap)]),
                       Node(["thermal_bridge_width", fmt(spoke_width)]), Node(["island_removal_mode", "0"])]),
                 Node(["polygon", Node(["pts", *[Node(["xy", fmt(x), fmt(y)]) for x, y in outline]])])]
        self.tree.append(node)
        return node

    def add_line(self, a: Point, b: Point, layer: str, width: float = 0.1) -> Node:
        node = Node(["gr_line", Node(["start", fmt(a[0]), fmt(a[1])]), Node(["end", fmt(b[0]), fmt(b[1])]),
                     Node(["stroke", Node(["width", fmt(width)]), Node(["type", "default"])]),
                     Node(["layer", QStr(layer)]), Node(["uuid", self._uuid("line", layer, a, b)])])
        self.tree.append(node)
        return node

    def add_rect(self, a: Point, b: Point, layer: str, width: float = 0.1) -> Node:
        node = Node(["gr_rect", Node(["start", fmt(a[0]), fmt(a[1])]), Node(["end", fmt(b[0]), fmt(b[1])]),
                     Node(["stroke", Node(["width", fmt(width)]), Node(["type", "default"])]),
                     Node(["fill", "no"]), Node(["layer", QStr(layer)]),
                     Node(["uuid", self._uuid("rect", layer, a, b)])])
        self.tree.append(node)
        return node

    def add_text(self, text: str, at: Point, layer: str = "F.SilkS", size: float = 1.0, thickness: float = 0.15,
                 angle: float = 0.0, justify: Optional[str] = None) -> Node:
        effects = Node(["effects", Node(["font", Node(["size", fmt(size), fmt(size)]),
                                         Node(["thickness", fmt(thickness)])])])
        if justify:
            effects.append(Node(["justify", *justify.split()]))
        node = Node(["gr_text", QStr(text), Node(["at", fmt(at[0]), fmt(at[1]), fmt(angle)]),
                     Node(["layer", QStr(layer)]), Node(["uuid", self._uuid("text", text, at)]), effects])
        self.tree.append(node)
        return node

    def outline_rect(self, x0: float, y0: float, x1: float, y1: float, corner: float = 0.0) -> None:
        """Board outline on Edge.Cuts; corner > 0 rounds the corners with arcs."""
        if corner <= 0:
            self.add_rect((x0, y0), (x1, y1), "Edge.Cuts", 0.05)
            return
        r = corner
        import math
        k = r * (1 - math.sqrt(0.5))
        segments = [((x0 + r, y0), (x1 - r, y0)), ((x1, y0 + r), (x1, y1 - r)),
                    ((x1 - r, y1), (x0 + r, y1)), ((x0, y1 - r), (x0, y0 + r))]
        for a, b in segments:
            self.add_line(a, b, "Edge.Cuts", 0.05)
        arcs = [((x1 - r, y0), (x1 - k, y0 + k), (x1, y0 + r)), ((x1, y1 - r), (x1 - k, y1 - k), (x1 - r, y1)),
                ((x0 + r, y1), (x0 + k, y1 - k), (x0, y1 - r)), ((x0, y0 + r), (x0 + k, y0 + k), (x0 + r, y0))]
        for s, m, e in arcs:
            self.tree.append(Node(["gr_arc", Node(["start", fmt(s[0]), fmt(s[1])]),
                                   Node(["mid", fmt(m[0]), fmt(m[1])]), Node(["end", fmt(e[0]), fmt(e[1])]),
                                   Node(["stroke", Node(["width", "0.05"]), Node(["type", "default"])]),
                                   Node(["layer", QStr("Edge.Cuts")]), Node(["uuid", self._uuid("arc", s)])]))

    def set_paper(self, paper: str, width: Optional[float] = None, height: Optional[float] = None) -> None:
        node = Node(["paper", QStr(paper)] + ([fmt(width), fmt(height)] if width and height else []))
        old = self.tree.get("paper")
        if old is not None:
            self.tree[self.tree.index(old)] = node
        else:
            self.tree.insert(5, node)


def translate_tree(tree: Node, dx: float, dy: float) -> None:
    """Move every top-level item by (dx, dy). Footprint children are local, so only the
    footprint's own position moves."""
    def shift(node: Node) -> None:
        for child in node.nodes():
            if child.name in ("start", "end", "mid", "center", "at", "xy") and len(child) >= 3:
                try:
                    child[1] = fmt(float(child[1]) + dx)
                    child[2] = fmt(float(child[2]) + dy)
                except ValueError:
                    pass
            elif child.name not in ("effects", "stroke", "font", "net"):
                shift(child)

    for item in tree.nodes():
        if item.name in ("footprint", "module"):
            at = item.get("at")
            if at is not None:
                at[1] = fmt(float(at[1]) + dx)
                at[2] = fmt(float(at[2]) + dy)
        elif item.name in ("segment", "arc", "via", "zone", "group", "dimension", "target", "image") \
                or item.name.startswith("gr_"):
            shift(item)
