#!/usr/bin/env python3
"""
rebuild_fraud_analysis.py
=========================
Rebuilds fraud_analysis.html from:
  - returnall.txt      (return transactions, all months)
  - username.txt       (employee ID → full name)
  - data-lake_dim_branch.sql  (store → DM/RM mapping)
  - target.txt         (MTD sales per store, for return-rate calc)

Run manually or via update_dashboard.py (called automatically each morning).

Usage:
    python rebuild_fraud_analysis.py
    python rebuild_fraud_analysis.py --no-push    # skip GitHub push
"""

import os, re, json, sys, subprocess
import pandas as pd
from datetime import datetime

# ── CONFIG ────────────────────────────────────────────────────────────────────
FOLDER  = os.path.dirname(os.path.abspath(__file__))
PUSH    = '--no-push' not in sys.argv

RETURNALL = os.path.join(FOLDER, 'returnall.txt')
USERNAME  = os.path.join(FOLDER, 'username.txt')
BRANCH_SQL= os.path.join(FOLDER, 'data-lake_dim_branch.sql')
TARGET    = os.path.join(FOLDER, 'target.txt')
OUT_JSON  = os.path.join(FOLDER, 'fraud_data.json')
OUT_HTML  = os.path.join(FOLDER, 'fraud_analysis.html')

# ── TEMPLATE (embedded, no external file needed) ──────────────────────────────
# The HTML template is read from fraud_analysis_template.html if it exists,
# otherwise a minimal fallback is used.  When Claude regenerates the dashboard
# it always writes the template alongside this script.
TEMPLATE_FILE  = os.path.join(FOLDER, 'fraud_analysis_template.html')
BARCODE_SQL    = os.path.join(FOLDER, 'data-lake_dim_item_barcode.sql')
PRODUCT_SQL    = os.path.join(FOLDER, 'data-lake_dim_product.sql')

# ── LOAD USERNAME MAP ─────────────────────────────────────────────────────────
def load_users():
    df = pd.read_csv(USERNAME, sep='\t', dtype=str, on_bad_lines='skip')
    return dict(zip(df['uname'].str.strip(), df['ufname'].str.strip()))

# ── LOAD DIM_BRANCH ───────────────────────────────────────────────────────────
def load_branches():
    with open(BRANCH_SQL, encoding='utf-8') as f:
        sql = f.read()
    vm = re.search(r"INSERT INTO `dim_branch` VALUES\s*(.*?);", sql, re.DOTALL)
    branches = {}
    for r in re.findall(r"\(([^)]+)\)", vm.group(1)):
        p = [x.strip().strip("'") for x in r.split(',')]
        if len(p) >= 6:
            branches[p[0].zfill(3)] = {
                'store_name': p[1] or '?', 'dm': p[3] or '?', 'rm': p[5] or '?'
            }
    return branches


# ── LOAD ITEM BARCODE (barcode → parcode) ─────────────────────────────────────
def _parse_sql_two_cols(sql_text, table_name):
    """Fast line-by-line parser: reads INSERT lines and extracts first two quoted string columns."""
    result = {}
    prefix = f"INSERT INTO `{table_name}` VALUES "
    for line in sql_text.splitlines():
        line = line.strip()
        if not line.startswith(prefix):
            continue
        # Each row: ('col1','col2',...)  split on ),( boundaries
        data = line[len(prefix):]
        # Walk char-by-char to extract first two quoted values per row
        i = 0
        n = len(data)
        while i < n:
            if data[i] != '(':
                i += 1
                continue
            i += 1  # skip '('
            cols = []
            for _ in range(2):
                if i >= n or data[i] != "'":
                    break
                i += 1  # skip opening quote
                val = []
                while i < n:
                    c = data[i]
                    if c == '\\' and i + 1 < n:
                        val.append(data[i+1])
                        i += 2
                    elif c == "'":
                        i += 1  # skip closing quote
                        break
                    else:
                        val.append(c)
                        i += 1
                cols.append(''.join(val))
                if i < n and data[i] == ',':
                    i += 1  # skip comma between cols
            if len(cols) == 2:
                result[cols[0]] = cols[1]
            # skip to end of this row
            while i < n and data[i] != ')':
                i += 1
            i += 1  # skip ')'
    return result

