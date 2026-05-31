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

import os, json, sys
import pandas as pd
from datetime import date
from collections import defaultdict

FOLDER         = os.path.dirname(os.path.abspath(__file__))
OUT_JSON       = os.path.join(FOLDER, 'product_data.json')
DB_CONFIG_FILE = os.path.join(FOLDER, 'db_config.json')
PUSH           = '--no-push' not in sys.argv

YEAR26, MONTH = 2026, 5
YEAR25        = 2025

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
def query_product_sales(conn):
    """
    Aggregate fact_sales by product for May 2026 vs May 2025.
    JOIN dim_product for name/brand/group/type.
    Returns DataFrame with one row per iprod.
    """
    sql = f"""
        SELECT
            fs.iprod,
            COALESCE(dp.idesc,  fs.iprod)    AS name,
            COALESCE(dp.brndesc, '')          AS brand,
            COALESCE(dp.igrdesc, 'ไม่ระบุ')  AS grp,
            COALESCE(dp.itydesc, '')          AS type_desc,
            COALESCE(dp.igrcode, '')          AS grp_code,
            SUM(CASE WHEN YEAR(fs.sodate)={YEAR26} AND MONTH(fs.sodate)={MONTH}
                     THEN fs.net_sales_amt ELSE 0 END)          AS s26,
            SUM(CASE WHEN YEAR(fs.sodate)={YEAR25} AND MONTH(fs.sodate)={MONTH}
                     THEN fs.net_sales_amt ELSE 0 END)          AS s25,
            SUM(CASE WHEN YEAR(fs.sodate)={YEAR26} AND MONTH(fs.sodate)={MONTH}
                     THEN COALESCE(fs.total_cost, 0) ELSE 0 END) AS cost26,
            SUM(CASE WHEN YEAR(fs.sodate)={YEAR26} AND MONTH(fs.sodate)={MONTH}
                     THEN fs.net_qty ELSE 0 END)                 AS q26,
            SUM(CASE WHEN YEAR(fs.sodate)={YEAR25} AND MONTH(fs.sodate)={MONTH}
                     THEN fs.net_qty ELSE 0 END)                 AS q25
        FROM fact_sales fs
        LEFT JOIN dim_product dp ON dp.iprod = fs.iprod
        WHERE fs.solinetype = 'N'
          AND {STORE_FILTER}
          AND (
              (YEAR(fs.sodate)={YEAR26} AND MONTH(fs.sodate)={MONTH})
              OR
              (YEAR(fs.sodate)={YEAR25} AND MONTH(fs.sodate)={MONTH})
          )
        GROUP BY fs.iprod, dp.idesc, dp.brndesc, dp.igrdesc, dp.itydesc, dp.igrcode
        HAVING s26 > 0
        ORDER BY s26 DESC
    """
    df = pd.read_sql(sql, conn)
    for col in ['s26','s25','cost26','q26','q25']:
        df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
    return df


# ── STEP 2: Barcodes + onhand + ipunit3 ───────────────────────────────────────
def query_barcodes(conn, iprod_list):
    if not iprod_list:
        return {}, {}
    placeholders = ','.join(['%s'] * len(iprod_list))
    sql = f"""
        SELECT parcode,
               MIN(barcode)              AS barcode,
               SUM(COALESCE(onhand, 0))  AS onhand,
               MIN(COALESCE(ipunit3, 0)) AS ipunit3
        FROM dim_item_barcode
        WHERE parcode IN ({placeholders})
          AND baractive = 'Y'
        GROUP BY parcode
    """
    cur = conn.cursor(dictionary=True)
    cur.execute(sql, iprod_list)
    rows = cur.fetchall()
    cur.close()
    bc_map   = {r['parcode']: r['barcode']              for r in rows}
    item_map = {r['parcode']: {'onhand': float(r['onhand'] or 0),
                                'ipunit3': float(r['ipunit3'] or 0)}
                for r in rows}
    return bc_map, item_map


