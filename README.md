# PCB Layout with an AI Agent in KiCad (`kicad-clean-pcb`)

[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
![KiCad 10](https://img.shields.io/badge/KiCad-10.0.x-314cb0)
![Agent Skill](https://img.shields.io/badge/Agent%20Skill-Claude%20Code%20%7C%20Codex-555)

[繁體中文說明](README.zh-TW.md)

An **Agent Skill for Claude Code and OpenAI Codex**. It takes a **KiCad PCB** from a working
prototype to fab-ready **Gerber and drill files**, and keeps you in the loop:

- you choose the design style up front,
- you approve every add-on circuit in a yes/no checklist,
- you confirm the placement on a **1:1 printout before a single track is routed**.

It is **not an autorouter**. It is the workflow, layout rules and checks that make an AI agent
behave like a careful PCB designer, for hand-soldered control boards, motor-driver boards and
module carrier boards.

## Why this exists

It came out of turning a perfboard prototype into a 4-layer carrier board. The prototype had an
MCU dev board, stepper-driver modules, encoder receivers and current-sense modules.

The agent's first attempt used automatic placement and grid routing. It passed DRC, but it had:

- about 10,000 zigzag track segments,
- four copper pours,
- a layout nobody could follow.

The restructured board had about 600 segments and 30 vias, one GND plane, and a third less
board area.

The 1:1 paper check came too late, after routing. It found a USB port blocked by a header row,
a fuse holder whose pitch didn't match the real part, and a terminal block that duplicated one
already on a module. All three meant rerouting.

This skill captures what fixed those problems, so the next board doesn't repeat them:

- **Decide in writing, early.** Preferences and add-on circuits are settled before the
  schematic, in a file both sides can read (`PCB_DECISIONS.md`).
- **Place, print, confirm, then route.** Mechanical mistakes surface on paper, not after
  routing.
- **Route by function group, one group at a time.** Straight lines and 45° corners, a main
  direction per layer, few vias. Run DRC after each group.
- **Nothing unrequested.** No protection, buffers or test points the user didn't approve. And
  no silently skipped protection either.

## What's inside

- **A 7-stage workflow with 4 checkpoints:** requirements and wiring → parts and decisions →
  schematic → placement (1:1 check) → routing → verification and fab files → close-out.
- **Three design presets, plus 17 adjustable axes:** Tidy & readable, Compact / shortest,
  Robust / max electrical. The axes cover stackup, vias, pours, protection policy, current
  target, temperature-rise limit, assembly method, silkscreen, checkpoint cadence and more.
- **`PCB_DECISIONS.md`, a yes/no handshake template.** It has:
  - a scope check (mains, >60 V, Li-ion, high-speed, safety-critical),
  - your preferences,
  - one row per optional protection or add-on circuit,
  - one row per optional technical check,
  - checkpoint sign-offs and a change log.

  A blank row means "not approved".
- **Reference guides:** layout rules per style; circuit policy (add-on classes A–D, current
  ratings, reverse-polarity options, regenerated motor energy); a routing playbook with
  stackup options; verification and order-spec templates; KiCad 10 scripting notes.
- **Four scripts**, listed under [Scripts](#scripts).

## Is it for you?

**Good fit**

- You have a working prototype (perfboard, breadboard, jumper wires, dev boards and modules) and
  want a real PCB.
- Low and medium-speed boards: microcontroller I/O, motor drivers, sensors, encoders,
  RS-422/RS-485, I²C/SPI/UART.
- You use Claude Code, Codex or another agent that supports Agent Skills, and you want to
  approve the important decisions yourself.

**Not a fit**

- RF, DDR, USB high-speed or other controlled-impedance designs; mains-powered or isolated
  supplies; battery charging; anything above 60 V DC; safety-critical or medical devices. The
  skill's scope check stops and says so.
- "Generate my whole board without asking me anything." This skill asks, on purpose, at four
  checkpoints.

## Requirements and version notes

| | Tested | Notes |
|---|---|---|
| KiCad | **10.0.x** | `kicad-cli` options and Gerber file naming change between versions. The skill checks `--help` and reads Gerber layers from X2 attributes instead of file extensions |
| OS | Windows 10 | macOS and Linux should work, but the paths in the docs are Windows-first and untested elsewhere |
| Python for board scripts | KiCad's bundled Python | `export_previews.py` and `trace_drop.py` use the legacy SWIG `pcbnew` bindings. KiCad has deprecated them in favour of the IPC API and plans to remove them in a future major release; these two scripts will need porting then |
| Python for Gerber tools | 3.8+ (stdlib only) | `gerber_readback.py` and `compare_gerbers.py` need no KiCad |
| Agents | Claude Code, Codex | Any agent that reads `SKILL.md` folders (the Agent Skills format) should work |

## Install

### Claude Code: plugin marketplace (recommended)

In a Claude Code session:

```text
/plugin marketplace add haohao-0725/PCB_Layout_with_AGENT_in_KiCAD
/plugin install kicad-clean-pcb@pcb-layout-with-agent
```

### Claude Code: copy the skill folder

```bash
git clone https://github.com/haohao-0725/PCB_Layout_with_AGENT_in_KiCAD.git
cp -r PCB_Layout_with_AGENT_in_KiCAD/skills/kicad-clean-pcb ~/.claude/skills/
```

For a single project, use `<project>/.claude/skills/` instead.

### Codex

```bash
cp -r PCB_Layout_with_AGENT_in_KiCAD/skills/kicad-clean-pcb ~/.agents/skills/
```

For a single repository, use `<repo>/.agents/skills/`. Older Codex releases read
`~/.codex/skills/`. Restart Codex after installing.

### Windows (PowerShell)

```powershell
Copy-Item -Recurse PCB_Layout_with_AGENT_in_KiCAD\skills\kicad-clean-pcb $HOME\.claude\skills\
```

## Quick start

Just describe the board. For example:

- "Turn my perfboard stepper controller into a PCB. Here are the pin map, BOM and photos."
- "Here's my KiCad schematic. Help me place it and route it so it's readable."
- "Check these Gerbers before I order them."

The agent starts with the scope check and asks you to pick a preset. Then it creates
`PCB_DECISIONS.md` in your project. From there, every checkpoint is a single message listing
everything that needs your answer.

## Design presets

| | T · Tidy & readable | C · Compact / shortest | R · Robust / max electrical |
|---|---|---|---|
| Goal | Read the layout at a glance; easy to hand-solder and modify | Smallest board, shortest connections, lowest cost | Best signal integrity, thermal margin and fault tolerance |
| Routing | Straight + 45°, one direction per layer, ordered lanes | Shortest 45° paths | As T, plus return-path rules |
| 4-layer stackup | Sig / GND / GND / Sig | Sig / GND / Power / Sig | Sig / GND / GND / Sig |
| Add-on circuits | Minimal (prototype is the baseline) | Minimal | Full protection at external interfaces |
| Current target / ΔT limit | 2 × measured / 20 °C | 2 × measured / 20 °C | Worst case / 10 °C |

You can mix and match, e.g. a tidy layout with full protection. All presets keep the 1:1 fit
check, measured footprints, native checks at zero, and a Gerber readback with a layer-order
table.

## The workflow

| Stage | Output | You confirm |
|---|---|---|
| 0. Scope, profile, preferences | `PCB_DECISIONS.md` Part A | ✔ |
| 1. Hardware list, requirements, wiring plan | Project brief | ✔ |
| 2. Parts gaps, add-on decisions | BOM, measured dimensions, yes/no rows answered | ✔ |
| 3. Schematic | ERC clean, netlist checked against the wiring plan | if needed |
| 4. Placement | Previews and a **1:1 fit-check PDF** | ✔ **no routing before this** |
| 5. Routing | Grouped routing, DRC after each group | at the end |
| 6. Verification and fab files | DRC/parity zero, Gerbers + drill + readback, order spec | ✔ |
| 7. Close-out | One rebuild entry point, archived old files, handoff notes | — |

## Scripts

| Script | What it does | Run with |
|---|---|---|
| `export_previews.py` | Routing, assembly and inner-plane previews (PDF + PNG) and a 1:1 fit-check PDF on A4/A3 | KiCad's Python |
| `trace_drop.py` | Voltage drop and IPC-2221 temperature rise along a net's tracks, to each load | KiCad's Python |
| `gerber_readback.py` | Layer functions and copper order from X2 attributes, board outline size, PTH/NPTH hole and slot counts, with optional expected values | Python 3.8+ |
| `compare_gerbers.py` | Geometry diff of two Gerber/drill bundles: lines, arcs, flashes, regions, holes and slots | Python 3.8+ |

```bash
# Windows example; on Windows set PYTHONUTF8=1
"C:/Program Files/KiCad/10.0/bin/python.exe" skills/kicad-clean-pcb/scripts/trace_drop.py board.kicad_pcb --net +5V --source J1.1 --load U3.8=0.15 --load J5.1=0.2
python skills/kicad-clean-pcb/scripts/gerber_readback.py fab.zip --expect-size 100x80 --expect-copper 4 --markdown
python skills/kicad-clean-pcb/scripts/compare_gerbers.py old.zip new.zip
```

Run the unit tests (no KiCad needed):

```bash
python -m unittest discover -s tests -v
```

## Repository layout

```text
.claude-plugin/          plugin.json + marketplace.json (Claude Code plugin marketplace)
skills/kicad-clean-pcb/
  SKILL.md               workflow, checkpoints, principles
  references/            preferences, layout rules, circuit policy, routing, checks, KiCad scripting, regional ordering
  assets/                PCB_DECISIONS and PROJECT_BRIEF templates
  scripts/               preview, trace, readback and compare tools
  agents/openai.yaml     Codex UI metadata
tests/                   unit tests for the scripts
```

## Limitations and disclaimer

- **Rules of thumb, not a standard.** The rules come from hand-built, low-to-medium-speed boards.
  Verify critical numbers (current, temperature, clearance) against datasheets, IPC standards
  and your fab's capabilities.
- **CAD-clean is not hardware-verified.** Passing DRC says nothing about waveforms, temperature
  or real-world plugging. Test the real board.
- **Estimates only.** `trace_drop.py` uses the IPC-2221 formula and ignores pours, pads and
  connectors.
- **What the Gerber tools skip.** They don't evaluate aperture-macro bodies or step-and-repeat
  blocks.
- **The agent never orders or pays.** It prepares files and specs; you place the order.
- **No warranty.** Provided as is under the MIT license. You are responsible for the boards you
  build.

## Contributing

Issues and pull requests are welcome. These help most:

- reports from other KiCad versions and operating systems,
- layout rules for board types not covered here,
- regional ordering notes,
- a port of the board scripts to KiCad's IPC API.

Please keep proposed rules generic. No project-specific numbers.

## License

[MIT](LICENSE)
