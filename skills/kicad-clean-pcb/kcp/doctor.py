"""`kcp doctor`: which copies of the skill and kcp are on this machine, and which one is running.

An agent follows whatever copy its session loaded. A stale Claude Code plugin, or an old folder
copied into ~/.claude/skills, gives it old instructions and old MCP tools without any error.
This lists every copy it can find with its version and says what to update.

    python <skill>/kcp doctor [--markdown]
"""
from __future__ import annotations

import json
import os
import re
import shutil
import sys
from pathlib import Path
from typing import Dict, List, Mapping, Optional

from . import __version__

NAME = "kicad-clean-pcb"


def version_key(text: Optional[str]):
    return tuple(int(n) for n in re.findall(r"\d+", text or "")[:3]) or (0,)


def claude_cli(env: Optional[Mapping[str, str]] = None) -> Optional[Dict]:
    """The `claude` command: on PATH, or else the copy the Claude desktop app runs for its Code tab,
    which is not on PATH (Windows: %APPDATA%\\Claude\\claude-code\\<version>\\<build>\\claude.exe;
    the folder changes when the app updates). {"path", "on_path"} or None."""
    env = os.environ if env is None else env
    found = shutil.which("claude", path=env.get("PATH", ""))
    if found:
        return {"path": found, "on_path": True}
    appdata = env.get("APPDATA")
    bundled = list(Path(appdata, "Claude", "claude-code").glob("*/*/claude.exe")) if appdata else []
    if not bundled:
        return None
    newest = max(bundled, key=lambda p: version_key(p.parent.parent.name))
    return {"path": str(newest), "on_path": False}


def update_steps(plugin_id: str, cli: Optional[Dict]) -> str:
    """How to update the plugin, with the claude command that works on this machine."""
    exe = f'"{cli["path"]}"' if cli and not cli["on_path"] else "claude"
    market = plugin_id.split("@", 1)[-1]
    text = (f"run `{exe} plugin marketplace update {market}` and then `{exe} plugin update {plugin_id}` "
            f"(or in a Claude Code session: /plugin, Installed tab, {plugin_id}, Update now), then start a "
            f"new session.")
    if cli and not cli["on_path"]:
        text += (" The claude command is not on PATH here; that path is the copy the Claude desktop app runs "
                 "(in PowerShell put & before it). You can run these for the user.")
    elif cli is None:
        text += (" No claude command was found: the user can run the update from a Claude Code session or "
                 "install the Claude Code CLI.")
    return text


def kcp_version(skill: Path) -> Optional[str]:
    """__version__ of <skill>/kcp, read from the file (not imported)."""
    try:
        text = (skill / "kcp" / "__init__.py").read_text(encoding="utf-8")
    except OSError:
        return None
    m = re.search(r"__version__\s*=\s*[\"']([^\"']+)", text)
    return m.group(1) if m else None


def skill_md_version(skill: Path) -> Optional[str]:
    """metadata.version from the SKILL.md front matter."""
    try:
        text = (skill / "SKILL.md").read_text(encoding="utf-8")
    except OSError:
        return None
    front = text.split("---", 2)[1] if text.startswith("---") else ""
    m = re.search(r"^\s*version:\s*[\"']?([0-9][0-9A-Za-z.\-]*)", front, re.M)
    return m.group(1) if m else None


def _claude_dir() -> Path:
    return Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")


def _same(a: Path, b: Path) -> bool:
    try:
        return a.resolve() == b.resolve()
    except OSError:
        return False


