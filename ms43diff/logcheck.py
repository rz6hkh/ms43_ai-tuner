# -*- coding: utf-8 -*-
"""
Does a logger definition (ADX) fit the firmware in the car? Checked at home,
before going to the car.

An ADX with the extended data request 0B B0 needs either the MS43X custom
firmware or the "DS2 Logging Feature Enhancement" patch of the community
patchlist in the firmware. The standard request 0B 03 works on every MS43.
The patch changes program code, so a 64 KB calibration file cannot show it.
"""

from __future__ import annotations

import os
import re
from typing import Any, Dict, Optional

from .i18n import t

_LOGGING_PATCH = re.compile(r"DS2\s*Logging|Logging\s*Feature", re.IGNORECASE)


def adx_summary(adx_path: str) -> Dict[str, Any]:
    from .adx import Adx
    from .ds2logger import adx_kind

    adx = Adx(adx_path)
    kind = adx_kind(adx)
    return {"title": adx.title, "channels": len(adx.channels), "baud": adx.baud, **kind}


def check(adx_path: str, bin_path: str, xdf=None, patchlist=None) -> Dict[str, Any]:
    """{"state": "ok" | "warn" | "unknown", "text": ...} for this ADX and this firmware."""
    from .binfile import BinFile, Reader
    from .compare import PATCH_APPLIED, check_patches

    kind = adx_summary(adx_path)
    if not kind["extended"]:
        return {"state": "ok", "text": t("Standard data request {req}: works on any MS43.",
                                         req=kind["request"] or "?")}
    if not bin_path or not os.path.isfile(bin_path):
        return {"state": "unknown", "text": t("Extended request 0B B0: choose the firmware that is in "
                                              "the car to check that it supports it.")}
    binf = BinFile(bin_path)
    firmware = ""
    if xdf is not None:
        try:
            firmware = Reader(xdf, binf).firmware_id() or ""
        except Exception:  # noqa: BLE001 - the check is advisory
            firmware = ""
    if "43X" in firmware.upper():
        return {"state": "ok", "text": t("Extended request 0B B0: the MS43X custom firmware {fw} "
                                         "supports it.", fw=firmware)}
    patch_state: Optional[str] = None
    if patchlist is not None and getattr(patchlist, "patches", None):
        statuses = [s for s in check_patches(patchlist, binf) if _LOGGING_PATCH.search(s.patch.title)]
        if statuses:
            patch_state = "applied" if any(s.state == PATCH_APPLIED for s in statuses) else "missing"
    if patch_state == "applied":
        return {"state": "ok", "text": t("Extended request 0B B0: the DS2 Logging Feature Enhancement "
                                         "patch is in {name}.", name=os.path.basename(bin_path))}
    small = binf.size_kb <= 64
    if patch_state == "missing" and not small:
        return {"state": "warn", "text": t(
            "Extended request 0B B0, but {name} ({fw}) has no DS2 Logging Feature Enhancement "
            "patch: the ECU will answer B0 and the logger will use the standard ADX (0B 03), "
            "fewer channels.", name=os.path.basename(bin_path), fw=firmware or "?")}
    return {"state": "unknown", "text": t(
        "Extended request 0B B0 needs the DS2 Logging Feature Enhancement patch or MS43X; "
        "{why} \"Check the connection\" in the car tells for sure.",
        why=t("a 64 KB calibration file cannot show a code patch.") if small else
        t("choose the patchlist XDF to check the firmware.") if patchlist is None else
        t("the patchlist has no such patch."))}
