"""build_dead_stock.py — Phase C: Dead Stock report
สินค้า onhand > 0 + ไม่มียอดขาย (chain-level) >= THRESHOLD_DAYS วัน

Output: dead_stock_data.json
Usage:
  py build_dead_stock.py              # build + push
  py build_dead_stock.py --no-push   # build only
  py build_dead_stock.py --days 180  # custom threshold
"""

import sys
import os
import json
import argparse
import traceback
from datetime import date, datetime, timedelta, timezone

# ── deps ──────────────────────────────────────────────────────────────────────
try:
    import mysql.connector
except ImportError:
    print('ERROR: pip install mysql-connector-python'); sys.exit(1)

# ── config ────────────────────────────────────────────────────────────────────
SCRIPT_DIR  = os.path.dirname(os.path.abspath(__file__))
OUTPUT_FILE = os.path.join(SCRIPT_DIR, 'dead_stock_data.json')
BUILT_BY    = 'claude-sonnet-4-6'

DB_PATHS = [
    os.path.join(SCRIPT_DIR, 'db_config.json'),
    r'F:\co work dashboard\db_config.json',
]

def load_db_config():
    for p in DB_PATHS:
        if os.path.exists(p):
            return json.load(open(p, encoding='utf-8'))
    raise FileNotFoundError('db_config.json not found')

def get_conn(cfg, database='MYPOS2018_CENTER'):
    return mysql.connector.connect(
        host=cfg['host'], port=int(cfg.get('port', 13306)),
        user=cfg['user'], password=cfg['password'],
        database=database, charset='utf8mb3',
        connection_timeout=30,
    )

# ── step 1: last sale date per product (chain-level) ─────────────────────────
def query_last_sale(cfg):
    """Returns {iprod: last_sale_date} for all products ever sold."""
    print('[1/5] Querying last sale date per product from fact_sales ...')
    conn = mysql.connector.connect(
        host=cfg['host'], port=int(cfg.get('port', 13306)),
        user=cfg['user'], password=cfg['password'],
        database='data-lake', charset='utf8mb3',
        connection_timeout=60,
    )
    cur = conn.cursor()
    cur.execute("""
        SELECT iprod, MAX(DATE(sodate)) as last_sale
        FROM `data-lake`.fact_sales
        GROUP BY iprod
    """)
    last_sale = {}
    for iprod, ls in cur:
        last_sale[str(iprod)] = ls  # date object
    cur.close()
    conn.close()
    print(f'  {len(last_sale):,} products with any sale history')
    return last_sale

# ── step 2: onhand per (iprod, whsno) ────────────────────────────────────────
def query_onhand(cfg):
    """Returns {iprod: {whsno: {qty, value}}} — valid stores only (1-500)."""
    print('[2/5] Querying onhand from ibl ...')
    conn = get_conn(cfg, 'MYWMS2023_CENTER')
    cur = conn.cursor()
    cur.execute("""
        SELECT ibl_parcode, ibl_whsno,
               SUM(ibl_qty_beg_bal + ibl_qty_rec - ibl_qty_iss) as qty,
               SUM(ibl_cst_beg_bal + ibl_cst_rec - ibl_cst_iss) as value
        FROM MYWMS2023_CENTER.ibl
        WHERE ibl_locno='stock' AND ibl_shelfno='shelfno'
        GROUP BY ibl_parcode, ibl_whsno
        HAVING qty > 0
    """)
    onhand = {}  # {iprod: {whsno_str: {qty, value}}}
    skipped = 0
    for iprod, whsno, qty, value in cur:
        # valid_store filter
        try:
            n = int(str(whsno).strip())
            if not (1 <= n <= 500):
                skipped += 1
                continue
        except (ValueError, TypeError):
            skipped += 1
            continue
        whs_str = f'{n:03d}'
        ip = str(iprod)
        if ip not in onhand:
            onhand[ip] = {}
        onhand[ip][whs_str] = {
            'qty':   float(qty)   if qty   is not None else 0.0,
            'value': float(value) if value is not None else 0.0,
        }
    cur.close()
    conn.close()
    print(f'  {len(onhand):,} products with onhand > 0 (skipped {skipped} invalid stores)')
    return onhand

# ── step 3: product names ─────────────────────────────────────────────────────
def query_product_names(cfg, iprods):
    """Returns {iprod: {name, group}} for given set of iprods."""
    print('[3/5] Querying product names from dim_product ...')
    conn = mysql.connector.connect(
        host=cfg['host'], port=int(cfg.get('port', 13306)),
        user=cfg['user'], password=cfg['password'],
        database='data-lake', charset='utf8mb3',
        connection_timeout=30,
    )
    cur = conn.cursor()
    cur.execute("SELECT iprod, idesc, igrcode FROM `data-lake`.dim_product")
    names = {}
    for iprod, idesc, igrcode in cur:
        if str(iprod) in iprods:
            names[str(iprod)] = {
                'name':  idesc  or '',
                'group': igrcode or '',
            }
    cur.close()
    conn.close()
    print(f'  {len(names):,} names resolved')
    return names

