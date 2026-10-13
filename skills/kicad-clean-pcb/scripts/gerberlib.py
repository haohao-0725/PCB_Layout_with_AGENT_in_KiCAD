"""Small Gerber (RS-274X / X2) and Excellon parser shared by compare_gerbers.py and
gerber_readback.py. Standard-library Python 3.8+ only; it reads geometry, it does not render.

Coordinates are converted to integer nanometres so files written with different coordinate
formats or units still compare equal.

Gerber: apertures (by definition text), polarity, interpolation mode (linear, CW, CCW arc),
quadrant mode, arc centres, draws, flashes and regions.
Excellon: tools, plating (file-level and per-tool attributes), round holes, G85 slots and
routed (M15/M16) slots.
Not handled: aperture-macro bodies, step-and-repeat (SR), image transforms (LM/LR/LS),
Excellon repeat codes and arcs in route mode (kept as raw text).
"""
from __future__ import annotations

import collections
import math
import re
import zipfile
from pathlib import Path

NM_PER_MM = 1_000_000
NM_PER_INCH = 25_400_000
SKIP_SUFFIXES = (".txt", ".md", ".json", ".csv", ".pdf", ".png", ".jpg", ".html", ".rpt", ".pos")


# ---------------------------------------------------------------- archive helpers

def read_bundle(path: str | Path) -> dict[str, str]:
    """Return {file name: text} for a .zip archive or a folder of fab files."""
    path = Path(path)
    out: dict[str, str] = {}
    if path.is_dir():
        for item in sorted(path.iterdir()):
            if item.is_file() and not item.name.lower().endswith(SKIP_SUFFIXES):
                out[item.name] = item.read_text(encoding="utf-8", errors="replace")
        return out
    with zipfile.ZipFile(path) as archive:
        for name in archive.namelist():
            if name.endswith("/") or name.lower().endswith(SKIP_SUFFIXES):
                continue
            out[name] = archive.read(name).decode("utf-8", "replace")
    return out


def kind_of(text: str) -> str:
    """'excellon', 'gerber' or 'other', judged by content rather than file extension."""
    head = text.lstrip()[:4000]
    if head.startswith("M48") or re.search(r"^\s*M48\s*$", head, re.M):
        return "excellon"
    if "%FS" in head or "%MO" in head or "%TF." in head:
        return "gerber"
    return "other"


# ---------------------------------------------------------------- Gerber

class Gerber:
    def __init__(self, text: str):
        self.attributes: dict[str, str] = {}
        self.items: collections.Counter = collections.Counter()
        self.segments: list[tuple] = []   # ('line', p0, p1) or ('arc', p0, p1, centre, ccw)
        self._parse(text)

    @property
    def file_function(self) -> str:
        return self.attributes.get("FileFunction", "")

    def _parse(self, text: str) -> None:
        int_digits, dec_digits, scale = 4, 6, NM_PER_MM
        apertures: dict[str, str] = {}
        aperture = None
        x = y = 0
        interp, quadrant = "G01", "G75"
        polarity = "D"
        in_region, contour = False, []

        def coord(raw: str | None, previous: int) -> int:
            if raw is None:
                return previous
            return round(int(raw) * scale / 10 ** dec_digits)

        for raw in re.split(r"\*", text):
            line = re.sub(r"[%\s]+", "", raw)
            if not line or line.startswith(("G04", "TA.", "TO.", "TD.")):
                continue
            m = re.match(r"TF\.(\w+),?(.*)", line)
            if m:
                self.attributes[m.group(1)] = m.group(2)
                continue
            m = re.match(r"FSLAX(\d)(\d)Y(\d)(\d)", line)
            if m:
                int_digits, dec_digits = int(m.group(1)), int(m.group(2))
                continue
            if line.startswith("MOMM"):
                scale = NM_PER_MM
                continue
            if line.startswith("MOIN"):
                scale = NM_PER_INCH
                continue
            m = re.match(r"ADD(\d+)(.*)", line, re.S)
            if m:
                apertures[m.group(1)] = re.sub(r"\s+", "", m.group(2))
                continue
            m = re.match(r"LP([CD])", line)
            if m:
                polarity = m.group(1)
                continue
            if line.startswith("G36"):
                in_region, contour = True, []
                continue
            if line.startswith("G37"):
                self.items[("region", polarity, tuple(contour))] += 1
                in_region = False
                continue
            if line in ("G74", "G75"):
                quadrant = line
                continue
            m = re.fullmatch(r"G0?([123])", line)
            if m:
                interp = "G0" + m.group(1)
                continue
            m = re.fullmatch(r"(?:G54)?D(\d+)", line)
            if m and int(m.group(1)) >= 10:
                aperture = apertures.get(m.group(1), "D" + m.group(1))
                continue
            m = re.fullmatch(r"(?:G0?([123]))?(?:X(-?\d+))?(?:Y(-?\d+))?(?:I(-?\d+))?(?:J(-?\d+))?D0?([123])", line)
            if not m:
                continue
            if m.group(1):
                interp = "G0" + m.group(1)
            nx, ny = coord(m.group(2), x), coord(m.group(3), y)
            i, j = coord(m.group(4), 0), coord(m.group(5), 0)
            op = m.group(6)
            if op == "1":
                if interp == "G01":
                    seg = ("line", (x, y), (nx, ny))
                    key = ("draw", polarity, aperture, "line", tuple(sorted([(x, y), (nx, ny)])))
                else:
                    seg = self._arc((x, y), (nx, ny), (x + i, y + j), interp == "G03")
                    key = ("draw", polarity, aperture, quadrant, seg[1:])
                if in_region:
                    contour.append(key[3:])
                else:
                    self.items[key] += 1
                    self.segments.append(seg)
            elif op == "2" and in_region:
                contour.append(("move", nx, ny))
            elif op == "3" and not in_region:
                self.items[("flash", polarity, aperture, nx, ny)] += 1
            x, y = nx, ny

    @staticmethod
    def _arc(p0, p1, centre, ccw: bool) -> tuple:
        """Canonical arc: always counter-clockwise, so a CW arc P->Q equals a CCW arc Q->P."""
        return ("arc", p0, p1, centre, True) if ccw else ("arc", p1, p0, centre, True)

    def outline_box_mm(self) -> tuple[float, float, float, float] | None:
        """Bounding box (x0, y0, x1, y1) in mm of draw centrelines, arcs included."""
        points = []
        for seg in self.segments:
            if seg[0] == "line":
                points += [seg[1], seg[2]]
                continue
            (sx, sy), (ex, ey), (cx, cy), _ = seg[1:]
            r = math.hypot(sx - cx, sy - cy)
            a0 = math.atan2(sy - cy, sx - cx)
            a1 = math.atan2(ey - cy, ex - cx)
            sweep = (a1 - a0) % (2 * math.pi) or 2 * math.pi
            for k in range(65):
                a = a0 + sweep * k / 64
                points.append((cx + r * math.cos(a), cy + r * math.sin(a)))
        if not points:
            return None
        xs, ys = [p[0] for p in points], [p[1] for p in points]
        return (min(xs) / NM_PER_MM, min(ys) / NM_PER_MM, max(xs) / NM_PER_MM, max(ys) / NM_PER_MM)