def load_barcode_map():
    if not os.path.exists(BARCODE_SQL):
        return {}
    with open(BARCODE_SQL, encoding='utf-8') as f:
        sql = f.read()
    # col1=parcode, col2=barcode  →  bmap[barcode]=parcode
    raw = _parse_sql_two_cols(sql, 'dim_item_barcode')
    return {v: k for k, v in raw.items()}  # flip: barcode->parcode

# ── LOAD DIM_PRODUCT (parcode → idesc) ────────────────────────────────────────
def load_product_map():
    if not os.path.exists(PRODUCT_SQL):
        return {}
    with open(PRODUCT_SQL, encoding='utf-8') as f:
        sql = f.read()
    # col1=iprod, col2=idesc  →  pmap[iprod]=idesc
    return _parse_sql_two_cols(sql, 'dim_product')

# ── LOAD RETURNS ──────────────────────────────────────────────────────────────
def load_returns(umap, branches):
    df = pd.read_csv(RETURNALL, sep='\t', dtype=str)
    for c in ['line_amount_inc_vat', 'return_qty', 'unit_price', 'allocated_net_amount']:
        df[c] = pd.to_numeric(df[c], errors='coerce')
    df['return_date'] = pd.to_datetime(df['return_date'], errors='coerce')
    df['month']   = df['return_date'].dt.strftime('%Y-%m')
    df['day']     = df['return_date'].dt.day
    df['whs']     = df['warehouse_code'].str.zfill(3)
    df['rtuname'] = df['rtuname'].fillna('').str.strip()
    for col in ['store_name', 'dm', 'rm']:
        df[col] = df['whs'].map(lambda x, c=col: branches.get(x, {}).get(c, '?')).fillna('?')
    # Filter only active returns (U = Used/Active); exclude cancelled (C)
    df = df[df['rtstatus'].str.strip() == 'U'].copy()
    df['is_zero']  = df['cstcode'].str.strip() == '0000'
    df['hour']     = pd.to_numeric(df['rttime'].str[:2], errors='coerce')
    df['fullname'] = df['rtuname'].map(umap).fillna('?')
    return df

# ── COMPUTE STORE RISK (simplified from target.txt + returnall) ────────────────
def compute_store_risk(df, branches):
    tgt = pd.read_csv(TARGET, sep='\t', dtype=str, on_bad_lines='skip')
    tgt['whsddpnetamt'] = pd.to_numeric(tgt.get('whsddpnetamt'), errors='coerce')
    # Use latest full month available in target
    max_mo = df['month'].max()
    yr, mo = max_mo.split('-')
    tgt_mo = tgt[(tgt['whsddyyyy'] == yr) & (tgt['whsddmm'] == str(int(mo)).zfill(2))]
    tgt_mo = tgt_mo.copy(); tgt_mo['whs'] = tgt_mo['whsddno'].str.zfill(3)
    sales = tgt_mo.groupby('whs')['whsddpnetamt'].sum()

    ret_mo = df[df['month'] == max_mo]
    ret_by  = ret_mo.groupby('whs')['allocated_net_amount'].sum()
    zero_by = ret_mo.groupby('whs')['is_zero'].mean() * 100
    cnt_by  = ret_mo.groupby('whs').size()

    rows = []
    for whs, br in branches.items():
        s = sales.get(whs, 0); r = ret_by.get(whs, 0)
        zp = float(zero_by.get(whs, 0)); cnt = int(cnt_by.get(whs, 0))
        if s == 0: continue
        rr = r / s * 100
        score = int(min(rr * 20, 50) + min(zp * 0.5, 30) + min(cnt * 0.5, 20))
        level = 'HIGH' if score >= 50 else 'MEDIUM' if score >= 25 else 'LOW'
        rows.append({'code': whs, 'name': br['store_name'],
                     'dm_name': br['dm'], 'rm_name': br['rm'],
                     'sales_mtd': round(float(s), 0), 'ret_mtd': round(float(r), 0),
                     'ret_rate': round(rr, 3), 'zero_pct': round(zp, 1),
                     'ret_cnt': cnt, 'score': score, 'level': level})
    rows.sort(key=lambda x: -x['score'])
    return rows

# ── BUILD MONTHLY ANALYSIS ────────────────────────────────────────────────────
def rec(d):
    return json.loads(d.fillna('?').to_json(orient='records', force_ascii=False))

