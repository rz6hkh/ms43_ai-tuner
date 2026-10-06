# -*- coding: utf-8 -*-
"""
Откатка карты наполнения (VE) по логу широкополосного лямбда-зонда.

Идея простая. Блок считает, сколько воздуха попало в цилиндр, и по этому
числу льёт топливо. Если реальная смесь оказалась беднее заданной — значит,
воздуха на самом деле было больше, чем блок думал, и карту наполнения надо
поднять. И наоборот.

    поправка = лямбда_измеренная / лямбда_целевая
    новое_значение = старое_значение × поправка

Тонкости, из-за которых наивный расчёт врёт:

  * **Замкнутый контур.** Если лямбда-регулирование включено, блок уже сам
    подобрал топливо, и ошибка наполнения видна не в лямбде, а в топливных
    коррекциях. Поэтому есть режим `trim`: поправка берётся из коррекций.
    Режим `both` перемножает оба вклада — так правильно, когда контур замкнут,
    но зонд всё равно показывает остаточное отклонение.
  * **Переходные режимы.** На резком газе показания зонда отстают от события
    на время прохода газов до датчика, и ускорительное обогащение искажает
    картину. Поэтому по умолчанию берутся только установившиеся точки:
    ограничение на скорость изменения оборотов и нагрузки.
  * **Задержка зонда.** Сдвиг лога на N отсчётов назад (`--delay`), иначе
    поправка размажется по соседним ячейкам.
  * **Мало данных.** Ячейка, куда попало три точки, ничего не значит.
    Ячейки с малым числом отсчётов не трогаются, а не заполняются мусором.

Инструмент считает и показывает — записывать в прошивку или нет, решаете вы.
"""

from __future__ import annotations

import csv
import math
import os
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from .binfile import Reader
from .xdf import Item

# ---------------------------------------------------------------------------
# Чтение лога
# ---------------------------------------------------------------------------

# Как обычно называются каналы в логах TunerPro/MS4x и у популярных ШЛЗ.
# Сопоставление регистронезависимое, по вхождению подстроки.
COLUMN_HINTS: Dict[str, Sequence[str]] = {
    "rpm": ("engine speed", "rpm", "\bn\b", "drehzahl", "nmot"),
    "load": ("mass air flow", "maf", "load", "map", "manifold", "rl", "füllung",
             "fuellung", "charge"),
    "lambda": ("wideband", "wb lambda", "afr", "lambda", "lsu", "o2", "aem",
               "innovate", "zeitronix"),
    "target": ("target lambda", "lambda target", "lam_sp", "commanded",
               "soll", "target afr"),
    "trim": ("trim", "adaptation", "fuel correction", "ltft", "stft", "lam_i",
             "integrator"),
    "tps": ("throttle", "tps", "pedal", "pvs"),
    "coolant": ("coolant", "tco", "water temp"),
    "time": ("time", "timestamp", "seconds", "zeit"),
}

# Стехиометрия для пересчёта AFR в лямбду
STOICH = {
    "gasoline": 14.7,
    "e85": 9.765,
    "e10": 14.13,
    "methanol": 6.4,
}


class LogError(ValueError):
    """С логом что-то не так."""


@dataclass
class LogColumns:
    rpm: str
    load: str
    lam: str
    target: Optional[str] = None
    trim: Optional[str] = None
    tps: Optional[str] = None
    coolant: Optional[str] = None
    time: Optional[str] = None


def _norm(name: str) -> str:
    return re.sub(r"[\s_\-\[\]()]+", " ", (name or "").strip().lower())


def guess_columns(headers: Sequence[str]) -> Dict[str, Optional[str]]:
    """Угадать, какой столбец лога за что отвечает."""
    normalized = {h: _norm(h) for h in headers}
    out: Dict[str, Optional[str]] = {}
    for role, hints in COLUMN_HINTS.items():
        best: Optional[str] = None
        best_score = 0
        for header, low in normalized.items():
            for hint in hints:
                if hint in low:
                    # длинное совпадение важнее короткого
                    score = len(hint) + (5 if low == hint else 0)
                    if score > best_score:
                        best, best_score = header, score
        out[role] = best
    return out


