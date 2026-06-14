"""
dashboards/html_patch.py — HTML string patchers (Phase 3c, 2026-06-14)

Extracted from update_dashboard.py:
  - upd_hk()    hero KPI cards in index.html
  - upd_skpi()  sales KPI mini cards
  - upd_kc()    KPI detail cards by id
"""

import re


def upd_hk(html, val, label):
    """Replace hero KPI value in index.html for a given label."""
    return re.sub(
        r'(<div class="hk-val">)[^<]+(</div><div class="hk-lab">' + re.escape(label) + ')',
        r'\g<1>' + val + r'\g<2>', html)


def upd_skpi(html, val, label):
    """Replace sales KPI mini-card value for a given label."""
    return re.sub(
        r'(<div class="skpi-label">' + re.escape(label) + r'</div>\s*<div class="skpi-val">)[^<]+(</div>)',
        r'\g<1>' + val + r'\g<2>', html)


def upd_kc(html, kc_id, val):
    """Replace content of <div id="kc_id">...</div>."""
    return re.sub(
        r'(<div[^>]+id="' + kc_id + r'"[^>]*>)[^<]*(</div>)',
        lambda m: m.group(1) + val + m.group(2),
        html
    )
