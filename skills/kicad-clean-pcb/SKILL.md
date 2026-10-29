---
name: kicad-clean-pcb
description: >-
  End-to-end KiCad PCB workflow with human checkpoints. Pick a design profile first (tidy and
  readable, compact and shortest, or maximum electrical robustness). Then plan the hardware and
  wiring, fill parts gaps, and draw the schematic. Place parts and get the user's sign-off on a
  1:1 printout before any routing. Route in structured groups, run checks, and produce Gerbers,
  drill files and an order spec. Decisions are recorded in a yes/no checklist file. Use this
  skill whenever the user wants to design, lay out, route, review or order a PCB in KiCad,
  even if KiCad isn't named. This includes turning a perfboard, breadboard, jumper-wire or
  module-stack prototype into a carrier board, and questions about placement, trace width,
  copper pours, Gerbers or fab ordering. Also for 畫 PCB, 電路板, 佈局, 走線, 載板, 洞洞板,
  打樣, 下單. Suited to low/medium-speed control, motor-driver and module-carrier boards. Not
  for RF, high-speed memory, mains-powered or isolated power designs.
license: MIT
compatibility: >-
  KiCad 10.0.x, tested on Windows 10. All bundled tools run on any Python 3.9+ (standard library
  only) and read or write the KiCad files directly; no pcbnew bindings are needed. kicad-cli is
  needed for DRC, ERC, netlists, previews and fab output; pdftoppm (Poppler) for PNG previews.
metadata:
  version: "0.1.0"
---

# KiCad PCB workflow with human checkpoints

Goal: a board that is wired correctly, fits the real parts, and is easy to assemble and debug.
Its layout should make sense to a person reading it. The user should not have to keep
correcting the agent along the way.

This skill exists to prevent three failure modes:

1. **A layout nobody can read.** Zigzag autorouted tracks, scattered parts, needless layer
   changes, and copper pours nobody asked for.
2. **Circuitry nobody asked for.** Protection, buffers, test points and jumpers the agent added
   on its own. They grow the board and the user has to remove them one by one later. The
   opposite also happens: protection the user would have wanted is silently skipped.
3. **Physical mismatches found after routing.** Examples: a USB port blocked by a header, a
   fuse-holder pitch that differs from the real part, a terminal that duplicates one already on
   a module. Fixing these after routing means rerouting.

The cure is the same for all three. Settle preferences and decisions with the user in writing,
at fixed checkpoints. Show the placement on a 1:1 printout before routing.

## The handshake file: `PCB_DECISIONS.md`

At stage 0, copy [assets/PCB_DECISIONS.template.md](assets/PCB_DECISIONS.template.md) into the
project, for example next to the `.kicad_pro`. Write it in the user's language. It holds:

- the scope check,
- the chosen profile and preferences (Part A),
- a yes/no decision for every add-on circuit (Part B),
- a yes/no decision for every optional technical check (Part C),
- the checkpoint sign-offs (Part D),
- a change log (Part E).

Rules:

- **The user fills the Decision column.** The agent writes its recommendation in its own column
  and never pre-fills the user's answer. The one exception is Part A, which may be pre-filled
  from the preset the user picked; the user then confirms Part A as a whole.
- **Blank means not approved.** Don't build an item that has no answer. Don't pass a checkpoint
  while any row it needs is blank.
- **Changing a decision goes in the change log** (date, from → to, reason, who asked). Never
  edit an answer silently.
- **Read the file at the start of every session** and don't re-ask what it already answers.
  Decisions made only in chat get lost after context compaction or in a new session.
- **Before giving a project-specific recommendation, add the row first.** If the project needs
  something the template doesn't list, add a row. Delete template rows that clearly don't apply,
  with a one-word reason.

## Stages and checkpoints

| Stage | Main output | User checkpoint |
|---|---|---|
| 0. Scope, profile and preferences | `PCB_DECISIONS.md` Part A | ✔ CP0 |
| 1. Hardware list, requirements, wiring plan | Project brief | ✔ CP1 (can be merged with CP0) |
| 2. Parts gaps and add-on decisions | BOM (on hand / to buy / substitute), measured dimensions, Parts B and C answered | ✔ CP2 |
| 3. Schematic | Schematic, ERC clean, netlist checked against the wiring plan | Only if questions come up |
| 4. Placement and confirmation | Unrouted placement, previews, 1:1 fit-check PDF | ✔ CP4: **no routing before this** |
| 5. Routing | Layer plan, routing in function groups, DRC after each group | Review at the end (or per group, per Part A) |
| 6. Verification and fab files | ERC/DRC/parity clean, Gerber + drill + readback, order spec | ✔ CP6 |
| 7. Close-out | One rebuild entry point, old files archived, handoff notes | — |