def read_log(path: str, delimiter: Optional[str] = None) -> Tuple[List[str], List[Dict[str, float]]]:
    """Прочитать CSV-лог. Возвращает (заголовки, строки со значениями float)."""
    if not os.path.isfile(path):
        raise LogError(f"Файл лога не найден: {path}")
    with open(path, "r", encoding="utf-8-sig", errors="replace", newline="") as fh:
        sample = fh.read(8192)
        fh.seek(0)
        if delimiter is None:
            try:
                delimiter = csv.Sniffer().sniff(sample, delimiters=",;\t").delimiter
            except csv.Error:
                delimiter = ","
        reader = csv.reader(fh, delimiter=delimiter)
        rows = list(reader)
    if not rows:
        raise LogError("Лог пустой")

    # заголовком считаем первую строку, в которой есть хоть одно нечисловое поле
    header_idx = 0
    for idx, row in enumerate(rows[:5]):
        if any(not _is_number(cell) for cell in row if cell.strip()):
            header_idx = idx
            break
    headers = [h.strip() for h in rows[header_idx]]

    data: List[Dict[str, float]] = []
    for row in rows[header_idx + 1:]:
        if not any(cell.strip() for cell in row):
            continue
        record: Dict[str, float] = {}
        for name, cell in zip(headers, row):
            value = _to_float(cell)
            if value is not None:
                record[name] = value
        if record:
            data.append(record)
    if not data:
        raise LogError("В логе не нашлось числовых строк")
    return headers, data


def _is_number(text: str) -> bool:
    return _to_float(text) is not None


def _to_float(text: str) -> Optional[float]:
    text = (text or "").strip().replace(",", ".")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def to_lambda(value: float, fuel: str = "gasoline") -> float:
    """Привести показание зонда к лямбде.

    ШЛЗ отдают то лямбду (около 1), то AFR (около 14.7), то напряжение 0-5 В.
    Различаем по величине: это надёжнее, чем доверять названию канала.
    """
    if value <= 0:
        return 0.0
    if 0.4 <= value <= 1.6:
        return value                      # уже лямбда
    stoich = STOICH.get(fuel, STOICH["gasoline"])
    if 5.0 <= value <= 30.0:
        return value / stoich             # AFR
    return value                          # оставляем как есть, решит пользователь


# ---------------------------------------------------------------------------
# Результат разбора
# ---------------------------------------------------------------------------


@dataclass
class CellStat:
    row: int
    col: int
    samples: int = 0
    weight: float = 0.0
    _sum: float = 0.0
    _sum_sq: float = 0.0

    def add(self, correction: float, weight: float = 1.0) -> None:
        self.samples += 1
        self.weight += weight
        self._sum += correction * weight
        self._sum_sq += correction * correction * weight

    @property
    def mean(self) -> float:
        return self._sum / self.weight if self.weight else 1.0

    @property
    def spread(self) -> float:
        """Среднеквадратичный разброс поправки внутри ячейки."""
        if self.weight <= 0:
            return 0.0
        mean = self.mean
        var = max(0.0, self._sum_sq / self.weight - mean * mean)
        return math.sqrt(var)


@dataclass
class TuneResult:
    item: Item
    old: List[List[float]]
    new: List[List[float]]
    correction: List[List[float]]          # во сколько раз, 1.0 = без изменений
    stats: Dict[Tuple[int, int], CellStat] = field(default_factory=dict)
    used_samples: int = 0
    total_samples: int = 0
    skipped: Dict[str, int] = field(default_factory=dict)
    mode: str = "lambda"
    notes: List[str] = field(default_factory=list)
    y_role: str = "rpm"
    x_role: str = "load"

    @property
    def touched_cells(self) -> int:
        return sum(1 for r in range(len(self.old))
                   for c in range(len(self.old[0]))
                   if self.new[r][c] != self.old[r][c])

    @property
    def coverage(self) -> float:
        total = len(self.old) * len(self.old[0]) if self.old else 0
        covered = sum(1 for s in self.stats.values() if s.samples)
        return covered / total if total else 0.0

    def samples_at(self, row: int, col: int) -> int:
        stat = self.stats.get((row, col))
        return stat.samples if stat else 0

    def correction_percent(self, row: int, col: int) -> float:
        return (self.correction[row][col] - 1.0) * 100.0


# ---------------------------------------------------------------------------
# Основной расчёт
# ---------------------------------------------------------------------------


def _bracket(axis: Sequence[float], value: float) -> Tuple[int, int, float]:
    """Индексы соседних узлов оси и вес правого узла (билинейная привязка)."""
    if not axis:
        return 0, 0, 0.0
    if len(axis) == 1:
        return 0, 0, 0.0
    ascending = axis[-1] >= axis[0]
    points = list(axis) if ascending else list(reversed(axis))
    if value <= points[0]:
        idx = 0
        t = 0.0
    elif value >= points[-1]:
        idx = len(points) - 2
        t = 1.0
    else:
        idx = 0
        for i in range(len(points) - 1):
            if points[i] <= value <= points[i + 1]:
                idx = i
                break
        span = points[idx + 1] - points[idx]
        t = (value - points[idx]) / span if span else 0.0
    lo, hi = idx, idx + 1
    if not ascending:
        lo, hi = len(axis) - 1 - lo, len(axis) - 1 - hi
    return lo, hi, t


