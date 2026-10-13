"""Compare the geometry of two Gerber/Excellon bundles (.zip archives or folders), ignoring
aperture numbering, drawing order, coordinate format and header dates.
Standard-library Python 3.8+ only.

    python compare_gerbers.py old.zip new.zip

Use it when fabrication files that were already reviewed or sent to a fab are regenerated
(for example after a documentation-only or BOM-value change), to confirm that copper, mask,
silkscreen, outline and drill data did not change. Prints SAME or a difference count per file
and lists a few differing items. Files are paired by name; files found on one side only are
listed. Exit code: 0 identical geometry, 1 differences, 2 usage error.

Compared: aperture definitions, polarity, draws (lines and arcs, including arc centres and
direction), flashes, regions, Excellon tool diameters, holes, G85 slots and routed slots.
Not compared: aperture-macro bodies (a macro edited without renaming it is not detected),
step-and-repeat blocks, image transforms, attributes and comments. See gerberlib.py.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gerberlib import Excellon, Gerber, kind_of, read_bundle  # noqa: E402


def geometry(text: str):
    kind = kind_of(text)
    if kind == "excellon":
        return Excellon(text).items
    if kind == "gerber":
        return Gerber(text).items
    return None


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(__doc__)
        return 2
    old, new = read_bundle(argv[1]), read_bundle(argv[2])
    differ = 0
    for name in sorted(set(old) & set(new)):
        fa, fb = geometry(old[name]), geometry(new[name])
        if fa is None or fb is None:
            continue
        extra, missing = fb - fa, fa - fb
        same = not extra and not missing
        differ += not same
        print(f"{name:44s} {sum(fa.values()):7d} -> {sum(fb.values()):7d}  "
              + ("SAME" if same else f"DIFF +{sum(extra.values())} -{sum(missing.values())}"))
        for item in list(missing)[:3]:
            print("    -", str(item)[:160])
        for item in list(extra)[:3]:
            print("    +", str(item)[:160])
    only_one = sorted(n for n in set(old) ^ set(new) if kind_of((old.get(n) or new.get(n))) != "other")
    for name in only_one:
        print(f"{name:44s} only in {'old' if name in old else 'new'} bundle")
    same = differ == 0 and not only_one
    print("Result: " + ("geometry identical" if same
                        else f"{differ} file(s) differ, {len(only_one)} file(s) present on one side only"))
    return 0 if same else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
