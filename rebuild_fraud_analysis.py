#!/usr/bin/env python3
"""
rebuild_fraud_analysis.py  ── MySQL-native edition
====================================================
Primary data source: MySQL data-lake
  fact_returns JOIN dim_branch + dim_item_barcode + dim_product  (one query)
  fact_sales  (MTD sales per store for risk scoring)

Fallback: local .txt / .sql dump files (offline mode)

Usage:
    py rebuild_fraud_analysis.py             # rebuild + push to GitHub
    py rebuild_fraud_analysis.py --no-push   # rebuild only (no push)
"""

import os, json, sys
import pandas as pd
from datetime import datetime, date

# ── PATHS ─────────────────────────────────────────────────────────────────────
FOLDER = os.path.dirname(os.path.abspath(__file__))
PUSH   = '--no-push' not in sys.argv

# Primary source: MySQL (MYPOS2018_CENTER + data-lake)
# fact_returns, dim_branch, dim_item_barcode, dim_product, fact_sales, xun → all from MySQL
# Local fallback files (offline mode only — not required)
RETURNALL    = os.path.join(FOLDER, 'returnall.txt')
USERNAME     = os.path.join(FOLDER, 'username.txt')   # fallback if xun query fails
BRANCH_SQL   = os.path.join(FOLDER, 'data-lake_dim_branch.sql')
TARGET       = os.path.join(FOLDER, 'target.txt')
BARCODE_SQL  = os.path.join(FOLDER, 'data-lake_dim_item_barcode.sql')
PRODUCT_SQL  = os.path.join(FOLDER, 'data-lake_dim_product.sql')

OUT_JSON       = os.path.join(FOLDER, 'fraud_data.json')
DB_CONFIG_FILE = os.path.join(FOLDER, 'db_config.json')

# ── USERNAME MAP (no dim_user in MySQL — keep file-based) ─────────────────────
def load_users():
    """Load username → fullname map from MYPOS2018_CENTER.xun (MySQL).
    Falls back to local username.txt if MySQL is unavailable."""
    cfg = _load_db_config()
    if cfg:
        try:
            import mysql.connector
            conn = mysql.connector.connect(
                host=cfg['host'], port=cfg.get('port', 3306),
                user=cfg['user'], password=cfg['password'],
                database='MYPOS2018_CENTER', connection_timeout=30,
                charset='utf8mb4'
            )
            cursor = conn.cursor(dictionary=True)
            cursor.execute("SELECT uname, ufname FROM xun WHERE uname IS NOT NULL")
            rows = cursor.fetchall()
            cursor.close(); conn.close()
            umap = {str(r['uname']).strip(): str(r['ufname'] or '').strip() for r in rows if r['uname']}
            print(f'      Loaded {len(umap):,} users from MYPOS2018_CENTER.xun')
            return umap
        except Exception as e:
            print(f'      WARNING: could not load from xun table: {e}')
            print(f'      Falling back to username.txt ...')
    # Fallback: local file
    if not os.path.exists(USERNAME):
        return {}
    df = pd.read_csv(USERNAME, sep='\t', dtype=str, on_bad_lines='skip')
    return dict(zip(df['uname'].str.strip(), df['ufname'].str.strip()))

# ── MYSQL HELPERS ─────────────────────────────────────────────────────────────
def _load_db_config():
    if not os.path.exists(DB_CONFIG_FILE):
        return None
    with open(DB_CONFIG_FILE, encoding='utf-8') as f:
        return json.load(f)

def _mysql_conn(cfg):
    import mysql.connector
    return mysql.connector.connect(
        host=cfg['host'], port=cfg.get('port', 3306),
        user=cfg['user'], password=cfg['password'],
        database=cfg['database'], connection_timeout=30,
        charset='utf8mb4'
    )