def detect_axis_roles(reader: Reader, item: Item) -> Tuple[str, str]:
    """Какая ось за что отвечает: возвращает роли (строки, столбцы).

    Нельзя предполагать «обороты по строкам»: у ip_map_ve_1__map__n по строкам
    давление во впуске, а обороты по столбцам, а у ip_iga_ron98_pl__n__maf
    наоборот. Смотрим на единицы оси, потом на токены имени.
    """

    def role_of(units: str, token: str) -> Optional[str]:
        low = (units or "").strip().lower()
        if low in ("rpm", "1/min", "об/мин"):
            return "rpm"
        if low in ("hpa", "kpa", "mbar", "bar", "kg/h", "mg/stk", "%", "mg/hub"):
            return "load"
        token = (token or "").lower()
        if token in ("n", "n32", "n_32", "nmot"):
            return "rpm"
        if token in ("map", "maf", "load", "ve", "rl", "pq", "maf_kgh"):
            return "load"
        return None

    parts = item.title.split("__")[1:] if "__" in item.title else []
    y_token = parts[-2] if len(parts) >= 2 else (parts[0] if parts else "")
    x_token = parts[-1] if len(parts) >= 2 else ""

    y_units = item.axis_y.units if item.axis_y else ""
    x_units = item.axis_x.units if item.axis_x else ""
    y_role = role_of(y_units, y_token)
    x_role = role_of(x_units, x_token)

    if y_role and not x_role:
        x_role = "load" if y_role == "rpm" else "rpm"
    elif x_role and not y_role:
        y_role = "load" if x_role == "rpm" else "rpm"
    elif not y_role and not x_role:
        # последняя попытка: обороты обычно кончаются далеко за тысячей
        y_axis = reader.axis_values(item, "y") or [0]
        x_axis = reader.axis_values(item, "x") or [0]
        if max(x_axis) > max(y_axis):
            y_role, x_role = "load", "rpm"
        else:
            y_role, x_role = "rpm", "load"
    elif y_role == x_role:
        # обе распознались одинаково — доверяем той, у которой единицы явные
        if (x_units or "").lower() in ("rpm", "1/min"):
            y_role = "load"
        else:
            x_role = "load" if y_role == "rpm" else "rpm"
    return y_role, x_role


