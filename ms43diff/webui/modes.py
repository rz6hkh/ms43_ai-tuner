# -*- coding: utf-8 -*-
"""
Data for the window modes other than "Compare A and B": Browse, Different
versions (compare + port plan), Patches, VE tuning and Reference.

Every function takes the server State and a request body and returns a JSON-
ready dict. The heavy lifting is done by the same modules the CLI uses.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List

from .. import heatmap, names, report
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
              "bin2": t("Firmware of the other version"), "patchlist": t("Patchlist XDF"),
              "velog": t("Log (CSV)")}
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
# VE tuning
# ---------------------------------------------------------------------------

_ROLES_LOG = ("rpm", "load", "lambda", "target", "trim", "coolant")


def ve_setup(state, body: Dict) -> Dict[str, Any]:
    """Maps that can be tuned and the log columns (with the program's guess)."""
    from .. import vetune

    reader = state.reader(_role(body))
    maps = [i.title for i in reader.xdf.readable_items() if i.rows > 1 and i.cols > 1]
    preferred = [n for n in maps if "_ve" in n or "maf_tab" in n or "_map_" in n]
    out: Dict[str, Any] = {"maps": preferred + [n for n in maps if n not in preferred],
                           "preferred": len(preferred), "columns": [], "guess": {}, "rows": 0}
    if state.paths.get("velog"):
        try:
            headers, rows = vetune.read_log(state.paths["velog"])
        except vetune.LogError as exc:
            out["log_error"] = str(exc)
        else:
            out.update(columns=headers, rows=len(rows),
                       guess={k: v for k, v in vetune.guess_columns(headers).items()
                              if k in _ROLES_LOG})
    return out


def ve_run(state, body: Dict) -> Dict[str, Any]:
    from .. import vetune

    role = _role(body)
    _need(state, "xdf", role, "velog")
    reader = state.reader(role)
    item = reader.xdf.by_title(body.get("map") or "")
    if item is None:
        raise ModeError(t("Choose a map."))
    try:
        headers, rows = vetune.read_log(state.paths["velog"])
    except vetune.LogError as exc:
        raise ModeError(str(exc)) from exc
    chosen = {**vetune.guess_columns(headers), **{k: v for k, v in (body.get("columns") or {}).items()
                                                  if v in headers}}
    missing = [r for r in ("rpm", "load", "lambda") if not chosen.get(r)]
    if missing:
        raise ModeError(t("Could not find these columns in the log: {cols}", cols=", ".join(missing)))
    columns = vetune.LogColumns(rpm=chosen["rpm"], load=chosen["load"], lam=chosen["lambda"],
                                target=chosen.get("target"), trim=chosen.get("trim"),
                                coolant=chosen.get("coolant"))
    num = lambda key, default: float(body.get(key) if body.get(key) not in (None, "") else default)  # noqa: E731
    result = vetune.analyse(reader, item, rows, columns, mode=body.get("mode") or "lambda",
                            fuel=body.get("fuel") or "gasoline",
                            target_lambda=num("target", 1.0),
                            min_samples=int(num("min_samples", 8)),
                            max_step=num("max_step", 25) / 100.0,
                            delay_samples=int(num("delay", 0)))
    state.ve = (reader, result)
    return ve_json(reader, result)


def ve_json(reader, result) -> Dict[str, Any]:
    item = result.item
    dec = item.value_decimals
    scale = max((abs(result.correction_percent(r, c)) for r in range(item.rows)
                 for c in range(item.cols)), default=1.0) or 1.0
    rows = []
    for r in range(item.rows):
        row = []
        for c in range(item.cols):
            samples = result.samples_at(r, c)
            touched = result.new[r][c] != result.old[r][c]
            cell: Dict[str, Any] = {"v": "·" if samples and not touched else "",
                                    "d": str(samples) if samples else "",
                                    "tip": t("was {old}, will be {new}; samples {n}",
                                             old=format_number(result.old[r][c], dec, 1),
                                             new=format_number(result.new[r][c], dec, 1), n=samples)}
            if touched:
                pct = result.correction_percent(r, c)
                rgb = heatmap.delta_color(pct, scale)
                cell.update(v=f"{pct:+.1f}%", bg=heatmap.hex_color(rgb),
                            fg=heatmap.hex_color(heatmap.text_color(rgb)))
            row.append(cell)
        rows.append(row)
    labels = lambda which: report._axis_labels(reader, item, which)  # noqa: E731
    y_name, x_name = names.axis_names(item.title)
    legend = [{"v": f"{v:+.1f}", "bg": heatmap.hex_color(rgb),
               "fg": heatmap.hex_color(heatmap.text_color(rgb))}
              for v, rgb in heatmap.delta_legend_stops(scale)]
    guidance = []
    for section in report._wiki_guidance(item.title)[:4]:
        text = section.text[:1500]
        shown = report.translate_wiki(text)
        guidance.append({"head": f"{section.page} / {section.heading}", "text": shown,
                         "orig": text if shown != text else "", "url": section.url})
    return {
        "map": item.title, "name": names.explain(item.title, item.description)["name"],
        "stats": {"used": result.used_samples, "total": result.total_samples,
                  "coverage": round(result.coverage * 100), "changed": result.touched_cells},
        "skipped": [[k, v] for k, v in result.skipped.items() if v],
        "notes": result.notes,
        "grid": {"x": labels("x"), "y": labels("y"), "rows": rows,
                 "caption": " · ".join(filter(None, [
                     t("rows — {name}", name=y_name or t("index")),
                     t("columns — {name}", name=x_name or t("index"))])),
                 "legend_title": t("correction, %:").rstrip(":"), "legend": legend},
        "wiki": guidance,
    }


def ve_save(state, body: Dict) -> Dict[str, Any]:
    if not getattr(state, "ve", None):
        raise ModeError(t("Calculate the correction first."))
    reader, result = state.ve
    kind = body.get("kind")
    if kind == "html":
        path = DIALOGS.save_file(t("Save as"), [(t("HTML page"), "*.html")],
                                 t("ms43_ve_tuning") + ".html", state.settings.get("last_out_dir", ""))
        if path:
            report.write_vetune_html(reader, result, path,
                                     log_name=os.path.basename(state.paths.get("velog", "")))
        return {"path": path}
    if kind == "bin":
        from .. import vetune

        base = os.path.splitext(os.path.basename(reader.bin.path))[0]
        path = DIALOGS.save_file(t("Save as"), [(t("Firmware files"), "*.bin")], f"{base}_ve.bin",
                                 os.path.dirname(reader.bin.path))
        if not path:
            return {"path": ""}
        if os.path.abspath(path) == os.path.abspath(reader.bin.path):
            raise ModeError(t("Cannot write over the source firmware."))
        info = vetune.write_tuned_bin(reader, result.item, result, path)
        return {"path": path, "cells": info["cells"], "clipped": info["clipped"]}
    raise ModeError(f"unknown format {kind}")


# ---------------------------------------------------------------------------
# Reference (MS4X Wiki)
# ---------------------------------------------------------------------------

def _section_list(state, sections) -> List[Dict[str, Any]]:
    state.wiki_sections = list(sections)
    return [{"id": i, "page": s.page, "heading": s.heading, "caution": bool(s.caution_lines)}
            for i, s in enumerate(state.wiki_sections)]


def wiki(state, body: Dict) -> Dict[str, Any]:
    from .. import wikicache

    if not wikicache.available():
        return {"available": False, "sections": []}
    info = wikicache.meta()
    query = (body.get("query") or "").strip()
    if body.get("cautions"):
        sections = wikicache.cautions()
    elif query:
        sections = wikicache.search(query, limit=200)
    else:
        sections = [s for page in wikicache.load() for s in page.sections]
    return {"available": True, "fetched": info.get("fetched", "?"),
            "pages": len(wikicache.load()), "params": len(wikicache.index_parameters()),
            "source": info.get("source", ""), "sections": _section_list(state, sections)}


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
    from .. import wikicache

    result = wikicache.download()
    wikicache.load(force=True)
    out = wiki(state, {})
    out["downloaded"] = result["pages"]
    out["errors"] = [f"{n}: {e[:80]}" for n, e in result["errors"]]
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