# ── STEP 3: Store-level breakdown for top 500 ─────────────────────────────────
def query_store_breakdown(conn, iprod_list):
    if not iprod_list:
        return {}
    placeholders = ','.join(['%s'] * len(iprod_list))
    sql = f"""
        SELECT
            fs.iprod,
            LPAD(fs.sotowhs, 3, '0')       AS whs,
            YEAR(fs.sodate)                AS yr,
            SUM(fs.net_sales_amt)          AS sales,
            SUM(fs.net_qty)                AS qty,
            SUM(COALESCE(fs.total_cost,0)) AS cost
        FROM fact_sales fs
        WHERE fs.solinetype = 'N'
          AND {STORE_FILTER}
          AND fs.iprod IN ({placeholders})
          AND (
              (YEAR(fs.sodate)={YEAR26} AND MONTH(fs.sodate)={MONTH})
              OR
              (YEAR(fs.sodate)={YEAR25} AND MONTH(fs.sodate)={MONTH})
          )
        GROUP BY fs.iprod, whs, YEAR(fs.sodate)
    """
    cur = conn.cursor(dictionary=True)
    cur.execute(sql, iprod_list)
    rows = cur.fetchall()
    cur.close()
    breakdown = defaultdict(dict)
    for r in rows:
        sfx = '26' if int(r['yr']) == YEAR26 else '25'
        breakdown[r['iprod']][f"{r['whs']}:{sfx}"] = {
            'sales': round(float(r['sales'] or 0)),
            'qty':   round(float(r['qty']   or 0)),
            'cost':  round(float(r['cost']  or 0)),
        }
    return dict(breakdown)


# ── STEP 4: Build JSON ────────────────────────────────────────────────────────
def build_json(df, barcode_map, item_map, store_breakdown, branch_info):
    today      = date.today()
    # whsddpact lags 1-2 days. Use yesterday's day unless overridden.
    # For May 2026: data finalized through day 30 (whsddpact lags on day 31).
    days_elapsed = min(today.day - 1, 30) if MONTH == 5 and today.day > 30 else today.day - 1
    days_elapsed = max(days_elapsed, 1)

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
            'ipunit3': round(info.get('ipunit3', 0)),
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

    return {
        'generated':    today.isoformat(),
        'days_elapsed': days_elapsed,
        'month26':      f'{YEAR26}-{MONTH:02d}',
        'month25':      f'{YEAR25}-{MONTH:02d}',
        'products':     products,
        'categories':   categories,
        'type_cats':    type_cats,
        'store_breakdown': store_breakdown,
        'store_info': {
            k: {'name': v['name'], 'dm': v['dm'], 'rm': v['rm']}
            for k, v in branch_info.items()
        },
        'rm_list': sorted({v['rm'] for v in branch_info.values() if v.get('rm')}),
        'dm_list': sorted({v['dm'] for v in branch_info.values() if v.get('dm')}),
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
    subprocess.run(['git', 'clone', f'https://{token}@github.com/{repo}.git', REPO_DIR],
                   capture_output=True, timeout=60)
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


# ── MAIN ──────────────────────────────────────────────────────────────────────
def main():
    print('=' * 60)
    print(f'  Product Data Builder  (MySQL-native)  May {YEAR26} vs {YEAR25}')
    print('=' * 60)

    cfg = _load_cfg()
    if not cfg:
        print('ERROR: db_config.json not found'); return

    conn = _conn(cfg)
    print(f'Connected to MySQL: {cfg["host"]}')

    print(f'\n[1/4] Querying product sales (May {YEAR26} vs May {YEAR25}) ...')
    df = query_product_sales(conn)
    total26 = df['s26'].sum()
    total25 = df['s25'].sum()
    yoy     = round((total26/total25-1)*100, 1) if total25 else 0
    print(f'      {len(df):,} products | '
          f'฿{total26:,.0f} ({yoy:+.1f}% YoY) | '
          f'{int(df["q26"].sum()):,} units')

    print('\n[2/4] Loading barcodes + onhand + ipunit3 ...')
    bc_map, item_map = query_barcodes(conn, df['iprod'].tolist())
    print(f'      {len(bc_map):,} barcodes')

    print('\n[3/4] Store breakdown (top 500 products) ...')
    top500 = df.head(500)['iprod'].tolist()
    store_bd = query_store_breakdown(conn, top500)
    print(f'      {sum(len(v) for v in store_bd.values()):,} store-product entries')

    conn.close()

    print('\n[4/4] Building product_data.json ...')
    branch_info = _load_branch_info()
    output = build_json(df, bc_map, item_map, store_bd, branch_info)

    with open(OUT_JSON, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, separators=(',', ':'))

    sz = os.path.getsize(OUT_JSON) // 1024
    print(f'      Saved: {sz:,} KB | '
          f'{len(output["products"])} products | '
          f'{len(output["type_cats"])} types | '
          f'{len(output["categories"])} groups')

    pri