"""build_store_discount_data.py — Store Price-Discount Dashboard data builder

Tracks price adjustments made BY STORES (cashier/end-of-bill discounts), excluding
central-marketing promotions (coupon / score-redemption / percentage promo).

Methodology (see Decisions.md [2026-07-09], FINAL revision — user confirmed the
classifier is solinetype, not the bill-header discount fields):
    list_price_line = dim_product.ipunit3 * fact_sales.net_qty   (== sopricunit, confirmed identical)
    line_discount    = list_price_line - fact_sales.net_sales_amt
    line_is_store    = fact_sales.solinetype IN ('O','P','Y')     -- store-initiated discount
                        (all other linetypes = automatic marketing/member-price promo)
    store_discount   = SUM(line_discount) WHERE line_is_store
    GP%_line         = (actual_price_line - total_cost) / actual_price_line
                        where actual_price_line = list_price_line - line_discount

    This file stores raw per-linetype buckets (qty, cost, net_sales, list_amt) — the
    store-vs-marketing split is applied at read time in the dashboard by checking
    which linetype key ('O'/'P'/'Y' vs rest) a bucket belongs to. This keeps the JSON
    reusable if the store/marketing linetype list ever needs to change without a
    rebuild. NOTE: solinetype='P' only occurs at sotowhs='901' (a special warehouse/
    channel code, not a real 1-500 store) so in practice this dashboard (scoped to
    valid_store 1-500) only ever sees 'O' and 'Y' as store-initiated.

    History: rev1 used fact_bill_header.sodisc_bill/sodisc bill-level proration
    (wrong mechanism). rev2 excluded sopricdisc entirely (wrong — some sopricdisc IS
    store-driven when the line's solinetype is O/P/Y). This rev3 is what user
    confirmed directly: classify by solinetype, no fact_bill_header join needed.

Joins: fact_sales.iprod = dim_product.iprod
       whs (sotowhs)    -> dim_branch (RM/DM) via dim_cache.json (already built by
       rebuild_fraud_analysis.py — reused here instead of re-querying dim_branch)

Output: store_discount_data.json
    {
      "schema": 1,
      "generated_at": "...",
      "window_days": N,
      "branches": {code: {name, dm, dm_code, rm, rm_code}},
      "days": {
        "YYYY-MM-DD": {
          "<whs>": {"<linetype>": [qty, cost, net_sales, list_amt]}
        }
      }
    }
    (dashboard derives discount = list_amt - net_sales per bucket, and classifies
    store vs marketing by whether the linetype key is in {'O','P','Y'})

Usage:
    python build_store_discount_data.py --days 92          # rolling window backfill/refresh
    python build_store_discount_data.py --day 2026-07-09    # single day incremental update
    python build_store_discount_data.py --days 92 --no-push
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime, timedelta

FOLDER = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, FOLDER)

from lib.db import get_conn, get_config          # noqa: E402
from lib.safe_write import safe_write_json        # noqa: E402

OUT_FILE = os.path.join(FOLDER, 'store_discount_data.json')
PRODUCTS_OUT_FILE = os.path.join(FOLDER, 'store_discount_products.json')
BRANCH_CACHE = os.path.join(FOLDER, 'dim_cache.json')
SCHEMA = 2  # v2: dropped store_discount column (bill-ratio method) — dashboard now
            # derives discount = list_amt - net_sales and classifies store vs
            # marketing by solinetype key (O/P/Y = store) at read time
WINDOW_DAYS_DEFAULT = 92  # ~3 months rolling
PRODUCTS_DAYS_KEPT = 2    # store_discount_products.json: today + yesterday only


def load_branches() -> dict:
    """Reuse the RM/DM/store mapping already built by rebuild_fraud_analysis.py."""
    if os.path.exists(BRANCH_CACHE):
        with open(BRANCH_CACHE, encoding='utf-8') as f:
            return json.load(f).get('branches', {})
    return {}


def query_range(conn, start_date: date, end_date_excl: date) -> dict:
    """Query store-discount aggregation for [start_date, end_date_excl).

    Returns {date_str: {whs: {linetype: [qty, cost, net_sales, list_amt, store_discount]}}}
    """
    sql = """
        SELECT
          DATE(s.sodate) AS d,
          LPAD(s.sotowhs,3,'0') AS whs,
          s.solinetype AS linetype,
          SUM(s.net_qty) AS qty,
          SUM(s.total_cost) AS cost,
          SUM(s.net_sales_amt) AS net_sales,
          SUM(dp.ipunit3 * s.net_qty) AS list_amt
        FROM fact_sales s
        JOIN dim_product dp ON dp.iprod = s.iprod
        WHERE s.sodate >= %s AND s.sodate < %s
          AND s.sotowhs REGEXP '^[0-9]+$'
          AND CAST(s.sotowhs AS UNSIGNED) BETWEEN 1 AND 500
        GROUP BY d, whs, linetype
    """
    cur = conn.cursor()
    cur.execute(sql, (start_date.isoformat(), end_date_excl.isoformat()))
    days: dict = {}
    n = 0
    for d, whs, linetype, qty, cost, net_sales, list_amt in cur:
        n += 1
        d_str = d.isoformat() if hasattr(d, 'isoformat') else str(d)
        linetype = linetype or '?'
        day_bucket = days.setdefault(d_str, {})
        whs_bucket = day_bucket.setdefault(whs, {})
        whs_bucket[linetype] = [
            round(float(qty or 0), 2),
            round(float(cost or 0), 2),
            round(float(net_sales or 0), 2),
            round(float(list_amt or 0), 2),
        ]
    cur.close()
    print(f'      {n:,} (date, store, linetype) rows from fact_sales')
    return days


def query_product_detail(conn, target_date: date) -> dict:
    """Product-level detail (barcode, name, qty, unit price, discount, net sales)
    for ONE day only, per store. This is the 'drill into a store's linetype ->
    per-product' view added 2026-07-09. Kept separate from store_discount_data.json
    (which is aggregated, 92-day rolling) because per-product-per-store detail is
    much bigger — only the latest day is kept, overwritten daily, not accumulated.
    """
    sql = """
        SELECT LPAD(s.sotowhs,3,'0') AS whs, s.iprod, s.solinetype AS linetype,
          SUM(s.net_qty) AS qty, SUM(s.net_sales_amt) AS net_sales,
          SUM(dp.ipunit3 * s.net_qty) AS list_amt, dp.ipunit3 AS unit_price, dp.idesc AS name,
          (SELECT MIN(b.barcode) FROM dim_item_barcode b WHERE b.parcode = s.iprod AND b.baractive='Y') AS barcode
        FROM fact_sales s
        JOIN dim_product dp ON dp.iprod = s.iprod
        WHERE s.sodate >= %s AND s.sodate < %s
          AND s.sotowhs REGEXP '^[0-9]+$'
          AND CAST(s.sotowhs AS UNSIGNED) BETWEEN 1 AND 500
        GROUP BY whs, s.iprod, linetype, dp.ipunit3, dp.idesc
    """
    start = target_date.isoformat()
    end_excl = (target_date + timedelta(days=1)).isoformat()
    cur = conn.cursor()
    cur.execute(sql, (start, end_excl))
    stores: dict = {}
    n = 0
    for whs, iprod, linetype, qty, net_sales, list_amt, unit_price, name, barcode in cur:
        n += 1
        bucket = stores.setdefault(whs, [])
        list_amt = float(list_amt or 0)
        net_sales = float(net_sales or 0)
        bucket.append({
            'iprod': iprod,
            'barcode': barcode or iprod,
            'name': name or iprod,
            'linetype': linetype or '?',
            'qty': round(float(qty or 0), 2),
            'unit_price': round(float(unit_price or 0), 2),
            'list_amt': round(list_amt, 2),
            'net_sales': round(net_sales, 2),
            'discount': round(list_amt - net_sales, 2),
        })
    cur.close()
    print(f'      {n:,} (store, product, linetype) rows for product detail on {target_date.isoformat()}')
    return stores


def merge_days(existing: dict, fresh: dict, window_days: int) -> dict:
    """Merge fresh day-buckets into existing, then trim to rolling window."""
    merged = dict(existing)
    merged.update(fresh)  # fresh always wins for overlapping dates
    cutoff = (date.today() - timedelta(days=window_days)).isoformat()
    merged = {d: v for d, v in merged.items() if d >= cutoff}
    return merged


def build(days_arg: int | None, single_day: str | None, push: bool):
    conn = get_conn()
    branches = load_branches()

    existing = {}
    if os.path.exists(OUT_FILE):
        with open(OUT_FILE, encoding='utf-8') as f:
            existing = json.load(f).get('days', {})

    if single_day:
        d = datetime.strptime(single_day, '%Y-%m-%d').date()
        print(f'[build_store_discount_data] single-day update: {d.isoformat()}')
        fresh = query_range(conn, d, d + timedelta(days=1))
        window_days = WINDOW_DAYS_DEFAULT
    else:
        window_days = days_arg or WINDOW_DAYS_DEFAULT
        end_excl = date.today() + timedelta(days=1)
        start = end_excl - timedelta(days=window_days)
        print(f'[build_store_discount_data] backfill range: {start} .. {end_excl} ({window_days}d)')
        fresh = query_range(conn, start, end_excl)

    conn.close()

    merged_days = merge_days(existing, fresh, window_days)

    output = {
        'schema': SCHEMA,
        'generated_at': datetime.now().isoformat(timespec='seconds'),
        'window_days': window_days,
        'branches': branches,
        'days': merged_days,
    }

    size = safe_write_json(OUT_FILE, output)
    print(f'[build_store_discount_data] wrote {OUT_FILE} ({size:,} bytes, '
          f'{len(merged_days)} days, {len(branches)} branches)')

    # Product-level detail (barcode/name/qty/price) — latest PRODUCTS_DAYS_KEPT
    # days only (default 2: today + yesterday, so the UI can show day-on-day
    # comparison at product level too), fully overwritten each run — not
    # accumulated onto the 92-day history (see query_product_detail docstring).
    recent_day_strs = sorted(merged_days.keys())[-PRODUCTS_DAYS_KEPT:] if merged_days else []
    if recent_day_strs:
        conn2 = get_conn()
        products_days = {}
        for d_str in recent_day_strs:
            d = datetime.strptime(d_str, '%Y-%m-%d').date()
            products_days[d_str] = query_product_detail(conn2, d)
        conn2.close()
        products_output = {
            'schema': 2,
            'dates': recent_day_strs,
            'generated_at': datetime.now().isoformat(timespec='seconds'),
            'days': products_days,
        }
        psize = safe_write_json(PRODUCTS_OUT_FILE, products_output)
        print(f'[build_store_discount_data] wrote {PRODUCTS_OUT_FILE} ({psize:,} bytes, '
              f'dates={recent_day_strs})')
    else:
        print('[build_store_discount_data] no days in output — skipping product detail')

    if push:
        push_github(OUT_FILE, 'store_discount_data.json')
        if recent_day_strs:
            push_github(PRODUCTS_OUT_FILE, 'store_discount_products.json')


def push_github(local_path, repo_filename):
    from lib.db import github_token, github_repo
    import base64
    import urllib.request

    token = github_token()
    repo = github_repo()
    if not token:
        print('[build_store_discount_data] no github_token in db_config.json — skip push')
        return

    with open(local_path, 'rb') as f:
        content_b64 = base64.b64encode(f.read()).decode('ascii')

    api_base = f'https://api.github.com/repos/{repo}/contents/{repo_filename}'
    req = urllib.request.Request(api_base, headers={
        'Authorization': f'token {token}',
        'Accept': 'application/vnd.github+json',
    })
    sha = None
    try:
        with urllib.request.urlopen(req) as resp:
            sha = json.loads(resp.read()).get('sha')
    except Exception:
        pass

    payload = {
        'message': f'Update {repo_filename} ({datetime.now().isoformat(timespec="seconds")})',
        'content': content_b64,
    }
    if sha:
        payload['sha'] = sha

    req2 = urllib.request.Request(
        api_base, data=json.dumps(payload).encode('utf-8'), method='PUT',
        headers={
            'Authorization': f'token {token}',
            'Accept': 'application/vnd.github+json',
            'Content-Type': 'application/json',
        })
    with urllib.request.urlopen(req2) as resp:
        result = json.loads(resp.read())
        print(f'[build_store_discount_data] pushed {repo_filename}: {result.get("commit", {}).get("sha", "?")}')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--days', type=int, default=None, help='rolling window size (default 92)')
    ap.add_argument('--day', type=str, default=None, help='single day YYYY-MM-DD incremental update')
    ap.add_argument('--no-push', action='store_true')
    args = ap.parse_args()
    build(args.days, args.day, push=not args.no_push)


if __name__ == '__main__':
    main()
