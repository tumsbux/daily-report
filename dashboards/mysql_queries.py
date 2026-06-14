"""MySQL query functions extracted from update_dashboard.py (lines 79-286).

These are functional copies of the original `_query_*` functions.
One difference from the original: `_query_fact_sales_may25` used module-
level YEAR/MONTH globals; here it's renamed `query_prev_year_same_month`
and takes (year, month) as parameters — behavior identical when called
with the same values update_dashboard.py would have used.

All queries follow the canonical rule `solinetype NOT IN ('C', 'R')`
(matches mobile app) and store filter `CAST(sotowhs AS UNSIGNED) BETWEEN
1 AND 500`. Returns dict results with both raw + padded + unpadded store
codes as keys (callers may lookup any format).

Phase 3a (2026-06-05): parallel module ready; update_dashboard.py NOT
yet wired to import from here.
"""
from __future__ import annotations

from typing import Any


def _open_conn(cfg: dict[str, Any], timeout: int = 30):
    """Internal: open MySQL connection from cfg dict (db_config.json shape)."""
    import mysql.connector
    return mysql.connector.connect(
        host=cfg['host'],
        port=cfg.get('port', 3306),
        user=cfg['user'],
        password=cfg['password'],
        database=cfg.get('database', 'data-lake'),
        connection_timeout=timeout,
        charset='utf8mb4',
    )


def _next_month_first_day(year: int | str, month: int | str) -> str:
    """Return YYYY-MM-01 of the month after (year, month)."""
    y, m = int(year), int(month)
    if m == 12:
        return f'{y + 1}-01-01'
    return f'{y}-{m + 1:02d}-01'


def query_returns_mtd(cfg, year, month):
    """Query fact_returns for MTD return amount per store.

    Returns:
        (store_ret_dict, total_amt, total_bills, max_day) where store_ret_dict
        maps store code (raw, unpadded, zero-padded) → MTD return amount.
    """
    next_mo = _next_month_first_day(year, month)
    conn = _open_conn(cfg, timeout=30)
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        """
        SELECT warehouse_code AS whs,
               SUM(allocated_net_amount) AS ret_amount,
               COUNT(DISTINCT rtsono)    AS ret_bills,
               MAX(DAY(return_date))     AS max_day
        FROM fact_returns
        WHERE rtstatus = 'U'
          AND return_date BETWEEN %s AND CURDATE()
          AND warehouse_code NOT IN ('901', '999')
        GROUP BY warehouse_code
        """,
        (f'{year}-{month}-01',),
    )
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    result: dict[str, float] = {}
    total_amt = 0.0
    total_bills = 0
    max_day = 0
    for r in rows:
        raw = str(r['whs'] or '').strip()
        if not raw:
            continue
        amt = float(r['ret_amount'] or 0)
        bills = int(r['ret_bills'] or 0)
        d = int(r['max_day'] or 0)
        total_amt += amt
        total_bills += bills
        if d > max_day:
            max_day = d
        result[raw] = amt
        try:
            result[str(int(raw))] = amt
        except Exception:
            pass
        try:
            result[raw.zfill(3)] = amt
        except Exception:
            pass
    return result, total_amt, total_bills, max_day


def query_txn_mtd(cfg, year, month):
    """Query fact_sales for distinct SO count per store MTD (transaction count).

    Returns:
        dict {store_code → txn_count} with raw + unpadded + padded keys.
    """
    conn = _open_conn(cfg, timeout=30)
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        """
        SELECT sotowhs AS whs,
               COUNT(DISTINCT sono) AS txn_count
        FROM fact_sales
        WHERE sodate >= %s AND sodate < %s
          AND solinetype NOT IN ('C', 'R')
          AND sotowhs NOT IN ('901', '999', '0901', '0999')
        GROUP BY sotowhs
        """,
        (f'{year}-{month}-01', _next_month_first_day(year, month)),
    )
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    result: dict[str, int] = {}
    for r in rows:
        raw = str(r['whs'] or '').strip()
        if not raw:
            continue
        cnt = int(r['txn_count'] or 0)
        result[raw] = cnt
        try:
            result[str(int(raw))] = cnt
        except Exception:
            pass
        try:
            result[raw.zfill(3)] = cnt
        except Exception:
            pass
    return result


def query_prev_year_same_month(cfg, year, month):
    """Query fact_sales for full previous-year same-month per store.

    Originally `_query_fact_sales_may25` in update_dashboard.py — references
    to module-level YEAR/MONTH replaced with explicit parameters.
    Used to set authoritative s25_may (YoY baseline) from fact_sales.

    Returns:
        dict {store_code → {'s25': sales_amt, 'txn25': txn_count}}
    """
    import calendar
    prev_y = int(year) - 1
    cur_m = int(month)
    _, last_day25 = calendar.monthrange(prev_y, cur_m)
    start_date = f'{prev_y}-{cur_m:02d}-01'
    end_date = f'{prev_y}-{cur_m:02d}-{last_day25:02d}'
    conn = _open_conn(cfg, timeout=60)
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        f"""
        SELECT sotowhs AS whs,
               SUM(net_sales_amt)   AS sales25,
               COUNT(DISTINCT sono) AS txn25
        FROM fact_sales
        WHERE sodate BETWEEN '{start_date}' AND '{end_date}'
          AND solinetype NOT IN ('C', 'R')
          AND sotowhs REGEXP '^[0-9]+$'
          AND CAST(sotowhs AS UNSIGNED) BETWEEN 1 AND 500
        GROUP BY sotowhs
        """
    )
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    result: dict[str, dict] = {}
    for r in rows:
        raw = str(r['whs'] or '').strip()
        if not raw:
            continue
        entry = {
            's25': float(r['sales25'] or 0),
            'txn25': int(r['txn25'] or 0),
        }
        result[raw] = entry
        try:
            result[str(int(raw))] = entry
        except Exception:
            pass
        try:
            result[raw.zfill(3)] = entry
        except Exception:
            pass
    return result


