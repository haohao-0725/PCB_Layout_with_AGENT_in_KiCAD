# Generating schematics and boards with scripts (optional)

Edit small or one-off boards directly in KiCad. Generator scripts pay off in two cases: boards
with many repeated units (multi-axis, multi-channel), and boards you expect to revise several
times after checking against the real parts. Change one parameter, rerun, and the whole board
updates consistently, with no forgotten manual edit.

Use the bundled `kcp` package (Python 3.9+, standard library only). It reads and writes the KiCad
files directly, so it needs no `pcbnew`. KiCad has deprecated the SWIG `pcbnew` bindings and plans
to remove them in KiCad 11; **don't write new generators on SWIG.** A complete worked example is
`examples/stepper-carrier-2axis/` in the skill's repository.

## 0. Starting a project: `kcp new`

```bash
python <skill>/kcp new my_board --copper 2      # or --copper 4
python my_board/rebuild_my_board.py             # run it once before changing anything
```

It writes the four scripts of §1 plus `kcp_path.py` and `layer_plan.json` for a placeholder
circuit (input header, capacitor, resistor, LED, four mounting holes). The placeholder passes
ERC, the netlist check, the fit check, DRC with parity, lint (preset T) and the Gerber readback,
so any later failure comes from your change. Then, in this order:

1. `build_<name>.py`: replace `SYMBOLS`, `PARTS`, `HOLES` and `NETCLASSES` with the confirmed
   wiring plan (CP1, CP2). Custom footprints from measured numbers go in a `.pretty` folder
   (`kcp.footprints.tht_footprint`) listed in `FOOTPRINT_LIBS`.
2. `place_<name>.py`: `BOARD`, `PLACEMENT`, `KEEPOUTS`, `SILK`. Run `--until pcb` and read the
   real pad positions and courtyards with `kcp inspect <board> --refs ...` before adjusting.
3. After CP4: one function per group in `route_<name>.py`.
4. `rebuild_<name>.py`: `PRESET`, `FAB_README` (the board spec from the order spec), and a
   voltage-drop step for nets above about 1 A.

**Finding kcp from a project folder.** The scripts start with `import kcp_path`, which puts kcp
on `sys.path`: `$KCP_SKILL` first, then the skill folder recorded by `kcp new`, an installed kcp
(`pip install`), the newest kicad-clean-pcb plugin in `~/.claude/plugins/cache/`, then
`~/.claude/skills/` and `~/.agents/skills/`. Set `KCP_SKILL` when the skill moves.

## 1. Structure

| Script | What it does | It is the source of truth for | kcp modules |
|---|---|---|---|
| `build_*.py` | The wiring plan: parts, the net on every pin, custom footprints from measured numbers, netclasses and rules. Writes the schematic, symbol library, lib tables, project file, BOM, manifest | The circuit | `kcp.wiring`, `kcp.project`, `kcp.footprints.tht_footprint` |
| `place_*.py` | Board outline, planes, every footprint at the positions from the parameters at the top of the file; silkscreen; fit check | Positions | `kcp.board`, `kcp.footprints`, `kcp.place` |
| `route_*.py` | One function per routing group; paths derived from pad coordinates | Routing | `kcp.route` |
| `rebuild_*.py` | The single entry point. One result line per step, stops at the first failure, refuses to run while `~*.lck` files exist | — | `kcp.kicad_cli`, `kcp.lint`, `kcp.previews`, `kcp.tracedrop`, `kcp.fab` |

Principles:

- **One source of coordinates.** Derive positions and routes from **pad coordinates and one set
  of parameters** (`router.pad("U1", 3)`). Never hide separate coordinate sets in several scripts.
- **Placement parameters live at the top of the file:** base point of each repeated unit,
  spacing, row order. Place a repeated unit once as a template and copy it with
  `kcp.place.array`; line rows up with `kcp.place.row`.
- **One routing function per group.** Its docstring says how the group is routed: layer, lane,
  where it changes layer.
- **Commit generated files with the scripts.** Generated files (`.kicad_sch`, `.kicad_pcb`,
  reports, fab files) go in the same commit as the script change. The user should not edit
  generated files in KiCad; if they do, port the change back into the scripts.

## 2. Schematic and parity: let KiCad make the netlist

- **Draw the schematic from the wiring plan** with `kcp.wiring.write_schematic`: one flat sheet,
  every pin gets a short wire and a global label with its net, unconnected pins get a no-connect
  flag, all pins are passive. `Design.problems()` catches single-pin nets, missing pins and
  duplicate references before anything is drawn. Run `kcp erc` and get it to 0 / 0.
