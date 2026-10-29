"""Entry point for `python -m kcp` and for `python <skill>/kcp` (running the folder directly)."""
import os
import sys

if not __package__:
    # Run as `python path/to/kcp`: Python put the kcp folder itself on sys.path. Replace it with the
    # parent folder so `import kcp` works and kcp's module names cannot shadow the standard library.
    here = os.path.dirname(os.path.abspath(__file__))
    sys.path[:] = [p for p in sys.path if os.path.abspath(p or ".") != here]
    sys.path.insert(0, os.path.dirname(here))

from kcp.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
