# Project brief: <board name>

The working record for one board. Copy it into the project (e.g. next to the `.kicad_pro`) and
write it in the user's language.

- Fill in what existing material already answers. Ask only for what is missing and affects the
  circuit, footprints or fabrication.
- Give each row a source and a date. Write "TBD" for unknowns.
- Decisions (profile, add-on circuits, checks, sign-offs) live in `PCB_DECISIONS.md`, not here.

## 1. Goal and boundaries

- What the board does, and which prototype it replaces (photos, wiring notes):
- Circuit baseline (prototype wiring, firmware pin configuration, existing BOM):
- Changes requested for this board:
- Board limits (maximum size, layers, mounting holes, enclosure):
- CAD source of truth (KiCad by hand / generator scripts), and which files a rebuild overwrites:

## 2. Hardware list

| Module / IC / connector | Part number / revision | Qty | Pins and interfaces used | Supply | Mounting (socket / soldered) | Dimension source and status |
|---|---|---|---|---|---|---|

## 3. Supplies and currents

| Rail | Voltage | Measured current (conditions, date) | Target (per Part A) | Source and protection | Loads |
|---|---|---|---|---|---|

Power tree: entry → fuse → reverse protection → trunk → branches, with the current in each
segment. Grounding: single GND net unless decided otherwise.

## 4. Wiring plan

| Function | MCU pin | Board connector.pin | Module.pin | Harness (who crimps, pin order, polarity) | Status |
|---|---|---|---|---|---|

| Interface operated while running (USB, debug, buttons, jumpers, terminal entry) | On which module / where | Clearance needed in front | Checked on 1:1 print |
|---|---|---|---|

## 5. Parts and measured dimensions

| Part / group | Spec (value, rating, qty) | On hand / to buy / substitute | Body and height | Pitch, lead diameter or blade width × thickness | Orientation, cable entry, mounting | Measured by, date |
|---|---|---|---|---|---|---|

- Distinguish hole-centre distance, hole-edge distance and body edge. Write down how each value
  was measured, e.g. "outer edge to outer edge 23.7 mm, lead thickness 0.45 mm → centre
  distance 23.25 mm".
- Photo pixels are not hole positions. Use measurements or the official drawing.

| Function / net | Symbol pin | Footprint pad | Physical position (top view) | Polarity / pin 1 | Status |
|---|---|---|---|---|---|

## 6. Placement and routing worksheet

| Function group | Position and row order | Connector, tool and plug clearance | Reserved corridor / fan-out | Confirmed |
|---|---|---|---|---|

| Layer / net group | Use and main direction | Width / clearance and basis | Layer changes and reason |
|---|---|---|---|

After each routing group, record only: new DRC issues, remaining nets, layer-change exceptions.

## 7. Delivery summary

- Final board file and fab zip location; size, layers, copper weights, layer-order table.
- ERC / DRC / unconnected / parity results; via count and exceptions; purpose of each pour.
- Physical details: confirmed and still open.
- Operating rules before power-up; what to verify on the real board.
- Order spec location; whether it was uploaded or ordered (by the user).
