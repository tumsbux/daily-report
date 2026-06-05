"""Shared date + store helpers.

Pulled from update_dashboard.py / rebuild_fraud_analysis.py /
build_product_data_mysql.py — historically duplicated across files.

Public API:
    TH_MONTHS         : list (1-indexed) full Thai month names
    TH_MONTHS_SHORT   : list (1-indexed) abbreviated Thai month names
    current_month()   : (year:int, month:int) auto from date.today()
    month_key(y, m)   : 'YYYY-MM'
    thai_month_name(m, year=None, short=False) : 'มิ.ย. 2026' / 'มิถุนายน 2026'
    days_in_month(y, m): int
    valid_store(code) : bool — store filter rule (int <= 500)
"""
from __future__ import annotations

import calendar
from datetime import date
from typing import Tuple

# 1-indexed: index 0 is empty so TH_MONTHS[6] = 'มิถุนายน'
TH_MONTHS = [
    '',
    'มกราคม', 'กุมภาพันธ์', 'มีนาคม', 'เมษายน',
    'พฤษภาคม', 'มิถุนายน', 'กรกฎาคม', 'สิงหาคม',
    'กันยายน', 'ตุลาคม', 'พฤศจิกายน', 'ธันวาคม',
]

TH_MONTHS_SHORT = [
    '',
    'ม.ค.', 'ก.พ.', 'มี.ค.', 'เม.ย.',
    'พ.ค.', 'มิ.ย.', 'ก.ค.', 'ส.ค.',
    'ก.ย.', 'ต.ค.', 'พ.ย.', 'ธ.ค.',
]


def current_month() -> Tuple[int, int]:
    """Return (year, month) from today (CE year, not BE)."""
    t = date.today()
    return t.year, t.month


def month_key(year: int, month: int) -> str:
    """Return 'YYYY-MM' string."""
    return f'{year:04d}-{month:02d}'


def thai_month_name(month: int, year: int | None = None, short: bool = False) -> str:
    """Return Thai month label.

    Examples:
        thai_month_name(6)              -> 'มิถุนายน'
        thai_month_name(6, 2026)        -> 'มิถุนายน 2026'
        thai_month_name(6, 2026, True)  -> 'มิ.ย. 2026'
    """
    table = TH_MONTHS_SHORT if short else TH_MONTHS
    if not (1 <= month <= 12):
        return ''
    label = table[month]
    return f'{label} {year}' if year is not None else label


def days_in_month(year: int, month: int) -> int:
    """Calendar days in given month."""
    return calendar.monthrange(year, month)[1]


def valid_store(code) -> bool:
    """Return True if store code is a regular branch (int <= 500).

    Excludes special codes like 901-999, WBT, WHC, WPT.
    Accepts int, str, or None.
    """
    try:
        return int(code) <= 500
    except (TypeError, ValueError):
        return False
