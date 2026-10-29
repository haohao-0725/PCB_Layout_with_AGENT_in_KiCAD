"""`kcp` command line. Every subcommand prints JSON (or Markdown with --markdown).

Exit codes: 0 ok; 1 the check failed (lint fail, checkpoint incomplete, DRC/ERC violations);
2 the tool could not run (bad arguments, unreadable file, kicad-cli missing).

    python <skill>/kcp inspect board.kicad_pcb [--summary] [--refs R1,R2] [--no-pads] [--drc]
    python <skill>/kcp lint board.kicad_pcb [--preset T] [--layer-plan plan.json] [--thresholds t.json]
    python <skill>/kcp decisions PCB_DECISIONS.md [--checkpoint CP2]
    python <skill>/kcp drc board.kicad_pcb [--refill] [--parity]
    python <skill>/kcp erc board.kicad_sch
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import List, Optional

from . import __version__


def _emit(data, markdown: Optional[str], out: Optional[Path]) -> None:
    text = markdown if markdown is not None else json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    if out:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
        print(json.dumps({"written": str(out)}))
    else:
        sys.stdout.write(text)


def _common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--markdown", action="store_true", help="print Markdown tables instead of JSON")
    parser.add_argument("--out", type=Path, help="write the result to this file instead of stdout")


def cmd_inspect(args) -> int:
    from .backends.file import load_board
    from .inspection import inspect_board, to_markdown
    board = load_board(args.board)
    drc = None
    if args.drc or args.refill:
        from . import kicad_cli
        drc = kicad_cli.summarize_drc(kicad_cli.drc(args.board, refill=args.refill))
    refs = [r.strip() for r in args.refs.split(",")] if args.refs else None
    data = inspect_board(board, pads=not args.no_pads, refs=refs, drc=drc, summary=args.summary)
    _emit(data, to_markdown(data) if args.markdown else None, args.out)
    return 0


def cmd_lint(args) -> int:
    from .backends.file import load_board
    from .lint import load_layer_plan, load_thresholds, lint_board, to_markdown
    board = load_board(args.board)
    plan = load_layer_plan(args.layer_plan) if args.layer_plan else None
    thresholds = load_thresholds(args.thresholds)
    result = lint_board(board, args.preset, thresholds, plan,
                        str(args.thresholds) if args.thresholds else None)
    _emit(result, to_markdown(result) if args.markdown else None, args.out)
    if result["status"] == "fail" or (args.strict and result["status"] == "warn"):
        return 1
    return 0


def cmd_decisions(args) -> int:
    from .decisions import check_file, to_markdown
    result = check_file(args.file, args.checkpoint)
    _emit(result, to_markdown(result) if args.markdown else None, args.out)
    if args.checkpoint and not result["checkpoint"]["ok"]:
        return 1
    return 0


def cmd_drc(args) -> int:
    from . import kicad_cli
    report = kicad_cli.drc(args.board, refill=args.refill, parity=args.parity)
    summary = kicad_cli.summarize_drc(report)
    data = {"tool": "kcp drc", "file": str(args.board), "refilled": args.refill, "parity": args.parity, **summary}
    if args.full:
        data["report"] = report
    md = None
    if args.markdown:
        md = (f"# DRC: {summary['violations']} violations, {summary['unconnected']} unconnected, "
              f"{summary['schematic_parity']} parity issues\n\n| Type | Count |\n|---|---:|\n"
              + "".join(f"| {k} | {v} |\n" for k, v in summary["by_type"].items()))
    _emit(data, md, args.out)
    bad = summary["violations"] + summary["unconnected"] + (summary["schematic_parity"] if args.parity else 0)
    return 1 if bad else 0


def cmd_erc(args) -> int:
    from . import kicad_cli
    report = kicad_cli.erc(args.schematic)
    summary = kicad_cli.summarize_erc(report)
    data = {"tool": "kcp erc", "file": str(args.schematic), **summary}
    if args.full:
        data["report"] = report
    md = None
    if args.markdown:
        md = (f"# ERC: {summary['errors']} errors, {summary['warnings']} warnings\n\n| Type | Count |\n|---|---:|\n"
              + "".join(f"| {k} | {v} |\n" for k, v in summary["by_type"].items()))
    _emit(data, md, args.out)
    return 1 if summary["violations"] else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="kcp", description="KiCad board tools for the kicad-clean-pcb skill.")
    parser.add_argument("--version", action="version", version=f"kcp {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("inspect", help="the board as JSON: outline, layers, footprints, pads, nets, tracks")
    p.add_argument("board", type=Path)
    p.add_argument("--summary", action="store_true", help="footprint positions only; nets with 2+ pads only")
    p.add_argument("--refs", help="only these footprints, comma separated")
    p.add_argument("--no-pads", action="store_true", help="leave out the per-pad list")
    p.add_argument("--drc", action="store_true", help="also run kicad-cli DRC for unconnected items (~15 s)")
    p.add_argument("--refill", action="store_true", help="refill zones in the DRC run (implies --drc)")
    _common(p)
    p.set_defaults(func=cmd_inspect)

    p = sub.add_parser("lint", help="tidiness score with pass/warn/fail per metric")
    p.add_argument("board", type=Path)
    p.add_argument("--preset", default="T", help="T, C or R (default T), as in the thresholds file")
    p.add_argument("--layer-plan", type=Path, help='JSON: {"F.Cu": "horizontal", "B.Cu": "vertical", "In1.Cu": "plane"}')
    p.add_argument("--thresholds", type=Path, help="thresholds file (default: kcp/presets/lint.json)")
    p.add_argument("--strict", action="store_true", help="exit 1 on warn as well as fail")
    _common(p)
    p.set_defaults(func=cmd_lint)

    p = sub.add_parser("decisions", help="blank rows in PCB_DECISIONS.md; checkpoint readiness")
    p.add_argument("file", type=Path)
    p.add_argument("--checkpoint", help="CP0, CP1, CP2, CP4 or CP6: exit 1 if a required answer is blank")
    _common(p)
    p.set_defaults(func=cmd_decisions)

    p = sub.add_parser("drc", help="kicad-cli DRC summarised as JSON")
    p.add_argument("board", type=Path)
    p.add_argument("--refill", action="store_true", help="refill zones first (the board file is not saved)")
    p.add_argument("--parity", action="store_true", help="include schematic parity (runs next to the schematic)")
    p.add_argument("--full", action="store_true", help="include the full kicad-cli report")
    _common(p)
    p.set_defaults(func=cmd_drc)

    p = sub.add_parser("erc", help="kicad-cli ERC summarised as JSON")
    p.add_argument("schematic", type=Path)
    p.add_argument("--full", action="store_true", help="include the full kicad-cli report")
    _common(p)
    p.set_defaults(func=cmd_erc)
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    for stream in (sys.stdout, sys.stderr):      # Windows consoles default to a legacy code page
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8")
            except (ValueError, OSError):
                pass
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except Exception as exc:  # report every failure as JSON so an agent can read it
        print(json.dumps({"tool": f"kcp {args.command}", "error": f"{type(exc).__name__}: {exc}"},
                         ensure_ascii=False))
        return 2


if __name__ == "__main__":
    sys.exit(main())
