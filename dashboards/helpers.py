"""Pure helper functions extracted from update_dashboard.py (lines 55-77).

These are byte-equivalent copies of the originals — behavior unchanged.
Phase 3a (2026-06-05): parallel module ready; update_dashboard.py NOT
yet wired to import from here.
"""
from __future__ import annotations

import json


def valid_store(code) -> bool:
    """Return True if store code is a regular branch (int <= 500).

    Excludes special codes like 901-999, WBT, WHC, WPT.
    """
    try:
        return int(code) <= 500
    except Exception:
        return False


def extract_json(html: str):
    """Find `const D=...` block in a dashboard HTML file and parse the embedded JSON.

    Returns (parsed_dict, start_index, end_index) where start/end mark the
    JSON object bounds inside the HTML string (so callers can splice in
    a replacement).
    """
    marker = 'const D='
    start = html.index(marker) + len(marker)
    depth = 0
    i = start
    end = start
    while i < len(html):
        if html[i] == '{':
            depth += 1
        elif html[i] == '}':
            depth -= 1
            if depth == 0:
                end = i + 1
                break
        i += 1
    return json.loads(html[start:end]), start, end


def safe_pct(num, denom, decimals: int = 1):
    """Return num/denom * 100, rounded; None if denom is zero/falsy or error."""
    try:
        return round(num / denom * 100, decimals) if denom else None
    except Exception:
        return None


def safe_yoy(new_val, old_val, decimals: int = 1):
    """Return year-over-year % change; None if old_val is zero/falsy or error."""
    try:
        return round((new_val / old_val - 1) * 100, decimals) if old_val else None
    except Exception:
        return None
