# Design profiles and preferences

Read this file at stage 0. People want different things from a board. One person wants a
layout they can read and hand-solder. Another wants the smallest, cheapest board. A third
wants every protection and the best signal integrity. None of these is wrong. Problems start
only when the agent guesses. So the user picks a preset, adjusts individual axes, and the
result goes into Part A of `PCB_DECISIONS.md`.

How to run it:

1. Show the preset table (§1). Recommend one with a single-sentence reason based on what you
   know about the project.
2. After the user picks, show the axis table (§2) with that preset's values and ask once:
   "Change anything?"
3. Write the result into Part A. Apply it without asking again. If the project makes an axis
   impossible, explain why and log the change in Part E.

## 1. Presets

| | **T · Tidy & readable** | **C · Compact / shortest** | **R · Robust / max electrical** |
|---|---|---|---|
| In one line | A layout you can read at a glance; easy to hand-solder, probe and modify | Smallest board and shortest connections; lowest fab cost | As much signal integrity, thermal margin and fault tolerance as the board can reasonably get |
| Typical use | Hand-built carrier boards, research prototypes, boards that others will maintain | Space-limited devices, small sensor boards, cost-sensitive batches | Long cables, motors and inductive loads, noisy environments, unattended or field use |
| Placement | Functional zones beside their connectors; identical repeated units; resistors in aligned rows | Parts clustered to shorten connections; dense packing | Zones as in T, with noisy and quiet areas separated; room for protection parts and test access |
| Routing | Straight + 45°, one main direction per layer, ordered lanes | Shortest 45° paths in any direction | As T, plus return-path rules: no signal crosses a plane gap |
| Vias | Minimal: power 0, signals ≤ 1 | As needed | As needed, with a GND stitching via beside each signal via that changes reference plane |
| 4-layer stackup | S1 (two GND planes) | S3 (GND + power plane) | S1 |
| Copper pours | GND planes only | Pours wherever they help | GND planes plus stitched outer-layer GND |
| Add-on circuits | Minimal: the working prototype is the baseline | Minimal | Full: protection at every external interface, test points |
| Current ratings | 2 × measured | 2 × measured | Worst case (stall, fuse rating, supply limit) |
| Trace ΔT limit | 20 °C | 20 °C | 10 °C |
| Silkscreen | Function names, pin 1, power marks; values in documents | Reference designators only | References, function names, test-point names, polarity |
| Checkpoints | Four (CP0/1–2/4/6) | Placement and final only | Four, plus review after every routing group |

All three presets keep these, because they cost little and save a lot:

- the 1:1 fit check before routing,
- measured footprints,
- operating-access clearance,
- native checks at zero,
- Gerber readback with a layer-order table.

## 2. Axes

An answer is an option letter. "Ask" means no preset decides it; always ask the user.

| ID | Axis | Options | T | C | R |
|---|---|---|---|---|---|
| A1 | Who draws | a agent places and routes (scripts or edits) · b agent places, user routes in KiCad, agent reviews · c user draws everything, agent plans and reviews | ask | ask | ask |
| A2 | Placement style | a zones + aligned rows · b shortest connections, dense · c zones + noise separation + test access | a | b | c |
| A3 | Routing geometry | a straight + 45°, layer directions, ordered lanes · b shortest 45° · c a + return-path rules | a | b | c |
| A4 | Routing method | a structured manual/scripted · b autorouter (e.g. Freerouting) then clean-up | a | a or b | a |
| A5 | Vias | a minimal (power 0, signals ≤ 1) · b as needed · c as needed + GND stitching | a | b | c |
| A6 | Layers and stackup | 2L-a · 2L-b · 4L-S1 · 4L-S2 · 4L-S3 (see §3) | 4L-S1 or 2L-a | 4L-S3 or 2L-b | 4L-S1 |
| A7 | Copper pours | a GND plane(s) only, power as wide tracks · b pours where useful · c GND planes + stitched outer GND pour | a | b | c |
| A8 | Add-on circuit policy | a minimal · b balanced · c full (see circuit-policy.md) | a | a | c |
| A9 | Current target | a 2 × measured · b worst case | a | a | b |
| A10 | Trace temperature-rise limit | a 20 °C · b 10 °C · c other | a | a | b |
| A11 | Assembly | a hand-soldered THT + sockets · b hand-soldered SMD (≥ 0805, ≥ 0.65 mm pitch) · c fab assembly (PCBA) | ask | ask | ask |
| A12 | Silkscreen | a function names + pin 1 + power marks · b references only · c references + names + test points + polarity | a | b | c |
| A13 | Board size | a smallest that keeps routing corridors · b absolute minimum · c fixed by enclosure | a | b | a |
| A14 | Physical fit check | a 1:1 print at placement · b a + 3D/STEP check of heights and mating · c skip (not recommended) | a | a | b |
| A15 | Checkpoint cadence | a four checkpoints · b + review after each routing group · c placement + final only | a | c | b |
| A16 | Fab and ordering | a local shop / reseller · b online fab (e.g. JLCPCB, PCBWay) · c other | ask | ask | ask |
| A17 | Document language | (the user's language) | ask | ask | ask |

Combinations are allowed, e.g. a tidy layout (T) with full protection (A8 c).

## 3. Stackup options

| Option | Layers (top → bottom) | Use when | Trade-off |
|---|---|---|---|
| **4L-S1** | Signals + power tracks / **GND** / **GND** / signals + power tracks | Default for T and R | Every routing layer sits on a solid reference. Power runs as wide outer-layer tracks, which costs outer-layer space |
| **4L-S2** | Signals / **GND** / power trunks + a few signals / signals | Low-speed boards with long logic-power trunks | Frees outer layers. The bottom layer references a fragmented layer, so keep fast edges (clocks, step pulses, SPI) on the top layer |
| **4L-S3** | Signals / **GND** / **power plane(s)** / signals | Many loads on one or two rails; compact boards | Classic and easy power distribution. The bottom layer references the power plane, so decouple well; split power planes create return-path gaps |
| **2L-a** | Most routing on top / mostly unbroken **GND** pour on bottom | Two-layer boards that want a usable reference | Bottom-layer crossings must be short and must not cut the GND pour into islands |
| **2L-b** | Routing on both layers / GND pour on both, stitched | Dense two-layer boards | Pours fragment easily. Check for unconnected or antenna-like slivers |

Notes:

- "Only pour GND" (A7 a) is compatible with S1: both inner planes are GND.
- Copper weight is a cost decision. Many fabs default to 1 oz outer / 0.5 oz inner. Size tracks
  for what you will order; don't ask for heavier copper to rescue a narrow track.

## 4. Saving defaults across projects

Users who always start the same way can keep a filled Part A in a file of their own and
mention it in their global agent notes (CLAUDE.md, AGENTS.md or similar). At stage 0, copy it
into the new project's `PCB_DECISIONS.md` and ask for a single confirmation. Don't write user
defaults into the installed skill folder; updates overwrite it.
