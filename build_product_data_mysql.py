#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_product_data_mysql.py — Product Analysis Data Builder (MySQL-native)
=========================================================================
Replaces the 7GB SQL file approach. Queries MySQL directly:
  fact_sales JOIN dim_product + dim_item_barcode

Outputs product_data.json for product_dashboard.html

Usage:
    py build_product_data_mysql.py             # build + push to GitHub
    py build_product_data_mysql.py --no-push   # build only
"""

import os, json, sys, calendar
import pandas as pd
from datetime import date
from collections import defaultdict

FOLDER         = os.path.dirname(os.path.abspath(__file__))
OUT_JSON       = os.path.join(FOLDER, 'product_data.json')
DB_CONFIG_FILE = os.path.join(FOLDER, 'db_config.json')
PUSH           = True  # overridden by argparse in main()
FULL_REFRESH   = False

from lib.safe_write import safe_write_parquet, safe_write_json
import pyarrow as pa
import pyarrow.parquet as pq
from datetime import datetime

RULE_HASH = "v2_sotowhs_1_500_solinetype_not_C_R"

def get_product_cache(cfg, year, month, days_elapsed, full_refresh=False):
    cache_dir = os.path.join(FOLDER, 'cache')
    os.makedirs(cache_dir, exist_ok=True)
    cache_path = os.path.join(cache_dir, f'product_mtd_{year}-{month:02d}.parquet')
    
    rebuild = full_refresh or not os.path.exists(cache_path)
    if not rebuild:
        try:
            meta = pq.read_metadata(cache_path)
            sch_meta = meta.schema.to_arrow_schema().metadata or {}
            c_v = sch_meta.get(b'v', b'').decode('utf-8')
            c_hash = sch_meta.get(b'rule_hash', b'').decode('utf-8')
            if c_v != '2' or c_hash != RULE_HASH:
                print(f"  Cache mismatch (v={c_v}, hash={c_hash}) -> auto full-refresh")
                rebuild = True
        except Exception as e:
            print(f"  Cache read error ({e}) -> auto full-refresh")
            rebuild = True
            
    schema = pa.schema([
        ('whs', pa.string()),
        ('iprod', pa.string()),
        ('day', pa.int16()),
        ('sales', pa.float64()),
        ('qty', pa.float64()),
        ('cost', pa.float64()),
    ])
    
    custom_metadata = {
        'v': '2',
        'built_by': 'antigravity-gemini-3-flash',
        'rule_hash': RULE_HASH,
        'timestamp': datetime.now().isoformat()
    }
    
    conn = _conn(cfg)
    try:
        if rebuild:
            print(f"  [CACHE] Full refresh for {year}-{month:02d} up to day {days_elapsed}...")
            start_date = f'{year}-{month:02d}-01'
            end_date = f'{year}-{month:02d}-{days_elapsed:02d}'
            sql = """
                SELECT LPAD(sotowhs, 3, '0') AS whs,
                       iprod,
                       DAY(sodate) AS day,
                       SUM(net_sales_amt) AS sales,
                       SUM(net_qty) AS qty,
                       SUM(COALESCE(total_cost, 0)) AS cost
                FROM fact_sales
                WHERE solinetype NOT IN ('C', 'R')
                  AND sotowhs REGEXP '^[0-9]+$'
                  AND CAST(sotowhs AS UNSIGNED) BETWEEN 1 AND 500
                  AND sodate BETWEEN %s AND %s
                GROUP BY sotowhs, iprod, DAY(sodate)
            """
            cur = conn.cursor(dictionary=True)
            cur.execute(sql, (start_date, end_date))
            rows = cur.fetchall()
            cur.close()
            df = pd.DataFrame(rows)
            if df.empty:
                df = pd.DataFrame(columns=['whs', 'iprod', 'day', 'sales', 'qty', 'cost'])
                df['day'] = df['day'].astype('int16')
                df['sales'] = df['sales'].astype('float64')
                df['qty'] = df['qty'].astype('float64')
                df['cost'] = df['cost'].astype('float64')
            else:
                df['whs'] = df['whs'].astype('string')
                df['iprod'] = df['iprod'].astype('string')
                df['day'] = df['day'].astype('int16')
                df['sales'] = df['sales'].astype('float64')
                df['qty'] = df['qty'].astype('float64')
                df['cost'] = df['cost'].astype('float64')
            
            safe_write_parquet(cache_path, df, schema, custom_metadata)
            return df
        else:
            start_day = max(1, days_elapsed - 6)
            print(f"  [CACHE] Incremental refresh for {year}-{month:02d} days {start_day}..{days_elapsed}...")
            start_date = f'{year}-{month:02d}-{start_day:02d}'
            end_date = f'{year}-{month:02d}-{days_elapsed:02d}'
            sql = """
                SELECT LPAD(sotowhs, 3, '0') AS whs,
                       iprod,
                       DAY(sodate) AS day,
                       SUM(net_sales_amt) AS sales,
                       SUM(net_qty) AS qty,
                       SUM(COALESCE(total_cost, 0)) AS cost
                FROM fact_sales
                WHERE solinetype NOT IN ('C', 'R')
                  AND sotowhs REGEXP '^[0-9]+$'
                  AND CAST(sotowhs AS UNSIGNED) BETWEEN 1 AND 500
                  AND sodate BETWEEN %s AND %s
                GROUP BY sotowhs, iprod, DAY(sodate)
            """
            cur = conn.cursor(dictionary=True)
            cur.execute(sql, (start_date, end_date))
            rows = cur.fetchall()
            cur.close()
            new_df = pd.DataFrame(rows)
            if not new_df.empty:
                new_df['whs'] = new_df['whs'].astype('string')
                new_df['iprod'] = new_df['iprod'].astype('string')
                new_df['day'] = new_df['day'].astype('int16')
                new_df['sales'] = new_df['sales'].astype('float64')
                new_df['qty'] = new_df['qty'].astype('float64')
                new_df['cost'] = new_df['cost'].astype('float64')
            else:
                new_df = pd.DataFrame(columns=['whs', 'iprod', 'day', 'sales', 'qty', 'cost'])
                new_df['day'] = new_df['day'].astype('int16')
                new_df['sales'] = new_df['sales'].astype('float64')
                new_df['qty'] = new_df['qty'].astype('float64')
                new_df['cost'] = new_df['cost'].astype('float64')
                
            df_old = pd.read_parquet(cache_path)
            df_filtered = df_old[~((df_old['day'] >= start_day) & (df_old['day'] <= days_elapsed))]
            df_merged = pd.concat([df_filtered, new_df], ignore_index=True)
            safe_write_parquet(cache_path, df_merged, schema, custom_metadata)
            return df_merged
    finally:
        conn.close()

def get_linetype_sales_cache(cfg, year, month, days_elapsed, full_refresh=False):
    cache_dir = os.path.join(FOLDER, 'cache')
    os.makedirs(cache_dir, exist_ok=True)
    cache_path = os.path.join(cache_dir, f'linetype_sales_{year}-{month:02d}.json')
    
    rebuild = full_refresh or not os.path.exists(cache_path)
    if not rebuild:
        try:
            with open(cache_path, encoding='utf-8') as f:
                cache_data = json.load(f)
            c_meta = cache_data.get('_meta', {})
            if c_meta.get('v') != 2 or c_meta.get('rule_hash') != RULE_HASH:
                print(f"  Linetype cache mismatch -> auto full-refresh")
                rebuild = True
        except Exception:
            rebuild = True
            
    conn = _conn(cfg)
    try:
        if rebuild:
            print(f"  [LINETYPE] Full refresh for {year}-{month:02d} up to day {days_elapsed}...")
            start_date = f'{year}-{month:02d}-01'
            end_date = f'{year}-{month:02d}-{days_elapsed:02d}'
            sql = """
                SELECT IFNULL(solinetype, 'unknown') AS solinetype,
                       DAY(sodate) AS day,
                       ROUND(SUM(net_sales_amt)) AS sales,
                       ROUND(SUM(net_qty)) AS qty,
                       COUNT(DISTINCT sono) AS bills
                FROM fact_sales
                WHERE solinetype NOT IN ('C', 'R')
                  AND sotowhs REGEXP '^[0-9]+$'
                  AND CAST(sotowhs AS UNSIGNED) BETWEEN 1 AND 500
                  AND sodate BETWEEN %s AND %s
                GROUP BY solinetype, DAY(sodate)
            """
            cur = conn.cursor(dictionary=True)
            cur.execute(sql, (start_date, end_date))
            rows = cur.fetchall()
            cur.close()
            
            days_data = {}
            for r in rows:
                day_str = str(r['day'])
                if day_str not in days_data:
                    days_data[day_str] = {}
                days_data[day_str][r['solinetype']] = {
                    'sales': int(r['sales'] or 0),
                    'qty': int(r['qty'] or 0),
                    'bills': int(r['bills'] or 0)
                }
                
            cache_data = {
                '_meta': {
                    'v': 2,
                    'built_by': 'antigravity-gemini-3-flash',
                    'rule_hash': RULE_HASH,
                    'timestamp': datetime.now().isoformat()
                },
                'days': days_data
            }
            safe_write_json(cache_path, cache_data)
        else:
            start_day = max(1, days_elapsed - 6)
            print(f"  [LINETYPE] Incremental refresh for {year}-{month:02d} days {start_day}..{days_elapsed}...")
            start_date = f'{year}-{month:02d}-{start_day:02d}'
            end_date = f'{year}-{month:02d}-{days_elapsed:02d}'
            sql = """
                SELECT IFNULL(solinetype, 'unknown') AS solinetype,
                       DAY(sodate) AS day,
                       ROUND(SUM(net_sales_amt)) AS sales,
                       ROUND(SUM(net_qty)) AS qty,
                       COUNT(DISTINCT sono) AS bills
                FROM fact_sales
                WHERE solinetype NOT IN ('C', 'R')
                  AND sotowhs REGEXP '^[0-9]+$'
                  AND CAST(sotowhs AS UNSIGNED) BETWEEN 1 AND 500
                  AND sodate BETWEEN %s AND %s
                GROUP BY solinetype, DAY(sodate)
            """
            cur = conn.cursor(dictionary=True)
            cur.execute(sql, (start_date, end_date))
            rows = cur.fetchall()
            cur.close()
            
            with open(cache_path, encoding='utf-8') as f:
                cache_data = json.load(f)
                
            for d in range(start_day, days_elapsed + 1):
                cache_data['days'].pop(str(d), None)
                
            for r in rows:
                day_str = str(r['day'])
                if day_str not in cache_data['days']:
                    cache_data['days'][day_str] = {}
                cache_data['days'][day_str][r['solinetype']] = {
                    'sales': int(r['sales'] or 0),
                    'qty': int(r['qty'] or 0),
                    'bills': int(r['bills'] or 0)
                }
            cache_data['_meta']['timestamp'] = datetime.now().isoformat()
            safe_write_json(cache_path, cache_data)
            
        return cache_data['days']
    finally:
        conn.close()


# Auto-detect current month from today (fixed 2026-06-05: previously hardcoded)
_today = date.today()
YEAR26, MONTH = _today.year, _today.month
YEAR25        = YEAR26 - 1
_, DAYS_26 = calendar.monthrange(YEAR26, MONTH)
_, DAYS_25 = calendar.monthrange(YEAR25, MONTH)

# ── store filter: numeric code ≤ 500, exclude warehouse codes ─────────────────
STORE_FILTER = """
    fs.sotowhs REGEXP '^[0-9]+$'
    AND CAST(fs.sotowhs AS UNSIGNED) BETWEEN 1 AND 500
