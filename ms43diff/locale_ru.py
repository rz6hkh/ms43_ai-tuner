# -*- coding: utf-8 -*-
"""
Russian UI catalog: English source text -> Russian text.

Keys must match the ``t("...")`` calls in the code exactly, placeholders
included. ``selftest.py`` checks that every key used in the code is present.
"""

from typing import Dict

RU: Dict[str, str] = {
    # --- common -------------------------------------------------------------
    "yes": "да",
    "no": "нет",

    # --- mathexpr -----------------------------------------------------------
    "unexpected character {ch!r} at position {pos} in formula {src!r}":
        "непонятный символ {ch!r} в позиции {pos} формулы {src!r}",
    "formula {src!r} ends unexpectedly": "формула {src!r} обрывается неожиданно",
    "extra characters at the end of formula {src!r}": "лишние символы в конце формулы {src!r}",
    "division by zero": "деление на ноль",
    "modulo by zero": "остаток от деления на ноль",
    "missing closing bracket in {src!r}": "нет закрывающей скобки в {src!r}",
    "missing closing bracket of function {name} in {src!r}":
        "нет закрывающей скобки у функции {name} в {src!r}",
    "unknown function {name!r}": "неизвестная функция {name!r}",
    "unknown variable {name!r} in formula {src!r}": "неизвестная переменная {name!r} в формуле {src!r}",
    "unexpected {tok!r} in formula {src!r}": "не ожидали {tok!r} в формуле {src!r}",
    "non-linear formula: {src}": "нелинейная формула: {src}",
    "1 bit = {value}": "1 бит = {value}",
    "offset {value}": "смещение {value}",

    # --- binfile ---------------------------------------------------------------
    'as in XDF':
        'как в XDF',
    'picked automatically':
        'подобрано автоматически',
    'the firmware software version is {fw}, but the XDF describes {title}. Addresses almost certainly differ and the result will be garbage. Use an XDF for {fw}.':
        'версия ПО в прошивке — {fw}, а XDF описывает {title}. Адреса почти наверняка не совпадают, результат будет мусорным. Возьмите XDF для {fw}.',
    'all {value}':
        'все {value}',
    ' (avg {value})':
        ' (ср. {value})',

    # --- xdf -------------------------------------------------------------------
    'scalar':
        'скаляр',
    'could not parse XDF {path}: {error}':
        'не удалось разобрать XDF {path}: {error}',
    'Category 0x{index:X}':
        'Категория 0x{index:X}',
    '<no category>':
        '<без категории>',

    # --- compare ---------------------------------------------------------------
    '{changed} of {total} cells changed, delta {lo}…{hi}':
        'изменено {changed} из {total} ячеек, дельта {lo}…{hi}',
    'address outside the file':
        'адрес вне границ файла',
    'could not read the values':
        'не удалось прочитать значения',
    'applied':
        'применён',
    'not applied':
        'не применён',
    'partially':
        'частично',
    'modified':
        'изменён',
    'out of file':
        'вне файла',
    '{name}: 0x{off:X} outside the file':
        '{name}: 0x{off:X} вне файла',
    '{name}: 0x{off:X} = {got} (expected {patched} or {base})':
        '{name}: 0x{off:X} = {got} (ожидалось {patched} или {base})',

    # --- crossdiff -------------------------------------------------------------
    'same':
        'совпадает',
    'different':
        'отличается',
    'missing in B':
        'нет в B',
    'missing in A':
        'нет в A',
    'different shape':
        'разная форма',
    'unreadable':
        'не читается',
    'safe: byte match':
        'безопасно: совпадение по байтам',
    'safe: name match':
        'безопасно: совпадение по имени',
    'warning':
        'предупреждение',
    'the parameter has no data in the target firmware':
        'у параметра нет данных в целевой прошивке',
    'the formula cannot be inverted for a field wider than 16 bits':
        'формулу нельзя обратить для поля шире 16 бит',
    'the value does not fit the bit width of the field':
        'значение не влезает в разрядность поля',
    'exact name match':
        'точное совпадение имени',
    'matched after name normalisation ({src} -> {dst})':
        'совпало после нормализации имени ({src} -> {dst})',
    'several parameters match the normalised name':
        'нормализованному имени соответствует несколько параметров',
    'different formulas: A "{a}", B "{b}"':
        'разные формулы: A «{a}», B «{b}»',
    'the factors differ by exactly {power:g} times — looks like a typo in one of the XDFs, check by hand before porting':
        'коэффициенты различаются ровно в {power:g} раз — похоже на опечатку в одном из XDF, проверьте вручную, прежде чем переносить',
    'different bit width: {a} and {b} bits':
        'разная разрядность: {a} и {b} бит',
    'different signedness':
        'разная знаковость',
    'different addresses: 0x{a:X} and 0x{b:X}':
        'разные адреса: 0x{a:X} и 0x{b:X}',
    '{changed} of {total} cells differ, delta {lo}…{hi}':
        'отличается {changed} из {total} ячеек, дельта {lo}…{hi}',
    '{a} vs {b}':
        '{a} против {b}',
    'text: "{a}" -> "{b}"':
        'текст: «{a}» -> «{b}»',
    'Match: ':
        'Совпадение: ',
    'Problem: ':
        'Проблема: ',
    'your value: {value}':
        'ваше значение: {value}',
    'your value: {value}   (target now: {before})':
        'ваше значение: {value}   (в целевой сейчас: {before})',
    'the target version has no parameter with this name; similar ones (check by hand): {names}':
        'в целевой версии нет параметра с таким именем; похожие (проверить вручную): {names}',
    'the target version has no parameter with this name and nothing similar — the function was most likely removed':
        'в целевой версии нет параметра с таким именем и похожих не нашлось — скорее всего функцию вырезали',
    'text field — port by hand':
        'текстовое поле — переносить вручную',
    'map size differs: {a} vs {b}':
        'размер карты отличается: {a} против {b}',
    'name, address, size and formula are identical — can be copied 1:1':
        'имя, адрес, размер и формула идентичны — можно копировать 1:1',
    'name and map size match':
        'имя и размер карты совпадают',
    'the formula differs (A "{a}", B "{b}") — port the physical value, not the bytes':
        'формула отличается (A «{a}», B «{b}») — переносить физическую величину, а не байты',
    'different addresses: 0x{a:X} → 0x{b:X}':
        'разные адреса: 0x{a:X} → 0x{b:X}',
    'different bit width: {a} → {b} bits':
        'разная разрядность: {a} → {b} бит',

    # --- vetune ----------------------------------------------------------------
    'Log file not found: {path}':
        'Файл лога не найден: {path}',
    'The log is empty':
        'Лог пустой',
    'No numeric rows found in the log':
        'В логе не нашлось числовых строк',
    'Could not read the map from the firmware':
        'Не удалось прочитать карту из прошивки',
    'required channels missing':
        'нет нужных каналов',
    'transient':
        'переходный режим',
    'cold engine':
        'холодный двигатель',
    'sensor reading out of range':
        'показания зонда вне диапазона',
    'Only {n} usable samples — too few for any conclusion. You need a warm run holding steady operating points, not a single drive.':
        'Пригодных точек всего {n} — этого мало для любых выводов. Нужен прогретый прогон с удержанием режимов, а не один проезд.',
    'The log covered {pct:.0f}% of the map cells. Uncovered cells are left alone — that is correct, but the map is only partly tuned. Log the missing areas in separate runs.':
        'Лог покрыл {pct:.0f}% ячеек карты. Непокрытые ячейки не тронуты — это правильно, но карта откатана лишь частично. Докатывайте недостающие зоны отдельными прогонами.',
    'The "by sensor" mode is only valid in open loop (full load). At part load the ECU adjusts the mixture itself and the VE error goes into the fuel trims — then you need the trim or both mode and a trim channel in the log.':
        'Режим «по зонду» верен только в разомкнутом контуре (полная нагрузка). На частичных нагрузках блок сам подгоняет смесь, и ошибка наполнения уходит в топливные коррекции — тогда нужен режим trim или both и канал коррекций в логе.',
    'The log has a fuel trim channel, but it is not used. For closed loop try --mode both.':
        'В логе есть канал топливных коррекций, но он не используется. Для замкнутого контура попробуйте --mode both.',
    '{n} cells hit the correction limit of ±{pct:.0f}%. This does not mean "raise the limit" — it means the airflow model is systematically off: check the MAF/MAP calibration, injector flow and fuel pressure before bending the map.':
        '{n} ячеек упёрлись в предел поправки ±{pct:.0f}%. Это не «докрутите предел», а признак, что модель наполнения расходится с реальностью системно: проверьте тарировку ДМРВ/MAP, производительность форсунок и давление топлива, прежде чем гнуть карту.',
    'In {n} cells the engine ran more than 10% lean. If this is a high-load area, do not drive like this: a lean mixture under load kills pistons and the catalyst faster than knock.':
        'В {n} ячейках мотор беднил больше чем на 10%. Если это зона высокой нагрузки — ездить так нельзя: бедная смесь под нагрузкой убивает поршни и катализатор быстрее, чем детонация.',
    'In {n} cells the correction spread is large — the data there is contradictory. Usually transients, a cold engine or an unaccounted sensor delay (try --delay 2…6).':
        'В {n} ячейках разброс поправки велик — данные там противоречивы. Обычно это переходные режимы, непрогретый мотор или неучтённая задержка зонда (попробуйте --delay 2…6).',
    'No coolant temperature channel in the log — cold-engine samples were not filtered out. Warm-up distorts the mixture, the result may drift.':
        'В логе не нашёлся канал температуры ОЖ — точки на непрогретом моторе не отфильтровались. Прогрев искажает смесь, результат может поехать.',
    'No target lambda in the log, the --target value is used. At full load the ECU targets enrichment (usually 0.85…0.90), and with a target of 1.0 the program would suggest leaning the engine where enrichment is intentional.':
        'Целевая лямбда в логе не найдена, взято значение из --target. На полной нагрузке блок целится в обогащение (обычно 0.85…0.90), и если считать цель равной 1.0, программа предложит обеднить мотор там, где обогащение сделано намеренно.',
    'The map has no address in this file':
        'У карты нет адреса в этом файле',

    # --- wikicache -------------------------------------------------------------
    'parsing failed: {error}':
        'разбор не удался: {error}',

    # --- report ----------------------------------------------------------------
    'the reference has no such value':
        'в справочнике такого значения нет',
    '─── MS4X Wiki ───':
        '─── MS4X Wiki (перевод) ───',
    '  ({n} more mentions: ms43diff wiki --param {title})':
        '  (ещё {n} упоминаний: ms43diff wiki --param {title})',
    'what MS4X Wiki says ({n})':
        'что пишет MS4X Wiki ({n}) — перевод',
    'original (English)':
        'оригинал (English)',
    '%Y-%m-%d %H:%M':
        '%d.%m.%Y %H:%M',
    '  MS43 FIRMWARE COMPARISON':
        '  СРАВНЕНИЕ ПРОШИВОК MS43',
    'XDF          : {title}  (v{version}, {author})':
        'Описание XDF : {title}  (v{version}, {author})',
    'File A       : {name}  ({kb} KB)':
        'Файл A       : {name}  ({kb} КБ)',
    'File B       : {name}  ({kb} KB)':
        'Файл B       : {name}  ({kb} КБ)',
    'Offset       : A {a} / B {b}':
        'Смещение     : A {a} / B {b}',
    'WARNING: the files differ in size, the smaller one is compared.':
        'ВНИМАНИЕ: файлы разного размера, сравниваются по меньшему.',
    'WARNING ({tag}): {text}':
        'ВНИМАНИЕ ({tag}): {text}',
    'Parameters changed  : {n}':
        'Параметров изменено : {n}',
    'Parameters same     : {n}':
        'Параметров совпало  : {n}',
    'Bytes changed       : {n} in {blocks} blocks':
        'Байт изменено       : {n} в {blocks} блоках',
    'Blocks outside XDF  : {n} ({bytes} bytes) — code edits/patches':
        'Блоков вне карт XDF : {n} ({bytes} байт) — это правки кода/патчи',
    'Skipped             : {n} (address outside the file)':
        'Пропущено           : {n} (адрес вне файла)',
    'No differences found in the parameters described by the XDF.':
        'Различий в параметрах, описанных XDF, не найдено.',
    '... showing {shown} of {total}. Use --limit 0 to show everything.':
        '... показано {shown} из {total}. Используйте --limit 0, чтобы вывести всё.',
    '    Description: {text}':
        '    Описание: {text}',
    '    Original: {text}':
        '    Оригинал: {text}',
    '    Value: {value}':
        '    Значение: {value}',
    '    Type: {shape} | XDF address {address} | file {offset} | {scaling}':
        '    Тип: {shape} | адрес XDF {address} | файл {offset} | {scaling}',
    '    After the change: {step}':
        '    После изменения: {step}',
    '    What it is: {text}':
        '    Что это: {text}',
    '    How to tune: {text}':
        '    Как крутить: {text}',
    '  CHANGES OUTSIDE THE DESCRIBED PARAMETERS (code / patches)':
        '  ИЗМЕНЕНИЯ ВНЕ ОПИСАННЫХ ПАРАМЕТРОВ (код / патчи)',
    '  0x{start:06X}–0x{end:06X}  ({n} bytes)':
        '  0x{start:06X}–0x{end:06X}  ({n} байт)',
    '  ... and {n} more blocks':
        '  ... и ещё {n} блоков',
    'changed cells:':
        'изменённые ячейки:',
    '  ... and {n} more cells':
        '  ... и ещё {n} ячеек',
    'Decoded     : {text}':
        'Расшифровка : {text}',
    'Dictionary  : {text}':
        'По словарю  : {text}',
    'Type        : {kind} | {shape}':
        'Тип         : {kind} | {shape}',
    'Category    : {text}':
        'Категория   : {text}',
    'Description : {text}':
        'Описание    : {text}',
    'Original    : {text}':
        'Оригинал    : {text}',
    'Purpose     : {text}':
        'Что делает  : {text}',
    'How to tune : {text}':
        'Как крутить : {text}',
    'Address     : XDF 0x{address:X} -> file 0x{offset:X}, {bits} bits, {sign}, {order}':
        'Адрес       : XDF 0x{address:X} -> файл 0x{offset:X}, {bits} бит, {sign}, {order}',
    'signed':
        'со знаком',
    'unsigned':
        'без знака',
    'Units       : {text}':
        'Единицы     : {text}',
    'Scale       : {text}':
        'Масштаб     : {text}',
    'Could not read the values (address outside the file).':
        'Не удалось прочитать значения (адрес вне файла).',
    'index':
        'индекс',
    'Rows    (Y): {text}':
        'Строки  (Y): {text}',
    'Columns (X): {text}':
        'Столбцы (X): {text}',
    '* — the value differs in the second file (the value from B is shown)':
        '* — значение отличается во втором файле (показано значение из B)',
    'XDF name':
        'Имя в XDF',
    'Name':
        'Название',
    'Category':
        'Категория',
    'Description':
        'Описание',
    'Description (original)':
        'Описание (EN)',
    'Type':
        'Тип',
    'Units':
        'Единицы',
    'XDF address':
        'Адрес XDF',
    'File offset':
        'Смещение в файле',
    'Cells changed':
        'Изменено ячеек',
    'Before -> After':
        'Было -> Стало',
    'Delta min':
        'Дельта мин',
    'Delta max':
        'Дельта макс',
    'Delta avg':
        'Дельта средн',
    'Max change, %':
        'Макс. изменение, %',
    'Scale':
        'Масштаб',
    'What it is':
        'Что это',
    'How to tune':
        'Как крутить',
    '# MS43 firmware comparison':
        '# Сравнение прошивок MS43',
    '* **Parameters changed:** {n}':
        '* **Изменено параметров:** {n}',
    '* **Bytes changed:** {n}':
        '* **Изменено байт:** {n}',
    '| Parameter | What it is | Before → After | Units |':
        '| Параметр | Что это | Было → Стало | Ед. |',
    '## Edits outside XDF maps (code / patches)':
        '## Правки вне карт XDF (код / патчи)',
    '| Offset | Length |':
        '| Смещение | Длина |',
    'Could not read the values.':
        'Не удалось прочитать значения.',
    'rows — {name}':
        'строки — {name}',
    'columns — {name}':
        'столбцы — {name}',
    'was {a}, now {b} {units}':
        'было {a}, стало {b} {units}',
    '{value} {units} — unchanged':
        '{value} {units} — без изменений',
    'change, {units}':
        'изменение, {units}',
    'change':
        'изменение',
    'value, {units}':
        'значение, {units}',
    'value':
        'значение',
    'MS43 firmware comparison':
        'Сравнение прошивок MS43',
    'KB':
        'КБ',
    'offset {label}':
        'смещение {label}',
    'Report created {date}':
        'Отчёт создан {date}',
    'parameters changed':
        'параметров изменено',
    'parameters same':
        'параметров совпало',
    'bytes changed':
        'байт изменено',
    'code edit blocks':
        'блоков правок кода',
    'Search parameters, descriptions, addresses…':
        'Поиск по параметрам, описаниям, адресам…',
    'Parameter':
        'Параметр',
    'Before → After':
        'Было → Стало',
    'Address':
        'Адрес',
    'What it does:':
        'Что делает:',
    'How to tune:':
        'Как крутить:',
    'What the values mean:':
        'Что означают значения:',
    'After the change:':
        'После изменения нужно:',
    '{n} cells changed':
        'изменено {n} яч.',
    'file {offset}':
        'файл {offset}',
    'map {shape} — {changed} of {total} cells changed':
        'карта {shape} — изменено {changed} из {total} ячеек',
    'Edits outside XDF maps (code / patches)':
        'Правки вне карт XDF (код / патчи)',
    'Offset':
        'Смещение',
    'Length, bytes':
        'Длина, байт',
    'Comment':
        'Комментарий',
    'not described in the XDF — probably a machine code edit':
        'не описано в XDF — вероятно, правка машинного кода',
    '  DIFFERENT SOFTWARE VERSIONS (parameters matched by name)':
        '  СРАВНЕНИЕ РАЗНЫХ ВЕРСИЙ ПО (сопоставление по именам параметров)',
    '   XDF {title} v{version}, software {fw}':
        '   XDF {title} v{version}, версия ПО {fw}',
    'Same value      : {n}':
        'Совпадает по значению : {n}',
    'Different       : {n}':
        'Отличается            : {n}',
    'Only in A       : {n}':
        'Есть только в A       : {n}',
    'Only in B       : {n}':
        'Есть только в B       : {n}',
    'Problems        : {n}':
        'Проблемных            : {n}',
    'Physical values are compared, not bytes: conversion formulas may differ':
        'Сравниваются физические величины, а не байты: у разных версий ПО',
    'between software versions.':
        'формулы пересчёта могут отличаться.',
    '... showing {shown} of {total}. Use --limit 0 for the full list.':
        '... показано {shown} из {total}. Используйте --limit 0 для полного списка.',
    '  ONLY IN A ({n}) — the target version has no such settings':
        '  ЕСТЬ ТОЛЬКО В A ({n}) — в целевой версии этих настроек нет',
    '  ... and {n} more':
        '  ... и ещё {n}',
    '  ONLY IN B ({n}) — new settings of the target version':
        '  ЕСТЬ ТОЛЬКО В B ({n}) — новые настройки целевой версии',
    'MS43: {a} ↔ {b} (different versions)':
        'MS43: {a} ↔ {b} (разные версии)',
    'Different software versions':
        'Сравнение разных версий ПО',
    'software {fw}':
        'ПО {fw}',
    'Parameters are matched by name; physical values are compared.':
        'Параметры сопоставлены по именам; сравниваются физические величины.',
    'only in A':
        'только в A',
    'only in B':
        'только в B',
    'Search…':
        'Поиск…',
    'Values':
        'Значения',
    'Notes':
        'Замечания',
    'Different':
        'Отличаются',
    'Only in A':
        'Есть только в A',
    'Only in B':
        'Есть только в B',
    'Problems':
        'Проблемные',
    'IMPORTANT: the program only builds a plan and writes nothing to the firmware. Make all edits by hand in TunerPro and recalculate the checksums there.':
        'ВАЖНО: программа только строит план и ничего не пишет в прошивку. Все правки вносите руками в TunerPro; контрольные суммы пересчитайте там же.',
    '  SETTINGS PORT PLAN BETWEEN SOFTWARE VERSIONS':
        '  ПЛАН ПЕРЕНОСА НАСТРОЕК МЕЖДУ ВЕРСИЯМИ ПО',
    'Source stock          : {name}':
        'Сток исходной версии : {name}',
    'Your tune             : {name}':
        'Ваш тюнинг           : {name}',
    'Source XDF            : {title} v{version}':
        'XDF исходной версии  : {title} v{version}',
    'Target firmware       : {name}':
        'Целевая прошивка     : {name}',
    'Target XDF            : {title} v{version}':
        'XDF целевой версии   : {title} v{version}',
    'Parameters you changed : {n}':
        'Вы изменили параметров : {n}',
    'Safe (by bytes)        : {n}':
        'Безопасно (по байтам)  : {n}',
    'Safe (by name)         : {n}':
        'Безопасно (по имени)   : {n}',
    'With a warning         : {n}':
        'Под предупреждением    : {n}',
    '  ... showing {shown} of {total}':
        '  ... показано {shown} из {total}',
    'SAFE — can be ported one-to-one':
        'БЕЗОПАСНО — можно перенести один в один',
    'SAFE BY NAME — port the physical value by hand':
        'БЕЗОПАСНО ПО ИМЕНИ — переносить физическую величину руками',
    'WARNING — sort it out by hand':
        'ПРЕДУПРЕЖДЕНИЕ — разбирайтесь вручную',
    'Everything is ported by hand in TunerPro — the program only shows the plan.':
        'Всё переносится руками в TunerPro — программа только показывает план.',
    'Settings port: {src} → {dst}':
        'Перенос настроек: {src} → {dst}',
    'Settings port plan between software versions':
        'План переноса настроек между версиями ПО',
    'Source stock:':
        'Сток исходной:',
    'Your tune:':
        'Ваш тюнинг:',
    'Target:':
        'Целевая:',
    'The program only builds a plan and writes nothing to the firmware. Make all edits by hand in TunerPro and recalculate the checksums there.':
        'Программа только строит план и ничего не пишет в прошивку. Все правки вносите руками в TunerPro; контрольные суммы пересчитайте там же.',
    'safe by bytes':
        'безопасно по байтам',
    'safe by name':
        'безопасно по имени',
    'with a warning':
        'под предупреждением',
    'What matched / what is wrong':
        'Чем совпало / что не так',
    'Safe — can be ported one-to-one':
        'Безопасно — можно перенести один в один',
    'Safe by name — port the physical value by hand':
        'Безопасно по имени — переносить физическую величину руками',
    'With a warning — sort it out by hand':
        'Под предупреждением — разбирайтесь вручную',
    'Status':
        'Статус',
    'Your value':
        'Ваше значение',
    'Target now':
        'В целевой сейчас',
    'Name in target':
        'Имя в целевой',
    '  MAP TUNING FROM A WIDEBAND LOG':
        '  ОТКАТКА КАРТЫ ПО ЛОГУ ШЛЗ',
    'Map          : {title}':
        'Карта        : {title}',
    'Mode         : {mode}':
        'Режим        : {mode}',
    'Log samples  : {total}, used {used}':
        'Точек в логе : {total}, использовано {used}',
    '               dropped "{reason}": {n}':
        '               отброшено «{reason}»: {n}',
    'Coverage     : {pct:.0f}% of map cells':
        'Покрытие     : {pct:.0f}% ячеек карты',
    'Changed      : {n} of {total} cells':
        'Изменено     : {n} из {total} ячеек',
    'Correction, % (how much to add to VE; empty — not enough data)':
        'Поправка, % (сколько добавить к наполнению; пусто — данных не хватило)',
    'Samples per cell (more is more reliable)':
        'Точек в ячейке (чем больше, тем надёжнее)',
    'New values ({units})':
        'Новые значения ({units})',
    'units':
        'ед.',
    '· — there is data, but too little or too scattered; the cell is left alone':
        '· — данные есть, но их мало или разброс велик, ячейка не тронута',
    '  WHAT THE MS4X WIKI SAYS ABOUT IT':
        '  ЧТО ОБ ЭТОМ ПИШЕТ MS4X WIKI (перевод)',
    'was {old}, will be {new}; samples {n}':
        'было {old}, станет {new}; точек {n}',
    'correction, %:':
        'поправка, %:',
    'the small number in a cell is how many log samples landed there':
        'маленькая цифра в ячейке — сколько точек лога туда попало',
    'Map tuning {title}':
        'Откатка карты {title}',
    'Map tuning from a wideband log':
        'Откатка карты по логу ШЛЗ',
    'Map:':
        'Карта:',
    'Firmware:':
        'Прошивка:',
    'Log:':
        'Лог:',
    'samples used':
        'точек использовано',
    'samples in the log':
        'точек в логе',
    'map coverage':
        'покрытие карты',
    'cells changed':
        'ячеек изменено',
    'Attention:':
        'Внимание:',
    'Proposed correction':
        'Предлагаемая поправка',
    'The map now':
        'Карта сейчас',
    'Coloured by value — the map before the edit.':
        'Цвет по значению — как карта выглядит до правки.',
    'What the MS4X Wiki says about it':
        'Что об этом пишет MS4X Wiki (перевод)',
    '  PATCHES: {title}':
        '  ПАТЧИ: {title}',
    '  Firmware: {name}':
        '  Прошивка: {name}',
    'Applied {n} of {total}':
        'Применено {n} из {total}',

    # --- pdfreport -------------------------------------------------------------
    'page {n}':
        'стр. {n}',
    'MS43 firmware comparison: {a} / {b}':
        'Сравнение прошивок MS43: {a} / {b}',
    'Parameters changed: {changed}    Same: {same}    Bytes changed: {bytes}    Code edit blocks: {blocks}':
        'Изменено параметров: {changed}    Совпало: {same}    Изменено байт: {bytes}    Блоков правок кода: {blocks}',
    'Value: {value}':
        'Значение: {value}',
    '{shape} · XDF address {address} · file {offset} · {scaling}':
        '{shape} · адрес XDF {address} · файл {offset} · {scaling}',
    'What it does: {text}':
        'Что делает: {text}',
    'How to tune: {text}':
        'Как крутить: {text}',
    '0x{start:06X}–0x{end:06X}   {n} bytes':
        '0x{start:06X}–0x{end:06X}   {n} байт',
    'MS43 maps: {names}':
        'Карты MS43: {names}',
    '{shape} · XDF address 0x{address:X} · file 0x{offset:X} · {scaling}':
        '{shape} · адрес XDF 0x{address:X} · файл 0x{offset:X} · {scaling}',
    'MS43 settings port plan':
        'План переноса настроек MS43',
    'Source stock: {name}':
        'Сток исходной версии: {name}',
    'Your tune: {name}  ({xdf})':
        'Ваш тюнинг: {name}  ({xdf})',
    'Target firmware: {name}  ({xdf})':
        'Целевая прошивка: {name}  ({xdf})',
    'Safe by bytes: {bytes}    Safe by name: {name}    With a warning: {warned}':
        'Безопасно по байтам: {bytes}    Безопасно по имени: {name}    Под предупреждением: {warned}',
    'in the target version: {name}':
        'в целевой версии: {name}',
    'reportlab is not installed. Run: python -m pip install reportlab':
        'Не установлен reportlab. Выполните: python -m pip install reportlab',

    # --- cli -------------------------------------------------------------------
    'No XDF given: add -x path\\to\\file.xdf or set the MS43_XDF environment variable.':
        'Не указан XDF: добавьте -x путь\\к\\файлу.xdf или задайте переменную окружения MS43_XDF.',
    'XDF file not found: {path}':
        'Не найден XDF-файл: {path}',
    'BIN file not found: {path}':
        'Не найден BIN-файл: {path}',
    'HTML report: {path}':
        'HTML-отчёт: {path}',
    'CSV report: {path}':
        'CSV-отчёт: {path}',
    'JSON report: {path}':
        'JSON-отчёт: {path}',
    'Markdown report: {path}':
        'Markdown-отчёт: {path}',
    'PDF not created: {error}':
        'PDF не создан: {error}',
    'PDF report: {path}':
        'PDF-отчёт: {path}',
    'Nothing found for: {query}':
        'Ничего не найдено по запросу: {query}',
    '{n} matches found, showing the first {max}.':
        'Найдено {n} совпадений, показываю первые {max}.',
    'Refine the query or raise --max.':
        'Уточните запрос или увеличьте --max.',
    '... and more. Over {n} matches, refine the query or use --limit 0.':
        '... и другие. Всего совпадений больше {n}, уточните запрос или укажите --limit 0.',
    '    value: {value}':
        '    значение: {value}',
    '    XDF address 0x{addr:X}':
        '    адрес XDF 0x{addr:X}',
    'Nothing found.':
        'Ничего не найдено.',
    'Found: {n}':
        'Найдено: {n}',
    'Categories in this XDF:':
        'Категории в этом XDF:',
    '... showing the first {n}. Use --limit 0 for the full list.':
        '... показаны первые {n}. Используйте --limit 0 для полного списка.',
    'Value':
        'Значение',
    'Exported {n} parameters to {path}':
        'Выгружено {n} параметров в {path}',
    '     original (English):':
        '     оригинал (English):',
    'Downloading MS4X Wiki pages (needs access to ms4x.net)…':
        'Качаю страницы MS4X Wiki (нужен доступ к ms4x.net, возможно через VPN)…',
    'Pages downloaded: {n}':
        'Загружено страниц: {n}',
    'Cache: {path}':
        'Кэш: {path}',
    '  failed: {name} — {error}':
        '  не удалось: {name} — {error}',
    'There is no local reference. On a machine with access to the site run:':
        'Локального справочника нет. Выполните на машине с доступом к сайту:',
    'MS4X Wiki reference, snapshot of {date}':
        'Справочник MS4X Wiki, снимок от {date}',
    'Source: {source}   Folder: {folder}':
        'Источник: {source}   Папка: {folder}',
    '  {n:>4} sections   {title}   ({name})':
        '  {n:>4} разделов   {title}   ({name})',
    '  MS4X WIKI WARNINGS — "how not to break anything"':
        '  ПРЕДУПРЕЖДЕНИЯ ИЗ MS4X WIKI — «как не убить ничего»',
    'Total: {n} warnings':
        'Всего: {n} предупреждений',
    'The reference does not mention parameter {name}.':
        'В справочнике нет упоминаний параметра {name}.',
    'Values of parameter {name}:':
        'Значения параметра {name}:',
    'What the MS4X Wiki says about {name}:':
        'Что MS4X Wiki пишет про {name} (перевод):',
    'Page "{name}" not found. List: ms43diff wiki --list':
        'Страница «{name}» не найдена. Список: ms43diff wiki --list',
    '  {url}   (snapshot {date})':
        '  {url}   (снимок {date})',
    'Sections found: {n}':
        'Найдено разделов: {n}',
    'MS4X Wiki reference (local copy).':
        'Справочник MS4X Wiki (локальная копия).',
    'Snapshot of {date}, pages: {pages}, parameters linked: {params}':
        'Снимок от {date}, страниц: {pages}, параметров связано: {params}',
    '  ms43diff wiki --list              list of pages':
        '  ms43diff wiki --list              список страниц',
    '  ms43diff wiki "lambda"            full-text search':
        '  ms43diff wiki "lambda"            поиск по тексту',
    '  ms43diff wiki --page Siemens_MS43 show a whole page':
        '  ms43diff wiki --page Siemens_MS43 показать страницу целиком',
    '  ms43diff wiki --param c_conf_cat  what the wiki says about a parameter':
        '  ms43diff wiki --param c_conf_cat  что вики пишет про параметр',
    '  ms43diff wiki --cautions          all warnings':
        '  ms43diff wiki --cautions          все предупреждения',
    '  ms43diff wiki --download          update the copy from the site':
        '  ms43diff wiki --download          обновить копию с сайта',
    '{file} has no <XDFPATCH> entries. This command needs a patchlist XDF (e.g. Siemens_MS43_MS430069_Community_Patchlist_*.xdf).':
        'В файле {file} нет записей <XDFPATCH>. Для этой команды нужен patchlist-XDF (например Siemens_MS43_MS430069_Community_Patchlist_*.xdf).',
    'Title         : {text}':
        'Название      : {text}',
    'File version  : {text}':
        'Версия файла  : {text}',
    'Author        : {text}':
        'Автор         : {text}',
    'Description   : {text}':
        'Описание      : {text}',
    'Region size   : 0x{size:X} ({kb} KB)':
        'Размер региона: 0x{size:X} ({kb} КБ)',
    'Categories    : {n}':
        'Категорий     : {n}',
    'Objects       : {n}  (tables {tables}, constants {consts}, of them axes {axes})':
        'Объектов      : {n}  (таблиц {tables}, констант {consts}, из них осей {axes})',
    'Patches       : {n}':
        'Патчей        : {n}',
    'Size          : {n} bytes ({kb} KB)':
        'Размер        : {n} байт ({kb} КБ)',
    'Offset        : {label}, fit {pct:.1f}%':
        'Смещение      : {label}, попадание {pct:.1f}%',
    'Readable      : {ok} of {total} objects':
        'Читается      : {ok} из {total} объектов',
    'Calib. header : {text}':
        'Шапка калибр. : {text}',
    'Software      : {fw}':
        'Версия ПО     : {fw}',
    'unknown':
        'не определена',
    'WARNING: {text}':
        'ВНИМАНИЕ: {text}',
    'At least two .bin files are needed':
        'Нужно минимум два .bin файла',
    '  COMPARING SEVERAL FIRMWARE FILES':
        '  СРАВНЕНИЕ НЕСКОЛЬКИХ ПРОШИВОК',
    'Differing parameters in total: {n}':
        'Всего различающихся параметров: {n}',
    'Columns in the log: {cols}, rows: {rows}':
        'Столбцов в логе: {cols}, строк: {rows}',
    'If something is detected wrong, set it by hand: --col-rpm / --col-load / --col-lambda / --col-target':
        'Если распознано неверно, укажите вручную: --col-rpm / --col-load / --col-lambda / --col-target',
    'Could not find these columns in the log: {cols}':
        'Не удалось найти в логе столбцы: {cols}',
    'See the list: ms43diff vetune LOG -b FIRMWARE -m MAP --columns':
        'Посмотрите список: ms43diff vetune ЛОГ -b ПРОШИВКА -m КАРТА --columns',
    'Several maps match, be more specific:':
        'Уточните карту, подходит несколько:',
    'Map "{name}" not found in this XDF.':
        'Карта «{name}» не найдена в этом XDF.',
    'Refused: cannot write over the source firmware.':
        'Отказ: нельзя писать поверх исходной прошивки.',
    'File {path} already exists. Add --force.':
        'Файл {path} уже есть. Добавьте --force.',
    'Cells written: {n}':
        'Записано ячеек: {n}',
    ', did not fit: {n}':
        ', не влезло: {n}',
    'New file: {path}':
        'Новый файл: {path}',
    'CHECKSUMS ARE NOT RECALCULATED — do it in TunerPro.':
        'КОНТРОЛЬНЫЕ СУММЫ НЕ ПЕРЕСЧИТАНЫ — сделайте это в TunerPro.',
    'Compare Siemens MS43 (BMW M52TU/M54) firmware using an XDF definition, with decoded parameter names.':
        'Сравнение прошивок Siemens MS43 (BMW M52TU/M54) по XDF-описанию с расшифровкой на русском.',
    'interface language (default: saved setting or system language)':
        'язык интерфейса (по умолчанию — сохранённый или язык системы)',
    '.xdf definition file (can be set with the MS43_XDF variable)':
        'файл описания .xdf (можно задать переменной MS43_XDF)',
    'include axis breakpoint tables (ldp_*)':
        'учитывать таблицы опорных точек осей (ldp_*)',
    'regular expression on name/description':
        'регулярное выражение по имени/описанию',
    'category filter (English or Russian)':
        'фильтр по категории (рус. или англ.)',
    'compare two firmware files':
        'сравнить две прошивки',
    'first firmware (e.g. stock)':
        'первая прошивка (например, сток)',
    'second firmware (e.g. tune)':
        'вторая прошивка (например, тюнинг)',
    'save an HTML report':
        'сохранить HTML-отчёт',
    'save a CSV report':
        'сохранить CSV-отчёт',
    'save a JSON report':
        'сохранить JSON-отчёт',
    'save a Markdown report':
        'сохранить Markdown-отчёт',
    'save a PDF report (with coloured maps)':
        'сохранить PDF-отчёт (с цветными картами)',
    'do not draw maps in the PDF (shorter and lighter)':
        'не рисовать карты в PDF (короче и легче)',
    'how many parameters to print to the console (0 — all)':
        'сколько параметров печатать в консоль (0 — все)',
    'show changed map cells':
        'показывать изменённые ячейки карт',
    'show the original description':
        'показывать оригинал описания',
    'do not show checksum changes':
        'не показывать изменения контрольных сумм',
    'skip the byte-by-byte scan':
        'не делать побайтовый скан',
    'merge byte blocks separated by at most N bytes':
        'склеивать блоки байтов, разделённые не более чем N байтами',
    'report files only':
        'только файлы отчётов',
    'show one map/constant with its axes':
        'показать одну карту/константу с осями',
    'parameter name or part of it (regex)':
        'имя параметра или часть имени (регулярка)',
    'second firmware — mark the differences':
        'вторая прошивка — отметить отличия',
    'maximum maps at a time':
        'максимум карт за раз',
    'save the maps to a coloured PDF':
        'сохранить карты в PDF с раскраской',
    'search parameters by English or Russian text':
        'искать параметры по русскому или английскому тексту',
    'what to search for':
        'что ищем',
    'also show the values from the firmware':
        'показать заодно значения из прошивки',
    'list parameters':
        'перечислить параметры',
    'show the values from the firmware':
        'показать значения из прошивки',
    'list the categories':
        'вывести список категорий',
    'export all firmware values to CSV':
        'выгрузить все значения прошивки в CSV',
    'compare firmware of DIFFERENT software versions (two XDFs)':
        'сравнить прошивки РАЗНЫХ версий ПО (два XDF)',
    'XDF for the first firmware':
        'XDF для первой прошивки',
    'XDF for the second firmware':
        'XDF для второй прошивки',
    'include checksums':
        'учитывать контрольные суммы',
    'plan for porting edits to firmware of another version (no writing)':
        'план переноса правок в прошивку другой версии ПО (без записи)',
    'stock of the source version (reference)':
        'сток исходной версии (эталон)',
    'your tuned firmware of the same version':
        'ваша доработанная прошивка той же версии',
    'firmware of the target version to port into':
        'прошивка целевой версии, куда переносим',
    'XDF of the source version':
        'XDF исходной версии',
    'XDF of the target version':
        'XDF целевой версии',
    'offline MS4X Wiki reference':
        'офлайн-справочник MS4X Wiki',
    'what to search for in the reference':
        'что искать в справочнике',
    'download/update the copy of the site (needs access to ms4x.net)':
        'скачать/обновить копию сайта (нужен доступ к ms4x.net)',
    'list of pages':
        'список страниц',
    'show a whole page':
        'показать страницу целиком',
    'what the wiki says about this XDF parameter':
        'что вики пишет про этот параметр XDF',
    'all "how not to break anything" warnings':
        'все предупреждения «как не убить ничего»',
    'also show the English original':
        'показывать ещё и оригинал на английском',
    'tune a map from a wideband lambda log':
        'откатать карту по логу ШЛЗ',
    'CSV log with a wideband sensor':
        'CSV-лог с широкополосным зондом',
    '.xdf definition file':
        'файл описания .xdf',
    'firmware':
        'прошивка',
    'name of the VE map (e.g. ip_map_ve_1__map__n)':
        'имя карты наполнения (например ip_map_ve_1__map__n)',
    'where the correction comes from':
        'откуда брать поправку',
    'target lambda if the log has none':
        'целевая лямбда, если её нет в логе',
    'samples needed in a cell before it is touched':
        'сколько точек нужно в ячейке, чтобы её трогать',
    'maximum correction per pass (0.25 = ±25%%)':
        'максимальная поправка за проход (0.25 = ±25%%)',
    'maximum spread within a cell':
        'предельный разброс внутри ячейки',
    'sensor reading shift, in samples':
        'сдвиг показаний зонда, отсчётов',
    'no smoothing':
        'не сглаживать',
    'max rpm jump between samples (larger — the sample is treated as transient and dropped)':
        'макс. скачок оборотов между отсчётами (больше — точка считается переходной и отбрасывается)',
    'max load jump between samples':
        'макс. скачок нагрузки между отсчётами',
    'skip samples colder than this coolant temperature':
        'не брать точки холоднее этой температуры ОЖ',
    'save a visual report':
        'сохранить наглядный отчёт',
    'write the new map to a NEW .bin':
        'записать новую карту в НОВЫЙ .bin',
    'only show which columns were found in the log':
        'только показать, какие столбцы нашлись в логе',
    'start the window interface':
        'запустить оконный интерфейс',
    'start the MCP server for an AI assistant (stdio)':
        'запустить MCP-сервер для нейросети (stdio)',
    '.bin firmware file':
        'файл прошивки .bin',
    'check which patches are applied':
        'проверить, какие патчи применены',
    'patchlist .xdf (can be set with the MS43_XDF variable)':
        'patchlist .xdf (можно задать переменной MS43_XDF)',
    'information about the XDF and the firmware':
        'сведения о XDF и прошивке',
    'compare several firmware files in one table':
        'сравнить сразу несколько прошивок таблицей',
    '... showing {shown} of {total}':
        '... показано {shown} из {total}',

    # --- mcpserver -------------------------------------------------------------
    'Firmware and/or XDF not set. Start the server with --xdf PATH.xdf --bin PATH.bin':
        'Не заданы прошивка и/или XDF. Запустите сервер с --xdf ПУТЬ.xdf --bin ПУТЬ.bin',
    'Switch values:':
        'Значения переключателя:',
    'source: {url}':
        'источник: {url}',
    '({n} more mentions in the wiki)':
        '(ещё {n} упоминаний в вики)',
    'Similar names: {names}':
        'Похожие имена: {names}',
    'Parameter "{name}" not found in the XDF.':
        'Параметр «{name}» в XDF не найден.',
    'Name: {text}':
        'Название: {text}',
    'Type: {kind} ({shape})':
        'Тип: {kind} ({shape})',
    'Category: {text}':
        'Категория: {text}',
    'Description: {text}':
        'Описание: {text}',
    'Original: {text}':
        'Оригинал: {text}',
    'Address: XDF 0x{address:X} → file 0x{offset:X}, {bits} bits, {sign}, {order}':
        'Адрес: XDF 0x{address:X} → файл 0x{offset:X}, {bits} бит, {sign}, {order}',
    'Units: {text}':
        'Единицы: {text}',
    'Scale: {text}':
        'Масштаб: {text}',
    'Value in the firmware: {value}':
        'Значение в прошивке: {value}',
    '## MS4X Wiki reference':
        '## Справочник MS4X Wiki',
    'Map "{name}" not found.':
        'Карта «{name}» не найдена.',
    'Could not read "{name}" (address outside the file?).':
        'Не удалось прочитать «{name}» (адрес вне файла?).',
    'Map {shape} is too big to print ({n} cells). Use get_param for a summary.':
        'Карта {shape} слишком большая для вывода ({n} ячеек). Используйте get_param для сводки.',
    'values in {units}; rows — {rows}; columns — {cols}':
        'значения в {units}; строки — {rows}; столбцы — {cols}',
    'The server has no firmware loaded.':
        'Сервер не инициализирован прошивкой.',
    'Firmware: {name}':
        'Прошивка: {name}',
    'Software version: {fw}':
        'Версия ПО: {fw}',
    'Offset: {label}':
        'Смещение: {label}',
    'Objects in the XDF: {n}':
        'Объектов в XDF: {n}',
    'MS4X Wiki reference: snapshot {date}, {n} pages':
        'Справочник MS4X Wiki: снимок {date}, {n} страниц',
    'Categories (number of parameters):':
        'Категории (число параметров):',
    '… there is more, showing the first {n}. Refine the filter.':
        '… ещё есть, показаны первые {n}. Уточните filter.',
    'Nothing found for these filters.':
        'Ничего не найдено по заданным фильтрам.',
    'Give name — the parameter name.':
        'Укажите name — имя параметра.',
    'Give name — the map name.':
        'Укажите name — имя карты.',
    'Give name and value.':
        'Укажите name и value.',
    'The reference is not loaded.':
        'Справочник не загружен.',
    'The wiki has no value meanings for {name}.':
        'Для {name} в вики нет расшифровки значений.',
    'value must be a number.':
        'value должно быть числом.',
    'The wiki has no value {key} for {name}. Available: {avail}':
        'Значения {key} у {name} в вики нет. Есть: {avail}',
    '(original: {text})':
        '(оригинал: {text})',
    'Give query.':
        'Укажите query.',
    'The reference is not loaded. Update it: ms43diff wiki --download':
        'Справочник не загружен. Обновите: ms43diff wiki --download',
    'Page not found. Available: {avail}':
        'Страница не найдена. Есть: {avail}',
    'MS4X Wiki warnings ("how not to break anything"):':
        'Предупреждения MS4X Wiki («как не убить ничего»):',
    'Error: {error}':
        'Ошибка: {error}',

    # --- mcpinstall ------------------------------------------------------------
    '{exe} not found next to {here}. Keep both .exe files in the same folder.':
        'Рядом с программой ({here}) нет {exe}. Держите оба .exe в одной папке.',
    'Cannot read {path}: {error}':
        'Не удалось прочитать {path}: {error}',
    '{path} is not valid JSON ({error}). Fix or remove it first; nothing was changed.':
        '{path} — некорректный JSON ({error}). Исправьте или удалите его; ничего не изменено.',
    '{path} has an unexpected structure; nothing was changed.':
        'У {path} неожиданная структура; ничего не изменено.',
    '{kind} file not found: {path}':
        'Не найден файл {kind}: {path}',
    'The "{name}" server was updated in Claude Desktop.':
        'Сервер «{name}» в Claude Desktop обновлён.',
    'The "{name}" server was added to Claude Desktop.':
        'Сервер «{name}» добавлен в Claude Desktop.',
    'Config: {path}':
        'Конфиг: {path}',
    'Previous version saved as: {path}':
        'Прежняя версия сохранена как: {path}',
    'XDF: {path}':
        'XDF: {path}',
    'Firmware: {path}':
        'Прошивка: {path}',
    'Quit Claude Desktop completely (tray icon → Quit) and start it again. Then ask in a chat, e.g. "What is my rev limit?"':
        'Полностью закройте Claude Desktop (значок в трее → Quit) и запустите снова. Потом спросите в чате, например: «Какая у меня отсечка?»',
    'The "{name}" server is not connected; nothing to remove.\nConfig: {path}':
        'Сервер «{name}» не подключён — удалять нечего.\nКонфиг: {path}',
    'The "{name}" server was removed from Claude Desktop.\nConfig: {path}\nRestart Claude Desktop for the change to take effect.':
        'Сервер «{name}» удалён из Claude Desktop.\nКонфиг: {path}\nПерезапустите Claude Desktop, чтобы изменение вступило в силу.',

    # --- mcp_main --------------------------------------------------------------
    'Choose the XDF definition':
        'Выберите файл описания XDF',
    'TunerPro definitions':
        'Определения TunerPro',
    'All files':
        'Все файлы',
    'Choose the firmware file':
        'Выберите файл прошивки',
    'Firmware files':
        'Прошивки',
    'Path to the .xdf file: ':
        'Путь к файлу .xdf: ',
    'Path to the .bin file: ':
        'Путь к файлу .bin: ',
    'Cancelled: both an .xdf and a .bin file are needed.':
        'Отменено: нужны и .xdf, и .bin.',
    'ms43diff MCP server: MS43 firmware data and the MS4X Wiki knowledge base for an AI assistant (read-only).':
        'MCP-сервер ms43diff: данные прошивки MS43 и база знаний MS4X Wiki для нейросети (только чтение).',
    'connect the server to Claude Desktop':
        'подключить сервер к Claude Desktop',
    'disconnect the server from Claude Desktop':
        'отключить сервер от Claude Desktop',
    '.xdf and .bin for --install':
        '.xdf и .bin для --install',

    # --- gui -------------------------------------------------------------------
    'MS43 AI-Tuner {version} — BMW MS43 firmware comparison':
        'MS43 AI-Tuner {version} — сравнение прошивок BMW MS43',
    'Nothing about this parameter in the local reference.\nIf the reference is not downloaded yet: the "Reference" tab, the "Update from site" button.\n':
        'В локальном справочнике про этот параметр ничего не нашлось.\nЕсли справочник ещё не скачан — вкладка «Справочник», кнопка «Обновить с сайта».\n',
    'Reference — {name}':
        'Справочник — {name}',
    'Done':
        'Готово',
    'Saved:\n{path}\n\nOpen it?':
        'Сохранено:\n{path}\n\nОткрыть?',
    'Choose a match':
        'Выбор соответствия',
    'Connect to Claude Desktop':
        'Подключение к Claude Desktop',
    'XDF definition':
        'Описание XDF',
    'Now: connected':
        'Сейчас: подключено',
    'Now: not connected':
        'Сейчас: не подключено',
    'AI assistant':
        'Нейросеть',
    'Language changed. Results were cleared — run them again.':
        'Язык изменён. Результаты очищены — запустите расчёт заново.',
    'Files (the same software version)':
        'Файлы (одна и та же версия ПО)',
    'Firmware A (stock)':
        'Прошивка A (сток)',
    'Firmware B (tune)':
        'Прошивка B (тюнинг)',
    'Comparing…':
        'Сравниваю…',
    'Done: {n} changes':
        'Готово: {n} изменений',
    'before → after: {value}':
        'было → стало: {value}',
    'Saved: {path}':
        'Сохранено: {path}',
    'Report saved:\n{path}\n\nOpen it?':
        'Отчёт сохранён:\n{path}\n\nОткрыть?',
    'Firmware A':
        'Прошивка A',
    'XDF of version A':
        'XDF версии A',
    'Firmware B':
        'Прошивка B',
    'XDF of version B':
        'XDF версии B',
    'Comparing different versions…':
        'Сравниваю разные версии…',
    'Source version (port from)':
        'Исходная версия (откуда переносим)',
    'Source version XDF':
        'XDF исходной версии',
    'Source version stock':
        'Сток исходной версии',
    'Your firmware':
        'Ваша прошивка',
    'Target version (port to)':
        'Целевая версия (куда переносим)',
    'Target version XDF':
        'XDF целевой версии',
    'Target firmware':
        'Целевая прошивка',
    'Building the port plan…':
        'Строю план переноса…',
    'Plan ready: {safe} safe, {warned} with a warning':
        'План готов: {safe} безопасных, {warned} под предупреждением',
    'Status: {text}':
        'Статус: {text}',
    'Your value: {value}':
        'Ваше значение: {value}',
    'Port — {name}':
        'Перенос — {name}',
    'Files':
        'Файлы',
    'Checking patches…':
        'Проверяю патчи…',
    'Searching…':
        'Ищу…',
    'Found: {n}  (double-click — show the map)':
        'Найдено: {n}  (двойной клик — показать карту)',
    'Log (CSV)':
        'Лог (CSV)',
    'Settings':
        'Настройки',
    '2D maps found: {n}':
        'Найдено двумерных карт: {n}',
    'Columns: {cols}, rows: {rows}':
        'Столбцов: {cols}, строк: {rows}',
    'Log columns':
        'Столбцы лога',
    'Calculating the correction…':
        'Считаю поправку…',
    'Correction calculated':
        'Поправка посчитана',
    'Cells written: {n}\nFile: {path}\n\nChecksums were NOT recalculated.':
        'Записано ячеек: {n}\nФайл: {path}\n\nКонтрольные суммы НЕ пересчитаны.',
    'Sections with warnings: {n}, lines: {lines}':
        'Разделов с предупреждениями: {n}, строк: {lines}',
    'Downloading the reference…':
        'Качаю справочник…',
    'Choose a file':
        'Выберите файл',
    'Copy name':
        'Копировать имя',
    'Copy row (all columns)':
        'Копировать строку (все столбцы)',
    'What the values mean':
        'Что означают значения',
    'After the change':
        'После изменения нужно',
    'What it does':
        'Что делает',
    'was {a} → now {b} ({delta}) {units}':
        'было {a} → стало {b} ({delta}) {units}',
    'Save the map as PDF':
        'Сохранить карту в PDF',
    'Files missing':
        'Не хватает файлов',
    'Choose the XDF and the firmware.':
        'Выберите XDF и прошивку.',
    'Ready':
        'Готово',
    'Connect to Claude Desktop…':
        'Подключить к Claude Desktop…',
    'Disconnect from Claude Desktop':
        'Отключить от Claude Desktop',
    'Remove the ms43diff server from Claude Desktop? Other servers and settings are not touched.':
        'Удалить сервер ms43diff из Claude Desktop? Другие серверы и настройки не затрагиваются.',
    'Error':
        'Ошибка',
    '{error}\n\nDetails were written to the log:\n{path}':
        '{error}\n\nПодробности записаны в журнал:\n{path}',
    'Save as':
        'Сохранить как',
    'Choose the XDF and both firmware files.':
        'Выберите XDF и обе прошивки.',
    'No data':
        'Нет данных',
    'Run the comparison first.':
        'Сначала выполните сравнение.',
    'File not created':
        'Файл не создан',
    'The file did not appear: {path}\nLog: {log}':
        'Файл не появился: {path}\nЖурнал: {log}',
    'Here each firmware has its own XDF. Parameters are matched by name,\nphysical values are compared, not bytes — conversion formulas and\naddresses may differ between software versions.':
        'Здесь у каждой прошивки свой XDF. Параметры сопоставляются по именам,\nсравниваются физические величины, а не байты — у разных версий ПО\nформулы пересчёта и адреса могут отличаться.',
    'Choose both XDFs and both firmware files.':
        'Выберите оба XDF и обе прошивки.',
    'Different: {diff} · same: {same} · only in A: {a} · only in B: {b}':
        'Отличается: {diff} · совпадает: {same} · только в A: {a} · только в B: {b}',
    'ms43_versions':
        'ms43_versii',
    'reference: your edits are found against it':
        'эталон: относительно него ищутся ваши правки',
    'Needed: the source version XDF, its stock, your firmware,\nthe target version XDF and the target firmware.':
        'Нужны: XDF исходной версии, её сток, ваша прошивка,\nXDF целевой версии и целевая прошивка.',
    'You changed: {n} · safe by bytes: {bytes} · safe by name: {name} · with a warning: {warned}':
        'Вы изменили: {n} · безопасно по байтам: {bytes} · безопасно по имени: {name} · под предупреждением: {warned}',
    'Name in the target version: {name}':
        'Имя в целевой версии: {name}',
    'What matched:':
        'Чем совпало:',
    'What is wrong:':
        'Что не так:',
    'This cannot be ported automatically — sort it out by hand.':
        'Автоматически такое не переносится — разбирайтесь вручную.',
    'Build the plan first.':
        'Сначала постройте план.',
    'e.g. Siemens_MS43_MS430069_Community_Patchlist_*.xdf':
        'например Siemens_MS43_MS430069_Community_Patchlist_*.xdf',
    'Choose the patchlist XDF and the firmware.':
        'Выберите patchlist XDF и прошивку.',
    'now in the firmware: {value}':
        'сейчас в прошивке: {value}',
    'TunerPro export or your wideband controller file':
        'экспорт из TunerPro или файл вашего ШЛЗ',
    'No XDF':
        'Нет XDF',
    'Choose the XDF file first.':
        'Сначала выберите файл XDF.',
    'No log':
        'Нет лога',
    'Choose the CSV log file.':
        'Выберите CSV-файл лога.',
    'The XDF, the firmware and the log are needed.':
        'Нужны XDF, прошивка и лог.',
    'No map chosen':
        'Не выбрана карта',
    'Press "Find maps" and choose a map.':
        'Нажмите «Найти карты» и выберите карту.',
    'Calculate the correction first.':
        'Сначала посчитайте поправку.',
    'ms43_ve_tuning':
        'ms43_otkatka',
    'Confirmation':
        'Подтверждение',
    'A NEW firmware file with the changed map will be created.\nThe source file is not changed.\n\nCells to change: {n}\n\nIMPORTANT: checksums are not recalculated — do it in TunerPro.':
        'Будет создан НОВЫЙ файл прошивки с изменённой картой.\nИсходный файл не меняется.\n\nЯчеек к изменению: {n}\n\nВАЖНО: контрольные суммы не пересчитываются — сделайте это в TunerPro.',
    'Refused':
        'Отказ',
    'Cannot write over the source firmware.':
        'Нельзя писать поверх исходной прошивки.',
    'MS4X Wiki, snapshot of {date} · pages {pages} · parameters linked {params} · source {source}':
        'MS4X Wiki, снимок от {date} · страниц {pages} · параметров связано {params} · источник {source}',
    'Updating the reference':
        'Обновление справочника',
    'The program will download pages from ms4x.net into the local copy.\nIt needs access to the site.\n\nContinue?':
        'Программа скачает страницы с ms4x.net в локальную копию.\nНужен доступ к сайту (у многих — только через VPN).\n\nПродолжить?',
    'showing {shown} of {total}':
        'показано {shown} из {total}',
    'rows: {n}':
        'строк: {n}',
    'difference':
        'разница',
    'values A':
        'значения A',
    'values B':
        'значения B',
    'PDF unavailable':
        'PDF недоступен',
    '★ {name}   (similarity {score:.2f})':
        '★ {name}   (похожесть {score:.2f})',
    'Log':
        'Журнал',
    'Log file:\n{path}':
        'Файл журнала:\n{path}',
    'Cells':
        'Ячеек',
    'Parameters changed: {changed} · same: {same} · bytes changed: {bytes} · code edit blocks: {blocks}':
        'Изменено параметров: {changed} · совпало: {same} · изменено байт: {bytes} · блоков правок кода: {blocks}',
    'ms43_report':
        'ms43_otchet',
    'Could not save':
        'Не удалось сохранить',
    'Source parameter':
        'Параметр исходной',
    'Target parameter':
        'Параметр целевой',
    'Can be ported one-to-one: enter the same value in TunerPro into the parameter with the same name.':
        'Можно перенести один в один: впишите то же значение в TunerPro в одноимённый параметр.',
    'Port the PHYSICAL value (what TunerPro shows), not the raw bytes — the format differs in the target version.':
        'Переносите ФИЗИЧЕСКУЮ величину (то, что показывает TunerPro), а не сырые байты — формат в целевой версии отличается.',
    'ms43_port':
        'ms43_perenos',
    'Patch':
        'Патч',
    'This XDF has no <XDFPATCH> entries. A patchlist file is needed, not a regular definition.':
        'В этом XDF нет записей <XDFPATCH>. Нужен patchlist-файл, а не обычное определение.',
    'Logs':
        'Логи',
    'The log cannot be read':
        'Лог не читается',
    'Map "{name}" not found in the XDF':
        'Карта «{name}» не найдена в XDF',
    'These columns were not found in the log: {cols}. Press "Log columns" to see what is there.':
        'В логе не нашлись столбцы: {cols}. Нажмите «Столбцы лога», чтобы посмотреть, что там есть.',
    'Used {used} of {total} samples · coverage {pct:.0f}% · {n} cells changed':
        'Использовано {used} из {total} точек · покрытие {pct:.0f}% · изменено {n} ячеек',
    'There is no local copy of the reference. Press "Update from site" (needs access to ms4x.net).':
        'Локальной копии справочника нет. Нажмите «Обновить с сайта» (нужен доступ к ms4x.net, возможно через VPN).',
    'original (English):':
        'оригинал (English):',
    'Pages downloaded: {n}\nCache: {path}':
        'Загружено страниц: {n}\nКэш: {path}',
    'Browse…':
        'Обзор…',
    'Filter:':
        'Фильтр:',
    'Close':
        'Закрыть',
    'As text':
        'Текстом',
    'Save PDF…':
        'Сохранить PDF…',
    'Parameter of the source version:':
        'Параметр исходной версии:',
    'Choose what to port it to in the target firmware.\nOn top — similar names with the same map size.':
        'Выберите, во что его перенести в целевой прошивке.\nСверху — похожие по имени и совпадающие по размеру карты.',
    'Search:':
        'Поиск:',
    'Choose':
        'Выбрать',
    'Skip parameter':
        'Пропустить параметр',
    'Cancel':
        'Отмена',
    "The AI assistant in Claude Desktop will be able to read this firmware and the MS4X Wiki through ms43diff (read-only). Claude Desktop's config is edited for you; other servers and settings are kept, and a .bak copy is saved.":
        'Нейросеть в Claude Desktop сможет читать эту прошивку и MS4X Wiki через ms43diff (только чтение). Конфиг Claude Desktop правится автоматически; другие серверы и настройки сохраняются, рядом кладётся копия .bak.',
    'Connect':
        'Подключить',
    'Show log':
        'Показать журнал',
    'HTML page':
        'HTML-страница',
    'CSV for Excel':
        'CSV для Excel',
    'PDF document':
        'PDF-документ',
    'Compare':
        'Сравнить',
    'Comparison':
        'Сравнение',
    'include axes (ldp_*)':
        'учитывать оси (ldp_*)',
    'show checksums':
        'показывать контрольные суммы',
    'Save HTML':
        'Сохранить HTML',
    'Save CSV':
        'Сохранить CSV',
    'Save PDF':
        'Сохранить PDF',
    'double-click a row — the map with highlighting':
        'двойной клик по строке — карта с подсветкой',
    'What the parameter is, what the values mean and what MS4X Wiki says':
        'Что это за параметр, что означают значения и что пишет MS4X Wiki',
    'Different versions':
        'Разные версии',
    'Settings port':
        'Перенос настроек',
    'Builds a PLAN for porting your edits to firmware of another software version and writes nothing.\nEdits are found as the difference between the source version stock and your firmware.\n"Safe" means a byte match (copy 1:1) or a name match (port the value by hand).\nEverything else gets a warning. Make all edits by hand in TunerPro.':
        'Строит ПЛАН переноса ваших правок в прошивку другой версии ПО и ничего не пишет.\nПравки определяются как разница между стоком исходной версии и вашей прошивкой.\n«Безопасно» — совпадение по байтам (копировать 1:1) или по имени (переносить величину руками).\nОстальное под предупреждением. Все правки вносите руками в TunerPro.',
    'Build the plan':
        'Построить план',
    'Save HTML report':
        'Сохранить отчёт HTML',
    'the program only shows the plan; you edit by hand in TunerPro. Double-click a row for details':
        'программа только показывает план; правите руками в TunerPro. Двойной клик по строке — подробности',
    'Patches':
        'Патчи',
    'Check':
        'Проверить',
    'Browse':
        'Просмотр',
    'Find':
        'Найти',
    'English or Russian: rev limit, knock, lambda…':
        'можно по-русски: отсечка, детонация, лямбда…',
    'MS4X Wiki reference for the selected parameter':
        'Справочник MS4X Wiki по выделенному параметру',
    'VE tuning':
        'Откатка по ШЛЗ',
    'Calculates a VE map correction from a wideband lambda log:\nif the mixture is leaner than the target, there was more air than the ECU thought.\nCells with too few samples are left alone. Explanations and\nwarnings come from the offline MS4X Wiki copy.':
        'Считает поправку к карте наполнения по логу широкополосного зонда:\nесли смесь беднее заданной — воздуха было больше, чем думал блок.\nЯчейки, куда попало мало точек, не трогаются. Пояснения и\nпредупреждения берутся из офлайн-копии MS4X Wiki.',
    'Map':
        'Карта',
    'Find maps':
        'Найти карты',
    'Mode':
        'Режим',
    'target lambda':
        'целевая лямбда',
    'min. samples per cell':
        'мин. точек в ячейке',
    'max. correction, %':
        'макс. поправка, %',
    'sensor delay':
        'задержка зонда',
    'Calculate correction':
        'Посчитать поправку',
    'HTML report':
        'Отчёт HTML',
    'Write a new .bin…':
        'Записать новый .bin…',
    'Reference':
        'Справочник',
    'All warnings':
        'Все предупреждения',
    'Update from site':
        'Обновить с сайта',
    'works offline; updating needs access to ms4x.net':
        'работает без интернета; обновление требует доступа к ms4x.net',
    'Reference ({n})':
        'Справочник ({n})',
    '{error}\n\nLog: {path}':
        '{error}\n\nЖурнал: {path}',
    'Failed:':
        'Не удалось:',
    'Firmware':
        'Прошивка',

    # --- web interface ---------------------------------------------------------
    'the older tkinter window':
        'старое окно на tkinter',
    'File not found':
        'Файл не найден',
    'Constant':
        'Константа',
    'Map {shape}':
        'Карта {shape}',
    'Choose firmware A (stock)':
        'Выберите прошивку A (сток)',
    'Choose firmware B (tune)':
        'Выберите прошивку B (тюнинг)',
    'Choose the firmware of the other version':
        'Выберите прошивку другой версии',
    '{n} parameters · {c} categories':
        '{n} параметров · {c} категорий',
    'text':
        'текст',
    '{changed} of {total} cells changed':
        'изменено {changed} из {total}',
    'Choose the XDF first.':
        'Сначала выберите XDF.',
    'Format':
        'Формат',
    '{bits} bits, {sign}, {order}':
        '{bits} бит, {sign}, {order}',
    'A — stock':
        'A — сток',
    'All':
        'Все',
    'B — tune':
        'B — тюнинг',
    'Before → after':
        'Было → стало',
    'Browse firmware':
        'Обзор прошивки',
    'Choose the files':
        'Выберите файлы',
    'Click a step or a card on the left to choose a file.':
        'Нажмите на шаг или на карточку слева, чтобы выбрать файл.',
    'Compare A and B':
        'Сравнить A и B',
    'Compare again':
        'Сравнить заново',
    'Details':
        'Подробности',
    'Edits outside the described parameters (code / patches)':
        'Правки вне описанных параметров (код / патчи)',
    'Everything is ready':
        'Всё готово',
    'Firmware A — stock':
        'Прошивка A — сток',
    'Firmware B — tune':
        'Прошивка B — тюнинг',
    'Firmware of the other version':
        'Прошивка другой версии',
    'Lowered':
        'Опущено',
    'MS4X Wiki offline':
        'MS4X Wiki офлайн',
    'Maps only':
        'Только карты',
    'Nothing found':
        'Ничего не найдено',
    'Open':
        'Открыть',
    'Other software version (for comparing versions and porting)':
        'Другая версия ПО (для сравнения версий и переноса)',
    'Press the button — the comparison takes a few seconds.':
        'Нажмите кнопку — сравнение займёт несколько секунд.',
    'Project':
        'Проект',
    'Raised':
        'Поднято',
    'Remove':
        'Убрать',
    'Saving…':
        'Сохраняю…',
    'Search: rev limit, VANOS, c_conf_cat, 0x61A8…':
        'Поиск: отсечка, VANOS, c_conf_cat, 0x61A8…',
    'The local reference says nothing about this parameter. Download it in the Reference mode.':
        'В локальном справочнике про этот параметр ничего нет. Скачать его можно в режиме «Справочник».',
    'This mode is coming in the next step':
        'Этот режим появится на следующем шаге',
    'Try another word — English or Russian, a name or an address.':
        'Попробуйте другое слово — по-русски или по-английски, имя или адрес.',
    'Two firmware files of the same software version, one XDF.':
        'Две прошивки одной версии ПО, один XDF.',
    'Use the classic window for it for now: ms43-ai-tuner.exe --classic':
        'Пока пользуйтесь для него старым окном: ms43-ai-tuner.exe --classic',
    'Waiting for the file…':
        'Жду выбора файла…',
    'Warnings':
        'Предупреждения',
    'What to do':
        'Что сделать',
    'XDF of the other version':
        'XDF другой версии',
    'choose the .bin':
        'выбрать .bin',
    'choose the .xdf file':
        'выбрать файл .xdf',
    'choose the stock .bin':
        'выбрать сток .bin',
    'choose the tuned .bin':
        'выбрать тюнинг .bin',
    'choose the first .bin (e.g. stock)':
        'выбрать первый .bin (например, сток)',
    'choose the second .bin (e.g. tune)':
        'выбрать второй .bin (например, тюнинг)',
    'Choose firmware A':
        'Выберите прошивку A',
    'Choose firmware B':
        'Выберите прошивку B',
    'compare and port edits':
        'сравнить и перенести правки',
    'connect to Claude':
        'подключить к Claude',
    'edits outside the XDF (code)':
        'правки вне XDF (код)',
    'hide the map':
        'скрыть карту',
    'map correction from a log':
        'поправка карты по логу',
    'original description (English)':
        'оригинал описания (English)',
    'search, all maps and values':
        'поиск, все карты и значения',
    'show the map':
        'показать карту',
    'what was changed in the tune':
        'что изменили в тюнинге',
    'which are applied':
        'какие применены',
    '{n} bytes':
        '{n} байт',
    'Claude Desktop is running now: quit it completely (tray icon → Quit) before starting it again, otherwise it may overwrite this change.':
        'Claude Desktop сейчас запущен: полностью закройте его (значок в трее → Quit) и только потом запустите снова, иначе он может затереть это изменение.',

    # --- AI assistant mode -----------------------------------------------------
    'the server program is missing: {path}':
        'нет программы сервера: {path}',
    'The "{name}" server is not connected.':
        'Сервер «{name}» не подключён.',
    'file not found: {path}':
        'файл не найден: {path}',
    'The server did not answer as expected.':
        'Сервер ответил не так, как ожидалось.',
    'No server called "{name}".':
        'Сервера «{name}» нет.',
    'Start the server first.':
        'Сначала запустите сервер.',
    'The claude command was not found. Install Claude Code or copy the command and run it in its terminal.':
        'Команда claude не найдена. Установите Claude Code или скопируйте команду и выполните её в его терминале.',
    'claude mcp add failed: {error}':
        'claude mcp add не сработал: {error}',
    'A server name may use Latin letters, digits, _ and - only.':
        'В имени сервера допустимы только латинские буквы, цифры, _ и -.',
    'Choose the XDF and the firmware in the project first.':
        'Сначала выберите XDF и прошивку в проекте.',
    'There is already a server called "{name}".':
        'Сервер «{name}» уже есть.',
    'Stop the server before renaming it.':
        'Остановите сервер, прежде чем переименовывать.',
    'The port must be between 1024 and 65535.':
        'Порт должен быть от 1024 до 65535.',
    'Stop the server before changing its port.':
        'Остановите сервер, прежде чем менять порт.',
    'Port {port} is busy ({error}). Choose another port.':
        'Порт {port} занят ({error}). Выберите другой порт.',
    'Add a server':
        'Добавить сервер',
    'Answer language':
        'Язык ответов',
    'Checking the server…':
        'Проверяю сервер…',
    'Choose the XDF and this firmware in the project on the left.':
        'Выберите XDF и эту прошивку в проекте слева.',
    'Claude Code has another address for this name — connect again.':
        'У Claude Code под этим именем записан другой адрес — подключите заново.',
    'Claude Code — live server':
        'Claude Code — живой сервер',
    'Claude Desktop is running now. Quit it before connecting, otherwise it may overwrite the change.':
        'Claude Desktop сейчас запущен. Закройте его перед подключением, иначе он может затереть изменение.',
    'Claude Desktop starts the server itself from its config file. After a change, quit Claude Desktop completely (tray icon → Quit) and start it again.':
        'Claude Desktop сам запускает сервер по своему конфигу. После изменения полностью закройте Claude Desktop (значок в трее → Quit) и запустите снова.',
    'Connect / update':
        'Подключить / обновить',
    'Connect to Claude Code':
        'Подключить к Claude Code',
    'Copied.':
        'Скопировано.',
    'Copy':
        'Копировать',
    'Disconnect':
        'Отключить',
    'Disconnect from Claude Code':
        'Отключить от Claude Code',
    'Firmware the AI sees':
        'Какую прошивку видит нейросеть',
    'I am removing the catalysts — what do I change and what matters?':
        'Я удаляю катализаторы — что поменять и что при этом важно?',
    'Let Claude read your firmware and the MS4X Wiki and answer questions about it. Read-only: nothing is ever written to the firmware.':
        'Claude читает вашу прошивку и MS4X Wiki и отвечает на вопросы о ней. Только чтение: в прошивку ничего не пишется.',
    'No ms43 servers in the Claude Desktop config yet.':
        'В конфиге Claude Desktop пока нет серверов ms43.',
    'Port':
        'Порт',
    'Remove the server':
        'Удалить сервер',
    'Run this command once in the Claude Code terminal. Keep the token private.':
        'Выполните эту команду один раз в терминале Claude Code. Токен никому не показывайте.',
    'Runs while this window is open. Choosing another file in the project takes effect at once, no restart of Claude Code needed.':
        'Работает, пока открыто это окно. Другая прошивка в проекте подхватывается сразу, перезапускать Claude Code не нужно.',
    'Server name':
        'Имя сервера',
    'Several servers can run at once, e.g. one for the stock and one for the tune.':
        'Можно запустить несколько серверов сразу, например для стока и для тюнинга.',
    'Show the ignition map ip_iga_ron98_pl__n__maf.':
        'Покажи карту зажигания ip_iga_ron98_pl__n__maf.',
    'Start':
        'Старт',
    'Stop':
        'Стоп',
    'Talking to Claude Code…':
        'Связываюсь с Claude Code…',
    'The server answers: {n} tools.':
        'Сервер отвечает: {n} инструментов.',
    'The server does not answer properly.':
        'Сервер отвечает неправильно.',
    'What does c_conf_cat = 4 mean, and what breaks if I change it?':
        'Что значит c_conf_cat = 4 и что сломается, если его поменять?',
    'What is my rev limit, and is it higher than stock?':
        'Какая у меня отсечка и выше ли она стока?',
    'What to ask':
        'Что спросить',
    'connect it again below.':
        'подключите заново ниже.',
    'connected to Claude Code':
        'подключён к Claude Code',
    'in the config':
        'в конфиге',
    'needs attention':
        'требует внимания',
    'not chosen':
        'не выбрана',
    'not connected to Claude Code':
        'не подключён к Claude Code',
    'running':
        'работает',
    'stopped':
        'остановлен',
    '{n} requests':
        'запросов: {n}',

    # --- window modes ----------------------------------------------------------
    'Patchlist XDF':
        'Patchlist XDF',
    'Choose in the project: {files}.':
        'Выберите в проекте: {files}.',
    'Choose a map.':
        'Выберите карту.',
    'Choose the patchlist XDF':
        'Выберите patchlist XDF',
    'Choose the wideband log (CSV)':
        'Выберите лог ШЛЗ (CSV)',
    '{n} patches':
        '{n} патчей',
    'Choose a section on the left':
        'Выберите раздел слева',
    'Compare the versions':
        'Сравнить версии',
    'Correction of the VE map from a wideband lambda log: if the mixture is leaner than the target, there was more air than the ECU thought. Cells with too few samples are left alone.':
        'Поправка карты наполнения по логу широкополосного зонда: если смесь беднее заданной — воздуха было больше, чем думал блок. Ячейки, куда попало мало точек, не трогаются.',
    'Each firmware has its own XDF. Parameters are matched by name, physical values are compared, not bytes.':
        'У каждой прошивки свой XDF. Параметры сопоставляются по именам, сравниваются физические величины, а не байты.',
    'Fuel':
        'Топливо',
    'Log: {rows} rows, {cols} columns. Check that the columns are recognised right.':
        'Лог: {rows} строк, {cols} столбцов. Проверьте, что столбцы распознаны верно.',
    'One firmware in full: every map and value, with the reference next to it.':
        'Одна прошивка целиком: все карты и значения, справка рядом.',
    'Plan for porting your edits':
        'План переноса ваших правок',
    'Press the button to check the patches.':
        'Нажмите кнопку, чтобы проверить патчи.',
    'Search the reference: lambda, boost, checksum…':
        'Поиск по справочнику: lambda, boost, checksum…',
    'Sections: {n}':
        'Разделов: {n}',
    'Showing the first {n} of {total}. Refine the search.':
        'Показаны первые {n} из {total}. Уточните поиск.',
    'Similar in the target:':
        'Похожие в целевой:',
    'There is no local copy of the reference yet':
        'Локальной копии справочника пока нет',
    'Value in the firmware':
        'Значение в прошивке',
    'Which patches from the community patchlist are applied to the firmware.':
        'Какие патчи из community patchlist применены к прошивке.',
    'Write':
        'Записать',
    'Your edits are the difference between A (stock) and B (tune); they are matched against the other version.':
        'Ваши правки — это разница между A (сток) и B (тюнинг); они сопоставляются с другой версией.',
    'Your firmware is compared with the firmware of the other version.':
        'Ваша прошивка сравнивается с прошивкой другой версии.',
    'both (closed loop)':
        'оба (замкнутый контур)',
    'by the fuel trims':
        'по топливным коррекциям',
    'by the sensor (open loop)':
        'по зонду (разомкнутый контур)',
    'choose the patchlist .xdf':
        'выбрать patchlist .xdf',
    'choose the wideband log (.csv)':
        'выбрать лог ШЛЗ (.csv)',
    'coolant temperature':
        'температура ОЖ',
    'engine speed':
        'обороты',
    'fuel trim':
        'топливная коррекция',
    'gasoline':
        'бензин',
    'load / air mass':
        'нагрузка / расход воздуха',
    'methanol':
        'метанол',
    'not applied or partly':
        'не применено или частично',
    'other version':
        'другая версия',
    'parameters you changed':
        'вы изменили параметров',
    'partly / modified':
        'частично / изменён',
    'patches in the list':
        'патчей в списке',
    'samples dropped':
        'точек отброшено',
    'wideband lambda':
        'лямбда ШЛЗ',
}
