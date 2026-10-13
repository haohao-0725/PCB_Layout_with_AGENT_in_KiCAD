# Generating schematics and boards with scripts (optional)

Edit small or one-off boards directly in KiCad. Generator scripts pay off in two cases: boards
with many repeated units (multi-axis, multi-channel), and boards you expect to revise several
times after checking against the real parts. Change one parameter, rerun, and the whole board
updates consistently, with no forgotten manual edit.

The notes below were verified on **KiCad 10.0.x with the SWIG `pcbnew` bindings**. KiCad has
deprecated these bindings in favour of the IPC API (`kicad-python`) and plans to remove them in
a future major version. For new long-lived generators, check which API your KiCad version
supports first.

## 1. Structure

| Script | What it does | It is the source of truth for |
|---|---|---|
| `build_*.py` | Writes the schematic, a manifest (JSON: each part's reference, value, footprint, pin nets, DNP, silkscreen name, notes), the BOM, custom footprints, and design rules and netclasses | The circuit |
| `place_*.py` | Starts from a base board (outline, mounting holes, module outline reference lines), loads footprints from the manifest, sets nets and schematic links, places parts from the parameters at the top of the file, tidies the silkscreen | Positions |
| `route_*.py` | Clears old tracks and zones; one function per routing group; creates the GND plane(s) and fills zones | Routing |
| `validate_*.py` | Schematic stage: manifest / netlist / firmware pins. PCB stage: pad nets and routing rules | Check rules |
| `export_*.py`, `readback_*.py` | Fab files, readback, previews | — |
| `rebuild_*.py` | The single entry point. Runs the steps in order, prints one result line per step, stops at the first failure, refuses to run while `~*.lck` files exist (KiCad has the project open) | — |

Principles:

- **One source of coordinates.** Derive positions and routes from **pad coordinates and one set
  of parameters**. Never hide separate coordinate sets in several scripts.
- **Placement parameters live at the top of the file:** base point of each repeated unit,
  spacing, resistor-row order. One function generates each repeated unit.
- **One routing function per group.** Its docstring says how the group is routed: layer, lane,
  where it changes layer.
- **Commit generated files with the scripts.** Generated files (`.kicad_sch`, `.kicad_pcb`,
  reports, fab files) go in the same commit as the script change. The user should not edit
  generated files in KiCad; if they do, port the change back into the scripts.

### A small routing helper (sketch)

```python
class Router:
    def pad(self, ref, number, pick=min):      # pad centre (x, y) in mm; pick chooses among same-numbered pads
    def path(self, net, layer, width, points):  # add segments along the points, skipping zero-length ones
    def via(self, net, xy, size=0.8, drill=0.4)
```

Describe each route as "from this pad → bend points → target pad". Compute the bend points
from pad coordinates, so they move with the placement when you rerun.

## 2. Making a generated board pass schematic parity

- **Schematic link.** Set the footprint's schematic path:
  `fp.SetPath(KIID_PATH('/<root uuid>/<sheet uuid>/<symbol uuid>'))`. The UUIDs must match the
  schematic, so use a deterministic UUID rule in the generator.
- **Description field.** The footprint's `Description` field must equal the symbol's
  Description.
- **Unconnected pins.** A pin left unconnected in the schematic appears in the netlist as a
  single-pin net named `unconnected-(REF-PinName-PadN)`. Create a net with exactly that name
  on the board and assign it to the pad. A `/` in the name is written as `{slash}`.
- **Other fields.** Value, footprint name and DNP state must match too.

## 3. pcbnew Python notes (KiCad 10)

- **Interpreter.** Run with KiCad's bundled Python. On Windows set `PYTHONUTF8=1`.
- **Saving.** Use `pcbnew.SaveBoard(path, board, True)`; with the third argument `True` it does
  not also rewrite the `.kicad_pro`. Save to a temporary folder first, then copy into place.
- **Deleting.** Use `board.Delete(item)`, not `Remove`; `Remove` causes trouble when footprints
  are loaded again later.
- **Assert dialogs.** Some calls raise a wxWidgets assert dialog on the user's desktop and block
  the script until it is closed. Two causes are known:
  - geometry on an empty `BOX2I`: compute outlines with plain tuples and skip empty boxes;
  - calling `GetWidth()` on a via: filter `GetTracks()` by `GetClass()` first.

  If a script seems to hang, check the desktop for a dialog. `Adding duplicate image handler` on
  stderr is harmless.
- **Paper size.** `PAGE_INFO` can't be set from Python. Save the board, then edit the
  `(paper "...")` text.
- **Negative coordinates.** `kicad-cli pcb export pdf` crops them. If anything sits above the
  outline (e.g. a module outline), export a shifted copy (`export_previews.py` does this).
- **Board size.** Measure it from the endpoints of the Edge.Cuts segments. A bounding box
  includes the line width (e.g. 100.05 instead of 100).
- **Text boxes.** The bounding box of 1 mm text is about 1.7 mm tall, including padding. Allow
  for it when avoiding collisions.
- **Footprint text.** `fp.Add(text)` first, then set the absolute position and angle.
- **Wider thermal spokes on a pad.**
  ```python
  pad.SetLocalZoneConnection(ZONE_CONNECTION_THERMAL)
  pad.SetLocalThermalSpokeWidthOverride(FromMM(w))
  ```
  `Get…Override()` returns None or an integer.
- **Duplicate pad numbers.** Some library footprints have two pads with the same number on one
  metal part (e.g. fuse clips). If `duplicate_pad_numbers_are_jumpers` is off, connect both pads
  with copper, or DRC reports them as unconnected.

## 4. Automatic silkscreen placement

For each reference and functional name, try candidate positions in order:

1. Rules written for dense areas, e.g. "vertical, left of the part" or "stacked above the name".
2. Above, below, left and right of the outline.

Check each candidate:

- not on a pad (0.2 mm margin),
- not touching other silkscreen (0.15 mm),
- not near text already placed (0.6 mm),
- not off the board.

Try strictly first (not over other courtyards), then relax. If nothing fits, list the item for
a person or a new rule. Never leave it silently overlapping.

## 5. Files and versions

- **Don't rebuild while KiCad has the project open** (`~*.lck` exists). KiCad's save overwrites
  the result, so ask the user to close it first. KiCad may rewrite the `.kicad_pro` on close
  (expanding defaults); a rebuild writes the generator's version back.
- **Stored hashes go stale.** If check records store file hashes, git line-ending conversion
  (`core.autocrlf=true`) and KiCad re-saves both invalidate them. Re-run the step from the
  source; don't hand-edit hashes. A `.gitattributes` with `*.kicad_* -text` avoids the
  line-ending part.
- **Compare Gerbers by geometry.** Gerber headers contain the creation date, so bytes change on
  every rebuild. Use `scripts/compare_gerbers.py`.
- **Before a new revision,** copy the fab files that were ordered into an archive folder, then
  change the revision number and output names.