def installed_plugins(claude: Optional[Path] = None) -> List[Dict]:
    """Entries for this plugin in Claude Code's installed_plugins.json."""
    claude = claude or _claude_dir()
    try:
        data = json.loads((claude / "plugins" / "installed_plugins.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    out = []
    for plugin_id, entries in (data.get("plugins") or {}).items():
        if not plugin_id.startswith(NAME + "@"):
            continue
        for entry in entries if isinstance(entries, list) else [entries]:
            path = Path(entry.get("installPath", "")) / "skills" / NAME
            out.append({"id": plugin_id, "scope": entry.get("scope"), "version": entry.get("version"),
                        "path": str(path)})
    return out


def find_copies(cwd: Optional[Path] = None, claude: Optional[Path] = None, home: Optional[Path] = None) -> List[Dict]:
    """Every skill folder named kicad-clean-pcb that an agent could load, with its versions."""
    claude = claude or _claude_dir()
    home = home or Path.home()
    places = []
    for plugin in installed_plugins(claude):
        places.append((f"Claude Code plugin {plugin['id']} ({plugin['scope']} scope)", Path(plugin["path"])))
    cache = claude / "plugins" / "cache"
    for folder in sorted(cache.glob(f"*/{NAME}/*/skills/{NAME}")):
        places.append(("plugin cache", folder))
    places += [("user skill (Claude Code)", claude / "skills" / NAME),
               ("user skill (Codex, other agents)", home / ".agents" / "skills" / NAME),
               ("user skill (older Codex)", home / ".codex" / "skills" / NAME)]
    if cwd is not None:
        places += [("project skill (Claude Code)", cwd / ".claude" / "skills" / NAME),
                   ("project skill (Codex, other agents)", cwd / ".agents" / "skills" / NAME)]
    copies: List[Dict] = []
    for where, folder in places:
        if not (folder / "SKILL.md").is_file():
            continue
        if any(_same(folder, Path(c["path"])) for c in copies):
            continue                      # the installed plugin's own folder is also in the cache
        copies.append({"where": where, "path": str(folder), "skill_md": skill_md_version(folder),
                       "kcp": kcp_version(folder)})
    return copies


def doctor(cwd: Optional[Path] = None, claude: Optional[Path] = None, cli_check: bool = True,
           home: Optional[Path] = None, env: Optional[Mapping[str, str]] = None) -> Dict:
    """The report described in the module docstring. claude: Claude Code's config folder
    (default $CLAUDE_CONFIG_DIR or ~/.claude); home: for ~/.agents and ~/.codex; env: for PATH and
    APPDATA when looking for the claude command (tests)."""
    running = Path(__file__).resolve().parent
    skill = running.parent
    claude = claude or _claude_dir()
    cli = claude_cli(env)
    copies = find_copies(cwd if cwd is not None else Path.cwd(), claude, home)
    for c in copies:
        c["in_use"] = _same(Path(c["path"]), skill)
    if not any(c["in_use"] for c in copies):
        copies.insert(0, {"where": "this copy (a clone, a pip install or a custom folder)", "path": str(skill),
                          "skill_md": skill_md_version(skill), "kcp": __version__, "in_use": True})
    warnings: List[str] = []

    here_md = skill_md_version(skill)
    if here_md and here_md != __version__:
        warnings.append(f"SKILL.md next to this kcp says {here_md} but kcp is {__version__}: the folder "
                        f"{skill} mixes two versions; reinstall it.")

    plugins = installed_plugins(claude)
    newest = max([__version__] + [c["kcp"] or c["skill_md"] for c in copies if c["kcp"] or c["skill_md"]],
                 key=version_key)
    for plugin in plugins:
        if version_key(plugin["version"]) < version_key(newest):
            warnings.append(f"The Claude Code plugin {plugin['id']} is {plugin['version']}, older than {newest} "
                            f"(found on this machine). Sessions load the plugin's SKILL.md and MCP tools, so "
                            f"they follow {plugin['version']}. To update, " + update_steps(plugin["id"], cli))
    if version_key(__version__) < version_key(newest):
        better = [c for c in copies if (c["kcp"] or "") == newest]
        where = better[0]["path"] if better else "another folder"
        warnings.append(f"This kcp is {__version__} ({skill}); {newest} is at {where}. Run that one, or "
                        f"update this copy.")

    for c in copies:
        if c["in_use"] or not c["where"].startswith(("user skill", "project skill")):
            continue
        version = c["kcp"] or c["skill_md"]
        label = f"version {version}" if version else "no version number, so from before 0.2"
        if plugins and "(Claude Code)" in c["where"]:
            warnings.append(f"{c['path']} ({label}) has the same name as the plugin's skill, and Claude Code "
                            f"loads it instead of the plugin's. Keep one install method: remove that folder "
                            f"(ask the user first) or uninstall the plugin.")
        elif version_key(version) < version_key(newest):
            agent = "Claude Code" if "(Claude Code)" in c["where"] else "Codex and other agents that read it"
            warnings.append(f"{c['path']} ({label}) is older than {newest}: {agent} follow that copy. Update "
                            f"it or remove it (ask the user first).")

    kicad = {"checked": cli_check, "path": None, "version": None}
    if cli_check:
        from . import kicad_cli
        found = kicad_cli.find_kicad_cli()
        if found is None:
            warnings.append("kicad-cli not found: install KiCad 10 or set KICAD_CLI. ERC, DRC, previews and "
                            "fab output need it.")
        else:
            kicad["path"] = str(found)
            try:
                kicad["version"] = kicad_cli.version(found)
            except Exception as exc:     # a broken install should not stop the report
                warnings.append(f"kicad-cli at {found} did not run: {exc}")
            if kicad["version"] and version_key(kicad["version"])[0] < 10:
                warnings.append(f"KiCad {kicad['version']}: kcp is tested with KiCad 10 only.")

    return {"tool": "kcp doctor", "ok": not warnings,
            "kcp": {"version": __version__, "path": str(running)},
            "skill_md": {"version": here_md, "path": str(skill / "SKILL.md")},
            "python": {"version": sys.version.split()[0], "executable": sys.executable},
            "kicad_cli": kicad, "claude_cli": cli, "copies": copies, "warnings": warnings}


def to_markdown(data: Dict) -> str:
    status = "OK" if data["ok"] else f"{len(data['warnings'])} problem(s)"
    kicad = data["kicad_cli"]
    if not kicad.get("checked", True):
        kicad_line = "not checked (--no-kicad)"
    else:
        kicad_line = (kicad["version"] or "not found") + (f" (`{kicad['path']}`)" if kicad["path"] else "")
    cli = data.get("claude_cli")
    if cli is None:
        claude_line = "not found"
    elif cli["on_path"]:
        claude_line = f"on PATH (`{cli['path']}`)"
    else:
        claude_line = f"not on PATH; the Claude desktop app's copy is `{cli['path']}`"
    lines = [f"# kcp doctor: {status}", "",
             f"- Running: kcp {data['kcp']['version']} at `{data['kcp']['path']}`",
             f"- SKILL.md next to it: {data['skill_md']['version']}",
             f"- Python {data['python']['version']} (`{data['python']['executable']}`)",
             f"- kicad-cli: {kicad_line}",
             f"- claude command (for plugin updates): {claude_line}", ""]
    if data["copies"]:
        lines += ["| Where | Version (SKILL.md / kcp) | In use | Path |", "|---|---|---|---|"]
        for c in data["copies"]:
            lines.append(f"| {c['where']} | {c['skill_md'] or '?'} / {c['kcp'] or 'none'} | "
                         f"{'yes' if c['in_use'] else ''} | `{c['path']}` |")
        lines.append("")
    if data["warnings"]:
        lines += ["## Problems", ""] + [f"- {w}" for w in data["warnings"]]
    return "\n".join(lines) + "\n"
