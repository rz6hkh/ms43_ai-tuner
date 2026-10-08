# -*- coding: utf-8 -*-
"""
MCP tools for firmware edits (the "Edits" screen of the window).

The model proposes changes; they collect in a draft for the firmware its server
shows. The draft is checked at once (rounding, field limits, patch bytes,
software version) and the model sees exactly what would land. There is no tool
that writes a .bin: the user reviews the draft in the window (heat maps, byte
diff, risks) and presses "Create .bin" there. Risky changes (more advance,
higher limits, protections off) also need a typed confirmation by the user.
"""

from __future__ import annotations

import contextvars
from typing import Any, Dict, List, Optional

from . import edits, names
from .binfile import format_number
from .i18n import t

# Set by the HTTP server for each request: the window's workspace, which owns
# the drafts, the project patchlist and the window itself.
WORKSPACE: "contextvars.ContextVar[Optional[Any]]" = contextvars.ContextVar(
    "ms43diff_workspace", default=None)


def _context():
    from .mcpserver import _require_state

    fw = _require_state()
    ws = WORKSPACE.get()
    if ws is None:
        raise ValueError(t("Edits work only through the live server of the open window."))
    return fw, ws, ws.draft(fw.bin_path)


def _plan_lines(plan: edits.ChangePlan) -> List[str]:
    c = plan.change
    head = f"#{c.id} [{c.kind}] {c.target}"
    if not plan.ok:
        return [head + " — " + t("REFUSED: {text}", text=plan.error)]
    out = [head + " — " + t("why: {text}", text=c.reason)]
    if c.evidence.get("log"):
        out.append("  " + t("evidence log: {name}", name=c.evidence["log"]))
    if plan.item is not None and plan.cells:
        dec = max(plan.item.value_decimals, 2)
        units = names.unit(plan.item.value_units)
        changed = [cell for cell in plan.cells if cell.raw_new != cell.raw_old]
        out.append("  " + t("cells changed: {n} of {total}", n=len(changed), total=len(plan.cells)))
        for cell in changed[:40]:
            asked = "" if format_number(cell.asked, dec, 1) == format_number(cell.new, dec, 1) else \
                "  " + t("(asked {value})", value=format_number(cell.asked, dec, 1))
            out.append(f"    {edits.cell_label(cell)}: {format_number(cell.old, dec, 1)} -> "
                       f"{format_number(cell.new, dec, 1)} {units}{asked}".rstrip())
        if len(changed) > 40:
            out.append("    " + t("… and {n} more", n=len(changed) - 40))
    elif plan.writes:
        for off, old, new in plan.writes[:20]:
            out.append(f"    0x{off:05X}: {old.hex().upper()} -> {new.hex().upper()}")
    for flag in plan.red:
        out.append("  " + t("RISK (needs the user's typed confirmation): {text}", text=flag))
    for note in plan.notes:
        out.append("  * " + note)
    return out


def _summary(fw, ws, draft) -> str:
    plan = edits.plan_draft(fw.reader, draft, ws.patchlist())
    out = [t("Draft for {name}: {n} change(s).", name=fw.reader.bin.name, n=len(draft.changes))]
    for blocker in plan.blockers:
        out.append(t("BLOCKER: {text}", text=blocker))
    for p in plan.plans:
        out.extend(_plan_lines(p))
    changed = sum(1 for o, n in plan.writes.values() if o != n)
    out.append(t("Bytes that would change: {n}.", n=changed))
    if plan.needs_full_image:
        out.append(t("Contains patches: the user must flash the FULL 512 KB image."))
    out.append(t("Nothing is written yet. The user creates the new .bin in the window "
                 "(call edit_show to open the draft there)."))
    return "\n".join(out)


def tool_edit_propose(args: Dict) -> str:
    fw, ws, draft = _context()
    kind = args.get("kind") or ""
    target = args.get("target") or ""
    reason = args.get("reason") or ""
    evidence = None
    if args.get("evidence_log"):
        from .mcplogs import evidence_for

        evidence = evidence_for(args["evidence_log"])
    payload = {k: v for k, v in args.items()
               if k not in ("kind", "target", "reason", "evidence_log")}
    change = draft.add(kind, target, payload, reason, evidence=evidence)
    plan = edits.plan_draft(fw.reader, draft, ws.patchlist())
    mine = next(p for p in plan.plans if p.change.id == change.id)
    if not mine.ok:
        draft.remove(change.id)
        return t("Not added. {text}", text=mine.error)
    ws.notify()
    lines = [t("Added to the draft:")] + _plan_lines(mine)
    lines.append(t("Draft: {n} change(s); nothing is written until the user creates the .bin "
                   "in the window.", n=len(draft.changes)))
    return "\n".join(lines)


