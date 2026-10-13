# Changelog

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
