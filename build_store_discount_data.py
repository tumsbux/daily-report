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
       whs (sotowhs)    -> dim_branch (RM/DM), queried fresh from dim_branch on every
       run (FIXED 2026-07-09: used to reuse dim_cache.json built by
       rebuild_fraud_analysis.py, which went stale when a store's RM assignment
       changed in dim_branch and silently misattributed that store's sales to the
       wrong RM — see Decisions.md [2026-07-09] branches-cache-staleness fix)

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
import time
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

BKK_TZ = ZoneInfo('Asia/Bangkok')


def now_bkk() -> datetime:
    """Bangkok-local now (GHA runner is UTC — datetime.now() alone is 7h behind)."""
    return datetime.now(BKK_TZ)

FOLDER = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, FOLDER)

from lib.db import get_conn, get_config          # noqa: E402
from lib.safe_write import safe_write_json        # noqa: E402

# Errno 2013 = "Lost connection to MySQL server during query" (seen 2026-07-10,
# GHA run #187 — build_store_discount_data.py crashed mid-92-day query and the
# workflow's continue-on-error masked it as a silent success). 2006 = "server
# has gone away", same failure family. RETRYABLE_ERRNOS below are retried with
# a fresh connection instead of killing the whole build.
RETRYABLE_ERRNOS = {2013, 2006}
CHUNK_DAYS = 14   # query_range pulls this many days per query instead of the
                   # full window in one shot, so a dropped connection only
                   # costs one chunk's worth of retry, not the whole 92 days
MAX_QUERY_RETRIES = 3
RETRY_DELAY_SECS = 5

OUT_FILE = os.path.join(FOLDER, 'store_discount_data.json')
PRODUCTS_OUT_DIR = os.path.join(FOLDER, 'store_discount_products')  # one small file per store
SCHEMA = 2  # v2: dropped store_discount column (bill-ratio method) — dashboard now
            # derives discount = list_amt - net_sales and classifies store vs
            # marketing by solinetype key (O/P/Y = store) at read time
WINDOW_DAYS_DEFAULT = 92  # ~3 months rolling
PRODUCTS_DAYS_KEPT = 2    # store_discount_products.json: today + yesterday only


def load_branches(conn) -> dict:
    """Query dim_branch directly for the current RM/DM/store mapping.

    FIXED 2026-07-09: previously reused dim_cache.json (built by
    rebuild_fraud_analysis.py) instead of querying dim_branch fresh. That cache
    is only refreshed when the fraud script happens to run, so when a store's
    code/RM assignment changes in dim_branch (e.g. store 080/081 code
    reassignment discovered 2026-07-09 — verified against live DB, sales for
    080 were being silently misattributed to the WRONG RM because the stale
    cache still mapped 080 to the old RM), this dashboard's RM/DM rollups would
    be wrong until the fraud cache happened to refresh. Querying dim_branch
    directly here removes that cross-script dependency entirely.
    """
    sql = """
        SELECT code, name, dm, dm_code, rm, rm_code
        FROM dim_branch
        WHERE code REGEXP '^[0-9]+$' AND CAST(code AS UNSIGNED) BETWEEN 1 AND 500
    """
    cur = conn.cursor()
    cur.execute(sql)
    branches = {}
    for code, name, dm, dm_code, rm, rm_code in cur:
        branches[str(code).zfill(3)] = {
            'name': name, 'dm': dm, 'dm_code': dm_code, 'rm': rm, 'rm_code': rm_code,
        }
    cur.close()
    print(f'[build_store_discount_data] loaded {len(branches)} branches fresh from dim_branch')
    return branches