def build_month(sub, barmap=None, prodmap=None):
    sub = sub.copy()
    barmap  = barmap  or {}
    prodmap = prodmap or {}
    # Repeat SO
    so = sub.groupby('rtsono').agg(
        lines=('rtno','count'), amount=('allocated_net_amount','sum'),
        cashier=('rtuname','first'), fname=('fullname','first'),
        store=('whs','first'), store_name=('store_name','first'),
        dm=('dm','first'), rm=('rm','first'),
        zero=('is_zero','sum'), date=('return_date','first')
    ).reset_index()
    so = so[so['lines'] > 1].sort_values('amount', ascending=False)

    # Product detail per rtsono (barcode -> parcode -> idesc)
    detail_map = (
        sub[sub['rtsono'].isin(so['rtsono'])]
        .groupby(['rtsono','iprod'])
        .agg(allocated_net_amount=('allocated_net_amount','sum'),
             return_qty=('return_qty','sum'))
        .reset_index()
        .sort_values(['rtsono','allocated_net_amount'], ascending=[True, False])
    )
    detail_dict = {}
    for sono, grp in detail_map.groupby('rtsono'):
        items = []
        for _, row in grp.iterrows():
            barcode = str(row['iprod'])
            parcode = barmap.get(barcode, barcode)   # fallback to barcode itself
            idesc   = prodmap.get(parcode, '')
            items.append({
                'barcode': barcode,
                'parcode': parcode,
                'idesc':   idesc,
                'qty':     int(row['return_qty']) if not pd.isna(row['return_qty']) else 0,
                'amt':     round(float(row['allocated_net_amount']), 2)
            })
        detail_dict[sono] = items
    so_list = json.loads(so.fillna('?').to_json(orient='records', force_ascii=False))
    for r in so_list:
        r['detail'] = detail_dict.get(r.get('rtsono'), [])

    # rtuname
    rtu = sub.groupby(['rtuname','fullname','whs','store_name','dm','rm']).agg(
        returns=('rtno','count'), amount=('allocated_net_amount','sum'),
        zero=('is_zero','sum'), uso=('rtsono','nunique'),
    ).reset_index()
    rtu['rep']   = rtu['returns'] - rtu['uso']
    rtu['zp']    = (rtu['zero'] / rtu['returns'] * 100).round(1)
    mx_a = max(rtu['amount'].max(), 1); mx_r = max(rtu['rep'].max(), 1)
    rtu['score'] = ((rtu['amount']/mx_a*40) + (rtu['zp']/100*35) + (rtu['rep']/mx_r*25)).round(1)
    rtu = rtu.sort_values('amount', ascending=False)

    # Store
    st = sub.groupby(['whs','store_name','dm','rm']).agg(
        returns=('rtno','count'), amount=('allocated_net_amount','sum'),
        cashiers=('rtuname','nunique'), zero=('is_zero','sum'),
    ).reset_index()
    st['zp'] = (st['zero'] / st['returns'] * 100).round(1)
    st = st.sort_values('amount', ascending=False)

    # DM
    dm = sub.groupby(['dm','rm']).agg(
        returns=('rtno','count'), amount=('allocated_net_amount','sum'),
        stores=('whs','nunique'), cashiers=('rtuname','nunique'), zero=('is_zero','sum'),
    ).reset_index()
    dm['zp'] = (dm['zero'] / dm['returns'] * 100).round(1)
    dm = dm.sort_values('amount', ascending=False)

    # RM
    rm = sub.groupby('rm').agg(
        returns=('rtno','count'), amount=('allocated_net_amount','sum'),
        stores=('whs','nunique'), cashiers=('rtuname','nunique'),
        zero=('is_zero','sum'), dms=('dm','nunique'),
    ).reset_index()
    rm['zp'] = (rm['zero'] / rm['returns'] * 100).round(1)
    rm = rm.sort_values('amount', ascending=False)

    # Hour / Day
    hr = sub.groupby('hour').agg(returns=('rtno','count'), amount=('allocated_net_amount','sum')).reset_index()
    hr = hr[hr['hour'].notna()].copy(); hr['hour'] = hr['hour'].astype(int); hr = hr.sort_values('hour')
    dy = sub.groupby('day').agg(returns=('rtno','count'), amount=('allocated_net_amount','sum')).reset_index()
    dy['day'] = dy['day'].astype(int); dy = dy.sort_values('day')

    za = float(sub[sub['is_zero']]['allocated_net_amount'].sum())
    na = float(hr[hr['hour'].isin([22,23])]['amount'].sum()) if len(hr) else 0.0
    return {
        'stats': {'n': int(sub['rtsono'].nunique()), 'total': float(sub['allocated_net_amount'].sum()),
                  'n_rtu': int(sub['rtuname'].nunique()), 'n_store': int(sub['whs'].nunique()),
                  'n_zero': int(sub['is_zero'].sum()), 'zero_amt': za,
                  'n_so_dup': int(len(so)), 'so_dup_amt': float(so['amount'].sum()),
                  'night_amt': na},
        'rtu':   rec(rtu.head(100)),
        'store': rec(st.head(100)),
        'dm':    rec(dm),
        'rm':    rec(rm),
        'hour':  rec(hr),
        'day':   rec(dy),
        'so':    so_list[:60],
    }

