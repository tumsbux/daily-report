"""Builds lost_product_data.json — 6-year sales history per product (2021-2026).
Identifies LOST products (no 2025+2026 sales) and STALE (no 2026 sales).

Source: data-lake.bld_acc_*_lake (5 tables: 2021, 2022, 2023, 2024, current)
Output: lost_product_data.json with full year-by-year qty grid + status + lost_score.
Format: compact schema v2 (_meta.schema=2) — global `codes` barcode table,
products as array-of-arrays + products_header, store_breakdown keyed by code
index. See Decisions.md ADR [2026-06-11]. Decoded by index.html decodeData().
"""
import gc
import json, os, sys, warnings
from datetime import date, timedelta
import mysql.connector
import pandas as pd

warnings.filterwarnings('ignore', category=UserWarning, module='pandas')

FOLDER   = os.path.dirname(os.path.abspath(__file__))
OUT_JSON = os.path.join(FOLDER, 'lost_product_data.json')

YEAR_TABLES = {
    2021: ('bld_acc_2021_lake', 'blh_acc_2021_lake'),
    2022: ('bld_acc_2022_lake', 'blh_acc_2022_lake'),
    2023: ('bld_acc_2023_lake', 'blh_acc_2023_lake'),
    2024: ('bld_acc_2024_lake', 'blh_acc_2024_lake'),
}
CURRENT_TABLES = ('bld_acc_lake', 'blh_acc_lake')   # holds 2025 + 2026
CURRENT_YEAR  = date.today().year
YEARS         = sorted(list(YEAR_TABLES.keys()) + [2025, CURRENT_YEAR])  # [2021..2026]


# ── Connection ───────────────────────────────────────────────────────────────
def _load_cfg():
    try:
        return json.load(open(os.path.join(FOLDER, 'db_config.json'), encoding='utf-8'))
    except FileNotFoundError:
        return None

def _conn(cfg, db='data-lake'):
    return mysql.connector.connect(
        host=cfg['host'], port=cfg.get('port', 3306),
        user=cfg['user'], password=cfg['password'],
        database=db,
    )


# ── STEP 1: Per-year qty aggregation ─────────────────────────────────────────
def query_year(conn, bld_table, blh_table, where_year=None):
    """Returns ({iprod: total_qty}, {(whs,iprod): qty}) for one year of sales.
    JOIN bld_acc + blh_acc on sono to get real sotowhs (matches dim_branch.code)
    and sodate (DATETIME, supports YEAR())."""
    if where_year is not None:
        year_filter = (
            f"AND blh.sodate >= '{where_year}-01-01' "
            f"AND blh.sodate <  '{where_year+1}-01-01'"
        )
    else:
        year_filter = ""

    sql_tot = f"""
        SELECT bld.iprod, SUM(bld.soqty) AS qty
        FROM `{bld_table}` bld
        JOIN `{blh_table}` blh ON blh.sono = bld.sono
        WHERE bld.solinetype NOT IN ('C', 'R')
          {year_filter}
        GROUP BY bld.iprod
        HAVING qty > 0
    """
    gc.collect()
    df = pd.read_sql(sql_tot, conn)
    tot = dict(zip(df['iprod'].astype(str), df['qty'].astype(float)))
    del df
    gc.collect()

    sql_store = f"""
        SELECT blh.sotowhs AS whs, bld.iprod,
               SUM(bld.soqty) AS qty,
               SUM(bld.solineamt) AS amt
        FROM `{bld_table}` bld
        JOIN `{blh_table}` blh ON blh.sono = bld.sono
        WHERE bld.solinetype NOT IN ('C', 'R')
          {year_filter}
          AND blh.sotowhs REGEXP '^[0-9]+$'
        GROUP BY blh.sotowhs, bld.iprod
        HAVING qty > 0
    """
    df2 = pd.read_sql(sql_store, conn)
    store = {}
    for whs, ip, q, a in zip(df2['whs'].astype(str), df2['iprod'].astype(str),
                              df2['qty'].astype(float), df2['amt'].astype(float)):
        try:
            n = int(whs)
            if 1 <= n <= 500:
                store[(f'{n:03d}', ip)] = (q, a)
        except ValueError:
            pass
    del df2
    gc.collect()
    return tot, store