def tool_edit_list(args: Dict) -> str:
    fw, ws, draft = _context()
    return _summary(fw, ws, draft)


def tool_edit_remove(args: Dict) -> str:
    fw, ws, draft = _context()
    if args.get("all"):
        draft.clear()
        ws.notify()
        return t("The draft is cleared.")
    change_id = int(args.get("id") or 0)
    if not draft.remove(change_id):
        return t("No change #{n} in the draft.", n=change_id)
    ws.notify()
    return t("Change #{n} removed.", n=change_id)


def tool_edit_show(args: Dict) -> str:
    fw, ws, draft = _context()
    ws.show("edits")
    return t("The draft is open in the window (Edits screen). The user checks it there and "
             "creates the new .bin.")


_CELL = {"type": "object", "properties": {
    "row": {"type": "integer", "description": "row index from 0 (or give y)"},
    "col": {"type": "integer", "description": "column index from 0 (or give x)"},
    "y": {"type": "number", "description": "row axis value, must be a breakpoint"},
    "x": {"type": "number", "description": "column axis value, must be a breakpoint"},
    "value": {"type": "number", "description": "new physical value"}}, "required": ["value"]}

TOOLS: List[Dict[str, Any]] = [
    {
        "name": "edit_propose",
        "description": (
            "Propose a firmware change. It is added to a draft for the firmware this server "
            "shows and checked at once: the reply says what will really land after rounding to "
            "the raw step, field limits, and risks. Nothing is written: the user reviews the "
            "draft in the window and creates a NEW .bin there (name_vN.bin plus a change log). "
            "kind: 'value' (a constant: value), 'cells' (cells: [{row,col,value}] or {y,x,value} "
            "by axis breakpoints), 'region' (op add|mul|set, amount, row_from/row_to/col_from/"
            "col_to or y_from/y_to/x_from/x_to, inclusive; omitted bounds = whole axis), "
            "'patch' (target = patch title from the Patchlist XDF, enable true|false). "
            "Always give a reason. Read the current values first (get_param/read_map). When the "
            "change rests on a log, give evidence_log: an edit of a firmware other than the one "
            "the log was recorded on becomes a risk the user must confirm."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "kind": {"type": "string", "enum": list(edits.KINDS)},
                "target": {"type": "string", "description": "parameter name, or patch title"},
                "reason": {"type": "string", "description": "why — goes into the change log"},
                "value": {"type": "number"},
                "cells": {"type": "array", "items": _CELL},
                "op": {"type": "string", "enum": list(edits.REGION_OPS)},
                "amount": {"type": "number"},
                "row_from": {"type": "integer"}, "row_to": {"type": "integer"},
                "col_from": {"type": "integer"}, "col_to": {"type": "integer"},
                "y_from": {"type": "number"}, "y_to": {"type": "number"},
                "x_from": {"type": "number"}, "x_to": {"type": "number"},
                "enable": {"type": "boolean"},
                "evidence_log": {"type": "string",
                                 "description": "the project log this change rests on (log_list)"},
            },
            "required": ["kind", "target", "reason"],
        },
        "_fn": tool_edit_propose,
    },
    {
        "name": "edit_list",
        "description": "The current draft: every change with before -> after, refusals, risks, "
                       "the number of bytes and whether the full 512 KB image must be flashed.",
        "inputSchema": {"type": "object", "properties": {}},
        "_fn": tool_edit_list,
    },
    {
        "name": "edit_remove",
        "description": "Remove one change from the draft by id, or all of them (all: true).",
        "inputSchema": {"type": "object", "properties": {
            "id": {"type": "integer"}, "all": {"type": "boolean"}}},
        "_fn": tool_edit_remove,
    },
    {
        "name": "edit_show",
        "description": "Open the draft in the program window (Edits screen) for the user: heat "
                       "maps before/after, byte diff, risks and the button that creates the .bin.",
        "inputSchema": {"type": "object", "properties": {}},
        "_fn": tool_edit_show,
    },
]
