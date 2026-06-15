"""build_visual_adj.py — Phase D: Visual Adjustment Audit
แหล่งข้อมูล:
  - ibl  (locno='visual', shelfno='adjustment') → cumulative net per store/product
  - itd_acc (itd_to_locno='visual')             → recent sessions with date

Output: visual_adj_data.json
Usage:
  py build_visual_adj.py             # build + push
  py build_visual_adj.py --no-push  # build only
"""

import sys, os, json, argparse, traceback
from datetime import datetime, timezone

try:
    import mysql.connector
except ImportError:
    print('ERROR: pip install mysql-connector-python'); sys.exit(1)

SCRIPT_DIR  = os.path.dirname(os.path.abspath(__file__))
OUTPUT_FILE = os.path.join(SCRIPT_DIR, 'visual_adj_data.json')
BUILT_BY    = 'claude-sonnet-4-6'

DB_PATHS = [
    os.path.join(SCRIPT_DIR, 'db_config.json'),
    r'F:\co work dashboard\db_config.json',
]

def load_cfg():
    for p in DB_PATHS:
        if os.path.exists(p):
            return json.load(open(p, encoding='utf-8'))
    raise FileNotFoundError('db_config.json not found')

def conn(cfg, db='MYWMS2023_CENTER'):
    return mysql.connector.connect(
        host=cfg['host'], port=int(cfg.get('port', 13306)),
        user=cfg['user'], password=cfg['password'],
        database=db, charset='utf8mb3', connection_timeout=60,
    )

# ── 1. store names ────────────────────────────────────────────────────────────
def query_stores(cfg):
    print('[1/4] Loading dim_branch ...')
    c = mysql.connector.connect(
        host=cfg['host'], port=int(cfg.get('port', 13306)),
        user=cfg['user'], password=cfg['password'],
        database='data-lake', charset='utf8mb3', connection_timeout=30,
    )
    cur = c.cursor()
    cur.execute("SELECT code, name, dm, rm FROM `data-lake`.dim_branch")
    stores = {}
    for code, name, dm, rm in cur:
        try:
            n = int(str(code).strip())
            if 1 <= n <= 500:
                stores[f'{n:03d}'] = {'name': name or '', 'dm': dm or '', 'rm': rm or ''}
        except (ValueError, TypeError):
            pass
    cur.close(); c.close()
    print(f'  {len(stores):,} stores')
    return stores

# ── 2. ibl cumulative per store ────────────────────────────────────────────────
def query_ibl_stores(cfg):
    print('[2/4] Querying ibl store summary ...')
    c = conn(cfg)
    cur = c.cursor()
    cur.execute("""
        SELECT ibl_whsno,
               COUNT(DISTINCT ibl_parcode)              AS products,
               ROUND(SUM(ibl_qty_rec), 0)               AS qty_up,
               ROUND(SUM(ibl_qty_iss), 0)               AS qty_down,
               ROUND(SUM(ibl_qty_rec - ibl_qty_iss), 0) AS net_qty,
               ROUND(SUM(ibl_cst_rec - ibl_cst_iss), 0) AS net_value
        FROM MYWMS2023_CENTER.ibl
        WHERE ibl_locno='visual' AND ibl_shelfno='adjustment'
          AND ibl_whsno REGEXP '^[0-9]+'
        GROUP BY ibl_whsno
    """)
    rows = []
    for whsno, products, qty_up, qty_down, net_qty, net_value in cur:
        try:
            n = int(str(whsno).strip())
            if not (1 <= n <= 500):
                continue
        except (ValueError, TypeError):
            continue
        rows.append({
            'store':     f'{n:03d}',
            'products':  int(products or 0),
            'qty_up':    float(qty_up   or 0),
            'qty_down':  float(qty_down or 0),
            'net_qty':   float(net_qty  or 0),
            'net_value': float(net_value or 0),
        })
    cur.close(); c.close()
    print(f'  {len(rows):,} stores with visual adjustments')
    return rows

