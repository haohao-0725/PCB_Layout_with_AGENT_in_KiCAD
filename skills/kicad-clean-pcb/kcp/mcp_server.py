"""MCP server for the kcp tools (stdio). Each tool is one `kcp` CLI subcommand with the same
inputs, and returns the same JSON: {"ok": bool, "exit_code": int, "result": {...}}.

    python <skill>/kcp mcp

Uses the official MCP Python SDK when it is installed (`mcp` 2.x MCPServer, or 1.x FastMCP);
otherwise a small built-in stdio JSON-RPC server with the same tools, so the plugin works with no
extra packages. Board arguments take a .kicad_pcb path, or "live" for the board open in KiCad
(IPC API, see backends/ipc.py): live edits are single KiCad commits that Ctrl+Z undoes.
"""
from __future__ import annotations

import json
import sys
import typing
from typing import Any, Callable, Dict, List, Optional

from . import __version__

NAME = "kicad-clean-pcb"
INSTRUCTIONS = (
    "Deterministic KiCad board tools for the kicad-clean-pcb skill: the agent decides, these tools "
    "do the geometry. Call check_setup once per project: it says whether this server, the skill "
    "text and other installed copies are the same version. Read the board with inspect_board "
    "before placing or routing; route with route_path (0/45/90 only, clearance-checked, nothing "
    "written on conflict); check with run_drc, lint_board and check_decisions. Never loosen rules "
    "to make a check pass."
)
TOOLS: List[Dict[str, Any]] = []


def tool(read_only: bool = True, destructive: bool = False):
    def register(fn: Callable) -> Callable:
        TOOLS.append({"fn": fn, "read_only": read_only, "destructive": destructive})
        return fn
    return register


def _run(argv: List[str]) -> Dict[str, Any]:
    # cli.run hands the result back per thread and never touches stdout: the SDK runs tool calls
    # in parallel threads, and stdout carries the MCP protocol.
    from .cli import run
    code, result = run([str(a) for a in argv])
    return {"ok": code == 0, "exit_code": code, "kcp_version": __version__, "result": result}


def _flag(name: str, value: Any) -> List[str]:
    if value is None or value is False:
        return []
    if value is True:
        return [name]
    return [name, str(value)]


# ---------------------------------------------------------------- tools (one per CLI subcommand)

@tool()
def check_setup() -> Dict[str, Any]:
    """Which version this MCP server is, every copy of the kicad-clean-pcb skill on this machine
    (plugin, plugin cache, ~/.claude/skills, ~/.agents/skills) with its version, Python and
    kicad-cli. ok=False lists what to update, e.g. an outdated plugin or an old copied skill
    folder that is loaded instead of the plugin's."""
    return _run(["doctor"])


@tool()
def inspect_board(board: str, summary: bool = True, refs: Optional[List[str]] = None, pads: bool = True,
                  drc: bool = False) -> Dict[str, Any]:
    """The board as JSON: outline size, layers, stackup, footprints (position, rotation, side,
    courtyard, pads with nets), nets with routing stats, tracks, vias, zones. board: a .kicad_pcb
    path or "live". summary=True keeps it short; drc=True adds unconnected items (~15 s)."""
    return _run(["inspect", board] + _flag("--summary", summary) + (["--refs", ",".join(refs)] if refs else [])
                + _flag("--no-pads", not pads) + _flag("--drc", drc))


@tool()
def lint_board(board: str, preset: str = "T", layer_plan: Optional[str] = None,
               thresholds: Optional[str] = None) -> Dict[str, Any]:
    """Tidiness score with pass/warn/fail per metric (segments per mm, zigzag, off-angle segments,
    jogs, vias on power nets, layer directions, tracks on plane layers, non-GND pours, dangling ends,
    silkscreen over pads, part-row alignment). layer_plan: JSON file of layer roles."""
    return _run(["lint", board, "--preset", preset] + _flag("--layer-plan", layer_plan)
                + _flag("--thresholds", thresholds))


