# -*- coding: utf-8 -*-
"""
The tuning project: a folder Claude Code works in.

    <folder>/
      CLAUDE.md               the owner's file; the program only makes sure it contains
                              the line "@.claude/ms43-rules.md" (an import)
      .claude/ms43-rules.md   rules, the setup, the tools — always regenerated
      .claude/settings.json   UTF-8 for Python, deny edits of generated files, the
                              SessionStart check (merged: the owner's keys stay)
      .claude/hooks/session_check.py   is the window open, files changed by hand, loose logs
      .claude/skills/*/       log review, ignition, fuel trims, test runs, change requests
      .mcp.json               connects Claude Code to the live server of the window
      tools/ms43log.py        TunerPro log loader for the bundled Python
      logs/  analysis/        logs; scripts, charts and notes (analysis/STATE.md: the
                              current state of the car, created once, kept by Claude)
      .ms43project.json       what the program generated (hashes), see below

Skills and tools: a file the owner has changed since it was generated (its hash
differs from the one recorded) is kept and reported. The owner's own skills
(any other folder in .claude/skills) are never touched.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from typing import Dict, List, Optional, Tuple

from . import i18n
from .i18n import t

KIT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "projectkit")
MANIFEST = ".ms43project.json"
RULES = ".claude/ms43-rules.md"
IMPORT_LINE = "@.claude/ms43-rules.md"
HOOK = ".claude/hooks/session_check.py"
BRIDGE = ".claude/ms43_bridge.py"
TOOLS_CACHE = ".claude/ms43-tools.json"
# regenerated every time, whatever is in them (the owner's notes go to CLAUDE.md)
ALWAYS = (RULES, ".mcp.json")
STATE_TEMPLATE = """# Current state of the car

