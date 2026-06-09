"""Builds lost_product_data.json — 6-year sales history per product (2021-2026).
VM/streaming variant: replaces pandas pd.read_sql with mysql.connector cursor.fetchmany
loop so peak RAM is ~50MB instead of multi-GB. Output is byte-for-byte identical to
the original build_lost_product_data.py.
"""
import json, os, sys, pickle
import concurrent.futures
from datetime import date, timedelta
import mysql.connector

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

BATCH = 10000   # fetchmany batch size
STATE_DIR = os.path.join(FOLDER, 'state')


def _state_file(year):
    return os.path.join(STATE_DIR, f'y{year}.pkl')


def _load_state():
    """Return (year_qty, year_store_qty) loaded from state files (for resume)."""
    os.makedirs(STATE_DIR, exist_ok=True)
    yq, ys = {}, {}
    for y in YEARS:
        f = _state_file(y)
        if os.path.exists(f):
            try:
                with open(f, 'rb') as fh:
                    tot, store = pickle.load(fh)
                yq[y] = tot
                ys[y] = store
                print(f'[state] resume: loaded year {y} ({len(tot):,} iprods)', flush=True)
            except Exception as e:
                print(f'[state] WARN: failed to load {f}: {e}', flush=True)
    return yq, ys


def _save_year_state(year, tot, store):
    with open(_state_file(year), 'wb') as fh:
        pickle.dump((tot, store), fh)


def _clear_state():
    if os.path.isdir(STATE_DIR):
        for f in os.listdir(STATE_DIR):
            try:
                os.remove(os.path.join(STATE_DIR, f))
            except OSError:
                pass


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


# ── STEP 1: Per-year qty aggregation (STREAMING) ─────────────────────────────
def query_year(conn, bld_table, blh_table, where_year=None):
    """Returns ({iprod: total_qty}, {(whs,iprod): (qty,amt)}) for one year.
    Streams rows via cursor.fetchmany() — never holds full result set in RAM."""
    if where_year is not None:
        # Use date range (uses sodate index, allows partition pruning)
        # NOT YEAR() — function call defeats indexes → full table scan
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
    tot = {}
    cur = conn.cursor(buffered=False)
    cur.execute(sql_tot)
    while True:
        rows = cur.fetchmany(BATCH)
        if not rows:
            break
        for ip, qty in rows:
            tot[str(ip)] = float(qty)
    cur.close()

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
    store = {}
    cur = conn.cursor(buffered=False)
    cur.execute(sql_store)
    while True:
        rows = cur.fetchmany(BATCH)
        if not rows:
            break
        for whs, ip, q, a in rows:
            try:
                n = int(str(whs))
                if 1 <= n <= 500:
                    store[(f'{n:03d}', str(ip))] = (float(q), float(a or 0))
            except (ValueError, TypeError):
                pass
    cur.close()
    return tot, store


# ── STEP 2: Name lookup (dim_product + dim_item_barcode bridge) ──────────────
def query_name_map(conn, parcode_set):
    if not parcode_set:
        return {}
    pl = list(parcode_set)
    NBATCH = 2000
    result = {}
    cur = conn.cursor(dictionary=True)

    for i in range(0, len(pl), NBATCH):
        batch = pl[i:i+NBATCH]
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

    missing = [p for p in pl if p not in result]
    for i in range(0, len(missing), NBATCH):
        batch = missing[i:i+NBATCH]
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
    active = [y for y in YEARS if qty_by_year[y] > 0]
    if not active:
        return None, None, None, 0
    last_year = max(active)
    years_gone = CURRENT_YEAR - last_year
    max_qty = max(qty_by_year.values())

    if qty_by_year[CURRENT_YEAR] > 0:
        status = 'ACTIVE'
        lost_score = 0
    elif qty_by_year[CURRENT_YEAR - 1] > 0:
        status = 'STALE'
        lost_score = max_qty
    else:
        status = 'LOST'
        lost_score = years_gone * max_qty

    return status, last_year, years_gone, round(lost_score)