@tool()
def check_decisions(file: str, checkpoint: Optional[str] = None) -> Dict[str, Any]:
    """Blank rows in PCB_DECISIONS.md (any language). checkpoint: CP0, CP1, CP2, CP4 or CP6 -
    ok is False while anything that checkpoint needs is blank or unconfirmed."""
    return _run(["decisions", file] + _flag("--checkpoint", checkpoint))


@tool()
def run_drc(board: str, refill: bool = False, parity: bool = False, save: bool = False) -> Dict[str, Any]:
    """kicad-cli DRC summarised: violations by type, unconnected items per net, schematic parity.
    refill=True refills zones on a copy; with save=True KiCad saves the refilled zones into the
    board file itself (needed before previews, lint fill areas and fab output)."""
    return _run(["drc", board] + _flag("--refill", refill or save) + _flag("--save", save) + _flag("--parity", parity))


@tool()
def run_erc(schematic: str) -> Dict[str, Any]:
    """kicad-cli ERC summarised by type."""
    return _run(["erc", schematic])


@tool()
def place_fit_check(board: str, keepouts: Optional[List[str]] = None, edge_min: float = 0.0,
                    ignore: Optional[List[str]] = None) -> Dict[str, Any]:
    """Courtyard overlaps, courtyard distance to the board edge, silkscreen past the edge (silk_edge),
    parts inside keep-out rectangles.
    keepouts: ["x0,y0,x1,y1,reason", ...] in mm."""
    argv = ["place", "fit-check", board, "--edge-min", str(edge_min)]
    for k in keepouts or []:
        argv += ["--keepout", k]
    return _run(argv + (["--ignore", ",".join(ignore)] if ignore else []))


@tool(read_only=False)
def place_move(board: str, ref: str, x: float, y: float, rot: Optional[float] = None) -> Dict[str, Any]:
    """Move (and optionally rotate) one footprint; pads and texts follow. Returns a fit check.
    On "live" this is one undoable KiCad commit."""
    return _run(["place", "move", board, ref, str(x), str(y)] + _flag("--rot", rot))


@tool(read_only=False)
def place_row(board: str, refs: List[str], start_x: float, start_y: float, pitch: float, axis: str = "x",
              rot: float = 0.0) -> Dict[str, Any]:
    """Line parts up in one row at a fixed pitch and angle (an aligned resistor row)."""
    return _run(["place", "row", board, "--refs", ",".join(refs), "--start", f"{start_x},{start_y}",
                 "--pitch", str(pitch), "--axis", axis, "--rot", str(rot)])


@tool(read_only=False)
def place_edge(board: str, ref: str, side: str, inset: float = 0.0, courtyard_only: bool = False,
               entry: Optional[str] = None) -> Dict[str, Any]:
    """Move a part flush with a board edge (left, right, top, bottom): its courtyard and silkscreen
    lines, so no silkscreen crosses the edge. courtyard_only=True ignores the silkscreen.
    entry="auto" also turns a known connector so the wire or plug goes in from outside the board
    (screw terminals, JST PH/XH/EH, barrel jack, footprints with a PCB Edge mark); or give the side
    it enters from at rotation 0. edge_mark in the result: inside_mm > 0 means the maker's PCB
    Edge mark is inside the board edge (use a negative inset to follow it)."""
    return _run(["place", "edge", board, ref, "--side", side, "--inset", str(inset)]
                + _flag("--courtyard-only", courtyard_only) + _flag("--entry", entry))


@tool(read_only=False)
def route_path(board: str, net: str, layer: str, points: List[str], width: Optional[float] = None,
               dry_run: bool = False, any_angle: bool = False) -> Dict[str, Any]:
    """Route pad -> bend points -> pad. points: ["U1.3", "12.5,30", "J1.2"] (REF.PAD or x,y in mm).
    Written only if every segment is 0/45/90 degrees and keeps the netclass clearance to other
    copper and the edge; otherwise ok=False with every conflict. width defaults to the netclass."""
    return _run(["route", "path", board, "--net", net, "--layer", layer, "--points", " ".join(points)]
                + _flag("--width", width) + _flag("--dry-run", dry_run) + _flag("--any-angle", any_angle))


