# Layout rules

§1 applies to every profile. Then apply the section for the placement and routing style chosen
in Part A: §2 Tidy, §3 Compact, §4 Robust. Mixed choices take the matching parts of each.
"e.g." values illustrate a rule; they are not fixed numbers.

## 1. Common to every profile

### Connectors and access
- **Connectors sit on the board edge with the cable entry facing out.** Mark pin 1 on every
  connector and terminal block (filled triangle).
- **Keep operating interfaces free.** USB ports, debug headers, buttons and jumpers on plugged-in
  modules are used while the board runs. Put nothing tall in front of them, and leave room for
  the plug and its cable. List them at stage 1 and check them on the 1:1 print.
- **Don't duplicate terminals a module already has.** For example, a current-sense module with
  its own screw terminals needs no second shunt terminal on the carrier; wire it off-board.
- **Ask before changing a harness pin order.** Reordering a connector to match the board's
  signal order avoids crossings, but the user crimps the harness.

### Real parts
- **Footprints follow the user's actual parts, as measured.** This covers fuse holders, diodes,
  terminals and electrolytic capacitors. If space is short, propose another mounting (e.g. a
  standing diode) and get confirmation.
- **Space under socketed modules.** It may hold low parts only: resistors flat on the board,
  capacitors laid down or tilted ≤ 45°. Base it on measurements: module standoff height, and
  where the header tails are on the underside. Keep a measured keep-out under the header tails.
  Document the assembly order ("solder these first, check height, then plug the module").

### Passives near their pins
- **Decoupling capacitors sit at the power pins.**
- **Bulk electrolytics sit beside the module they feed.** Put the + pad toward the power pin;
  the size follows the part on hand (measure the diameter).

### Silkscreen
- **Legible.** Text height ≥ 1.0 mm and line width ≥ 0.15 mm, or the fab minimum if larger.
  Keep a consistent orientation.
- **Clear of everything.** No text on pads, no overlaps, nothing over other parts' outlines.
- **Short names.** If a name doesn't fit, shorten it rather than shrinking the font.

### Board edge and size
- **Mounting holes.** Put them in the corners.
- **Copper keeps off the edge.** Keep ≥ 0.5 mm, or the fab rule if larger.
- **Check the biggest parts when shrinking.** Electrolytics, fuse holders and terminals must not
  have courtyards that overlap each other or crowd the edge.

## 2. Tidy & readable (T)

### Zones and flow
- **Functional zones, each next to its own connector.** For example:
  - power entry along one edge,
  - drivers in a row with their output terminals on the same edge,
  - encoders, sensors and limit switches each in their own area near their connectors.

  Looking at the board should tell you what each area does.
- **Place parts along the real signal flow:** connector → termination / filter → receiver IC →
  series resistor → MCU. Never pull a part away from its circuit just to group equal values.
- **Repeated units are identical.** Multi-axis or multi-channel blocks share one template:
  orientation, relative position, spacing and fan-out. For example, each driver's pull-ups,
  decoupling, bulk capacitor and output terminal are arranged the same way.
