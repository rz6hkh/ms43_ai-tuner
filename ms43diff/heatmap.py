# -*- coding: utf-8 -*-
"""
Map colouring shared by the HTML report, the GUI and the PDF.

Two different jobs with different palettes:

  * **values** — a sequential "low → high" scale. Blue → yellow → red: it
    reads both in colour and in black-and-white print, because lightness
    grows together with hue.
  * **difference** — a diverging scale with zero in the middle: blue (lower)
    → grey (unchanged) → red (higher). Zero must be neutral, otherwise the eye
    catches on changes that do not exist.

Both palettes keep overlaid text readable: text_color() returns black or white
depending on the actual background luminance.
"""

from __future__ import annotations

from typing import List, Optional, Sequence, Tuple

RGB = Tuple[int, int, int]

# Sequential scale: cold dark -> warm light.
# A viridis-like line with a more contrasting top, so that a 1-2 degree
# difference is visible on an ignition map.
_SEQUENTIAL: List[RGB] = [
    (38, 54, 106),
    (43, 96, 148),
    (46, 137, 152),
    (76, 168, 130),
    (140, 190, 97),
    (206, 202, 74),
    (240, 178, 62),
    (232, 129, 55),
    (206, 74, 54),
]

# Diverging scale for differences: lower -> unchanged -> higher
_DIVERGING_NEG: List[RGB] = [(33, 87, 160), (94, 145, 200), (170, 200, 230)]
_DIVERGING_MID: RGB = (238, 238, 238)
_DIVERGING_POS: List[RGB] = [(240, 200, 170), (216, 128, 90), (176, 42, 38)]


def _lerp(a: RGB, b: RGB, t: float) -> RGB:
    return (
        int(round(a[0] + (b[0] - a[0]) * t)),
        int(round(a[1] + (b[1] - a[1]) * t)),
        int(round(a[2] + (b[2] - a[2]) * t)),
    )


def _ramp(colors: Sequence[RGB], t: float) -> RGB:
    if not colors:
        return (128, 128, 128)
    if len(colors) == 1:
        return colors[0]
    t = min(1.0, max(0.0, t))
    pos = t * (len(colors) - 1)
    idx = min(int(pos), len(colors) - 2)
    return _lerp(colors[idx], colors[idx + 1], pos - idx)


def value_color(value: float, low: float, high: float) -> RGB:
    """Cell colour by its value within the map range."""
    if high <= low:
        return _SEQUENTIAL[len(_SEQUENTIAL) // 2]
    return _ramp(_SEQUENTIAL, (value - low) / (high - low))


def delta_color(delta: float, scale: float) -> RGB:
    """Cell colour by the size of the change. scale is the maximum absolute change."""
    if scale <= 0 or delta == 0:
        return _DIVERGING_MID
    t = min(1.0, abs(delta) / scale)
    if delta < 0:
        return _lerp(_DIVERGING_MID, _ramp(_DIVERGING_NEG, t), t)
    return _lerp(_DIVERGING_MID, _ramp(_DIVERGING_POS, t), t)


def text_color(background: RGB) -> RGB:
    """Black or white — whichever reads on this background."""
    # relative luminance, W3C formula
    r, g, b = [c / 255 for c in background]
    r = r / 12.92 if r <= 0.03928 else ((r + 0.055) / 1.055) ** 2.4
    g = g / 12.92 if g <= 0.03928 else ((g + 0.055) / 1.055) ** 2.4
    b = b / 12.92 if b <= 0.03928 else ((b + 0.055) / 1.055) ** 2.4
    luminance = 0.2126 * r + 0.7152 * g + 0.0722 * b
    return (0, 0, 0) if luminance > 0.45 else (255, 255, 255)


def hex_color(rgb: RGB) -> str:
    return "#{:02X}{:02X}{:02X}".format(*rgb)


# ---------------------------------------------------------------------------


def value_range(matrix: Sequence[Sequence[float]]) -> Tuple[float, float]:
    values = [v for row in matrix for v in row]
    if not values:
        return 0.0, 1.0
    return min(values), max(values)


def delta_scale(before: Sequence[Sequence[float]],
                after: Sequence[Sequence[float]]) -> float:
    """Maximum absolute change — normalises the diverging scale."""
    worst = 0.0
    for row_a, row_b in zip(before, after):
        for a, b in zip(row_a, row_b):
            worst = max(worst, abs(b - a))
    return worst


def legend_stops(low: float, high: float, count: int = 7) -> List[Tuple[float, RGB]]:
    """Tick points for the value scale legend."""
    if count < 2:
        count = 2
    step = (high - low) / (count - 1) if high > low else 0.0
    return [(low + step * i, value_color(low + step * i, low, high))
            for i in range(count)]


def delta_legend_stops(scale: float, count: int = 7) -> List[Tuple[float, RGB]]:
    """Tick points for the change scale legend (symmetric around zero)."""
    if count % 2 == 0:
        count += 1
    half = count // 2
    out: List[Tuple[float, RGB]] = []
    for i in range(-half, half + 1):
        value = scale * i / half if half else 0.0
        out.append((value, delta_color(value, scale)))
    return out