- **Read the netlist back from KiCad** with `kcp.wiring.read_netlist` (it runs `kicad-cli sch
  export netlist`), compare it with the plan (`check_against_design`), and build the board from
  it: nets per pad, value, fields and the footprint's schematic path all come from KiCad's own
  netlist, so `kcp drc --parity` passes the way "Update PCB from schematic" would. Unconnected
  pins get KiCad's own `unconnected-(REF-PinName-PadN)` net names this way.
- **Symbol library.** Write the project symbol library from the same definitions
  (`write_symbol_library`) and point `sym-lib-table` at it (`write_lib_tables`), so ERC finds no
  library mismatch.
- **Project file.** `kcp.project.write_project(path, info["root_uuid"], netclasses, rules)` writes
  the `.kicad_pro`: design rules (`DEFAULT_RULES`, prototype-fab minimums, overridden by `rules`),
  netclasses as `(name, track width, clearance, [net patterns])` and the root sheet that
  `write_schematic` returned. `NetClasses.from_project` reads it back for the router.

## 3. Board building on the file backend (`kcp.board`, `kcp.footprints`)

- **New board:** `BoardBuilder.new(copper=4, thickness=1.6)` writes the layer table and a stackup;
  `outline_rect`, `add_zone`, `add_text`, `add_rect` (e.g. module outlines on `Dwgs.User`).
- **Footprints:** `FootprintLibrary(project_dir)` resolves `Nickname:Name` through the project's
  `fp-lib-table`, then KiCad's own libraries. `place_footprint` copies the library footprint,
  keeps its geometry in footprint-local coordinates and adds the rotation to pad and text angles
  (the board file stores those as absolute angles). Copying the library footprint unchanged
  keeps DRC's library-mismatch check quiet.
- **Board-only parts** (mounting holes): `place_footprint(..., board_only=True)`; they need no
  symbol.
- **Moving and texts:** `kcp.place.move` rotates pads and texts with the footprint;
  `kcp.place.set_text` moves or hides a field such as the reference, and shows the `Silk` field
  on the silkscreen (`layer="F.SilkS", hide=False`; library footprints keep it hidden on F.Fab).
