"""Estimate voltage drop and temperature rise along the copper tracks of one net in a KiCad board.
Runs with any Python 3.9+ (reads the .kicad_pcb file directly; no pcbnew needed).

    python trace_drop.py board.kicad_pcb --net +5V --source J1.1 \\
        --load U3.8=0.15 --load J5.1=0.125 --inner-um 17.5 --temp-c 40 --dt-limit 20

Same options and output as before; the work is done by kcp.tracedrop (also available as
`python <skill>/kcp tracedrop ...`, which prints JSON). Method and limits:

- Track graph of the net: straight and arc tracks, T-junctions, pads joining track ends that land
  inside them, parallel tracks between the same points combined as parallel resistors.
- Lowest-resistance path from the source pad to each load; loops are treated as that tree, which
  over-estimates the drop.
- Resistance rho(T) * length / (width * thickness), rho(T) = 1.724e-8 * (1 + 0.00393 (T - 20 C)).
- IPC-2221 temperature rise per segment (k = 0.048 outer, 0.024 inner); conservative. Near the
  limit, check with an IPC-2152 calculator before widening.
- Track copper only (no pours, pads, joints, connectors, return path); layer connectivity is
  inferred from coordinates, so run it on a board with no unconnected items.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from kcp.tracedrop import analyse, copper_rho, ipc2221_delta_t, parallel, to_text  # noqa: E402,F401


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("board")
    parser.add_argument("--net", required=True)
    parser.add_argument("--source", required=True, help="source pad as REF.PAD, e.g. J1.1")
    parser.add_argument("--load", action="append", default=[], help="load pad and current, REF.PAD=AMPS; repeat")
    parser.add_argument("--outer-um", type=float, default=35.0, help="outer copper thickness, default 35 (1 oz)")
    parser.add_argument("--inner-um", type=float, default=17.5, help="inner copper thickness, default 17.5 (0.5 oz)")
    parser.add_argument("--temp-c", type=float, default=40.0, help="copper temperature for resistivity, default 40")
    parser.add_argument("--rho", type=float, help="override resistivity in ohm*m")
    parser.add_argument("--dt-limit", type=float, default=20.0, help="flag segments whose rise exceeds this (C)")
    args = parser.parse_args()

    from kcp.backends.file import load_board
    loads = {}
    for item in args.load:
        name, _, amps = item.partition("=")
        loads[name] = float(amps)
    try:
        result = analyse(load_board(args.board), args.net, args.source, loads, args.outer_um, args.inner_um,
                         args.temp_c, args.rho, args.dt_limit)
    except ValueError as exc:
        raise SystemExit(str(exc))
    sys.stdout.write(to_text(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
