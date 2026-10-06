# -*- coding: utf-8 -*-
"""
Локальный кэш MS4X Wiki — справочник, работающий без интернета.

Зачем: сайт ms4x.net у многих открывается только через VPN, а разбираться
в прошивке нужно за компьютером с TunerPro. Поэтому страницы выкачиваются
один раз и дальше читаются с диска.

Что делает модуль:
  * `download()` — тянет страницы и раскладывает их по разделам;
  * `load()` — читает кэш;
  * `index_parameters()` — автоматически связывает текст вики с именами
    параметров из XDF: вики пишет их прямо в тексте (c_conf_cat,
    lc_swi_cal_mon_cks и т.д.), поэтому для каждого параметра можно найти
    абзац, где он объясняется;
  * `cautions()` — собирает все блоки Warning/Note. Именно они отвечают на
    вопрос «как не убить ничего».

Содержимое кэша принадлежит авторам MS4X Wiki и хранится локально как
справочная копия; у каждого куска сохраняются название страницы и ссылка.

Сайт отдаёт 403 на запрос без узнаваемого User-Agent, поэтому он задаётся явно.
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

BASE = "https://www.ms4x.net/index.php?title="
USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")

# Страницы, которые имеет смысл держать офлайн. Порядок = порядок выкачки.
DEFAULT_PAGES: Tuple[str, ...] = (
    # Имена взяты из ссылок главной страницы вики — регистр и подчёркивания
    # там неочевидные («First_steps_and_requirements», «How_to_connect»).
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


def page_url(page: str) -> str:
    return BASE + urllib.parse.quote(page, safe="_/:")


# ---------------------------------------------------------------------------
# Разбор HTML
# ---------------------------------------------------------------------------

_SKIP_TAGS = {"script", "style", "sup", "table"}
_HEADINGS = {"h1", "h2", "h3", "h4", "h5", "h6"}


class _WikiParser(HTMLParser):
    """Выдёргивает из страницы MediaWiki заголовки, абзацы и списки.

    Таблицы пропускаем: в тексте они всё равно разваливаются, а нужные из них
    (карта памяти, адреса контрольных сумм) вынесены в KB вручную.
    """

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.blocks: List[Tuple[str, str]] = []   # (вид, текст)
        self._skip_depth = 0
        self._current: Optional[str] = None
        self._buf: List[str] = []
        self._in_content = False
        self._content_depth = 0
        self._div_depth = 0

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
        if tag in _HEADINGS or tag in ("p", "li", "dd", "dt"):
            self._flush()

    def handle_data(self, data):
        if self._in_content and not self._skip_depth and self._current:
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


@dataclass
class Section:
    heading: str
    text: str
    page: str
    url: str

    @property
    def caution_lines(self) -> List[str]:
        """Абзацы-предупреждения внутри раздела.

        Проверять весь раздел целиком бесполезно: «Warning:» стоит в середине,
        а не в начале, поэтому смотрим каждый абзац отдельно.
        """
        markers = ("warning", "note:", "caution", "important", "attention", "danger")
        phrases = ("not advised", "should be avoided", "may damage", "will damage",
                   "can damage", "do not ", "don't ", "never ", "at your own risk",
                   "be careful", "make sure", "won't start", "will not start",
                   "risk of", "otherwise the engine", "engine damage")
        out: List[str] = []
        for line in self.text.split("\n"):
            low = line.strip().lower()
            if not low:
                continue
            if low.startswith(markers) or any(p in low for p in phrases):
                out.append(line.strip())
        return out

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
    heading = "Общее"
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
# Хранилище
# ---------------------------------------------------------------------------


def bundled_dir() -> str:
    """Кэш, лежащий рядом с программой (уезжает вместе с .exe).

    В собранном PyInstaller-ом .exe файлы распаковываются во временную папку,
    путь к которой лежит в sys._MEIPASS.
    """
    import sys

    base = getattr(sys, "_MEIPASS", None)
    if base:
        packed = os.path.join(base, "ms43diff", "wikidata")
        if os.path.isdir(packed):
            return packed
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "wikidata")


def user_dir() -> str:
    """Кэш пользователя — сюда пишет обновление."""
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    return os.path.join(base, "ms43diff", "wiki")


def cache_path(folder: str) -> str:
    return os.path.join(folder, "ms4x_wiki.json")


def download(pages: Sequence[str] = DEFAULT_PAGES, folder: Optional[str] = None,
             progress=None, timeout: int = 30) -> Dict:
    """Скачать страницы в кэш. Возвращает сводку.

    Сайту нужен браузерный User-Agent, иначе он отвечает 403.
    """
    folder = folder or user_dir()
    os.makedirs(folder, exist_ok=True)
    collected: List[WikiPage] = []
    errors: List[Tuple[str, str]] = []
    for idx, name in enumerate(pages, 1):
        if progress:
            progress(idx, len(pages), name)
        request = urllib.request.Request(page_url(name),
                                         headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                raw = response.read()
        except (urllib.error.URLError, OSError) as exc:
            errors.append((name, str(exc)))
            continue
        try:
            html_text = raw.decode("utf-8", errors="replace")
            collected.append(parse_html(name, html_text))
        except Exception as exc:  # noqa: BLE001 - одна битая страница не должна ронять всё
            errors.append((name, f"разбор не удался: {exc}"))

    payload = {
        "source": "https://www.ms4x.net",
        "note": "Локальная справочная копия MS4X Wiki. Права — у авторов вики.",
        "fetched": time.strftime("%Y-%m-%d %H:%M"),
        "pages": [p.to_json() for p in collected],
    }
    with open(cache_path(folder), "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=1)
    return {"folder": folder, "pages": len(collected), "errors": errors,
            "path": cache_path(folder)}


_LOADED: Optional[List[WikiPage]] = None
_META: Dict = {}


def load(force: bool = False) -> List[WikiPage]:
    """Прочитать кэш: сперва пользовательский, потом поставляемый с программой."""
    global _LOADED, _META
    if _LOADED is not None and not force:
        return _LOADED
    for folder in (user_dir(), bundled_dir()):
        path = cache_path(folder)
        if not os.path.isfile(path):
            continue
        try:
            with open(path, "r", encoding="utf-8") as fh:
                payload = json.load(fh)
        except (OSError, ValueError):
            continue
        _META = {k: v for k, v in payload.items() if k != "pages"}
        _META["folder"] = folder
        _LOADED = [WikiPage.from_json(p) for p in payload.get("pages", [])]
        return _LOADED
    _LOADED = []
    _META = {}
    return _LOADED


def meta() -> Dict:
    load()
    return _META


def available() -> bool:
    return bool(load())


# ---------------------------------------------------------------------------
# Связь с параметрами XDF
# ---------------------------------------------------------------------------

# Имена параметров в тексте вики: c_conf_cat, lc_swi_cal_mon_cks, ip_iga_...
_PARAM_RE = re.compile(r"\b((?:c|ip|id|ldp|ldpm|lc|cal|schw)_[a-z0-9_]{2,})\b")

_INDEX: Optional[Dict[str, List[Section]]] = None


def index_parameters() -> Dict[str, List[Section]]:
    """Имя параметра -> куски вики, где он упоминается."""
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
    """Что вики пишет про конкретный параметр."""
    if not title:
        return []
    index = index_parameters()
    found = list(index.get(title, []))
    if found:
        return found
    # у переименованных параметров пробуем нормализованное имя
    from .crossdiff import normalize_title

    normalized = normalize_title(title)
    for name, sections in index.items():
        if normalize_title(name) == normalized:
            for section in sections:
                if section not in found:
                    found.append(section)
    return found


_VALUE_LINE = re.compile(r"^\s*(-?\d+)\s*[:\)]\s*(.+?)\s*$")


# Строка, которая ОПРЕДЕЛЯЕТ параметр, а не просто упоминает его:
# «Configuration switch - Lambda sensor configuration (c_conf_cat)»
# «id_maf_tab__v_maf_1__v_maf_2 - MAF sensor definition»
_DEFINES = re.compile(
    r"\((?P<paren>[a-z][a-z0-9_]*)\)\s*$|^(?P<lead>[a-z][a-z0-9_]{4,})\s*[-–—:]"
)


def _defined_name(line: str) -> Optional[str]:
    match = _DEFINES.search(line.strip())
    if not match:
        return None
    return match.group("paren") or match.group("lead")


def focused_text(section: "Section", title: str, after: int = 20) -> str:
    """Только блок про этот параметр, без соседних.

    Раздел «Switches» описывает подряд два десятка переключателей одним куском.
    Показывать его целиком ради одного параметра — именно то, что путает:
    в выдержке оказываются чужие имена и чужие значения. Поэтому ищем строку,
    которая параметр ОПРЕДЕЛЯЕТ, и берём от неё до определения следующего.
    """
    lines = section.text.split("\n")

    start = None
    for i, line in enumerate(lines):
        if title in line and _defined_name(line) == title:
            start = i
            break
    if start is None:                       # определения нет — берём упоминание
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
        if other and other != title:        # началось описание другого параметра
            break
        if title not in line and _VALUE_LINE.match(line) is None and not line.strip():
            end += 1
            continue
        end += 1
    return "\n".join(lines[start:end]).strip()


def value_meanings(title: str) -> Dict[int, str]:
    """Что означает каждое значение переключателя, по тексту вики.

    Вики описывает переключатели так:

        Configuration switch - Lambda sensor configuration (c_conf_cat)
        0: Automatic variant learning — Single bank system …
        1: Automatic variant learning — Dual bank system …

    Берём строки-перечисления, идущие сразу после упоминания параметра.
    Именно это отвечает на вопрос «было 4, стало 1 — и что это значит».
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
                    # одна пустая/служебная строка перечисление не обрывает
                    if follow.strip():
                        break
                    continue
                out.setdefault(int(match.group(1)), match.group(2).strip())
            if out:
                return out
    return out