def query_fact_sales_mtd(cfg, year, month, days_elapsed):
    """Query fact_sales directly for MTD net_sales_amt + total_cost per store.

    This is the authoritative sales source — matches the mobile app exactly.

    Returns:
        (result_dict, fact_max_day) where result_dict maps store_code →
        {'sales': amt, 'cost': amt, 'txn': cnt}, and fact_max_day is the
        actual max DAY(sodate) seen (may lag DAYS_ELAPSED by ~3 days).
    """
    conn = _open_conn(cfg, timeout=60)
    cursor = conn.cursor(dictionary=True)
    end_date = f'{year}-{month}-{int(days_elapsed):02d}'
    cursor.execute(
        """
        SELECT sotowhs AS whs,
               SUM(net_sales_amt)          AS sales_amt,
               SUM(COALESCE(total_cost,0)) AS cost_amt,
               COUNT(DISTINCT sono)        AS txn_count,
               MAX(DAY(sodate))            AS max_day_seen
        FROM fact_sales
        WHERE sodate BETWEEN %s AND %s
          AND solinetype NOT IN ('C', 'R')
          AND sotowhs REGEXP '^[0-9]+$'
          AND CAST(sotowhs AS UNSIGNED) BETWEEN 1 AND 500
        GROUP BY sotowhs
        """,
        (f'{year}-{month}-01', end_date),
    )
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    result: dict[str, dict] = {}
    fact_max_day = 0
    for r in rows:
        raw = str(r['whs'] or '').strip()
        if not raw:
            continue
        d = int(r.get('max_day_seen') or 0)
        if d > fact_max_day:
            fact_max_day = d
        entry = {
            'sales': float(r['sales_amt'] or 0),
            'cost': float(r['cost_amt'] or 0),
            'txn': int(r['txn_count'] or 0),
        }
        result[raw] = entry
        try:
            result[str(int(raw))] = entry
        except Exception:
            pass
        try:
            result[raw.zfill(3)] = entry
        except Exception:
            pass
    return result, fact_max_day


def query_whsdd(cfg, year, month):
    """Query MYPOS2018_CENTER.whsdd for daily store targets + actuals.

    Returns:
        list of dicts with normalised string values (same shape as
        target.txt rows): whsddno, whsddyyyy, whsddmm, whsdddd,
        whsddptar, whsddpact, whsddpnetamt, whsddpnetcost, whsddtotdoc.
    """
    # Note: original opened conn without 'database' kwarg; this matches.
    import mysql.connector
    conn = mysql.connector.connect(
        host=cfg['host'],
        port=cfg.get('port', 3306),
        user=cfg['user'],
        password=cfg['password'],
        connection_timeout=30,
        charset='utf8mb4',
    )
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        """
        SELECT whsddno, whsddyyyy, whsddmm, whsdddd,
               whsddptar, whsddpact,
               whsddpnetamt, whsddpnetcost
        FROM MYPOS2018_CENTER.whsdd
        WHERE whsddyyyy = %s AND whsddmm = %s
        """,
        (int(year), int(month)),
    )
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    result = []
    for r in rows:
        result.append({
            'whsddno':       str(r['whsddno']),
            'whsddyyyy':     str(r['whsddyyyy']),
            'whsddmm':       str(r['whsddmm']).zfill(2),
            'whsdddd':       str(r['whsdddd']).zfill(2),
            'whsddptar':     float(r.get('whsddptar') or 0),
            'whsddpact':     float(r.get('whsddpact') or 0),
            'whsddpnetamt':  float(r.get('whsddpnetamt') or 0),
            'whsddpnetcost': float(r.get('whsddpnetcost') or 0),
            'whsddtotdoc':   0,  # not in whsdd — txn count comes from fact_sales
        })
    return result


def autodetect_max_day(cfg, year, month) -> int:
    """Return MAX(DAY(sodate)) from fact_sales for given month, 0 if none.

    Replicates the inline auto-detect block in update_dashboard.py
    (lines 299-321). Returns 0 on any error (caller falls back).
    """
    try:
        import mysql.connector, calendar
        y, m = int(year), int(month)
        _, last_day = calendar.monthrange(y, m)
        start_date = f'{y}-{m:02d}-01'
        end_date = f'{y}-{m:02d}-{last_day:02d}'
        conn = mysql.connector.connect(
            host=cfg['host'],
            port=cfg.get('port', 3306),
            user=cfg['user'],
            password=cfg['password'],
            database=cfg.get('database', 'data-lake'),
            connection_timeout=30,
            charset='utf8mb4',
        )
        cur = conn.cursor()
        cur.execute(
            """
            SELECT MAX(DAY(sodate)) FROM fact_sales
            WHERE sodate BETWEEN %s AND %s
              AND solinetype NOT IN ('C','R')
              AND sotowhs REGEXP '^[0-9]+$'
              AND CAST(sotowhs AS UNSIGNED) BETWEEN 1 AND 500
            """,
            (start_date, end_date),
        )
        row = cur.fetchone()
        cur.close()
        conn.close()
        return int(row[0]) if row and row[0] else 0
    except Exception:
        return 0