@tool(read_only=False)
def route_cleanup(board: str, nets: Optional[List[str]] = None) -> Dict[str, Any]:
    """Merge collinear segments and drop zero-length ones."""
    return _run(["route", "cleanup", board] + (["--nets", ",".join(nets)] if nets else []))


@tool()
def route_lane(lines: List[Dict[str, Any]], entry: Optional[List[str]] = None) -> Dict[str, Any]:
    """Crossing-free order of lines in a lane. lines: [{"net": "A", "exit": 12.5, "turn": "right"}];
    entry: the order they arrive in - returns the pairs that would cross."""
    return _run(["route", "lane", "--lines", json.dumps(lines)] + (["--entry", ",".join(entry)] if entry else []))


@tool(read_only=False)
def export_previews(board: str, out_dir: str = "previews", dpi: int = 150) -> Dict[str, Any]:
    """Routing, assembly and inner-layer PDFs (+ PNG) and the 1:1 fit-check PDF (writes into out_dir)."""
    return _run(["previews", board, "--out-dir", out_dir, "--dpi", str(dpi)])


@tool()
def trace_drop(board: str, net: str, source: str, loads: Dict[str, float], outer_um: float = 35.0,
               inner_um: float = 17.5, temp_c: float = 40.0, dt_limit: float = 20.0) -> Dict[str, Any]:
    """Voltage drop and IPC-2221 temperature rise along a net's tracks. source: "J1.1";
    loads: {"U3.8": 0.15} (amps)."""
    argv = ["tracedrop", board, "--net", net, "--source", source, "--outer-um", str(outer_um),
            "--inner-um", str(inner_um), "--temp-c", str(temp_c), "--dt-limit", str(dt_limit)]
    for pad, amps in loads.items():
        argv += ["--load", f"{pad}={amps}"]
    return _run(argv)


@tool(read_only=False)
def export_fab(board: str, out_dir: str = "fab", refill: bool = False, zip_name: Optional[str] = None,
               readme: Optional[str] = None, layers: Optional[List[str]] = None) -> Dict[str, Any]:
    """Gerbers (all copper, masks, silkscreens, Edge.Cuts) + Excellon drill (PTH/NPTH separate) into
    out_dir/gerber, a zip with README.txt and SHA256SUMS.txt, then a readback of the zip against the
    board (size, copper count, PTH, NPTH). readme: path of a text file with the board spec for the
    fab. refill=True refills and saves the zones first. Nothing is uploaded or ordered."""
    return _run(["fab", board, "--out-dir", out_dir] + _flag("--refill", refill) + _flag("--zip", zip_name)
                + _flag("--readme", readme) + (["--layers", ",".join(layers)] if layers else []))


@tool()
def gerber_readback(bundle: str, expect_size: Optional[str] = None, expect_copper: Optional[int] = None,
                    expect_pth: Optional[int] = None, expect_npth: Optional[int] = None) -> Dict[str, Any]:
    """Read a fab zip or folder like a fab would: layer functions, copper order (from X2 attributes),
    outline size, PTH/NPTH counts; compares against expected values (expect_size "100x80")."""
    return _script("gerber_readback.py", [bundle, "--markdown"] + _flag("--expect-size", expect_size)
                   + _flag("--expect-copper", expect_copper) + _flag("--expect-pth", expect_pth)
                   + _flag("--expect-npth", expect_npth))


@tool()
def compare_gerbers(old: str, new: str) -> Dict[str, Any]:
    """Geometry diff of two Gerber/drill bundles; ok=True means the geometry is identical."""
    return _script("compare_gerbers.py", [old, new])


def _script(name: str, args: List[str]) -> Dict[str, Any]:
    import subprocess
    from pathlib import Path
    script = Path(__file__).resolve().parents[1] / "scripts" / name
    result = subprocess.run([sys.executable, str(script), *args], capture_output=True, text=True, encoding="utf-8",
                            errors="replace")
    return {"ok": result.returncode == 0, "exit_code": result.returncode,
            "result": {"text": result.stdout.strip(), "stderr": result.stderr.strip()[-2000:]}}