"""

def _load_cfg():
    if not os.path.exists(DB_CONFIG_FILE):
        return None
    with open(DB_CONFIG_FILE, encoding='utf-8') as f:
        return json.load(f)

def _conn(cfg):
    import mysql.connector
    return mysql.connector.connect(
        host=cfg['host'], port=cfg.get('port', 3306),
        user=cfg['user'], password=cfg['password'],
        database=cfg.get('database', 'data-lake'),
        connection_timeout=60, charset='utf8mb4'
    )

def _load_branch_info():
    """Load store→DM/RM mapping from dim_cache.json (already built by rebuild_fraud_analysis.py)."""
    cache = os.path.join(FOLDER, 'dim_cache.json')
    if os.path.exists(cache):
        with open(cache, encoding='utf-8') as f:
            return json.load(f).get('branches', {})
    return {}

# ── STEP 1: Product sales aggregation ────────────────────────────────────────
def query_product_sales(conn, days_elapsed):
    cfg = _load_cfg()
    df_curr = get_product_cache(cfg, YEAR26, MONTH, days_elapsed, full_refresh=FULL_REFRESH)
    df_prev = get_product_cache(cfg, YEAR25, MONTH, DAYS_25, full_refresh=FULL_REFRESH)
    
    df_curr_f = df_curr[df_curr['day'] <= days_elapsed]
    # Same-period YoY (2026-06-11): compare days 1-N of prev year, not full month
    # (cache still holds full prev month — filter at aggregation only)
    df_prev_f = df_prev[df_prev['day'] <= days_elapsed]
    
    agg_curr = df_curr_f.groupby('iprod').agg(
        s26=('sales', 'sum'),
        cost26=('cost', 'sum'),
        q26=('qty', 'sum')
    ).reset_index()
    
    agg_prev = df_prev_f.groupby('iprod').agg(
        s25=('sales', 'sum'),
        q25=('qty', 'sum')
    ).reset_index()
    
    df = pd.merge(agg_curr, agg_prev, on='iprod', how='outer').fillna(0)
    df = df[df['s26'] > 0].sort_values('s26', ascending=False).reset_index(drop=True)
    
    iprod_list = df['iprod'].tolist()
    dim_map = _query_dim_product(conn, iprod_list)
    
    df['name']      = df['iprod'].map(lambda x: dim_map.get(x, {}).get('name', x))
    df['brand']     = df['iprod'].map(lambda x: dim_map.get(x, {}).get('brand', ''))
    df['grp']       = df['iprod'].map(lambda x: dim_map.get(x, {}).get('grp', 'ไม่ระบุ'))
    df['type_desc'] = df['iprod'].map(lambda x: dim_map.get(x, {}).get('type', ''))
    df['grp_code']  = df['iprod'].map(lambda x: dim_map.get(x, {}).get('grp_code', ''))
    df['ipunit3']   = df['iprod'].map(lambda x: dim_map.get(x, {}).get('ipunit3', 0))
    return df



def _dim_product_columns(conn):
    """Return set of column names in dim_product (lowercase)."""
    cur = conn.cursor()
    cur.execute("SHOW COLUMNS FROM dim_product")
    cols = {row[0].lower() for row in cur.fetchall()}
    cur.close()
    return cols


def _query_dim_product(conn, iprod_list):
    """
    Resolve product name/group/type/ipunit3 for a list of iprods.
    Handles two cases:
      - iprod matches dim_product.iprod directly
      - iprod is a barcode → look up via dim_item_barcode.parcode → dim_product
    Returns {iprod: {name, brand, grp, type, grp_code, ipunit3}}
    ipunit3 sourced from dim_product (fixed 2026-06-05 — previously from dim_item_barcode where col didn't exist → always 0)
    """
    if not iprod_list:
        return {}
    placeholders = ','.join(['%s'] * len(iprod_list))

    # Detect ipunit3 column (defensive — dim_product schema may vary)
    dp_cols = _dim_product_columns(conn)
    ipu3_select = ', ipunit3' if 'ipunit3' in dp_cols else ''
    has_ipu3    = 'ipunit3' in dp_cols

    # Direct lookup in dim_product
    cur = conn.cursor(dictionary=True)
    cur.execute(f"""
        SELECT iprod, idesc AS name, brndesc AS brand,
               igrdesc AS grp, itydesc AS type_desc, igrcode AS grp_code
               {ipu3_select}
        FROM dim_product
        WHERE iprod IN ({placeholders})
    """, iprod_list)
    result = {}
    for r in cur.fetchall():
        result[r['iprod']] = {
            'name':     r['name']     or r['iprod'],
            'brand':    r['brand']    or '',
            'grp':      r['grp']      or 'ไม่ระบุ',
            'type':     r['type_desc']or '',
            'grp_code': r['grp_code'] or '',
            'ipunit3':  float(r['ipunit3'] or 0) if has_ipu3 else 0,
        }

    # For iprods not found (barcode-as-iprod), look up via dim_item_barcode
    missing = [x for x in iprod_list if x not in result]
    if missing:
        pm = ','.join(['%s'] * len(missing))
        bridge_ipu3 = ', dp.ipunit3' if has_ipu3 else ''
        cur.execute(f"""
            SELECT dib.barcode, dp.iprod AS parcode,
                   dp.idesc AS name, dp.brndesc AS brand,
                   dp.igrdesc AS grp, dp.itydesc AS type_desc, dp.igrcode AS grp_code
                   {bridge_ipu3}
            FROM dim_item_barcode dib
            JOIN dim_product dp ON dp.iprod = dib.parcode
            WHERE dib.barcode IN ({pm}) AND dib.baractive = 'Y'
        """, missing)
        for r in cur.fetchall():
            result[r['barcode']] = {
                'name':     r['name']     or r['barcode'],
                'brand':    r['brand']    or '',
                'grp':      r['grp']      or 'ไม่ระบุ',
                'type':     r['type_desc']or '',
                'grp_code': r['grp_code'] or '',
                'ipunit3':  float(r['ipunit3'] or 0) if has_ipu3 else 0,
            }
    cur.close()
    return result


# ── STEP 2: Barcodes (+ onhand/ipunit3 if columns exist) ─────────────────────
def _dim_barcode_columns(conn):
    """Return set of column names in dim_item_barcode."""
    cur = conn.cursor()
    cur.execute("SHOW COLUMNS FROM dim_item_barcode")
    cols = {row[0].lower() for row in cur.fetchall()}
    cur.close()
    return cols

def query_barcodes(conn, iprod_list):
    if not iprod_list:
        return {}, {}
    placeholders = ','.join(['%s'] * len(iprod_list))

    # Check which optional columns exist
    cols = _dim_barcode_columns(conn)
    extra = []
    if 'onhand'  in cols: extra.append("SUM(COALESCE(onhand,0))  AS onhand")
    if 'ipunit3' in cols: extra.append("MIN(COALESCE(ipunit3,0)) AS ipunit3")
    extra_sql = (', ' + ', '.join(extra)) if extra else ''

    sql = f"""
        SELECT parcode,
               MIN(barcode) AS barcode
               {extra_sql}
        FROM dim_item_barcode
        WHERE parcode IN ({placeholders})
          AND baractive = 'Y'
        GROUP BY parcode
    """
    cur = conn.cursor(dictionary=True)
    cur.execute(sql, iprod_list)
    rows = cur.fetchall()
    cur.close()
    bc_map   = {r['parcode']: r['barcode'] for r in rows}
    item_map = {r['parcode']: {
                    'onhand':  float(r['onhand']  or 0) if 'onhand'  in cols else 0,
                    'ipunit3': float(r['ipunit3'] or 0) if 'ipunit3' in cols else 0,
                } for r in rows}
    return bc_map, item_map


# ── STEP 2b: May 2025 total per store (for store-level YoY baseline) ─────────
def query_store_sales_may25(conn, days_elapsed):
    cfg = _load_cfg()
    df_prev = get_product_cache(cfg, YEAR25, MONTH, DAYS_25, full_refresh=FULL_REFRESH)
    # Same-period YoY (2026-06-11): days 1-N only
    df_prev = df_prev[df_prev['day'] <= days_elapsed]
    df_grouped = df_prev.groupby('whs')['sales'].sum().reset_index()
    return {r['whs']: int(round(r['sales'])) for _, r in df_grouped.iterrows()}


# ── STEP 2c: May 2026 total per store (true total — fixes HAVING threshold gap) ─
def query_store_sales_may26(conn, days_elapsed):
    cfg = _load_cfg()
    df_curr = get_product_cache(cfg, YEAR26, MONTH, days_elapsed, full_refresh=FULL_REFRESH)
    df_filtered = df_curr[df_curr['day'] <= days_elapsed]
    df_grouped = df_filtered.groupby('whs')['sales'].sum().reset_index()
    return {r['whs']: int(round(r['sales'])) for _, r in df_grouped.iterrows()}


# ── STEP 2d: Sales breakdown by solinetype ────────────────────────────────────
def query_sales_by_linetype(conn, days_elapsed):
    cfg = _load_cfg()
    days_data = get_linetype_sales_cache(cfg, YEAR26, MONTH, days_elapsed, full_refresh=FULL_REFRESH)
    
    totals = defaultdict(lambda: {'sales': 0, 'qty': 0, 'bills': 0})
    for d in range(1, days_elapsed + 1):
        day_str = str(d)
        if day_str in days_data:
            for linetype, vals in days_data[day_str].items():
                totals[linetype]['sales'] += vals['sales']
                totals[linetype]['qty'] += vals['qty']
                totals[linetype]['bills'] += vals['bills']
                
    result = []
    for linetype, v in sorted(totals.items(), key=lambda x: x[1]['sales'], reverse=True):
        result.append({
            'type': linetype,
            'sales': int(v['sales']),
            'qty': int(v['qty']),
            'bills': int(v['bills'])
        })
    return result


# ── STEP 3: Store-indexed breakdown — ALL products ────────────────────────────
def query_store_breakdown(conn, days_elapsed):
    cfg = _load_cfg()
    df_curr = get_product_cache(cfg, YEAR26, MONTH, days_elapsed, full_refresh=FULL_REFRESH)
    df_filtered = df_curr[df_curr['day'] <= days_elapsed]
    df_grouped = df_filtered.groupby(['whs', 'iprod']).agg(s26=('sales', 'sum'), q26=('qty', 'sum')).reset_index()
    df_grouped = df_grouped[df_grouped['s26'] > 0]
    
    result = defaultdict(dict)
    for _, r in df_grouped.iterrows():
        result[r['whs']][r['iprod']] = [
            int(round(r['s26'])),
            int(round(r['q26']))
        ]
    print(f'      {len(result)} stores, {sum(len(v) for v in result.values()):,} product-store entries (from cache)')
    return dict(result)


# ── STEP 3b: Per-store onhand from MyWMS ibl (added 2026-06-05) ──────────────
def query_onhand_per_store(conn):
    """Returns {(parcode, whs_padded): onhand_qty} from MYWMS2023_CENTER.ibl.
    Direct join: iprod = ibl_parcode (86.6% match confirmed via test_iprod_vs_ibl.py).
    Filter to locno='stock' shelfno='shelfno' = main shelf stock (excludes visual
    adjustment and partner consignment rows). Stores 1-500 only."""
    sql = """
        SELECT LPAD(ibl_whsno, 3, '0') AS whs,
               ibl_parcode AS iprod,
               SUM(ibl_qty_beg_bal + ibl_qty_rec - ibl_qty_iss) AS onhand,
               MAX(ibl_date_sale) AS last_sale
        FROM MYWMS2023_CENTER.ibl
        WHERE ibl_locno = 'stock'
          AND ibl_shelfno = 'shelfno'
          AND ibl_whsno REGEXP '^[0-9]+$'
          AND CAST(ibl_whsno AS UNSIGNED) BETWEEN 1 AND 500
        GROUP BY whs, ibl_parcode
        HAVING onhand > 0
    """
    cur = conn.cursor(dictionary=True)
    cur.execute(sql)
    result = {}
    n_rows = 0
    for r in cur.fetchall():
        n_rows += 1
        result[(r['iprod'], r['whs'])] = int(float(r['onhand']))
    cur.close()
    print(f'      {n_rows:,} (iprod, store) onhand rows from MYWMS ibl')
    return result


# ── STEP 4: Build JSON ────────────────────────────────────────────────────────
def build_json(df, barcode_map, item_map, store_breakdown, branch_info, days_elapsed, store_s25=None, store_s26=None, linetype_breakdown=None, onhand_map=None):
    today = date.today()
    products = []
    for rank, (_, row) in enumerate(df.iterrows(), 1):
        s26   = float(row['s26'])
        s25   = float(row['s25'])
        q26   = float(row['q26'])
        q25   = float(row['q25'])
        cost26= float(row['cost26'])
        gp26  = s26 - cost26
        iprod = row['iprod']
        info  = item_map.get(iprod, {})
        products.append({
            'rank':    rank,
            'iprod':   iprod,
            'barcode': barcode_map.get(iprod, iprod),
            'name':    str(row['name']  or '')[:40],
            'brand':   str(row['brand'] or '')[:25],
            'group':   str(row['grp']   or 'ไม่ระบุ')[:30],
            'type':    str(row['type_desc'] or '')[:25],
            'q26':     round(q26),
            'q25':     round(q25),
            'q_yoy':   round((q26/q25-1)*100, 1) if q25 else None,
            's26':     round(s26),
            's25':     round(s25),
            's_yoy':   round((s26/s25-1)*100, 1) if s25 else None,
            'cost26':  round(cost26),
            'gp26':    round(gp26),
            'gp_pct':  round(gp26/s26*100, 1) if s26 else 0,
            'onhand':  round(info.get('onhand', 0)),
            'ipunit3': round(float(row.get('ipunit3', 0) or 0)),  # from dim_product (fixed 2026-06-05)
        })

    # Categories by igrdesc (group)
    cat = defaultdict(lambda: {'sales26':0,'sales25':0,'cost26':0,'qty26':0,'qty25':0,'count':0})
    for _, row in df.iterrows():
        g = str(row['grp'] or 'ไม่ระบุ')[:30]
        cat[g]['sales26'] += float(row['s26'])
        cat[g]['sales25'] += float(row['s25'])
        cat[g]['cost26']  += float(row['cost26'])
        cat[g]['qty26']   += float(row['q26'])
        cat[g]['qty25']   += float(row['q25'])
        cat[g]['count']   += 1
    categories = []
    for g, v in sorted(cat.items(), key=lambda x: x[1]['sales26'], reverse=True)[:50]:
        s26, s25, c26 = v['sales26'], v['sales25'], v['cost26']
        gp = s26 - c26
        categories.append({
            'group':   g,
            'count':   v['count'],
            'sales26': round(s26),
            'sales25': round(s25),
            'cost26':  round(c26),
            'gp26':    round(gp),
            'gp_pct':  round(gp/s26*100, 1) if s26 else 0,
            'qty26':   round(v['qty26']),
            'qty25':   round(v['qty25']),
            's_yoy':   round((s26/s25-1)*100, 1) if s25 else None,
        })

    # Type-level categories (itydesc) with igrdesc_count + barcode_count
    type_agg = defaultdict(lambda: {
        'sales26':0,'sales25':0,'cost26':0,'qty26':0,'qty25':0,
        'barcodes':set(),'grps':set()
    })
    for _, row in df.iterrows():
        t = str(row['type_desc'] or 'ไม่ระบุประเภท')[:30]
        type_agg[t]['sales26'] += float(row['s26'])
        type_agg[t]['sales25'] += float(row['s25'])
        type_agg[t]['cost26']  += float(row['cost26'])
        type_agg[t]['qty26']   += float(row['q26'])
        type_agg[t]['qty25']   += float(row['q25'])
        bc = barcode_map.get(row['iprod'], row['iprod'])
        type_agg[t]['barcodes'].add(bc)
        type_agg[t]['grps'].add(str(row['grp'] or 'ไม่ระบุ')[:30])
    total_s26 = sum(v['sales26'] for v in type_agg.values()) or 1
    type_cats = []
    for t, v in sorted(type_agg.items(), key=lambda x: x[1]['sales26'], reverse=True):
        s26, s25, c26 = v['sales26'], v['sales25'], v['cost26']
        gp = s26 - c26
        type_cats.append({
            'type':        t,
            'sales26':     round(s26),
            'sales25':     round(s25),
            'cost26':      round(c26),
            'gp26':        round(gp),
            'gp_pct':      round(gp/s26*100, 1) if s26 else 0,
            'qty26':       round(v['qty26']),
            'qty25':       round(v['qty25']),
            's_yoy':       round((s26/s25-1)*100, 1) if s25 else None,
            'pct_of_total': round(s26/total_s26*100, 2),
            'barcode_cnt': len(v['barcodes']),
            'grp_cnt':     len(v['grps']),
        })

    # Merge onhand into store_breakdown as 3rd array element: [s26, q26, onhand]
    # Old shape stays array-compatible — JS destructure `[s26, q26]` still works.
    if onhand_map:
        for whs, pmap in store_breakdown.items():
            for iprod, vals in pmap.items():
                oh = onhand_map.get((iprod, whs), 0)
                if len(vals) == 2:
                    vals.append(oh)
                elif len(vals) >= 3:
                    vals[2] = oh

    return {
        'generated':    today.isoformat(),
        'days_elapsed': days_elapsed,
        'days_in_month': DAYS_26,
        'month26':      f'{YEAR26}-{MONTH:02d}',
        'month25':      f'{YEAR25}-{MONTH:02d}',
        'products':     products,
        'categories':   categories,
        'type_cats':    type_cats,
        'store_breakdown': store_breakdown,
        'store_info': {
            k: {
                'name':    v['name'], 'dm': v['dm'], 'rm': v['rm'],
                's25_may': (store_s25 or {}).get(k.zfill(3), 0),
                's26_may': (store_s26 or {}).get(k.zfill(3), 0),
            }
            for k, v in branch_info.items()
        },
        'rm_list': sorted({v['rm'] for v in branch_info.values() if v.get('rm')}),
        'dm_list': sorted({v['dm'] for v in branch_info.values() if v.get('dm')}),
        'linetype_breakdown': linetype_breakdown or [],
    }


# ── PUSH ──────────────────────────────────────────────────────────────────────
def push_github(cfg):
    import subprocess, shutil, tempfile, uuid
    token    = cfg.get('github_token', '')
    repo     = cfg.get('github_repo', 'tumsbux/daily-report')
    REPO_DIR = os.path.join(tempfile.gettempdir(), f'dlr-{uuid.uuid4().hex[:8]}')
    env = {**os.environ,
           'GIT_AUTHOR_NAME':    'Dashboard Bot', 'GIT_AUTHOR_EMAIL':    'bot@dashboard',
           'GIT_COMMITTER_NAME': 'Dashboard Bot', 'GIT_COMMITTER_EMAIL': 'bot@dashboard'}
    subprocess.run(['git', 'clone', '--depth', '1', f'https://{token}@github.com/{repo}.git', REPO_DIR],
                   capture_output=True, timeout=300)  # shallow clone — full history timed out at 60s (2026-06-11)
    shutil.copy2(OUT_JSON, os.path.join(REPO_DIR, 'product_data.json'))
    subprocess.run(['git', '-C', REPO_DIR, 'add', 'product_data.json'],
                   capture_output=True, env=env)
    cr = subprocess.run(
        ['git', '-C', REPO_DIR, 'commit', '-m', f'product data update {date.today()}'],
        capture_output=True, text=True, env=env)
    if 'nothing to commit' in (cr.stdout + cr.stderr):
        print('  GitHub: nothing to commit')
    else:
        pr = subprocess.run(['git', '-C', REPO_DIR, 'push', 'origin', 'HEAD'],
                            capture_output=True, text=True, env=env, timeout=60)
        print('  GitHub:', '✅ pushed OK' if pr.returncode == 0 else pr.stderr[-150:])
    shutil.rmtree(REPO_DIR, ignore_errors=True)



# ── Auto-detect max available day in fact_sales ───────────────────────────────
def detect_max_day(conn):
    """Query fact_sales for the latest day with data in the current month/year."""
    end_date26 = f'{YEAR26}-{MONTH:02d}-{DAYS_26:02d}'
    cur = conn.cursor()
    cur.execute(f"""
        SELECT MAX(DAY(sodate))
        FROM fact_sales
        WHERE sodate BETWEEN '{YEAR26}-{MONTH:02d}-01' AND '{end_date26}'
          AND solinetype NOT IN ('C', 'R')
          AND sotowhs REGEXP '^[0-9]+$'
          AND CAST(sotowhs AS UNSIGNED) BETWEEN 1 AND 500
    """)
    row = cur.fetchone()
    cur.close()
    return int(row[0]) if row and row[0] else 1


# ── MAIN ──────────────────────────────────────────────────────────────────────
def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--day', type=int, default=None)
    parser.add_argument('--no-push', action='store_true')
    parser.add_argument('--full-refresh', action='store_true')
    args = parser.parse_args()
    global PUSH, FULL_REFRESH
    PUSH = not args.no_push
    FULL_REFRESH = args.full_refresh

    cfg = _load_cfg()
    if not cfg:
        print('ERROR: db_config.json not found'); return

    conn = _conn(cfg)
    print('Connected to MySQL: ' + cfg['host'])

    if args.day:
        days_elapsed = args.day
        print(f'  Using --day {days_elapsed} (manual override)')
    else:
        days_elapsed = detect_max_day(conn)
        print(f'  Auto-detected max day in fact_sales: {days_elapsed}')

    print('=' * 60)
    print('  Product Data Builder  May %d vs %d  days 1-%d' % (YEAR26, YEAR25, days_elapsed))
    print('=' * 60)

    print('[1/4] Querying product sales ...')
    df = query_product_sales(conn, days_elapsed)
    total26 = df['s26'].sum()
    total25 = df['s25'].sum()
    yoy = round((total26/total25-1)*100, 1) if total25 else 0
    print('      %d products | %.1fM (%+.1f%% YoY) | %d units' % (
        len(df), total26/1e6, yoy, int(df['q26'].sum())))

    print('[2/4] Loading barcodes ...')
    bc_map, item_map = query_barcodes(conn, df['iprod'].tolist())
    print('      %d barcodes' % len(bc_map))

    print('[3/4] Store breakdown (ALL products) ...')
    store_bd = query_store_breakdown(conn, days_elapsed)

    print('      Loading May 2025 per-store baseline ...')
    store_s25 = query_store_sales_may25(conn, days_elapsed)
    print('      %d stores with May25 data' % len(store_s25))

    print('      Loading May 2026 per-store true total ...')
    store_s26 = query_store_sales_may26(conn, days_elapsed)
    print('      %d stores with May26 data' % len(store_s26))

    print('      Loading sales by solinetype ...')
    linetype_bd = query_sales_by_linetype(conn, days_elapsed)
    print('      %d line types found' % len(linetype_bd))

    print('      Loading per-store onhand from MYWMS ibl ...')
    try:
        onhand_map = query_onhand_per_store(conn)
    except Exception as _e:
        print(f'      WARNING: onhand query failed: {_e}')
        onhand_map = {}

    conn.close()

    print('[4/4] Building product_data.json ...')
    branch_info = _load_branch_info()
    output = build_json(df, bc_map, item_map, store_bd, branch_info, days_elapsed, store_s25, store_s26, linetype_bd, onhand_map)

    with open(OUT_JSON, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, separators=(',', ':'))

    sz = os.path.getsize(OUT_JSON) // 1024
    print('      Saved: %d KB | %d products | %d types' % (
        sz, len(output['products']), len(output.get('type_cats', []))))

    print('Done! May %d days 1-%d: %.1fM | YoY: %+.1f%% | %d SKU' % (
        YEAR26, days_elapsed, total26/1e6, yoy, len(output['products'])))

    if PUSH:
        push_github(cfg)


if __name__ == '__main__':
    main()
