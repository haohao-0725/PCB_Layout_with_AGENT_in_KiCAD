# Releasing

The maintainer publishes; agents prepare the files and never handle PyPI or GitHub credentials.

## Before a release

1. Run the tests (both Pythons if you can):

   ```bash
   python -m unittest discover -s tests -v
   ```
2. Rebuild the example and confirm every step prints `[OK]`:

   ```bash
   python examples/stepper-carrier-2axis/rebuild_stepper_carrier.py
   ```
3. Set the version in four places: `pyproject.toml` (`version`), `.claude-plugin/plugin.json`
   (`version`), `skills/kicad-clean-pcb/SKILL.md` (`metadata.version`), and `kcp/__init__.py`
   (`__version__`). Move the CHANGELOG's "Unreleased" heading to the version and date.

## PyPI (optional)

The package is `kicad-clean-pcb`; it installs the `kcp` command. The skill folder works without it.

```bash
python -m pip install build twine
python -m build
python -m twine check dist/*
python -m twine upload dist/*          # your PyPI account or an API token
```

Check first that the name `kicad-clean-pcb` is still free on PyPI (or pick another `name` in
`pyproject.toml`). Upload to TestPyPI first if you want a dry run:
`python -m twine upload --repository testpypi dist/*`.

## GitHub

- Tag the release (`git tag v0.3.0 && git push origin v0.3.0`) and create a GitHub release with
  the CHANGELOG section as notes.
- Topics: kicad, kicad-pcb, pcb-design, pcb-layout, claude-code, claude-skills, agent-skills,
  codex, gerber, hardware-design, electronics.
- Social preview: `examples/stepper-carrier-2axis/review/stepper_carrier_routing.png` works as a
  starting point (GitHub wants 1280 x 640).
