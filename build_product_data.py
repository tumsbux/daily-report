#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_product_data.py — Product Analysis Data Builder
Streams fact_sales.sql, joins dim_product + dim_branch
Outputs product_data.json for product_dashboard.html
"""

import re, json, os, sys, subprocess
from collections import defaultdict

FOLDER      = os.path.dirname(os.path.abspath(__file__))
SALES_SQL   = os.path.join(FOLDER, 'data-lake_fact_sales.sql')
PRODUCT_SQL = os.path.join(FOLDER, 'data-lake_dim_product.sql')
BARCODE_SQL = os.path.join(FOLDER, 'data-lake_dim_item_barcode.sql')
BRANCH_SQL  = os.path.join(FOLDER, 'data-lake_dim_branch.sql')
OUT_FILE    = os.path.join(FOLDER, 'product_data.json')

TARGET_MONTHS = {'2026-05', '2025-05'}   # May 2026 vs May 2025

def valid_store(code):
    try:    return int(code) <= 500
    except: return False

# ── 1. Load dim tables from cache (fast) or SQL (slow) ───────────────────
CACHE_FILE = os.path.join(FOLDER, 'dim_cache.json')
if os.path.exists(CACHE_FILE):
    print('[1/4] Loading dims from cache ...')
    import json as _json
    _cache = _json.load(open(CACHE_FILE, encoding='utf-8'))
    products = _cache['products']
    barcodes = _cache['barcodes']
    branches = _cache['branches']
    print(f'   {len(products):,} products | {len(barcodes):,} barcodes | {len(branches):,} branches (cached)')
else:
    raise FileNotFoundError('dim_cache.json not found — run pre-cache step first')

# ── 3. Stream fact_sales ──────────────────────────────────────────────────
import argparse as _ap
_parser = _ap.ArgumentParser()
_parser.add_argument('--chunk', type=int, default=0)
_parser.add_argument('--total-chunks', type=int, default=4)
_args = _parser.parse_known_args()[0]
CHUNK = _args.chunk
TOTAL_CHUNKS = _args.total_chunks
print('[3/4] Streaming fact_sales via grep pipe (May 2025 + May 2026) ...')

agg = defaultdict(lambda: defaultdict(lambda: defaultdict(lambda: {'qty': 0.0, 'sales': 0.0, 'cost': 0.0})))

# Chunk support: --chunk 0 = full file, --chunk 1..N = Nth of N parts
FILE_SIZE     = os.path.getsize(SALES_SQL)
BLOCK         = 1 << 20   # 1MB blocks
TOTAL_BLOCKS  = FILE_SIZE // BLOCK
CHUNK_BLOCKS  = TOTAL_BLOCKS // TOTAL_CHUNKS
PROGRESS_FILE = os.path.join(FOLDER, 'product_progress.json')

# Load saved partial agg if resuming any chunk after the first
if CHUNK > 1 and os.path.exists(PROGRESS_FILE):
    import json as _j2
    _saved = _j2.load(open(PROGRESS_FILE, encoding='utf-8'))
    for ym, prods in _saved.items():
        for iprod, stores in prods.items():
            for store, vals in stores.items():
                agg[ym][iprod][store]['qty']   += vals['qty']
                agg[ym][iprod][store]['sales'] += vals['sales']
                agg[ym][iprod][store]['cost']  += vals['cost']
    print(f'   Loaded partial progress from chunk {CHUNK-1}')

lines_read = 0; rows_matched = 0; skipped = 0

grep_pattern = '|'.join(TARGET_MONTHS)
grep_cmd = ['grep', '-E', grep_pattern]

if CHUNK == 0:  # full file
    proc = subprocess.Popen(['grep', '-E', grep_pattern, SALES_SQL],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=1<<22)
    src = proc.stdout
else:
    skip_blocks  = (CHUNK - 1) * CHUNK_BLOCKS
    if CHUNK == TOTAL_CHUNKS:
        dd_cmd = ['dd', f'if={SALES_SQL}', f'skip={skip_blocks}', 'bs=1M', 'status=none']
    else:
        dd_cmd = ['dd', f'if={SALES_SQL}', f'skip={skip_blocks}', f'count={CHUNK_BLOCKS}', 'bs=1M', 'status=none']
    print(f'   dd: skip={skip_blocks} blocks, count={CHUNK_BLOCKS if CHUNK < TOTAL_CHUNKS else "to-end"} blocks')
    dd_proc   = subprocess.Popen(dd_cmd,   stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    grep_proc = subprocess.Popen(grep_cmd, stdin=dd_proc.stdout,
                                 stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=1<<22)
    dd_proc.stdout.close()
    src = grep_proc.stdout

with src:
    for raw in src:
        line = raw.decode('utf-8', errors='replace')
        if not line.startswith('INSERT'):
            continue
        lines_read += 1
        v_start = line.find(' VALUES (')
        if v_start == -1:
            continue
        vals_block = line[v_start + 8:]
        _tm0, _tm1 = tuple(TARGET_MONTHS)  # fast refs
        for rec in vals_block.split('),('):
            # Fast pre-filter: skip records that don't contain a target month
            if _tm0 not in rec and _tm1 not in rec:
                continue
            try:
                p = rec.split("'")
                if len(p) < 24:
                    continue
                ym = p[7][:7]
                if ym not in TARGET_MONTHS:
                    continue
                stype = p[23]
                if stype == 'C':
                    continue
                store = p[13]
                if not valid_store(store):
                    skipped += 1; continue
                iprod = p[5]
                n1 = p[10].split(',')
                cost  = float(n1[8])
                n2 = p[18].split(',')
                sales = float(n2[2])
                qty   = float(n1[1]) - float(n1[2])
            except (IndexError, ValueError):
                continue
            agg[ym][iprod][store]['qty']   += qty
            agg[ym][iprod][store]['sales'] += sales
            agg[ym][iprod][store]['cost']  += cost
            rows_matched += 1
        if lines_read % 50 == 0:
            sys.stdout.write(f'\r   chunk{CHUNK} lines: {lines_read} | rows: {rows_matched:,}   ')
            sys.stdout.flush()

if CHUNK == 0:
    proc.wait()
else:
    grep_proc.wait(); dd_proc.wait()

print(f'\n   Done. {rows_matched:,} rows aggregated, {skipped:,} skipped')

# After intermediate chunks, save partial progress and exit
if CHUNK > 0 and CHUNK < TOTAL_CHUNKS:
    import json as _j3
    _out = {ym: {ip: dict(stores) for ip, stores in prods.items()}
            for ym, prods in agg.items()}
    _j3.dump(_out, open(PROGRESS_FILE, 'w', encoding='utf-8'), ensure_ascii=False)
    print(f'   Saved partial progress → product_progress.json')
    sys.exit(0)

# ── 4. Build output JSON ──────────────────────────────────────────────────
print('[4/4] Building product_data.json ...')

# Collapse: for each product, sum across all stores per month
prod_month = defaultdict(lambda: {'26': {'qty':0,'sales':0,'cost':0},
                                   '25': {'qty':0,'sales':0,'cost':0}})

for iprod, store_data in agg['2026-05'].items():
    for store, vals in store_data.items():
        prod_month[iprod]['26']['qty']   += vals['qty']
        prod_month[iprod]['26']['sales'] += vals['sales']
        prod_month[iprod]['26']['cost']  += vals['cost']

for iprod, store_data in agg['2025-05'].items():
    for store, vals in store_data.items():
        prod_month[iprod]['25']['qty']   += vals['qty']
        prod_month[iprod]['25']['sales'] += vals['sales']
        prod_month[iprod]['25']['cost']  += vals['cost']

# Sort by May 2026 sales desc, keep top 300
sorted_prods = sorted(prod_month.items(), key=lambda x: x[1]['26']['sales'], reverse=True)[:300]

# Also build RM/DM/Store breakdown for top 100 products
top100_codes = {iprod for iprod, _ in sorted_prods[:100]}
store_breakdown = defaultdict(lambda: defaultdict(lambda: {'qty':0,'sales':0}))
for ym, prods in agg.items():
    sfx = '26' if ym == '2026-05' else '25'
    for iprod in top100_codes:
        if iprod in prods:
            for store, vals in prods[iprod].items():
                store_breakdown[iprod][store + ':' + sfx]['qty']   += vals['qty']
                store_breakdown[iprod][store + ':' + sfx]['sales'] += vals['sales']

# Category totals
cat_tot = defaultdict(lambda: {'qty26':0,'sales26':0,'qty25':0,'sales25':0})
for iprod, data in prod_month.items():
    info = products.get(iprod, {})
    grp  = info.get('group', '') or 'ไม่ระบุ'
    cat_tot[grp]['qty26']   += data['26']['qty']
    cat_tot[grp]['sales26'] += data['26']['sales']
    cat_tot[grp]['qty25']   += data['25']['qty']
    cat_tot[grp]['sales25'] += data['25']['sales']

# RM totals per category
rm_cat = defaultdict(lambda: defaultdict(lambda: {'sales26':0,'sales25':0}))

output = {
    'generated': __import__('datetime').date.today().isoformat(),
    'month26': '2026-05',
    'month25': '2025-05',
    'products': [],
    'categories': [],
    'rm_list': sorted({b['rm'] for b in branches.values() if b['rm']}),
    'dm_list': sorted({b['dm'] for b in branches.values() if b['dm']}),
    'store_info': {k: {'name': v['name'], 'dm': v['dm'], 'rm': v['rm']} for k, v in branches.items()},
}

for rank, (iprod, data) in enumerate(sorted_prods, 1):
    info  = products.get(iprod, {'name': iprod, 'brand': '', 'group': '', 'type': ''})
    s26   = data['26']['sales']
    s25   = data['25']['sales']
    q26   = data['26']['qty']
    q25   = data['25']['qty']
    gp26  = s26 - data['26']['cost'] if s26 else 0
    yoy_s = round((s26 / s25 - 1) * 100, 1) if s25 else None
    yoy_q = round((q26 / q25 - 1) * 100, 1) if q25 else None
    gp_pct= round(gp26 / s26 * 100, 1) if s26 else 0
    output['products'].append({
        'rank': rank,
        'iprod': iprod,
        'barcode': barcodes.get(iprod, iprod),
        'name':  info.get('name', '')[:40],
        'brand': info.get('brand', '')[:25],
        'group': info.get('group', '')[:30],
        'type':  info.get('type', '')[:25],
        'q26': round(q26, 0),
        'q25': round(q25, 0),
        'q_yoy': yoy_q,
        's26': round(s26, 0),
        's25': round(s25, 0),
        's_yoy': yoy_s,
        'gp26': round(gp26, 0),
        'gp_pct': gp_pct,
    })

# Category list sorted by May 2026 sales
for grp, vals in sorted(cat_tot.items(), key=lambda x: x[1]['sales26'], reverse=True)[:30]:
    s26 = vals['sales26']; s25 = vals['sales25']
    output['categories'].append({
        'group':   grp,
        'sales26': round(s26, 0),
        'sales25': round(s25, 0),
        'qty26':   round(vals['qty26'], 0),
        'qty25':   round(vals['qty25'], 0),
        's_yoy': round((s26/s25-1)*100,1) if s25 else None,
    })

with open(OUT_FILE, 'w', encoding='utf-8') as f:
    json.dump(output, f, ensure_ascii=False, separators=(',', ':'))

size_kb = os.path.getsize(OUT_FILE) // 1024
print(f'   Saved product_data.json ({size_kb:,} KB)')
print(f'   Products: {len(output["products"])}  |  Categories: {len(output["categories"])}')
print('Done!')