def _query_returns_full(cfg, months_back=3):
    """
    Single JOIN: fact_returns + dim_branch + dim_item_barcode + dim_product.
    Returns enriched DataFrame — store_name, dm, rm, parcode, idesc pre-filled.
    Primary amount column: line_amount_inc_vat (aliased to 'amount').
    """
    from dateutil.relativedelta import relativedelta
    start = (date.today().replace(day=1)
             - relativedelta(months=months_back - 1)).strftime('%Y-%m-01')
    sql = f"""
        SELECT
            fr.rtno,
            fr.rtsono,
            fr.rtserlno,
            fr.iprod,
            COALESCE(dib.parcode, fr.iprod)  AS parcode,
            COALESCE(dp.idesc,    '')         AS idesc,
            fr.return_date,
            fr.cstcode,
            fr.rtstatus,
            fr.warehouse_code,
            LPAD(fr.warehouse_code, 3, '0')  AS whs,
            fr.return_qty,
            fr.unit_price,
            fr.line_amount_inc_vat           AS amount,
            fr.allocated_net_amount,
            fr.rtuname,
            fr.rttime,
            fr.rtrcode,
            fr.rtrdesc,
            COALESCE(db.name,      '?')      AS store_name,
            COALESCE(db.dm,        '?')      AS dm,
            COALESCE(db.rm,        '?')      AS rm,
            COALESCE(db.prvn_name, '')       AS prvn_name
        FROM fact_returns fr
        LEFT JOIN dim_branch db
               ON LPAD(fr.warehouse_code, 3, '0') = db.code
        LEFT JOIN dim_item_barcode dib
               ON fr.iprod = dib.barcode AND dib.baractive = 'Y'
        LEFT JOIN dim_product dp
               ON COALESCE(dib.parcode, fr.iprod) = dp.iprod
        WHERE fr.rtstatus = 'U'
          AND fr.return_date >= '{start}'
          AND fr.warehouse_code NOT IN ('901', '999')
    """
    conn = _mysql_conn(cfg)
    df = pd.read_sql(sql, conn)
    conn.close()
    bills = df['rtsono'].nunique()
    print(f'  MySQL returns: {len(df):,} rows | {bills:,} bills | from {start}')
    return df

def _query_whsdd_sales_cost(cfg, year_month):
    """Fallback: MTD sales + cost from MYPOS2018_CENTER.whsdd (used when fact_sales unavailable).
    Returns (sales_map, cost_map) where each is {whs: float}."""
    yr, mo = year_month.split('-')
    conn = _mysql_conn(cfg)
    cursor = conn.cursor(dictionary=True)
    cursor.execute("""
        SELECT LPAD(whsddno, 3, '0') AS whs,
               SUM(whsddpnetamt)      AS sales_mtd,
               SUM(whsddpnetcost)     AS cost_mtd
        FROM MYPOS2018_CENTER.whsdd
        WHERE whsddyyyy = %s AND whsddmm = %s
          AND whsddno NOT IN ('901', '999')
        GROUP BY whsddno
    """, (int(yr), int(mo)))
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    sales_map = {r['whs']: float(r['sales_mtd'] or 0) for r in rows}
    cost_map  = {r['whs']: float(r['cost_mtd']  or 0) for r in rows}
    total_s = sum(sales_map.values())
    total_c = sum(cost_map.values())
    avg_gp  = round((total_s - total_c) / total_s * 100, 2) if total_s else 0
    print(f'  whsdd fallback: {len(sales_map):,} stores | '
          f'฿{total_s:,.0f} | avg GP%={avg_gp:.1f}%')
    return sales_map, cost_map

def _query_sales_mtd(cfg):
    """Latest-available month net sales + cost per store from fact_sales.
    Auto-detects the latest month with data (handles month boundaries correctly).
    Returns (sales_map, cost_map) where each is {whs: float}."""
    # Auto-detect latest month in fact_sales (avoids querying June when May data is latest)
    conn = _mysql_conn(cfg)
    cur = conn.cursor()
    cur.execute("""
        SELECT MAX(DATE_FORMAT(sodate, '%Y-%m-01'))
        FROM fact_sales
        WHERE sotowhs REGEXP '^[0-9]+$'
          AND CAST(sotowhs AS UNSIGNED) BETWEEN 1 AND 500
          AND solinetype NOT IN ('C','R')
    """)
    row = cur.fetchone()
    cur.close()
    latest_month_start = row[0] if row and row[0] else None

    if not latest_month_start:
        conn.close()
        return {}, {}

    sql = """
        SELECT LPAD(sotowhs, 3, '0') AS whs,
               SUM(net_sales_amt)    AS sales_mtd,
               SUM(total_cost)       AS cost_mtd
        FROM fact_sales
        WHERE sodate >= %s
          AND YEAR(sodate) = YEAR(%s) AND MONTH(sodate) = MONTH(%s)
          AND solinetype NOT IN ('C','R')
          AND sotowhs REGEXP '^[0-9]+$'
          AND CAST(sotowhs AS UNSIGNED) BETWEEN 1 AND 500
        GROUP BY sotowhs
    """
    df = pd.read_sql(sql, conn, params=(latest_month_start, latest_month_start, latest_month_start))
    conn.close()
    df['sales_mtd'] = pd.to_numeric(df['sales_mtd'], errors='coerce').fillna(0)
    df['cost_mtd']  = pd.to_numeric(df['cost_mtd'],  errors='coerce').fillna(0)
    total_s = df['sales_mtd'].sum()
    total_c = df['cost_mtd'].sum()
    avg_gp  = round((total_s - total_c) / total_s * 100, 2) if total_s else 0
    print(f'  MySQL sales MTD: {len(df):,} stores | '
          f'฿{total_s:,.0f} | avg GP%={avg_gp:.1f}%')
    sales_map = df.set_index('whs')['sales_mtd'].to_dict()
    cost_map  = df.set_index('whs')['cost_mtd'].to_dict()
    return sales_map, cost_map

