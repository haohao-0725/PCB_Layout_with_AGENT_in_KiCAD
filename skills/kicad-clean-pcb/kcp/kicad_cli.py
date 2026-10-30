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
    # Project library tables point at ${KIPRJMOD}; point the copies back at the real project.
    project = board.parent.resolve().as_posix()
    for table in ("fp-lib-table", "sym-lib-table"):
        source = board.parent / table
        if source.is_file():
            text = source.read_text(encoding="utf-8").replace("${KIPRJMOD}", project)
            (folder / table).write_text(text, encoding="utf-8")
    return target


def drc(board: PathLike, refill: bool = False, parity: bool = False, in_place: Optional[bool] = None,
        cli: Optional[Path] = None, save: bool = False) -> Dict:
    """Run DRC and return the parsed JSON report.

    Schematic parity needs the schematic files, so it runs in place; otherwise it runs on a copy.
    save=True (with refill) has KiCad write the refilled zones into the board file itself.
    """
    board = Path(board).resolve()
    in_place = (parity or save) if in_place is None else in_place
    with tempfile.TemporaryDirectory(prefix="kcp_drc_") as tmp:
        target = board if in_place else _copy_project(board, Path(tmp))
        report = Path(tmp) / "drc.json"
        args = ["pcb", "drc", "--format", "json", "--severity-all", "--units", "mm", "--output", str(report)]
        if refill:
            args.append("--refill-zones")
        if save:
            args.append("--save-board")
        if parity:
            args.append("--schematic-parity")
        result = run(args + [str(target)], cli)
        if not report.is_file():
            raise KiCadCliError(f"kicad-cli pcb drc failed: {(result.stderr or result.stdout).strip()}")
        return json.loads(report.read_text(encoding="utf-8"))


def refill_zones(board: PathLike, cli: Optional[Path] = None) -> Dict:
    """Refill every zone and save the board (KiCad writes the file). A board written by a script
    has empty zones until this runs: previews, lint fill areas and Gerbers need it. Returns the
    DRC summary of that run."""
    return summarize_drc(drc(board, refill=True, save=True, cli=cli))


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


def _xy3(pos: Optional[Dict]) -> List[Optional[float]]:
    pos = pos or {}
    return [round(pos["x"], 3) if "x" in pos else None, round(pos["y"], 3) if "y" in pos else None]


def item_index(root) -> Dict[str, Dict]:
    """uuid -> {"label", "ref"?, "zone"?} for every board object, read from the board file.

    Report descriptions are in KiCad's UI language, but every report item carries the uuid of a
    board object, so this names items the same way on every machine: "J1 pad 1 [+5V]",
    "R1 Reference text (F.SilkS)", "J1 line on F.SilkS", "track [GND] on F.Cu"."""
    from .model import _net_name
    numbers = {}
    for net in root.all("net"):
        atoms = net.atoms()
        if len(atoms) >= 2:
            numbers[str(atoms[0])] = str(atoms[1])
    index: Dict[str, Dict] = {}

    def add(node, label: str, ref: str = "", zone: bool = False) -> None:
        uid = node.value("uuid", "")
        if uid:
            index[str(uid)] = {"label": label, **({"ref": ref} if ref else {}), **({"zone": True} if zone else {})}

    def net_tag(node) -> str:
        net = _net_name(node, numbers)
        return f" [{net}]" if net else ""

    for child in root.nodes():
        name = child.name
        layer = child.value("layer", "") or ""
        if name in ("footprint", "module"):
            ref = ""
            for prop in child.all("property"):
                if len(prop) > 2 and str(prop[1]) == "Reference":
                    ref = str(prop[2])
            for text in child.all("fp_text"):
                if len(text) > 2 and str(text[1]) == "reference" and not ref:
                    ref = str(text[2])
            add(child, f"{ref} footprint", ref)
            for sub in child.nodes():
                sname = sub.name
                slayer = sub.value("layer", "") or ""
                if sname == "pad":
                    number = str(sub[1]) if len(sub) > 1 else ""
                    add(sub, f"{ref} pad {number}{net_tag(sub)}", ref)
                elif sname == "property" and len(sub) > 1:
                    add(sub, f"{ref} {sub[1]} text ({slayer})", ref)
                elif sname == "fp_text" and len(sub) > 2:
                    kind = str(sub[1])
                    what = f"{kind.capitalize()} text" if kind in ("reference", "value") else f"text '{sub[2]}'"
                    add(sub, f"{ref} {what} ({slayer})", ref)
                elif sname.startswith("fp_"):
                    add(sub, f"{ref} {sname[3:]} on {slayer}", ref)
                elif sname == "zone":
                    add(sub, f"{ref} zone{net_tag(sub)}", ref, zone=True)
        elif name in ("segment", "arc"):
            add(child, f"{'track' if name == 'segment' else 'arc track'}{net_tag(child)} on {layer}")
        elif name == "via":
            add(child, f"via{net_tag(child)}")
        elif name == "zone":
            zname = child.value("name", "") or ""
            add(child, f"zone{' ' + repr(zname) if zname else ''}{net_tag(child)}", zone=True)
        elif name == "gr_text" and len(child) > 1:
            add(child, f"board text '{child[1]}' ({layer})")
        elif name.startswith("gr_"):
            add(child, f"board {name[3:]} on {layer}")
    return index


def list_violations(report: Dict, root=None, limit: Optional[int] = None) -> List[Dict]:
    """Every DRC violation, unconnected item and parity issue with the parts involved and where.

    root: the parsed board file (kcp.sexpr.load), used to name the items in any UI language;
    without it the item descriptions from the report are used. "at" is the position (mm) of the
    first item that is not a zone (KiCad reports zones at 0,0)."""
    index = item_index(root) if root is not None else {}
    groups = (("violation", [v for v in report.get("violations", []) if not v.get("excluded")]),
              ("unconnected", report.get("unconnected_items", [])),
              ("parity", report.get("schematic_parity", [])))
    out: List[Dict] = []
    for kind, entries in groups:
        for entry in entries:
            items, at = [], None
            for item in entry.get("items", []):
                info = index.get(str(item.get("uuid", "")))
                xy = _xy3(item.get("pos"))
                items.append({"item": info["label"] if info else item.get("description", ""),
                              **({"ref": info["ref"]} if info and info.get("ref") else {}), "at": xy})
                if at is None and not (info and info.get("zone")):
                    at = xy
            out.append({"kind": kind, "type": entry.get("type", "?"), "severity": entry.get("severity"),
                        "refs": sorted({i["ref"] for i in items if i.get("ref")}),
                        "at": at or (items[0]["at"] if items else None), "items": items})
            if limit is not None and len(out) >= limit:
                return out
    return out


def violations_markdown(details: List[Dict], total: Optional[int] = None) -> str:
    """The list from list_violations as a Markdown table."""
    if not details:
        return ""
    lines = ["| # | Kind | Type | Severity | Parts | At (mm) | Items |", "|---:|---|---|---|---|---|---|"]
    for i, d in enumerate(details, 1):
        at = d.get("at") or [None, None]
        where = f"{at[0]}, {at[1]}" if at[0] is not None else ""
        items = "; ".join(x["item"] for x in d["items"]).replace("|", "\\|")
        lines.append(f"| {i} | {d['kind']} | {d['type']} | {d.get('severity') or ''} | {', '.join(d['refs'])} "
                     f"| {where} | {items} |")
    more = f"\n\n{total - len(details)} more not listed.\n" if total and total > len(details) else "\n"
    return "\n".join(lines) + more


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
