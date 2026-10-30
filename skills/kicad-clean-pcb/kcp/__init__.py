"""kcp: deterministic KiCad board tools for the kicad-clean-pcb skill.

The agent decides; these tools do the geometry. Core modules use only the Python standard
library (3.9+), so they run from a copied skill folder:

    python <skill>/kcp inspect board.kicad_pcb
    python -m kcp lint board.kicad_pcb --preset T        (with <skill> on PYTHONPATH)
"""
__version__ = "0.3.0"