# ── STEP 2: Name lookup (dim_product + dim_item_barcode bridge) ──────────────
def query_name_map(conn, parcode_set):
    """Lookup product name/brand/group from dim_product.
    iprod in bld_acc may equal dim_product.iprod directly,
    or be a barcode that needs bridging via dim_item_barcode. Try both.
    (Param still called parcode_set for backward-compat with caller)."""
    if not parcode_set:
        return {}
    pl = list(parcode_set)
    BATCH = 2000
    result = {}
    cur = conn.cursor(dictionary=True)

    # 1) Direct match in dim_product
    for i in range(0, len(pl), BATCH):
        batch = pl[i:i+BATCH]
        ph = ','.join(['%s'] * len(batch))
        cur.execute(f"""
            SELECT iprod, idesc AS name, brndesc AS brand,
                   igrdesc AS grp, itydesc AS type_desc, ipunit3
            FROM dim_product
            WHERE iprod IN ({ph})
        """, batch)
        for r in cur.fetchall():
            result[r['iprod']] = {
                'iprod':   r['iprod'],
                'name':    r['name']      or '',
                'brand':   r['brand']     or '',
                'group':   r['grp']       or 'ไม่ระบุ',
                'type':    r['type_desc'] or '',
                'ipunit3': float(r['ipunit3'] or 0),
            }

    # 2) Barcode bridge for the rest
    missing = [p for p in pl if p not in result]
    for i in range(0, len(missing), BATCH):
        batch = missing[i:i+BATCH]
        ph = ','.join(['%s'] * len(batch))
        cur.execute(f"""
            SELECT dib.barcode AS parcode, dp.iprod, dp.idesc AS name,
                   dp.brndesc AS brand, dp.igrdesc AS grp,
                   dp.itydesc AS type_desc, dp.ipunit3
            FROM dim_item_barcode dib
            JOIN dim_product dp ON dp.iprod = dib.parcode
            WHERE dib.barcode IN ({ph})
              AND dib.baractive = 'Y'
        """, batch)
        for r in cur.fetchall():
            result[r['parcode']] = {
                'iprod':   r['iprod'],
                'name':    r['name']      or '',
                'brand':   r['brand']     or '',
                'group':   r['grp']       or 'ไม่ระบุ',
                'type':    r['type_desc'] or '',
                'ipunit3': float(r['ipunit3'] or 0),
            }
    cur.close()
    return result


# ── STEP 2b: Store info from dim_branch ──────────────────────────────────────
def query_branch_info(conn):
    """Returns {whs: {name, dm, rm}} from data-lake.dim_branch.
    Defensive — handles column-name variants via SHOW COLUMNS."""
    cur = conn.cursor(dictionary=True)
    cur.execute("SHOW COLUMNS FROM dim_branch")
    cols = {r['Field'].lower(): r['Field'] for r in cur.fetchall()}
    pick = lambda *names: next((cols[n] for n in names if n in cols), None)
    c_whs  = pick('code','branch_code','store_code','whs','warehouse','warehouse_code','whscode','whsno')
    c_name = pick('name','warehouse_name','whsname','branch_name','store_name','desc')
    c_dm   = pick('dm','dm_code','dm_name','district_manager','dmname')
    c_rm   = pick('rm','rm_code','rm_name','regional_manager','rmname','region')
    if not c_whs:
        cur.close(); return {}
    sels = [f"`{c_whs}` AS whs"]
    if c_name: sels.append(f"`{c_name}` AS name")
    if c_dm:   sels.append(f"`{c_dm}` AS dm")
    if c_rm:   sels.append(f"`{c_rm}` AS rm")
    cur.execute(f"SELECT {', '.join(sels)} FROM dim_branch")
    out = {}
    for r in cur.fetchall():
        try:
            n = int(str(r['whs']).strip())
            if 1 <= n <= 500:
                out[f'{n:03d}'] = {
                    'name': (r.get('name') or '').strip() if c_name else '',
                    'dm':   (r.get('dm')   or '').strip() if c_dm   else '',
                    'rm':   (r.get('rm')   or '').strip() if c_rm   else '',
                }
        except (ValueError, AttributeError):
            pass
    cur.close()
    return out