- **Follow the user's zone directions.** The overall direction is shown to the user with the
  first placement. If the user gives one (e.g. "motor terminals on the right, encoders bottom
  left"), follow it.

### Passives
- **Same-function resistors form one aligned row:** same orientation, same pitch, same line.
  Different functions get different rows (e.g. termination resistors in one row, series
  resistors toward the MCU in another).
- **Position follows function.**
  - Termination resistors sit at the receiver inputs.
  - Series resistors sit on the way to the MCU.
  - Pull-ups and pull-downs sit beside the part they serve (e.g. driver enable pull-up beside
    the driver, limit-switch pull-up beside its RC filter).
  - RC filters sit near the receiving pin.
- **Order inside a row matches the destination pin order,** so the tracks leaving the row don't
  cross.

### Track appearance
- **Straight lines and 45° corners only.** Prefer long straight runs. No zigzags and no small
  dodging jogs around obstacles.
- **Each layer has a main direction** (e.g. top horizontal, bottom vertical). Order the vertical
  lines in a lane by destination, so a line turning off doesn't cut across its neighbours.
- **Repeated units use the same fan-out and the same route.** Differential pairs run together,
  on one layer, at constant spacing.

### Vias
- **Power, high-current and motor-phase tracks: zero vias.** Change layers on THT pads.
- **Signals: at most one via.** Where crossings are unavoidable, put them at planned places
  (e.g. a lane entrance). Justified exceptions are fine; record them.

### Copper
- **Only GND is poured,** as plane(s) per the stackup, on a single GND net.
- **Power uses planned wide trunks.** No power pours, no islands, no thin copper tongues. Every
  piece of copper must have a stated purpose.
- **Widen the thermal spokes on high-current GND pads:** power entry, driver power ground, bulk
  capacitor negative.

### Power entry
- **In a row:** terminal → fuse → reverse-polarity protection → trunk, short and straight.
- **Long logic-power trunks** may run on an inner layer and branch to the loads (stackup S2), or
  as wide outer-layer tracks (S1).

### Silkscreen
- **Label modules and connectors by function:** axis, purpose, direction.
- **Mark the supply pin or + on harness connectors** (e.g. "5V" beside an encoder connector's
  supply pin).
- **No repeated explanations.** Values and full pin tables go in the assembly drawing or
  documents.

### Size
- Reserve corridors and fan-out space first, then shrink the board to a sensible minimum. Don't
  cram the board to hit an area number.

## 3. Compact / shortest (C)

- **Placement by connectivity.**
  - Place to minimise total ratsnest length, and rotate parts to untangle it.
  - Use smaller packages if the assembly method allows (0603/0805 instead of THT).
- **Routing.**
  - Shortest 45° paths in any direction; vias as needed, but at or above the fab minimum.
  - Fast or high-current signals still need a nearby return path. Place a GND via near any
    signal via that changes reference plane.
- **Pours.** Allowed where they shorten connections or replace long power tracks. Stitch outer
  GND pours to the plane, and remove isolated or unconnected pieces.
- **Watch for:**
  - heat from packed power parts,
  - room for a soldering iron and for rework,
  - test access for at least each supply rail.
- **Size.** The absolute minimum within fab rules; consider panelisation for batches.

## 4. Robust / max electrical (R)

- **Separate by noise class.**
  - Put power and motor circuits in one area, analog and sensitive circuits in another,
    digital in between.
  - Noisy cables enter on one side, away from sensitive inputs.
- **Reference planes.**
  - Every signal layer sits next to a solid plane (stackup S1).
  - No signal crosses a plane split or gap.
  - Put a GND stitching via within about 1–2 mm of every signal via that changes reference
    plane.
  - If outer-layer GND pours are used, stitch them densely, with a via fence along the board
    edge.
- **Small high di/dt loops.**
  - Driver input capacitors sit right at the supply pins: bulk plus ceramic at every driver.
  - Keep switching loops tight, with no long thin supply tracks to switching stages.
- **Protection at each external interface,** per Part B: TVS or ESD parts at the connector,
  before anything else, with a short direct path to GND. Add per-branch fuses where a cable
  fault can occur.
- **Test access.**
  - A labelled test point or pad on each rail and on key signals.
  - A GND test point near each group.
- **Ratings.**
  - Size tracks for the worst-case current, with ΔT ≤ 10 °C.
  - Derate protection parts.
  - Set clearances for the highest voltage on the board (IPC-2221 table for anything above
    about 30 V).
- **Thermal.**
  - Estimate dissipation for hot parts (I × Vf, I² × R).
  - Give them copper area.
  - Add thermal vias under SMD power pads.
- **Silkscreen.** References, function names, test-point names, polarity and supply marks.
