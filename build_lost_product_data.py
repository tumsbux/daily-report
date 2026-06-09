"""Builds lost_product_data.json — 6-year sales history per product (2021-2026).
Identifies LOST products (no 2025+2026 sales) and STALE (no 2026 sales).

Source: data-lake.bld_acc_*_lake (5 tables: 2021, 2022, 2023, 2024, current)
Output: lost_product_data.json with full year-by-year qty grid + status + lost_score.
"""
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
        year_filter = f"AND YEAR(blh.sodate) = {where_year}"
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
    df = pd.read_sql(sql_tot, conn)
    tot = dict(zip(df['iprod'].astype(str), df['qty'].astype(float)))

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

    # Per-year aggregation (chain + per-store)
    year_qty = {}                 # {year: {iprod: qty}}
    year_store_qty = {}           # {year: {(whs,iprod): qty}}
    for year, (bld, blh) in YEAR_TABLES.items():
        print(f'[{year}] JOIN {bld} + {blh} ...')
        tot, store = query_year(conn, bld, blh)
        year_qty[year] = tot
        year_store_qty[year] = store
        print(f'  {len(tot):,} iprods | {len(store):,} (whs,iprod) | qty={sum(tot.values()):,.0f}')

    bld_cur, blh_cur = CURRENT_TABLES
    for year in [2025, CURRENT_YEAR]:
        print(f'[{year}] JOIN {bld_cur} + {blh_cur} WHERE YEAR(sodate)={year} ...')
        tot, store = query_year(conn, bld_cur, blh_cur, where_year=year)
        year_qty[year] = tot
        year_store_qty[year] = store
        print(f'  {len(tot):,} iprods | {len(store):,} (whs,iprod) | qty={sum(tot.values()):,.0f}')

    all_parcodes = set()
    for yq in year_qty.values():
        all_parcodes.update(yq.keys())
    print(f'\nTotal unique parcodes across all years: {len(all_parcodes):,}')

    print('Building per-store breakdown ...')
    store_breakdown = {}      # {whs: {iprod: [q21..q26]}}
    store_amt_total = {}      # {(whs,iprod): total_amt across all 6 years}
    yidx = {y: i for i, y in enumerate(YEARS)}
    for year, sd in year_store_qty.items():
        idx = yidx[year]
        for (whs, ip), val in sd.items():
            # val is (qty, amt) tuple from updated query_year
            if isinstance(val, tuple):
                q, a = val
            else:
                q, a = val, 0
            arr = store_breakdown.setdefault(whs, {}).setdefault(ip, [0]*len(YEARS))
            arr[idx] = round(q)
            store_amt_total[(whs, ip)] = store_amt_total.get((whs, ip), 0) + a
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
            total_qty = sum(arr)
            total_amt = store_amt_total.get((whs, ip), 0)
            # Drop if BOTH below threshold (OR keep logic = NOT(qty<MIN AND amt<MIN))
            if total_qty < MIN_QTY and total_amt < MIN_AMT:
                del store_breakdown[whs][ip]
                removed += 1
            else:
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

    output = {
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
        'products':        products,
        'store_breakdown': store_breakdown,
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