# ---------------------------------------------------------------- JSON schema from signatures

def _schema_of(tp) -> Dict[str, Any]:
    origin = typing.get_origin(tp)
    args = typing.get_args(tp)
    if origin is typing.Union:
        rest = [a for a in args if a is not type(None)]
        return _schema_of(rest[0]) if len(rest) == 1 else {}
    if tp is str:
        return {"type": "string"}
    if tp is bool:
        return {"type": "boolean"}
    if tp is int:
        return {"type": "integer"}
    if tp is float:
        return {"type": "number"}
    if origin in (list, List):
        return {"type": "array", "items": _schema_of(args[0]) if args else {}}
    if origin in (dict, Dict) or tp is dict:
        return {"type": "object"}
    return {}


def input_schema(fn: Callable) -> Dict[str, Any]:
    import inspect
    hints = typing.get_type_hints(fn)
    props, required = {}, []
    for name, param in inspect.signature(fn).parameters.items():
        props[name] = _schema_of(hints.get(name, str))
        if param.default is inspect.Parameter.empty:
            required.append(name)
        elif param.default is not None:
            props[name]["default"] = param.default
    return {"type": "object", "properties": props, "required": required}


def tool_list() -> List[Dict[str, Any]]:
    return [{"name": t["fn"].__name__, "description": (t["fn"].__doc__ or "").strip(),
             "inputSchema": input_schema(t["fn"]),
             "annotations": {"readOnlyHint": t["read_only"], "destructiveHint": t["destructive"],
                             "idempotentHint": t["read_only"], "openWorldHint": False}} for t in TOOLS]


# ---------------------------------------------------------------- servers

PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")


def handle(message: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """One JSON-RPC message of the built-in server; returns the response (None for notifications)."""
    method, msg_id = message.get("method"), message.get("id")
    if msg_id is None:
        return None
    params = message.get("params") or {}
    if method == "initialize":
        version = params.get("protocolVersion")
        result = {"protocolVersion": version if version in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0],
                  "capabilities": {"tools": {"listChanged": False}},
                  "serverInfo": {"name": NAME, "version": __version__}, "instructions": INSTRUCTIONS}
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        result = {"tools": tool_list()}
    elif method == "tools/call":
        fns = {t["fn"].__name__: t["fn"] for t in TOOLS}
        fn = fns.get(params.get("name"))
        if fn is None:
            return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": -32602, "message": f"unknown tool {params.get('name')}"}}
        try:
            data = fn(**(params.get("arguments") or {}))
        except TypeError as exc:
            return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": -32602, "message": str(exc)}}
        result = {"content": [{"type": "text", "text": json.dumps(data, ensure_ascii=False)}],
                  "structuredContent": data, "isError": not data.get("ok", False) and data.get("exit_code") == 2}
    else:
        return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": -32601, "message": f"method not found: {method}"}}
    return {"jsonrpc": "2.0", "id": msg_id, "result": result}


def serve_builtin(stdin=None, stdout=None) -> None:
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except ValueError:
            response = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}}
        else:
            response = handle(message)
        if response is not None:
            stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
            stdout.flush()


def serve(prefer_sdk: bool = True) -> None:
    server_cls = None
    if prefer_sdk:
        try:
            from mcp.server.mcpserver import MCPServer as server_cls      # mcp 2.x
        except ImportError:
            try:
                from mcp.server.fastmcp import FastMCP as server_cls      # mcp 1.x
            except ImportError:
                server_cls = None
    if server_cls is None:
        serve_builtin()
        return
    from mcp.types import ToolAnnotations
    try:
        server = server_cls(NAME, instructions=INSTRUCTIONS, version=__version__)
    except TypeError:                                        # mcp 1.x has no version argument
        server = server_cls(NAME, instructions=INSTRUCTIONS)
    for t in TOOLS:
        server.add_tool(t["fn"], annotations=ToolAnnotations(readOnlyHint=t["read_only"],
                                                             destructiveHint=t["destructive"],
                                                             idempotentHint=t["read_only"], openWorldHint=False))
    server.run("stdio")
