"""Dashboard shared library — phase 1 refactor (2026-06-05).

Modules:
    db          : MySQL connection helper (get_conn / get_config)
    dates       : Thai month names, current_month(), valid_store()
    safe_write  : safe_write_html() with </html> verification

Usage:
    from lib.db import get_conn
    from lib.dates import current_month, TH_MONTHS_SHORT, valid_store
    from lib.safe_write import safe_write_html
"""
