# My PCB defaults: Part A

An example of saved defaults for the `kicad-clean-pcb` skill. Copy this file **outside** the
installed skill folder (updates overwrite that folder), for example to `~/pcb-defaults/`, and
change the Decision column to your own answers. Then point your agent at it from your global
notes (`~/.claude/CLAUDE.md` for Claude Code, `~/.codex/AGENTS.md` or `AGENTS.md` for Codex):

```markdown
## PCB work
For the kicad-clean-pcb skill, my default Part A is in ~/pcb-defaults/PCB_PART_A_DEFAULTS.md.
Copy it into each new PCB_DECISIONS.md and ask me once to confirm it.
```

At stage 0 the agent copies this table into the project's `PCB_DECISIONS.md` and asks you to
confirm it as a whole (CP0), instead of walking through every axis. Options are explained in the
skill's `references/preferences.md`. Check the file with:

```bash
python <skill>/kcp decisions PCB_PART_A_DEFAULTS.md
```

**Preset chosen:** T

| ID | Axis | Options | Decision |
|---|---|---|---|
| A1 | Who draws | a agent places and routes · b agent places, user routes, agent reviews · c user draws, agent plans and reviews | a |
| A2 | Placement style | a zones + aligned rows · b shortest, dense · c zones + noise separation + test access | a |
| A3 | Routing geometry | a straight + 45°, layer directions, ordered lanes · b shortest 45° · c a + return-path rules | a |
| A4 | Routing method | a structured manual/scripted · b autorouter then clean-up | a |
| A5 | Vias | a minimal (power 0, signals ≤ 1) · b as needed · c as needed + GND stitching | a |
| A6 | Layers and stackup | 2L-a · 2L-b · 4L-S1 · 4L-S2 · 4L-S3 | 4L-S1 (2L-a for simple boards) |
| A7 | Copper pours | a GND plane(s) only · b pours where useful · c GND planes + stitched outer GND | a |
| A8 | Add-on circuit policy | a minimal · b balanced · c full | a |
| A9 | Current target | a 2 × measured · b worst case | a |
| A10 | Trace temperature-rise limit | a 20 °C · b 10 °C · c other: ___ | a |
| A11 | Assembly | a hand THT + sockets · b hand SMD ≥ 0805 · c fab assembly | a |
| A12 | Silkscreen | a function names + pin 1 + power marks · b references only · c references + names + test points + polarity | a |
| A13 | Board size | a smallest that keeps routing corridors · b absolute minimum · c fixed by enclosure: ___ | a |
| A14 | Physical fit check | a 1:1 print at placement · b a + 3D/STEP check · c skip | a |
| A15 | Checkpoint cadence | a four checkpoints · b + after every routing group · c placement + final only | a |
| A16 | Fab and ordering | a local shop / reseller · b online fab · c other: ___ | b (JLCPCB) |
| A17 | Document language | | English |