# ---------------------------------------------------------------- Excellon

class Excellon:
    def __init__(self, text: str):
        self.file_function = ""
        self.tools: dict[str, dict] = {}          # T1 -> {"dia": nm, "plating": "Plated"/"NonPlated"/""}
        self.items: collections.Counter = collections.Counter()
        self._parse(text)

    def _parse(self, text: str) -> None:
        scale = NM_PER_MM
        pending_plating = ""
        tool = None
        x = y = 0
        routing = tool_down = False

        def num(raw: str | None, previous: int) -> int:
            if raw is None:
                return previous
            if "." in raw:
                return round(float(raw) * scale)
            return round(int(raw) * scale / 1000)   # implied 3 decimals; rare in modern output

        def dia(name: str) -> float:
            return self.tools.get(name, {}).get("dia", -1)

        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            m = re.search(r"TF\.FileFunction,([^\s]+)", line)
            if m:
                self.file_function = m.group(1)
                continue
            m = re.search(r"TA\.AperFunction,(\w+)", line)
            if m:
                pending_plating = m.group(1)
                continue
            if line.startswith(";"):
                continue
            if line.startswith("METRIC"):
                scale = NM_PER_MM
                continue
            if line.startswith("INCH"):
                scale = NM_PER_INCH
                continue
            m = re.fullmatch(r"(T\d+)C([\d.]+).*", line)
            if m:
                self.tools[m.group(1)] = {"dia": round(float(m.group(2)) * scale), "plating": pending_plating}
                pending_plating = ""
                continue
            m = re.fullmatch(r"(T\d+)", line)
            if m:
                tool = m.group(1)
                continue
            if line == "M15":
                tool_down = True
                continue
            if line == "M16":
                tool_down = False
                continue
            if line == "G05":
                routing = tool_down = False
                continue
            m = re.fullmatch(r"X(-?[\d.]+)?Y(-?[\d.]+)?G85X(-?[\d.]+)?Y(-?[\d.]+)?", line)
            if m:
                p0 = (num(m.group(1), x), num(m.group(2), y))
                p1 = (num(m.group(3), p0[0]), num(m.group(4), p0[1]))
                self.items[("slot", dia(tool), tuple(sorted([p0, p1])))] += 1
                x, y = p1
                continue
            m = re.fullmatch(r"G0([01])(?:X(-?[\d.]+))?(?:Y(-?[\d.]+))?", line)
            if m and (m.group(2) or m.group(3)):
                nx, ny = num(m.group(2), x), num(m.group(3), y)
                if m.group(1) == "0":
                    routing = True
                elif tool_down:
                    self.items[("route", dia(tool), tuple(sorted([(x, y), (nx, ny)])))] += 1
                x, y = nx, ny
                continue
            m = re.fullmatch(r"X(-?[\d.]+)?Y(-?[\d.]+)?", line)
            if m and not routing:
                x, y = num(m.group(1), x), num(m.group(2), y)
                self.items[("hole", dia(tool), x, y)] += 1
                continue
            if re.match(r"G0[23]", line):
                self.items[("route-arc-raw", dia(tool), line)] += 1

    def plating_of(self, tool_dia: int) -> str:
        """'Plated' / 'NonPlated' for a tool diameter, from per-tool attributes or the file function."""
        for info in self.tools.values():
            if info["dia"] == tool_dia and info["plating"]:
                return info["plating"]
        if self.file_function.startswith("NonPlated"):
            return "NonPlated"
        if self.file_function.startswith("Plated"):
            return "Plated"
        return "Unknown"