def _query_range_once(conn, start_date: date, end_date_excl: date) -> tuple[dict, int]:
    """Single-shot query for [start_date, end_date_excl) on an already-open conn.
    Raises mysql.connector.errors.OperationalError on connection loss — caller
    (query_range) catches this and retries with a fresh connection.
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
    return days, n


def query_range(start_date: date, end_date_excl: date) -> dict:
    """Query store-discount aggregation for [start_date, end_date_excl), split
    into CHUNK_DAYS-sized pieces, each on its OWN fresh connection, with retry
    on connection loss (errno 2013/2006 — see RETRYABLE_ERRNOS docstring above).

    FIXED 2026-07-10: previously took a single long-lived `conn` and ran the
    whole window (e.g. 92 days) as one query. GHA run #187 crashed with
    "mysql.connector.errors.OperationalError: 2013 (HY000): Lost connection to
    MySQL server during query" partway through — because build_store_discount_data.py
    runs LAST in the daily pipeline (after ~17 min of other DB-heavy steps),
    and continue-on-error in the workflow silently swallowed the crash, so the
    dashboard's data silently stopped updating. Chunking means a dropped
    connection only costs one ~14-day chunk's retry, not the whole build; a
    fresh connection per chunk avoids reusing one that's gone stale/idle.
    """
    import mysql.connector.errors as _mysql_errors

    days: dict = {}
    total_n = 0
    cur_start = start_date
    while cur_start < end_date_excl:
        cur_end = min(cur_start + timedelta(days=CHUNK_DAYS), end_date_excl)
        attempt = 0
        while True:
            attempt += 1
            conn = get_conn()
            try:
                chunk_days, n = _query_range_once(conn, cur_start, cur_end)
                total_n += n
                for d_str, whs_map in chunk_days.items():
                    days.setdefault(d_str, {}).update(whs_map)
                break
            except _mysql_errors.OperationalError as e:
                errno = getattr(e, 'errno', None)
                if errno not in RETRYABLE_ERRNOS or attempt >= MAX_QUERY_RETRIES:
                    raise
                print(f'      WARN: chunk {cur_start}..{cur_end} lost connection '
                      f'(errno {errno}), retry {attempt}/{MAX_QUERY_RETRIES - 1} '
                      f'in {RETRY_DELAY_SECS}s...')
                time.sleep(RETRY_DELAY_SECS)
            finally:
                try:
                    conn.close()
                except Exception:
                    pass
        cur_start = cur_end

    print(f'      {total_n:,} (date, store, linetype) rows from fact_sales '
          f'(chunked {CHUNK_DAYS}d/query)')
    return days


def _query_product_detail_once(conn, target_date: date) -> tuple[dict, int]:
    sql = """
        SELECT LPAD(s.sotowhs,3,'0') AS whs, s.iprod, s.solinetype AS linetype,
          SUM(s.net_qty) AS qty, SUM(s.net_sales_amt) AS net_sales,
          SUM(dp.ipunit3 * s.net_qty) AS list_amt, dp.ipunit3 AS unit_price, dp.idesc AS name,
          SUM(s.total_cost) AS cost,
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
    for whs, iprod, linetype, qty, net_sales, list_amt, unit_price, name, cost, barcode in cur:
        n += 1
        bucket = stores.setdefault(whs, [])
        list_amt = float(list_amt or 0)
        net_sales = float(net_sales or 0)
        cost = float(cost or 0)
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
            'cost': round(cost, 2),
        })
    cur.close()
    return stores, n


def query_product_detail(target_date: date) -> dict:
    """Product-level detail (barcode, name, qty, unit price, discount, net sales)
    for ONE day only, per store. This is the 'drill into a store's linetype ->
    per-product' view added 2026-07-09. Kept separate from store_discount_data.json
    (which is aggregated, 92-day rolling) because per-product-per-store detail is
    much bigger — only the latest day is kept, overwritten daily, not accumulated.

    NOTE 2026-07-10: added SUM(s.total_cost) AS cost so the product-level table
    can show GP% per line item (previously GP% only existed at RM/DM/store/
    linetype aggregate levels, not per product) — see Decisions.md [2026-07-10]

    FIXED 2026-07-10: now opens its OWN fresh connection per call and retries
    on connection loss (errno 2013/2006), same fix as query_range — see that
    function's docstring for why (GHA run #187 crash).
    """
    import mysql.connector.errors as _mysql_errors

    attempt = 0
    while True:
        attempt += 1
        conn = get_conn()
        try:
            stores, n = _query_product_detail_once(conn, target_date)
            print(f'      {n:,} (store, product, linetype) rows for product '
                  f'detail on {target_date.isoformat()}')
            return stores
        except _mysql_errors.OperationalError as e:
            errno = getattr(e, 'errno', None)
            if errno not in RETRYABLE_ERRNOS or attempt >= MAX_QUERY_RETRIES:
                raise
            print(f'      WARN: product detail {target_date.isoformat()} lost '
                  f'connection (errno {errno}), retry {attempt}/'
                  f'{MAX_QUERY_RETRIES - 1} in {RETRY_DELAY_SECS}s...')
            time.sleep(RETRY_DELAY_SECS)
        finally:
            try:
                conn.close()
            except Exception:
                pass