def analyse(
    reader: Reader,
    item: Item,
    log_rows: Sequence[Dict[str, float]],
    columns: LogColumns,
    *,
    mode: str = "lambda",
    fuel: str = "gasoline",
    target_lambda: float = 1.0,
    min_samples: int = 8,
    max_spread: float = 0.06,
    max_step: float = 0.25,
    delay_samples: int = 0,
    steady_rpm: float = 250.0,
    steady_load: float = 8.0,
    min_coolant: Optional[float] = 70.0,
    smooth: bool = True,
) -> TuneResult:
    """Посчитать поправку к карте по логу.

    mode: 'lambda' — только по зонду; 'trim' — только по топливным коррекциям;
          'both' — перемножить (для замкнутого контура с остаточной ошибкой).
    max_step: не двигать ячейку больше чем на эту долю за один проход.
    """
    old = reader.matrix(item)
    if not old:
        raise LogError("Не удалось прочитать карту из прошивки")
    rows, cols = item.rows, item.cols
    y_axis = reader.axis_values(item, "y") or list(range(rows))
    x_axis = reader.axis_values(item, "x") or list(range(cols))

    # Роли осей определяем, а не предполагаем: у ip_map_ve_1__map__n давление
    # по строкам и обороты по столбцам, у ip_iga_ron98_pl__n__maf наоборот.
    y_role, x_role = detect_axis_roles(reader, item)

    stats: Dict[Tuple[int, int], CellStat] = {}
    skipped: Dict[str, int] = {
        "нет нужных каналов": 0,
        "переходный режим": 0,
        "холодный двигатель": 0,
        "показания зонда вне диапазона": 0,
    }
    used = 0

    prev_rpm: Optional[float] = None
    prev_load: Optional[float] = None

    for idx, row in enumerate(log_rows):
        rpm = row.get(columns.rpm)
        load = row.get(columns.load)
        # показания зонда берём со сдвигом: газы доходят до датчика не мгновенно
        source = log_rows[idx + delay_samples] if 0 <= idx + delay_samples < len(log_rows) else None
        lam_raw = source.get(columns.lam) if source else None

        if rpm is None or load is None or lam_raw is None:
            skipped["нет нужных каналов"] += 1
            continue

        if min_coolant is not None and columns.coolant:
            coolant = row.get(columns.coolant)
            if coolant is not None and coolant < min_coolant:
                skipped["холодный двигатель"] += 1
                continue

        if prev_rpm is not None and prev_load is not None:
            if abs(rpm - prev_rpm) > steady_rpm or abs(load - prev_load) > steady_load:
                prev_rpm, prev_load = rpm, load
                skipped["переходный режим"] += 1
                continue
        prev_rpm, prev_load = rpm, load

        measured = to_lambda(lam_raw, fuel)
        if not (0.4 <= measured <= 1.6):
            skipped["показания зонда вне диапазона"] += 1
            continue

        target = target_lambda
        if columns.target:
            candidate = row.get(columns.target)
            if candidate:
                target = to_lambda(candidate, fuel)
        if target <= 0:
            target = target_lambda

        correction = 1.0
        if mode in ("lambda", "both"):
            correction *= measured / target
        if mode in ("trim", "both") and columns.trim:
            trim = row.get(columns.trim)
            if trim is not None:
                # коррекция бывает в процентах (±10) и в долях (±0.1)
                factor = 1.0 + (trim / 100.0 if abs(trim) > 1.5 else trim)
                if factor > 0:
                    correction *= factor

        y_value = rpm if y_role == "rpm" else load
        x_value = rpm if x_role == "rpm" else load
        r_lo, r_hi, ty = _bracket(y_axis, y_value)
        c_lo, c_hi, tx = _bracket(x_axis, x_value)
        for r, wy in ((r_lo, 1 - ty), (r_hi, ty)):
            for c, wx in ((c_lo, 1 - tx), (c_hi, tx)):
                weight = wy * wx
                if weight <= 0 or not (0 <= r < rows and 0 <= c < cols):
                    continue
                stats.setdefault((r, c), CellStat(r, c)).add(correction, weight)
        used += 1

    # --- собираем поправку по ячейкам ---
    factor = [[1.0 for _ in range(cols)] for _ in range(rows)]
    for (r, c), stat in stats.items():
        if stat.samples < min_samples:
            continue
        if stat.spread > max_spread:
            continue
        value = stat.mean
        value = max(1.0 - max_step, min(1.0 + max_step, value))
        factor[r][c] = value

    if smooth:
        factor = _smooth(factor, stats, min_samples)

    new = [[old[r][c] * factor[r][c] for c in range(cols)] for r in range(rows)]

    result = TuneResult(
        item=item, old=old, new=new, correction=factor, stats=stats,
        used_samples=used, total_samples=len(log_rows), skipped=skipped, mode=mode,
        y_role=y_role, x_role=x_role,
    )
    result.notes.extend(_advise(result, columns, mode, max_step))
    return result