# ── step 4: store names ───────────────────────────────────────────────────────
def query_store_names(cfg):
    """Returns {code_padded: {name, dm, rm}}."""
    print('[4/5] Querying store names from dim_branch ...')
    conn = mysql.connector.connect(
        host=cfg['host'], port=int(cfg.get('port', 13306)),
        user=cfg['user'], password=cfg['password'],
        database='data-lake', charset='utf8mb3',
        connection_timeout=30,
    )
    cur = conn.cursor()
    cur.execute("SELECT code, name, dm, rm FROM `data-lake`.dim_branch")
    stores = {}
    for code, name, dm, rm in cur:
        try:
            n = int(str(code).strip())
            stores[f'{n:03d}'] = {'name': name or '', 'dm': dm or '', 'rm': rm or ''}
        except (ValueError, TypeError):
            pass
    cur.close()
    conn.close()
    print(f'  {len(stores):,} stores loaded')
    return stores

# ── step 5: build JSON ────────────────────────────────────────────────────────
def build_json(last_sale, onhand, names, stores, threshold_days, as_of_date):
    print('[5/5] Building dead_stock_data.json ...')
    cutoff = as_of_date - timedelta(days=threshold_days)

    products = []
    for iprod, store_map in onhand.items():
        # chain-level last sale check
        ls = last_sale.get(iprod)
        if ls is not None and ls >= cutoff:
            continue  # sold recently → not dead stock

        # aggregate chain totals
        total_qty   = sum(v['qty']   for v in store_map.values())
        total_value = sum(v['value'] for v in store_map.values())
        if total_qty <= 0:
            continue

        days_since = (as_of_date - ls).days if ls else None
        name_info  = names.get(iprod, {'name': '', 'group': ''})

        store_list = []
        for whs, sv in sorted(store_map.items()):
            si = stores.get(whs, {})
            store_list.append({
                'code':  whs,
                'name':  si.get('name', ''),
                'dm':    si.get('dm', ''),
                'rm':    si.get('rm', ''),
                'qty':   round(sv['qty'],   2),
                'value': round(sv['value'], 2),
            })

        products.append({
            'iprod':      iprod,
            'name':       name_info['name'],
            'group':      name_info['group'],
            'last_sale':  ls.isoformat() if ls else None,
            'days_since': days_since,
            'onhand_qty':   round(total_qty,   2),
            'onhand_value': round(total_value, 2),
            'stores':     store_list,
        })

    # sort by onhand_value descending
    products.sort(key=lambda p: p['onhand_value'], reverse=True)

    total_qty_sum   = sum(p['onhand_qty']   for p in products)
    total_value_sum = sum(p['onhand_value'] for p in products)

    payload = {
        '_meta': {
            'schema':         1,
            'built_by':       BUILT_BY,
            'built_at':       datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
            'as_of':          as_of_date.isoformat(),
            'threshold_days': threshold_days,
        },
        'summary': {
            'total_products':    len(products),
            'total_onhand_qty':  round(total_qty_sum, 2),
            'total_onhand_value': round(total_value_sum, 2),
        },
        'products': products,
    }

    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, separators=(',', ':'))

    size_mb = os.path.getsize(OUTPUT_FILE) / 1024 / 1024
    print(f'  Wrote {len(products):,} dead-stock products → {OUTPUT_FILE} ({size_mb:.1f} MB)')
    return payload

# ── push ──────────────────────────────────────────────────────────────────────
def push_to_github(cfg):
    import importlib.util, subprocess
    push_script = os.path.join(SCRIPT_DIR, 'push_files_api.py')
    if not os.path.exists(push_script):
        # fallback: look in co work dashboard
        push_script = r'F:\co work dashboard\push_files_api.py'
    if not os.path.exists(push_script):
        print('WARNING: push_files_api.py not found — skipping push')
        return
    result = subprocess.run(
        [sys.executable, push_script, OUTPUT_FILE, '-m', 'data(dead-stock): rebuild dead_stock_data.json'],
        capture_output=True, text=True
    )
    if result.stdout: print(result.stdout)
    if result.stderr: print(result.stderr, file=sys.stderr)

# ── main ──────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--no-push', action='store_true')
    parser.add_argument('--days', type=int, default=90, help='Dead stock threshold in days (default: 90)')
    args = parser.parse_args()

    cfg = load_db_config()
    as_of = date.today()

    print(f'=== Dead Stock Builder === threshold={args.days}d  as_of={as_of}')
    try:
        last_sale = query_last_sale(cfg)
        onhand    = query_onhand(cfg)
        iprods    = set(onhand.keys())
        names     = query_product_names(cfg, iprods)
        stores    = query_store_names(cfg)
        payload   = build_json(last_sale, onhand, names, stores, args.days, as_of)

        print(f'\nSummary:')
        print(f"  Dead-stock products : {payload['summary']['total_products']:,}")
        print(f"  Total onhand qty    : {payload['summary']['total_onhand_qty']:,.0f}")
        print(f"  Total onhand value  : ฿{payload['summary']['total_onhand_value']:,.0f}")

        if not args.no_push:
            push_to_github(cfg)
        else:
            print('(--no-push: skipping GitHub push)')

    except Exception as e:
        print(f'ERROR: {type(e).__name__}: {e!r}')
        traceback.print_exc()
        sys.exit(1)

if __name__ == '__main__':
    main()
