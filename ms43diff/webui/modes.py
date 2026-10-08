# -*- coding: utf-8 -*-
"""
Data for the window modes other than "Compare A and B": Browse, Different
versions (compare + port plan), Patches, Edits and Reference.

Every function takes the server State and a request body and returns a JSON-
ready dict. The heavy lifting is done by the same modules the CLI uses.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List

from .. import names, report
from ..binfile import BinFile, format_number
from ..compare import PATCH_APPLIED, check_patches
from ..crossdiff import build_port_plan, cross_compare
from ..i18n import t
from ..xdf import OUT_TEXT
from .dialogs import DIALOGS


class ModeError(Exception):
    """A problem to show to the user as is."""


def _kind(item) -> str:
    return t("Constant") if item.cell_count == 1 else t("Map {shape}", shape=item.shape_str)


def _role(body: Dict) -> str:
    role = body.get("role") or "bin_a"
    return role if role in ("bin_a", "bin_b", "bin2") else "bin_a"


# ---------------------------------------------------------------------------
# Browse
# ---------------------------------------------------------------------------

def browse(state, body: Dict) -> Dict[str, Any]:
    from ..cli import _compile, _matches

    reader = state.reader(_role(body))
    xdf = reader.xdf
    counts: Dict[str, int] = {}
    for item in xdf.readable_items():
        for name in xdf.category_names(item):
            counts[name] = counts.get(name, 0) + 1
    categories = [{"key": k, "name": names.category(k), "count": counts[k]}
                  for k in sorted(counts, key=lambda n: (-counts[n], n))]

    query = (body.get("query") or "").strip()
    category = body.get("category") or ""
    pattern = _compile(query) if query else None
    limit = 400
    items, total = [], 0
    for item in xdf.readable_items():
        if category and category not in xdf.category_names(item):
            continue
        if pattern and not _matches(item, xdf, pattern, None):
            continue
        total += 1
        if len(items) >= limit:
            continue
        info = names.explain(item.title, item.description)
        items.append({
            "title": item.title, "name": info["name"], "kind": _kind(item),
            "value": reader.summary(item) or "—", "units": names.unit(item.value_units),
            "has_map": item.cell_count > 1 and item.value_output_type != OUT_TEXT,
            "address": f"0x{item.address:X}" if item.address is not None else "",
        })
    return {"categories": categories, "items": items, "total": total, "limit": limit,
            "file": reader.bin.name, "xdf": f"{xdf.title} v{xdf.file_version}",
            "warning": reader.version_warning() or ""}


# ---------------------------------------------------------------------------
# Different versions: compare and port plan
# ---------------------------------------------------------------------------

def _need(state, *roles: str) -> None:
    labels = {"xdf": t("XDF definition"), "bin_a": t("Firmware A"),
              "bin_b": t("Firmware B"), "xdf2": t("XDF of the other version"),
              "bin2": t("Firmware of the other version"), "patchlist": t("Patchlist XDF")}
    missing = [labels[r] for r in roles if not state.paths.get(r)]
    if missing:
        raise ModeError(t("Choose in the project: {files}.", files=", ".join(missing)))


def cross(state, body: Dict) -> Dict[str, Any]:
    role = "bin_a" if body.get("role") == "bin_a" else "bin_b"
    _need(state, "xdf", role, "xdf2", "bin2")
    result = cross_compare(state.xdf(state.paths["xdf"]), BinFile(state.paths[role]),
                           state.xdf(state.paths["xdf2"]), BinFile(state.paths["bin2"]))
    groups = [("diff", t("Different"), result.different), ("only_a", t("Only in A"), result.only_a),
              ("only_b", t("Only in B"), result.only_b), ("problem", t("Problems"), result.problems)]
    out_groups = []
    for key, title, rows in groups:
        items = []
        for row in rows:
            item = row.item
            info = names.explain(row.title, item.description if item else "")
            items.append({"title": row.title, "name": info["name"], "status": row.status_label,
                          "summary": row.summary(),
                          "units": names.unit(item.value_units) if item else "",
                          "notes": row.notes, "side": "a" if row.item_a is not None else "b"})
        if items:
            out_groups.append({"key": key, "name": title, "items": items})
    state.cross = result
    return {"a": result.bin_a.name, "b": result.bin_b.name,
            "xdf_a": result.xdf_a.title, "xdf_b": result.xdf_b.title,
            "fw_a": result.reader_a.firmware_id() or "?", "fw_b": result.reader_b.firmware_id() or "?",
            "stats": {"different": len(result.different), "same": result.identical,
                      "only_a": len(result.only_a), "only_b": len(result.only_b)},
            "groups": out_groups}


def port(state, body: Dict) -> Dict[str, Any]:
    _need(state, "xdf", "bin_a", "bin_b", "xdf2", "bin2")
    plan = build_port_plan(state.xdf(state.paths["xdf"]), BinFile(state.paths["bin_a"]),
                           BinFile(state.paths["bin_b"]), state.xdf(state.paths["xdf2"]),
                           BinFile(state.paths["bin2"]))
    groups = [("safe_bytes", t("Safe — can be ported one-to-one"), plan.safe_bytes),
              ("safe_name", t("Safe by name — port the physical value by hand"), plan.safe_name),
              ("warned", t("With a warning — sort it out by hand"), plan.warned)]
    out_groups = []
    for key, title, entries in groups:
        items = []
        for entry in entries:
            item = entry.item_dst or entry.item_src
            info = names.explain(entry.title, item.description if item else "")
            items.append({
                "title": entry.title, "name": info["name"], "status": entry.status_label,
                "dst": entry.dst_title if entry.dst_title != entry.title else "",
                "summary": entry.summary(), "units": names.unit(item.value_units) if item else "",
                "bits": entry.match_bits if entry.safe else entry.warn_bits,
                "candidates": [c for c, _ in entry.candidates[:5]],
            })
        if items:
            out_groups.append({"key": key, "name": title, "items": items})
    state.port = plan
    return {"stock": plan.bin_stock.name, "tuned": plan.bin_tuned.name,
            "target": plan.bin_target.name, "xdf_src": plan.xdf_src.title,
            "xdf_dst": plan.xdf_dst.title,
            "stats": {"changed": len(plan.entries), "safe_bytes": len(plan.safe_bytes),
                      "safe_name": len(plan.safe_name), "warned": len(plan.warned)},
            "groups": out_groups}


# ---------------------------------------------------------------------------
# Patches
# ---------------------------------------------------------------------------

def patches(state, body: Dict) -> Dict[str, Any]:
    role = _role(body)
    _need(state, "patchlist", role)
    patchlist = state.xdf(state.paths["patchlist"])
    if not patchlist.patches:
        raise ModeError(t("This XDF has no <XDFPATCH> entries. A patchlist file is needed, "
                          "not a regular definition."))
    statuses = check_patches(patchlist, BinFile(state.paths[role]))
    groups: Dict[str, List] = {}
    for status in statuses:
        cat_names = ([patchlist.category_name(c) for c in status.patch.categories]
                     or [t("<no category>")])
        cat = ", ".join(names.category(n) for n in cat_names)
        groups.setdefault(cat, []).append({
            "title": status.patch.title, "state": status.state, "label": status.label,
            "desc": names.description(status.patch.description),
            "desc_orig": status.patch.description if names.description(
                status.patch.description) != status.patch.description else "",
            "details": status.details[:5],
        })
    applied = sum(1 for s in statuses if s.state == PATCH_APPLIED)
    return {"file": os.path.basename(state.paths[role]), "patchlist": patchlist.title,
            "stats": {"total": len(statuses), "applied": applied},
            "groups": [{"name": k, "items": groups[k]} for k in sorted(groups)]}


# ---------------------------------------------------------------------------
# Edits (the draft the AI fills through MCP; the user creates the .bin here)
# ---------------------------------------------------------------------------

def _edits_context(state, body: Dict):
    from .. import edits

    role = _role(body)
    _need(state, "xdf2" if role == "bin2" else "xdf", role)
    reader = state.reader(role)
    draft = state.draft(reader.bin.path)
    return edits, role, reader, draft


def edits_state(state, body: Dict) -> Dict[str, Any]:
    edits, role, reader, draft = _edits_context(state, body)
    plan = edits.plan_draft(reader, draft, state.patchlist())
    changes = []
    for p in plan.plans:
        c, item = p.change, p.item
        entry: Dict[str, Any] = {
            "id": c.id, "kind": c.kind, "target": c.target, "reason": c.reason,
            "evidence": c.evidence.get("log", ""),
            "source": c.source, "created": c.created, "ok": p.ok, "error": p.error,
            "red": p.red, "notes": p.notes,
            "writes": [{"off": f"0x{off:05X}", "old": old.hex().upper(), "new": new.hex().upper()}
                       for off, old, new in p.writes[:64]],
            "more_writes": max(0, len(p.writes) - 64),
        }
        if item is not None:
            dec = max(item.value_decimals, 2)
            info = names.explain(item.title, item.description)
            changed = [cell for cell in p.cells if cell.raw_new != cell.raw_old]
            entry.update(name=info["name"], units=names.unit(item.value_units),
                         has_map=item.cell_count > 1, shape=_kind(item),
                         changed=len(changed), total=len(p.cells),
                         cells=[{"r": cell.row, "c": cell.col, "at": edits.cell_label(cell),
                                 "old": format_number(cell.old, dec, 1),
                                 "new": format_number(cell.new, dec, 1),
                                 "asked": format_number(cell.asked, dec, 1)}
                                for cell in changed[:12]])
        changes.append(entry)
    runs = plan.byte_runs()
    return {
        "role": role, "file": reader.bin.name, "xdf": reader.xdf.title,
        "fw": reader.firmware_id() or "?", "size_kb": reader.bin.size_kb,
        "changes": changes, "blockers": plan.blockers, "ok": plan.ok, "red": plan.red,
        "full_image": plan.needs_full_image,
        "bytes": sum(1 for o, n in plan.writes.values() if o != n),
        "runs": [{"off": f"0x{off:05X}", "len": len(old), "old": old[:16].hex(" ").upper(),
                  "new": new[:16].hex(" ").upper()} for off, old, new in runs[:300]],
        "more_runs": max(0, len(runs) - 300),
        "next_file": os.path.basename(edits.next_version_path(reader.bin.path)),
        "confirm_word": t("CONFIRM"),
    }


def edits_remove(state, body: Dict) -> Dict[str, Any]:
    edits, role, reader, draft = _edits_context(state, body)
    if body.get("all"):
        draft.clear()
    else:
        draft.remove(int(body.get("id") or 0))
    state.notify()
    return edits_state(state, body)


def edits_create(state, body: Dict) -> Dict[str, Any]:
    edits, role, reader, draft = _edits_context(state, body)
    typed = (body.get("confirm") or "").strip().upper()
    try:
        result = edits.write_new_bin(reader, draft, state.patchlist(),
                                     confirm_red=typed in ("CONFIRM", t("CONFIRM").upper()))
    except edits.EditError as exc:
        raise ModeError(str(exc)) from exc
    except OSError as exc:
        raise ModeError(t("Could not write the file: {error}", error=exc)) from exc
    state.created.append(result["path"])
    draft.clear()
    state.notify()
    return {"path": result["path"], "notes": result["notes"], "bytes": result["bytes"],
            "name": os.path.basename(result["path"])}


def edits_use(state, body: Dict) -> Dict[str, Any]:
    """Put a .bin created in this session into the project (as A, B or other)."""
    path = body.get("path") or ""
    if path not in state.created:
        raise ModeError(t("Only a file created here can be put into the project this way."))
    state.set_path(_role(body), path)
    state.notify()
    return {"ok": True}


# ---------------------------------------------------------------------------
# Reference (MS4X Wiki)
# ---------------------------------------------------------------------------

def _section_list(state, sections) -> List[Dict[str, Any]]:
    state.wiki_sections = list(sections)
    return [{"id": i, "page": s.page, "heading": s.heading, "caution": bool(s.caution_lines)}
            for i, s in enumerate(state.wiki_sections)]


def wiki(state, body: Dict) -> Dict[str, Any]:
    from .. import wikicache

    job = getattr(state, "wiki_job", None)
    running = _job_view(job) if job and not job.get("done") else None
    if not wikicache.available():
        return {"available": False, "sections": [], "hint": wikicache.offline_hint(), "job": running}
    info = wikicache.meta()
    query = (body.get("query") or "").strip()
    if body.get("cautions"):
        sections = wikicache.cautions()
    elif query:
        sections = wikicache.search(query, limit=200)
    else:
        sections = [s for page in wikicache.load() for s in page.sections]
    return {"available": True, "fetched": info.get("fetched", "?"),
            "pages": len(wikicache.load()), "expected": len(wikicache.expected_pages()),
            "missing": wikicache.missing_pages(), "params": len(wikicache.index_parameters()),
            "extra": [n for n in info.get("extra", []) if n not in wikicache.DEFAULT_PAGES],
            "skipped": list(info.get("skipped", [])),
            "source": info.get("source", ""), "sections": _section_list(state, sections),
            "job": running}


def wiki_section(state, body: Dict) -> Dict[str, Any]:
    from .. import wikitrans

    sections = getattr(state, "wiki_sections", [])
    idx = int(body.get("id", -1))
    if not 0 <= idx < len(sections):
        raise ModeError(t("Nothing found."))
    section = sections[idx]
    cautions = set(section.caution_lines)
    lines = []
    for line in section.text.split("\n"):
        line = line.strip()
        if line:
            lines.append({"text": wikitrans.translate_line(line), "orig": line,
                          "warn": line in cautions})
    return {"page": section.page, "heading": section.heading, "url": section.url,
            "lines": lines, "translated": any(l["text"] != l["orig"] for l in lines)}


def wiki_download(state, body: Dict) -> Dict[str, Any]:
    """Start the update from the site in the background; wiki_progress reports it."""
    import threading

    from .. import wikicache

    job = getattr(state, "wiki_job", None)
    if job and not job.get("done"):
        return {**wiki(state, {}), "job": _job_view(job)}
    job = {"done": False, "stage": "pages", "i": 0, "n": 0, "name": "", "result": None, "error": ""}
    state.wiki_job = job

    def progress(i, n, name, stage="pages"):
        job.update(stage=stage, i=i, n=n, name=name)

    def run():
        try:
            job["result"] = wikicache.download(timeout=15, progress=progress)
        except Exception as exc:  # noqa: BLE001 - shown to the owner, the reference is untouched
            job["error"] = str(exc)
        job["done"] = True

    threading.Thread(target=run, daemon=True).start()
    return {**wiki(state, {}), "job": _job_view(job)}


def _job_view(job: Dict) -> Dict[str, Any]:
    return {k: job[k] for k in ("done", "stage", "i", "n", "name", "error")}


def wiki_progress(state, body: Dict) -> Dict[str, Any]:
    from .. import wikicache

    job = getattr(state, "wiki_job", None)
    if not job:
        return {"job": None}
    if not job["done"]:
        return {"job": _job_view(job)}
    state.wiki_job = None
    out = wiki(state, {})
    out["job"] = _job_view(job)
    result = job["result"]
    if result is None:
        out["message"] = t("The update failed: {error}", error=job["error"])
        out["errors"] = []
        return out
    out["downloaded"] = result["pages"]
    out["written"] = result["written"]
    out["errors"] = [f"{n}: {e[:80]}" for n, e in result["errors"]]
    if not result["written"]:
        out["message"] = t("Nothing was downloaded; the reference was not changed.") + "\n" + \
            wikicache.offline_hint()
        return out
    lines = [t("Pages downloaded: {n}", n=result["pages"])]
    if result["added"]:
        lines.append(t("New MS43 pages found on the site and added: {list}",
                       list=", ".join(result["added"])))
    if result["skipped"]:
        lines.append(t("New pages not about the MS43, skipped: {n}", n=len(result["skipped"])))
    if result["listing_error"]:
        lines.append(t("Could not read the list of pages on the site: {error}",
                       error=result["listing_error"][:120]))
    if result["missing"]:
        lines.append(t("Still missing: {list}", list=", ".join(result["missing"])))
    out["message"] = "\n".join(lines)
    return out


def wiki_add(state, body: Dict) -> Dict[str, Any]:
    from .. import wikicache

    name = str(body.get("page") or "")
    if name not in wikicache.meta().get("skipped", []):
        raise ModeError(t("Nothing found."))
    try:
        result = wikicache.add_pages([name], timeout=15)
    except (OSError, ValueError) as exc:
        raise ModeError(str(exc)) from exc
    out = wiki(state, {})
    out["message"] = (t("Added: {list}", list=", ".join(result["added"])) if result["added"] else
                      t("Nothing was downloaded; the reference was not changed.") + "\n" +
                      wikicache.offline_hint())
    return out


def wiki_import(state, body: Dict) -> Dict[str, Any]:
    from .. import wikicache

    path = DIALOGS.open_file(t("MS4X Wiki reference file"),
                             [(t("MS4X Wiki reference"), "*.json"), (t("All files"), "*.*")])
    if not path:
        return {**wiki(state, {}), "cancelled": True}
    try:
        result = wikicache.import_file(path)
    except (OSError, ValueError) as exc:
        raise ModeError(str(exc)) from exc
    out = wiki(state, {})
    out["message"] = t("Reference imported: {n} pages → {path}", n=result["pages"],
                       path=result["path"])
    return out


def wiki_export(state, body: Dict) -> Dict[str, Any]:
    from .. import wikicache

    path = DIALOGS.save_file(t("Save as"), [(t("MS4X Wiki reference"), "*.json")],
                             "ms4x_wiki.json")
    if not path:
        return {**wiki(state, {}), "cancelled": True}
    try:
        n = wikicache.export_file(path)
    except (OSError, ValueError) as exc:
        raise ModeError(str(exc)) from exc
    out = wiki(state, {})
    out["message"] = t("Saved: {n} pages → {path}. Rights belong to the MS4X Wiki authors: "
                       "for your own computers only.", n=n, path=path)
    return out



# ---------------------------------------------------------------------------
# Logs (TunerPro CSV in the project, bound to the firmware that was in the car)
# ---------------------------------------------------------------------------

def _logs_dir(state) -> str:
    folder = state.logs_dir()
    if not folder:
        raise ModeError(t("Create the project first (AI assistant screen): logs are kept in its "
                          "logs/ folder, where Claude Code reads them."))
    return folder


def _log_entry(path: str) -> Dict[str, Any]:
    from .. import tplog

    binding = tplog.read_binding(path)
    entry: Dict[str, Any] = {"name": os.path.basename(path),
                             "firmware": os.path.basename(binding["bin"]) if binding else "",
                             "problem": tplog.binding_status(binding),
                             "old": tplog.redecode_status(path) == "old"}
    try:
        log = tplog.load(path)
        q = tplog.quality(log)
        events = tplog.knock_events(log)
        entry.update(rows=q["rows"], duration=round(q["duration"], 1), rate=round(q["rate"], 1),
                     events=len(events))
    except (OSError, tplog.LogError) as exc:
        entry["error"] = str(exc)
    return entry


def logs_state(state, body: Dict) -> Dict[str, Any]:
    from .. import tplog

    folder = state.logs_dir()
    firmwares = []
    for role, label in (("bin_a", t("Firmware A")), ("bin_b", t("Firmware B")),
                        ("bin2", t("Firmware of the other version"))):
        xdf_role = "xdf2" if role == "bin2" else "xdf"
        if state.paths.get(role) and state.paths.get(xdf_role):
            firmwares.append({"role": role, "label": label,
                              "name": os.path.basename(state.paths[role])})
    view, state.log_view = state.log_view, {}
    return {"project": bool(folder), "folder": folder,
            "logs": [_log_entry(p) for p in tplog.list_logs(folder)],
            "firmwares": firmwares, "view": view, "filters": list(tplog.FILTERS),
            "adx": os.path.basename(state.paths.get("adx", "") or "")}


def _firmware_for(state, role: str):
    """(firmware, XDF) the owner says was in the car; None when a dialog was cancelled."""
    if role in ("bin_a", "bin_b", "bin2"):
        return state.paths.get(role, ""), state.paths.get("xdf2" if role == "bin2" else "xdf", "")
    if role == "file":
        bin_path = DIALOGS.open_file(t("The firmware that was in the car"),
                                     [(t("Firmware"), "*.bin"), (t("All files"), "*.*")])
        if not bin_path:
            return None
        xdf_path = DIALOGS.open_file(t("The XDF for that firmware"),
                                     [(t("XDF definition"), "*.xdf"), (t("All files"), "*.*")])
        if not xdf_path:
            return None
        return bin_path, xdf_path
    raise ModeError(t("Choose the firmware that was in the car."))


def _pick_adx(state) -> str:
    path = DIALOGS.open_file(t("The ADX the .xdl logs are recorded with"),
                             [(t("TunerPro logger definition"), "*.adx"), (t("All files"), "*.*")],
                             state.paths.get("adx", ""))
    if path:
        state.set_path("adx", os.path.normpath(path))
    return path


def logs_redecode(state, body: Dict) -> Dict[str, Any]:
    """Decode logs again from their raw files (after a decoder fix or with another ADX)."""
    from .. import tplog

    folder = _logs_dir(state)
    if body.get("all"):
        paths = [p for p in tplog.list_logs(folder) if tplog.redecode_status(p) == "old"]
    else:
        paths = [_log_path(state, body)]
    done, failed = [], []
    for path in paths:
        try:
            tplog.redecode(path)
            done.append(os.path.basename(path))
        except tplog.LogError as exc:
            failed.append(f"{os.path.basename(path)}: {exc}")
    out = logs_state(state, {})
    out["message"] = t("Decoded again: {n}", n=len(done)) + ("\n" + "\n".join(failed) if failed else "")
    return out


def logs_pick_adx(state, body: Dict) -> Dict[str, Any]:
    _pick_adx(state)
    return logs_state(state, {})


def logs_add(state, body: Dict) -> Dict[str, Any]:
    from .. import tplog

    folder = _logs_dir(state)
    firmware = _firmware_for(state, body.get("role") or "")
    if firmware is None:
        return {**logs_state(state, {}), "cancelled": True}
    bin_path, xdf_path = firmware
    src = DIALOGS.open_file(t("TunerPro log"), [(t("TunerPro log"), "*.csv *.xdl *.jsonl"),
                                                 (t("All files"), "*.*")])
    if not src:
        return {**logs_state(state, {}), "cancelled": True}
    adx_path = ""
    if src.lower().endswith(".jsonl"):
        adx_path = state.paths.get("adx", "")      # the standard 0B 03 ADX is tried as well
    if src.lower().endswith(".xdl"):
        adx_path = state.paths.get("adx", "")
        if not adx_path or not os.path.isfile(adx_path):
            adx_path = _pick_adx(state)
            if not adx_path:
                return {**logs_state(state, {}), "cancelled": True}
    try:
        dest = tplog.add_log(src, folder, bin_path, xdf_path, str(body.get("note") or "")[:500],
                             adx_path)
    except (OSError, tplog.LogError) as exc:
        raise ModeError(str(exc)) from exc
    out = logs_state(state, {})
    out["added"] = os.path.basename(dest)
    return out


def logs_note(state, body: Dict) -> Dict[str, Any]:
    """Save the conditions note of a log (where, fuel, air, complaint, what changed, text)."""
    from .. import tplog

    path = tplog.resolve(state.logs_dir(), str(body.get("log") or ""))
    try:
        c = tplog.set_conditions(path, body.get("conditions") or {})
    except (OSError, tplog.LogError) as exc:
        raise ModeError(str(exc)) from exc
    state.notify()
    return {"conditions": c, "missing": tplog.missing_conditions({"conditions": c, "note": c["note"]})}


def _analysis_files(state, log_name: str) -> List[Dict[str, str]]:
    folder = os.path.dirname(state.logs_dir())
    adir = os.path.join(folder, "analysis")
    stem = os.path.splitext(log_name)[0].lower()
    if not os.path.isdir(adir):
        return []
    out = []
    for name in sorted(os.listdir(adir)):
        low = name.lower()
        if stem in low and low.endswith((".png", ".md", ".txt")):
            out.append({"name": name, "kind": "image" if low.endswith(".png") else "text"})
    return out


def _map_rank(title: str) -> int:
    """Main part-load ignition map first, then other ignition maps, then the rest."""
    low = title.lower()
    if not low.startswith("ip_iga"):
        return 4
    if "ron98_pl" in low or "ron_98_pl" in low:
        return 0
    if "_pl" in low and "91" not in low:
        return 1
    if "_pl" in low:
        return 2
    return 3


def _map_choices(reader) -> List[Dict[str, str]]:
    from .. import tplog

    out = []
    for item in reader.xdf.readable_items(include_axes=False):
        if item.cell_count <= 1 or not any(tplog.axis_tokens(item.title)):
            continue
        out.append({"title": item.title, "name": names.name(item.title)})
    out.sort(key=lambda m: (_map_rank(m["title"]), m["title"]))
    return out


def logs_view(state, body: Dict) -> Dict[str, Any]:
    import math

    from .. import tplog

    path = _log_path(state, body)
    log = tplog.load(path)
    binding = tplog.read_binding(path)
    problem = tplog.binding_status(binding)
    q = tplog.quality(log)
    events = []
    for ev in tplog.knock_events(log):
        events.append({
            "start": ev["start"], "end": ev["end"], "rows": ev["rows"], "det": ev["detections"],
            **{k: [round(ev[k][0], 1), round(ev[k][1], 1)] for k in
               ("rpm", "load_ign", "throttle", "iat", "coolant") if k in ev},
            "cyl": {c: v for c, v in sorted(ev["cylinders"].items())}})
    _, stats = tplog.row_filter(log, tplog.FILTERS)
    maps: List[Dict[str, str]] = []
    if not problem:
        from ..binfile import Reader

        maps = _map_choices(Reader(state.xdf(binding["xdf"]), BinFile(binding["bin"])))
    numeric = [c for c in log.columns if c != tplog.TIME]
    knocked = [c for c in tplog.knock_columns(log)
               if any(v < 0 for v in log.data[c] if not math.isnan(v))]
    default_chart = [c for c in (tplog.RPM, tplog.LOAD_IGN, tplog.THROTTLE[0], tplog.THROTTLE[1])
                     if log.has(c)][:3] + (knocked or tplog.knock_columns(log)[:1])
    return {
        "name": log.name, "title": log.title, "old": tplog.redecode_status(path) == "old",
        "firmware": os.path.basename(binding["bin"]) if binding else "",
        "firmware_path": binding["bin"] if binding else "", "added": (binding or {}).get("added", ""),
        "note": (binding or {}).get("note", ""), "problem": problem,
        "conditions": tplog.conditions(binding) if binding else None,
        "missing": tplog.missing_conditions(binding) if binding else [],
        "rows": q["rows"], "duration": round(q["duration"], 2), "rate": round(q["rate"], 1),
        "gaps": [[round(a, 2), round(b, 2)] for a, b in q["gaps"][:50]], "stuck": q["stuck"],
        "constant": q["constant"], "empty": q["empty"],
        "skipped": q["skipped"], "events": events, "flags": tplog.flag_summary(log),
        "filter_stats": stats, "channels": numeric,
        "units": {c: log.units.get(c, "") for c in numeric},
        "throttle_units": log.units.get(tplog.THROTTLE[0], "") if log.has(tplog.THROTTLE[0]) else "",
        "chart": default_chart, "maps": maps, "files": _analysis_files(state, log.name),
        "trims": tplog.trim_channels(log),
        "others": [os.path.basename(p) for p in tplog.list_logs(state.logs_dir())
                   if os.path.basename(p) != log.name],
        "t0": log.time[0] if log.n else 0, "t1": log.time[-1] if log.n else 0,
    }


def _log_path(state, body: Dict) -> str:
    from .. import tplog

    try:
        return tplog.resolve(_logs_dir(state), body.get("log", ""))
    except tplog.LogError as exc:
        raise ModeError(str(exc)) from exc


def logs_series(state, body: Dict) -> Dict[str, Any]:
    """Channels for the chart, thinned to about `points` min/max pairs per lane."""
    import math

    from .. import tplog

    log = tplog.load(_log_path(state, body))
    tm = log.time
    t0 = float(body.get("from", tm[0] if log.n else 0))
    t1 = float(body.get("to", tm[-1] if log.n else 0))
    idx = [i for i in range(log.n) if t0 <= tm[i] <= t1]
    points = max(100, min(4000, int(body.get("points") or 1200)))
    step = max(1, len(idx) // points)
    lanes = []
    for name in body.get("channels") or []:
        col = log.col(name)
        if col is None:
            continue
        xs, ys = [], []
        for k in range(0, len(idx), step):
            chunk = [i for i in idx[k:k + step] if not math.isnan(col[i])]
            if not chunk:
                continue
            lo = min(chunk, key=lambda i: col[i])
            hi = max(chunk, key=lambda i: col[i])
            for i in sorted({lo, hi}):
                xs.append(round(tm[i], 3))
                ys.append(col[i])
        lanes.append({"name": name, "units": log.units.get(name, ""), "t": xs, "v": ys})
    _, onset = tplog.knock_rows(log)
    marks = [round(tm[i], 3) for i in idx if onset[i]]
    return {"from": t0, "to": t1, "lanes": lanes, "knock": marks}


def _hit_json(hit: Dict[str, Any]) -> Dict[str, Any]:
    from .. import tplog

    out = {"n": hit["n"], "k": hit["knock"], "r": hit["retard"], "w": hit["worst"],
           "cyl": hit["cyl"], "t": hit["t"]}
    if hit.get("vn"):
        out.update(m=tplog.fmt(hit["mean"]), lo=tplog.fmt(hit["vmin"]), hi=tplog.fmt(hit["vmax"]))
    return out


def _compare_status(a: Dict[str, Any], b: Dict[str, Any]) -> str:
    if not (a["n"] and b["n"]):
        return "one" if (a["n"] or b["n"]) else ""
    if a["knock"] and not b["knock"]:
        return "fixed"
    if b["knock"] and not a["knock"]:
        return "new"
    if a["knock"] and b["knock"]:
        return "still"
    return "ok"


def logs_map(state, body: Dict) -> Dict[str, Any]:
    """A log over a map; with value_channel the cells show that channel's mean; with
    compare (a second log) the cells show before -> after."""
    import math

    from .. import heatmap, tplog
    from ..mcplogs import DEFAULT_FILTERS, compare, overlay

    path = _log_path(state, body)
    filters = body.get("filters")
    if filters is None:
        filters = list(DEFAULT_FILTERS)
    filters = [f for f in filters if f in tplog.FILTERS]
    value = body.get("value_channel", "")
    other = body.get("compare", "")
    try:
        if other:
            pair = compare(state, _log_path(state, {"log": other}), path, body.get("map", ""),
                           body.get("y_channel", ""), body.get("x_channel", ""), filters, value)
            before, ov = pair["before"], pair["after"]
        else:
            before, ov = None, overlay(state, path, body.get("map", ""), body.get("y_channel", ""),
                                       body.get("x_channel", ""), filters, value)
    except (OSError, tplog.LogError) as exc:
        raise ModeError(str(exc)) from exc
    item, matrix = ov["item"], ov["matrix"]
    dec, otype = item.value_decimals, item.value_output_type
    low, high = heatmap.value_range(matrix)
    means = [h["mean"] for line in ov["grid"] for h in line if h.get("vn")]
    scale = max([abs(m) for m in means] + [1e-9]) if value else 0
    rows = []
    for r, line in enumerate(ov["grid"]):
        row = []
        for c, hit in enumerate(line):
            if value and hit.get("vn") and not math.isnan(hit["mean"]):
                rgb = heatmap.delta_color(hit["mean"], scale)
            else:
                rgb = heatmap.value_color(matrix[r][c], low, high)
            cell = {"v": format_number(matrix[r][c], dec, otype), "bg": heatmap.hex_color(rgb),
                    "fg": heatmap.hex_color(heatmap.text_color(rgb)), **_hit_json(hit)}
            if before is not None:
                was = before["matrix"][r][c]
                if was != matrix[r][c]:
                    cell["was"] = format_number(was, dec, otype)
                cell["a"] = _hit_json(before["grid"][r][c])
                cell["st"] = _compare_status(before["grid"][r][c], hit)
            row.append(cell)
        rows.append(row)
    y_name, x_name = names.axis_names(item.title)
    out = {
        "map": item.title, "name": names.name(item.title), "units": names.unit(item.value_units),
        "y": [tplog.fmt(v) for v in ov["y_breaks"]] or [""],
        "x": [tplog.fmt(v) for v in ov["x_breaks"]] or [""],
        "y_name": y_name, "x_name": x_name,
        "y_channel": ov["y_channel"], "x_channel": ov["x_channel"], "rows": rows,
        "used": ov["rows_used"], "outside": ov["outside"], "filters": ov["filters"],
        "filter_stats": ov["filter_stats"], "firmware": os.path.basename(ov["binding"]["bin"]),
        "value_channel": ov["value_channel"], "value_units": ov["value_units"],
    }
    if before is not None:
        out.update(compare=os.path.basename(before["log"].path),
                   compare_firmware=os.path.basename(before["binding"]["bin"]),
                   compare_used=before["rows_used"])
    return out


def logs_file(state, body: Dict) -> Dict[str, Any]:
    """An analysis file (chart or notes) Claude wrote for a log."""
    import base64

    folder = os.path.join(os.path.dirname(_logs_dir(state)), "analysis")
    name = os.path.basename(body.get("file", ""))
    path = os.path.join(folder, name)
    if not name or not os.path.isfile(path):
        raise ModeError(t("Nothing found."))
    if name.lower().endswith(".png"):
        with open(path, "rb") as fh:
            return {"name": name, "image": "data:image/png;base64," + base64.b64encode(fh.read()).decode()}
    with open(path, encoding="utf-8", errors="replace") as fh:
        return {"name": name, "text": fh.read(200_000)}


# ---------------------------------------------------------------------------
# The logger (the cable)
# ---------------------------------------------------------------------------

def _logger_adx(state, role: str = "bin_a") -> str:
    """The chosen ADX; none chosen: the suggested one of the pack, else the built-in standard."""
    from .. import adxpack

    path = state.paths.get("adx", "")
    if not path or not os.path.isfile(path):
        view = _adx_view(state, role)
        suggested = os.path.join(adxpack.folder(), view["recommended"]) if view["recommended"] else ""
        path = suggested if suggested and os.path.isfile(suggested) else adxpack.standard_adx()
    if not path:
        path = _pick_adx(state)
    if not path:
        raise ModeError(t("Choose the ADX the logger reads the ECU with."))
    return path


def _logger_port(state, body: Dict) -> str:
    from .. import i18n

    port = str(body.get("port") or "").strip()
    if not port:
        raise ModeError(t("Choose the COM port of the cable."))
    state.settings["logger_port"] = port
    i18n.save_settings(logger_port=port)
    return port


def _transport(port: str):
    from ..ds2logger import SerialTransport

    return lambda adx: SerialTransport(port, adx.parity)


def _adx_view(state, role: str) -> Dict[str, Any]:
    """The chosen ADX, whether the firmware in the car supports it, the pack and a suggestion."""
    from .. import adxpack, car as carmod, logcheck

    path = state.paths.get("adx", "")
    out: Dict[str, Any] = {"name": os.path.basename(path), "path": path}
    bin_path = state.paths.get(role if role in ("bin_a", "bin_b", "bin2") else "bin_a", "")
    xdf = None
    firmware = ""
    try:
        if bin_path:
            from ..binfile import BinFile, Reader

            xdf_path = state.paths.get("xdf2" if role == "bin2" else "xdf", "")
            if xdf_path:
                xdf = state.xdf(xdf_path)
                firmware = Reader(xdf, BinFile(bin_path)).firmware_id() or ""
    except Exception:  # noqa: BLE001 - the check just knows less
        xdf = None
    if path and os.path.isfile(path):
        try:
            out.update(logcheck.adx_summary(path))
            patchlist = state.xdf(state.paths["patchlist"]) if state.paths.get("patchlist") else None
            out["check"] = logcheck.check(path, bin_path, xdf, patchlist)
        except Exception as exc:  # noqa: BLE001 - shown next to the ADX
            out["error"] = str(exc)
    project = os.path.dirname(_logs_dir(state)) if state.settings.get("project_dir") else ""
    model = carmod.load(project)["model"] if project and os.path.isdir(project) else ""
    engine = adxpack.engine_of(model, os.path.basename(bin_path), os.path.basename(path))
    out["engine"] = engine
    out["firmware"] = firmware
    out["pack"] = [{"name": f["name"], "request": f.get("request", ""), "extended": f.get("extended"),
                    "channels": f.get("channels"), "error": f.get("error", "")}
                   for f in adxpack.files() if f["type"] == "adx"]
    out["recommended"] = os.path.basename(adxpack.recommend(firmware, engine))
    out["standard"] = os.path.basename(adxpack.standard_adx())
    out["pack_folder"] = adxpack.folder()
    return out


def logger_state(state, body: Dict) -> Dict[str, Any]:
    from ..ds2logger import list_ports

    rec = getattr(state, "recorder", None)
    role = str(body.get("role") or state.settings.get("logger_role") or "bin_a")
    return {"ports": list_ports(), "port": state.settings.get("logger_port", ""),
            "adx": os.path.basename(state.paths.get("adx", "") or ""),
            "adx_info": _adx_view(state, role),
            "status": dict(rec.status) if rec else None, "recording": bool(rec and rec.running),
            "test": getattr(state, "logger_test", None)}


def logger_pack(state, body: Dict) -> Dict[str, Any]:
    """Download the ADX pack from the MS4X Wiki (never bundled with the program)."""
    from .. import adxpack

    try:
        res = adxpack.download(timeout=20)
    except (OSError, ValueError) as exc:
        raise ModeError(t("Could not read the list of files on ms4x.net: {error}", error=exc)) from exc
    out = logger_state(state, body)
    lines = [t("Downloaded: {n} file(s) into {folder}", n=len(res["files"]), folder=res["folder"])]
    if res["errors"]:
        lines.append(t("Failed: {list}", list="; ".join(f"{n}: {e[:60]}" for n, e in res["errors"][:5])))
    out["message"] = "\n".join(lines)
    return out


def logger_use_adx(state, body: Dict) -> Dict[str, Any]:
    """Choose an ADX of the pack (by file name, only inside the pack folder)."""
    from .. import adxpack

    name = os.path.basename(str(body.get("name") or ""))
    path = os.path.join(adxpack.folder(), name)
    if not name or not os.path.isfile(path):
        raise ModeError(t("No such file in the ADX pack: {name}", name=name))
    state.set_path("adx", path)
    return logger_state(state, body)


def logger_test(state, body: Dict) -> Dict[str, Any]:
    import datetime as _dt

    from ..ds2logger import test_connection

    if getattr(state, "recorder", None) and state.recorder.running:
        raise ModeError(t("Stop the recording first."))
    folder = _logs_dir(state)
    adx_path = _logger_adx(state, str(body.get("role") or "bin_a"))
    port = _logger_port(state, body)
    raw = os.path.join(folder, "raw")
    os.makedirs(raw, exist_ok=True)
    journal = os.path.join(raw, _dt.datetime.now().strftime("test_%Y-%m-%d_%H-%M-%S.jsonl"))
    from .. import adxpack

    result = test_connection(adx_path, _transport(port), journal, adxpack.standard_adx())
    result["journal_file"] = os.path.relpath(journal, folder)
    state.logger_test = result
    return logger_state(state, {})


def logger_start(state, body: Dict) -> Dict[str, Any]:
    from .. import tplog
    from ..adx import DECODER_VERSION
    from ..ds2logger import Recorder

    if getattr(state, "recorder", None) and state.recorder.running:
        raise ModeError(t("A recording is already running."))
    folder = _logs_dir(state)
    firmware = _firmware_for(state, body.get("role") or "")
    if firmware is None:
        return {**logger_state(state, {}), "cancelled": True}
    bin_path, xdf_path = firmware
    if not (os.path.isfile(bin_path) and os.path.isfile(xdf_path)):
        raise ModeError(t("Choose the firmware that was in the car."))
    adx_path = _logger_adx(state, str(body.get("role") or "bin_a"))
    port = _logger_port(state, body)
    note = str(body.get("note") or "")[:500]

    from .. import adxpack

    def done(csv_path: str) -> None:
        tplog.bind(csv_path, bin_path, xdf_path, note,
                   {"adx": os.path.abspath(rec.adx_path), "recorded_with": "MS43 AI-Tuner logger",
                    "decoder": DECODER_VERSION, "logger_mode": rec.mode,
                    "raw": os.path.relpath(rec.raw_path, folder)})
        state.notify()

    rec = Recorder(adx_path, _transport(port), folder, done, adxpack.standard_adx())
    state.recorder = rec
    state.logger_test = None
    rec.start()
    return logger_state(state, {})


def logger_stop(state, body: Dict) -> Dict[str, Any]:
    rec = getattr(state, "recorder", None)
    if rec:
        rec.stop()
    out = logger_state(state, {})
    out["logs"] = logs_state(state, {})
    return out

# ---------------------------------------------------------------------------
# Reports for the other modes
# ---------------------------------------------------------------------------

def save_report(state, body: Dict) -> Dict[str, Any]:
    kind, what = body.get("kind", "html"), body.get("what", "")
    types = {"html": (t("HTML page"), "*.html"), "csv": (t("CSV for Excel"), "*.csv"),
             "pdf": (t("PDF document"), "*.pdf")}
    if kind not in types:
        raise ModeError(f"unknown format {kind}")
    if what == "cross" and getattr(state, "cross", None) is not None and kind == "html":
        name = t("ms43_versions")
        writer = lambda path: report.write_cross_html(state.cross, path)  # noqa: E731
    elif what == "port" and getattr(state, "port", None) is not None:
        name = t("ms43_port")
        if kind == "html":
            writer = lambda path: report.write_port_html(state.port, path)  # noqa: E731
        elif kind == "csv":
            writer = lambda path: report.write_port_csv(state.port, path)  # noqa: E731
        else:
            from ..pdfreport import write_port_pdf

            writer = lambda path: write_port_pdf(state.port, path)  # noqa: E731
    else:
        raise ModeError(t("Run the comparison first."))
    path = DIALOGS.save_file(t("Save as"), [types[kind]], f"{name}.{kind}",
                             state.settings.get("last_out_dir", ""))
    if path:
        writer(path)
    return {"path": path}
