# -*- coding: utf-8 -*-
"""
Справочник MS4X Wiki (https://www.ms4x.net) — «библия» этих прошивок.

Тут не копия сайта, а указатель: карта разделов с русскими пояснениями плюс
правило, какая страница относится к какому параметру или категории XDF.
Сам сайт живой и обновляется, поэтому осмысленно вести именно ссылки, а не
устаревающий слепок. Единственное, что взято оттуда целиком, — официальный
словарь сокращений (модуль keywords.py), потому что это справочная таблица,
без которой имена параметров не читаются.

Куда это встроено:
  * `ms43diff wiki` — список разделов и поиск по ним;
  * `ms43diff show` / GUI — под каждым параметром показываются ссылки на
    страницы, relevant для его категории;
  * `ms43diff wiki --open <тема>` — открыть страницу в браузере.
"""

from __future__ import annotations

import webbrowser
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence

BASE = "https://www.ms4x.net/index.php?title="
HOME = "https://www.ms4x.net/index.php?title=Main_Page"


def url(page: str) -> str:
    return BASE + page.replace(" ", "_")


@dataclass
class Page:
    title: str                       # как называется страница на вики
    ru: str                          # о чём она по-русски
    section: str                     # раздел вики
    tags: List[str] = field(default_factory=list)   # ключевые слова для поиска
    categories: List[str] = field(default_factory=list)  # категории XDF

    @property
    def url(self) -> str:
        return url(self.title)


# Структура сайта на 23.07.2026. Русские пояснения — наши.
PAGES: List[Page] = [
    # --- общее ---
    Page("First Steps And Requirements", "С чего начать: что нужно для работы с MS4x",
         "Общее", ["начало", "требования", "оборудование"]),
    Page("Siemens Keyword Translation",
         "Официальный словарь сокращений Siemens — расшифровка имён параметров",
         "Общее", ["сокращения", "словарь", "имена", "keyword"]),
    Page("How To Connect", "Как подключиться к блоку", "Общее",
         ["подключение", "кабель", "интерфейс", "k-line"]),
    Page("Live Tuning Options", "Живая правка прошивки на работающем моторе",
         "Общее", ["live", "онлайн", "тюнинг"]),

    # --- ЭБУ ---
    Page("Siemens MS43", "Главная страница по MS43: версии ПО, карта памяти, особенности",
         "ЭБУ", ["ms43", "прошивка", "память"],
         ["Software Version", "Checksums"]),
    Page("Siemens MS43X Custom Firmware",
         "Кастомная прошивка MS43X: что добавлено и как настраивается",
         "ЭБУ", ["ms43x", "кастом", "x001", "flex", "e85", "наддув"]),
    Page("Siemens MS43 CAN Bus", "Шина CAN в MS43: сообщения и их содержимое",
         "ЭБУ", ["can", "шина", "сообщения"], ["CAN"]),
    Page("Siemens MS43 PCB Components", "Компоненты платы MS43", "ЭБУ",
         ["плата", "компоненты", "ремонт"]),
    Page("Siemens MS43 Pinout", "Распиновка разъёмов MS43", "ЭБУ",
         ["распиновка", "разъём", "пины", "проводка"]),

    # --- логирование ---
    Page("TunerPro Data Logging", "Логирование через TunerPro: настройка и запуск",
         "Логирование", ["лог", "логирование", "tunerpro", "adx"]),
    Page("Logger.S", "Альтернативный логгер", "Логирование", ["лог", "логгер"]),

    # --- загрузки ---
    Page("Flashing Tools", "Программы для прошивки блока", "Загрузки",
         ["прошивальщик", "флеш", "bootmode"]),
    Page("Definition Files", "XDF-определения для всех версий ПО", "Загрузки",
         ["xdf", "определения", "definition"]),
    Page("Firmware Files", "Файлы прошивок", "Загрузки", ["прошивка", "bin", "firmware"]),
    Page("TunerPro MS43 Community Patchlist",
         "Патчлист сообщества для MS43: список патчей и что они делают",
         "Загрузки", ["патч", "patchlist", "ews", "иммобилайзер"]),

    # --- наддув и доработки ---
    Page("Siemens MS43 Extended Load Limit",
         "Снятие ограничения нагрузки — нужно при наддуве и мощном атмо",
         "Доработки", ["нагрузка", "предел", "наддув", "load"],
         ["Intake Model", "Airflow Meter", "Torque"]),
    Page("Siemens MS43 Retrofit MAP Sensor",
         "Установка датчика абсолютного давления (MAP) — база для speed-density",
         "Доработки", ["map", "давление", "speed density", "наполнение", "ve"],
         ["Intake Model", "Airflow Meter"]),
    Page("2048kg/h MAF Sensor Switch", "Переход на расходомер 2048 кг/ч",
         "Доработки", ["дмрв", "maf", "расходомер"], ["Airflow Meter"]),
    Page("Audi RS4 MAF Sensor Conversion", "Установка расходомера от Audi RS4",
         "Доработки", ["дмрв", "maf", "rs4"], ["Airflow Meter"]),
    Page("PMAS HPX MAF Sensor Conversion", "Установка расходомера PMAS HPX",
         "Доработки", ["дмрв", "maf", "pmas"], ["Airflow Meter"]),
    Page("Additional Analog Inputs For Logging With MS43",
         "Дополнительные аналоговые входы для логирования (сюда цепляют ШЛЗ)",
         "Доработки", ["ШЛЗ", "широкополосный", "wideband", "аналоговый", "вход"],
         ["Lambda Controller"]),
    Page("Use Rear O2 Inputs For Analog Sensors",
         "Использование входов задних лямбд под аналоговые датчики",
         "Доработки", ["ШЛЗ", "лямбда", "вход", "wideband"],
         ["Lambda Controller", "Catalyst"]),
    Page("B58 Ignition Coil Conversion", "Установка катушек от B58",
         "Доработки", ["катушки", "зажигание", "b58"], ["Ignition"]),
    Page("E46 Fuel Pressure Regulator Modification", "Доработка регулятора давления топлива",
         "Доработки", ["топливо", "давление", "рдт"], ["Fuel System"]),
    Page("M5x To N54 Intake Conversion", "Впуск от N54 на M5x",
         "Доработки", ["впуск", "коллектор", "n54"], ["Intake Air", "Intake Model"]),
    Page("M5x To S58 Intake Conversion", "Впуск от S58 на M5x",
         "Доработки", ["впуск", "коллектор", "s58"], ["Intake Air", "Intake Model"]),

    # --- прочее ---
    Page("Fuel Injector Deadtimes", "Мёртвое время форсунок — таблицы по моделям",
         "Прочее", ["форсунки", "мёртвое время", "deadtime", "впрыск"], ["Injection"]),
    Page("Aftermarket Upgrade Sensor Data", "Тарировки неоригинальных датчиков",
         "Прочее", ["датчик", "тарировка", "sensor"], ["Sensor Definitions"]),
    Page("CanTCU Integration (8HP/DCT Swaps)", "Интеграция CanTCU для свапа 8HP/DCT",
         "Прочее", ["акпп", "8hp", "dct", "cantcu"], ["AT-Gearbox", "CAN"]),
    Page("Bosch Cluster Shiftlight Retrofitting", "Шифтлайт в приборной панели Bosch",
         "Прочее", ["шифтлайт", "приборка"], ["Engine Speed"]),
    Page("Engine Wiring Harness Connectors", "Разъёмы моторной косы",
         "Прочее", ["коса", "разъём", "проводка"]),
    Page("3D Printable Parts", "Детали для 3D-печати", "Прочее", ["3d", "печать"]),
]

