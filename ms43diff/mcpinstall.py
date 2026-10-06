# -*- coding: utf-8 -*-
"""
Connecting the ms43diff MCP server to Claude Desktop.

Claude Desktop reads its MCP servers from claude_desktop_config.json:

    {"mcpServers": {"ms43": {"command": "...", "args": [...]}}}

install() adds (or replaces) our entry and keeps everything else in the file
untouched; a copy of the previous file is saved next to it as .bak first.
The command is worked out from where the program itself runs, so no paths are
hard-coded anywhere (the .bat wrappers stay free of personal data).

Claude Desktop reads the file at start-up, so it has to be restarted (quit from
the tray, not just closed) for a change to take effect. Where the file lives
depends on how Claude Desktop was installed, see config_candidates().
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from typing import Dict, List, Optional, Tuple

from .i18n import get_lang, t

SERVER_NAME = "ms43"
MCP_EXE = "ms43-ai-tuner-mcp.exe"
OLD_MCP_EXES = ("ms43diff-mcp.exe",)      # names used by earlier releases


class InstallError(RuntimeError):
    """The server could not be connected; the message says why."""


def config_candidates() -> List[str]:
    """Possible claude_desktop_config.json locations, most specific first.

    On Windows Claude Desktop comes in two flavours. The Microsoft Store (MSIX)
    package keeps its config in its own virtualised folder
    %LOCALAPPDATA%\\Packages\\Claude_*\\LocalCache\\Roaming\\Claude — a file in
    %APPDATA%\\Claude is simply never read by it. The classic installer uses
    %APPDATA%\\Claude.
    """
    out: List[str] = []
    if sys.platform == "win32":
        packages = os.path.join(os.environ.get("LOCALAPPDATA") or "", "Packages")
        try:
            names = sorted(n for n in os.listdir(packages) if n.lower().startswith("claude_"))
        except OSError:
            names = []
        for name in names:
            out.append(os.path.join(packages, name, "LocalCache", "Roaming", "Claude",
                                    "claude_desktop_config.json"))
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
        out.append(os.path.join(base, "Claude", "claude_desktop_config.json"))
    elif sys.platform == "darwin":
        out.append(os.path.expanduser(
            "~/Library/Application Support/Claude/claude_desktop_config.json"))
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
        out.append(os.path.join(base, "Claude", "claude_desktop_config.json"))
    return out


def config_path() -> str:
    """The config Claude Desktop actually reads.

    A Store (MSIX) installation wins: if its package folder exists, that is the
    Claude Desktop in use, whether or not its config file was created yet.
    """
    candidates = config_candidates()
    for path in candidates[:-1]:
        if os.path.isdir(os.path.dirname(os.path.dirname(os.path.dirname(path)))):
            return path
    return candidates[-1]


def claude_running() -> bool:
    """Is Claude Desktop running? It may overwrite a config edited under it."""
    if sys.platform != "win32":
        return False
    import subprocess

    try:
        out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq claude.exe", "/NH"],
                             capture_output=True, text=True, timeout=10,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
    except (OSError, subprocess.SubprocessError):
        return False
    return "claude.exe" in out.lower()


def server_command() -> List[str]:
    """Command that starts the MCP server from this installation."""
    if getattr(sys, "frozen", False):
        exe = os.path.abspath(sys.executable)
        if os.path.basename(exe).lower() in (MCP_EXE,) + OLD_MCP_EXES:
            return [exe]
        for name in (MCP_EXE,) + OLD_MCP_EXES:
            sibling = os.path.join(os.path.dirname(exe), name)
            if os.path.isfile(sibling):
                return [sibling]
        raise InstallError(t("{exe} not found next to {here}. Keep both .exe files "
                             "in the same folder.", exe=MCP_EXE, here=os.path.dirname(exe)))
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    script = os.path.join(root, "mcp_main.py")
    if os.path.isfile(script):
        return [os.path.abspath(sys.executable), script]
    return [os.path.abspath(sys.executable), "-m", "ms43diff", "mcp"]


def split_paths(paths: List[str]) -> Tuple[Optional[str], Optional[str]]:
    """Pick the .xdf and the .bin out of a list of paths (drag-and-drop order varies)."""
    xdf = bin_ = None
    for path in paths:
        ext = os.path.splitext(path)[1].lower()
        if ext == ".xdf" and xdf is None:
            xdf = path
        elif ext != ".xdf" and bin_ is None:
            bin_ = path
    return xdf, bin_


def _read_config(path: str) -> Dict:
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, encoding="utf-8-sig") as fh:
            text = fh.read()
    except OSError as exc:
        raise InstallError(t("Cannot read {path}: {error}", path=path, error=exc)) from exc
    if not text.strip():
        return {}
    try:
        data = json.loads(text)
    except ValueError as exc:
        # Never overwrite a file we do not understand: the user may lose settings.
        raise InstallError(t("{path} is not valid JSON ({error}). Fix or remove it "
                             "first; nothing was changed.", path=path, error=exc)) from exc
    if not isinstance(data, dict):
        raise InstallError(t("{path} has an unexpected structure; nothing was changed.",
                             path=path))
    return data


def _write_config(path: str, data: Dict) -> Optional[str]:
    """Write atomically; back up the previous file. Returns the backup path."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    backup = None
    if os.path.isfile(path):
        backup = path + ".bak"
        shutil.copy2(path, backup)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    os.replace(tmp, path)
    return backup