# ── LEGACY FALLBACK PARSERS ────────────────────────────────────────────────────
def _parse_branch_row(data, start):
    i = start; n = len(data)
    if i >= n or data[i] != '(':
        return None
    i += 1; cols = []
    while i < n:
        if data[i] == ')':
            i += 1; break
        if data[i] == "'":
            i += 1; val = []
            while i < n:
                c = data[i]
                if c == '\\' and i + 1 < n: val.append(data[i+1]); i += 2
                elif c == "'": i += 1; break
                else: val.append(c); i += 1
            cols.append(''.join(val))
        elif data[i] in (',', ' '): i += 1
        elif data[i:i+4] == 'NULL': cols.append(''); i += 4
        else:
            j = i
            while i < n and data[i] not in (',', ')'): i += 1
            cols.append(data[j:i])
        if len(cols) == 6:
            while i < n and data[i] != ')': i += 1
            i += 1; break
    if len(cols) >= 6:
        return cols[0], cols[1], cols[3], cols[5], i
    return None

def load_branches():
    if not os.path.exists(BRANCH_SQL): return {}
    with open(BRANCH_SQL, encoding='utf-8', errors='replace') as f: sql = f.read()
    prefix = "INSERT INTO `dim_branch` VALUES "
    branches = {}
    for line in sql.splitlines():
        line = line.strip()
        if not line.startswith(prefix): continue
        data = line[len(prefix):]; i = 0
        while i < len(data):
            if data[i] != '(': i += 1; continue
            result = _parse_branch_row(data, i)
            if result is None: i += 1; continue
            whs, store_name, dm, rm, i = result
            branches[whs.zfill(3)] = {'store_name': store_name or '?', 'dm': dm or '?', 'rm': rm or '?'}
            if i < len(data) and data[i] == ',': i += 1
    return branches

def _parse_sql_two_cols(sql_text, table_name):
    result = {}; prefix = f"INSERT INTO `{table_name}` VALUES "
    for line in sql_text.splitlines():
        line = line.strip()
        if not line.startswith(prefix): continue
        data = line[len(prefix):]; i = 0; n = len(data)
        while i < n:
            if data[i] != '(': i += 1; continue
            i += 1; cols = []
            for _ in range(2):
                if i >= n or data[i] != "'": break
                i += 1; val = []
                while i < n:
                    c = data[i]
                    if c == '\\' and i+1 < n: val.append(data[i+1]); i += 2
                    elif c == "'": i += 1; break
                    else: val.append(c); i += 1
                cols.append(''.join(val))
                if i < n and data[i] == ',': i += 1
            if len(cols) == 2: result[cols[0]] = cols[1]
            while i < n and data[i] != ')': i += 1
            i += 1
    return result

def load_barcode_map():
    if not os.path.exists(BARCODE_SQL): return {}
    with open(BARCODE_SQL, encoding='utf-8', errors='replace') as f: sql = f.read()
    barmap = {}; prefix = "INSERT INTO `dim_item_barcode` VALUES "
    for line in sql.splitlines():
        line = line.strip()
        if not line.startswith(prefix): continue
        data = line[len(prefix):]; i = 0; n = len(data)
        while i < n:
            if data[i] != '(': i += 1; continue
            i += 1; cols = []
            for _ in range(2):
                if i >= n or data[i] != "'": break
                i += 1; val = []
                while i < n:
                    c = data[i]
                    if c == '\\' and i+1 < n: val.append(data[i+1]); i += 2
                    elif c == "'": i += 1; break
                    else: val.append(c); i += 1
                cols.append(''.join(val))
                if i < n and data[i] == ',': i += 1
            if len(cols) == 2: barmap[cols[1]] = cols[0]   # barcode → parcode
            while i < n and data[i] != ')': i += 1
            i += 1
    return barmap

def load_product_map():
    if not os.path.exists(PRODUCT_SQL): return {}
    with open(PRODUCT_SQL, encoding='utf-8', errors='replace') as f: sql = f.read()
    return _parse_sql_two_cols(sql, 'dim_product')

