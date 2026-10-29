"""Thin wrapper around `kicad-cli`: DRC and ERC as JSON, Gerber, drill and PDF export.

kicad-cli is found from $KICAD_CLI, then PATH, then the usual install folders. Report text is in
KiCad's UI language, so callers should use the `type` fields, not the descriptions.
"""
from __future__ import annotations

import glob
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Union

PathLike = Union[str, Path]


class KiCadCliError(RuntimeError):
    pass


def _version_key(path: str):
    m = re.search(r"(\d+)\.(\d+)", path)
    return (int(m.group(1)), int(m.group(2))) if m else (0, 0)


def find_kicad_cli() -> Optional[Path]:
    env = os.environ.get("KICAD_CLI")
    if env and Path(env).is_file():
        return Path(env)
    found = shutil.which("kicad-cli")
    if found:
        return Path(found)
    candidates: List[str] = []
    if sys.platform == "win32":
        for root in (os.environ.get("ProgramFiles", r"C:\Program Files"), r"C:\Program Files"):
            candidates += glob.glob(os.path.join(root, "KiCad", "*", "bin", "kicad-cli.exe"))
    elif sys.platform == "darwin":
        candidates += ["/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli"]
        candidates += glob.glob("/Applications/KiCad*/KiCad.app/Contents/MacOS/kicad-cli")
    else:
        candidates += ["/usr/bin/kicad-cli", "/usr/local/bin/kicad-cli"]
    candidates = [c for c in candidates if os.path.isfile(c)]
    if not candidates:
        return None
    return Path(sorted(candidates, key=_version_key)[-1])


def run(args: Sequence[str], cli: Optional[Path] = None, timeout: float = 600) -> subprocess.CompletedProcess:
    cli = cli or find_kicad_cli()
    if cli is None:
        raise KiCadCliError("kicad-cli not found; install KiCad or set KICAD_CLI")
    return subprocess.run([str(cli), *args], capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=timeout)


def version(cli: Optional[Path] = None) -> str:
    return run(["version"], cli).stdout.strip()


def _copy_project(board: Path, folder: Path) -> Path:
    """Copy the board with its project and custom-rules files, so kicad-cli writes nothing
    (it creates a .kicad_prl) next to the user's files."""
    target = folder / board.name
    shutil.copy2(board, target)
    for suffix in (".kicad_pro", ".kicad_dru"):
        side = board.with_suffix(suffix)
        if side.is_file():
            shutil.copy2(side, folder / side.name)
    return target


def drc(board: PathLike, refill: bool = False, parity: bool = False, in_place: Optional[bool] = None,
        cli: Optional[Path] = None) -> Dict:
    """Run DRC and return the parsed JSON report.

    Schematic parity needs the schematic files, so it runs in place; otherwise it runs on a copy.
    """
    board = Path(board).resolve()
    in_place = parity if in_place is None else in_place
    with tempfile.TemporaryDirectory(prefix="kcp_drc_") as tmp:
        target = board if in_place else _copy_project(board, Path(tmp))
        report = Path(tmp) / "drc.json"
        args = ["pcb", "drc", "--format", "json", "--severity-all", "--units", "mm", "--output", str(report)]
        if refill:
            args.append("--refill-zones")
        if parity:
            args.append("--schematic-parity")
        result = run(args + [str(target)], cli)
        if not report.is_file():
            raise KiCadCliError(f"kicad-cli pcb drc failed: {(result.stderr or result.stdout).strip()}")
        return json.loads(report.read_text(encoding="utf-8"))


def erc(schematic: PathLike, cli: Optional[Path] = None) -> Dict:
    schematic = Path(schematic).resolve()
    with tempfile.TemporaryDirectory(prefix="kcp_erc_") as tmp:
        report = Path(tmp) / "erc.json"
        result = run(["sch", "erc", "--format", "json", "--severity-all", "--units", "mm",
                      "--output", str(report), str(schematic)], cli)
        if not report.is_file():
            raise KiCadCliError(f"kicad-cli sch erc failed: {(result.stderr or result.stdout).strip()}")
        return json.loads(report.read_text(encoding="utf-8"))


_NET_IN_DESCRIPTION = re.compile(r"\[([^\]]*)\]")


def item_net(description: str) -> Optional[str]:
    """Net name from a report item description such as 'Pad 1 [GND] of R1 on F.Cu'."""
    m = _NET_IN_DESCRIPTION.search(description or "")
    return m.group(1) if m else None


def summarize_drc(report: Dict) -> Dict:
    """Counts by type and severity, unconnected items per net. Excluded violations are left out."""
    violations = [v for v in report.get("violations", []) if not v.get("excluded")]
    unconnected = report.get("unconnected_items", [])
    per_net: Counter = Counter()
    for item in unconnected:
        nets = {item_net(i.get("description", "")) for i in item.get("items", [])} - {None}
        for net in nets or {"?"}:
            per_net[net] += 1
    sheets = report.get("sheets")
    return {
        "kicad_version": report.get("kicad_version"),
        "violations": len(violations),
        "errors": sum(1 for v in violations if v.get("severity") == "error"),
        "warnings": sum(1 for v in violations if v.get("severity") == "warning"),
        "by_type": dict(Counter(v.get("type", "?") for v in violations).most_common()),
        "unconnected": len(unconnected),
        "unconnected_by_net": dict(per_net.most_common()),
        "schematic_parity": len(report.get("schematic_parity", [])),
        **({"sheets": len(sheets)} if sheets else {}),
    }


def summarize_erc(report: Dict) -> Dict:
    violations = [v for sheet in report.get("sheets", []) for v in sheet.get("violations", [])
                  if not v.get("excluded")]
    return {
        "kicad_version": report.get("kicad_version"),
        "violations": len(violations),
        "errors": sum(1 for v in violations if v.get("severity") == "error"),
        "warnings": sum(1 for v in violations if v.get("severity") == "warning"),
        "by_type": dict(Counter(v.get("type", "?") for v in violations).most_common()),
    }


def export_gerbers(board: PathLike, out_dir: PathLike, layers: Sequence[str], cli: Optional[Path] = None) -> None:
    result = run(["pcb", "export", "gerbers", "--layers", ",".join(layers), "--output", str(out_dir) + os.sep,
                  str(board)], cli)
    if result.returncode:
        raise KiCadCliError(f"gerber export failed: {(result.stderr or result.stdout).strip()}")


def export_drill(board: PathLike, out_dir: PathLike, cli: Optional[Path] = None) -> None:
    result = run(["pcb", "export", "drill", "--format", "excellon", "--excellon-units", "mm",
                  "--drill-origin", "absolute", "--excellon-separate-th", "--output", str(out_dir) + os.sep,
                  str(board)], cli)
    if result.returncode:
        raise KiCadCliError(f"drill export failed: {(result.stderr or result.stdout).strip()}")


def export_pdf(board: PathLike, pdf: PathLike, layers: Sequence[str], extra: Sequence[str] = (),
               cli: Optional[Path] = None) -> None:
    result = run(["pcb", "export", "pdf", "--mode-single", "--layers", ",".join(layers), *extra,
                  "--output", str(pdf), str(board)], cli)
    if result.returncode:
        raise KiCadCliError(f"pdf export failed: {(result.stderr or result.stdout).strip()}")