def status(name: str = SERVER_NAME) -> Optional[Dict]:
    """Our entry in the Claude Desktop config, or None."""
    try:
        data = _read_config(config_path())
    except InstallError:
        return None
    servers = data.get("mcpServers")
    if isinstance(servers, dict) and isinstance(servers.get(name), dict):
        return servers[name]
    return None


def install(xdf: str, bin_path: str, name: str = SERVER_NAME,
            lang: Optional[str] = None) -> Dict:
    """Add/replace the server entry. Returns details for the user."""
    for label, path in ((".xdf", xdf), (".bin", bin_path)):
        if not path or not os.path.isfile(path):
            raise InstallError(t("{kind} file not found: {path}", kind=label, path=path or "—"))
    command = server_command()
    entry = {
        "command": command[0],
        "args": command[1:] + ["--xdf", os.path.abspath(xdf),
                               "--bin", os.path.abspath(bin_path),
                               "--lang", lang or get_lang()],
    }
    path = config_path()
    data = _read_config(path)
    servers = data.get("mcpServers")
    if not isinstance(servers, dict):
        servers = {}
        data["mcpServers"] = servers
    replaced = name in servers
    servers[name] = entry
    backup = _write_config(path, data)
    return {"config": path, "backup": backup, "replaced": replaced, "entry": entry,
            "name": name, "running": claude_running()}


def uninstall(name: str = SERVER_NAME) -> Dict:
    """Remove the server entry. Returns details for the user."""
    path = config_path()
    data = _read_config(path)
    servers = data.get("mcpServers")
    if not isinstance(servers, dict) or name not in servers:
        return {"config": path, "removed": False, "backup": None, "name": name}
    del servers[name]
    backup = _write_config(path, data)
    return {"config": path, "removed": True, "backup": backup, "name": name,
            "running": claude_running()}


def install_message(info: Dict) -> str:
    entry = info["entry"]
    args = entry["args"]
    lines = [
        t("The \"{name}\" server was updated in Claude Desktop.", name=info["name"])
        if info["replaced"] else
        t("The \"{name}\" server was added to Claude Desktop.", name=info["name"]),
        "",
        t("Config: {path}", path=info["config"]),
    ]
    if info["backup"]:
        lines.append(t("Previous version saved as: {path}", path=info["backup"]))
    if info.get("running"):
        lines += ["", t("Claude Desktop is running now: quit it completely (tray icon → Quit) "
                        "before starting it again, otherwise it may overwrite this change.")]
    lines += [
        t("XDF: {path}", path=args[args.index("--xdf") + 1]),
        t("Firmware: {path}", path=args[args.index("--bin") + 1]),
        "",
        t("Quit Claude Desktop completely (tray icon → Quit) and start it again. "
          "Then ask in a chat, e.g. \"What is my rev limit?\""),
    ]
    return "\n".join(lines)


def uninstall_message(info: Dict) -> str:
    if not info["removed"]:
        return t("The \"{name}\" server is not connected; nothing to remove.\nConfig: {path}",
                 name=info["name"], path=info["config"])
    text = t("The \"{name}\" server was removed from Claude Desktop.\nConfig: {path}\n"
             "Restart Claude Desktop for the change to take effect.",
             name=info["name"], path=info["config"])
    if info.get("running"):
        text += "\n\n" + t("Claude Desktop is running now: quit it completely (tray icon → Quit) "
                            "before starting it again, otherwise it may overwrite this change.")
    return text