# ── MAIN DATA LOADER ───────────────────────────────────────────────────────────
def load_returns(umap, branches=None):
    """
    Load & enrich returns DataFrame.
    MySQL path: single JOIN query (fact_returns + dim tables).
    Fallback:   returnall.txt + local SQL dump files.
    'branches' param accepted for backward compat but ignored on MySQL path.
    """
    cfg = _load_db_config()
    df = None

    # ── MySQL path ────────────────────────────────────────────────────────────
    if cfg:
        try:
            df = _query_returns_full(cfg)
        except Exception as e:
            print(f'  MySQL error: {e}')
            df = None

    # ── Fallback: local files ─────────────────────────────────────────────────
    if df is None:
        print(f'  Falling back to local files ...')
        if branches is None:
            branches = load_branches()
        barmap  = load_barcode_map()
        prodmap = load_product_map()
        df = pd.read_csv(RETURNALL, sep='\t', dtype=str, on_bad_lines='skip')
        df = df[df['rtstatus'].str.strip() == 'U'].copy()
        df['whs']        = df['warehouse_code'].str.zfill(3)
        df['store_name'] = df['whs'].map(lambda x: branches.get(x, {}).get('store_name', '?'))
        df['dm']         = df['whs'].map(lambda x: branches.get(x, {}).get('dm', '?'))
        df['rm']         = df['whs'].map(lambda x: branches.get(x, {}).get('rm', '?'))
        df['prvn_name']  = ''
        df['parcode']    = df['iprod'].astype(str).map(lambda b: barmap.get(b, b))
        df['idesc']      = df['parcode'].map(lambda p: prodmap.get(p, ''))
        # Choose best amount column — prefer allocated_net_amount (net) per user spec
        for col in ['allocated_net_amount', 'line_amount_inc_vat']:
            if col in df.columns:
                df['amount'] = pd.to_numeric(df[col], errors='coerce')
                break

    # ── Common post-processing ────────────────────────────────────────────────
    for c in ['amount', 'return_qty', 'unit_price', 'allocated_net_amount']:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors='coerce')
    if 'amount' not in df.columns:
        df['amount'] = 0.0

    df['return_date'] = pd.to_datetime(df['return_date'], errors='coerce')
    df['month'] = df['return_date'].dt.strftime('%Y-%m')
    df['day']   = df['return_date'].dt.day

    if 'whs' not in df.columns:
        df['whs'] = df['warehouse_code'].astype(str).str.zfill(3)

    df['rtuname'] = df['rtuname'].fillna('').astype(str).str.strip()
    df['cstcode'] = df['cstcode'].fillna('').astype(str).str.strip()
    df['is_zero'] = df['cstcode'] == '0000'

    # rttime: timedelta64 (MySQL TIME) or string → convert to "HH:MM" string
    if 'rttime' in df.columns:
        if pd.api.types.is_timedelta64_dtype(df['rttime']):
            df['hour'] = df['rttime'].dt.components['hours']
            # Convert timedelta to "HH:MM" so JSON serialises as readable string
            def _td_to_hhmm(td):
                try:
                    if pd.isna(td): return ''
                    c = td.components
                    return f"{int(c.hours):02d}:{int(c.minutes):02d}"
                except Exception:
                    return ''
            df['rttime'] = df['rttime'].apply(_td_to_hhmm)
        else:
            df['hour'] = pd.to_numeric(df['rttime'].astype(str).str[:2], errors='coerce')
            # Normalise string times to "HH:MM"
            df['rttime'] = df['rttime'].astype(str).str[:5]
    else:
        df['hour'] = None

    df['fullname'] = df['rtuname'].map(umap).fillna('?')

    for col in ['store_name', 'dm', 'rm', 'idesc', 'parcode', 'rtrdesc', 'rtrcode', 'prvn_name']:
        if col in df.columns:
            df[col] = df[col].fillna('').astype(str)

    return df

