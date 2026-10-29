"""`kcp` command line. Every subcommand prints JSON (or Markdown with --markdown).

Exit codes: 0 ok; 1 the check failed (lint fail, checkpoint incomplete, DRC/ERC violations,
fit-check problems, route conflicts, lane crossings); 2 the tool could not run (bad arguments,
unreadable file, kicad-cli missing, KiCad has the project open).

    python <skill>/kcp inspect board.kicad_pcb [--summary] [--refs R1,R2] [--no-pads] [--drc]
    python <skill>/kcp lint board.kicad_pcb [--preset T] [--layer-plan plan.json] [--thresholds t.json]
    python <skill>/kcp decisions PCB_DECISIONS.md [--checkpoint CP2]
    python <skill>/kcp drc board.kicad_pcb [--refill] [--parity]
    python <skill>/kcp erc board.kicad_sch
    python <skill>/kcp place fit-check|move|row|edge board.kicad_pcb ...
    python <skill>/kcp route path|cleanup board.kicad_pcb ... ;  kcp route lane --lines ... --entry ...
    python <skill>/kcp previews board.kicad_pcb --out-dir previews
    python <skill>/kcp tracedrop board.kicad_pcb --net +5V --source J1.1 --load U3.8=0.15
    python <skill>/kcp mcp                      # MCP server on stdio (same tools)

Board arguments of inspect, lint, place fit-check / move and route path also accept "live": the
board open in KiCad, through its IPC API (pip install kicad-python; enable the API server in KiCad).
"""
from __future__ import annotations

import argparse
import json
import sys
import threading
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from . import __version__

_local = threading.local()


def _emit(data, markdown: Optional[str], out: Optional[Path]) -> None:
    sink = getattr(_local, "sink", None)
    if sink is not None:                 # called through run(): hand the data back, print nothing
        sink.append(data)
        return
    text = markdown if markdown is not None else json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    if out:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
        print(json.dumps({"written": str(out)}))
    else:
        sys.stdout.write(text)


LIVE = "live"


def _is_live(board) -> bool:
    return str(board) == LIVE


def _load(board):
    """The board model from a file, or from the board open in KiCad when board == 'live'."""
    if _is_live(board):
        from .backends.ipc import LiveBoard
        return LiveBoard().snapshot()
    from .backends.file import load_board
    return load_board(board)


def _common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--markdown", action="store_true", help="print Markdown tables instead of JSON")
    parser.add_argument("--out", type=Path, help="write the result to this file instead of stdout")


def cmd_inspect(args) -> int:
    from .inspection import inspect_board, to_markdown
    board = _load(args.board)
    drc = None
    if (args.drc or args.refill) and not _is_live(args.board):
        from . import kicad_cli
        drc = kicad_cli.summarize_drc(kicad_cli.drc(args.board, refill=args.refill))
    refs = [r.strip() for r in args.refs.split(",")] if args.refs else None
    data = inspect_board(board, pads=not args.no_pads, refs=refs, drc=drc, summary=args.summary)
    _emit(data, to_markdown(data) if args.markdown else None, args.out)
    return 0


def cmd_lint(args) -> int:
    from .lint import load_layer_plan, load_thresholds, lint_board, to_markdown
    board = _load(args.board)
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


def _point(text: str):
    x, _, y = text.partition(",")
    return float(x), float(y)


def _keepout(text: str):
    parts = text.split(",", 4)
    if len(parts) < 4:
        raise argparse.ArgumentTypeError("keep-out is x0,y0,x1,y1[,reason]")
    return (float(parts[0]), float(parts[1]), float(parts[2]), float(parts[3]),
            parts[4] if len(parts) > 4 else "keep-out")


