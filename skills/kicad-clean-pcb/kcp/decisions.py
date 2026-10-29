"""`kcp decisions`: read PCB_DECISIONS.md, list unanswered rows, and check checkpoint readiness.

Works on the file in any language: rows are found by their IDs (S1, A1, B1, C1, CP0 ...), and the
answer column by its header ("... (Yes/No)", "Decision", "決定" ...). A blank answer means
"not decided", exactly as the template says.

What each checkpoint needs before it can pass:

    CP0  scope rows (S) and Part A answered, preset chosen
    CP1  as CP0, and CP0 confirmed in Part D
    CP2  S, A, B and C answered; CP0 and CP1 confirmed
    CP4  as CP2, and CP2 confirmed
    CP6  as CP4, CP4 confirmed, and every Part C row answered Yes has a result
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

ID_RE = re.compile(r"^(CP|S|A|B|C)(\d+)$")
PARTS = {"S": "scope", "A": "A", "B": "B", "C": "C", "CP": "D"}
BLANK = {"", "?", "tbd", "todo", "待定", "未定", "未決定", "…", "..."}
YES = {"yes", "y", "ok", "✔", "✓", "✅", "true", "approved", "confirmed", "是", "好", "確認", "已確認", "同意", "可以"}
NO = {"no", "n", "false", "否", "不", "不要", "不同意", "✗", "✘", "❌"}

REQUIREMENTS = {
    "CP0": (("scope", "A"), ()),
    "CP1": (("scope", "A"), ("CP0",)),
    "CP2": (("scope", "A", "B", "C"), ("CP0", "CP1")),
    "CP4": (("scope", "A", "B", "C"), ("CP0", "CP1", "CP2")),
    "CP6": (("scope", "A", "B", "C"), ("CP0", "CP1", "CP2", "CP4")),
}


def _clean(cell: str) -> str:
    cell = cell.strip()
    cell = re.sub(r"<!--.*?-->", "", cell)
    cell = cell.replace("**", "").replace("__", "").strip("`").strip()
    return cell


def is_blank(answer: str) -> bool:
    text = _clean(answer)
    if text.lower() in BLANK:
        return True
    if re.fullmatch(r"_+|<[^>]*>", text):     # "___" or "<fill in>"
        return True
    return False


def is_yes(answer: str) -> bool:
    text = _clean(answer).lower()
    first = re.split(r"[\s(（,，;；:：/]", text, maxsplit=1)[0] if text else ""
    return text in YES or first in YES


def _cells(line: str) -> List[str]:
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|"):
        line = line[:-1]
    return [c.strip() for c in re.split(r"(?<!\\)\|", line)]


def _is_separator(cells: List[str]) -> bool:
    return bool(cells) and all(re.fullmatch(r":?-{2,}:?", c.replace(" ", "")) for c in cells if c)


def _header_index(header: List[str], keys: Tuple[str, ...], avoid: Tuple[str, ...] = ()) -> Optional[int]:
    for i, cell in enumerate(header):
        low = cell.lower().replace(" ", "")
        if any(k in low for k in keys) and not any(a in low for a in avoid):
            return i
    return None


def _decision_column(header: List[str]) -> Optional[int]:
    avoid = ("rec", "建議")
    found = _header_index(header, ("yes/no", "是/否", "yes／no"), avoid)
    if found is None:
        found = _header_index(header, ("decision", "決定", "決策", "選擇", "答覆", "回答", "confirmed", "已確認"), avoid)
    return found


def parse(text: str) -> Dict:
    lines = text.splitlines()
    rows, warnings, seen = [], [], set()
    preset: Optional[str] = None
    preset_line = False
    for line in lines:
        m = re.search(r"(?i)(preset chosen|選定的?預設|預設風格|選擇的預設)[^:：]*[:：]\s*(.*)$", line)
        if m:
            preset_line = True
            value = _clean(m.group(2))
            preset = None if is_blank(value) else value

    i = 0
    while i < len(lines):
        if not lines[i].lstrip().startswith("|"):
            i += 1
            continue
        block = []
        while i < len(lines) and lines[i].lstrip().startswith("|"):
            block.append(_cells(lines[i]))
            i += 1
        if len(block) < 3 or not _is_separator(block[1]):
            continue
        header, body = block[0], block[2:]
        col = _decision_column(header)
        result_col = _header_index(header, ("result", "結果"))
        id_rows = [r for r in body if r and ID_RE.match(_clean(r[0]))]
        if not id_rows:
            continue
        if col is None:
            warnings.append(f"table starting '{' | '.join(header)[:60]}' has row IDs but no answer column")
            continue
        for r in id_rows:
            row_id = _clean(r[0])
            m = ID_RE.match(row_id)
            part = PARTS[m.group(1)]
            if row_id in seen:
                warnings.append(f"duplicate row ID {row_id}")
            seen.add(row_id)
            answer = _clean(r[col]) if col < len(r) else ""
            item = _clean(r[1]) if len(r) > 1 else ""
            entry = {"id": row_id, "part": part, "item": item[:100], "answer": answer,
                     "blank": is_blank(answer)}
            if result_col is not None:
                entry["result"] = _clean(r[result_col]) if result_col < len(r) else ""
            rows.append(entry)
    return {"rows": rows, "preset": preset, "preset_line": preset_line, "warnings": warnings}


def check(parsed: Dict, checkpoint: Optional[str] = None) -> Dict:
    rows = parsed["rows"]
    parts: Dict[str, Dict] = {}
    for name in ("scope", "A", "B", "C", "D"):
        mine = [r for r in rows if r["part"] == name]
        parts[name] = {"rows": len(mine), "answered": sum(1 for r in mine if not r["blank"]),
                       "blank": [r["id"] for r in mine if r["blank"]]}
    verdict = None
    if checkpoint:
        cp = checkpoint.upper().replace("-", "")
        if cp not in REQUIREMENTS:
            raise ValueError(f"unknown checkpoint {checkpoint!r}; use one of {', '.join(REQUIREMENTS)}")
        need_parts, need_signoffs = REQUIREMENTS[cp]
        missing = []
        for name in need_parts:
            if parts[name]["rows"] == 0:
                missing.append(f"{'scope check' if name == 'scope' else 'Part ' + name}: no rows found")
            missing += parts[name]["blank"]
        if "A" in need_parts and parsed["preset_line"] and not parsed["preset"]:
            missing.append("preset chosen")
        signoff = {r["id"]: r for r in rows if r["part"] == "D"}
        for cp_id in need_signoffs:
            r = signoff.get(cp_id)
            if r is None:
                missing.append(f"Part D: no {cp_id} row")
            elif not is_yes(r["answer"]):
                missing.append(f"{cp_id} not confirmed in Part D")
        if cp == "CP6":
            for r in rows:
                if r["part"] == "C" and is_yes(r["answer"]) and not r.get("result"):
                    missing.append(f"{r['id']} answered Yes but has no result")
        verdict = {"id": cp, "ok": not missing, "missing": missing}
    return {"preset": parsed["preset"], "parts": parts,
            "blank_rows": [{"id": r["id"], "item": r["item"]} for r in rows if r["blank"]],
            "checkpoint": verdict, "warnings": parsed["warnings"]}


def check_file(path: Union[str, Path], checkpoint: Optional[str] = None) -> Dict:
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"decisions file not found: {path}")
    result = check(parse(path.read_text(encoding="utf-8")), checkpoint)
    return {"tool": "kcp decisions", "file": str(path), **result}


def to_markdown(result: Dict) -> str:
    lines = [f"# Decisions: `{result['file']}`", "", f"Preset chosen: {result['preset'] or '(blank)'}", "",
             "| Part | Rows | Answered | Blank |", "|---|---:|---:|---|"]
    for name, p in result["parts"].items():
        label = "Scope check" if name == "scope" else f"Part {name}"
        lines.append(f"| {label} | {p['rows']} | {p['answered']} | {', '.join(p['blank']) or '—'} |")
    cp = result.get("checkpoint")
    if cp:
        lines += ["", f"## {cp['id']}: {'ready' if cp['ok'] else 'NOT ready'}"]
        lines += [f"- {m}" for m in cp["missing"]]
    if result["warnings"]:
        lines += ["", "## Warnings"] + [f"- {w}" for w in result["warnings"]]
    return "\n".join(lines) + "\n"
