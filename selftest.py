#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Самопроверка ms43diff.

    python selftest.py                         # только внутренние проверки
    python selftest.py def.xdf стоковая.bin     # плюс проверки на реальных файлах

Внутренние проверки не требуют никаких файлов и внешних библиотек.
"""

from __future__ import annotations

import sys

# На чистой Windows (в т.ч. на CI-раннере) stdout по умолчанию cp1252 и не
# кодирует кириллицу — print падает с UnicodeEncodeError. Принудительно UTF-8.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

from ms43diff.binfile import BinFile, Reader, format_number
from ms43diff.mathexpr import Equation
from ms43diff.xdf import Embedded, XdfFile

_failed = 0


def check(name: str, got, want) -> None:
    global _failed
    ok = got == want
    if isinstance(want, float) or isinstance(got, float):
        try:
            ok = abs(float(got) - float(want)) < 1e-6
        except (TypeError, ValueError):
            ok = False
    mark = "OK  " if ok else "ОШИБКА"
    if not ok:
        _failed += 1
        print(f"[{mark}] {name}: получено {got!r}, ожидалось {want!r}")
    else:
        print(f"[{mark}] {name}")


def test_math() -> None:
    print("\n--- Формулы пересчёта ---")
    check("0.75*X-48.0 при X=64", Equation("0.75*X-48.0").apply(64), 0.0)
    check("0.375*X-23.625 при X=155", Equation("0.375*X-23.625").apply(155), 34.5)
    check("X*0.003906 при X=750", Equation("X*0.003906").apply(750), 2.9295)
    check("32.0*X при X=202", Equation("32.0*X").apply(202), 6464.0)
    # переменная называется не X — так бывает в автогенерированном XDF
    check("0.1*X0 при X0=250", Equation("0.1*X0", ["X0"]).apply(250), 25.0)
    check("скобки и степень", Equation("(2+3)^2").apply(0), 25.0)
    check("функция abs", Equation("abs(0-X)").apply(7), 7.0)
    check("битая формула не падает", Equation("0.5*").apply(9), 9.0)
    check("деление на ноль не падает", Equation("X/0").apply(9), 9.0)
    eq = Equation("0.75*X-48.0")
    check("линейность распознана", eq.is_linear, True)
    check("обратный пересчёт", eq.invert(0.0), 64.0)
    check("описание масштаба", eq.describe_ru("°C"), "1 бит = 0.75 °C, смещение -48 °C")


def test_embedded() -> None:
    print("\n--- Раскладка данных ---")
    e = Embedded(address=0x100, size_bits=16, rowcount=20, colcount=16, type_flags=0x02)
    check("знаковость", e.signed, False)
    check("порядок байт", e.lsb_first, True)
    check("байт на элемент", e.elem_bytes, 2)
    check("шаг строки", e.row_stride, 32)
    check("длина блока", e.byte_length, 20 * 32)
    s = Embedded(address=0x10, size_bits=8, type_flags=0x03)
    check("знаковое 8 бит", s.signed, True)
    check("статическая ось без данных",
          Embedded(size_bits=8, major_stride_bits=-32).has_data, False)


def test_format() -> None:
    print("\n--- Форматирование ---")
    check("десятичные знаки", format_number(2.9295, 2, 1), "2.93")
    check("целое", format_number(6464.0, 0, 3), "6464")
    check("шестнадцатеричное", format_number(255, 0, 2), "0xFF")


def test_ru() -> None:
    print("\n--- Русский слой ---")
    from ms43diff import ru

    check(
        "расшифровка имени",
        ru.name_ru("ip_iga_ron_98_pl_ivvt__n__maf").startswith(
            "[КАРТА] угол опережения зажигания"
        ),
        True,
    )
    check("оси из имени", ru.axis_names_ru("ip_iga_ron_98_pl_ivvt__n__maf"),
          ("обороты двигателя", "расход воздуха (нагрузка)"))
    check("категория", ru.category_ru("Vanos"), "VANOS (фазовращатели)")
    check("единицы", ru.unit_ru("mg/stk"), "мг/такт")
    check(
        "идентификатор не переводится пословно",
        "c_vs_fac" in ru.description_ru("Set c_vs_fac to 1096"),
        True,
    )
    check(
        "перевод описания",
        ru.description_ru("Maximum engine speed for misfire detection"),
        "Максимальный обороты двигателя для обнаружение пропусков воспламенения",
    )


def test_files(xdf_path: str, bin_path: str) -> None:
    print(f"\n--- Реальные файлы ---")
    xdf = XdfFile(xdf_path)
    binf = BinFile(bin_path)
    reader = Reader(xdf, binf)
    print(f"XDF: {xdf.title} v{xdf.file_version}, объектов {len(xdf.items)}")
    print(f"BIN: {binf.name}, {binf.size_kb} КБ, смещение {reader.offset.label}, "
          f"попадание {reader.offset.fit * 100:.1f}%")

    check("смещение подобрано полностью", reader.offset.fit, 1.0)

    ratio = xdf.by_title("c_gr_rax_sp")
    if ratio is not None:
        values = reader.values(ratio)
        print(f"Главная пара (c_gr_rax_sp) = {values[0]:.3f}")
        check("главная пара в разумных пределах", 2.0 < values[0] < 5.0, True)

    limiter = xdf.by_title("id_n_max_mt__gear")
    if limiter is not None:
        values = reader.values(limiter)
        print(f"Отсечка МКПП по передачам: {[int(v) for v in values]}")
        check("отсечка в разумных пределах", all(3000 < v < 9000 for v in values), True)

    iga = xdf.by_title("ip_iga_ron_98_pl_ivvt__n__maf")
    if iga is not None:
        values = reader.values(iga)
        print(f"Карта УОЗ RON98: {min(values):.1f}…{max(values):.1f} ° к.в., "
              f"ячеек {len(values)}")
        check("УОЗ в разумных пределах", -30 < min(values) and max(values) < 60, True)
        x = reader.axis_values(iga, "x")
        y = reader.axis_values(iga, "y")
        check("ось X прочитана", x is not None and len(x) == iga.cols, True)
        check("ось Y прочитана", y is not None and len(y) == iga.rows, True)


def main() -> int:
    test_math()
    test_embedded()
    test_format()
    test_ru()
    if len(sys.argv) >= 3:
        test_files(sys.argv[1], sys.argv[2])
    else:
        print("\n(Проверки на реальных файлах пропущены — "
              "запустите: python selftest.py def.xdf прошивка.bin)")
    print()
    if _failed:
        print(f"ПРОВАЛЕНО проверок: {_failed}")
        return 1
    print("Все проверки пройдены.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