# ── 3. ibl top products (chain-level) ─────────────────────────────────────────
def query_ibl_products(cfg):
    print('[3/4] Querying ibl product summary (all SKUs with visual adj) ...')
    c = conn(cfg)
    cur = c.cursor()
    cur.execute("""
        SELECT ibl_parcode,
               COUNT(DISTINCT ibl_whsno)                AS stores,
               ROUND(SUM(ibl_qty_rec), 0)               AS qty_up,
               ROUND(SUM(ibl_qty_iss), 0)               AS qty_down,
               ROUND(SUM(ibl_qty_rec - ibl_qty_iss), 0) AS net_qty,
               ROUND(SUM(ibl_cst_rec - ibl_cst_iss), 0) AS net_value
        FROM MYWMS2023_CENTER.ibl
        WHERE ibl_locno='visual' AND ibl_shelfno='adjustment'
          AND ibl_whsno REGEXP '^[0-9]+'
        GROUP BY ibl_parcode
        ORDER BY ABS(SUM(ibl_qty_rec - ibl_qty_iss)) DESC
    """)
    products_raw = []
    iprods = []
    for row in cur:
        parcode, stores, qty_up, qty_down, net_qty, net_value = row
        products_raw.append({
            'iprod':     str(parcode),
            'stores':    int(stores or 0),
            'qty_up':    float(qty_up   or 0),
            'qty_down':  float(qty_down or 0),
            'net_qty':   float(net_qty  or 0),
            'net_value': float(net_value or 0),
        })
        iprods.append(str(parcode))
    cur.close(); c.close()

    # resolve names
    names = {}
    if iprods:
        c2 = mysql.connector.connect(
            host=cfg['host'], port=int(cfg.get('port', 13306)),
            user=cfg['user'], password=cfg['password'],
            database='data-lake', charset='utf8mb3', connection_timeout=30,
        )
        cur2 = c2.cursor()
        cur2.execute("SELECT iprod, idesc, igrcode FROM `data-lake`.dim_product")
        iprod_set = set(iprods)
        for iprod, idesc, igrcode in cur2:
            if str(iprod) in iprod_set:
                names[str(iprod)] = {'name': idesc or '', 'group': igrcode or ''}
        cur2.close(); c2.close()

    for p in products_raw:
        info = names.get(p['iprod'], {})
        p['name']  = info.get('name', '')
        p['group'] = info.get('group', '')

    print(f'  {len(products_raw):,} products, {len(names):,} names resolved')
    return products_raw

# ── 4. itd_acc recent sessions (UNION itd_acc + itd_acc_20260610) ────────────
def query_recent_sessions(cfg):
    print('[4/4] Querying itd_acc + itd_acc_20260610 sessions ...')
    c = conn(cfg)
    cur = c.cursor()
    cur.execute("""
        SELECT itd_fr_whsno                              AS store,
               itd_refno                                 AS session_ref,
               itd_datetime                              AS sess_date,
               COUNT(*)                                  AS txn_count,
               ROUND(SUM(ABS(itd_qty)), 0)               AS total_qty,
               ROUND(SUM(ABS(itd_qty * itd_costunit)), 0) AS total_value
        FROM (
            SELECT itd_fr_whsno, itd_refno, itd_datetime, itd_qty, itd_costunit
            FROM MYWMS2023_CENTER.itd_acc
            WHERE itd_to_locno='visual' AND itd_to_shelfno='adjustment'
              AND itd_fr_whsno REGEXP '^[0-9]+'
            UNION ALL
            SELECT itd_fr_whsno, itd_refno, itd_datetime, itd_qty, itd_costunit
            FROM MYWMS2023_CENTER.itd_acc_20260610
            WHERE itd_to_locno='visual' AND itd_to_shelfno='adjustment'
              AND itd_fr_whsno REGEXP '^[0-9]+'
        ) combined
        GROUP BY itd_fr_whsno, itd_refno, itd_datetime
        ORDER BY itd_datetime DESC, total_qty DESC
    """)
    sessions = []
    for store, ref, date_val, txn, qty, value in cur:
        try:
            n = int(str(store).strip())
            if not (1 <= n <= 500):
                continue
        except (ValueError, TypeError):
            continue
        sessions.append({
            'store':       f'{n:03d}',
            'session_ref': str(ref or ''),
            'date':        date_val.isoformat() if date_val else None,
            'txn_count':   int(txn   or 0),
            'total_qty':   float(qty   or 0),
            'total_value': float(value or 0),
        })
    cur.close(); c.close()
    print(f'  {len(sessions):,} sessions loaded')
    return sessions

