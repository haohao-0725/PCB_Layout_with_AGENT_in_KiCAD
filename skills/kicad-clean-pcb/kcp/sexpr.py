"""Read and write KiCad s-expression files (.kicad_pcb, .kicad_sch, .kicad_mod).

A list in the file becomes a `Node` (a Python list whose first element is the head symbol):

    (segment (start 1 2) (end 3 2) (width 0.3))
    -> Node(['segment', Node(['start', '1', '2']), Node(['end', '3', '2']), Node(['width', '0.3'])])

Atoms stay text. Quoted strings are `QStr` (a `str` subclass) so they are written back with
quotes; numbers are not converted, so a read/write round trip loses nothing. Standard library only.
"""
from __future__ import annotations

import re
from typing import Iterator, List, Optional, Union


class QStr(str):
    """A string that was quoted in the source file."""

    __slots__ = ()


class SexprError(ValueError):
    pass


Atom = str


class Node(list):
    """One parenthesised list. Element 0 is the head symbol."""

    __slots__ = ()

    @property
    def name(self) -> str:
        return self[0] if self and isinstance(self[0], str) else ""

    def nodes(self) -> Iterator["Node"]:
        """Child lists, in order."""
        return (item for item in self if isinstance(item, Node))

    def atoms(self) -> List[str]:
        """Atoms after the head, in order."""
        return [item for item in self[1:] if not isinstance(item, Node)]

    def get(self, name: str) -> Optional["Node"]:
        """First child list with this head, or None."""
        for item in self:
            if isinstance(item, Node) and item and item[0] == name:
                return item
        return None

    def all(self, name: str) -> List["Node"]:
        """Every child list with this head."""
        return [item for item in self if isinstance(item, Node) and item and item[0] == name]

    def value(self, name: str, default: Optional[str] = None, index: int = 1) -> Optional[str]:
        """Atom `index` of the first child list called `name`: (width 0.3) -> '0.3'."""
        child = self.get(name)
        if child is None or len(child) <= index or isinstance(child[index], Node):
            return default
        return child[index]

    def number(self, name: str, default: Optional[float] = None, index: int = 1) -> Optional[float]:
        text = self.value(name, None, index)
        if text is None:
            return default
        try:
            return float(text)
        except ValueError:
            return default

    def numbers(self, name: str) -> List[float]:
        """All numeric atoms of the first child list called `name`: (at 1 2 90) -> [1, 2, 90]."""
        child = self.get(name)
        if child is None:
            return []
        out = []
        for item in child[1:]:
            if isinstance(item, Node):
                continue
            try:
                out.append(float(item))
            except ValueError:
                pass
        return out

    def flag(self, token: str) -> bool:
        """True when `token` appears as a bare atom, or as (token yes)."""
        for item in self[1:]:
            if isinstance(item, Node):
                if item and item[0] == token and (len(item) == 1 or item[1] in ("yes", "true")):
                    return True
            elif item == token and not isinstance(item, QStr):
                return True
        return False


_TOKEN = re.compile(r'\s*(?:(\()|(\))|"((?:[^"\\]|\\.)*)"|([^\s()"]+))', re.S)
_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", "\\": "\\", '"': '"'}


def _unescape(text: str) -> str:
    if "\\" not in text:
        return text
    return re.sub(r"\\(.)", lambda m: _ESCAPES.get(m.group(1), m.group(1)), text)


def loads(text: str) -> Node:
    """Parse one top-level s-expression."""
    stack: List[Node] = []
    root: Optional[Node] = None
    pos, end = 0, len(text)
    match = _TOKEN.match
    while pos < end:
        m = match(text, pos)
        if m is None:
            if text[pos:].strip() == "":
                break
            line = text.count("\n", 0, pos) + 1
            raise SexprError(f"unexpected text at line {line}: {text[pos:pos + 30]!r}")
        pos = m.end()
        if m.group(1):
            node = Node()
            if stack:
                stack[-1].append(node)
            elif root is not None:
                raise SexprError("more than one top-level expression")
            else:
                root = node
            stack.append(node)
        elif m.group(2):
            if not stack:
                raise SexprError("unbalanced ')'")
            stack.pop()
        elif not stack:
            raise SexprError("atom outside any list")
        elif m.group(3) is not None:
            stack[-1].append(QStr(_unescape(m.group(3))))
        else:
            stack[-1].append(m.group(4))
    if stack:
        raise SexprError("unbalanced '(': file ends inside a list")
    if root is None:
        raise SexprError("empty file")
    return root


def load(path) -> Node:
    with open(path, encoding="utf-8") as handle:
        return loads(handle.read())


def _atom(item: str) -> str:
    if isinstance(item, QStr) or item == "" or re.search(r'[\s()"]', item):
        escaped = item.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
        return f'"{escaped}"'
    return item


def _is_flat(node: Node) -> bool:
    return not any(isinstance(item, Node) for item in node)


def _flat(node: Node) -> str:
    return "(" + " ".join(_atom(item) for item in node) + ")"


def dumps(node: Node, indent: str = "\t", width: int = 100) -> str:
    """Write a node the way KiCad lays files out: short lists inline, nested lists one per line,
    point lists packed several per line."""
    out: List[str] = []

    def emit(item: Node, depth: int) -> None:
        pad = indent * depth
        if _is_flat(item):
            out.append(pad + _flat(item))
            return
        first = next(i for i, x in enumerate(item) if isinstance(x, Node))
        out.append(pad + "(" + " ".join(_atom(x) for x in item[:first]))
        rest = item[first:]
        if all(isinstance(c, Node) and _is_flat(c) and c.name == "xy" for c in rest):
            line = ""
            for child in rest:
                piece = _flat(child)
                if line and len(pad) + len(indent) + len(line) + 1 + len(piece) > width:
                    out.append(pad + indent + line)
                    line = piece
                else:
                    line = f"{line} {piece}" if line else piece
            if line:
                out.append(pad + indent + line)
        else:
            for child in rest:   # keep the original order, atoms after lists included
                if isinstance(child, Node):
                    emit(child, depth + 1)
                else:
                    out.append(pad + indent + _atom(child))
        out.append(pad + ")")

    emit(node, 0)
    return "\n".join(out) + "\n"