def merge_days(existing: dict, fresh: dict, window_days: int) -> dict:
    """Merge fresh day-buckets into existing, then trim to rolling window."""
    merged = dict(existing)
    merged.update(fresh)  # fresh always wins for overlapping dates
    cutoff = (date.today() - timedelta(days=window_days)).isoformat()
    merged = {d: v for d, v in merged.items() if d >= cutoff}
    return merged


def build(days_arg: int | None, single_day: str | None, push: bool):
    # NOTE 2026-07-10: load_branches still uses one short-lived connection
    # (it's a fast single query). query_range/query_product_detail now open
    # and close their OWN connections internally (chunked + retry-safe) —
    # see their docstrings for why (GHA run #187 crash mid-query).
    conn = get_conn()
    branches = load_branches(conn)
    conn.close()

    existing = {}
    if os.path.exists(OUT_FILE):
        with open(OUT_FILE, encoding='utf-8') as f:
            existing = json.load(f).get('days', {})

    if single_day:
        d = datetime.strptime(single_day, '%Y-%m-%d').date()
        print(f'[build_store_discount_data] single-day update: {d.isoformat()}')
        fresh = query_range(d, d + timedelta(days=1))
        window_days = WINDOW_DAYS_DEFAULT
    else:
        window_days = days_arg or WINDOW_DAYS_DEFAULT
        end_excl = date.today() + timedelta(days=1)
        start = end_excl - timedelta(days=window_days)
        print(f'[build_store_discount_data] backfill range: {start} .. {end_excl} ({window_days}d)')
        fresh = query_range(start, end_excl)

    merged_days = merge_days(existing, fresh, window_days)

    output = {
        'schema': SCHEMA,
        'generated_at': now_bkk().isoformat(timespec='seconds'),
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
    # 2026-07-09: split into ONE SMALL FILE PER STORE (store_discount_products/<whs>.json)
    # instead of one combined ~24MB file — combined file made the dashboard's
    # per-store drill-down fetch the whole thing just to look at one store.
    recent_day_strs = sorted(merged_days.keys())[-PRODUCTS_DAYS_KEPT:] if merged_days else []
    product_file_paths: list[str] = []
    if recent_day_strs:
        by_day: dict[str, dict] = {}
        for d_str in recent_day_strs:
            d = datetime.strptime(d_str, '%Y-%m-%d').date()
            by_day[d_str] = query_product_detail(d)  # opens/retries its own connection

        # reshape from {date: {whs: [items]}} to {whs: {date: [items]}}
        all_whs = set()
        for day_stores in by_day.values():
            all_whs.update(day_stores.keys())

        os.makedirs(PRODUCTS_OUT_DIR, exist_ok=True)
        total_bytes = 0
        for whs in sorted(all_whs):
            store_days = {d_str: by_day[d_str].get(whs, []) for d_str in recent_day_strs}
            store_output = {
                'schema': 3,
                'whs': whs,
                'dates': recent_day_strs,
                'generated_at': now_bkk().isoformat(timespec='seconds'),
                'days': store_days,
            }
            path = os.path.join(PRODUCTS_OUT_DIR, f'{whs}.json')
            total_bytes += safe_write_json(path, store_output)
            product_file_paths.append(path)
        print(f'[build_store_discount_data] wrote {len(product_file_paths)} per-store product '
              f'files to {PRODUCTS_OUT_DIR} ({total_bytes:,} bytes total, dates={recent_day_strs})')
    else:
        print('[build_store_discount_data] no days in output — skipping product detail')

    if push:
        push_github(OUT_FILE, 'store_discount_data.json')
        if product_file_paths:
            rel_paths = [os.path.relpath(p, FOLDER).replace('\\', '/') for p in product_file_paths]
            push_github_tree(rel_paths, f'Update store_discount_products/ ({now_bkk().isoformat(timespec="seconds")})')


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
        'message': f'Update {repo_filename} ({now_bkk().isoformat(timespec="seconds")})',
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


def push_github_tree(rel_paths: list[str], message: str):
    """Push MANY files as ONE commit via the Git Data API (blob+tree+commit),
    same approach as push_files_api.py. Used for store_discount_products/ (202
    small per-store files) so a daily run doesn't create 202 separate commits.
    """
    from lib.db import github_token, github_repo
    import base64
    import urllib.request
    import urllib.error
    import time as _time

    token = github_token()
    repo = github_repo()
    if not token:
        print('[build_store_discount_data] no github_token in db_config.json — skip push')
        return

    headers = {
        'Authorization': f'token {token}',
        'Accept': 'application/vnd.github+json',
        'Content-Type': 'application/json',
    }

    def api(method, path, body=None, retries=4):
        # 401 on git/blobs during this 202-file bulk-POST loop has been observed to be
        # a TRANSIENT secondary-rate-limit/abuse-detection response from GitHub (the
        # same token succeeds again seconds later) rather than a real bad-credentials
        # error — see Decisions.md [2026-07-10]. Retry it like a 5xx instead of raising
        # immediately.
        url = f'https://api.github.com/{path}'
        data = json.dumps(body).encode() if body is not None else None
        for attempt in range(retries):
            req = urllib.request.Request(url, data=data, method=method, headers=headers)
            try:
                with urllib.request.urlopen(req, timeout=300) as r:
                    return json.loads(r.read())
            except urllib.error.HTTPError as e:
                if (e.code >= 500 or e.code in (401, 403)) and attempt < retries - 1:
                    wait = 10 * (attempt + 1)
                    print(f'      WARN: HTTP {e.code} on {method} {path} — retry '
                          f'{attempt + 1}/{retries - 1} in {wait}s...')
                    _time.sleep(wait)
                    continue
                raise RuntimeError(f'HTTP {e.code} on {method} {path}: {e.read().decode()[:300]}')
            except (urllib.error.URLError, TimeoutError):
                if attempt < retries - 1:
                    _time.sleep(10 * (attempt + 1))
                    continue
                raise

    ref = api('GET', f'repos/{repo}/git/ref/heads/main')
    parent = ref['object']['sha']
    commit = api('GET', f'repos/{repo}/git/commits/{parent}')

    tree_items = []
    for i, rel in enumerate(rel_paths):
        local = os.path.join(FOLDER, rel)
        if not os.path.exists(local):
            continue
        with open(local, 'rb') as fh:
            blob = api('POST', f'repos/{repo}/git/blobs',
                       {'content': base64.b64encode(fh.read()).decode(), 'encoding': 'base64'})
        tree_items.append({'path': rel, 'mode': '100644', 'type': 'blob', 'sha': blob['sha']})
        # small pacing delay — ~200 sequential blob POSTs in a tight loop is the
        # likely trigger for GitHub's secondary rate-limit/abuse detection (see
        # Decisions.md [2026-07-10]); this cuts request rate without meaningfully
        # slowing the ~202-file run (adds ~30s total).
        if i % 20 == 19:
            _time.sleep(1)

    if not tree_items:
        print('[build_store_discount_data] push_github_tree: no files found — skip')
        return

    tree = api('POST', f'repos/{repo}/git/trees',
               {'base_tree': commit['tree']['sha'], 'tree': tree_items})
    new_commit = api('POST', f'repos/{repo}/git/commits',
                     {'message': message, 'tree': tree['sha'], 'parents': [parent]})
    api('PATCH', f'repos/{repo}/git/refs/heads/main', {'sha': new_commit['sha']})
    print(f'[build_store_discount_data] pushed {len(tree_items)} files in 1 commit: '
          f'{new_commit["sha"][:8]}')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--days', type=int, default=None, help='rolling window size (default 92)')
    ap.add_argument('--day', type=str, default=None, help='single day YYYY-MM-DD incremental update')
    ap.add_argument('--no-push', action='store_true')
    args = ap.parse_args()
    build(args.days, args.day, push=not args.no_push)


if __name__ == '__main__':
    main()