# ── build JSON ────────────────────────────────────────────────────────────────
def build_json(store_rows, product_rows, sessions, stores_meta):
    # enrich store rows with dim_branch info
    for r in store_rows:
        info = stores_meta.get(r['store'], {})
        r['name'] = info.get('name', '')
        r['dm']   = info.get('dm', '')
        r['rm']   = info.get('rm', '')

    # session summary per store
    sess_by_store = {}
    for s in sessions:
        st = s['store']
        if st not in sess_by_store:
            sess_by_store[st] = {'session_count': 0, 'recent_date': None, 'recent_qty': 0}
        sess_by_store[st]['session_count'] += 1
        if sess_by_store[st]['recent_date'] is None or s['date'] > sess_by_store[st]['recent_date']:
            sess_by_store[st]['recent_date'] = s['date']
            sess_by_store[st]['recent_qty']  = s['total_qty']

    for r in store_rows:
        ss = sess_by_store.get(r['store'], {})
        r['session_count'] = ss.get('session_count', 0)
        r['recent_date']   = ss.get('recent_date')
        r['recent_qty']    = ss.get('recent_qty', 0)

    # sort store rows by |net_value| desc
    store_rows.sort(key=lambda r: abs(r['net_value']), reverse=True)

    total_net_qty   = sum(r['net_qty']   for r in store_rows)
    total_net_value = sum(r['net_value'] for r in store_rows)

    payload = {
        '_meta': {
            'schema':   1,
            'built_by': BUILT_BY,
            'built_at': datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
            'note':     'ibl=cumulative all-time | itd_acc=recent sessions only',
        },
        'summary': {
            'total_stores':    len(store_rows),
            'total_products':  len(product_rows),
            'total_sessions':  len(sessions),
            'total_net_qty':   round(total_net_qty, 0),
            'total_net_value': round(total_net_value, 0),
        },
        'stores':   store_rows,
        'products': product_rows,
        'sessions': sessions,
    }

    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, separators=(',', ':'))

    size_mb = os.path.getsize(OUTPUT_FILE) / 1024 / 1024
    print(f'\nOutput: {OUTPUT_FILE} ({size_mb:.1f} MB)')
    print(f'  stores={len(store_rows)} products={len(product_rows)} sessions={len(sessions)}')
    print(f'  net_qty={total_net_qty:,.0f}  net_value=฿{total_net_value:,.0f}')
    return payload

# ── push ──────────────────────────────────────────────────────────────────────
def push(cfg):
    import subprocess
    ps = os.path.join(SCRIPT_DIR, 'push_files_api.py')
    if not os.path.exists(ps):
        ps = r'F:\co work dashboard\push_files_api.py'
    if not os.path.exists(ps):
        print('WARNING: push_files_api.py not found'); return
    r = subprocess.run(
        [sys.executable, ps, OUTPUT_FILE, '-m', 'data(visual-adj): rebuild visual_adj_data.json'],
        capture_output=True, text=True
    )
    if r.stdout: print(r.stdout)
    if r.stderr: print(r.stderr, file=sys.stderr)

# ── main ──────────────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--no-push', action='store_true')
    args = ap.parse_args()

    print('=== Visual Adjustment Audit Builder ===')
    try:
        cfg           = load_cfg()
        stores_meta   = query_stores(cfg)
        store_rows    = query_ibl_stores(cfg)
        product_rows  = query_ibl_products(cfg)
        sessions      = query_recent_sessions(cfg)
        build_json(store_rows, product_rows, sessions, stores_meta)

        if not args.no_push:
            push(cfg)
        else:
            print('(--no-push)')
    except Exception as e:
        print(f'ERROR: {type(e).__name__}: {e!r}')
        traceback.print_exc()
        sys.exit(1)

if __name__ == '__main__':
    main()
