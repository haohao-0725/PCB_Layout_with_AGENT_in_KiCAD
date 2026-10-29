# Circuit policy: add-on circuits, protection and ratings

Read this file before stage 2.

## 1. The baseline is the working prototype

Users of this skill usually have a prototype that works: perfboard, jumper wires or off-the-shelf
modules, with firmware that runs on it. Its wiring, part values and firmware pins are the
circuit baseline. Change only what the user explicitly asks to change.

Agents tend to fail in two directions:

- **Adding things nobody asked for.** Buffers, test points, TVS diodes, brake circuits, split
  grounds, address jumpers and duplicate terminals. The board grows and gets messier, and the
  user has to remove the extras one at a time.
- **Silently leaving out something the user would have wanted.**

So every item outside the baseline becomes a row in Part B of `PCB_DECISIONS.md`. Each row
gives:

- the real problem the item solves,
- its cost: parts, area, routing, assembly,
- a recommendation.

The user answers each row once, before the schematic. Nothing is added or removed outside the
table. If the user has removed an item, later stages must not bring it back as a "suggestion";
reopening a decision goes through the change log.

## 2. Classes and policy levels

| Class | What it is | Typical examples |
|---|---|---|
| **A** | Cheap; prevents one fault from destroying several expensive parts | Main fuse, reverse-polarity protection on the main supply, bulk and decoupling capacitors per driver/IC, driver enable defaulting to "off" |
| **B** | Already in the prototype and shown to be useful | RC filters on long-cable inputs, series resistors on fault/diagnostic pins, series resistors between receivers and the MCU |
| **C** | Helps only for specific faults or for measurement | Level shifters where MCU pins are already tolerant, test points, TVS/ESD arrays, regenerative-energy clamps or brake choppers, split or Kelvin grounds, address straps, terminals duplicating a module's own |
| **D** | Unsure, but impossible to add later | Footprint without part (DNP): differential termination, optional pull-ups |

What the agent recommends for each class depends on the add-on policy (Part A, axis A8):

| Class | a · Minimal | b · Balanced | c · Full |
|---|---|---|---|
| A | Recommend **Yes**. If the user wants it out, state the consequence in numbers (e.g. "a reversed supply destroys N drivers and the electrolytics") and let the user decide | Yes | Yes |
| B | Keep as in the prototype; don't strengthen | Keep | Keep; strengthen only where analysis shows a need |
| C | Recommend **No** unless the problem has actually happened on the prototype | Yes for interfaces people plug or touch (USB, external sensor connectors, the supply input); No otherwise | Yes, unless the user declines |
| D | DNP pads | DNP pads | Populate where analysis shows a need, else DNP |

To judge a class C item, ask: "Has this happened on the prototype? How likely is it, and what
does it cost when it does?" If the agent can't name a concrete scenario, the recommendation is
No under the minimal policy.

## 3. Ratings and track sizing

### Current target
- **a · 2 × measured** (default). Twice the average current the user measured on a bench supply
  under real operation, with all axes running.
- **b · Worst case.** The larger of 2 × measured and the worst-case current: stall, fuse rating
  or supply limit.

Don't inflate ratings from a supply's maximum unless policy b says so.

Size motor-phase tracks for the phase current set on the driver, not for the supply's average
current. Use the supply's average current to estimate the heat and drop in protection parts.

Write every estimate down with its assumptions, so the user can judge it. For example: "series
rectifier at 0.6 A: about 0.85 V and 0.5 W; fine for continuous use".

### Track sizing: check voltage drop *and* temperature rise
1. **Voltage drop.** Run `scripts/trace_drop.py` at the expected copper temperature. Check the
   voltage at the far load against that load's tolerance (e.g. 5 V logic is often specified as
   4.75–5.25 V).
2. **Temperature rise.** `trace_drop.py` also reports the IPC-2221 rise per segment. Compare it
   with the ΔT limit in Part A.
   - IPC-2221 is conservative, especially for inner layers. When a result is near the limit,
     check it with an IPC-2152 calculator. KiCad's own PCB Calculator → Track Width uses
     IPC-2221.
   - Inner layers are often 0.5 oz (17.5 µm), so they reach a temperature limit much sooner
     than 1 oz outer layers of the same width.
3. **If either check fails,** fix it in this order:
   1. widen the track,
   2. move it to an outer layer,
   3. run it in parallel on two layers between THT pads,
   4. last, ask about heavier copper (a cost decision for the user).

## 4. Reverse-polarity protection options

| Option | Loss at current I | Blocks regenerated current? | Notes |
|---|---|---|---|
| None | 0 | — | Only if the connector is keyed and a reversal is truly impossible |
| Series Schottky (e.g. 3–5 A types) | ≈ 0.4–0.5 V × I | Yes | Simple; dissipation = Vf × I |
| Series standard rectifier (1N540x class) | ≈ 0.8–1.0 V × I | Yes | Fine at low current; check dissipation |
| P-MOSFET in the supply line (gate pulled to GND, Zener clamp when Vin > Vgs max) | I² × Rds(on) | **No.** Once on, it conducts both ways | Lowest loss; regenerated energy can flow back to the supply, if the supply can absorb it |
| Ideal-diode controller + MOSFET | I² × Rds(on) | Yes | Low loss, blocks reverse current; more parts, usually SMD |
| Shunt diode + fuse | 0 in normal use | — | A reversal blows the fuse; the fuse must clear before the diode fails |

### Regenerated energy (motor boards)
A decelerating motor acts as a generator. Behind a blocking element (series diode, ideal
diode), that energy can only go into the bus capacitors, so the bus voltage rises.

Most bench supplies can't sink current. So even with a P-MOSFET, or with no protection at all,
the energy usually ends up in the capacitors too.

Estimate it:

- the energy available, ½ J ω², per axis that decelerates at the same time,
- against what the capacitance can take, ½ C (Vmax² − Vbus²), with Vmax the lowest absolute
  maximum on the bus (driver, capacitors).

Small steppers at moderate speed usually give a small result, but **check it against the margin,
not just the size**. Common StepStick drivers are rated about 29–30 V, so a 24 V bus has only
5–6 V of headroom: two small motors stopping together can push it close to the limit when each
driver has only the usual 100 µF. Add every axis that can decelerate at once, and include the load
inertia if you know it. If the result is not comfortably below the limit, the options are:

- more bulk capacitance,
- a TVS or Zener clamp sized for the energy,
- a brake chopper,
- gentler deceleration in firmware.

Record the decision as a Part B row.

## 5. Use the parts on hand

- **Ask what the user already has.** A part on hand that meets the rating target is used, even
  if it isn't the "best" part number. State the difference from the ideal part.
- **For parts to buy,** suggest types that are easy to get locally, plus one alternative in the
  same package.
- **Footprints come from the measured part,** not from "typical dimensions".

## 6. Small but important details

- **Tie unused IC inputs to a fixed level.** For example, on an unused differential receiver
  channel, A goes to VCC and B to GND. It is more stable than floating and costs no parts.
- **Check every input pin's voltage tolerance and the power-up order.** If removing a part (e.g.
  a buffer) brings an operating rule such as "the MCU must be powered whenever 5 V is present",
  write it into the assembly and operating notes.
- **Don't carry a decision from another project** ("we skipped protection there"). Judge each
  board by its own supplies, plugging habits and loads.