Put every open question of a checkpoint in one message as a list, with the recommended option
for each. Don't drip-feed questions.

## Tools by stage

Use the bundled tools instead of guessing coordinates or counting by eye. Run them as
`python <skill>/kcp <command> ...` (any Python 3.9+, no KiCad needed except for `drc`/`erc`).
Each prints JSON, or Markdown with `--markdown`; exit code 1 means the check failed, 2 means the
tool could not run. Details in [Bundled tools and scripts](#bundled-tools-and-scripts).

| Stage | Call | What it tells you |
|---|---|---|
| 0 | `kcp decisions PCB_DECISIONS.md --checkpoint CP0` | Blank scope and Part A rows before asking for CP0 |
| 2 | `kcp decisions PCB_DECISIONS.md --checkpoint CP2` | Every blank row in Parts B and C; CP2 cannot pass while it exits 1 |
| 3 | `kcp erc board.kicad_sch` | ERC errors and warnings by type |
| 4 | `kcp inspect board.kicad_pcb --summary` | Real positions, rotations, courtyards and pad nets: read them, don't recompute them |
| 4 | `kcp place row` / `edge` / `move`, then `kcp place fit-check --keepout ...` | Rows and edge connectors placed exactly; courtyard overlaps, edge distance, keep-outs in front of USB plugs |
| 4 | `kcp lint board.kicad_pcb --preset <A-preset>`, `kcp previews board.kicad_pcb` | Row alignment and silkscreen over pads; the previews and the 1:1 fit-check PDF for CP4 |
| 5 | `kcp route lane` before a group, `kcp route path` for each route | Crossing-free lane order; every path checked for 0/45/90° and clearance before it is written |
| 5 | `kcp drc board.kicad_pcb` and `kcp lint ... --layer-plan plan.json` after each group | New DRC issues, unconnected nets left, zigzags, off-angle segments, vias, tracks on plane layers |
| 5 | `kcp tracedrop board.kicad_pcb --net ... --source ... --load ...` | Voltage drop and temperature rise of power tracks (Part C C1/C2) |
| 6 | `kcp route cleanup`, `kcp drc board.kicad_pcb --refill --parity`, final `kcp lint`, `kcp decisions ... --checkpoint CP6` | Merged segments; native checks at zero; the lint table for the delivery summary; Part C results recorded |

`kcp lint` numbers support the visual review; they never replace it.

## Stage 0: scope, profile and preferences

1. **Scope check** (template, top section). Ask whether the board involves any of these:
   - mains voltage,
   - DC above 60 V,
   - lithium cell charging or packs,
   - controlled impedance or signals above ~50 MHz,
   - safety-critical or medical use.

   If yes, say plainly that this skill's rules are not enough for that part. Recommend the
   relevant standard or a qualified reviewer. Continue only on the parts it does cover.
2. **Profile.**
   - If `PCB_DECISIONS.md` already has Part A, use it.
   - If the user points to saved defaults (a previous project's file, or a note in their
     CLAUDE.md / AGENTS.md), copy that Part A and ask for one confirmation.
   - Otherwise read [references/preferences.md](references/preferences.md). Present the three
     presets in a short table, recommend one in a sentence, and let the user choose. Then show
     the preference axes with the preset's values, and ask once whether to change any.
   - Mark the axes marked "ask" explicitly: who draws, assembly method, fab, language.
3. From here on, apply Part A without asking again. Raise an exception only when the project
   makes a preference impossible (for example, a 2-layer board has no inner plane). Explain why
   and log the change.

## Stage 1: hardware, requirements, wiring plan

Start from what exists:

- prototype photos or wiring notes,
- firmware pin configuration (e.g. a CubeMX `.ioc` or a pin map),
- an existing BOM,
- module product pages or datasheets.

Fill [assets/PROJECT_BRIEF.template.md](assets/PROJECT_BRIEF.template.md) and ask only for what
is missing and affects the circuit, footprints or fabrication.

- **Hardware list.** For each module, IC and connector: part number and revision, quantity, pins
  used, supply, mounting (socket or soldered), and which dimensions are known.
- **Requirements.**
  - Functions and channel counts.
  - Supply rails: voltage and *measured* current. If there is no measurement, ask the user to
    read it from a bench supply under real operation.
  - Cables: who crimps them and which connectors.
  - Board limits: size, layers, mounting holes, enclosure.
- **Wiring plan.**
  - One table: function → MCU pin → board connector pin → module pin.
  - Harness pin orders.
  - Power tree: entry → fuse → protection → branches, with the current in each branch.
  - Grounding: a single GND net unless decided otherwise.
- **Operating access.** List the interfaces that are plugged in or pressed while the board runs:
  USB, debug headers, buttons, jumpers, terminal entries. Placement must keep them free.

## Stage 2: parts gaps and add-on decisions

- **BOM.** Derive the full BOM from the wiring plan and check it against the user's stock.
  Split it into "on hand", "to buy" and "substitute from stock". A part on hand that meets the
  rating target (see [references/circuit-policy.md](references/circuit-policy.md)) is used. Say
  how it differs from the ideal part: drop, heat, size.
- **Measured dimensions.** Ask the user to measure every real part that affects a footprint:
  - pitch,
  - lead diameter, or blade width and thickness,
  - body size and height,
  - capacitor diameter,
  - terminal entry direction,
  - module hole positions and anything protruding underneath.

  Say how to measure, e.g. "outer edge to outer edge" vs "centre to centre". Never take hole
  positions from photo pixels.
- **Pin map.** Build a map of function → symbol pin → footprint pad → physical position
  (top view, pin 1). Library double-row header numbering must be checked.
- **Parts B and C.** Fill them in `PCB_DECISIONS.md`. The agent's recommendation follows the
  add-on policy chosen in Part A (circuit-policy.md). Each row states the real problem it
  solves and its cost. The user answers Yes or No for each row. **CP2 passes only when every row
  is answered** (`kcp decisions PCB_DECISIONS.md --checkpoint CP2` lists what is still blank).

## Stage 3: schematic

- **Source of truth.** Decide what the CAD source is.
  - Small boards: edit in KiCad.
  - Boards with many repeated units, or that will be revised against the real parts several
    times: generator scripts (schematic, placement and routing kept separate). See
    [references/kicad-scripting.md](references/kicad-scripting.md).

  Write down "what to edit where". Never keep two editable copies.
- **Structure.**
  - Group by function, and give nets meaningful names.
  - Mark NC and DNP explicitly.
  - Tie unused IC inputs to a fixed level.
- **Netclasses.** Use separate classes for supply, high-current outputs and logic power. Widths
  and clearances come from stage 5 sizing.
- **Silkscreen names.** Keep the functional name of each module and connector in one field
  (e.g. `Silk`) that the PCB silkscreen reads, so a rename happens in one place.
- **Checks.**
  - ERC: 0 errors and 0 warnings.
  - Export the netlist and check it against the wiring plan line by line.
  - Script the checks of the contracts that matter most: MCU pins, addresses, current-sense
    direction.

## Stage 4: placement and confirmation

Apply [references/layout-rules.md](references/layout-rules.md) for the chosen layout style:

1. **Mechanics first.**
   - Outline estimate and mounting holes.
   - Module outlines.
   - Edge connectors, with the cable entry facing out.
   - Free space in front of operating interfaces.
   - Keep-outs under modules: header tails, height limits.
2. **Zones.** Functional zones, each next to its connector. Repeated units use one template.
3. **Passives.** Place them by function (rules per style). Decoupling capacitors go at the
   power pins.
4. **Routing corridors.** Reserve them: MCU breakout directions, power trunks, lane widths.
   Order parts to match the pin order at the destination so lines don't cross.
5. **A/B trials.** If an IC's orientation is unclear, try both and keep the cleaner one.
6. **Silkscreen.** No text on pads, no overlaps. Add functional names, pin 1 marks and power
   pin marks.

Send the user:

- a top-view preview,
- close-ups of dense areas,
- **the 1:1 fit-check PDF** from `scripts/export_previews.py`.

Ask them to print it at 100 %, measure the outline to confirm the scale, and then lay the real
parts and modules on the paper. They check:

- pins and holes,
- operating access,
- cable entry,
- part envelopes.

Revise until they confirm (CP4). **No routing before CP4.** After any later mechanical change,
print 1:1 again.

## Stage 5: routing

Read [references/routing-playbook.md](references/routing-playbook.md) first.

- **Layer plan.** Write it before routing: stackup from Part A, the use and main direction of
  each layer, and the width and clearance of each net group. Also save the layer roles as a small
  JSON file (`{"F.Cu": "horizontal", "In1.Cu": "plane", "B.Cu": "vertical"}`) so
  `kcp lint --layer-plan` can check main directions and tracks on plane layers.
- **Order.** Route by function group:
  1. power,
  2. high-current outputs,
  3. differential and encoder inputs,
  4. local RC and filters,
  5. analog,
  6. MCU control lines,
  7. everything else.

  After each group, run DRC and look at a close-up. With git, commit each group.
- **Geometry and vias** follow Part A.
- **Sizing.** Size power tracks for both voltage drop and temperature rise with
  `scripts/trace_drop.py`, against the current target and ΔT limit in Part A. If either is too
  high, widen the track first. Then consider moving it to an outer layer or paralleling it on
  two layers. Only then propose heavier copper.
- **Getting stuck.** If the same local problem fails three attempts, stop. Don't keep swapping
  routers or patch scripts. Report the stuck nets, the obstacles, what was tried, and which
  placement or pin-order decision the user needs to make.

## Stage 6: verification and fab files

Read [references/checks-and-delivery.md](references/checks-and-delivery.md).

- **Native checks at zero.** ERC, DRC with zones refilled, unconnected items, and schematic
  parity must all be zero. Don't get there by ignoring rules, loosening widths or adding
  exclusions.
- **Every "Yes" in Part C** is executed and its result recorded.
- **Visual review.** Review the whole board and each layer. Trace a few representative nets per
  group: clear order, no zigzags, no needless layer changes, tidy rows, readable silkscreen.
  DRC passing does not replace this. Put the `kcp lint --markdown` table in the delivery summary,
  and explain every warn or fail that stays.
- **Fab files.**
  - Export Gerbers and Excellon drill files (PTH and NPTH separate).
  - Run `scripts/gerber_readback.py` against the native board values.
  - Take the layer-order table from its output. Inner-layer file extensions differ between KiCad
    versions, so never infer the order from extensions.
- **Order spec.** Write the spec, a message the user can paste to the fab, the questions to ask
  the fab, and suggested values for online order forms.
- **Regenerated files.** If fab files are regenerated after the user has seen them, run
  `scripts/compare_gerbers.py` before saying they are unchanged.
- **Ordering.** Never order, pay or upload to a fab on the user's behalf.

## Stage 7: close-out

- **One rebuild entry point.** For generator projects: schematic → placement → routing →
  checks → fab files. It stops on the first failure and refuses to run while KiCad has the
  project open (`~*.lck` files).
- **Archive old material.** Move old versions, trial tools and stale reports to an `archive/`
  folder marked "superseded". Don't leave a pile of routers that patch each other.
- **Handoff notes** (project README / AGENTS.md):
  - status,
  - links to important files,
  - a "to change X, edit Y" table,
  - the rebuild command,
  - the revision procedure: archive the fab files that were ordered before changing anything.

## Working principles

- **The working prototype is the baseline.** Change only what the user asked to change. Anything
  extra becomes a row in Part B, decided once.
- **Measure, don't guess.** Write down any temporary assumption and have the user check it on
  the 1:1 print.
- **Every stage leaves something the user can see:** previews, a PDF, a check summary. With git,
  commit once per stage.
- **CAD-clean is not hardware-verified.** DRC only proves the drawing is self-consistent.
  Waveforms, temperature and real plugging need the real board.
- **Report in the user's language.**
  - Lead with results, then the decisions or measurements needed. Numbers carry units.
  - When the user asks something like "can I remove this part?", answer with an estimate:
    "removing it saves 0.55 W but a reversed supply destroys all four drivers". A bare rule is
    not enough.
  - Label every claim as "CAD-checked", "estimated" or "needs hardware verification".

## Bundled tools and scripts

### `kcp/`: board tools (Python 3.9+, standard library only)

Run `python <skill>/kcp <command> --help` for every option.

| Command | Purpose |
|---|---|
| `inspect board.kicad_pcb [--summary] [--refs R1,R2] [--no-pads] [--drc]` | Board as JSON: outline size, layers and stackup; footprints (ref, value, footprint, x/y/rotation, side, courtyard box, pads with number, net, position, shape, size, drill); nets (netclass, pads, segments, length, vias); track, via and zone statistics. `--drc` adds unconnected items per net from kicad-cli (~15 s on a large board) |
| `lint board.kicad_pcb [--preset T\|C\|R] [--layer-plan plan.json] [--thresholds t.json] [--strict]` | Tidiness score, pass / warn / fail per metric: segments per mm and per connection, off-angle segments, turns per 10 mm, S-bend jogs, vias on power nets and per signal connection, layer main-direction conformity, tracks on GND plane layers, non-GND pours, dangling ends, silkscreen over pads (text boxes estimated), part-row alignment. Exit 1 on fail. Thresholds are in `kcp/presets/lint.json`; copy it and pass `--thresholds` to change them |
| `decisions PCB_DECISIONS.md [--checkpoint CP0\|CP1\|CP2\|CP4\|CP6]` | Blank rows per Part, in any language (rows found by ID, answers by the `Yes/No` or `Decision` column). With `--checkpoint`, exit 1 while anything that checkpoint needs is blank or unconfirmed |
| `drc board.kicad_pcb [--refill] [--parity]` | kicad-cli DRC summarised: violations by type, unconnected per net, parity. Runs on a temporary copy unless `--parity` is given, so nothing is written next to the board |
| `erc board.kicad_sch` | kicad-cli ERC summarised by type |
| `place fit-check\|move\|row\|edge board.kicad_pcb ...` | Courtyard overlaps, edge distance and keep-outs; move or rotate a footprint (pads and texts follow); line parts up; put a connector flush with an edge. Writes refuse while KiCad has the project open |
| `route path board.kicad_pcb --net N --layer L --points "REF.PAD x,y REF.PAD" [--dry-run]` | Writes a 0/45/90° path only if it keeps the netclass clearance (larger of the two nets) to other copper and the edge; otherwise exit 1 with every conflict |
| `route lane --lines JSON --entry A,B,C` / `route cleanup board.kicad_pcb` | Crossing-free order of lines in a lane, and the pairs that cross with the current order / merge collinear segments, drop zero-length ones |
| `previews board.kicad_pcb --out-dir DIR` | Routing, assembly and inner-layer PDFs (+ PNG) and the 1:1 fit-check PDF on A4/A3 |
| `tracedrop board.kicad_pcb --net N --source REF.PAD --load REF.PAD=A ...` | Voltage drop and IPC-2221 temperature rise along a net's tracks |

In a generator script, import the same modules: `kcp.wiring` (schematic from a wiring plan,
netlist read-back), `kcp.board` and `kcp.footprints` (board building), `kcp.place`, `kcp.route`
(`Router`, `bus`, `lane_order`, `cleanup`). See [references/kicad-scripting.md](references/kicad-scripting.md).
Example layer plans and a complete generated board are in the repository's `examples/`.

### `scripts/`

| Script | Purpose | Runs with |
|---|---|---|
| `export_previews.py` | Same as `kcp previews`, with the original options | Any Python 3.9+: `export_previews.py board.kicad_pcb --out previews` |
| `trace_drop.py` | Same as `kcp tracedrop`, with the original options and text output | Any Python 3.9+: `trace_drop.py board.kicad_pcb --net +5V --source J1.1 --load U3.8=0.15 ...` |
| `gerber_readback.py` | Layer functions and copper order from X2 attributes, outline size, PTH/NPTH counts; compares against expected values | Any Python 3.8+: `gerber_readback.py fab.zip --expect-size 100x80 --expect-copper 4` |
| `compare_gerbers.py` | Geometry diff of two Gerber/drill bundles (lines, arcs, flashes, regions, holes, slots) | Any Python 3.8+: `compare_gerbers.py old.zip new.zip` |

`kicad-cli` is found from `$KICAD_CLI`, `PATH`, or the usual install folder
(Windows: `C:/Program Files/KiCad/<version>/bin/kicad-cli.exe`). Only Windows has been tested.

## Version notes

- **Tested with KiCad 10.0.x.** `kicad-cli` options and Gerber file naming change between
  versions. Check `kicad-cli <command> --help` before relying on a flag. Identify Gerber layers
  by their `%TF.FileFunction` attribute, not by file extension.
- **Python bindings.** Nothing bundled imports `pcbnew`: KiCad has deprecated the SWIG bindings
  and plans to remove them in KiCad 11. `kcp` reads and writes the files itself and drives
  `kicad-cli`; a live backend through KiCad's IPC API is optional (see the README).
- **Board file format.** `kcp` reads KiCad 10 boards (nets written by name) and the older format
  with numbered nets.