# ---------------------------------------------------------------------------
# Listing and checking our entries
# ---------------------------------------------------------------------------

def is_ours(entry: Dict) -> bool:
    """Was this config entry made for an ms43diff / MS43 AI-Tuner server?"""
    if not isinstance(entry, dict):
        return False
    command = os.path.basename(str(entry.get("command", ""))).lower()
    args = [str(a) for a in entry.get("args") or []]
    return (command in (MCP_EXE,) + OLD_MCP_EXES
            or any(os.path.basename(a).lower() == "mcp_main.py" for a in args)
            or ("ms43diff" in args and "mcp" in args))


def _arg(args: List[str], *flags: str) -> str:
    for flag in flags:
        if flag in args and args.index(flag) + 1 < len(args):
            return args[args.index(flag) + 1]
    return ""


def describe(name: str, entry: Dict) -> Dict:
    """What an entry points at and whether those files still exist."""
    args = [str(a) for a in entry.get("args") or []]
    command = str(entry.get("command", ""))
    script = next((a for a in args if a.lower().endswith(".py")), "")
    info = {"name": name, "command": command, "xdf": _arg(args, "--xdf", "-x"),
            "bin": _arg(args, "--bin", "-b"), "lang": _arg(args, "--lang") or ""}
    problems = []
    if os.path.isabs(command) and not os.path.isfile(command):
        problems.append(t("the server program is missing: {path}", path=command))
    if script and not os.path.isfile(script):
        problems.append(t("the server program is missing: {path}", path=script))
    for key in ("xdf", "bin"):
        if info[key] and not os.path.isfile(info[key]):
            problems.append(t("file not found: {path}", path=info[key]))
    info["problems"] = problems
    return info


def entries() -> List[Dict]:
    """Our servers currently in the Claude Desktop config."""
    try:
        data = _read_config(config_path())
    except InstallError:
        return []
    servers = data.get("mcpServers")
    if not isinstance(servers, dict):
        return []
    return [describe(name, entry) for name, entry in servers.items() if is_ours(entry)]


CHECK_MESSAGES = [
    {"jsonrpc": "2.0", "id": 1, "method": "initialize",
     "params": {"protocolVersion": "2024-11-05", "clientInfo": {"name": "check", "version": "1"}}},
    {"jsonrpc": "2.0", "method": "notifications/initialized"},
    {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
    {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
     "params": {"name": "firmware_info", "arguments": {}}},
]


def summarize_check(answers: List[Dict]) -> Dict:
    """Turn the answers to CHECK_MESSAGES into a short report."""
    by_id = {a.get("id"): a for a in answers if isinstance(a, dict)}
    tools = len(((by_id.get(2) or {}).get("result") or {}).get("tools") or [])
    info = (by_id.get(3) or {}).get("result") or {}
    text = "".join(c.get("text", "") for c in info.get("content") or [])
    ok = bool(by_id.get(1, {}).get("result")) and tools > 0 and not info.get("isError")
    return {"ok": ok, "tools": tools, "info": text,
            "error": "" if ok else (text or t("The server did not answer as expected."))}


def check_entry(name: str, timeout: float = 30) -> Dict:
    """Start the server exactly as Claude Desktop would and ask it a few questions."""
    import subprocess

    data = _read_config(config_path())
    entry = (data.get("mcpServers") or {}).get(name)
    if not isinstance(entry, dict):
        raise InstallError(t("The \"{name}\" server is not connected.", name=name))
    stdin = "\n".join(json.dumps(m) for m in CHECK_MESSAGES) + "\n"
    try:
        proc = subprocess.run([entry.get("command", "")] + [str(a) for a in entry.get("args") or []],
                              input=stdin.encode("utf-8"), capture_output=True, timeout=timeout,
                              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.SubprocessError) as exc:
        return {"ok": False, "tools": 0, "info": "", "error": str(exc)}
    answers = []
    for line in proc.stdout.decode("utf-8", "replace").splitlines():
        try:
            answers.append(json.loads(line))
        except ValueError:
            pass
    result = summarize_check(answers)
    if not result["ok"] and proc.stderr:
        result["error"] += "\n" + proc.stderr.decode("utf-8", "replace")[-600:]
    return result

