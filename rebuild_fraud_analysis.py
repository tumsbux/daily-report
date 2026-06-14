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

from dashboards.fraud_queries import (
    _mysql_conn, _load_sales_mtd_from_cache,
    _get_frozen_returns, _query_returns_full,
    _query_whsdd_sales_cost, _query_sales_mtd,
)
from dashboards.fraud_agg import _rec, _build_product_agg, _build_reason_agg, build_month


# ── PATHS ─────────────────────────────────────────────────────────────────────
FOLDER = os.path.dirname(os.path.abspath(__file__))
PUSH   = '--no-push' not in sys.argv
FULL_REFRESH = '--full-refresh' in sys.argv

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
            df = _query_returns_full(cfg, FOLDER, full_refresh=FULL_REFRESH)
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

    df['return_date'] = pd.to_datetime(df['return_date'], errors='coerce', format='mixed')
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

    # Try cache first (Phase IR-D optimization)
    cached_sales = _load_sales_mtd_from_cache(max_mo, FOLDER)
    if cached_sales:
        sales_map, cost_map = cached_sales

    # Primary: data-lake.fact_sales
    if not sales_map and cfg:
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
        print(f'      {mo}: {sub["rtsono"].nunique():,} bills | '
              f'{len(sub):,} rows | \u0e3f{sub["amount"].sum():,.0f}')

    with open(OUT_JSON, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False)
    sz = os.path.getsize(OUT_JSON) // 1024
    print(f'      fraud_data.json saved ({sz:,} KB)')

    if PUSH:
        push_github()

if __name__ == '__main__':
    main()
