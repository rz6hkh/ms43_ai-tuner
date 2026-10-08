# -*- coding: utf-8 -*-
"""
Local MS4X Wiki cache — a reference that works without internet.

Why: ms4x.net is not reachable everywhere, and firmware work happens at the
computer with TunerPro. So pages are downloaded once and then read from disk.

What the module does:
  * `download()` — fetches the pages and splits them into sections;
  * `load()` — reads the cache;
  * `index_parameters()` — links wiki text to XDF parameter names
    automatically: the wiki mentions them right in the text (c_conf_cat,
    lc_swi_cal_mon_cks etc.), so for every parameter we can find the paragraph
    that explains it;
  * `cautions()` — collects all Warning/Note blocks. They answer the question
    "how not to break anything".

The cache content belongs to the MS4X Wiki authors and is stored locally as a
reference copy; every piece keeps its page title and link.

The site returns 403 to requests without a recognisable User-Agent, so one is
set explicitly.
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field
from html.parser import HTMLParser
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from .i18n import t

BASE = "https://www.ms4x.net/index.php?title="
USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")

# Pages worth keeping offline. Order = download order.
DEFAULT_PAGES: Tuple[str, ...] = (
    # Names are taken from the links on the wiki main page — case and
    # underscores there are not obvious ("First_steps_and_requirements", "How_to_connect").
    "Siemens_MS43",
    "MS43X_Custom_Firmware",
    "Siemens_Keyword_Translation",
    "Siemens_MS43_Extended_Load_Limit",
    "Siemens_MS43_Retrofit_MAP_Sensor",
    "Additional_Analog_Inputs_For_Logging_With_MS43",
    "Use_Rear_O2_Inputs_For_Analog_Sensors",
    "TunerPro_Data_Logging",
    "TunerPro_MS43_Community_Patchlist",
    "Fuel_Injector_Deadtimes",
    "Aftermarket_Upgrade_Sensor_Data",
    "2048kg/h_MAF_Sensor_Switch",
    "Audi_RS4_MAF_Sensor_Conversion",
    "PMAS_HPX_MAF_Sensor_Conversion",
    "B58_Ignition_Coil_Conversion",
    "M5x_To_N54_Intake_Conversion",
    "M5x_To_S58_Intake_Conversion",
    "E46_Fuel_Pressure_Regulator_Modification",
    "Forced_Induction_Upgrades",
    "Siemens_MS43_Pinout",
    "Siemens_MS43_CAN_Bus",
    "Siemens_MS43_PCB_Components",
    "First_steps_and_requirements",
    "How_to_connect",
    "Live_Tuning_Options",
    "Flashing_Tools",
    "Definition_Files",
    "Firmware_Files",
    "MS4X_Dev_Group_Flasher",
    "Logger.S",
    "Engine_Wiring_Harness_Connectors",
    "CanTCU_Integration",
    "Alpina_Firmware_Preservation",
    "Cluster_M3_LED_Retrofitting",
    "Siemens_GS20",
)


def offline_hint() -> str:
    """What to do when the site cannot be reached."""
    return t(
        "If ms4x.net cannot be reached: the program uses the system proxy settings, so a "
        "VPN or proxy that works in the browser works here too. Or copy ms4x_wiki.json from "
        "a computer where the reference is loaded (Reference → Save a copy) and import it.")


def page_url(page: str) -> str:
    return BASE + urllib.parse.quote(page, safe="_/:")


# ---------------------------------------------------------------------------
# HTML parsing
# ---------------------------------------------------------------------------

_SKIP_TAGS = {"script", "style", "sup"}
_HEADINGS = {"h1", "h2", "h3", "h4", "h5", "h6"}


class _WikiParser(HTMLParser):
    """Extracts headings, paragraphs, lists and tables from a MediaWiki page.

    A table becomes one text block, a line per row with the cells joined by
    " | " (sensor voltage scales, pinouts and CAN layouts live in tables).
    """

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.blocks: List[Tuple[str, str]] = []   # (kind, text)
        self._skip_depth = 0
        self._current: Optional[str] = None
        self._buf: List[str] = []
        self._in_content = False
        self._content_depth = 0
        self._div_depth = 0
        self._table_depth = 0
        self._rows: List[str] = []
        self._cells: List[str] = []
        self._cell: Optional[List[str]] = None

    def handle_starttag(self, tag, attrs):
        attrs_d = dict(attrs)
        if tag == "div":
            self._div_depth += 1
            classes = (attrs_d.get("class") or "")
            if not self._in_content and (
                "mw-parser-output" in classes or attrs_d.get("id") == "mw-content-text"
            ):
                self._in_content = True
                self._content_depth = self._div_depth
        if tag in _SKIP_TAGS:
            self._skip_depth += 1
            return
        if not self._in_content or self._skip_depth:
            return
        if tag == "table":
            if self._table_depth == 0:
                self._flush()
                self._rows = []
            self._table_depth += 1
            return
        if self._table_depth:
            if tag == "tr" and self._table_depth == 1:
                self._cells = []
            elif tag in ("td", "th") and self._table_depth == 1:
                self._cell = []
            elif tag == "br" and self._cell is not None:
                self._cell.append(" ")
            return
        if tag in _HEADINGS:
            self._flush()
            self._current = "heading"
            self._buf = []
        elif tag in ("p", "li", "dd", "dt"):
            self._flush()
            self._current = "text"
            self._buf = []
        elif tag == "br":
            self._buf.append("\n")

    def handle_endtag(self, tag):
        if tag in _SKIP_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)
            return
        if tag == "div":
            if self._in_content and self._div_depth == self._content_depth:
                self._in_content = False
            self._div_depth = max(0, self._div_depth - 1)
        if not self._in_content or self._skip_depth:
            return
        if self._table_depth:
            if tag == "table":
                self._table_depth -= 1
                if self._table_depth == 0 and self._rows:
                    self.blocks.append(("text", "\n".join(self._rows)))
                    self._rows = []
            elif tag in ("td", "th") and self._table_depth == 1 and self._cell is not None:
                self._cells.append(re.sub(r"\s+", " ", "".join(self._cell)).strip())
                self._cell = None
            elif tag == "tr" and self._table_depth == 1:
                if any(self._cells):
                    self._rows.append(" | ".join(self._cells))
                self._cells = []
            return
        if tag in _HEADINGS or tag in ("p", "li", "dd", "dt"):
            self._flush()

    def handle_data(self, data):
        if not self._in_content or self._skip_depth:
            return
        if self._table_depth:
            if self._cell is not None:
                self._cell.append(data)
            return
        if self._current:
            self._buf.append(data)

    def _flush(self):
        if self._current and self._buf:
            text = re.sub(r"[ \t]+", " ", "".join(self._buf)).strip()
            text = re.sub(r"\n{2,}", "\n", text)
            if text and text.lower() not in ("edit", "advertising:"):
                self.blocks.append((self._current, text))
        self._current = None
        self._buf = []

    def close(self):
        self._flush()
        super().close()


_CAUTION_LABEL = re.compile(r"^\s*(warning|attention|danger|caution|disclaimer|important)\b", re.I)
_CAUTION_RISK = re.compile(
    r"\b(damag\w*|harm\w*|brick\w*|destroy\w*|dangerous|not advised|not advisable|"
    r"should be avoided|at your own risk|lean[- ]wall|non[- ]starting|"
    r"engine (?:will not|won't|isn't) start\w*|know what you'?re doing|"
    r"(?:lead\w* to|result\w* in|will|can|may) (?:a |the )?corrupt\w*)", re.I)
_CAUTION_START = re.compile(r"(?:^|[.!:;(]\s*)(do not|don'?t|never|make sure|be careful)\b", re.I)
_CAUTION_ANY = re.compile(r"\b(do not|don'?t|never|make sure|be careful)\b", re.I)
_CAUTION_CONTEXT = re.compile(r"\b(flash\w*|boot ?mode|VIN|checksum\w*|adaptation\w*|immobili\w*)", re.I)


def _is_caution_line(line: str) -> bool:
    if "copyright" in line.lower():
        return False                       # site rules, not tuning
    return bool(_CAUTION_LABEL.search(line) or _CAUTION_RISK.search(line)
                or _CAUTION_START.search(line)
                or (_CAUTION_ANY.search(line) and _CAUTION_CONTEXT.search(line)))


@dataclass
class Section:
    heading: str
    text: str
    page: str
    url: str

    @property
    def caution_lines(self) -> List[str]:
        """Warning paragraphs inside the section.

        Checking the whole section is useless: "Warning:" sits in the middle,
        not at the start, so each paragraph is checked separately. A paragraph
        counts when it starts with a warning label, names a real risk, starts
        with a prohibition, or has a prohibition next to flashing, the VIN,
        checksums or adaptations. Plain notes ("Note: MS45 uses a different MAF
        sensor") and turns of speech ("never used in production") do not.
        """
        return [line.strip() for line in self.text.split("\n")
                if line.strip() and _is_caution_line(line)]

    @property
    def is_caution(self) -> bool:
        return bool(self.caution_lines)


@dataclass
class WikiPage:
    name: str
    title: str
    url: str
    fetched: str
    sections: List[Section] = field(default_factory=list)

    def to_json(self) -> Dict:
        return {
            "name": self.name,
            "title": self.title,
            "url": self.url,
            "fetched": self.fetched,
            "sections": [
                {"heading": s.heading, "text": s.text} for s in self.sections
            ],
        }

    @classmethod
    def from_json(cls, raw: Dict) -> "WikiPage":
        page = cls(
            name=raw.get("name", ""), title=raw.get("title", ""),
            url=raw.get("url", ""), fetched=raw.get("fetched", ""),
        )
        page.sections = [
            Section(heading=s.get("heading", ""), text=s.get("text", ""),
                    page=page.title, url=page.url)
            for s in raw.get("sections", [])
        ]
        return page


def parse_html(name: str, html_text: str) -> WikiPage:
    parser = _WikiParser()
    parser.feed(html_text)
    parser.close()

    title = name.replace("_", " ")
    match = re.search(r"<title>(.*?)</title>", html_text, re.S | re.I)
    if match:
        title = re.sub(r"\s*-\s*MS4X Wiki\s*$", "", match.group(1)).strip()

    page = WikiPage(name=name, title=title, url=page_url(name),
                    fetched=time.strftime("%Y-%m-%d %H:%M"))
    heading = "General"
    buffer: List[str] = []
    for kind, text in parser.blocks:
        if kind == "heading":
            if buffer:
                page.sections.append(
                    Section(heading, "\n".join(buffer), page.title, page.url))
                buffer = []
            heading = text
        else:
            buffer.append(text)
    if buffer:
        page.sections.append(Section(heading, "\n".join(buffer), page.title, page.url))
    return page


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------


def bundled_dir() -> str:
    """The cache shipped next to the program (travels with the .exe).

    In a PyInstaller .exe the files are unpacked into a temporary folder whose
    path is in sys._MEIPASS.
    """
    import sys

    base = getattr(sys, "_MEIPASS", None)
    if base:
        packed = os.path.join(base, "ms43diff", "wikidata")
        if os.path.isdir(packed):
            return packed
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "wikidata")


def user_dir() -> str:
    """The user cache — updates are written here."""
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    return os.path.join(base, "ms43diff", "wiki")


def cache_path(folder: str) -> str:
    return os.path.join(folder, "ms4x_wiki.json")


def _write_cache(folder: str, payload: Dict) -> str:
    """Write the cache atomically: a broken write never leaves a half file."""
    os.makedirs(folder, exist_ok=True)
    path = cache_path(folder)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, path)
    return path


def _fetch(url: str, timeout: int) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8", errors="replace")


_SKIP_PAGE = re.compile(r"^(Main_Page|Special:|File:|Category:|Template:|User:|Talk:|Help:|MediaWiki:)",
                        re.IGNORECASE)
_ALLPAGES_LINK = re.compile(r'href="(?:/index\.php\?title=|/wiki/)([^"&#]+)"[^>]*title="[^"]*"')


def site_pages(timeout: int = 30) -> List[str]:
    """Names of all articles on the wiki (MediaWiki API, or the Special:AllPages page)."""
    names: List[str] = []
    try:
        cont = ""
        for _ in range(20):
            url = (BASE.replace("index.php?title=", "api.php?") +
                   "action=query&list=allpages&aplimit=500&format=json" +
                   (f"&apcontinue={urllib.parse.quote(cont)}" if cont else ""))
            data = json.loads(_fetch(url, timeout))
            names += [p["title"].replace(" ", "_") for p in data["query"]["allpages"]]
            cont = (data.get("continue") or {}).get("apcontinue", "")
            if not cont:
                break
    except (urllib.error.URLError, OSError, ValueError, KeyError, TypeError):
        names = []
        html_text = _fetch(page_url("Special:AllPages"), timeout)
        body = html_text.split("mw-allpages-body", 1)[-1]
        names = [urllib.parse.unquote(n) for n in _ALLPAGES_LINK.findall(body)]
    out: List[str] = []
    for name in names:
        if name and not _SKIP_PAGE.match(name) and name not in out:
            out.append(name)
    return out


# Other control units: a page named after one of them is about that unit, even when it
# compares itself with the MS43.
_OTHER_ECU = re.compile(r"MS4[0125]|MS45|ME7|ME9|MSD\d|MSV\d|GS\d\d|GK\d\d|Bosch|M3\.3|MK60|EK\d",
                        re.IGNORECASE)


def is_ms43_page(page: "WikiPage") -> bool:
    """Is a page about the MS43 (or about the whole MS4x family it belongs to)?"""
    title = page.title or page.name
    if re.search(r"MS43", title, re.IGNORECASE):
        return True
    if _OTHER_ECU.search(title.replace("MS4X", "").replace("MS4x", "")):
        return False
    if re.search(r"MS4X", title, re.IGNORECASE):
        return True
    text = " ".join(s.text for s in page.sections)
    return len(re.findall(r"\bMS43", text, re.IGNORECASE)) >= 2


def _body(page: "WikiPage") -> tuple:
    return tuple(s.text for s in page.sections)


def add_pages(names: Sequence[str], folder: Optional[str] = None, timeout: int = 30) -> Dict:
    """Add pages the owner picked (e.g. ones skipped as not about the MS43)."""
    folder = folder or user_dir()
    payload = _read_payload(cache_path(folder)) or (
        {**meta(), "pages": [p.to_json() for p in load()]} if load() else None)
    if payload is None:
        raise ValueError(t("The reference is not loaded."))
    added, errors = [], []
    pages = [p for p in payload["pages"] if p.get("name") not in set(names)]
    for name in names:
        try:
            pages.append(parse_html(name, _fetch(page_url(name), timeout)).to_json())
            added.append(name)
        except Exception as exc:  # noqa: BLE001 - reported to the owner
            errors.append((name, str(exc)))
    extra = list(payload.get("extra", []))
    extra += [n for n in added if n not in extra and n not in DEFAULT_PAGES]
    clean = {k: v for k, v in payload.items() if k not in ("pages", "folder")}
    clean.update(extra=extra, skipped=[n for n in payload.get("skipped", []) if n not in added],
                 pages=pages)
    if added:
        _write_cache(folder, clean)
        load(force=True)
    return {"added": added, "errors": errors}


def download(pages: Optional[Sequence[str]] = None, folder: Optional[str] = None,
             progress=None, timeout: int = 30, discover: bool = True) -> Dict:
    """Download pages into the cache. Returns a summary.

    The site needs a browser User-Agent, otherwise it answers 403. A page that
    fails keeps its previous copy; when nothing could be downloaded the cache
    is not touched at all (a failed update never wipes a working reference).

    With discover, the list of all pages on the site is read too: pages that are
    new since the last update are fetched and kept only when they are about the
    MS43 (is_ms43_page); the others are remembered as skipped and not fetched again.
    """
    folder = folder or user_dir()
    old = _read_payload(cache_path(folder)) or (dict(meta()) if load() else {})
    extra: List[str] = list(old.get("extra", []))
    skipped: List[str] = list(old.get("skipped", []))
    aliases: Dict[str, str] = dict(old.get("aliases", {}))
    say = progress or (lambda *a, **k: None)
    wanted = list(pages) if pages is not None else list(DEFAULT_PAGES) + \
        [n for n in extra if n not in DEFAULT_PAGES]
    collected: List[WikiPage] = []
    errors: List[Tuple[str, str]] = []
    for idx, name in enumerate(wanted, 1):
        say(idx, len(wanted), name, stage="pages")
        try:
            html_text = _fetch(page_url(name), timeout)
        except (urllib.error.URLError, OSError) as exc:
            errors.append((name, str(exc)))
            if not collected and len(errors) >= 2 and not isinstance(exc, urllib.error.HTTPError):
                # The site is not reachable at all: do not wait out every page.
                errors.append(("…", t("stopped: the site is not reachable")))
                break
            continue
        try:
            page = parse_html(name, html_text)
        except Exception as exc:  # noqa: BLE001 - one broken page must not break everything
            errors.append((name, t("parsing failed: {error}", error=exc)))
            continue
        if not page.sections:
            # A block page, a login or bot check, or a changed site layout: keep the old copy.
            errors.append((name, t("no article text in the answer (the old copy is kept)")))
            continue
        collected.append(page)

    added: List[str] = []
    new_skipped: List[str] = []
    listing_error = ""
    if discover and pages is None and collected:
        say(0, 0, "", stage="listing")
        try:
            known = set(DEFAULT_PAGES) | set(extra) | set(skipped) | set(aliases)
            fresh_names = [n for n in site_pages(timeout) if n not in known]
        except (urllib.error.URLError, OSError, ValueError) as exc:
            fresh_names, listing_error = [], str(exc)
        bodies = {_body(p): p.name for p in collected + load()}
        for idx, name in enumerate(fresh_names, 1):
            say(idx, len(fresh_names), name, stage="new")
            try:
                page = parse_html(name, _fetch(page_url(name), timeout))
            except Exception as exc:  # noqa: BLE001 - a broken page is just not added
                errors.append((name, str(exc)))
                continue
            if not page.sections:
                errors.append((name, t("no article text in the answer (the old copy is kept)")))
                continue
            twin = bodies.get(_body(page))
            if twin:
                aliases[name] = twin       # another name of a page we have (a redirect)
                continue
            if is_ms43_page(page):
                collected.append(page)
                extra.append(name)
                added.append(name)
            else:
                skipped.append(name)
                new_skipped.append(name)

    if not collected:
        return {"folder": folder, "pages": 0, "kept": len(load()), "errors": errors,
                "path": "", "written": False, "added": [], "skipped": [],
                "listing_error": listing_error, "missing": missing_pages()}
    # A name in extra that is another name of a page we have (a redirect) is an alias.
    by_body: Dict[tuple, str] = {}
    for p in collected:
        twin = by_body.setdefault(_body(p), p.name)
        if twin != p.name and p.name not in DEFAULT_PAGES:
            aliases[p.name] = twin
    extra = [n for n in extra if n not in aliases]
    collected = [p for p in collected if p.name not in aliases]
    fresh = {p.name for p in collected}
    keep_names = set(wanted) | set(extra)
    kept = [p for p in load() if p.name not in fresh and p.name in keep_names]
    payload = {
        "source": "https://www.ms4x.net",
        "note": "Local reference copy of the MS4X Wiki. Rights belong to the wiki authors.",
        "fetched": time.strftime("%Y-%m-%d %H:%M"),
        "extra": extra,
        "skipped": skipped,
        "aliases": aliases,
        "pages": [p.to_json() for p in collected + kept],
    }
    path = _write_cache(folder, payload)
    load(force=True)
    return {"folder": folder, "pages": len(collected), "kept": len(kept), "errors": errors,
            "path": path, "written": True, "added": added, "skipped": new_skipped,
            "listing_error": listing_error, "missing": missing_pages()}


def _read_payload(path: str) -> Optional[Dict]:
    """A cache file as a dict, or None when it is not a usable reference."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            payload = json.load(fh)
    except (OSError, ValueError):
        return None
    pages = payload.get("pages") if isinstance(payload, dict) else None
    if not isinstance(pages, list) or not pages:
        return None
    if not all(isinstance(p, dict) and isinstance(p.get("sections"), list) for p in pages):
        return None
    return payload


def import_file(path: str, folder: Optional[str] = None) -> Dict:
    """Use a reference file (ms4x_wiki.json) copied from another computer."""
    payload = _read_payload(path)
    if payload is None:
        raise ValueError(t("This is not an MS4X Wiki reference file (ms4x_wiki.json)."))
    # Keep only what the reader understands; the file is data from elsewhere.
    clean = {
        "source": str(payload.get("source", "https://www.ms4x.net"))[:200],
        "note": "Local reference copy of the MS4X Wiki. Rights belong to the wiki authors.",
        "fetched": str(payload.get("fetched", "?"))[:40],
        "pages": [WikiPage.from_json(p).to_json() for p in payload["pages"]],
    }
    target = _write_cache(folder or user_dir(), clean)
    load(force=True)
    return {"path": target, "pages": len(clean["pages"])}


def export_file(path: str) -> int:
    """Save the reference in use to a file (to carry it to another computer)."""
    source = meta().get("folder")
    if not source:
        raise ValueError(t("The reference is not loaded."))
    with open(cache_path(source), "rb") as src, open(path, "wb") as dst:
        dst.write(src.read())
    return len(load())


_LOADED: Optional[List[WikiPage]] = None
_META: Dict = {}


def load(force: bool = False) -> List[WikiPage]:
    """Read the cache: the user one first, then the one shipped with the program."""
    global _LOADED, _META, _INDEX
    if _LOADED is not None and not force:
        return _LOADED
    for folder in (user_dir(), bundled_dir()):
        payload = _read_payload(cache_path(folder))
        if payload is None:
            continue                     # missing, broken or empty: try the next one
        _META = {k: v for k, v in payload.items() if k != "pages"}
        _META["folder"] = folder
        _LOADED = []
        seen = set()
        names = set(payload.get("aliases") or {})
        for raw in payload["pages"]:
            page = WikiPage.from_json(raw)
            names.add(page.name)
            body = _body(page)
            if body and body in seen:
                continue            # the same article under a second name (a redirect)
            seen.add(body)
            _LOADED.append(page)
        _META["names"] = sorted(names)
        _INDEX = None
        return _LOADED
    _LOADED = []
    _META = {}
    _INDEX = None
    return _LOADED


def meta() -> Dict:
    load()
    return _META


def expected_pages() -> List[str]:
    """The standard pages plus the MS43 pages found on the site at earlier updates."""
    aliases = meta().get("aliases") or {}
    extra = [n for n in meta().get("extra", []) if n not in DEFAULT_PAGES and n not in aliases]
    return list(DEFAULT_PAGES) + extra


def missing_pages() -> List[str]:
    """Expected pages the loaded reference lacks (empty = complete)."""
    load()
    have = set(_META.get("names", []))
    return [name for name in expected_pages() if name not in have]


def available() -> bool:
    return bool(load())


# ---------------------------------------------------------------------------
# Linking to XDF parameters
# ---------------------------------------------------------------------------

# Parameter names in wiki text: c_conf_cat, lc_swi_cal_mon_cks, ip_iga_...
_PARAM_RE = re.compile(r"\b((?:c|ip|id|ldp|ldpm|lc|cal|schw)_[a-z0-9_]{2,})\b")

_INDEX: Optional[Dict[str, List[Section]]] = None


def index_parameters() -> Dict[str, List[Section]]:
    """Parameter name -> wiki chunks that mention it."""
    global _INDEX
    if _INDEX is not None:
        return _INDEX
    index: Dict[str, List[Section]] = {}
    for page in load():
        for section in page.sections:
            for name in set(_PARAM_RE.findall(section.text)):
                bucket = index.setdefault(name, [])
                if section not in bucket:
                    bucket.append(section)
    _INDEX = index
    return index


def sections_for(title: str) -> List[Section]:
    """What the wiki says about a specific parameter."""
    if not title:
        return []
    index = index_parameters()
    found = list(index.get(title, []))
    if found:
        return found
    # for renamed parameters try the normalised name
    from .crossdiff import normalize_title

    normalized = normalize_title(title)
    for name, sections in index.items():
        if normalize_title(name) == normalized:
            for section in sections:
                if section not in found:
                    found.append(section)
    return found


_VALUE_LINE = re.compile(r"^\s*(-?\d+)\s*[:\)]\s*(.+?)\s*$")


# A line that DEFINES a parameter rather than just mentioning it:
# "Configuration switch - Lambda sensor configuration (c_conf_cat)"
# "id_maf_tab__v_maf_1__v_maf_2 - MAF sensor definition"
_DEFINES = re.compile(
    r"\((?P<paren>[a-z][a-z0-9_]*)\)\s*$|^(?P<lead>[a-z][a-z0-9_]{4,})\s*[-–—:]"
)


def _defined_name(line: str) -> Optional[str]:
    match = _DEFINES.search(line.strip())
    if not match:
        return None
    return match.group("paren") or match.group("lead")


def focused_text(section: "Section", title: str, after: int = 20) -> str:
    """Only the block about this parameter, without its neighbours.

    The "Switches" section describes two dozen switches in one chunk. Showing
    all of it for one parameter is exactly what confuses: the excerpt contains
    other names and other values. So we find the line that DEFINES the
    parameter and take everything up to the next definition.
    """
    lines = section.text.split("\n")

    start = None
    for i, line in enumerate(lines):
        if title in line and _defined_name(line) == title:
            start = i
            break
    if start is None:                       # no definition — take the mention
        for i, line in enumerate(lines):
            if title in line:
                start = i
                break
    if start is None:
        return section.text

    end = start + 1
    while end < len(lines) and end - start <= after:
        line = lines[end]
        other = _defined_name(line)
        if other and other != title:        # another parameter starts here
            break
        if title not in line and _VALUE_LINE.match(line) is None and not line.strip():
            end += 1
            continue
        end += 1
    return "\n".join(lines[start:end]).strip()


def value_meanings(title: str) -> Dict[int, str]:
    """What each switch value means, according to the wiki text.

    The wiki describes switches like this:

        Configuration switch - Lambda sensor configuration (c_conf_cat)
        0: Automatic variant learning — Single bank system …
        1: Automatic variant learning — Dual bank system …

    We take the enumeration lines right after the parameter is mentioned.
    This answers the question "it was 4, now it is 1 — what does that mean".
    """
    if not title:
        return {}
    out: Dict[int, str] = {}
    for section in sections_for(title):
        lines = section.text.split("\n")
        for idx, line in enumerate(lines):
            if title not in line:
                continue
            for follow in lines[idx + 1:]:
                match = _VALUE_LINE.match(follow)
                if not match:
                    # one empty/service line does not end the enumeration
                    if follow.strip():
                        break
                    continue
                out.setdefault(int(match.group(1)), match.group(2).strip())
            if out:
                return out
    return out


def procedure_for(title: str) -> List[str]:
    """What to do after changing the parameter (if the wiki says so)."""
    out: List[str] = []
    for section in sections_for(title):
        lines = section.text.split("\n")
        for idx, line in enumerate(lines):
            low = line.lower()
            if title.lower() in low and ("procedure" in low or "after chang" in low):
                for follow in lines[idx + 1:]:
                    if not follow.strip():
                        continue
                    if _VALUE_LINE.match(follow) or "configuration switch" in follow.lower():
                        break
                    out.append(follow.strip())
                    if len(out) >= 6:
                        break
        if out:
            break
    return out


def search(query: str, limit: int = 40) -> List[Section]:
    """Full-text search over the cache."""
    needle = (query or "").lower().strip()
    if not needle:
        return []
    words = [w for w in needle.split() if w]
    found: List[Tuple[int, Section]] = []
    seen = set()
    for page in load():
        for section in page.sections:
            if (section.heading, section.text) in seen:
                continue
            seen.add((section.heading, section.text))
            text = section.text.lower()
            heading = section.heading.lower()
            hits = [w for w in words if w in text or w in heading]
            if not hits:
                continue
            # many different query words and the words in the heading count most; a
            # glossary that repeats one word a hundred times must not win
            score = 10 * len(hits) + sum(min(text.count(w), 3) for w in hits)
            score += 6 * sum(1 for w in words if w in heading)
            if needle in heading:
                score += 30
            elif len(words) > 1 and needle in text:
                score += 15
            found.append((score, section))
    found.sort(key=lambda pair: -pair[0])
    return [section for _, section in found[:limit]]


def sections_by_heading(*headings: str) -> List[Section]:
    """Wiki sections by heading (exact substring, case-insensitive)."""
    wanted = [h.lower() for h in headings]
    out: List[Section] = []
    for page in load():
        for section in page.sections:
            low = section.heading.lower()
            if any(w in low for w in wanted):
                out.append(section)
    return out


def guidance_for_map(title: str) -> List[Section]:
    """What to read before editing a specific map.

    First the sections that name the map directly, then the wiki sections on
    the topic of what the map does.
    """
    found = list(sections_for(title))
    low = (title or "").lower()
    topics: List[str] = []
    if "_ve" in low or "_map_" in low or "maf" in low or "load" in low:
        topics += ["Engine Load", "Injection Load", "Mass Air Flow Sensor",
                   "Extending VO Tables", "Failsafe Mode"]
    if "iga" in low or "ign" in low:
        topics += ["Ignition Timing Maps", "Fuel Octane Adaptation",
                   "Knock Detection"]
    if "lam" in low or "_ti_" in low or low.startswith("ip_ti"):
        topics += ["Lambda Regulation", "Base Injection Maps",
                   "Full Load Enrichment", "Injector Duty Cycle"]
    if "cam" in low or "ivvt" in low:
        topics += ["VANOS Setpoint Maps", "Camshaft Parameters"]
    for section in sections_by_heading(*topics):
        if section not in found:
            found.append(section)
    return found


def cautions(page_name: Optional[str] = None) -> List[Section]:
    """All wiki warnings — "how not to break anything"."""
    out: List[Section] = []
    for page in load():
        if page_name and page.name != page_name and page.title != page_name:
            continue
        for section in page.sections:
            if section.is_caution:
                out.append(section)
    return out


def page_names() -> List[Tuple[str, str, int]]:
    """Pages in the cache: (name, title, number of sections)."""
    return [(p.name, p.title, len(p.sections)) for p in load()]


def page(name: str) -> Optional[WikiPage]:
    lowered = (name or "").lower().replace(" ", "_")
    for p in load():
        if p.name.lower() == lowered or p.title.lower() == name.lower():
            return p
    for p in load():
        if lowered in p.name.lower():
            return p
    return None
