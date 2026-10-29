"""Live backend: work on the board that is open in KiCad, through KiCad's IPC API.

Needs KiCad 10 running with the API server enabled (Preferences -> Plugins in KiCad 9/10; the
setting is stored as `api.enable_server` in kicad_common.json) and `pip install kicad-python`
(module `kipy`). KiCad 10.0.6 or newer is recommended for kicad-python 0.8.

- Reading: the live board is fetched in file format (`Board.get_as_string`) and parsed by the same
  code as the file backend, so inspect, lint, fit check and the router's clearance check see
  exactly what KiCad has open, saved or not.
- Writing: every kcp operation is one KiCad commit with a message such as "kcp: route X_DIR", so
  the user can undo it with a single Ctrl+Z. Nothing is written when a check fails.
- KiCad 10's API has no schematic commands and no library footprint loading; use the file backend
  and kicad-cli for those.
"""
from __future__ import annotations

import contextlib
from types import SimpleNamespace
from typing import Dict, List, Optional, Sequence, Tuple

from .. import sexpr
from ..board import BoardBuilder
from ..model import Board, NetClasses, board_from_tree

Point = Tuple[float, float]


def _kipy() -> SimpleNamespace:
    """The kipy pieces this backend uses (replaced by fakes in tests)."""
    try:
        from kipy import KiCad
        from kipy.board_types import Net, Track
        from kipy.geometry import Angle, Vector2
        from kipy.util import from_mm
        from kipy.util.board_layer import layer_from_canonical_name
    except ImportError as exc:                      # pragma: no cover - depends on the machine
        raise RuntimeError("the live backend needs kicad-python: pip install kicad-python") from exc
    return SimpleNamespace(KiCad=KiCad, Net=Net, Track=Track, Angle=Angle, Vector2=Vector2, from_mm=from_mm,
                           layer=layer_from_canonical_name)


class LiveBoard:
    def __init__(self, socket_path: Optional[str] = None, kicad=None, api: Optional[SimpleNamespace] = None):
        self.api = api or _kipy()
        self.kicad = kicad or self.api.KiCad(socket_path=socket_path, client_name="kcp")
        self.board = self.kicad.get_board()

    # ------------------------------------------------------------ reading

    def tree(self) -> sexpr.Node:
        return sexpr.loads(self.board.get_as_string())

    def netclasses(self) -> NetClasses:
        project = None
        with contextlib.suppress(Exception):
            path = self.board.get_project().path
            from pathlib import Path
            folder = Path(path)
            candidates = sorted(folder.glob("*.kicad_pro")) if folder.is_dir() else [folder.with_suffix(".kicad_pro")]
            project = candidates[0] if candidates else None
        return NetClasses.from_project(project)

    def snapshot(self) -> Board:
        return board_from_tree(self.tree(), None, self.netclasses())

    def builder(self) -> BoardBuilder:
        """A file-backend copy of the live board, for checks (never saved back)."""
        return BoardBuilder(self.tree())

    # ------------------------------------------------------------ writing

    @contextlib.contextmanager
    def commit(self, message: str):
        """One undo step in KiCad; dropped if anything inside fails."""
        commit = self.board.begin_commit()
        try:
            yield
        except BaseException:
            self.board.drop_commit(commit)
            raise
        self.board.push_commit(commit, message)

    def _footprint(self, ref: str):
        for fp in self.board.get_footprints():
            if fp.reference_field.text.value == ref:
                return fp
        raise KeyError(f"no footprint {ref} on the live board")

    def move_footprint(self, ref: str, x: float, y: float, rotation: Optional[float] = None) -> None:
        fp = self._footprint(ref)
        fp.position = self.api.Vector2.from_xy_mm(x, y)
        if rotation is not None:
            fp.orientation = self.api.Angle.from_degrees(rotation)
        with self.commit(f"kcp: move {ref}"):
            self.board.update_items([fp])

    def add_tracks(self, net: str, layer: str, width: float, points: Sequence[Point], message: str) -> int:
        tracks = []
        for a, b in zip(points, points[1:]):
            if a == b:
                continue
            t = self.api.Track()
            t.start = self.api.Vector2.from_xy_mm(a[0], a[1])
            t.end = self.api.Vector2.from_xy_mm(b[0], b[1])
            t.width = self.api.from_mm(width)
            t.layer = self.api.layer(layer)
            t.net = self.api.Net(name=net)
            tracks.append(t)
        with self.commit(message):
            self.board.create_items(tracks)
        return len(tracks)

    def route_path(self, net: str, layer: str, width: Optional[float], points: Sequence, any_angle: bool = False,
                   dry_run: bool = False) -> Dict:
        """Check a path against the live board with the file-backend router, then write it as one commit.
        points: (x, y) tuples or 'REF.PAD' strings."""
        from ..route import Router
        router = Router(self.builder(), self.netclasses())
        resolved: List[Point] = []
        for p in points:
            if isinstance(p, str):
                ref, _, pad = p.rpartition(".")
                resolved.append(router.pad(ref, pad))
            else:
                resolved.append((float(p[0]), float(p[1])))
        width = width if width is not None else router.width(net)
        problems = router.check_path(net, layer, width, resolved, any_angle)
        written = 0
        if not problems and not dry_run:
            written = self.add_tracks(net, layer, width, resolved, f"kcp: route {net}")
        return {"net": net, "layer": layer, "width": width, "points": [list(p) for p in resolved],
                "conflicts": problems, "written": bool(written), "segments": written}

    def refill_zones(self) -> None:
        self.board.refill_zones()