# ── STORE RISK ─────────────────────────────────────────────────────────────────
def compute_store_risk(df, branches_or_cfg=None):
    """
    Compute risk score per store.
    Tries MySQL fact_sales for MTD sales; falls back to target.txt.
    'branches_or_cfg' can be a cfg dict (MySQL) or legacy branches dict.
    """
    cfg = None
    if isinstance(branches_or_cfg, dict) and 'host' in branches_or_cfg:
        cfg = branches_or_cfg
    else:
        cfg = _load_db_config()

    # ── Get MTD sales + cost ──────────────────────────────────────────────────
    max_mo    = df['month'].max()   # needed for fallback queries
    sales_map = {}
    cost_map  = {}

    # Primary: data-lake.fact_sales
    if cfg:
        try:
            sales_map, cost_map = _query_sales_mtd(cfg)
        except Exception as e:
            print(f'  MySQL fact_sales error: {e}')

    # Fallback 1: MYPOS2018_CENTER.whsdd
    if not sales_map and cfg:
        try:
            sales_map, cost_map = _query_whsdd_sales_cost(cfg, max_mo)
        except Exception as e:
            print(f'  MySQL whsdd fallback error: {e}')

    # Fallback 2: target.txt (offline mode only)
    if not sales_map and os.path.exists(TARGET):
        try:
            tgt = pd.read_csv(TARGET, sep='\t', dtype=str, on_bad_lines='skip')
            tgt['whsddpnetamt']  = pd.to_numeric(tgt.get('whsddpnetamt'),  errors='coerce')
            tgt['whsddpnetcost'] = pd.to_numeric(tgt.get('whsddpnetcost'), errors='coerce')
            yr, mo = max_mo.split('-')
            tgt_mo = tgt[(tgt['whsddyyyy'] == yr) & (tgt['whsddmm'] == str(int(mo)).zfill(2))].copy()
            tgt_mo['whs'] = tgt_mo['whsddno'].str.zfill(3)
            sales_map = tgt_mo.groupby('whs')['whsddpnetamt'].sum().to_dict()
            cost_map  = tgt_mo.groupby('whs')['whsddpnetcost'].sum().to_dict()
            print(f'  Store risk: fallback target.txt ({len(sales_map)} stores)')
        except Exception as e:
            print(f'  target.txt error: {e}')

    # ── Aggregations for latest month ─────────────────────────────────────────
    ret_mo  = df[df['month'] == max_mo]

    store_meta = df.groupby('whs').agg(
        store_name=('store_name', 'first'),
        dm=('dm', 'first'),
        rm=('rm', 'first'),
    ).reset_index().set_index('whs').to_dict(orient='index')

    ret_by  = ret_mo.groupby('whs')['amount'].sum()
    zero_by = ret_mo.groupby('whs')['is_zero'].mean() * 100
    cnt_by  = ret_mo.groupby('whs').size()

    # Valid store codes only: numeric, 1–500 (excludes 901, 999, and any non-store codes)
    def _valid_whs(code):
        try:
            n = int(code)
            return 1 <= n <= 500
        except Exception:
            return False

    all_whs = {w for w in (set(store_meta.keys()) | set(sales_map.keys()))
               if _valid_whs(w)}

    # If cost_map is missing or all-zero (fact_sales.total_cost may be unpopulated),
    # fall back to MYPOS2018_CENTER.whsdd.whsddpnetcost which is always populated
    if cfg and not any(v for v in cost_map.values() if v):
        try:
            _, cost_map = _query_whsdd_sales_cost(cfg, max_mo)
            print(f'  GP cost: fallback to MYPOS2018_CENTER.whsdd ({len(cost_map)} stores)')
        except Exception as e:
            print(f'  whsdd cost fallback error: {e}')

    # Chain-average GP% (used to compute per-store deviation)
    total_s_all = sum(float(sales_map.get(w, 0)) for w in all_whs)
    total_c_all = sum(float(cost_map.get(w, 0)) for w in all_whs)
    avg_gp_pct  = round((total_s_all - total_c_all) / total_s_all * 100, 2) if total_s_all else 0

    rows = []
    for whs in all_whs:
        meta = store_meta.get(whs, {'store_name': '?', 'dm': '?', 'rm': '?'})
        s    = float(sales_map.get(whs, 0))
        c    = float(cost_map.get(whs, 0))
        r    = float(ret_by.get(whs, 0))
        zp   = float(zero_by.get(whs, 0))
        cnt  = int(cnt_by.get(whs, 0))
        # Per-store GP% and deviation from chain average
        gp_pct = round((s - c) / s * 100, 2) if s > 0 else 0
        gp_dev = round(gp_pct - avg_gp_pct, 2) if s > 0 else 0
        if s == 0:
            score = 0; level = 'LOW'; rr = 0.0
        else:
            rr    = r / s * 100
            score = int(min(rr * 20, 50) + min(zp * 0.5, 30) + min(cnt * 0.5, 20))
            level = 'HIGH' if score >= 50 else 'MEDIUM' if score >= 25 else 'LOW'
            rr    = round(rr, 3)
        rows.append({
            'code': whs, 'name': meta['store_name'],
            'dm_name': meta['dm'], 'rm_name': meta['rm'],
            'sales_mtd': round(s, 0), 'ret_mtd': round(r, 0),
            'ret_rate': rr, 'zero_pct': round(zp, 1),
            'ret_cnt': cnt, 'score': score, 'level': level,
            'gp_pct': gp_pct, 'gp_dev': gp_dev,
        })
    rows.sort(key=lambda x: -x['score'])
    return rows

