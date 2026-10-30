# Verification and fabrication delivery

## 1. Checklist

1. **Native checks at zero.** This covers:
   - ERC errors and warnings,
   - DRC errors and warnings with zones refilled,
   - unconnected items,
   - schematic parity.

   ```bash
   python <skill>/kcp erc board.kicad_sch
   python <skill>/kcp drc board.kicad_pcb --refill --parity
   ```

   Both summarise kicad-cli's JSON reports by type and exit 1 on any violation, unconnected item
   or parity issue. `--full` adds the whole report. The raw commands are
   `kicad-cli sch erc --format json --severity-all ...` and
   `kicad-cli pcb drc --format json --refill-zones --schematic-parity --severity-all ...`.

   Never reach zero by excluding rules, loosening widths, editing the netlist or adding
   exclusions. A warning that genuinely has a reason goes into the delivery summary.
   Options can change between KiCad versions; check `kicad-cli pcb drc --help`.
2. **Compare against the wiring plan.** Check:
   - pad nets,
   - DNP flags,
   - footprints,
   - the contracts that matter: MCU pins, addresses, current-sense direction.

   A validator script should check only rules whose failure would cause real trouble. For
   example: power and phase tracks on outer layers only, minimum widths, no vias on power, GND
   plane outline. Avoid checks tied to old coordinates; they break on every layout change.
3. **Every "Yes" in Part C is run** and its result recorded in `PCB_DECISIONS.md` (Part D notes).
4. **Visual review.** Look at the whole board and each layer, and trace a few representative
   nets per group: power, phase, differential, analog, control. Check for:
   - a clear order,
   - no zigzags or needless layer changes,
   - tidy resistor rows,
   - readable silkscreen,
   - room for tools and plugs.

   Do this even after DRC passes.
5. **Mechanical.**
   - The courtyards of the largest parts don't overlap and keep off the edge.
   - Part heights under modules fit.
   - Mounting holes have room for screw heads.
   - Without 3D models, courtyards and measured envelopes are the only mechanical check, so
     every custom footprint needs a courtyard.

## 2. 1:1 fit check

- `kcp previews` (or `scripts/export_previews.py`) writes a portrait A4 (A3 if needed) 1:1 PDF.
  It contains copper, silkscreen, fab outlines and reference layers such as module outlines.
- **Printing.** The user prints at "Actual size / 100 %" with scaling off. They measure the
  printed outline first to confirm the scale, then lay the real parts, modules and terminals on
  it. They check:
  - holes,
  - orientation,
  - space for operating interfaces,
  - cable entry,
  - part envelopes.
- **When.** Do it **at the placement checkpoint, before routing**. Do it again after any real
  change to holes, connectors or the outline. Doing it after routing means rerouting whatever
  it reveals.

## 3. Fabrication files

`kcp fab board.kicad_pcb --out-dir fab --readme spec.txt` runs every step below: Gerbers and
drill files, the zip with README.txt and SHA256SUMS.txt, and the readback against the board. The
commands show what it does and work on their own. Refill the zones first
(`kcp drc board.kicad_pcb --refill --save`, or `kcp fab --refill`), or the pours are missing.

- **Gerbers.** A 4-layer board needs 9 layers: F.Cu, In1.Cu, In2.Cu, B.Cu, F.Mask, B.Mask,
  F.SilkS, B.SilkS, Edge.Cuts. Keep X2 attributes enabled (the default), because the readback
  depends on them.
  ```bash
  kicad-cli pcb export gerbers --layers F.Cu,In1.Cu,In2.Cu,B.Cu,F.Mask,B.Mask,F.SilkS,B.SilkS,Edge.Cuts --output fab/ board.kicad_pcb
  ```
- **Drill files.** Excellon, with PTH and NPTH in separate files:
  ```bash
  kicad-cli pcb export drill --format excellon --excellon-units mm --drill-origin absolute --excellon-separate-th --output fab/ board.kicad_pcb
  ```
- **Readback.**
  ```bash
  python scripts/gerber_readback.py fab.zip --expect-size WxH --expect-copper N --expect-pth P --expect-npth Q --markdown
  ```
  Take the expected values from the native board: outline from the Edge.Cuts endpoints, and
  plated count = THT pads + vias. It prints the copper layer order from each file's
  `%TF.FileFunction` attribute. **Use that output as the layer-order table.** Inner-layer file
  extensions are not a reliable guide. KiCad 10 writes In1.Cu as `.g1`, older versions numbered
  them differently, and fabs use their own conventions. Never write the order from extensions or
  memory.