_BY_TITLE = {p.title.lower(): p for p in PAGES}


def sections() -> Dict[str, List[Page]]:
    out: Dict[str, List[Page]] = {}
    for page in PAGES:
        out.setdefault(page.section, []).append(page)
    return out


def search(query: str) -> List[Page]:
    """Найти страницы по русскому или английскому запросу."""
    needle = (query or "").lower().strip()
    if not needle:
        return list(PAGES)
    found = []
    for page in PAGES:
        haystack = " ".join([page.title, page.ru, page.section, *page.tags]).lower()
        if needle in haystack:
            found.append(page)
    return found


def pages_for_category(category: str) -> List[Page]:
    """Страницы вики, относящиеся к категории XDF (английское имя категории)."""
    return [p for p in PAGES if category in p.categories]


def pages_for_item(title: str, categories: Sequence[str]) -> List[Page]:
    """Что почитать по конкретному параметру."""
    found: List[Page] = []
    for category in categories:
        for page in pages_for_category(category):
            if page not in found:
                found.append(page)
    lowered = (title or "").lower()
    hints = {
        "maf": "Siemens MS43 Retrofit MAP Sensor",
        "map": "Siemens MS43 Retrofit MAP Sensor",
        "ve": "Siemens MS43 Retrofit MAP Sensor",
        "lam": "Additional Analog Inputs For Logging With MS43",
        "vls": "Use Rear O2 Inputs For Analog Sensors",
        "ti": "Fuel Injector Deadtimes",
        "iga": "B58 Ignition Coil Conversion",
    }
    for token, page_title in hints.items():
        if f"_{token}_" in lowered or lowered.startswith(f"{token}_"):
            page = _BY_TITLE.get(page_title.lower())
            if page and page not in found:
                found.append(page)
    return found


def open_in_browser(query: str) -> Optional[Page]:
    """Открыть подходящую страницу в браузере пользователя."""
    matches = search(query)
    if not matches:
        webbrowser.open(HOME)
        return None
    webbrowser.open(matches[0].url)
    return matches[0]