# ── AGGREGATION HELPERS ────────────────────────────────────────────────────────
def _rec(d):
    return json.loads(d.fillna('?').to_json(orient='records', force_ascii=False))

def _build_product_agg(sub, barmap=None, prodmap=None):
    """Aggregate by product. Uses pre-joined parcode/idesc (barmap/prodmap ignored)."""
    agg = sub.groupby('iprod').agg(
        return_qty=('return_qty', 'sum'),
        bills=('rtsono', 'nunique'),
        amount=('amount', 'sum'),
        parcode=('parcode', 'first'),
        idesc=('idesc', 'first'),
    ).reset_index()
    agg['barcode']    = agg['iprod'].astype(str)
    agg['return_qty'] = agg['return_qty'].fillna(0).round(0).astype(int)
    agg = agg[['barcode', 'parcode', 'idesc', 'return_qty', 'bills', 'amount']]
    agg = agg.sort_values('amount', ascending=False)  # no cap — export all products
    records = json.loads(agg.fillna('').to_json(orient='records', force_ascii=False))

    for rec in records:
        bc = rec['barcode']
        sub_bc = sub[sub['iprod'] == bc].copy()
        grp = sub_bc.groupby('rtsono').agg(
            cashier=('rtuname', 'first'), fullname=('fullname', 'first'),
            whs=('whs', 'first'), store_name=('store_name', 'first'),
            return_date=('return_date', 'first'), rttime=('rttime', 'first'),
            return_qty=('return_qty', 'sum'), amt=('amount', 'sum'),
        ).reset_index()
        grp['return_qty'] = grp['return_qty'].fillna(0).round(0).astype(int)
        grp['amt']        = grp['amt'].fillna(0).round(0)
        grp = grp.sort_values('amt', ascending=False).head(50)
        if 'return_date' in grp.columns and pd.api.types.is_datetime64_any_dtype(grp['return_date']):
            grp = grp.copy()
            grp['return_date'] = grp['return_date'].dt.strftime('%Y-%m-%d').where(grp['return_date'].notna(), '')
        rec['bills_list'] = json.loads(grp.fillna('').to_json(orient='records', force_ascii=False))
    return records

def _build_reason_agg(sub):
    """Dominant-reason aggregation — no double-counting per bill."""
    if 'rtrdesc' not in sub.columns:
        return []
    sub = sub.copy()
    sub['rtrdesc'] = sub['rtrdesc'].fillna('').str.strip()
    sub.loc[sub['rtrdesc'] == '', 'rtrdesc'] = 'ไม่ระบุเหตุผล'

    dominant = (sub.sort_values('amount', ascending=False)
                   .groupby('rtsono')['rtrdesc'].first()
                   .reset_index()
                   .rename(columns={'rtrdesc': 'dominant_reason'}))
    sub = sub.merge(dominant, on='rtsono', how='left')

    returns_agg = sub.groupby('rtrdesc').agg(
        returns=('rtno', 'count'), amount=('amount', 'sum'),
        stores=('whs', 'nunique'), cashiers=('rtuname', 'nunique'),
    ).reset_index()
    bills_agg = sub.groupby('dominant_reason')['rtsono'].nunique().reset_index()
    bills_agg.columns = ['rtrdesc', 'bills']
    agg = returns_agg.merge(bills_agg, on='rtrdesc', how='left')
    agg['bills'] = agg['bills'].fillna(0).astype(int)
    agg = agg.sort_values('amount', ascending=False)
    records = json.loads(agg.fillna('').to_json(orient='records', force_ascii=False))

    dom_map = dominant.set_index('rtsono')['dominant_reason'].to_dict()
    for rec in records:
        reason = rec['rtrdesc']
        sonos  = [s for s, dr in dom_map.items() if dr == reason]
        sub_r  = sub[sub['rtsono'].isin(sonos)].copy()
        grp = sub_r.groupby('rtsono').agg(
            cashier=('rtuname', 'first'), fullname=('fullname', 'first'),
            whs=('whs', 'first'), store_name=('store_name', 'first'),
            return_date=('return_date', 'first'), rttime=('rttime', 'first'),
            amt=('amount', 'sum'),
        ).reset_index()
        grp['amt'] = grp['amt'].fillna(0).round(0)
        grp = grp.sort_values('amt', ascending=False).head(100)
        if 'return_date' in grp.columns and pd.api.types.is_datetime64_any_dtype(grp['return_date']):
            grp = grp.copy()
            grp['return_date'] = grp['return_date'].dt.strftime('%Y-%m-%d').where(grp['return_date'].notna(), '')
        rec['bills_list'] = json.loads(grp.fillna('').to_json(orient='records', force_ascii=False))
    return records

