# -*- coding: utf-8 -*-
"""
The "AI assistant" mode: MCP servers for Claude Code and Claude Desktop.

Claude Code: live HTTP servers inside this process (mcphttp.py). Each server
has a name, the project firmware it shows (A, B or the other version), an
answer language and a fixed port, kept in the settings so the address Claude
Code was given stays valid. One bearer token, generated once, protects them.
Registration in Claude Code goes through its own CLI (`claude mcp add`); the
current registrations are read from ~/.claude.json without running anything.

Claude Desktop only takes stdio servers from its config file, so for it the
mode adds/removes config entries (mcpinstall.py) and can test an entry by
starting the server exactly as Claude Desktop would.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import shutil
import subprocess
from typing import Dict, List, Optional

from .. import i18n, mcphttp, mcpinstall
from ..i18n import t

FIRST_PORT = 8743
ROLES = ("bin_a", "bin_b", "bin2")
_NAME = re.compile(r"^[A-Za-z0-9_-]{1,40}$")


class AiError(Exception):
    """A problem to show to the user as is."""


class AiManager:
    def __init__(self, state) -> None:
        self.state = state                  # webui.server.State (project files)
        self.running: Dict[str, mcphttp.McpHttpServer] = {}
        settings = state.settings
        self.token = settings.get("mcp_token") or secrets.token_urlsafe(24)
        self.servers: List[Dict] = settings.get("ai_servers") or [
            {"name": "ms43", "role": "bin_b", "lang": i18n.get_lang(), "port": FIRST_PORT}]
        self._save()

    # ------------------------------------------------------------------
    def _save(self) -> None:
        self.state.settings["mcp_token"] = self.token
        self.state.settings["ai_servers"] = self.servers
        i18n.save_settings(mcp_token=self.token, ai_servers=self.servers)

    def _find(self, name: str) -> Dict:
        for server in self.servers:
            if server["name"] == name:
                return server
        raise AiError(t("No server called \"{name}\".", name=name))

    def _files(self, role: str):
        xdf = self.state.paths.get("xdf2" if role == "bin2" else "xdf", "")
        return xdf, self.state.paths.get(role, "")

    # ------------------------------------------------------------------
    def describe(self) -> Dict:
        code = claude_code_servers()
        servers = []
        for s in self.servers:
            xdf, binf = self._files(s["role"])
            live = self.running.get(s["name"])
            url = f"http://127.0.0.1:{s['port']}/mcp"
            registered = code.get(s["name"])
            servers.append({
                **s, "url": url, "running": live is not None,
                "requests": live.requests if live else 0,
                "xdf": os.path.basename(xdf), "bin": os.path.basename(binf),
                "ready": bool(xdf and binf),
                "command": code_command(s["name"], url, self.token),
                "registered": bool(registered),
                "registered_other": bool(registered) and registered.get("url") != url,
            })
        return {
            "servers": servers,
            "claude_cli": bool(find_claude()),
            "desktop": {
                "config": mcpinstall.config_path(),
                "entries": mcpinstall.entries(),
                "running": mcpinstall.claude_running(),
            },
        }

    def add(self) -> None:
        used = {s["name"] for s in self.servers}
        ports = {s["port"] for s in self.servers}
        name = "ms43" if "ms43" not in used else next(
            f"ms43_{i}" for i in range(2, 100) if f"ms43_{i}" not in used)
        port = next(p for p in range(FIRST_PORT, FIRST_PORT + 100) if p not in ports)
        self.servers.append({"name": name, "role": "bin_a", "lang": i18n.get_lang(), "port": port})
        self._save()

    def update(self, name: str, changes: Dict) -> None:
        server = self._find(name)
        if "name" in changes and changes["name"] != name:
            new = str(changes["name"]).strip()
            if not _NAME.match(new):
                raise AiError(t("A server name may use Latin letters, digits, _ and - only."))
            if any(s["name"] == new for s in self.servers):
                raise AiError(t("There is already a server called \"{name}\".", name=new))
            if name in self.running:
                raise AiError(t("Stop the server before renaming it."))
            server["name"] = new
        if changes.get("role") in ROLES:
            server["role"] = changes["role"]
        if changes.get("lang") in i18n.LANGS:
            server["lang"] = changes["lang"]
            live = self.running.get(server["name"])
            if live:
                live.lang = server["lang"]
        if "port" in changes:
            port = int(changes["port"])
            if not 1024 <= port <= 65535:
                raise AiError(t("The port must be between 1024 and 65535."))
            if server["name"] in self.running:
                raise AiError(t("Stop the server before changing its port."))
            server["port"] = port
        self._save()

    def remove(self, name: str) -> None:
        self.stop(name)
        self.servers = [s for s in self.servers if s["name"] != name]
        self._save()

    def start(self, name: str) -> None:
        server = self._find(name)
        if name in self.running:
            return
        role = server["role"]
        live = mcphttp.McpHttpServer(name, server["port"], self.token,
                                     lambda: self._files(role), server["lang"])
        try:
            live.start()
        except OSError as exc:
            raise AiError(t("Port {port} is busy ({error}). Choose another port.",
                            port=server["port"], error=exc)) from exc
        self.running[name] = live

    def stop(self, name: str) -> None:
        live = self.running.pop(name, None)
        if live:
            live.stop()

    def stop_all(self) -> None:
        for name in list(self.running):
            self.stop(name)

    def check(self, name: str) -> Dict:
        server = self._find(name)
        if name not in self.running:
            raise AiError(t("Start the server first."))
        url = f"http://127.0.0.1:{server['port']}/mcp"
        try:
            answers = mcphttp.call(url, self.token, mcpinstall.CHECK_MESSAGES)
        except Exception as exc:  # noqa: BLE001 - shown in the check result
            return {"ok": False, "tools": 0, "info": "", "error": str(exc)}
        return mcpinstall.summarize_check(answers)

    # ---- Claude Code registration --------------------------------------
    def code_register(self, name: str, register: bool) -> Dict:
        server = self._find(name)
        claude = find_claude()
        if not claude:
            raise AiError(t("The claude command was not found. Install Claude Code or copy "
                            "the command and run it in its terminal."))
        url = f"http://127.0.0.1:{server['port']}/mcp"
        # replacing an entry needs a remove first; a missing one is not an error
        _run([claude, "mcp", "remove", "--scope", "user", name])
        if not register:
            return {"ok": True}
        result = _run([claude, "mcp", "add", "--transport", "http", "--scope", "user", name, url,
                       "--header", f"Authorization: Bearer {self.token}"])
        if result.returncode != 0:
            raise AiError(t("claude mcp add failed: {error}",
                            error=(result.stderr or result.stdout).strip()[-500:]))
        return {"ok": True}

    # ---- Claude Desktop -------------------------------------------------
    def desktop_install(self, name: str, role: str, lang: str) -> str:
        if not _NAME.match(name or ""):
            raise AiError(t("A server name may use Latin letters, digits, _ and - only."))
        xdf, binf = self._files(role if role in ROLES else "bin_b")
        if not (xdf and binf):
            raise AiError(t("Choose the XDF and the firmware in the project first."))
        info = mcpinstall.install(xdf, binf, name=name, lang=lang)
        return mcpinstall.install_message(info)

    def desktop_remove(self, name: str) -> str:
        return mcpinstall.uninstall_message(mcpinstall.uninstall(name))


# ---------------------------------------------------------------------------
# Claude Code helpers
# ---------------------------------------------------------------------------

def find_claude() -> Optional[str]:
    return shutil.which("claude")


def _run(args: List[str]) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, text=True, timeout=60,
                          creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def code_command(name: str, url: str, token: str) -> str:
    return (f'claude mcp add --transport http --scope user {name} {url} '
            f'--header "Authorization: Bearer {token}"')


def claude_code_servers() -> Dict[str, Dict]:
    """User-scope MCP servers registered in Claude Code (read from ~/.claude.json)."""
    path = os.path.join(os.path.expanduser("~"), ".claude.json")
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {}
    servers = data.get("mcpServers") if isinstance(data, dict) else None
    return {k: v for k, v in servers.items() if isinstance(v, dict)} if isinstance(servers, dict) else {}
