# PCB decisions: <board name>

This file is the handshake record between the user and the agent. The agent creates it at
stage 0 from the skill template, keeps it in the project, and reads it at the start of every
session.

**How to answer.**

- Write `Yes` or `No` (or an option letter) in the **Decision** column.
- **A blank row means "not decided".** The agent will not build that item and will not pass the
  checkpoint that needs it.
- **Agent rec.** is the agent's recommendation; it is never the decision.
- To change an answer later, add a line to Part E instead of overwriting it silently.

| Board | Project folder | Created | Last updated |
|---|---|---|---|
| | | | |

---

## Scope check (stage 0)

If any answer is Yes, the agent must say which parts of the design this skill does not cover,
and recommend the relevant standard or a qualified reviewer.

| ID | Question | Decision (Yes/No) | Notes |
|---|---|---|---|
| S1 | Does the board connect to mains AC, directly or through an internal power supply? | | |
| S2 | Is any rail above 60 V DC? | | |
| S3 | Does it charge or carry lithium cells / packs? | | |
| S4 | Any controlled-impedance lines or signals above ~50 MHz (USB HS, Ethernet, DDR, RF)? | | |
| S5 | Is it safety-critical, medical, or meant to run unattended near people? | | |

## Part A: Profile and preferences (stage 0)

Preset (pick one): `T` Tidy & readable · `C` Compact / shortest · `R` Robust / max electrical ·
`Custom`

**Preset chosen:**

Options are explained in the skill's `references/preferences.md`. The Decision column may be
pre-filled from the chosen preset; the user confirms Part A as a whole at CP0.

| ID | Axis | Options | Decision |
|---|---|---|---|
| A1 | Who draws | a agent places and routes · b agent places, user routes, agent reviews · c user draws, agent plans and reviews | |
| A2 | Placement style | a zones + aligned rows · b shortest, dense · c zones + noise separation + test access | |
| A3 | Routing geometry | a straight + 45°, layer directions, ordered lanes · b shortest 45° · c a + return-path rules | |
| A4 | Routing method | a structured manual/scripted · b autorouter then clean-up | |
| A5 | Vias | a minimal (power 0, signals ≤ 1) · b as needed · c as needed + GND stitching | |
| A6 | Layers and stackup | 2L-a · 2L-b · 4L-S1 · 4L-S2 · 4L-S3 | |
| A7 | Copper pours | a GND plane(s) only · b pours where useful · c GND planes + stitched outer GND | |
| A8 | Add-on circuit policy | a minimal · b balanced · c full | |
| A9 | Current target | a 2 × measured · b worst case | |
| A10 | Trace temperature-rise limit | a 20 °C · b 10 °C · c other: ___ | |
| A11 | Assembly | a hand THT + sockets · b hand SMD ≥ 0805 · c fab assembly | |
| A12 | Silkscreen | a function names + pin 1 + power marks · b references only · c references + names + test points + polarity | |
| A13 | Board size | a smallest that keeps routing corridors · b absolute minimum · c fixed by enclosure: ___ | |
| A14 | Physical fit check | a 1:1 print at placement · b a + 3D/STEP check · c skip | |
| A15 | Checkpoint cadence | a four checkpoints · b + after every routing group · c placement + final only | |
| A16 | Fab and ordering | a local shop / reseller · b online fab · c other: ___ | |
| A17 | Document language | | |

## Part B: Add-on circuits and protection (stage 2)

The agent deletes rows that clearly don't apply (one-word reason in Notes) and adds
project-specific rows at the end. Classes and policy levels are explained in
`references/circuit-policy.md`. Answer every remaining row.

