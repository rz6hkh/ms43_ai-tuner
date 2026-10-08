"""
ms43diff — compare Siemens MS43 (BMW M52TU/M54) firmware using an XDF definition.

The package reads TunerPro definitions (.xdf), pulls the real values of every
constant and map out of a .bin, compares two (or more) firmware files and
prints a report in English or Russian.
"""

__version__ = "1.2.0"
__all__ = ["xdf", "binfile", "compare", "ru", "names", "i18n", "report", "mathexpr"]
