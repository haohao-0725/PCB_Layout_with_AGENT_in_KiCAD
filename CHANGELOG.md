# Changelog

## Unreleased (0.2.0 in progress)

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
- Tests: s-expression round trip, geometry, board model, all tools, and a hand-written 4-layer
  test board that KiCad's own DRC confirms.

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