def build_month(sub, barmap=None, prodmap=None):
    """Build all aggregations for one month (or ALL). barmap/prodmap ignored."""
    sub = sub.copy()

    # Repeat SO (bills with >1 line)
    so = sub.groupby('rtsono').agg(
        lines=('rtno', 'count'), amount=('amount', 'sum'),
        cashier=('rtuname', 'first'), fname=('fullname', 'first'),
        store=('whs', 'first'), store_name=('store_name', 'first'),
        dm=('dm', 'first'), rm=('rm', 'first'),
        zero=('is_zero', 'sum'), date=('return_date', 'first'),
        time=('rttime', 'first'),
    ).reset_index()
    so = so[so['lines'] > 1].sort_values('amount', ascending=False)

    # Product detail per rtsono
    detail_map = (
        sub[sub['rtsono'].isin(so['rtsono'])]
        .groupby(['rtsono', 'iprod'])
        .agg(amount=('amount', 'sum'), return_qty=('return_qty', 'sum'),
             parcode=('parcode', 'first'), idesc=('idesc', 'first'))
        .reset_index()
        .sort_values(['rtsono', 'amount'], ascending=[True, False])
    )
    detail_dict = {}
    for sono, grp in detail_map.groupby('rtsono'):
        items = []
        for _, row in grp.iterrows():
            items.append({
                'barcode': str(row['iprod']),
                'parcode': str(row['parcode']),
                'idesc':   str(row['idesc']),
                'qty':     int(row['return_qty']) if not pd.isna(row['return_qty']) else 0,
                'amt':     round(float(row['amount']), 2),
            })
        detail_dict[sono] = items
    # Convert date (datetime64 → 'dd-mm-yyyy') before JSON serialization
    if 'date' in so.columns and pd.api.types.is_datetime64_any_dtype(so['date']):
        so = so.copy()
        so['date'] = so['date'].dt.strftime('%d-%m-%Y')
    so_list = json.loads(so.fillna('?').to_json(orient='records', date_format='iso', force_ascii=False))
    for r in so_list:
        r['detail'] = detail_dict.get(r.get('rtsono'), [])

    # rtuname
    rtu = sub.groupby(['rtuname', 'fullname', 'whs', 'store_name', 'dm', 'rm']).agg(
        returns=('rtno', 'count'), amount=('amount', 'sum'),
        zero=('is_zero', 'sum'), uso=('rtsono', 'nunique'),
    ).reset_index()
    rtu['rep']   = rtu['returns'] - rtu['uso']
    rtu['zp']    = (rtu['zero'] / rtu['returns'] * 100).round(1)
    mx_a = max(rtu['amount'].max(), 1); mx_r = max(rtu['rep'].max(), 1)
    rtu['score'] = ((rtu['amount']/mx_a*40) + (rtu['zp']/100*35) + (rtu['rep']/mx_r*25)).round(1)
    rtu = rtu.sort_values('amount', ascending=False)

    # Store
    st = sub.groupby(['whs', 'store_name', 'dm', 'rm']).agg(
        returns=('rtno', 'count'), amount=('amount', 'sum'),
        cashiers=('rtuname', 'nunique'), zero=('is_zero', 'sum'),
    ).reset_index()
    st['zp'] = (st['zero'] / st['returns'] * 100).round(1)
    st = st.sort_values('amount', ascending=False)

    # DM
    dm = sub.groupby(['dm', 'rm']).agg(
        returns=('rtsono', 'nunique'), amount=('amount', 'sum'),
        stores=('whs', 'nunique'), cashiers=('rtuname', 'nunique'),
        zero=('is_zero', 'sum'), row_cnt=('rtno', 'count'),
    ).reset_index()
    dm['zp'] = (dm['zero'] / dm['row_cnt'] * 100).round(1)
    dm = dm.drop(columns=['row_cnt']).sort_values('amount', ascending=False)

    # RM
    rm = sub.groupby('rm').agg(
        returns=('rtsono', 'nunique'), amount=('amount', 'sum'),
        stores=('whs', 'nunique'), cashiers=('rtuname', 'nunique'),
        zero=('is_zero', 'sum'), dms=('dm', 'nunique'),
        row_cnt=('rtno', 'count'),
    ).reset_index()
    rm['zp'] = (rm['zero'] / rm['row_cnt'] * 100).round(1)
    rm = rm.drop(columns=['row_cnt']).sort_values('amount', ascending=False)

    # Hour / Day
    hr = sub.groupby('hour').agg(returns=('rtno', 'count'), amount=('amount', 'sum')).reset_index()
    hr = hr[hr['hour'].notna()].copy(); hr['hour'] = hr['hour'].astype(int); hr = hr.sort_values('hour')
    dy = sub.groupby('day').agg(returns=('rtno', 'count'), amount=('amount', 'sum')).reset_index()
    dy['day'] = dy['day'].astype(int); dy = dy.sort_values('day')

    za = float(sub[sub['is_zero']]['amount'].sum())
    na = float(hr[hr['hour'].isin([22, 23])]['amount'].sum()) if len(hr) else 0.0

    return {
        'stats': {
            'n':          int(sub['rtsono'].nunique()),
            'total':      float(sub['allocated_net_amount'].sum() if 'allocated_net_amount' in sub.columns else sub['amount'].sum()),
            'n_rtu':      int(sub['rtuname'].nunique()),
            'n_store':    int(sub['whs'].nunique()),
            'n_zero':     int(sub['is_zero'].sum()),
            'zero_amt':   za,
            'n_so_dup':   int(len(so)),
            'so_dup_amt': float(so['amount'].sum()),
            'night_amt':  na,
        },
        'rtu':     _rec(rtu.head(600)),
        'store':   _rec(st.head(250)),
        'dm':      _rec(dm),
        'rm':      _rec(rm),
        'hour':    _rec(hr),
        'day':     _rec(dy),
        'so':      so_list[:500],
        'product': _build_product_agg(sub),
        'reason':  _build_reason_agg(sub),
    }

