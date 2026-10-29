"""File backend: read and write .kicad_pcb files directly, without KiCad running.

Writing refuses while KiCad has the project open (a `~*.lck` file next to the board), because
KiCad's next save would overwrite the change.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import List, Optional, Union

from .. import sexpr
from ..model import Board, NetClasses, board_from_tree

PathLike = Union[str, Path]


class BoardLockedError(RuntimeError):
    pass


def lock_files(board_path: PathLike) -> List[Path]:
    """KiCad lock files in the board's folder (KiCad has the project or board open)."""
    folder = Path(board_path).resolve().parent
    return sorted(folder.glob("~*.lck"))


def load_board(path: PathLike, netclasses: Optional[NetClasses] = None) -> Board:
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"board file not found: {path}")
    return board_from_tree(sexpr.load(path), path, netclasses)


def save_tree(tree: sexpr.Node, path: PathLike, force: bool = False) -> Path:
    """Write a board tree. Writes a temporary file first, then replaces the target."""
    path = Path(path)
    locks = lock_files(path)
    if locks and not force:
        names = ", ".join(p.name for p in locks)
        raise BoardLockedError(f"KiCad has this project open ({names}); close it before writing {path.name}")
    text = sexpr.dumps(tree)
    fd, tmp = tempfile.mkstemp(prefix=path.stem + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
    return path


def save_board(board: Board, path: Optional[PathLike] = None, force: bool = False) -> Path:
    target = Path(path) if path else board.path
    if target is None:
        raise ValueError("no output path")
    return save_tree(board.root, target, force)