- **Edge parts:** `kcp.place.to_edge` puts the courtyard and the silkscreen lines flush with the
  edge and keeps the other coordinate. Many library terminals draw the pin-1 mark outside the
  courtyard, and KiCad's DRC flags silkscreen that crosses the edge (`silk_edge_clearance`);
  touching it is fine. Call it after the footprints are added, on the builder:

  ```python
  from kcp.place import to_edge
  EDGE = {"J1": ("bottom", "auto"), "J2": ("left", None)}       # ref: (board side, entry)
  for ref, (side, entry) in EDGE.items():
      result = to_edge(builder, ref, side, entry=entry)          # {"at": [x, y, rot], "entry", "edge_mark"?}
  ```

  `entry="auto"` turns the part so the wire or plug goes in from outside the board, for the
  connectors in `kcp.place.ENTRY_SIDES` (layout-rules.md §1) and footprints with a "PCB Edge" mark;
  any other connector raises an error that asks for the side it enters from at rotation 0
  (`"left"`, `"right"`, `"top"`, `"bottom"`, as seen in KiCad's 3D viewer). `entry=None` keeps
  the rotation. `edge_mark.inside_mm` > 0 means the maker's PCB Edge mark lies that far inside
  the board edge (USB receptacles meant to overhang): pass `inset=-inside_mm` to follow it, and
  expect the silkscreen past the edge to need `silk=False` or a moved outline. `kcp new` writes
  this loop into `place_<name>.py`. The lower-level `at_edge(fp, outline, side)` only computes the
  position.
- **Zones are written unfilled.** `kcp.kicad_cli.refill_zones(board)` (CLI:
  `kcp drc board --refill --save`) has KiCad fill them and save the board in its own formatting;
  do that before DRC, previews, lint fill areas and fab output.
- **Writes refuse while KiCad has the project open** (`~*.lck`): KiCad's next save would overwrite
  them. Ask the user to close KiCad.

## 4. Routing (`kcp.route`)

```python
r = Router(builder, NetClasses.from_project(board_path.with_suffix(".kicad_pro")))
a, b = r.pad("U1", 3), r.pad("J1", 2)
r.path("SIG", "F.Cu", None, [a, (a[0] + 5, a[1]), b])          # width from the netclass
bus(r, [(net, start, end), ...], "F.Cu", bend=20.0)             # fan-out with one 45-degree step each
```

- Describe each route as "from this pad → bend points → target pad"; compute the bend points
  from pad coordinates, so they move with the placement.
- The router refuses any segment that is not 0/45/90° and any segment closer to other copper than
  the netclass clearance (the larger of the two nets) or to the board edge. Nothing is written on a
  conflict; `RouteConflict.conflicts` lists every problem. Change the path, don't loosen rules.
- `bus(router, lines, layer, bend, width=None, axis="x")`: each line leaves its start along
  `axis`, turns at that coordinate (`bend`), takes one 45° section to the end's other coordinate
  and runs on to the end. `axis="y"` for lines that leave vertically. It refuses lines whose order
  differs at the two ends: fix the order (pin order, row order) first. `lane_order` gives the
  crossing-free order for a lane (routing-playbook.md §3).
- `cleanup` merges collinear segments and drops zero-length ones.
- A generator reroutes everything on each run (`builder.remove(["segment", "arc", "via"])` first),
  so commit per stage or per routing change rather than per group.

## 4a. Fab output (`kcp.fab`)

`kcp.fab.export(board, out_dir, zip_name, layers=None, readme=spec_text)` (CLI: `kcp fab`) writes
Gerbers (all copper, masks, silkscreens, Edge.Cuts) and Excellon drill files (PTH and NPTH
separate) into `out_dir/gerber/`, zips them with README.txt (your spec text, then the copper layer
order read back from the X2 attributes) and SHA256SUMS.txt, and reads the zip back against the
board: outline size, copper layers, PTH and NPTH counts (`kcp.fab.expected(board)`). `ok` is False
on any mismatch.

## 5. Automatic silkscreen placement

For each reference and functional name, try candidate positions in order:

1. Rules written for dense areas, e.g. "vertical, left of the part" or "stacked above the name".
2. Above, below, left and right of the outline.

Check each candidate:

- not on a pad (0.2 mm margin),
- not touching other silkscreen (0.15 mm),
- not near text already placed (0.6 mm),
- not off the board.

`kcp lint` reports silkscreen over pads; DRC reports silk overlaps. `kcp drc` lists each one in
`details` with the part, the item ("R1 Reference text (F.SilkS)", "J1 pad 2 [GND]", "U1 line on
F.SilkS") and its position, named from the board file so the list reads the same in any KiCad UI
language (`kcp.kicad_cli.list_violations(report, load_board(path).root)` in a script). If
nothing fits, list the item for a person or a new rule. Never leave it silently overlapping.

## 6. Files and versions

- **Board file format.** `kcp` reads KiCad 10 boards (nets written by name) and the older format
  with numbered nets.
- **Don't rebuild while KiCad has the project open** (`~*.lck` exists). KiCad's save overwrites
  the result. KiCad may rewrite the `.kicad_pro` on close (expanding defaults); a rebuild writes
  the generator's version back.
- **kicad-cli writes a `.kicad_prl`** next to the files it opens. `kcp drc` runs on a temporary
  copy unless schematic parity is requested. Keep `*.kicad_prl` out of git.
- **Stored hashes go stale.** If check records store file hashes, git line-ending conversion
  (`core.autocrlf=true`) and KiCad re-saves both invalidate them. Re-run the step from the
  source; don't hand-edit hashes.
- **Compare Gerbers by geometry.** Gerber headers contain the creation date, so bytes change on
  every rebuild. Use `scripts/compare_gerbers.py`; after refactoring a generator it should report
  "geometry identical".
- **Before a new revision,** copy the fab files that were ordered into an archive folder, then
  change the revision number and output names.

## 7. Legacy pcbnew notes (only for existing SWIG generators)

- Run with KiCad's bundled Python; on Windows set `PYTHONUTF8=1`. The bindings are gone in KiCad 11.
- `pcbnew.SaveBoard(path, board, True)` does not rewrite the `.kicad_pro`; use `board.Delete(item)`,
  not `Remove`.
- Some calls raise a wxWidgets assert dialog and block the script: geometry on an empty `BOX2I`,
  and `GetWidth()` on a via. Filter `GetTracks()` by `GetClass()` first.
- `PAGE_INFO` can't be set from Python: save, then edit the `(paper ...)` text.
- Footprint schematic path: `fp.SetPath(KIID_PATH('/<sheet uuids>/<symbol uuid>'))`, taken from
  the netlist, not invented.