def procedure_for(title: str) -> List[str]:
    """Что надо сделать после изменения параметра (если вики это описывает)."""
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
    """Полнотекстовый поиск по кэшу."""
    needle = (query or "").lower().strip()
    if not needle:
        return []
    words = [w for w in needle.split() if w]
    found: List[Tuple[int, Section]] = []
    for page in load():
        for section in page.sections:
            haystack = (section.heading + "\n" + section.text).lower()
            score = sum(haystack.count(w) for w in words)
            if score:
                if needle in section.heading.lower():
                    score += 20
                found.append((score, section))
    found.sort(key=lambda pair: -pair[0])
    return [section for _, section in found[:limit]]


def sections_by_heading(*headings: str) -> List[Section]:
    """Разделы вики по названию заголовка (точное вхождение, без регистра)."""
    wanted = [h.lower() for h in headings]
    out: List[Section] = []
    for page in load():
        for section in page.sections:
            low = section.heading.lower()
            if any(w in low for w in wanted):
                out.append(section)
    return out


def guidance_for_map(title: str) -> List[Section]:
    """Что почитать перед правкой конкретной карты.

    Сначала разделы, где карта названа прямо, потом тематические разделы
    вики по тому, что эта карта делает.
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
    """Все предупреждения из вики — «как не убить ничего»."""
    out: List[Section] = []
    for page in load():
        if page_name and page.name != page_name and page.title != page_name:
            continue
        for section in page.sections:
            if section.is_caution:
                out.append(section)
    return out


def page_names() -> List[Tuple[str, str, int]]:
    """Список страниц в кэше: (имя, заголовок, число разделов)."""
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