# ── PUSH TO GITHUB ─────────────────────────────────────────────────────────────
def push_github():
    import subprocess
    try:
        res = subprocess.run(
            ['git', '-C', FOLDER, 'status', '--porcelain', 'fraud_data.json'],
            capture_output=True, text=True)
        if not res.stdout.strip():
            print('  GitHub: no changes — skipped push'); return
        subprocess.run(['git', '-C', FOLDER, 'add', 'fraud_data.json'], check=True)
        today = datetime.now().strftime('%Y-%m-%d %H:%M')
        subprocess.run(['git', '-C', FOLDER, 'commit', '-m', f'fraud data update {today}'], check=True)
        subprocess.run(['git', '-C', FOLDER, 'push'], check=True)
        print('  GitHub: pushed OK')
    except Exception as e:
        print(f'  GitHub push failed: {e}')

# ── MAIN ───────────────────────────────────────────────────────────────────────
def main():
    print('=' * 60)
    print('  Fraud Analysis Rebuilder  (MySQL-native)')
    print('=' * 60)

    cfg = _load_db_config()

    print('[1/4] Loading user map ...')
    umap = load_users()
    print(f'      {len(umap):,} users')

    print('[2/4] Loading returns (MySQL JOIN) ...')
    df = load_returns(umap)
    months = sorted(df['month'].dropna().unique())
    # Exclude current partial month if we're within first 6 days
    from datetime import date as _date
    _today = _date.today()
    _cur_mo = _today.strftime('%Y-%m')
    if _today.day <= 6 and _cur_mo in months:
        months = [m for m in months if m != _cur_mo]
        print(f'      [skip] Excluded partial month {_cur_mo} (day {_today.day} <= 6)')
    print(f'      {len(df):,} rows | {df["rtsono"].nunique():,} bills | '
          f'months: {", ".join(months)}')

    print('[3/4] Computing store risk ...')
    sr  = compute_store_risk(df, cfg)
    h   = sum(1 for s in sr if s['level'] == 'HIGH')
    m   = sum(1 for s in sr if s['level'] == 'MEDIUM')
    l   = sum(1 for s in sr if s['level'] == 'LOW')
    print(f'      {len(sr)} stores  HIGH={h}  MEDIUM={m}  LOW={l}')

    print('[4/4] Building analysis data ...')
    out = {
        'gen':      datetime.now().strftime('%Y-%m-%d %H:%M'),
        'months':   months,
        'data':     {},
        'sr':       sr,
        'sr_count': {'H': h, 'M': m, 'L': l},
    }
    out['data']['ALL'] = build_month(df)
    for mo in months:
        sub = df[df['month'] == mo]
        out['data'][mo] = build_month(sub)
        print(f'      {mo}: {sub["rtsono"].nunique()