def _advise(result: "TuneResult", columns: LogColumns, mode: str,
            max_step: float) -> List[str]:
    """Замечания «как опытный тюнер посмотрел бы на этот прогон».

    Ничего не решает за пользователя, но проговаривает то, из-за чего чаще
    всего получают мусорный результат или ломают мотор.
    """
    notes: List[str] = []
    item = result.item
    min_needed = 32

    if result.used_samples < min_needed:
        notes.append(
            f"Пригодных точек всего {result.used_samples} — этого мало для любых "
            f"выводов. Нужен прогретый прогон с удержанием режимов, а не один проезд."
        )
    if result.coverage < 0.3:
        notes.append(
            f"Лог покрыл {result.coverage * 100:.0f}% ячеек карты. Непокрытые ячейки "
            f"не тронуты — это правильно, но карта откатана лишь частично. "
            f"Докатывайте недостающие зоны отдельными прогонами."
        )
    if mode == "lambda" and not columns.trim:
        notes.append(
            "Режим «по зонду» верен только в разомкнутом контуре (полная нагрузка). "
            "На частичных нагрузках блок сам подгоняет смесь, и ошибка наполнения "
            "уходит в топливные коррекции — тогда нужен режим trim или both "
            "и канал коррекций в логе."
        )
    if columns.trim and mode == "lambda":
        notes.append(
            "В логе есть канал топливных коррекций, но он не используется. "
            "Для замкнутого контура попробуйте --mode both."
        )

    extreme = [
        (r, c) for r in range(item.rows) for c in range(item.cols)
        if abs(result.correction_percent(r, c)) >= max_step * 100 - 0.01
        and result.new[r][c] != result.old[r][c]
    ]
    if extreme:
        notes.append(
            f"{len(extreme)} ячеек упёрлись в предел поправки ±{max_step * 100:.0f}%. "
            f"Это не «докрутите предел», а признак, что модель наполнения "
            f"расходится с реальностью системно: проверьте тарировку ДМРВ/MAP, "
            f"производительность форсунок и давление топлива, прежде чем гнуть карту."
        )

    lean_big = [
        (r, c) for r in range(item.rows) for c in range(item.cols)
        if result.correction_percent(r, c) >= 10.0
    ]
    if lean_big:
        notes.append(
            f"В {len(lean_big)} ячейках мотор беднил больше чем на 10%. Если это "
            f"зона высокой нагрузки — ездить так нельзя: бедная смесь под нагрузкой "
            f"убивает поршни и катализатор быстрее, чем детонация."
        )

    noisy = [key for key, stat in result.stats.items()
             if stat.samples >= 8 and stat.spread > 0.05]
    if noisy:
        notes.append(
            f"В {len(noisy)} ячейках разброс поправки велик — данные там "
            f"противоречивы. Обычно это переходные режимы, непрогретый мотор "
            f"или неучтённая задержка зонда (попробуйте --delay 2…6)."
        )

    if columns.coolant is None:
        notes.append(
            "В логе не нашёлся канал температуры ОЖ — точки на непрогретом моторе "
            "не отфильтровались. Прогрев искажает смесь, результат может поехать."
        )
    if columns.target is None:
        notes.append(
            "Целевая лямбда в логе не найдена, взято значение из --target. "
            "На полной нагрузке блок целится в обогащение (обычно 0.85…0.90), "
            "и если считать цель равной 1.0, программа предложит обеднить мотор "
            "там, где обогащение сделано намеренно."
        )
    return notes


def _smooth(factor: List[List[float]], stats: Dict[Tuple[int, int], CellStat],
            min_samples: int) -> List[List[float]]:
    """Лёгкое сглаживание 3×3 по ячейкам, где есть данные.

    Ячейки без данных не участвуют и не меняются: размазывать поправку
    на области, где машина не была, — верный способ получить провал.
    """
    rows, cols = len(factor), len(factor[0])
    out = [row[:] for row in factor]
    for r in range(rows):
        for c in range(cols):
            stat = stats.get((r, c))
            if not stat or stat.samples < min_samples:
                continue
            total = 0.0
            weight = 0.0
            for dr in (-1, 0, 1):
                for dc in (-1, 0, 1):
                    rr, cc = r + dr, c + dc
                    if not (0 <= rr < rows and 0 <= cc < cols):
                        continue
                    neighbour = stats.get((rr, cc))
                    if not neighbour or neighbour.samples < min_samples:
                        continue
                    w = 4.0 if (dr == 0 and dc == 0) else 1.0
                    total += factor[rr][cc] * w
                    weight += w
            if weight:
                out[r][c] = total / weight
    return out


# ---------------------------------------------------------------------------
# Запись результата
# ---------------------------------------------------------------------------


def write_tuned_bin(reader: Reader, item: Item, result: TuneResult,
                    out_path: str) -> Dict:
    """Записать новую карту в НОВЫЙ .bin. Исходный файл не трогается."""
    from .crossdiff import phys_to_raw

    data = bytearray(reader.bin.data)
    base = reader.item_offset(item)
    d = item.data
    if base is None or d is None:
        raise LogError("У карты нет адреса в этом файле")

    order = "little" if d.lsb_first else "big"
    cols = max(1, d.colcount)
    written = 0
    clipped = 0
    for r in range(item.rows):
        for c in range(item.cols):
            value = result.new[r][c]
            raw, reason = phys_to_raw(item, value)
            if raw is None:
                clipped += 1
                continue
            idx = r * cols + c
            rr, cc = divmod(idx, cols)
            off = base + rr * d.row_stride + cc * d.col_stride
            if off < 0 or off + d.elem_bytes > len(data):
                continue
            data[off:off + d.elem_bytes] = int(raw).to_bytes(
                d.elem_bytes, order, signed=d.signed)
            written += 1

    with open(out_path, "wb") as fh:
        fh.write(data)
    return {"path": out_path, "cells": written, "clipped": clipped,
            "size": len(data)}
