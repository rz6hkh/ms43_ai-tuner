# -*- coding: utf-8 -*-
"""
Russian layer: decoding of XDF names, descriptions, categories and units.

Three levels of translation, from exact to approximate:

  1. PARAM_RU  — hand-verified explanations for the parameters that actually
                 get tuned on an MS43 (rev limit, ignition, MAF, VANOS...).
  2. TOKEN_RU  — expansion of abbreviations in the name. MS4x names are built
                 as <prefix>_<quantity>_<qualifiers>__<axis X>__<axis Y>,
                 e.g. ip_iga_ron_98_pl_ivvt__n__maf =
                 "ignition map, RON 98, part load, with VANOS, by rpm and air mass".
  3. WORD_RU / PHRASE_RU — word-by-word translation of English XDF descriptions.
                 Clumsy, but the meaning gets across; untranslated words stay in
                 Latin letters so it is visible where the translation is weak.

All abbreviation expansions were checked against descriptions inside the XDF
itself (e.g. puc -> "trailing throttle fuel cut-off", pste -> "power steering",
bol -> "bottom limit", ch -> "catalyst heating").

The Russian strings below are data (the Russian UI), not code comments.
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

from . import keywords

# ---------------------------------------------------------------------------
# TunerPro categories
# ---------------------------------------------------------------------------

CATEGORY_RU: Dict[str, str] = {
    "Axis": "Оси (опорные точки)",
    "Air Conditioner": "Кондиционер",
    "Airflow Meter": "ДМРВ (расходомер воздуха)",
    "Alternator": "Генератор",
    "Ambient Air": "Наружный воздух",
    "Anti Jerk": "Антирывковая функция",
    "AT-Gearbox": "АКПП",
    "Battery Voltage": "Напряжение бортсети",
    "CAN": "Шина CAN",
    "Canister Purge": "Продувка адсорбера",
    "Catalyst": "Катализатор",
    "Checksums": "Контрольные суммы",
    "Clutch Switch": "Датчик сцепления",
    "Config Switches": "Конфигурационные переключатели",
    "Coolant Fan": "Вентилятор охлаждения",
    "Coolant Temperature": "Температура охлаждающей жидкости",
    "Crankshaft": "Коленвал / датчик положения",
    "Cruise Control": "Круиз-контроль",
    "Diagnostic Trouble Codes": "Коды неисправностей (DTC)",
    "DISA": "DISA (изменяемая геометрия впуска)",
    "DMTL": "DMTL (диагностика утечек паров топлива)",
    "DTC Suppression": "Подавление кодов неисправностей",
    "Engine Speed": "Обороты двигателя",
    "Engine Start": "Пуск двигателя",
    "ESP": "ESP / DSC",
    "eThermostat": "Электротермостат",
    "EWS": "EWS (иммобилайзер)",
    "Exhaust Flap": "Заслонка выпуска",
    "Exhaust Gas Temperature": "Температура отработавших газов",
    "Fuel Pump": "Топливный насос",
    "Fuel System": "Топливная система",
    "Full Load Detection": "Определение полной нагрузки",
    "Gear Recognition": "Распознавание передачи",
    "Idle Speed": "Холостой ход",
    "Ignition": "Зажигание",
    "Injection": "Впрыск",
    "Intake Air": "Впускной воздух",
    "Intake Model": "Модель впуска",
    "Kilometer Counter": "Счётчик пробега",
    "Knock": "Детонация",
    "Lambda Controller": "Лямбда-регулирование",
    "Limp Home": "Аварийный режим",
    "Main Relay": "Главное реле",
    "Misfire": "Пропуски воспламенения",
    "OBD": "OBD",
    "Oil Temperature": "Температура масла",
    "Rough Road Detection": "Определение плохой дороги",
    "Secondary Air": "Система вторичного воздуха",
    "Sensor Definitions": "Тарировки датчиков",
    "Software Version": "Версия ПО",
    "Steering Wheel": "Рулевое колесо",
    "System Diagnosis": "Диагностика системы",
    "System Monitoring": "Мониторинг системы",
    "Throttle": "Дроссельная заслонка",
    "Timer": "Таймеры",
    "Torque": "Крутящий момент",
    "Torsion Correction": "Коррекция кручения коленвала",
    "Trailing Throttle Fuel Cut": "Отсечка топлива на сбросе газа (ПХХ)",
    "Vanos": "VANOS (фазовращатели)",
    "Warm Up": "Прогрев",
    "Vehicle Speed": "Скорость автомобиля",
    # patchlist categories
    "ECU Information": "Информация о блоке",
    "Immobilizer Bypass": "Отключение иммобилайзера (EWS)",
    "Checksum Bypass": "Отключение проверки контрольных сумм",
    "Launch Control Deprecated": "Launch Control (устаревший)",
    "M3/M5 Cluster LEDs": "Светодиоды приборки M3/M5",
    "DS2 Logging Extensions": "Расширенное логирование DS2",
    "MAF Sensor Hack": "Подмена сигнала ДМРВ",
    "Boost Control Over Canister Purge Output": "Управление наддувом через выход адсорбера",
    "Map Reduction": "Урезание карт",
}


# ---------------------------------------------------------------------------
# Units
# ---------------------------------------------------------------------------

UNIT_RU: Dict[str, str] = {
    "-": "",
    "rpm": "об/мин",
    "km/h": "км/ч",
    "kg/h": "кг/ч",
    "mg/stk": "мг/такт",
    "°C": "°C",
    "°CRK": "° к.в.",
    "°CRK/seg": "° к.в./сегмент",
    "°PVS": "° педали",
    "°TPS": "° дросселя",
    "°pste": "° руля",
    "°PVS/s": "° педали/с",
    "s": "с",
    "ms": "мс",
    "us": "мкс",
    "min": "мин",
    "%": "%",
    "%pwm": "% ШИМ",
    "%/10ms": "%/10 мс",
    "V": "В",
    "mV": "мВ",
    "A": "А",
    "mA": "мА",
    "Ah": "А·ч",
    "ohm": "Ом",
    "Nm": "Н·м",
    "hPa": "гПа",
    "km": "км",
    "L": "л",
    "g": "г",
    "m/s^2": "м/с²",
    "rpm/s": "об/мин·с",
    "rpm/10ms": "об/мин за 10 мс",
    "rpm/(km/h)": "об/мин на км/ч",
    "0.1s": "0,1 с",
    "*seg": "× сегмент",
    "OBDII P Code": "код OBD-II (P####)",
    "Gear": "передача",
    "gear": "передача",
    "%pwm ": "% ШИМ",
    "mg/hub": "мг/такт",
    "1/min": "об/мин",
}


def unit_ru(units: str) -> str:
    if not units:
        return ""
    key = units.strip()
    if key in UNIT_RU:
        return UNIT_RU[key]
    # junk units like "6", "8" occur in auto-generated XDFs
    if key.isdigit():
        return ""
    return key


# ---------------------------------------------------------------------------
# Abbreviations in parameter names
# ---------------------------------------------------------------------------

PREFIX_RU: Dict[str, Tuple[str, str]] = {
    # prefix -> (short label, explanation)
    # Expansions are taken from the official MS4x Wiki glossary:
    # ID — index table WITHOUT interpolation, IP — WITH interpolation.
    "c": ("КОНСТ", "калибровочная константа, правится в TunerPro"),
    "ip": ("КАРТА", "таблица С интерполяцией между точками"),
    "id": ("ТАБЛ", "таблица БЕЗ интерполяции (выбор по индексу)"),
    "ldp": ("ОСЬ", "список опорных точек — ось другой карты"),
    "ldpm": ("ОСЬ", "многократно используемый список опорных точек"),
    "lc": ("ПЕРЕКЛ", "логическая калибровочная константа (обычно 0/1)"),
    "cal": ("КС", "контрольная сумма калибровки"),
    "schw": ("ПОРОГ", "порог"),
    "t": ("ТАБЛ", "таблица"),
}

TOKEN_RU: Dict[str, str] = {
    # --- measured quantities ---
    "n": "обороты двигателя",
    "vs": "скорость автомобиля",
    "maf": "расход воздуха (нагрузка)",
    "hfm": "расходомер воздуха (HFM)",
    "tco": "температура ОЖ",
    "tia": "температура впускного воздуха",
    "toil": "температура масла",
    "tam": "температура наружного воздуха",
    "teg": "температура ОГ",
    "tmot": "температура двигателя",
    "temp": "температура",
    "amp": "атмосферное давление",
    "vb": "напряжение бортсети",
    "iga": "угол опережения зажигания",
    "igk": "зажигание (контроль)",
    "ign": "зажигание",
    "igc": "коррекция зажигания",
    "igcfb": "обратная связь коррекции зажигания",
    "ti": "время впрыска",
    "tq": "крутящий момент",
    "tqi": "индикаторный момент",
    "lam": "лямбда",
    "lamb": "лямбда",
    "ls": "лямбда-зонд",
    "lsh": "подогрев лямбда-зонда",
    "vls": "напряжение лямбда-зонда",
    "pvs": "положение педали газа",
    "tps": "положение дроссельной заслонки",
    "isa": "регулятор холостого хода",
    "isapwm": "ШИМ клапана холостого хода",
    "is": "холостой ход",
    "ecf": "вентилятор охлаждения",
    "ecfpwm": "ШИМ вентилятора охлаждения",
    "mtc": "управление главной дроссельной заслонкой",
    "mtcpwm": "ШИМ главной дроссельной заслонки",
    "cp": "продувка адсорбера",
    "cppwm": "ШИМ клапана продувки",
    "cps": "система продувки адсорбера",
    "dmtl": "диагностика утечек паров топлива",
    "sa": "вторичный воздух",
    "sap": "насос вторичного воздуха",
    "cat": "катализатор",
    "knk": "детонация",
    "ron": "октановое число",
    "cop": "защита катализатора от перегрева",
    "mis": "пропуски воспламенения",
    "er": "неравномерность вращения",
    "rr": "плохая дорога",
    "aj": "антирывковая функция",
    "cru": "круиз-контроль",
    "ews": "иммобилайзер EWS",
    "imob": "иммобилайзер",
    "ivvt": "VANOS",
    "cam": "распредвал",
    "vim": "изменяемая геометрия впуска (DISA)",
    "disa": "DISA",
    "vol": "объём",
    "im": "впускной коллектор",
    "gear": "передача",
    "gr": "передаточное отношение",
    "rax": "задняя ось",
    "km": "пробег",
    "ftl": "уровень топлива в баке",
    "fsd": "диагностика топливной системы",
    "accin": "компрессор кондиционера",
    "acr": "исполнительный механизм",
    "pste": "усилитель руля / датчик угла руля",
    "lws": "датчик угла поворота руля",
    "asr": "ASR (антипробуксовка)",
    "esp": "ESP / DSC",
    "obd": "OBD",
    "can": "шина CAN",
    "mil": "лампа Check Engine",
    "ef": "заслонка выпуска",
    "es": "остановка двигателя",
    "eru": "двигатель работает",
    "cs": "датчик сцепления",
    "ch": "прогрев катализатора",
    "dtc": "код неисправности",
    "abc": "счётчик неисправностей",
    "cyl": "цилиндр",
    "crk": "коленвал",
    "seg": "сегмент коленвала",
    "cyc": "цикл",
    "cycnr": "число циклов",
    "wall": "плёнка топлива на стенках",
    "eoi": "конец впрыска",
    "soi": "начало впрыска",
    "cast": "после холодного пуска",
    "cst": "холодный пуск",
    "st": "пуск",
    "ast": "после пуска",
    "wf": "плёнка топлива на стенках",
    "wuo": "прогрев",
    "dew": "точка росы",
    "mres": "резерв крутящего момента",
    "mdres": "резерв момента",
    "pow": "мощность",
    "nl": "генератор",
    "rly": "реле",
    "bts": "тест ламп/датчиков",
    "ssg": "SMG (роботизированная КПП)",
    "msr": "MSR (момент торможения двигателем)",
    "egs": "блок АКПП (EGS)",
    "clu": "сцепление",

    # --- modes and states ---
    # PL = part load, FL = full load (per the official MS4x glossary)
    "pl": "частичная нагрузка",
    "fl": "полная нагрузка",
    "puc": "отсечка топлива на сбросе газа (ПХХ)",
    "pu": "сброс газа / замедление",
    "dri": "селектор в Drive (АКПП)",
    "mt": "МКПП",
    "at": "АКПП",
    "amt": "роботизированная КПП (SMG/SSG)",
    "lih": "аварийный режим",
    "in": "впуск",
    "iv": "впускной клапан",
    "ex": "выпуск",
    "up": "верхний / до катализатора",
    "down": "нижний / после катализатора",
    "post": "после",
    "pre": "до",
    "tra": "переходный режим",
    "dyn": "динамический режим",
    "eol": "заводская настройка (конец конвейера)",
    "on": "включено",
    "off": "выключено",
    "state": "состояние",
    "act": "активно",
    "ready": "готовность",
    "req": "запрос",
    "conf": "конфигурация",
    "cnf": "конфигурация",
    "var": "вариант",
    "sw": "программное обеспечение",
    "msw": "переключатель режима",

    # --- maths and processing ---
    "max": "максимум",
    "min": "минимум",
    "sp": "уставка (заданное значение)",
    "tgt": "цель",
    "ref": "эталон",
    "av": "среднее",
    "mv": "среднее значение",
    "mmv": "скользящее среднее",
    "fil": "фильтр",
    "crlc": "константа фильтрации/корреляции",
    "fac": "коэффициент",
    "add": "прибавка",
    "sub": "вычитание",
    "ofs": "смещение",
    "cor": "коррекция",
    "corr": "коррекция",
    "ad": "адаптация",
    "inc": "приращение (увеличение)",
    "dec": "уменьшение",
    "grd": "градиент",
    "lgrd": "ограничение скорости изменения",
    "slop": "крутизна",
    "hys": "гистерезис",
    "thd": "порог",
    "lim": "ограничение",
    "ltc": "коррекция при переходной нагрузке",
    "dif": "разница",
    "sum": "сумма",
    "int": "интегральная часть",
    "i": "интегральная часть",
    "p": "пропорциональная часть",
    "d": "дифференциальная часть",
    "ctr": "счётчик",
    "ctl": "управление",
    "nr": "количество",
    "num": "количество",
    "ratio": "отношение",
    "perc": "процент",
    "bit": "бит",
    "chk": "проверка",
    "cks": "контрольная сумма",
    "crc": "CRC",
    "clc": "расчёт",
    "mod": "модификатор",
    "rpl": "восстановление на частичной нагрузке",
    "saf": "расход вторичного воздуха",
    "sav": "клапан вторичного воздуха",
    "sas": "аварийное отключение",
    "bol": "нижний предел",
    "tol": "верхний предел",
    "neg": "отрицательный",
    "pos": "положительный / позиция",
    "ducy": "скважность ШИМ",
    "pwm": "ШИМ",
    "v": "напряжение",
    "cur": "ток",
    "freq": "частота",
    "frq": "частота",
    "vel": "скорость изменения",
    "ang": "угол",
    "kgh": "кг/ч",
    "stk": "такт",
    "mec": "механический",
    "elc": "электрический",
    "mon": "мониторинг",
    "mon2": "мониторинг (2-й контур)",
    "diag": "диагностика",
    "plaus": "проверка достоверности",
    "dly": "задержка",
    "tout": "таймаут",
    "t": "время",
    "leak": "утечка",
    "loss": "потери",
    "ini": "инициализация",
    "rst": "сброс",
    "intr": "прерывание",
    "cdn": "условие",
    "cha": "заряд",
    "gp": "аварийная программа",
    "spi": "шина SPI",
    "tors": "торсионная коррекция коленвала",
    "ect": "электротермостат",
    "acin": "кондиционер включён",
    "etc": "электронный дроссель (EDK)",
    "edk": "электронный дроссель (EDK)",
    "dhp": "демпфер дросселя (dashpot)",
    "ena": "разрешить",
    "inh": "запретить",
    "actchk": "проверка исполнения",
    "deacc": "замедление",
    "rvl": "задний ход",
    "sif": "последовательный интерфейс",
    "afl": "бедная смесь",
    "afr": "богатая смесь",
    "afs": "стехиометрия",
    "ldp": "опорные точки",
    "idx": "индекс",
    "map": "давление во впуске (MAP)",
    "mes": "измеренное",
    "eu": "нормы Euro",
    "mpl": "многократный",
    "lsl": "широкополосный лямбда-зонд (ШЛЗ)",
    "vlsl": "напряжение широкополосного зонда",
    "ve": "коэффициент наполнения (VE)",
    "ff": "flex-fuel (датчик состава топлива)",
    "e85": "этанол E85",
    "bc": "управление наддувом",
    "lc": "launch control",
    "nls": "no-lift shift",
    "ral": "rolling anti-lag",
    "icl": "отсечка зажиганием",
}

# The official MS4x Wiki glossary fills the gaps: anything missing from our
# entries above comes from there. Our entries win only where an abbreviation
# has a narrower meaning in MS43 than in the general Siemens glossary.
_OFFICIAL = {token.lower(): translation for token, (_, translation) in keywords.KEYWORDS.items()}
for _token, _translation in _OFFICIAL.items():
    TOKEN_RU.setdefault(_token, _translation)

# Numeric suffixes that must not be translated
_NUMERIC = re.compile(r"^\d+$")


# ---------------------------------------------------------------------------
# Description translation: phrases first (longer ones first), then single words
# ---------------------------------------------------------------------------

PHRASE_RU: Dict[str, str] = {
    "trailing throttle fuel cut off": "отсечка топлива на сбросе газа (ПХХ)",
    "trailing throttle fuel cut-off": "отсечка топлива на сбросе газа (ПХХ)",
    "trailing throttle fuel cut": "отсечка топлива на сбросе газа (ПХХ)",
    "fault counter max limit": "предел счётчика ошибок",
    "fault counter increment": "шаг счётчика ошибок",
    "fault counter": "счётчик ошибок",
    "debounce counter": "счётчик подтверждения ошибки",
    "configuration switch": "конфигурационный переключатель",
    "engine speed threshold": "порог оборотов двигателя",
    "engine speed limitation": "ограничение оборотов двигателя",
    "engine speed limiter": "ограничитель оборотов (отсечка)",
    "engine speed limit": "ограничение оборотов",
    "engine speed hysteresis": "гистерезис по оборотам",
    "engine speed": "обороты двигателя",
    "vehicle speed limitation": "ограничение скорости автомобиля",
    "vehicle speed": "скорость автомобиля",
    "idle speed": "обороты холостого хода",
    "coolant temperature": "температура охлаждающей жидкости",
    "intake air temperature": "температура впускного воздуха",
    "ambient air temperature": "температура наружного воздуха",
    "ambient temperature": "температура наружного воздуха",
    "exhaust gas temperature": "температура отработавших газов",
    "oil temperature": "температура масла",
    "catalyst temperature": "температура катализатора",
    "substitute temperature": "замещающая температура",
    "radiator outlet": "выход радиатора",
    "accelerator pedal": "педаль газа",
    "brake pedal": "педаль тормоза",
    "throttle position": "положение дроссельной заслонки",
    "throttle plate": "дроссельная заслонка",
    "throttle dashpot": "демпфер дроссельной заслонки",
    "ignition angle correction": "коррекция угла опережения зажигания",
    "ignition angle": "угол опережения зажигания",
    "ignition advance": "опережение зажигания",
    "ignition retard": "запаздывание зажигания",
    "spark advance": "опережение зажигания",
    "dwell time": "время накопления в катушке",
    "injection time": "время впрыска",
    "start of injection": "начало впрыска",
    "duty cycle": "скважность ШИМ",
    "upstream lambda sensor": "верхний лямбда-зонд (до катализатора)",
    "downstream lambda sensor": "нижний лямбда-зонд (после катализатора)",
    "post cat lambda sensor": "лямбда-зонд после катализатора",
    "precat lambda sensor": "лямбда-зонд до катализатора",
    "lambda sensor heater": "подогрев лямбда-зонда",
    "lambda sensor voltage": "напряжение лямбда-зонда",
    "lambda sensor": "лямбда-зонд",
    "lambda controller": "лямбда-регулятор",
    "knock detection": "обнаружение детонации",
    "knock control": "контроль детонации",
    "knock intensity": "интенсивность детонации",
    "misfire detection": "обнаружение пропусков воспламенения",
    "canister purge valve": "клапан продувки адсорбера",
    "canister purge": "продувка адсорбера",
    "secondary air": "вторичный воздух",
    "intake camshaft": "впускной распредвал",
    "exhaust camshaft": "выпускной распредвал",
    "intake manifold": "впускной коллектор",
    "camshaft": "распредвал",
    "electric coolant fan": "электровентилятор охлаждения",
    "electric coolant thermostat": "электротермостат",
    "coolant fan": "вентилятор охлаждения",
    "manual transmission": "МКПП",
    "automatic transmission": "АКПП",
    "automated manual transmission": "роботизированная КПП (SMG)",
    "cruise control": "круиз-контроль",
    "full load": "полная нагрузка",
    "part load": "частичная нагрузка",
    "indicated engine torque": "индикаторный крутящий момент",
    "engine torque": "крутящий момент двигателя",
    "torque reserve": "резерв крутящего момента",
    "rough road": "плохая дорога",
    "anti-jerk": "антирывковая функция",
    "anti jerk": "антирывковая функция",
    "limp home": "аварийный режим",
    "instrument cluster": "приборная панель",
    "fuel tank level": "уровень топлива в баке",
    "fuel system": "топливная система",
    "air condition compressor": "компрессор кондиционера",
    "air conditioner": "кондиционер",
    "battery voltage": "напряжение бортсети",
    "main relay": "главное реле",
    "catalyst overheating": "перегрев катализатора",
    "catalyst heating": "прогрев катализатора",
    "wall film": "плёнка топлива на стенках",
    "engine start": "пуск двигателя",
    "engine stop": "остановка двигателя",
    "gear shift": "переключение передачи",
    "gear recognition": "распознавание передачи",
    "rear axle ratio": "передаточное отношение главной пары",
    "gearbox gears": "передачи КПП",
    "drive engaged": "селектор в положении Drive",
    "drive-off-support": "помощь при трогании",
    "system monitoring": "мониторинг системы",
    "system diagnostics": "диагностика системы",
    "system diagnosis": "диагностика системы",
    "plausibility check": "проверка достоверности",
    "moving mean value": "скользящее среднее",
    "correlation constant": "константа фильтрации (корреляции)",
    "correlation factor": "коэффициент фильтрации",
    "weighting factor": "весовой коэффициент",
    "multiplicative factor": "мультипликативный коэффициент",
    "additive factor": "аддитивная поправка",
    "gradient limitation": "ограничение скорости изменения",
    "time delay": "задержка по времени",
    "dead time": "мёртвое время",
    "steering wheel": "рулевое колесо",
    "power steering": "усилитель руля",
    "cylinder shut-off": "отключение цилиндра",
    "cylinders shut-off": "отключение цилиндров",
    "fuel shut-off": "отсечка топлива",
    "fuel cut": "отсечка топлива",
    "shut off": "отключение",
    "cold condition": "на холодном двигателе",
    "operating conditions": "рабочие условия",
    "application condition": "условие применения",
    "reference conditions": "эталонные условия",
    "valve overlap": "перекрытие клапанов",
    "checksum": "контрольная сумма",
    "kilometer counter": "счётчик пробега",
    "adaptation": "адаптация",
    "readiness": "готовность (Readiness)",
    "does not seem to be implemented in the code": "судя по коду, не используется",
    "doesn't seem to be implemented in the code": "судя по коду, не используется",
    "does not seem to be used in the code": "судя по коду, не используется",
    "seem to be": "похоже,",
    "in case of": "в случае",
    "versus": "в зависимости от",
    "vs.": "в зависимости от",
    "out of": "вне",
    "based on": "на основе",
    "ron98": "бензин RON98 (≈АИ-98)",
    "ron 98": "бензин RON98 (≈АИ-98)",
    "ron91": "бензин RON91 (≈АИ-92)",
    "ron 91": "бензин RON91 (≈АИ-92)",
    "part and full load": "частичная и полная нагрузка",
    "this patch": "этот патч",
    "launch control": "Launch Control (старт с оборотов)",
    "rolling anti lag": "Rolling Anti-Lag (антилаг с хода)",
    "anti lag": "антилаг",
    "boot mode": "режим bootmode",
    "can bus": "шина CAN",
    "can output": "выход на шину CAN",
    "can message": "сообщение шины CAN",
    "vehicle speed sensor": "датчик скорости автомобиля",
    "at your own risk": "на свой страх и риск",
    "use only with": "использовать только с",
    "engine speed sensor": "датчик оборотов двигателя",
    "rear differential": "задний редуктор",
    "ignition coil": "катушка зажигания",
    "hard limiter": "жёсткий ограничитель",
    "soft limiter": "мягкий ограничитель",
    "warm engine": "прогретый двигатель",
    "cold engine": "холодный двигатель",
}

WORD_RU: Dict[str, str] = {
    "a": "", "an": "", "the": "", "of": "", "for": "для", "to": "до", "in": "в",
    "at": "при", "on": "при", "off": "выкл", "and": "и", "or": "или", "is": "—",
    "are": "—", "be": "быть", "with": "с", "without": "без", "by": "по",
    "from": "от", "during": "во время", "before": "до", "after": "после",
    "when": "когда", "while": "пока", "if": "если", "which": "который",
    "that": "который", "this": "этот", "those": "те", "there": "там",
    "has": "имеет", "have": "иметь", "been": "было", "will": "будет",
    "not": "не", "no": "нет", "than": "чем", "as": "как", "any": "любой",
    "all": "все", "one": "один", "two": "два", "three": "три", "second": "второй",
    "third": "третий", "fourth": "четвёртый", "forth": "четвёртый",
    "fifth": "пятый", "first": "первый", "last": "последний", "new": "новый",
    "old": "старый", "own": "собственный", "your": "ваш", "so": "поэтому",
    "only": "только", "once": "однократно", "each": "каждый", "per": "на",
    "over": "свыше", "under": "ниже", "above": "выше", "below": "ниже",
    "between": "между", "near": "около", "until": "до", "due": "из-за",
    "either": "либо", "also": "также", "e": "", "g": "",

    "engine": "двигатель", "speed": "обороты", "vehicle": "автомобиль",
    "temperature": "температура", "temperatures": "температуры",
    "coolant": "ОЖ", "oil": "масло", "air": "воздух", "ambient": "наружный",
    "intake": "впускной", "exhaust": "выпускной", "gas": "газ",
    "fuel": "топливо", "tank": "бак", "level": "уровень", "pump": "насос",
    "injector": "форсунка", "injectors": "форсунки", "injection": "впрыск",
    "ignition": "зажигание", "spark": "искра", "coils": "катушки",
    "angle": "угол", "advance": "опережение", "retard": "запаздывание",
    "retardation": "запаздывание", "degrees": "градусы",
    "throttle": "дроссель", "pedal": "педаль", "accelerator": "газ",
    "brake": "тормоз", "braking": "торможение", "clutch": "сцепление",
    "gear": "передача", "gears": "передачи", "gearbox": "КПП",
    "transmission": "КПП", "manual": "механическая", "automatic": "автоматическая",
    "automated": "роботизированная", "neutral": "нейтраль", "reverse": "задний ход",
    "drive": "движение", "driving": "движение", "shift": "переключение",
    "lock": "блокировка", "lockup": "блокировка гидротрансформатора",
    "locking": "блокировка", "converter": "гидротрансформатор",
    "clutch": "сцепление", "axle": "ось", "rear": "задний", "wheel": "колесо",
    "differential": "дифференциал", "ratio": "отношение",

    "lambda": "лямбда", "sensor": "датчик", "sensors": "датчики",
    "voltage": "напряжение", "current": "ток", "resistance": "сопротивление",
    "battery": "аккумулятор", "alternator": "генератор", "relay": "реле",
    "signal": "сигнал", "input": "вход", "output": "выход",
    "heater": "подогреватель", "heating": "подогрев", "heat": "тепло",
    "upstream": "до катализатора", "downstream": "после катализатора",
    "precat": "до катализатора", "postcat": "после катализатора",
    "post": "после", "pre": "до", "bank": "банк",
    "catalyst": "катализатор", "cat": "катализатор", "converter": "нейтрализатор",
    "emission": "выбросы", "emissions": "выбросы", "mixture": "смесь",
    "rich": "богатая", "lean": "бедная", "enrichment": "обогащение",
    "combustion": "сгорание", "misfire": "пропуск воспламенения",
    "cylinder": "цилиндр", "cylinders": "цилиндры", "cyl": "цилиндр",
    "crankshaft": "коленвал", "camshaft": "распредвал", "cam": "распредвал",
    "vanos": "VANOS", "valve": "клапан", "overlap": "перекрытие",
    "manifold": "коллектор", "flap": "заслонка", "volume": "объём",
    "flow": "расход", "mass": "масса", "load": "нагрузка", "charge": "наполнение",
    "pressure": "давление", "barometric": "барометрическое",
    "vacuum": "разрежение", "boost": "наддув",

    "knock": "детонация", "lnock": "детонация", "intensity": "интенсивность",
    "detection": "обнаружение", "detect": "обнаружить", "detected": "обнаружено",
    "detecting": "обнаружение", "recognition": "распознавание",
    "window": "окно", "beginning": "начало", "end": "конец",
    "threshold": "порог", "thresholds": "пороги", "limit": "предел",
    "limitation": "ограничение", "limited": "ограничено", "limiting": "ограничение",
    "limiter": "ограничитель", "max": "макс.", "maximum": "максимальный",
    "maximim": "максимальный", "min": "мин.", "minimum": "минимальный",
    "hysteresis": "гистерезис", "range": "диапазон", "tol": "допуск",
    "offset": "смещение", "factor": "коэффициент", "gain": "усиление",
    "multiplier": "множитель", "multiplicative": "мультипликативный",
    "additive": "аддитивный", "correction": "коррекция", "corr": "коррекция",
    "compensation": "компенсация", "adaptation": "адаптация",
    "adaptative": "адаптивный", "adaptive": "адаптивный", "learn": "обучение",
    "learning": "обучение", "trim": "коррекция", "modifier": "модификатор",
    "increment": "приращение", "incrementation": "приращение",
    "decrement": "уменьшение", "decrementation": "уменьшение",
    "increase": "увеличение", "increasing": "растущий",
    "decrease": "уменьшение", "decreasing": "падающий",
    "gradient": "градиент", "slope": "крутизна", "ramp": "нарастание",
    "delay": "задержка", "duration": "длительность", "period": "период",
    "time": "время", "timeout": "таймаут", "timer": "таймер",
    "counter": "счётчик", "count": "количество", "number": "количество",
    "cycle": "цикл", "cycles": "циклы", "segment": "сегмент",
    "tooth": "зуб", "teeth": "зубья", "cog": "зуб",

    "idle": "холостой ход", "idlespeed": "обороты холостого хода",
    "start": "пуск", "starting": "пуск", "restart": "перезапуск",
    "cranking": "прокрутка стартером", "stop": "остановка",
    "stopped": "остановлен", "stopping": "остановка", "running": "работа",
    "warm": "прогрев", "warming": "прогрев", "cold": "холодный",
    "hot": "горячий", "overheating": "перегрев", "overtemperature": "перегрев",
    "cooling": "охлаждение", "fan": "вентилятор", "thermostat": "термостат",
    "radiator": "радиатор", "outlet": "выход", "electric": "электрический",
    "electrical": "электрический", "elctrical": "электрический",

    "diagnosis": "диагностика", "diagnostics": "диагностика",
    "diagnostis": "диагностика", "diagnostic": "диагностический",
    "monitoring": "мониторинг", "monitor": "мониторинг",
    "plausibility": "достоверность", "plausibillity": "достоверность",
    "plausible": "достоверный", "implausible": "недостоверный",
    "implausibility": "недостоверность", "plausiblization": "проверка достоверности",
    "fault": "ошибка", "faulty": "неисправный", "error": "ошибка",
    "errors": "ошибки", "failure": "отказ", "malfunction": "неисправность",
    "malfunctioning": "неисправность", "code": "код", "codes": "коды",
    "check": "проверка", "test": "тест", "testing": "тестирование",
    "criteria": "критерий", "criterias": "критерии", "condition": "условие",
    "conditions": "условия", "state": "состояние", "status": "статус",
    "event": "событие", "debounce": "подтверждение",

    "control": "управление", "controller": "регулятор", "regulation": "регулирование",
    "setpoint": "уставка", "setpoints": "уставки", "target": "целевой",
    "desired": "заданный", "nominal": "номинальный", "actual": "фактический",
    "reference": "эталонный", "references": "эталоны", "basic": "базовый",
    "basis": "база", "standard": "стандартный", "default": "по умолчанию",
    "value": "значение", "values": "значения", "raw": "сырой",
    "calculated": "расчётный", "calculation": "расчёт", "calculations": "расчёты",
    "calculate": "рассчитать", "model": "модель", "map": "карта",
    "table": "таблица", "tables": "таблицы", "definition": "описание",
    "characteristic": "характеристика", "curve": "кривая",
    "linearization": "линеаризация", "normalization": "нормирование",
    "normalisation": "нормирование", "conversion": "пересчёт",
    "scale": "масштаб", "weighting": "взвешивание", "weight": "вес",
    "blend": "смешивание", "blending": "смешивание", "filter": "фильтр",
    "filtering": "фильтрация", "floating": "плавающий", "averaging": "усреднение",
    "mean": "среднее", "average": "среднее", "integral": "интегральный",
    "proportional": "пропорциональный", "derivative": "дифференциальный",
    "loop": "контур", "feedback": "обратная связь",

    "activation": "активация", "activate": "включить", "activated": "включено",
    "activating": "включение", "activations": "включения",
    "deactivation": "отключение", "deactivate": "отключить",
    "disable": "отключить", "disabling": "отключение", "enable": "включить",
    "enabled": "включено", "enabling": "включение", "inactive": "неактивно",
    "active": "активно", "switch": "переключатель", "switching": "переключение",
    "switched": "переключено", "toggle": "переключение", "select": "выбор",
    "selected": "выбранный", "choice": "выбор", "mode": "режим",
    "phase": "фаза", "phases": "фазы", "stage": "ступень", "step": "шаг",
    "transition": "переход", "intermediate": "промежуточный",
    "initialization": "инициализация", "initialisation": "инициализация",
    "intialization": "инициализация", "initialized": "инициализировано",
    "reset": "сброс", "update": "обновление", "updating": "обновление",
    "abort": "прерывание", "interrupt": "прерывание", "cancelling": "отмена",
    "prevention": "предотвращение", "prevent": "предотвратить",
    "avoid": "избежать", "protection": "защита", "safety": "безопасность",
    "substitute": "замещающий", "subsitute": "замещающий",
    "substitue": "замещающий", "replacement": "замещение",

    "full": "полный", "part": "часть", "partial": "частичный",
    "total": "суммарный", "sum": "сумма", "difference": "разница",
    "deviation": "отклонение", "drift": "уход", "variation": "разброс",
    "share": "доля", "percentage": "процент", "relative": "относительный",
    "absolute": "абсолютный", "positive": "положительный",
    "negative": "отрицательный", "upper": "верхний", "lower": "нижний",
    "bottom": "нижний", "top": "верхний", "high": "высокий", "low": "низкий",
    "higher": "выше", "greater": "больше", "short": "короткий",
    "long": "длинный", "fast": "быстрый", "rapid": "быстрый", "slow": "медленный",
    "smooth": "плавный", "hard": "жёсткий", "soft": "мягкий",
    "strong": "сильный", "weak": "слабый", "weakening": "ослабление",
    "dynamic": "динамический", "dynmic": "динамический", "dynamics": "динамика",
    "steady": "установившийся", "stationary": "неподвижный",
    "instationary": "переходный", "stabilisation": "стабилизация",
    "acceleration": "ускорение", "deceleration": "замедление",
    "velocity": "скорость изменения", "friction": "трение",
    "efficiency": "КПД", "power": "мощность", "torque": "крутящий момент",
    "indicated": "индикаторный", "loss": "потери", "consumption": "расход",
    "demand": "потребность", "request": "запрос", "required": "требуемый",
    "allowed": "допустимый", "permitted": "разрешённый", "exceeded": "превышен",
    "overrevving": "перекрут", "overflow": "переполнение",
    "cut": "отсечка", "cutoff": "отсечка", "shut": "отключение",
    "opening": "открытие", "open": "открыт", "opened": "открыт",
    "closing": "закрытие", "close": "закрыть", "position": "положение",
    "postion": "положение", "point": "точка", "width": "ширина",
    "amount": "величина", "amplitude": "амплитуда",
    "amplification": "усиление", "amplifier": "усилитель",
    "modulation": "модуляция", "pulse": "импульс", "frequency": "частота",
    "duty": "скважность", "dwell": "накопление",

    "system": "система", "systems": "системы", "component": "компонент",
    "module": "модуль", "unit": "блок", "ecu": "блок управления",
    "device": "устройство", "interface": "интерфейс", "bus": "шина",
    "can": "CAN", "message": "сообщение", "messages": "сообщения",
    "communication": "связь", "transmitting": "передача",
    "sending": "отправка", "received": "принято", "data": "данные",
    "parameter": "параметр", "parameters": "параметры", "file": "файл",
    "section": "секция", "area": "область", "channel": "канал",
    "serial": "последовательный", "programming": "программирование",
    "access": "доступ", "write": "запись", "read": "чтение",
    "memory": "память", "latch": "фиксация", "sync": "синхронизация",
    "synchronization": "синхронизация", "identification": "идентификация",
    "indentification": "идентификация", "self": "само",
    "cluster": "приборная панель", "instrument": "приборный",
    "instr": "приборный", "guage": "указатель", "indicator": "индикатор",
    "warning": "предупреждение", "light": "лампа", "led": "светодиод",
    "steering": "рулевое управление", "stering": "рулевое управление",
    "compressor": "компрессор", "conditioner": "кондиционер",
    "conditioning": "кондиционирование", "ac": "кондиционер",
    "secondary": "вторичный", "canister": "адсорбер", "purge": "продувка",
    "evaporative": "испарения", "carb": "нормы CARB", "leakage": "утечка",
    "leak": "утечка", "cap": "крышка", "filler": "заливная горловина",
    "immobilizer": "иммобилайзер", "auth": "авторизация", "key": "ключ",
    "crash": "авария", "road": "дорога", "rough": "неровный",
    "noise": "шум", "adhesion": "сцепление с дорогой",
    "jerk": "рывок", "anti": "анти", "dashpot": "демпфер",
    "support": "поддержка", "home": "дом", "limp": "аварийный",
    "solenoid": "электромагнитный клапан", "actuator": "исполнительный механизм",
    "mechanical": "механический", "pencil": "карандашного типа",
    "style": "тип", "twin": "сдвоенный", "single": "одиночный",
    "multi": "много", "multifunction": "многофункциональный",
    "variable": "переменный", "variant": "вариант", "variants": "варианты",
    "constant": "константа", "gradual": "постепенный", "direct": "прямой",
    "direction": "направление", "forward": "вперёд", "back": "назад",
    "rotation": "вращение", "aided": "с помощью", "assisted": "с помощью",
    "operation": "работа", "operating": "рабочий", "function": "функция",
    "capability": "возможность", "used": "используется", "use": "использовать",
    "applied": "применено", "application": "применение", "implemented": "реализовано",
    "seem": "похоже", "does": "", "doesn": "не", "risk": "риск",
    "result": "результат", "resulting": "результирующий",
    "response": "отклик", "decay": "затухание", "energization": "запитывание",
    "preparation": "подготовка", "predrive": "предварительный привод",
    "supply": "питание", "ground": "масса", "feed": "подача",
    "draw": "потребление", "reduction": "снижение", "intervention": "вмешательство",
    "triggering": "срабатывание", "jump": "скачок", "drop": "провал",
    "missing": "отсутствующий", "rest": "остаток", "free": "свободный",
    "fully": "полностью", "met": "выполнено", "moving": "скользящий",
    "optimal": "оптимальный", "normal": "нормальный", "effective": "эффективный",
    "dependent": "зависящий", "depending": "в зависимости", "regarding": "относительно",
    "according": "согласно", "determine": "определить", "represent": "представляет",
    "complies": "соответствует", "changes": "изменения", "change": "изменение",
    "renewed": "повторный", "acquired": "полученный", "maintained": "поддерживается",
    "achieve": "достичь", "reach": "достичь", "stays": "остаётся",
    "away": "прочь", "towards": "к", "translation": "пересчёт",
    "intercept": "смещение", "perform": "выполнить", "external": "внешний",
    "firmware": "прошивка", "autogenerated": "автосгенерировано",
    "contain": "содержать", "could": "может", "obd": "OBD", "eobd": "EOBD",
    "mil": "лампа Check Engine", "dtc": "код неисправности",
    "asc": "ASC (антипробуксовка)", "asr": "ASR (антипробуксовка)",
    "esp": "ESP/DSC", "dsc": "DSC", "abs": "ABS", "egs": "блок АКПП",
    "ssg": "SMG", "msr": "MSR", "ews": "EWS (иммобилайзер)",
    "disa": "DISA", "dmtl": "DMTL", "maf": "расход воздуха",
    "tps": "положение дросселя", "pvs": "положение педали",
    "iga": "УОЗ", "ti": "время впрыска", "tco": "температура ОЖ",
    "tia": "температура впускного воздуха", "toil": "температура масла",
    "tam": "температура наружного воздуха", "teg": "температура ОГ",
    "lam": "лямбда", "vls": "напряжение лямбда-зонда", "ron": "октановое число",
    "sp": "уставка", "mv": "среднее", "mmv": "скользящее среднее",
    "fac": "коэффициент", "dif": "разница", "cor": "коррекция",
    "ad": "адаптация", "st": "пуск", "ast": "после пуска",
    "ex": "выпуск", "iv": "впуск", "pl": "полная нагрузка", "fl": "полная нагрузка",
    "cp": "продувка адсорбера", "sa": "вторичный воздух", "cat": "катализатор",
    "cop": "защита катализатора", "ecf": "вентилятор охлаждения",
    "ect": "электронный дроссель", "ef": "заслонка выпуска",
    "ivvt": "VANOS", "lgrd": "ограничение градиента", "thd": "порог",
    "ctr": "счётчик", "ctl": "управление", "lv": "уровень", "ls": "лямбда-зонд",
    "lim": "предел", "conf": "конфигурация", "diag": "диагностика",
    "mon": "мониторинг", "puc": "ПХХ с отсечкой", "pu": "сброс газа",
    "tra": "переходный режим", "saf": "безопасность", "bol": "нижний предел",
    "accin": "компрессор кондиционера", "fsd": "диагностика топливной системы",
    "ftl": "уровень топлива", "crlc": "константа фильтрации",
    "cps": "система продувки", "isapwm": "ШИМ клапана ХХ", "cppwm": "ШИМ продувки",
    "add": "прибавка", "sub": "вычитание", "vo": "напряжение",
    "ip": "карта", "xdf": "XDF", "crc": "CRC", "ii": "II",
    "eu": "Euro", "cc": "круиз-контроль", "cs": "помощь при трогании",
    "lws": "датчик угла руля", "dft": "отклонение", "ign": "зажигание",
    "sta": "стартер", "sec": "с", "ms": "мс", "tq": "момент",
    "perc": "процент", "temp": "температура", "amp": "атмосферное давление",
    "vs": "скорость автомобиля", "tmot": "температура двигателя",
    "igk": "зажигание", "clu": "сцепление", "rly": "реле",
    "stb": "резерв", "crp": "прокрутка", "inf": "информация",
    "dri": "селектор Drive", "amt": "SMG", "lt": "долговременный",
    "de": "де", "re": "повторно", "xc": "", "xbf": "", "xaf": "", "xbd": "",
    "gt": "больше", "siemens": "Siemens", "infineon": "Infineon",
    "motorola": "Motorola", "asic": "ASIC", "bit": "бит",
    "mres": "резерв момента", "pste": "усилитель руля", "sap": "насос вторичного воздуха",
    "er": "неравномерность вращения", "rr": "плохая дорога",
    "aj": "антирывковая функция", "cru": "круиз-контроль", "es": "пуск двигателя",
    "ch": "прогрев катализатора", "wf": "прогрев", "seg": "сегмент",
    "km": "км", "kg": "кг", "mg": "мг", "nm": "Н·м", "hpa": "гПа",
    "rpm": "об/мин", "vim": "DISA", "vol": "объём", "im": "впускной коллектор",

    # words used in patch descriptions
    "patch": "патч", "patches": "патчи", "implements": "реализует",
    "implement": "реализовать", "feature": "функция", "features": "функции",
    "you": "вы", "yours": "ваш", "want": "хотите", "need": "нужно",
    "may": "может", "can": "может", "should": "следует", "must": "должен",
    "where": "где", "instead": "вместо", "chose": "выбирается",
    "choose": "выбрать", "still": "по-прежнему", "green": "зелёный",
    "handy": "удобно", "install": "установить", "into": "в",
    "keep": "сохранить", "older": "более старых", "more": "более",
    "accurate": "точный", "make": "сделать", "skip": "пропустить",
    "division": "деление", "located": "расположенный", "inside": "внутри",
    "impulses": "импульсов", "kilometer": "километр", "coil": "катушка",
    "zero": "ноль", "whole": "весь", "sprocket": "звёздочка",
    "center": "центральный", "unless": "если только не",
    "encounter": "столкнётесь", "crank": "прокручиваться",
    "flash": "прошить", "flashed": "прошито", "previously": "ранее",
    "binary": "файл прошивки", "help": "помочь", "checking": "проверка",
    "meter": "указатель", "option": "опция", "coding": "кодирование",
    "display": "отобразить", "gauge": "указатель", "boost": "наддув",
    "adds": "добавляет", "damage": "повредить", "set": "установить",
    "requires": "требует", "disables": "отключает", "enables": "включает",
    "removes": "удаляет", "remove": "удалить", "removed": "удалено",
    "deprecated": "устаревший", "warning": "внимание", "note": "примечание",
    "combined": "объединено", "release": "выпуск", "next": "следующий",
    "fixes": "исправляет", "fix": "исправление", "clear": "очистить",
    "realign": "заново согласовать", "module": "модуль", "via": "через",
    "custom": "пользовательский", "default": "по умолчанию",
    "table": "таблица", "switch": "переключатель", "over": "через",
    "cut": "отсечка", "limiter": "ограничитель", "cluster": "приборная панель",
    "bosch": "Bosch", "bmw": "BMW", "m": "M", "e": "E",
    "configuration": "конфигурация", "configured": "настроено",
    "banks": "банки", "learning": "обучение", "learn": "обучение",
    "either": "либо", "both": "оба", "none": "нет", "other": "другой",
    "same": "тот же", "different": "другой", "specific": "конкретный",
    "given": "заданный", "such": "такой", "including": "включая",
}


# ---------------------------------------------------------------------------
# Hand-verified explanations of important parameters
# ---------------------------------------------------------------------------
# ru   — a clear Russian name
# note — what it actually does
# tune — what to change and what to watch

PARAM_RU: Dict[str, Dict[str, str]] = {
    "id_n_max_mt__gear": {
        "ru": "Отсечка по оборотам, мягкая, МКПП (по передачам)",
        "note": "Мягкая отсечка: ЭБУ начинает срезать топливо/момент. Таблица по номеру передачи.",
        "tune": "Поднимать вместе с id_n_max_max_mt__gear, разница обычно 150-250 об/мин. "
                "Выше 7000 на M54 без доработки клапанного механизма — риск.",
    },
    "id_n_max_max_mt__gear": {
        "ru": "Отсечка по оборотам, жёсткая, МКПП (по передачам)",
        "note": "Жёсткий предел. Достигается, если мягкая не удержала обороты.",
        "tune": "Всегда держать выше мягкой отсечки id_n_max_mt__gear.",
    },
    "id_n_max_at__gear": {
        "ru": "Отсечка по оборотам, мягкая, АКПП (по передачам)",
        "note": "То же, что и для МКПП, но для автомата.",
        "tune": "Правится вместе с id_n_max_max_at__gear.",
    },
    "id_n_max_max_at__gear": {
        "ru": "Отсечка по оборотам, жёсткая, АКПП (по передачам)",
        "note": "Жёсткий предел оборотов для АКПП.",
        "tune": "Держать выше мягкой отсечки.",
    },
    "c_vs_max_mt_1": {
        "ru": "Ограничитель максимальной скорости, МКПП",
        "note": "Заводское ограничение скорости для механики.",
        "tune": "Поднять до 300+ км/ч, чтобы снять ограничитель. Учтите индекс скорости резины.",
    },
    "c_vs_max_at_1": {
        "ru": "Ограничитель максимальной скорости, АКПП",
        "note": "Заводское ограничение скорости для автомата.",
        "tune": "Аналогично МКПП-версии.",
    },
    "c_vs_max_hys": {
        "ru": "Гистерезис ограничителя скорости",
        "note": "На сколько км/ч должна упасть скорость, чтобы ограничение отпустило.",
        "tune": "Обычно не трогают.",
    },
    "ip_iga_ron_98_pl_ivvt__n__maf": {
        "ru": "Основная карта УОЗ, бензин RON98",
        "note": "Целевой угол опережения зажигания для хорошего топлива, "
                "работает на частичной и полной нагрузке. Оси: обороты × расход воздуха. "
                "(pl в имени — part load, частичная нагрузка.)",
        "tune": "Главная карта для прибавки мощности. Добавлять по 1-2° и обязательно "
                "смотреть коррекции по детонации в логе. При стоковом железе запас невелик.",
    },
    "ip_iga_ron_91_pl_ivvt__n__maf": {
        "ru": "Основная карта УОЗ, бензин RON91",
        "note": "Карта зажигания для низкооктанового топлива. ЭБУ смешивает 91 и 98 карты "
                "по адаптированному коэффициенту октанового числа.",
        "tune": "Если поднимаете только карту 98, при плохом бензине мотор уйдёт на эту карту. "
                "Держать её консервативной.",
    },
    "ip_iga_aj_ron_98__n__maf": {
        "ru": "Карта УОЗ, бензин 98, антирывковая функция",
        "note": "Применяется в переходных режимах для сглаживания рывков.",
        "tune": "Правят вместе с основными картами, чтобы не было провала на переходах.",
    },
    "ip_iga_aj_ron_91__n__maf": {
        "ru": "Карта УОЗ, бензин 91, антирывковая функция",
        "note": "То же для низкооктанового топлива.",
        "tune": "Держать консервативной.",
    },
    "id_maf_tab__v_maf_1__v_maf_2": {
        "ru": "Тарировка ДМРВ (напряжение → расход воздуха)",
        "note": "Пересчёт напряжения расходомера в кг/ч. Основа всей модели нагрузки.",
        "tune": "Правится при смене расходомера или установке впуска другого диаметра. "
                "Ошибка здесь ломает и топливо, и зажигание, и момент — трогать только с логами.",
    },
    "c_gr_rax_sp": {
        "ru": "Передаточное отношение главной пары",
        "note": "Стоковое значение E39 530i — 2.93. Используется для расчёта передачи и скорости.",
        "tune": "Менять при замене редуктора, иначе поедет распознавание передач.",
    },
    "id_vim_pl__n_vim__maf": {
        "ru": "Управление DISA при частичной нагрузке",
        "note": "Точка переключения заслонки впускного коллектора по оборотам и нагрузке.",
        "tune": "Стоково переключается около 3750 об/мин. Смещение точки заметно "
                "меняет форму кривой момента.",
    },
    "id_vim_fl__n_vim": {
        "ru": "Управление DISA (форсированный режим)",
        "note": "Точка переключения DISA в режиме полной нагрузки.",
        "tune": "См. id_vim_pl__n_vim__maf.",
    },
    "c_n_lim_min": {
        "ru": "Порог оборотов для записи события перекрута",
        "note": "Выше этого значения ЭБУ фиксирует перекрут в памяти.",
        "tune": "Поднимают вместе с отсечкой, иначе после каждой поездки в отсечку будет запись.",
    },
    "c_n_min_vs_max": {
        "ru": "Минимальные обороты для срабатывания ограничителя скорости",
        "note": "Ниже этих оборотов ограничение максимальной скорости не работает. "
                "В самом XDF описания нет — смысл выведен из имени и из того, "
                "как этот параметр меняют в тюненых прошивках.",
        "tune": "Распространённый способ снять ограничитель скорости: задрать "
                "значение выше отсечки (например, 8160), тогда условие никогда "
                "не выполнится. Альтернатива — поднять c_vs_max_mt_1 / c_vs_max_at_1.",
    },
    "c_conf_cat": {
        "ru": "Конфигурация лямбда-зондов (0…4)",
        "note": "Задаёт, сколько банков и лямбда-зондов ожидает блок: один или два "
                "банка, есть ли зонды после катализатора и обучаются ли они "
                "автоматически. Точная расшифровка каждого значения приведена в "
                "описании из XDF выше — в разных версиях XDF нумерация "
                "описана немного по-разному, ориентируйтесь на неё.",
        "tune": "Значение 1 используют при удалении катализаторов, чтобы блок "
                "перестал следить за задними зондами (P0420/P0430). "
                "Значение должно соответствовать реальной проводке — "
                "иначе получите ошибки по зондам.",
    },
    "c_conf_sap": {
        "ru": "Конфигурация насоса вторичного воздуха (0…3)",
        "note": "Задаёт вариант системы вторичного воздуха и её диагностики.",
        "tune": "Меняют при удалении насоса вторичного воздуха, чтобы убрать P0491/P0492. "
                "Проверьте, какой вариант соответствует вашей машине.",
    },
    "c_conf_teg": {
        "ru": "Конфигурация датчика температуры отработавших газов (0…2)",
        "note": "Наличие и тип датчика температуры ОГ.",
        "tune": "Отключают при отсутствии датчика.",
    },
    "c_conf_mil": {
        "ru": "Конфигурация лампы Check Engine (0…3)",
        "note": "Как ведёт себя контрольная лампа неисправностей.",
        "tune": "Трогают редко; не убирает саму ошибку, только индикацию.",
    },
    "c_conf_eobd": {
        "ru": "Конфигурация E-OBD",
        "note": "Включение европейского режима бортовой диагностики.",
        "tune": "Влияет на набор активных диагностик и на Readiness.",
    },
    "c_tam_min_ect": {
        "ru": "Мин. температура наружного воздуха для работы электротермостата",
        "note": "Ниже этой температуры карта уставки ОЖ электротермостата не применяется.",
        "tune": "Снижают, чтобы «холодная» уставка ОЖ работала круглый год.",
    },
    "c_toil_min_ect": {
        "ru": "Мин. температура масла для работы электротермостата",
        "note": "Порог по маслу для перехода на пониженную уставку ОЖ.",
        "tune": "Часто снижают вместе с c_tam_min_ect и c_tia_min_ect.",
    },
    "c_tia_min_ect": {
        "ru": "Мин. температура впускного воздуха для работы электротермостата",
        "note": "Порог по воздуху для перехода на пониженную уставку ОЖ.",
        "tune": "Часто снижают вместе с c_tam_min_ect и c_toil_min_ect.",
    },
    "c_tco_sp_toil_min": {
        "ru": "Уставка температуры ОЖ до превышения порогов электротермостата",
        "note": "Целевая температура ОЖ, пока не превышены пороги "
                "c_toil_min_ect / c_tam_min_ect / c_tia_min_ect. Стоково около 105 °C.",
        "tune": "Классическая правка: снизить до 90-95 °C, чтобы мотор ходил холоднее. "
                "Ниже 85 °C уходит в постоянное обогащение и растёт расход.",
    },
    "c_tco_sp_tia_max": {
        "ru": "Уставка температуры ОЖ при превышении порогов по маслу/воздуху",
        "note": "Целевая температура ОЖ, когда превышены c_toil_max_ect или c_tia_max_ect.",
        "tune": "Снижают вместе с c_tco_sp_toil_min.",
    },
    "c_conf_dmtl": {
        "ru": "Конфигурация DMTL (диагностика утечек паров топлива)",
        "note": "Включение модуля диагностики герметичности топливной системы.",
        "tune": "Отключают при отсутствии модуля DMTL.",
    },
    "cal_cks": {
        "ru": "CRC16 калибровочной секции",
        "note": "Контрольная сумма калибровочной зоны. ЭБУ проверяет её при старте.",
        "tune": "Пересчитывается автоматически тюнерским софтом. Вручную не трогать.",
    },
    "cal_mon_cks_1": {
        "ru": "Аддитивная контрольная сумма мониторинга, часть 1",
        "note": "Сумма значений блока мониторинга калибровки.",
        "tune": "Пересчитывается автоматически.",
    },
    "cal_mon_cks_2": {
        "ru": "Аддитивная контрольная сумма мониторинга, часть 2",
        "note": "Сумма значений блока мониторинга калибровки.",
        "tune": "Пересчитывается автоматически.",
    },
}


# ---------------------------------------------------------------------------
# Translation functions
# ---------------------------------------------------------------------------

_WORD_SPLIT = re.compile(r"([A-Za-z]+)")

# Identifiers like c_vs_fac / ip_iga_ron_98_pl_ivvt__n__maf must not be
# translated word by word (that would mangle them), so they are hidden behind
# placeholders during translation.
_IDENT_RE = re.compile(r"\b[A-Za-z][A-Za-z0-9]*(?:_+[A-Za-z0-9]+){1,}\b")
# Factory option and fault codes: SA199, P0420, M54, E39 — never translated.
_CODE_RE = re.compile(r"\b[A-Z]{1,3}\d{2,}\b")
_PLACEHOLDER = "\x00{}\x00"


def category_ru(name: str) -> str:
    return CATEGORY_RU.get(name, name)


def _mask(text: str, pattern: "re.Pattern[str]", saved: List[str]) -> str:
    def grab(match: "re.Match[str]") -> str:
        saved.append(match.group(0))
        return _PLACEHOLDER.format(len(saved) - 1)

    return pattern.sub(grab, text)


def _unmask_identifiers(text: str, saved: List[str]) -> str:
    for idx, value in enumerate(saved):
        text = text.replace(_PLACEHOLDER.format(idx), value)
    return text


def _apply_phrases(text: str) -> str:
    lowered = text
    for eng in sorted(PHRASE_RU, key=len, reverse=True):
        pattern = re.compile(r"(?<![A-Za-z])" + re.escape(eng) + r"(?![A-Za-z])", re.IGNORECASE)
        lowered = pattern.sub(lambda m, r=PHRASE_RU[eng]: r, lowered)
    return lowered


def _translate_word(word: str) -> str:
    lower = word.lower()
    if lower in WORD_RU:
        return WORD_RU[lower]
    # simple plural forms
    if lower.endswith("s") and lower[:-1] in WORD_RU:
        return WORD_RU[lower[:-1]]
    if lower.endswith("es") and lower[:-2] in WORD_RU:
        return WORD_RU[lower[:-2]]
    return word


def description_ru(text: str) -> str:
    """Translate an English XDF description into Russian (approximately)."""
    if not text:
        return ""
    # Order matters: hide identifiers first (otherwise "vs" inside c_vs_fac
    # gets caught by a phrase replacement), then translate phrases, then hide
    # factory codes and translate single words.
    saved: List[str] = []
    masked = _mask(text, _IDENT_RE, saved)
    result = _mask(_apply_phrases(masked), _CODE_RE, saved)
    out_parts: List[str] = []
    for chunk in _WORD_SPLIT.split(result):
        if chunk.isascii() and chunk.isalpha():
            out_parts.append(_translate_word(chunk))
        else:
            out_parts.append(chunk)
    joined = _unmask_identifiers("".join(out_parts), saved)
    joined = re.sub(r"[ \t]{2,}", " ", joined)
    joined = re.sub(r"\s+([,.;:!?)])", r"\1", joined)
    joined = re.sub(r"^[\s\-—]+", "", joined)
    joined = joined.strip()
    if joined and joined[0].islower():
        joined = joined[0].upper() + joined[1:]
    return joined


def split_name(title: str) -> Tuple[str, List[str], List[str]]:
    """Split a name like ip_iga_ron_98_pl_ivvt__n__maf.

    Returns (prefix, main tokens, axis tokens).
    """
    if not title:
        return "", [], []
    parts = title.split("__")
    head = parts[0]
    axes = parts[1:]
    tokens = [t for t in head.split("_") if t]
    prefix = ""
    if tokens and tokens[0] in PREFIX_RU:
        prefix = tokens[0]
        tokens = tokens[1:]
    axis_tokens: List[str] = []
    for axis in axes:
        axis_tokens.extend(t for t in axis.split("_") if t)
    return prefix, tokens, axis_tokens


def token_ru(token: str) -> Optional[str]:
    if _NUMERIC.match(token):
        return token
    return TOKEN_RU.get(token)


def _tokens_ru(tokens: List[str]) -> str:
    words = []
    for tok in tokens:
        translated = token_ru(tok)
        words.append(translated if translated else tok)
    return ", ".join(w for w in words if w)


def axis_names_ru(title: str) -> Tuple[str, str]:
    """Axis labels from the name.

    MS4x names are ordered ip_<quantity>__<row axis>__<column axis>, e.g.
    ip_iga_ron_98_pl_ivvt__n__maf — rows by rpm, columns by air mass.
    Returns (row label, column label).
    """
    if not title or "__" not in title:
        return "", ""
    parts = [p for p in title.split("__")[1:] if p]
    if not parts:
        return "", ""
    if len(parts) == 1:
        return _tokens_ru(parts[0].split("_")), ""
    y = _tokens_ru(parts[-2].split("_"))
    x = _tokens_ru(parts[-1].split("_"))
    return y, x


def name_ru(title: str) -> str:
    """Decode a parameter name through the abbreviation dictionary."""
    if not title:
        return ""
    prefix, tokens, _ = split_name(title)
    body = _tokens_ru(tokens)

    label = PREFIX_RU.get(prefix, ("", ""))[0]
    text = f"[{label}] {body}" if label else body

    y_name, x_name = axis_names_ru(title)
    if y_name and x_name:
        text += f" — строки: {y_name}; столбцы: {x_name}"
    elif y_name:
        text += f" — по оси: {y_name}"
    return text


def kind_ru(title: str) -> str:
    prefix, _, _ = split_name(title)
    return PREFIX_RU.get(prefix, ("", "объект"))[1]


def explain(title: str, description: str = "") -> Dict[str, str]:
    """Collect everything we know about a parameter, in Russian."""
    curated = PARAM_RU.get(title)
    out = {
        "name": curated["ru"] if curated else name_ru(title),
        "decoded": name_ru(title),
        "kind": kind_ru(title),
        "desc": description_ru(description),
        "desc_en": description or "",
        "note": curated.get("note", "") if curated else "",
        "tune": curated.get("tune", "") if curated else "",
        "curated": "да" if curated else "нет",
    }
    return out
