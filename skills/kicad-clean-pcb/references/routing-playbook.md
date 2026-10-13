# Routing playbook

Read this file before stage 5. The geometry, via and pour rules come from Part A; this file
covers how to get there.

## 1. Before routing: the layer plan

Write a table so the user and the agent both know what each layer does. Take the stackup from
Part A (options in preferences.md §3). For example, 4L-S1 on a tidy board:

| Layer | Use | Main direction | Notes |
|---|---|---|---|
| F.Cu | Local fan-out, MCU breakout, high-current outputs, power entry | Horizontal | |
| In1.Cu | Solid GND plane | — | No tracks |
| In2.Cu | Solid GND plane | — | No tracks |
| B.Cu | Power trunks, differential inputs, vertical lanes | Vertical | |

With 4L-S2, In2.Cu carries the logic-power trunks as tracks, plus the few signals that must
cross. Keep fast edges off B.Cu, because its reference is fragmented.

List the width and clearance of every net group (netclasses): signals (e.g. 0.3 mm), logic
power, high-current outputs, main supply.

**A netclass clearance applies to everything passing that net's pads.** If a power netclass has
a larger clearance, signal tracks passing a power pad must keep that distance too.

## 2. Routing order

Route one function group at a time. After each group, run DRC and look at a close-up. With git,
commit once per group.

1. Main supply: entry → fuse → protection → trunk → branches
2. High-current outputs (motor phases etc.)
3. Differential / encoder inputs and their receivers
4. Local RC, filter and decoupling connections
5. Analog signals (current-sense outputs etc.)
6. MCU control lines to drivers
7. Remaining connectors (limit switches, sensors) and MCU signals

Adjust the order to the bottleneck: route the tightest, least flexible group first.
"Unconnected" items during routing are a to-do list. Don't stop because of them, and don't call
the board finished while any remain.

## 3. Avoiding crossings

- **Solve crossings with order before vias.** Try these first; they usually beat adding a via:
  - connector pin order (ask the user),
  - resistor-row order,
  - IC orientation,
  - lane order.
- **Lane order.** Lines going down a vertical lane turn off one by one toward their targets. A
  line turning right crosses every line to its right that is still going down. So the line
  furthest right must turn off first, which means its target is the nearest. If lines go both
  up and down, look for cycles. If there is one, move some lines to another layer.
- **Change layers on THT pads.** A through-hole pad exists on every layer, so a track can change
  layer on it without a via. Power and phase tracks can often reach zero vias this way.
- **Threading between pins.**
  - Gap = pitch − pad diameter.
  - One track fits if gap ≥ track width + 2 × clearance. For example, a 2.54 mm pitch with
    Ø1.6 mm pads leaves 0.94 mm, enough for one 0.3 mm track at 0.3 mm clearance.
  - Connector pads larger than standard often block this. Shrinking them back to standard
    usually opens the gap.
- **Outer row of a double-row header.** Reach it diagonally through the gap between two
  inner-row pins.
- **Diagonals near pads.** Check the clearance as a point-to-line distance. Start the diagonal
  further from the pad, or run a short straight piece first.
- **A via blocks every layer.** Before placing one, check that no other layer needs to pass
  through that spot.

## 4. Vias and layer changes

- Follow Part A. Under the minimal policy:
  - power and phase tracks: zero vias,
  - signals: at most one via,
  - unavoidable crossings: grouped at planned spots, never hopping up and down.
- **Low via count doesn't mean few layer changes.** THT pads change layers too. At review,
  trace a few representative signals through their actual layer sequence.
- **Return paths.** When a signal via changes reference plane (e.g. from a layer referenced to
  GND to one referenced to a power plane), place a GND (or decoupling) via close to it. This is
  required under the robust profile and good practice otherwise.
- **Exceptions.** A justified exception (e.g. two lines blocked by a breakout, one extra via
  each) is fine; write down why. Never make a long detour just to save a via count.

## 5. Power tracks and GND

- **Sizing.** Size by current target, copper weight, length and both checks in circuit-policy
  §3: `trace_drop.py` for drop and ΔT. Typical copper is 35 µm outer and 17.5 µm inner; use
  the fab's actual values.
- **GND connection to pads.**
  - Connect pads to GND planes with thermal reliefs for hand soldering.
  - Widen the spokes on high-current GND pads.
  - After filling, check for starved thermals and islands.
- **No power pours under the minimal-copper preference.** Distribute high current with wide
  trunks and short branches.

## 6. Appearance

- **Clean up the geometry.** Merge collinear segments, delete zero-length ones, and never
  squeeze through obstacles with small jogs.
- **Repeated units route identically.** Differential pairs stay paired on one layer.
- **Look before showing.** After routing, export full-board and per-layer previews
  (`scripts/export_previews.py`) plus close-ups of dense areas. Review them yourself before
  showing the user.

## 7. When stuck

If the same local problem fails three attempts, stop. Don't keep switching routers or writing
patch scripts. Report:

- the stuck nets,
- the obstacles,
- what was tried,
- the placement or pin-order decision the user needs to make.

At the end keep exactly one active board file, not a trail of candidates.

## 8. Autorouter (only if Part A allows it)

If A4 = b, run the autorouter only after placement is confirmed and the power and
high-current groups are routed by hand. Afterwards:

- delete zigzags,
- merge segments,
- remove needless vias,
- re-run DRC.

Autorouter output rarely meets the tidy style, so don't use it with A3 = a.
