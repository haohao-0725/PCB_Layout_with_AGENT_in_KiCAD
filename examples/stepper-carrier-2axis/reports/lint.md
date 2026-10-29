# Tidiness lint: PASS (preset T: Tidy & readable)

Board: `stepper_carrier.kicad_pcb`

| Metric | Value | Target | Status |
|---|---:|---|---|
| Track segments (incl. arcs) | 78 |  | info |
| Total track length | 752.8 mm |  | info |
| Segments per mm of track | 0.1036 1/mm | ≤ 0.15 (warn ≤ 0.3) | pass |
| Worst net: segments per pad-to-pad connection | 3 | ≤ 10 (warn ≤ 20) | pass |
| Segments not at 0/45/90° | 0 | ≤ 0 (warn ≤ 3) | pass |
| Arc tracks | 0 |  | info |
| Turns per 10 mm of track (zigzag) | 0.412 1/10mm | ≤ 1 (warn ≤ 2) | pass |
| Short S-bend jogs (< 2 × width) | 4 | ≤ 5 (warn ≤ 25) | pass |
| Collinear joints (segments that could be merged) | 0 |  | info |
| Vias | 0 |  | info |
| Vias on power / high-current nets | 0 | ≤ 0 (warn ≤ 2) | pass |
| Vias on GND nets | 0 |  | info |
| Signal nets above the via limit (per connection) | 0 | ≤ 0 (warn ≤ 3) | pass |
| Lowest layer main-direction conformity | 78.7 % | ≥ 75 (warn ≥ 60) | pass |
| Tracks on GND plane layers | 0 | ≤ 0 (warn ≤ 0) | pass |
| Copper zones | 2 |  | info |
| Zones on nets other than GND | 0 | ≤ 0 (warn ≤ 0) | pass |
| Dangling track ends | 0 | ≤ 0 (warn ≤ 0) | pass |
| Silkscreen over pads (approx.) (text boxes are estimated from the font size) | 0 | ≤ 0 (warn ≤ 5) | pass |
| Worst part-row misalignment | — |  | skip |
| Misaligned part rows | 0 |  | info |

## Layers

| Layer | Role | H mm | V mm | 45° mm | Other mm | Conformity |
|---|---|---:|---:|---:|---:|---:|
| F.Cu | horizontal | 446.9 | 18.3 | 64.7 | 0 | 84.3 % |
| B.Cu | vertical | 42.9 | 175.4 | 4.6 | 0 | 78.7 % |

## Worst nets by segments per connection

| net | segments | pads | per_connection |
|---|---|---|---|
| X_1B | 3 | 2 | 3.0 |
| X_1A | 3 | 2 | 3.0 |
| X_2A | 3 | 2 | 3.0 |
| X_2B | 3 | 2 | 3.0 |
| Y_EN_N | 6 | 3 | 3.0 |
| Y_1B | 3 | 2 | 3.0 |
| Y_1A | 3 | 2 | 3.0 |
| Y_2A | 3 | 2 | 3.0 |
| Y_2B | 3 | 2 | 3.0 |
| +5V | 3 | 2 | 3.0 |

## Zigzag nets

| net | turns | length_mm | turns_per_10mm |
|---|---|---|---|
| Y_EN_N | 3 | 22.7 | 1.32 |
| X_EN_N | 2 | 23.8 | 0.84 |
| X_1A | 2 | 25.5 | 0.78 |
| X_2A | 2 | 25.5 | 0.78 |
| Y_1A | 2 | 25.5 | 0.78 |
| Y_2A | 2 | 25.5 | 0.78 |
| X_1B | 2 | 26.6 | 0.75 |
| X_2B | 2 | 26.6 | 0.75 |
| Y_1B | 2 | 26.6 | 0.75 |
| Y_2B | 2 | 26.6 | 0.75 |

## Short jogs

| net | layer | start | length_mm | width_mm |
|---|---|---|---|---|
| X_1A | F.Cu | 20, 56.05 | 1.796 | 1.0 |
| X_2A | F.Cu | 20, 58.59 | 1.796 | 1.0 |
| Y_1A | F.Cu | 20, 96.69 | 1.796 | 1.0 |
| Y_2A | F.Cu | 20, 99.23 | 1.796 | 1.0 |

## Zones

| net | layers | role | filled_area_mm2 |
|---|---|---|---|
| GND | In1.Cu | ground | 17085.6 |
| GND | In2.Cu | ground | 17085.6 |
