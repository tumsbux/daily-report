"""Dashboard package — Phase 3 refactor (started 2026-06-05).

Goal: decompose the 1,215-line update_dashboard.py + 757-line
rebuild_fraud_analysis.py into focused modules. Phase 3 is staged:

    Phase 3a (DONE): Extract pure functions to parallel modules here.
                     update_dashboard.py NOT modified — still production.
    Phase 3b (TODO): Wire imports — replace in-script defs with imports
                     from this package. Test side-by-side, then commit.
    Phase 3c (TODO): Decompose rebuild_fraud_analysis.py similarly.

Modules (Phase 3a):
    helpers        : Pure utilities — valid_store, extract_json, safe_pct, safe_yoy
    mysql_queries  : DB query functions for sales/returns/txn/whsdd

Each module here is a verbatim parallel copy of code already in
update_dashboard.py. Behavior is identical. Once Phase 3b wires them
in, the in-script defs will be deleted in favor of imports.
"""
