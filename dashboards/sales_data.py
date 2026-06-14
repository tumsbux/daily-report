"""
dashboards/sales_data.py — Sales cache helpers (Phase 3c, 2026-06-14)

Extracted from update_dashboard.py:
  - get_sales_daily_cache()      (IR-C incremental refresh)
  - update_monthly_totals_cache()
"""

import os
import json
from collections import defaultdict
from datetime import datetime


def get_sales_daily_cache(cfg, year, month, days_elapsed, full_refresh=False, *, folder, rule_hash):
    """Build/update the per-store daily sales cache for a given year-month.

    Args:
        cfg: db_config dict
        year, month: strings (e.g. '2026', '06')
        days_elapsed: int, max day to include
        full_refresh: bool, force full rebuild
        folder: FOLDER path (caller's working dir)
        rule_hash: schema/rule version string for cache validation
    Returns:
        dict {whs: {sales, cost, txn}} aggregated up to days_elapsed
    """
    import mysql.connector

    cache_dir = os.path.join(folder, 'cache')
    os.makedirs(cache_dir, exist_ok=True)
    cache_path = os.path.join(cache_dir, f'sales_daily_{year}-{month}.json')

    rebuild = full_refresh or not os.path.exists(cache_path)
    if not rebuild:
        try:
            with open(cache_path, encoding='utf-8') as f:
                cache_data = json.load(f)
            c_meta = cache_data.get('_meta', {})
            if c_meta.get('v') != 2 or c_meta.get('rule_hash') != rule_hash:
                print(f"  Sales cache mismatch -> auto full-refresh")
                rebuild = True
        except Exception:
            rebuild = True

    if rebuild:
        print(f"  [SALES CACHE] Full refresh for {year}-{month} up to day {days_elapsed}...")
        conn = mysql.connector.connect(
            host=cfg['host'], port=cfg.get('port', 3306),
            user=cfg['user'], password=cfg['password'],
            database=cfg.get('database', 'data-lake'),
            connection_timeout=60, charset='utf8mb4'
        )
        try:
            start_date = f'{year}-{month}-01'
            end_date = f'{year}-{month}-{days_elapsed:02d}'
            sql = """
                SELECT sotowhs AS whs,
                       DAY(sodate) AS day,
                       SUM(net_sales_amt)          AS sales_amt,
                       SUM(COALESCE(total_cost,0)) AS cost_amt,
                       COUNT(DISTINCT sono)        AS txn_count
                FROM fact_sales
                WHERE sodate BETWEEN %s AND %s
                  AND solinetype NOT IN ('C', 'R')
                  AND sotowhs REGEXP '^[0-9]+$'
                  AND CAST(sotowhs AS UNSIGNED) BETWEEN 1 AND 500
                GROUP BY sotowhs, DAY(sodate)
            """
            cur = conn.cursor(dictionary=True)
            cur.execute(sql, (start_date, end_date))
            rows = cur.fetchall()
            cur.close()

            stores_data = defaultdict(dict)
            for r in rows:
                raw_whs = str(r['whs']).strip()
                day_str = str(r['day'])
                stores_data[raw_whs][day_str] = {
                    'sales': float(r['sales_amt'] or 0),
                    'cost':  float(r['cost_amt'] or 0),
                    'txn':   int(r['txn_count'] or 0)
                }

            cache_data = {
                '_meta': {
                    'v':         2,
                    'built_by':  'antigravity-gemini-3-flash',
                    'rule_hash': rule_hash,
                    'timestamp': datetime.now().isoformat()
                },
                'stores': dict(stores_data)
            }
            from lib.safe_write import safe_write_json
            safe_write_json(cache_path, cache_data)
        finally:
            conn.close()
    else:
        start_day = max(1, days_elapsed - 6)
        print(f"  [SALES CACHE] Incremental refresh for {year}-{month} days {start_day}..{days_elapsed}...")
        conn = mysql.connector.connect(
            host=cfg['host'], port=cfg.get('port', 3306),
            user=cfg['user'], password=cfg['password'],
            database=cfg.get('database', 'data-lake'),
            connection_timeout=60, charset='utf8mb4'
        )
        try:
            start_date = f'{year}-{month}-{start_day:02d}'
            end_date = f'{year}-{month}-{days_elapsed:02d}'
            sql = """
                SELECT sotowhs AS whs,
                       DAY(sodate) AS day,
                       SUM(net_sales_amt)          AS sales_amt,
                       SUM(COALESCE(total_cost,0)) AS cost_amt,
                       COUNT(DISTINCT sono)        AS txn_count
                FROM fact_sales
                WHERE sodate BETWEEN %s AND %s
                  AND solinetype NOT IN ('C', 'R')
                  AND sotowhs REGEXP '^[0-9]+$'
                  AND CAST(sotowhs AS UNSIGNED) BETWEEN 1 AND 500
                GROUP BY sotowhs, DAY(sodate)
            """
            cur = conn.cursor(dictionary=True)
            cur.execute(sql, (start_date, end_date))
            rows = cur.fetchall()
            cur.close()

            with open(cache_path, encoding='utf-8') as f:
                cache_data = json.load(f)

            stores_data = cache_data.setdefault('stores', {})
            for s_code, d_map in list(stores_data.items()):
                for d in range(start_day, days_elapsed + 1):
                    d_map.pop(str(d), None)

            for r in rows:
                raw_whs = str(r['whs']).strip()
                day_str = str(r['day'])
                stores_data.setdefault(raw_whs, {})[day_str] = {
                    'sales': float(r['sales_amt'] or 0),
                    'cost':  float(r['cost_amt'] or 0),
                    'txn':   int(r['txn_count'] or 0)
                }
            cache_data['_meta']['timestamp'] = datetime.now().isoformat()
            from lib.safe_write import safe_write_json
            safe_write_json(cache_path, cache_data)
        finally:
            conn.close()

    result = {}
    for whs, d_map in cache_data.get('stores', {}).items():
        sales_sum = 0.0
        cost_sum  = 0.0
        txn_sum   = 0
        for d in range(1, days_elapsed + 1):
            day_str = str(d)
            if day_str in d_map:
                sales_sum += d_map[day_str].get('sales', 0.0)
                cost_sum  += d_map[day_str].get('cost',  0.0)
                txn_sum   += d_map[day_str].get('txn',   0)
        entry = {'sales': sales_sum, 'cost': cost_sum, 'txn': txn_sum}
        result[whs] = entry
        try:
            result[str(int(whs))] = entry
        except Exception:
            pass
        try:
            result[whs.zfill(3)] = entry
        except Exception:
            pass

    return result


def update_monthly_totals_cache(D, current_month_key, current_month_total, *, folder):
    """Persist and return the cross-month sales totals cache.

    Args:
        D: dashboard data dict (reads D['summary']['m26_tot'] / ['m25_tot'])
        current_month_key: str, e.g. '2026-06'
        current_month_total: unused (kept for signature compat)
        folder: FOLDER path
    Returns:
        cache_data dict with keys 'm25_tot', 'm26_tot'
    """
    cache_path = os.path.join(folder, 'cache', 'sales_monthly_tot.json')
    cache_data = {'m25_tot': {}, 'm26_tot': {}}
    if os.path.exists(cache_path):
        try:
            with open(cache_path, encoding='utf-8') as f:
                cache_data = json.load(f)
        except Exception:
            pass
    for k, v in D['summary'].get('m26_tot', {}).items():
        if k != current_month_key and k not in cache_data.setdefault('m26_tot', {}):
            cache_data['m26_tot'][k] = v
    for k, v in D['summary'].get('m25_tot', {}).items():
        if k not in cache_data.setdefault('m25_tot', {}):
            cache_data['m25_tot'][k] = v
    from lib.safe_write import safe_write_json
    safe_write_json(cache_path, cache_data)
    return cache_data