| ID | Item | Real problem it solves | Cost (parts / area / routing / assembly) | Class | Agent rec. | Decision (Yes/No) | Notes |
|---|---|---|---|---|---|---|---|
| B1 | Main supply fuse (rating: ___) | A short burns tracks, connectors or wiring | | A | | | |
| B2 | Reverse-polarity protection: none / series Schottky / series rectifier / P-MOSFET / ideal-diode / shunt + fuse | A swapped supply destroys every module on the rail | | A | | | |
| B3 | Bulk capacitor per driver / module (value: ___) | Supply dips and spikes from long leads and switching loads | | A | | | |
| B4 | 100 nF decoupling at every IC supply pin | Local supply noise, erratic ICs | | A | | | |
| B5 | Driver enable defaults to "off" (pull-up/down) | Motors energise while the MCU boots or resets | | A | | | |
| B6 | Regenerated-energy handling: none / more bulk / TVS clamp / brake chopper / firmware decel limit | Bus over-voltage when motors decelerate behind a blocking diode | | C | | | |
| B7 | TVS on the supply input | Surges from long supply leads, hot-plugging, inductive loads | | C | | | |
| B8 | ESD protection on connectors people plug or touch (USB, external sensors) | ESD damage to MCU pins | | C | | | |
| B9 | RC filter on long-cable digital inputs (limit switches, buttons) | Noise and bounce | | B/C | | | |
| B10 | Series resistors on MCU-facing lines | Ringing; fault current into MCU pins | | B/C | | | |
| B11 | Level shifting / buffers | Inputs that are not tolerant of the signal voltage | | A if needed, else C | | | |
| B12 | Differential termination resistors (fit / DNP) | Reflections on long differential lines | | D | | | |
| B13 | Test points on rails and key signals | Faster debugging | | C | | | |
| B14 | Per-branch fuses / polyfuses | One shorted cable takes down the whole rail | | C | | | |
| B15 | Power-good LEDs | Visual check that rails are up | | C | | | |
| B16 | Address / configuration jumpers | Flexibility without rework | | C | | | |
| B17 | Split or Kelvin grounds | Precision measurement errors | | C | | | |
| B18 | Connectors that duplicate a module's own terminals | Convenience | | C | | | |
| B19 | Mounting holes tied to GND | Shielding / chassis bonding in metal enclosures | | C | | | |
| B20 | (project-specific) | | | | | | |

## Part C: Technical checks (decided at stage 2, run at stages 4–6)

| ID | Check | Why | Effort | Agent rec. | Decision (Yes/No) | Result |
|---|---|---|---|---|---|---|
| C1 | Voltage drop on long power trunks (`trace_drop.py`) | Far loads may fall below their supply tolerance | Minutes | | | |
| C2 | Track temperature rise (`trace_drop.py`, IPC-2221; IPC-2152 calculator if close) | Thin or inner copper heats up | Minutes | | | |
| C3 | Return-path review: no signal crosses a plane gap; stitching vias at reference changes | Noise, crosstalk, EMI | Medium | | | |
| C4 | Clearance / creepage per voltage (IPC-2221 table) | Arcing or leakage above ~30 V | Minutes | | | |
| C5 | Protection-part ratings against the current target (fuse I²t and hold current, diode dissipation) | Nuisance blowing or overheating | Minutes | | | |
| C6 | Regenerated bus-voltage estimate | Over-voltage on motor deceleration | Minutes | | | |
| C7 | Hot-part dissipation and copper area | Overheating parts | Minutes | | | |
| C8 | Pin voltage tolerance and power-up order, pin by pin | Back-powering, latch-up | Medium | | | |
| C9 | 3D / STEP check of heights and mating parts | Collisions the 1:1 print can't show | Medium | | | |
| C10 | Fab capability check (min track/space/drill/annular ring) for the chosen fab | Rejected or upcharged order | Minutes | | | |
| C11 | Gerber geometry compare after any regeneration (`compare_gerbers.py`) | Unnoticed changes in delivered files | Minutes | | | |
| C12 | (project-specific) | | | | | |

**Always done, not optional:**

- the 1:1 fit check at placement (unless A14 = c),
- ERC / DRC / unconnected / schematic parity at zero,
- Gerber readback with a layer-order table,
- the agent never orders, pays or uploads on the user's behalf.

## Part D: Checkpoint sign-off

| Checkpoint | The user confirms | Date | Confirmed (Yes/No) | Notes |
|---|---|---|---|---|
| CP0 | Scope check and Part A | | | |
| CP1 | Project brief: hardware list, requirements, wiring plan, power tree | | | |
| CP2 | BOM, measured dimensions, every row of Parts B and C answered | | | |
| CP4 | Placement, including the 1:1 print check with real parts | | | |
| CP6 | Check results, fab files, layer-order table, order spec | | | |

## Part E: Change log

| Date | ID | From → To | Reason | Requested by |
|---|---|---|---|---|
| | | | | |
