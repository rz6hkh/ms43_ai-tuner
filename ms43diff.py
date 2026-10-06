#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Точка входа для запуска без установки пакета: python ms43diff.py ..."""

import sys

from ms43diff.cli import main

if __name__ == "__main__":
    sys.exit(main())