def cmd_place(args) -> int:
    from .board import BoardBuilder
    from . import place as pl
    if args.action == "fit-check":
        report = pl.fit_check(_load(args.board), args.keepout or [], args.edge_min,
                              args.ignore.split(",") if args.ignore else ())
        _emit({"tool": "kcp place fit-check", **report}, None, args.out)
        return 0 if report["ok"] else 1
    if _is_live(args.board):
        if args.action != "move":
            raise ValueError("on the live board only 'place move' and 'place fit-check' are available")
        from .backends.ipc import LiveBoard
        live = LiveBoard()
        live.move_footprint(args.ref, args.x, args.y, args.rot)
        report = pl.fit_check(live.snapshot())
        _emit({"tool": "kcp place move", "live": True, "moved": {args.ref: [args.x, args.y, args.rot]},
               "fit_check": report}, None, args.out)
        return 0 if report["ok"] else 1
    b = BoardBuilder.open(args.board)
    moved = {}
    if args.action == "move":
        pl.move(b, args.ref, args.x, args.y, args.rot)
        moved[args.ref] = [args.x, args.y, args.rot]
    elif args.action == "row":
        refs = [r.strip() for r in args.refs.split(",")]
        for ref, (x, y, a) in pl.row(refs, _point(args.start), args.pitch, args.axis, args.rot).items():
            pl.move(b, ref, x, y, a)
            moved[ref] = [x, y, a]
    elif args.action == "edge":
        board = b.board(args.board)
        fp = board.footprint(args.ref)
        if fp is None:
            raise KeyError(f"no footprint {args.ref}")
        x, y = pl.at_edge(fp, board.outline_bbox(), args.side, args.inset)
        pl.move(b, args.ref, x, y)
        moved[args.ref] = [round(x, 4), round(y, 4), None]
    b.save(args.board, force=args.force)
    report = pl.fit_check(b.board(args.board))
    _emit({"tool": f"kcp place {args.action}", "moved": moved, "fit_check": report}, None, args.out)
    return 0 if report["ok"] else 1


def cmd_route(args) -> int:
    from . import route as rt
    if args.action == "lane":
        lines = json.loads(Path(args.lines).read_text(encoding="utf-8") if Path(args.lines).is_file() else args.lines)
        entry = [n.strip() for n in args.entry.split(",")] if args.entry else None
        result = rt.lane_order(lines, entry)
        _emit({"tool": "kcp route lane", **result}, None, args.out)
        return 1 if result.get("crossings") else 0
    if args.action == "path" and _is_live(args.board):
        from .backends.ipc import LiveBoard
        tokens = [tok if "," not in tok else _point(tok) for tok in args.points.replace(";", " ").split()]
        result = LiveBoard().route_path(args.net, args.layer, args.width, tokens, args.any_angle, args.dry_run)
        _emit({"tool": "kcp route path", "live": True, **result}, None, args.out)
        return 1 if result["conflicts"] else 0
    from .board import BoardBuilder
    from .model import NetClasses
    b = BoardBuilder.open(args.board)
    if args.action == "cleanup":
        stats = rt.cleanup(b, args.nets.split(",") if args.nets else None)
        b.save(args.board, force=args.force)
        _emit({"tool": "kcp route cleanup", **stats}, None, args.out)
        return 0
    router = rt.Router(b, NetClasses.from_project(Path(args.board).with_suffix(".kicad_pro")))
    points = []
    for token in args.points.replace(";", " ").split():
        if "," in token:
            points.append(_point(token))
        else:
            ref, _, pad = token.rpartition(".")
            points.append(router.pad(ref, pad))
    width = args.width if args.width is not None else router.width(args.net)
    problems = router.check_path(args.net, args.layer, width, points, args.any_angle)
    data = {"tool": "kcp route path", "net": args.net, "layer": args.layer, "width": width,
            "points": [list(p) for p in points], "conflicts": problems, "written": False}
    if not problems and not args.dry_run:
        router.path(args.net, args.layer, width, points, args.any_angle, check=False)
        b.save(args.board, force=args.force)
        data["written"] = True
    _emit(data, None, args.out)
    return 1 if problems else 0