Kept by Claude after each log review: open faults, what was checked, the firmware in the
car, the next step. Short — the details stay in analysis/<log>_review.md.
"""
LANG_NAMES = {"en": "English", "ru": "Russian"}


def kit_dir() -> str:
    """The templates; inside a PyInstaller .exe they are unpacked to sys._MEIPASS."""
    base = getattr(sys, "_MEIPASS", None)
    if base and os.path.isdir(os.path.join(base, "ms43diff", "projectkit")):
        return os.path.join(base, "ms43diff", "projectkit")
    return KIT


def bundled_python() -> str:
    """The Python Claude Code should run: the one shipped next to the .exe, else this one."""
    if getattr(sys, "frozen", False):
        candidate = os.path.join(os.path.dirname(sys.executable), "python", "python.exe")
        if os.path.isfile(candidate):
            return candidate
        return "python"
    return sys.executable or "python"


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _templates() -> Dict[str, str]:
    """Project path -> template path."""
    kit = kit_dir()
    out = {RULES: os.path.join(kit, "CLAUDE.md"),
           "tools/ms43log.py": os.path.join(kit, "tools", "ms43log.py"),
           HOOK: os.path.join(kit, "hooks", "session_check.py"),
           BRIDGE: os.path.join(kit, "tools", "ms43_bridge.py")}
    skills = os.path.join(kit, "skills")
    for name in sorted(os.listdir(skills)):
        path = os.path.join(skills, name, "SKILL.md")
        if os.path.isfile(path):
            out[f".claude/skills/{name}/SKILL.md"] = path
    return out


def _fill(text: str, values: Dict[str, str]) -> str:
    for key, value in values.items():
        text = text.replace("{" + key + "}", value)
    return text


def mcp_config(url: str, token: str, name: str = "ms43", python: str = "",
               bridge: str = "") -> str:
    """Through the bridge (Claude Code starts it, so the server never "fails" while the window
    is closed) when the bundled Python is there; else straight to the window over HTTP."""
    if python and bridge and os.path.isfile(python):
        server = {"type": "stdio", "command": python, "args": [bridge],
                  "env": {"MS43_URL": url, "MS43_TOKEN": token,
                          "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}}
    else:
        server = {"type": "http", "url": url, "headers": {"Authorization": f"Bearer {token}"}}
    return json.dumps({"mcpServers": {name: server}}, indent=2) + "\n"


def tool_list() -> List[Dict]:
    """The tools of the live server, for the bridge to show while the window is closed."""
    from . import mcpserver

    answer = mcpserver.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}) or {}
    return (answer.get("result") or {}).get("tools") or []


def _settings(path: str, python: str, hook: str, generated: List[str]) -> bytes:
    """.claude/settings.json: the owner's keys stay, ours are set."""
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, dict):
            data = {}
    except (OSError, ValueError):
        data = {}
    env = data.setdefault("env", {})
    env.update(PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    perms = data.setdefault("permissions", {})
    ours = []
    for rel in generated:
        target = "/" + (rel.rsplit("/", 1)[0] + "/**" if rel.startswith(".claude/skills/") else rel)
        ours += [f"Edit({target})", f"Write({target})"]
    deny = [r for r in perms.get("deny", []) if r not in ours]
    perms["deny"] = deny + sorted(set(ours))
    hooks = data.setdefault("hooks", {})
    start = [h for h in hooks.get("SessionStart", [])
             if "session_check.py" not in json.dumps(h)]
    if python and os.path.isfile(python):
        start.append({"hooks": [{"type": "command", "command": f'"{python}" "{hook}"'}]})
    if start:
        hooks["SessionStart"] = start
    else:
        hooks.pop("SessionStart", None)
    if not hooks:
        data.pop("hooks", None)
    return (json.dumps(data, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def _claude_md(path: str, name: str, old_hash: Optional[str]) -> Optional[bytes]:
    """The owner's CLAUDE.md with the import line; None when nothing to change."""
    start = (f"# {name}\n\n{IMPORT_LINE}\n\nThe current state of the car: analysis/STATE.md.\n"
             "Your own notes about the car and the project go below.\n")
    if not os.path.isfile(path):
        return start.encode("utf-8")
    with open(path, "rb") as fh:
        current = fh.read()
    if old_hash and _sha(current) == old_hash:
        return start.encode("utf-8")          # the old full rules we generated, untouched
    text = current.decode("utf-8", errors="replace")
    if IMPORT_LINE in text:
        return None
    return (text.rstrip("\n") + "\n\n" + IMPORT_LINE + "\n").encode("utf-8")


def create_or_update(folder: str, values: Dict[str, str], url: str, token: str,
                     server: str = "ms43") -> Dict[str, List[str]]:
    """Write the project files. Returns {"written": [...], "kept": [...]}."""
    folder = os.path.abspath(folder)
    os.makedirs(folder, exist_ok=True)
    for sub in ("logs", "analysis"):
        os.makedirs(os.path.join(folder, sub), exist_ok=True)
    manifest_path = os.path.join(folder, MANIFEST)
    try:
        with open(manifest_path, encoding="utf-8") as fh:
            manifest = json.load(fh)
    except (OSError, ValueError):
        manifest = {}
    hashes: Dict[str, str] = dict(manifest.get("files") or {})
    old_claude = hashes.pop("CLAUDE.md", None)      # CLAUDE.md is the owner's from now on
    files: Dict[str, bytes] = {}
    for rel, src in _templates().items():
        with open(src, encoding="utf-8") as fh:
            text = fh.read()
        files[rel] = (text if rel.endswith(".py") else _fill(text, values)).encode("utf-8")
    files[".mcp.json"] = mcp_config(url, token, server, values.get("python", ""),
                                    os.path.join(folder, *BRIDGE.split("/"))).encode("utf-8")

    written, kept = [], []
    for rel, data in files.items():
        path = os.path.join(folder, *rel.split("/"))
        if os.path.isfile(path):
            with open(path, "rb") as fh:
                current = fh.read()
            if current == data:
                hashes[rel] = _sha(data)
                continue
            if rel not in ALWAYS and hashes.get(rel) != _sha(current):
                kept.append(rel)            # changed by the owner (or not ours): keep it
                continue
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as fh:
            fh.write(data)
        hashes[rel] = _sha(data)
        written.append(rel)

    # files that are partly the owner's: changed in place, never replaced
    generated = [rel for rel in files if rel not in (".mcp.json",)]
    extra = {
        "CLAUDE.md": _claude_md(os.path.join(folder, "CLAUDE.md"), values.get("name", "MS43"),
                                old_claude),
        ".claude/settings.json": _settings(os.path.join(folder, ".claude", "settings.json"),
                                           values.get("python", ""),
                                           os.path.join(folder, *HOOK.split("/")), generated),
    }
    gitignore = os.path.join(folder, ".gitignore")
    try:
        with open(gitignore, encoding="utf-8") as fh:
            ignore = fh.read()
    except OSError:
        ignore = ""
    if ".mcp.json" not in ignore.split():
        extra[".gitignore"] = (ignore.rstrip("\n") + ("\n" if ignore.strip() else "")
                               + "# the token of the MS43 AI-Tuner window\n.mcp.json\n").encode("utf-8")
    extra[TOOLS_CACHE] = json.dumps(tool_list(), ensure_ascii=False).encode("utf-8")
    state = os.path.join(folder, "analysis", "STATE.md")
    if not os.path.isfile(state):
        extra["analysis/STATE.md"] = STATE_TEMPLATE.encode("utf-8")
    for rel, data in extra.items():
        if data is None:
            continue
        path = os.path.join(folder, *rel.split("/"))
        if os.path.isfile(path):
            with open(path, "rb") as fh:
                if fh.read() == data:
                    continue
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as fh:
            fh.write(data)
        written.append(rel)
    with open(manifest_path, "w", encoding="utf-8") as fh:
        json.dump({"generator": "MS43 AI-Tuner", "files": hashes}, fh, indent=1)
    return {"written": written, "kept": kept, "folder": folder}


def has_history(folder: str) -> bool:
    """Has Claude Code kept a conversation for this folder (~/.claude/projects/<folder>)?"""
    key = re.sub(r"[^A-Za-z0-9]", "-", os.path.abspath(folder))
    path = os.path.join(os.path.expanduser("~"), ".claude", "projects", key)
    try:
        return any(name.endswith(".jsonl") for name in os.listdir(path))
    except OSError:
        return False


DESKTOP_MIN = (2, 1, 285)          # `claude --desktop` appeared in this version


def claude_version(claude: str) -> Optional[Tuple[int, ...]]:
    """The installed Claude Code version, e.g. (2, 1, 284); None when unknown."""
    try:
        res = subprocess.run([claude, "--version"], capture_output=True, text=True, timeout=30,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.TimeoutExpired):
        return None
    m = re.search(r"(\d+)\.(\d+)\.(\d+)", res.stdout or "")
    return tuple(int(x) for x in m.groups()) if m else None


def open_in_claude_code(folder: str, where: str = "desktop") -> str:
    """Open the project in Claude Code: the Code tab of the desktop app ("desktop", needs
    Claude Code 2.1.285+) or a terminal ("terminal"). The last conversation in the folder
    is continued when there is one. An older Claude Code opens a terminal instead.
    Returns what was done: "desktop", "terminal" or "terminal_old" (desktop asked, too old)."""
    claude = shutil.which("claude")
    if not claude:
        raise FileNotFoundError(t("The claude command was not found. Install Claude Code, then "
                                  "open the project folder in it."))
    extra = ["--continue"] if has_history(folder) else []
    no_window = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    if where == "desktop":
        version = claude_version(claude)
        if version is not None and version < DESKTOP_MIN:
            _open_terminal(claude, folder, extra)
            return "terminal_old"
        try:
            res = subprocess.run([claude, "--desktop", *extra], cwd=folder, capture_output=True,
                                 text=True, timeout=60, creationflags=no_window)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise FileNotFoundError(str(exc)) from exc
        if res.returncode != 0 and "unknown option" in (res.stderr + res.stdout).lower():
            _open_terminal(claude, folder, extra)
            return "terminal_old"
        if res.returncode != 0:
            detail = (res.stderr or res.stdout or "").strip().splitlines()
            raise FileNotFoundError(
                t("The desktop app did not open: {error}. Update Claude Code (claude update; "
                  "needs 2.1.285 or newer and the Claude desktop app) or open it in a terminal.",
                  error=detail[-1][:200] if detail else res.returncode))
        return "desktop"
    _open_terminal(claude, folder, extra)
    return "terminal"


def _open_terminal(claude: str, folder: str, extra: List[str]) -> None:
    if os.name == "nt":
        subprocess.Popen(["cmd", "/c", "start", "", "cmd", "/k", "claude", *extra], cwd=folder,
                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    else:  # pragma: no cover - development only
        subprocess.Popen([claude, *extra], cwd=folder)


def default_values(name: str, firmware: str, xdf: str, bin_a: str, bin_b: str,
                   lang: Optional[str] = None) -> Dict[str, str]:
    lang = lang or i18n.get_lang()
    return {"name": name, "lang_name": LANG_NAMES.get(lang, "English"), "firmware": firmware or "?",
            "xdf": xdf or "—", "bin_a": bin_a or "—", "bin_b": bin_b or "—",
            "python": bundled_python(), "mcp_url": "", "car": ""}