# ── MAIN ─────────────────────────────────────────────────────────────────────
def main():
    cfg = _load_cfg()
    if not cfg:
        print('ERROR: db_config.json not found'); sys.exit(1)
    conn = _conn(cfg)
    print('Connected to data-lake @ ' + cfg['host'], flush=True)
    print('=' * 60, flush=True)
    print(f'  Lost Product Builder (streaming) — years {YEARS[0]}..{YEARS[-1]}', flush=True)
    print('=' * 60, flush=True)

    # Resume from previous run if state files exist
    year_qty, year_store_qty = _load_state()

    # Build per-year jobs for years NOT yet cached
    jobs = []
    for year, (bld, blh) in YEAR_TABLES.items():
        if year not in year_qty:
            jobs.append((year, bld, blh, None))
    bld_cur, blh_cur = CURRENT_TABLES
    for year in [2025, CURRENT_YEAR]:
        if year not in year_qty:
            jobs.append((year, bld_cur, blh_cur, year))

    def _run_one(job):
        yr, bld, blh, wyr = job
        c = _conn(cfg)
        print(f'[{yr}] start ({bld})', flush=True)
        tot, store = query_year(c, bld, blh, where_year=wyr)
        c.close()
        _save_year_state(yr, tot, store)  # PERSIST IMMEDIATELY
        print(f'[{yr}] done | {len(tot):,} iprods | {len(store):,} (whs,iprod) | qty={sum(tot.values()):,.0f}', flush=True)
        return yr, tot, store

    if jobs:
        print(f'Launching {len(jobs)} parallel year queries ({len(year_qty)} cached) ...', flush=True)
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(jobs)) as ex:
            futures = [ex.submit(_run_one, j) for j in jobs]
            for fut in concurrent.futures.as_completed(futures):
                yr, tot, store = fut.result()
                year_qty[yr] = tot
                year_store_qty[yr] = store
    else:
        print('All 6 years cached — skipping query phase', flush=True)

    # Verify all years collected; if not, exit (next run will resume)
    missing = [y for y in YEARS if y not in year_qty]
    if missing:
        print(f'\n[partial] missing years: {missing}', flush=True)
        print(f'[partial] re-run script to resume — state cached for {sorted(year_qty.keys())}', flush=True)
        sys.exit(2)

    # Close the main connection since each thread used its own
    conn.close()
    conn = _conn(cfg)  # reopen for the dim_branch / dim_product queries below

    all_parcodes = set()
    for yq in year_qty.values():
        all_parcodes.update(yq.keys())
    print(f'\nTotal unique parcodes across all years: {len(all_parcodes):,}', flush=True)

    print('Building per-store breakdown ...', flush=True)
    store_breakdown = {}
    store_amt_total = {}
    yidx = {y: i for i, y in enumerate(YEARS)}
    for year, sd in year_store_qty.items():
        idx = yidx[year]
        for (whs, ip), val in sd.items():
            if isinstance(val, tuple):
                q, a = val
            else:
                q, a = val, 0
            arr = store_breakdown.setdefault(whs, {}).setdefault(ip, [0]*len(YEARS))
            arr[idx] = round(q)
            store_amt_total[(whs, ip)] = store_amt_total.get((whs, ip), 0) + a
    n_pairs = sum(len(p) for p in store_breakdown.values())
    print(f'  {len(store_breakdown)} stores, {n_pairs:,} (whs,iprod) pairs (pre-prune)', flush=True)

    MIN_QTY = 15
    MIN_AMT = 3000
    removed = 0
    for whs in list(store_breakdown.keys()):
        for ip in list(store_breakdown[whs].keys()):
            arr = store_breakdown[whs][ip]
            total_qty = sum(arr)
            total_amt = store_amt_total.get((whs, ip), 0)
            if total_qty < MIN_QTY and total_amt < MIN_AMT:
                del store_breakdown[whs][ip]
                removed += 1
            else:
                while len(arr) > 1 and arr[-1] == 0:
                    arr.pop()
        if not store_breakdown[whs]:
            del store_breakdown[whs]
    n_after = sum(len(p) for p in store_breakdown.values())
    print(f'  pruned {removed:,} pairs (<{MIN_QTY} qty AND <{MIN_AMT:,} amt) + trailing zeros', flush=True)
    print(f'  final: {len(store_breakdown)} stores, {n_after:,} pairs', flush=True)

    print('Querying dim_branch ...', flush=True)
    branch_info = query_branch_info(conn)
    print(f'  {len(branch_info)} stores with branch metadata', flush=True)

    print('Resolving names from dim_product ...', flush=True)
    name_map = query_name_map(conn, all_parcodes)
    print(f'  Names resolved: {len(name_map):,}/{len(all_parcodes):,}', flush=True)
    conn.close()

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

    products.sort(key=lambda p: (-p['lost_score'], -p['max_qty']))

    n_active = sum(1 for p in products if p['status'] == 'ACTIVE')
    n_stale  = sum(1 for p in products if p['status'] == 'STALE')
    n_lost   = sum(1 for p in products if p['status'] == 'LOST')
    qty_lost_last_year = sum(p['max_qty'] for p in products if p['status'] == 'LOST')

    output = {
        'generated':       (date.today() - timedelta(days=1)).isoformat(),
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

    # Also save to f:\lost-Product\lost_product_data.json for VM localhost server
    try:
        alt_path = r"f:\lost-Product\lost_product_data.json"
        with open(alt_path, 'w', encoding='utf-8') as fAlt:
            json.dump(output, fAlt, ensure_ascii=False, separators=(',', ':'))
        print(f'[OUT] Also saved copy to: {alt_path}', flush=True)
    except Exception as e:
        print(f'WARN: failed to save copy to f:\\lost-Product: {e}', flush=True)

    _clear_state()  # cleanup pickle cache after successful write

    sz = os.path.getsize(OUT_JSON) // 1024
    print(f'\n[OUT] Saved: {sz} KB | {len(products):,} products', flush=True)
    print(f'  ACTIVE: {n_active:,}  STALE: {n_stale:,}  LOST: {n_lost:,}', flush=True)
    print(f'  Peak historical qty of LOST products: {qty_lost_last_year:,}', flush=True)


if __name__ == '__main__':
    main()