def cmd_previews(args) -> int:
    from .previews import export
    result = export(args.board, args.out_dir, args.dpi, [l for l in args.extra_layers.split(",") if l],
                    [l for l in args.fit_layers.split(",") if l])
    _emit(result, None, args.out)
    return 0


def cmd_tracedrop(args) -> int:
    from .backends.file import load_board
    from .tracedrop import analyse, to_text
    loads = {}
    for item in args.load:
        name, _, amps = item.partition("=")
        loads[name] = float(amps)
    result = analyse(load_board(args.board), args.net, args.source, loads, args.outer_um, args.inner_um,
                     args.temp_c, args.rho, args.dt_limit)
    _emit(result, to_text(result) if args.markdown else None, args.out)
    return 1 if result["above_limit"] else 0


def cmd_mcp(args) -> int:
    from .mcp_server import serve, tool_list
    if args.list:
        _emit({"tool": "kcp mcp", "tools": tool_list()}, None, None)
        return 0
    serve(prefer_sdk=not args.builtin)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="kcp", description="KiCad board tools for the kicad-clean-pcb skill.")
    parser.add_argument("--version", action="version", version=f"kcp {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("inspect", help="the board as JSON: outline, layers, footprints, pads, nets, tracks")
    p.add_argument("board", type=Path, help="a .kicad_pcb file, or 'live' for the board open in KiCad (IPC API)")
    p.add_argument("--summary", action="store_true", help="footprint positions only; nets with 2+ pads only")
    p.add_argument("--refs", help="only these footprints, comma separated")
    p.add_argument("--no-pads", action="store_true", help="leave out the per-pad list")
    p.add_argument("--drc", action="store_true", help="also run kicad-cli DRC for unconnected items (~15 s)")
    p.add_argument("--refill", action="store_true", help="refill zones in the DRC run (implies --drc)")
    _common(p)
    p.set_defaults(func=cmd_inspect)

    p = sub.add_parser("lint", help="tidiness score with pass/warn/fail per metric")
    p.add_argument("board", type=Path, help="a .kicad_pcb file, or 'live' for the board open in KiCad")
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

    p = sub.add_parser("place", help="fit check, move, rows, edge placement (writes refuse while KiCad is open)")
    actions = p.add_subparsers(dest="action", required=True)
    a = actions.add_parser("fit-check", help="courtyard overlaps, edge distance, keep-outs")
    a.add_argument("board", type=Path)
    a.add_argument("--keepout", type=_keepout, action="append", help="x0,y0,x1,y1[,reason]; repeat")
    a.add_argument("--edge-min", type=float, default=0.0, help="minimum courtyard distance to the board edge (mm)")
    a.add_argument("--ignore", help="references to leave out, comma separated")
    a = actions.add_parser("move", help="move (and rotate) one footprint")
    a.add_argument("board", type=Path)
    a.add_argument("ref")
    a.add_argument("x", type=float)
    a.add_argument("y", type=float)
    a.add_argument("--rot", type=float, help="new rotation in degrees (default: keep)")
    a = actions.add_parser("row", help="line parts up at a fixed pitch and angle")
    a.add_argument("board", type=Path)
    a.add_argument("--refs", required=True, help="references in order, comma separated")
    a.add_argument("--start", required=True, help="x,y of the first part")
    a.add_argument("--pitch", type=float, required=True)
    a.add_argument("--axis", choices=["x", "y"], default="x")
    a.add_argument("--rot", type=float, default=0.0)
    a = actions.add_parser("edge", help="put a connector's courtyard flush with a board edge")
    a.add_argument("board", type=Path)
    a.add_argument("ref")
    a.add_argument("--side", choices=["left", "right", "top", "bottom"], required=True)
    a.add_argument("--inset", type=float, default=0.0)
    for a in actions.choices.values():
        a.add_argument("--force", action="store_true", help="write even if KiCad lock files exist")
        a.add_argument("--out", type=Path, help="write the result to this file instead of stdout")
    p.set_defaults(func=cmd_place)

    p = sub.add_parser("route", help="checked 0/45/90 paths, cleanup, lane order")
    actions = p.add_subparsers(dest="action", required=True)
    a = actions.add_parser("path", help="pad -> bend points -> pad; refused with a conflict list if unsafe")
    a.add_argument("board", type=Path)
    a.add_argument("--net", required=True)
    a.add_argument("--layer", required=True)
    a.add_argument("--width", type=float, help="default: the net's netclass width")
    a.add_argument("--points", required=True, help='"REF.PAD x,y x,y REF.PAD" (space or ; separated)')
    a.add_argument("--any-angle", action="store_true", help="allow angles other than 0/45/90")
    a.add_argument("--dry-run", action="store_true", help="check only, write nothing")
    a = actions.add_parser("cleanup", help="merge collinear segments, drop zero-length ones")
    a.add_argument("board", type=Path)
    a.add_argument("--nets", help="only these nets, comma separated")
    a = actions.add_parser("lane", help="crossing-free order of lines in a lane (playbook §3)")
    a.add_argument("--lines", required=True,
                   help='JSON or a JSON file: [{"net": "A", "exit": 12.5, "turn": "right"}, ...]')
    a.add_argument("--entry", help="the order the lines arrive in, comma separated: report crossings")
    for a in actions.choices.values():
        a.add_argument("--force", action="store_true", help="write even if KiCad lock files exist")
        a.add_argument("--out", type=Path, help="write the result to this file instead of stdout")
    p.set_defaults(func=cmd_route)

    p = sub.add_parser("previews", help="routing/assembly/inner PDF+PNG and a 1:1 fit-check PDF")
    p.add_argument("board", type=Path)
    p.add_argument("--out-dir", type=Path, default=Path("previews"))
    p.add_argument("--dpi", type=int, default=150)
    p.add_argument("--extra-layers", default="Dwgs.User", help="reference layers on every preview")
    p.add_argument("--fit-layers", default="F.Cu,F.SilkS,F.Fab,Edge.Cuts", help="layers on the 1:1 page")
    p.add_argument("--out", type=Path, help="write the result to this file instead of stdout")
    p.set_defaults(func=cmd_previews)

    p = sub.add_parser("tracedrop", help="voltage drop and IPC-2221 temperature rise along a net")
    p.add_argument("board", type=Path)
    p.add_argument("--net", required=True)
    p.add_argument("--source", required=True, help="REF.PAD")
    p.add_argument("--load", action="append", default=[], help="REF.PAD=AMPS; repeat")
    p.add_argument("--outer-um", type=float, default=35.0)
    p.add_argument("--inner-um", type=float, default=17.5)
    p.add_argument("--temp-c", type=float, default=40.0)
    p.add_argument("--rho", type=float)
    p.add_argument("--dt-limit", type=float, default=20.0)
    _common(p)
    p.set_defaults(func=cmd_tracedrop)

    p = sub.add_parser("mcp", help="run the MCP server on stdio (the same tools as this CLI)")
    p.add_argument("--builtin", action="store_true", help="use the built-in server even if the mcp SDK is installed")
    p.add_argument("--list", action="store_true", help="print the tool list and exit")
    p.set_defaults(func=cmd_mcp)
    return parser


def run(argv: List[str]) -> Tuple[int, Dict]:
    """Run one subcommand and return (exit code, result) without printing anything.
    Thread-safe; used by the MCP server, which owns stdout."""
    _local.sink = []
    try:
        try:
            args = build_parser().parse_args([str(a) for a in argv])
        except SystemExit as exc:
            code = exc.code if isinstance(exc.code, int) else 2
            return code, {"error": f"bad arguments: {' '.join(map(str, argv))}"}
        try:
            code = args.func(args)
        except Exception as exc:
            return 2, {"tool": f"kcp {args.command}", "error": f"{type(exc).__name__}: {exc}"}
        return code, (_local.sink[-1] if _local.sink else {})
    finally:
        _local.sink = None


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