- **Fab README.** The zip contains an English `README.txt`:
  - size, layer count, thickness, copper weights,
  - **the layer-order table**,
  - minimum track, space and hole,
  - via tenting,
  - PTH/NPTH separate,
  - bare boards only.

  Add a `SHA256SUMS.txt`.
- **Regenerated files.** If fab files are regenerated after delivery, run
  `scripts/compare_gerbers.py old.zip new.zip` before saying nothing changed. Gerber headers
  contain dates, so byte-level differences are normal.

## 4. The order spec (for the user to talk to the fab)

Write an order-spec document in the project. Take every value from the real board and the
readback report, never from a previous board.

### 4.1 Spec table

| Item | Value | Notes |
|---|---|---|
| Material / layers / thickness | FR-4 / N layers / 1.6 mm | |
| Size / quantity | W × H mm, rectangular / 5 pcs | Many fabs have a minimum of 5 |
| Copper weight | Outer 1 oz, inner 0.5 oz | Heavier inner copper usually costs extra |
| Layer order | L1 … Ln mapped to file names (from readback) | **Always state it**, or inner layers can be swapped |
| Min track / space | e.g. 0.3 / 0.25 mm | |
| Vias | Drill / diameter, count; tented | No via-in-pad means no plugging needed |
| Drills | PTH count and sizes; NPTH count and sizes | From readback |
| Solder mask / silkscreen | Green / white | Cheapest and fastest |
| Surface finish | HASL with lead (easiest to hand-solder); lead-free HASL if RoHS is required | ENIG not needed for hand-soldered THT |
| Other | No panel, no impedance control, no gold fingers, no castellations, bare boards only | Adjust to the project |

### 4.2 Message template for a shop or reseller

```text
Hello, I'd like a quote for an N-layer PCB. Gerber archive attached.
- FR-4, N layers, 1.6 mm thick
- W x H mm, quantity 5, no panelisation
- Copper: outer 1 oz, inner 0.5 oz (please also quote inner 1 oz)
- Layer order: L1 = <file>, L2 = <file>, L3 = <file>, L4 = <file>
- Min track X mm, min space Y mm, min hole Z mm (vias tented)
- Green solder mask, white silkscreen, HASL (leaded or lead-free)
- No impedance control, no gold fingers, no castellated holes; bare boards only, no assembly
Could you confirm lead time, total price including shipping, invoice options,
and whether you can send engineering files for approval before production? Thank you.
```

### 4.3 Questions to ask the seller
- Can they make this layer count? Many shops do only 1–2 layers.
- Do they manufacture in-house or resell? Which factory makes it, and where does it ship from?
- Will they follow the stated layer order and inner copper weight?
- What are the lead time and shipping cost?
- Can they issue an invoice that works for reimbursement (labs and companies often need one)?
- Will they send engineering confirmation files before production?
- Will they print an order number on the board?
- What is the price difference between 5 and 10 pieces?

### 4.4 Online fab order forms (e.g. JLCPCB, PCBWay)
Suggest a value for each field:

- Layers, Dimensions, Quantity, Thickness, Colour, Surface finish,
- Outer and inner copper weight,
- Via covering: tented,
- Impedance control: no,
- Confirm production file: yes for a first multilayer board,
- Mark on PCB: order-number position, or paid removal.

After upload, the user checks layers, outline, silkscreen and drills in the fab's online Gerber
viewer.

For local or regional specifics (marketplaces, invoices, import customs), see the regional
notes, e.g. [ordering-taiwan.md](ordering-taiwan.md).

## 5. Delivery summary (last message to the user)

- **Board and fab files:** which board file is the result, where the fab zip is, size and
  layer count.
- **Checks:** native check results, via count and layer-change exceptions, and the purpose of
  every pour.
- **Part C:** the result of each "Yes" item.
- **Physical details:** parts, holes and heights that are confirmed, and those still open.
- **Before power-up:** operating rules (e.g. which supplies must come up together), and what
  must be verified on the real board.
- **Ordering:** where the order spec is. Ordering and payment are the user's to do.
