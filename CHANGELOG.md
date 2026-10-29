# Changelog

## 0.2.0 (prepared 2026-10-29, not yet tagged)

- `kcp` board tools, standard-library Python 3.9+, no `pcbnew`:
  - `inspect`: the board as JSON (outline, layers, stackup, footprints, pads, nets, tracks, vias,
    zones; unconnected items from kicad-cli with `--drc`).
  - `lint`: tidiness score per preset (T/C/R) with pass/warn/fail; thresholds in
    `kcp/presets/lint.json`. Metrics: segments per mm and per connection, off-angle segments,
    turns per 10 mm, S-bend jogs, vias on power nets and per signal connection, layer
    main-direction conformity (with a layer plan), tracks on GND plane layers, non-GND pours,
    dangling ends, silkscreen over pads, part-row alignment.
  - `decisions`: blank rows in `PCB_DECISIONS.md` in any language; `--checkpoint` readiness.
  - `drc` / `erc`: kicad-cli reports summarised; DRC runs on a temporary copy.
  - Reads KiCad 10 boards (nets by name) and the older numbered-net format.
- `SKILL.md`: which stage calls which tool; layer plan saved as JSON for the lint.
- `examples/`: saved Part A defaults, layer plans (4L-S1, 4L-S2, 2L-a).
- `pyproject.toml` for an optional `pip install` (console script `kcp`).
- Board building on the file backend: `kcp.wiring` (schematic from a wiring plan; KiCad's own
  netlist read back for nets and parity), `kcp.board`, `kcp.footprints`, `kcp.place` (move, rows,
  arrays, edge placement, fit check), `kcp.route` (0/45/90 paths checked for clearance before
  writing, `bus` fan-outs, `lane_order`, `cleanup`), `kcp.previews`, `kcp.tracedrop`.
- `scripts/export_previews.py` and `scripts/trace_drop.py` ported to the file backend: same options,
  any Python 3.9+, no `pcbnew`. Nothing bundled imports `pcbnew` any more.
- MCP server (`kcp mcp`, registered in `plugin.json`): 16 tools, one per command; official SDK when
  installed (mcp 1.x FastMCP or 2.x MCPServer), built-in stdio server otherwise.
- Live mode through KiCad's IPC API (`kicad-python`): pass `live` instead of a board file; every
  edit is one KiCad commit that Ctrl+Z undoes. Tested against a stand-in for `kipy` only.
- Example `examples/stepper-carrier-2axis/`: NUCLEO-F446ZE + 2 × TMC2209 carrier generated from the
  wiring plan to the fab zip by one rebuild script; ERC/DRC/parity 0, no vias, lint passes preset
  T, Gerber readback matches. Decision file, brief, order spec and bring-up sheet included.
- References: rules the tools enforce now name the tool; `kicad-scripting.md` rewritten for the
  file backend; regenerated-energy check stresses driver voltage margin; pull-up placement tip.
- Fixes: the Gerber scripts print UTF-8 on any console (they crashed on cp950 Windows consoles).
- Tests: s-expression round trip, geometry, board model, all tools, building, routing, MCP and
  live backend (74 in total), plus a hand-written 4-layer test board that KiCad's own DRC confirms.

## 0.1.0 (first public release)

- Seven-stage KiCad workflow with four user checkpoints; no routing before placement is
  confirmed on a 1:1 printout.
- Design presets (Tidy, Compact, Robust) and 17 adjustable preference axes.
- `PCB_DECISIONS.md` handshake template: scope check, preferences, yes/no decisions for add-on
  circuits and technical checks, checkpoint sign-off, change log.
- Layout rules per style, circuit policy (add-on classes A–D, ratings, reverse-polarity options,
  regenerated energy), routing playbook with stackup options, verification and order-spec guide,
  Taiwan ordering notes, KiCad 10 scripting notes.
- Scripts: `export_previews.py`, `trace_drop.py` (voltage drop + IPC-2221 temperature rise,
  arcs, parallel paths, temperature-corrected copper), `gerber_readback.py` (layer order from X2
  attributes, outline, PTH/NPTH counts), `compare_gerbers.py` (geometry diff incl. arcs and slots).
- Unit tests for the parts of the scripts that run without KiCad.