# ── STEP 3: Compute status + lost_score ──────────────────────────────────────
def classify(qty_by_year):
    """Returns (status, last_year, years_gone, lost_score)."""
    active = [y for y in YEARS if qty_by_year[y] > 0]
    if not active:
        return None, None, None, 0
    last_year = max(active)
    years_gone = CURRENT_YEAR - last_year
    max_qty = max(qty_by_year.values())

    # User's rule: LOST = no 2025 AND no 2026 sales
    if qty_by_year[CURRENT_YEAR] > 0:
        status = 'ACTIVE'
        lost_score = 0
    elif qty_by_year[CURRENT_YEAR - 1] > 0:
        status = 'STALE'
        lost_score = max_qty  # potential 1-year loss
    else:
        status = 'LOST'
        # Recent biggest sellers gone → highest score
        lost_score = years_gone * max_qty

    return status, last_year, years_gone, round(lost_score)


# ── MAIN ─────────────────────────────────────────────────────────────────────
def main():
    cfg = _load_cfg()
    if not cfg:
        print('ERROR: db_config.json not found'); return
    conn = _conn(cfg)
    print('Connected to data-lake @ ' + cfg['host'])
    print('=' * 60)
    print(f'  Lost Product Builder — years {YEARS[0]}..{YEARS[-1]}')
    print('=' * 60)

    # Check for --full-refresh flag or missing cache
    FULL_REFRESH = '--full-refresh' in sys.argv
    qty_cache_path = os.path.join(FOLDER, 'cache', 'lost_qty_2021_2025.parquet')
    store_cache_path = os.path.join(FOLDER, 'cache', 'lost_store_2021_2025.parquet')
    
    if FULL_REFRESH or not os.path.exists(qty_cache_path) or not os.path.exists(store_cache_path):
        print("Historical cache missing or --full-refresh requested. Building cache...")
        import subprocess
        script_path = os.path.join(FOLDER, 'scripts', 'build_lost_cache_2021_2024.py')
        subprocess.run([sys.executable, script_path], check=True)

    # Load from cache (2021-2025)
    year_qty = {}                 # {year: {iprod: qty}}
    store_breakdown = {}          # {whs: {iprod: [q21..q26, amt]}}
    yidx = {y: i for i, y in enumerate(YEARS)}
    
    print("Loading 2021-2025 historical cache...")
    df_qty_cache = pd.read_parquet(qty_cache_path)
    df_store_cache = pd.read_parquet(store_cache_path)
    
    import gc
    
    for yr in [2021, 2022, 2023, 2024, 2025]:
        sub_qty = df_qty_cache[df_qty_cache['year'] == yr]
        year_qty[yr] = dict(zip(sub_qty['iprod'].astype(str), sub_qty['qty'].astype(float)))
        
        idx = yidx[yr]
        sub_store = df_store_cache[df_store_cache['year'] == yr]
        for whs, ip, q, a in zip(sub_store['whs'].astype(str), sub_store['iprod'].astype(str),
                                  sub_store['qty'].astype(float), sub_store['amt'].astype(float)):
            arr = store_breakdown.setdefault(whs, {}).setdefault(ip, [0]*(len(YEARS) + 1))
            arr[idx] = round(q)
            arr[-1] += a
        print(f"  [{yr}] Loaded from cache: {len(year_qty[yr]):,} iprods | {len(sub_store):,} store rows")

    # Clear DataFrame RAM immediately
    del df_qty_cache, df_store_cache
    gc.collect()

    # Query active years dynamically (only CURRENT_YEAR)
    bld_cur, blh_cur = CURRENT_TABLES
    for year in [CURRENT_YEAR]:
        print(f'[{year}] JOIN {bld_cur} + {blh_cur} (sodate range query) ...')
        tot, store = query_year(conn, bld_cur, blh_cur, where_year=year)
        year_qty[year] = tot
        
        idx = yidx[year]
        for (whs, ip), val in store.items():
            if isinstance(val, tuple):
                q, a = val
            else:
                q, a = val, 0
            arr = store_breakdown.setdefault(whs, {}).setdefault(ip, [0]*(len(YEARS) + 1))
            arr[idx] = round(q)
            arr[-1] += a
        print(f'  {len(tot):,} iprods | {len(store):,} (whs,iprod) | qty={sum(tot.values()):,.0f}')

    all_parcodes = set()
    for yq in year_qty.values():
        all_parcodes.update(yq.keys())
    print(f'\nTotal unique parcodes across all years: {len(all_parcodes):,}')

    n_pairs = sum(len(p) for p in store_breakdown.values())
    print(f'  {len(store_breakdown)} stores, {n_pairs:,} (whs,iprod) pairs (pre-prune)')

    # ── Shrink: prune low-volume + low-value pairs + drop trailing zeros
    # Keep pair only if qty >= MIN_QTY OR amt >= MIN_AMT (catch volume movers AND value items)
    # Drop trailing zero years from each array (dashboard reads arr[i]||0)
    MIN_QTY = 15      # min total qty across 6 years
    MIN_AMT = 3000    # min total baht across 6 years
    removed = 0
    for whs in list(store_breakdown.keys()):
        for ip in list(store_breakdown[whs].keys()):
            arr = store_breakdown[whs][ip]
            total_qty = sum(arr[:len(YEARS)])
            total_amt = arr[-1]
            # Drop if BOTH below threshold (OR keep logic = NOT(qty<MIN AND amt<MIN))
            if total_qty < MIN_QTY and total_amt < MIN_AMT:
                del store_breakdown[whs][ip]
                removed += 1
            else:
                arr.pop()  # Remove total_amt element
                while len(arr) > 1 and arr[-1] == 0:
                    arr.pop()
        if not store_breakdown[whs]:
            del store_breakdown[whs]
    n_after = sum(len(p) for p in store_breakdown.values())
    print(f'  pruned {removed:,} pairs (<{MIN_QTY} qty AND <฿{MIN_AMT:,} amt) + trailing zeros')
    print(f'  final: {len(store_breakdown)} stores, {n_after:,} pairs')

    print('Querying dim_branch ...')
    branch_info = query_branch_info(conn)
    print(f'  {len(branch_info)} stores with branch metadata')

    # Name lookup
    print('Resolving names from dim_product ...')
    name_map = query_name_map(conn, all_parcodes)
    print(f'  Names resolved: {len(name_map):,}/{len(all_parcodes):,}')
    conn.close()

    # Build product list
    products = []
    for parcode in all_parcodes:
        qty_by_year = {y: round(float(year_qty[y].get(parcode, 0))) for y in YEARS}
        status, last_year, years_gone, lost_score = classify(qty_by_year)
        if status is None:
            continue
        info = name_map.get(parcode, {})
        active_years = [y for y in YEARS if qty_by_year[y] > 0]
        first_year = min(active_years)
        total_qty = sum(qty_by_year.values())
        max_qty = max(qty_by_year.values())

        products.append({
            'parcode':     parcode,
            'iprod':       info.get('iprod', parcode),
            'name':        info.get('name', '')[:50],
            'brand':       info.get('brand', '')[:25],
            'group':       info.get('group', 'ไม่ระบุ')[:30],
            'type':        info.get('type', '')[:25],
            'ipunit3':     round(info.get('ipunit3', 0)),
            'q2021':       qty_by_year[2021],
            'q2022':       qty_by_year[2022],
            'q2023':       qty_by_year[2023],
            'q2024':       qty_by_year[2024],
            'q2025':       qty_by_year[2025],
            'q2026':       qty_by_year[2026],
            'first_year':  first_year,
            'last_year':   last_year,
            'years_active': len(active_years),
            'years_gone':  years_gone,
            'total_qty':   total_qty,
            'max_qty':     max_qty,
            'status':      status,
            'lost_score':  lost_score,
        })

    # Sort by lost_score desc (biggest losses first) then by max_qty
    products.sort(key=lambda p: (-p['lost_score'], -p['max_qty']))

    n_active = sum(1 for p in products if p['status'] == 'ACTIVE')
    n_stale  = sum(1 for p in products if p['status'] == 'STALE')
    n_lost   = sum(1 for p in products if p['status'] == 'LOST')
    qty_lost_last_year = sum(p['max_qty'] for p in products if p['status'] == 'LOST')

    # ── Compact encoding (schema v2) — ADR [2026-06-11] ─────────────────────
    # Global code table: every barcode/iprod string stored ONCE in `codes`,
    # referenced by int index everywhere (products + store_breakdown keys).
    # Products emitted as array-of-arrays + single `products_header` row.
    # BREAKING vs v1 — decoded one-time by decodeData() in index.html.
    code_set = set()
    for p in products:
        code_set.add(p['parcode'])
        code_set.add(p['iprod'])
    for _prods in store_breakdown.values():
        code_set.update(_prods.keys())
    codes = sorted(code_set)
    cidx = {c: i for i, c in enumerate(codes)}
    print(f'  codes table: {len(codes):,} unique barcodes/iprods')

    STATUS_CODES = ['ACTIVE', 'STALE', 'LOST']
    PRODUCTS_HEADER = [
        'parcode', 'iprod', 'name', 'brand', 'group', 'type', 'ipunit3',
        'q2021', 'q2022', 'q2023', 'q2024', 'q2025', 'q2026',
        'first_year', 'last_year', 'years_active', 'years_gone',
        'total_qty', 'max_qty', 'status', 'lost_score',
    ]
    prod_rows = []
    for p in products:
        row = [cidx[p['parcode']], cidx[p['iprod']]]
        row += [p[k] for k in PRODUCTS_HEADER[2:19]]   # name .. max_qty
        row += [STATUS_CODES.index(p['status']), p['lost_score']]
        prod_rows.append(row)

    sb_compact = {
        whs: {str(cidx[ip]): arr for ip, arr in _prods.items()}
        for whs, _prods in store_breakdown.items()
    }

    output = {
        '_meta': {
            'schema':       2,
            'built_by':     'claude-fable-5',
            'status_codes': STATUS_CODES,
        },
        'generated':       (date.today() - timedelta(days=1)).isoformat(),  # data lake = today-1
        'years':           YEARS,
        'current_year':    CURRENT_YEAR,
        'summary': {
            'total_products': len(products),
            'active':         n_active,
            'stale':          n_stale,
            'lost':           n_lost,
            'qty_lost_peak':  qty_lost_last_year,
        },
        'codes':           codes,
        'products_header': PRODUCTS_HEADER,
        'products':        prod_rows,
        'store_breakdown': sb_compact,
        'store_info':      branch_info,
    }

    with open(OUT_JSON, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, separators=(',', ':'))

    sz = os.path.getsize(OUT_JSON) // 1024
    print(f'\n[OUT] Saved: {sz} KB | {len(products):,} products')
    print(f'  ACTIVE: {n_active:,}  STALE: {n_stale:,}  LOST: {n_lost:,}')
    print(f'  Peak historical qty of LOST products: {qty_lost_last_year:,}')
    print(f'\nTop 10 LOST by impact:')
    for p in [x for x in products if x['status']=='LOST'][:10]:
        print(f'  {p["parcode"]:15} last={p["last_year"]} max_qty={p["max_qty"]:>6,} {p["name"][:40]}')


if __name__ == '__main__':
    main()