# ── PUSH TO GITHUB ────────────────────────────────────────────────────────────
def push_github():
    try:
        res = subprocess.run(
            ['git', '-C', FOLDER, 'status', '--porcelain', 'fraud_analysis.html', 'fraud_data.json'],
            capture_output=True, text=True)
        if not res.stdout.strip():
            print('  GitHub: no changes — skipped push')
            return
        subprocess.run(['git', '-C', FOLDER, 'add', 'fraud_analysis.html', 'fraud_data.json'], check=True)
        today = datetime.now().strftime('%Y-%m-%d')
        subprocess.run(['git', '-C', FOLDER, 'commit', '-m', f'fraud analysis update {today}'], check=True)
        subprocess.run(['git', '-C', FOLDER, 'push'], check=True)
        print('  GitHub: pushed fraud_analysis.html + fraud_data.json')
    except Exception as e:
        print(f'  GitHub push failed: {e}')


# ── MAIN ──────────────────────────────────────────────────────────────────────
def main():
    print('=' * 60)
    print('  Fraud Analysis Rebuilder')
    print('=' * 60)

    print('[1/5] Loading users & branch mapping ...')
    umap     = load_users()
    branches = load_branches()
    barmap   = load_barcode_map()
    prodmap  = load_product_map()
    print(f'      {len(umap)} users · {len(branches)} branches · {len(barmap)} barcodes · {len(prodmap)} products')

    print('[2/5] Loading returnall.txt ...')
    df = load_returns(umap, branches)
    months = sorted(df["month"].unique())
    print(f'      {len(df):,} rows · months: {", ".join(months)}')

    print('[3/5] Computing store risk ...')
    sr = compute_store_risk(df, branches)
    h = sum(1 for s in sr if s["level"]=="HIGH")
    m = sum(1 for s in sr if s["level"]=="MEDIUM")
    l = sum(1 for s in sr if s["level"]=="LOW")
    print(f'      {len(sr)} stores  HIGH={h}  MEDIUM={m}  LOW={l}')

    print('[4/5] Building analysis data ...')
    out = {"gen": datetime.now().strftime("%Y-%m-%d %H:%M"),
           "months": months, "data": {},
           "sr_count": {"H": h, "M": m, "L": l}}
    out["data"]["ALL"] = build_month(df, barmap, prodmap)
    for mo in months:
        out["data"][mo] = build_month(df[df["month"] == mo], barmap, prodmap)
        print(f'      {mo}: {len(df[df["month"]==mo]):,} rows')

    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False)
    print(f'      fraud_data.json saved ({os.path.getsize(OUT_JSON)//1024} KB)')

    print("[5/5] Injecting into HTML template ...")
    if not os.path.exists(TEMPLATE_FILE):
        print(f"  ERROR: Template not found: {TEMPLATE_FILE}")
        sys.exit(1)
    with open(TEMPLATE_FILE, encoding="utf-8") as f:
        tmpl = f.read()
    html = tmpl.replace("PLACEHOLDER_DATA", json.dumps(out, ensure_ascii=False))
    with open(OUT_HTML, "w", encoding="utf-8") as f:
        f.write(html)
    print(f'      fraud_analysis.html saved ({os.path.getsize(OUT_HTML)//1024} KB)')

    if PUSH:
        push_github()

    print()
    print("=" * 60)
    print("  OK  Fraud Analysis updated!")
    print(f'  Total return: {out["data"]["ALL"]["stats"]["total"]:,.0f} baht')
    print(f'  RT count (distinct): {out["data"]["ALL"]["stats"]["n"]:,}')
    print(f'  Stores (HIGH risk): {h}')
    print("=" * 60)

if __name__ == "__main__":
    main()
