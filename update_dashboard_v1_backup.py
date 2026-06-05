#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
update_dashboard.py -- Daily Sales Dashboard Updater
"""

import csv, json, re, os, glob, sys, argparse, subprocess, shutil, tempfile, uuid
from collections import defaultdict
from datetime import date

# CONFIG
FOLDER         = os.path.dirname(os.path.abspath(__file__))
DASHBOARD_FILE = os.path.join(FOLDER, 'sales_dashboard_v8.html')
INDEX_FILE     = os.path.join(FOLDER, 'index.html')
TARGET_FILE    = os.path.join(FOLDER, 'target.txt')
RETURNS_SQL    = os.path.join(FOLDER, 'data-lake_fact_returns.sql')

# Auto-detect current month from today's date
_today_for_month = date.today()
YEAR           = str(_today_for_month.year)
MONTH          = f'{_today_for_month.month:02d}'
MONTH_KEY      = YEAR + '-' + MONTH
import calendar as _cal
DAYS_IN_MONTH  = _cal.monthrange(int(YEAR), int(MONTH))[1]
MONTH_NAME     = _today_for_month.strftime('%B %Y')
_TH_MONTHS = ['','มกราคม','กุมภาพันธ์','มีนาคม','เมษายน','พฤษภาคม','มิถุนายน',
               'กรกฎาคม','สิงหาคม','กันยายน','ตุลาคม','พฤศจิกายน','ธันวาคม']
_TH_MONTHS_SHORT = ['','ม.ค.','ก.พ.','มี.ค.','เม.ย.','พ.ค.','มิ.ย.',
                    'ก.ค.','ส.ค.','ก.ย.','ต.ค.','พ.ย.','ธ.ค.']
MONTH_NAME_TH  = _TH_MONTHS[_today_for_month.month] + ' ' + YEAR

DB_CONFIG_FILE = os.path.join(FOLDER, 'db_config.json')
REPO_DIR       = os.path.join(tempfile.gettempdir(), f'dlr-{uuid.uuid4().hex[:8]}')

# Load GitHub token from db_config.json (never hardcode secrets in source)
def _read_github_token():
    try:
        with open(DB_CONFIG_FILE, encoding='utf-8') as _f:
            return json.load(_f).get('github_token', '')
    except Exception:
        return ''

def _read_github_repo():
    try:
        with open(DB_CONFIG_FILE, encoding='utf-8') as _f:
            return json.load(_f).get('github_repo', 'tumsbux/daily-report')
    except Exception:
        return 'tumsbux/daily-report'

GITHUB_TOKEN = _read_github_token()
GITHUB_REPO  = _read_github_repo()
GITHUB_URL   = 'https://' + GITHUB_TOKEN + '@github.com/' + GITHUB_REPO + '.git'

# HELPERS
def valid_store(code):
    try:    return int(code) <= 500
    except: return False

def extract_json(html):
    marker = 'const D='
    start  = html.index(marker) + len(marker)
    depth = 0; i = start
    while i < len(html):
        if html[i] == '{':  depth += 1
        elif html[i] == '}':
            depth -= 1
            if depth == 0: end = i + 1; break
        i += 1
    return json.loads(html[start:end]), start, end

def safe_pct(num, denom, decimals=1):
    try:    return round(num / denom * 100, decimals) if denom else None
    except: return None

def safe_yoy(new_val, old_val, decimals=1):
    try:    return round((new_val / old_val - 1) * 100, decimals) if old_val else None
    except: return None

def _load_db_config():
    if not os.path.exists(DB_CONFIG_FILE):
        return None
    with open(DB_CONFIG_FILE, encoding='utf-8') as f:
        return json.load(f)

def _query_returns_mtd(cfg, year, month):
    """Query fact_returns for MTD return amount per store.
    Returns (store_ret_dict, total_amt, total_bills, max_day)."""
    import mysql.connector
    next_mo = (f'{int(year)+1}-01-01' if int(month) == 12
               else f'{year}-{int(month)+1:02d}-01')
    conn = mysql.connector.connect(
        host=cfg['host'], port=cfg.get('port', 3306),
        user=cfg['user'], password=cfg['password'],
        database=cfg.get('database', 'data-lake'),
        connection_timeout=30, charset='utf8mb4'
    )
    cursor = conn.cursor(dictionary=True)
    cursor.execute("""
        SELECT warehouse_code AS whs,
               SUM(allocated_net_amount) AS ret_amount,
               COUNT(DISTINCT rtsono)    AS ret_bills,
               MAX(DAY(return_date))     AS max_day
        FROM fact_returns
        WHERE rtstatus = 'U'
          AND return_date BETWEEN %s AND CURDATE()
          AND warehouse_code NOT IN ('901', '999')
        GROUP BY warehouse_code
    """, (f'{year}-{month}-01',))
    rows = cursor.fetchall()
    cursor.close(); conn.close()
    result = {}; total_amt = 0.0; total_bills = 0; max_day = 0
    for r in rows:
        raw = str(r['whs'] or '').strip()
        if not raw: continue
        amt   = float(r['ret_amount'] or 0)
        bills = int(r['ret_bills']   or 0)
        d     = int(r['max_day']     or 0)
        total_amt += amt; total_bills += bills
        if d > max_day: max_day = d
        result[raw] = amt
        try: result[str(int(raw))]  = amt
        except: pass
        try: result[raw.zfill(3)]   = amt
        except: pass
    return result, total_amt, total_bills, max_day

def _query_txn_mtd(cfg, year, month):
    """Query fact_sales for distinct SO count per store MTD (transaction count).
    fact_sales columns: sotowhs (store), sodate (date), solinetype, sono (order no)."""
    import mysql.connector
    conn = mysql.connector.connect(
        host=cfg['host'], port=cfg.get('port', 3306),
        user=cfg['user'], password=cfg['password'],
        database=cfg.get('database', 'data-lake'),
        connection_timeout=30, charset='utf8mb4'
    )
    cursor = conn.cursor(dictionary=True)
    cursor.execute("""
        SELECT sotowhs AS whs,
               COUNT(DISTINCT sono) AS txn_count
        FROM fact_sales
        WHERE sodate >= %s AND sodate < %s
          AND solinetype NOT IN ('C', 'R')
          AND sotowhs NOT IN ('901', '999', '0901', '0999')
        GROUP BY sotowhs
    """, (f'{year}-{month}-01',
          f'{int(year)+1}-01-01' if int(month) == 12 else f'{year}-{int(month)+1:02d}-01'))
    rows = cursor.fetchall()
    cursor.close(); conn.close()
    # Return both raw and padded keys so whichever format the dashboard uses will match
    result = {}
    for r in rows:
        raw = str(r['whs'] or '').strip()
        if not raw: continue
        cnt = int(r['txn_count'] or 0)
        result[raw] = cnt
        try: result[str(int(raw))] = cnt   # unpadded e.g. '1'
        except: pass
        try: result[raw.zfill(3)] = cnt    # padded   e.g. '001'
        except: pass
    return result

def _query_fact_sales_may25(cfg):
    """Query fact_sales for full previous-year same-month per store.
    Used to set authoritative s25_may (YoY baseline) from fact_sales instead of whsddpact.
    NOTE: name kept 'may25' for backward compat; query is dynamic (YEAR-1, current MONTH)."""
    import mysql.connector
    _y_prev = int(YEAR) - 1
    _m_cur  = int(MONTH)
    conn = mysql.connector.connect(
        host=cfg['host'], port=cfg.get('port', 3306),
        user=cfg['user'], password=cfg['password'],
        database=cfg.get('database', 'data-lake'),
        connection_timeout=60, charset='utf8mb4'
    )
    cursor = conn.cursor(dictionary=True)
    cursor.execute(f"""
        SELECT sotowhs AS whs,
               SUM(net_sales_amt)   AS sales25,
               COUNT(DISTINCT sono) AS txn25
        FROM fact_sales
        WHERE YEAR(sodate) = {_y_prev} AND MONTH(sodate) = {_m_cur}
          AND solinetype NOT IN ('C', 'R')
          AND sotowhs REGEXP '^[0-9]+$'
          AND CAST(sotowhs AS UNSIGNED) BETWEEN 1 AND 500
        GROUP BY sotowhs
    """)
    rows = cursor.fetchall()
    cursor.close(); conn.close()
    result = {}
    for r in rows:
        raw = str(r['whs'] or '').strip()
        if not raw: continue
        entry = {
            's25':  float(r['sales25'] or 0),
            'txn25': int(r['txn25']   or 0),
        }
        result[raw] = entry
        try: result[str(int(raw))] = entry
        except: pass
        try: result[raw.zfill(3)] = entry
        except: pass
    return result


def _query_fact_sales_mtd(cfg, year, month, days_elapsed):
    """Query fact_sales directly for MTD net_sales_amt + total_cost per store.
    This is the authoritative sales source — matches the mobile app exactly.
    Also returns the actual max day found in fact_sales (may lag DAYS_ELAPSED by ~3 days)."""
    import mysql.connector
    conn = mysql.connector.connect(
        host=cfg['host'], port=cfg.get('port', 3306),
        user=cfg['user'], password=cfg['password'],
        database=cfg.get('database', 'data-lake'),
        connection_timeout=60, charset='utf8mb4'
    )
    cursor = conn.cursor(dictionary=True)
    end_date = f'{year}-{month}-{int(days_elapsed):02d}'
    cursor.execute("""
        SELECT sotowhs AS whs,
               SUM(net_sales_amt)          AS sales_amt,
               SUM(COALESCE(total_cost,0)) AS cost_amt,
               COUNT(DISTINCT sono)        AS txn_count,
               MAX(DAY(sodate))            AS max_day_seen
        FROM fact_sales
        WHERE sodate BETWEEN %s AND %s
          AND solinetype NOT IN ('C', 'R')
          AND sotowhs REGEXP '^[0-9]+$'
          AND CAST(sotowhs AS UNSIGNED) BETWEEN 1 AND 500
        GROUP BY sotowhs
    """, (f'{year}-{month}-01', end_date))
    rows = cursor.fetchall()
    cursor.close(); conn.close()
    result = {}; fact_max_day = 0
    for r in rows:
        raw = str(r['whs'] or '').strip()
        if not raw: continue
        d = int(r.get('max_day_seen') or 0)
        if d > fact_max_day: fact_max_day = d
        entry = {
            'sales': float(r['sales_amt'] or 0),
            'cost':  float(r['cost_amt']  or 0),
            'txn':   int(r['txn_count']   or 0),
        }
        result[raw] = entry
        try: result[str(int(raw))] = entry
        except: pass
        try: result[raw.zfill(3)] = entry
        except: pass
    return result, fact_max_day


def _query_whsdd(cfg, year, month):
    """Query MYPOS2018_CENTER.whsdd for daily store targets + actuals.
    Returns list of dicts with normalised string values (same shape as target.txt rows)."""
    import mysql.connector
    conn = mysql.connector.connect(
        host=cfg['host'], port=cfg.get('port', 3306),
        user=cfg['user'], password=cfg['password'],
        connection_timeout=30, charset='utf8mb4'
    )
    cursor = conn.cursor(dictionary=True)
    cursor.execute("""
        SELECT whsddno, whsddyyyy, whsddmm, whsdddd,
               whsddptar, whsddpact,
               whsddpnetamt, whsddpnetcost
        FROM MYPOS2018_CENTER.whsdd
        WHERE whsddyyyy = %s AND whsddmm = %s
    """, (int(year), int(month)))
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    result = []
    for r in rows:
        result.append({
            'whsddno':       str(r['whsddno']),
            'whsddyyyy':     str(r['whsddyyyy']),
            'whsddmm':       str(r['whsddmm']).zfill(2),
            'whsdddd':       str(r['whsdddd']).zfill(2),
            'whsddptar':     float(r.get('whsddptar')  or 0),
            'whsddpact':     float(r.get('whsddpact')  or 0),
            'whsddpnetamt':  float(r.get('whsddpnetamt')  or 0),
            'whsddpnetcost': float(r.get('whsddpnetcost') or 0),
            'whsddtotdoc':   0,   # not in whsdd — txn count comes from fact_sales
        })
    return result

# ARGUMENTS
parser = argparse.ArgumentParser()
parser.add_argument('--day', type=int, default=None)
args = parser.parse_args()

today = date.today()
if args.day:
    DAYS_ELAPSED = args.day
else:
    # Auto-detect from fact_sales — handles month-boundary correctly
    # (e.g. June 1: today.day-1=0 but fact_sales still has May 31 data)
    _db_cfg_early = _load_db_config()
    _auto_day = 0
    if _db_cfg_early:
        try:
            import mysql.connector as _mc
            _c = _mc.connect(
                host=_db_cfg_early['host'], port=_db_cfg_early.get('port', 3306),
                user=_db_cfg_early['user'], password=_db_cfg_early['password'],
                database=_db_cfg_early.get('database', 'data-lake'),
                connection_timeout=30, charset='utf8mb4')
            _cur = _c.cursor()
            _cur.execute("""
                SELECT MAX(DAY(sodate)) FROM fact_sales
                WHERE YEAR(sodate)=%s AND MONTH(sodate)=%s
                  AND solinetype NOT IN ('C','R')
                  AND sotowhs REGEXP '^[0-9]+$'
                  AND CAST(sotowhs AS UNSIGNED) BETWEEN 1 AND 500
            """, (int(YEAR), int(MONTH)))
            _row = _cur.fetchone()
            _cur.close(); _c.close()
            if _row and _row[0]: _auto_day = int(_row[0])
        except Exception as _e:
            print('  WARN: fact_sales day auto-detect failed: %s' % _e)
    DAYS_ELAPSED = _auto_day if _auto_day > 0 else max(1, today.day - 1)
    if _auto_day > 0:
        print('  Auto-detected max day from fact_sales: %d' % DAYS_ELAPSED)

print('=' * 62)
print('  Sales Dashboard Updater -- Day %d/%d %s' % (DAYS_ELAPSED, DAYS_IN_MONTH, MONTH_NAME))
print('=' * 62)

# STEP 1: Load daily targets from MYPOS2018_CENTER.whsdd (fallback: target.txt)
print('\n[1/7] Loading targets from MySQL (MYPOS2018_CENTER.whsdd) ...')

store_target_days = defaultdict(dict)
store_tar_monthly = defaultdict(float)
store_tar_mtd     = defaultdict(float)
store_txn_mtd     = defaultdict(int)
day_totals        = defaultdict(float)

_db_cfg     = _load_db_config()
_whsdd_rows = None
_whsdd_src  = 'target.txt (fallback)'

if _db_cfg:
    try:
        _whsdd_rows = _query_whsdd(_db_cfg, YEAR, MONTH)
        _whsdd_src  = 'MySQL MYPOS2018_CENTER.whsdd'
        print('    MySQL: %d store-day rows loaded' % len(_whsdd_rows))
    except Exception as _we:
        print('    MySQL whsdd error: %s -- falling back to target.txt' % _we)

if not _whsdd_rows:
    if not os.path.exists(TARGET_FILE):
        print('    ERROR: MySQL unavailable AND target.txt not found.')
        print('    ABORT: cannot update dashboard without data. Existing file preserved.')
        raise SystemExit(0)   # exit cleanly — do NOT overwrite the existing file
    else:
        with open(TARGET_FILE, encoding='utf-8') as _tf:
            _whsdd_rows = list(csv.DictReader(_tf, delimiter='\t'))
        print('    Fallback: target.txt (%d rows)' % len(_whsdd_rows))

for row in _whsdd_rows:
    if str(row.get('whsddyyyy', '')) != YEAR: continue
    if str(row.get('whsddmm', '')).zfill(2) != MONTH: continue
    no  = str(row.get('whsddno', ''))
    if not valid_store(no): continue
    day = int(float(str(row.get('whsdddd') or 0)))
    if day == 0: continue
    tar = float(row.get('whsddptar') or 0)
    # whsddpact may lag 1-2 days; fall back to whsddpnetamt so recent days are recognised as finalized
    act = float(row.get('whsddpact') or row.get('whsddpnetamt') or 0)
    txn = int(float(row.get('whsddtotdoc') or 0))
    store_tar_monthly[no] += tar
    if day <= DAYS_ELAPSED:
        store_tar_mtd[no] += tar
        day_totals[day]   += act
        if act > 0:
            store_target_days[no][day] = act
            store_txn_mtd[no]         += txn

# Supplement store_txn_mtd from fact_sales (whsdd has no txn count column)
if _db_cfg:
    try:
        _txn_map = _query_txn_mtd(_db_cfg, YEAR, MONTH)
        for _whs, _cnt in _txn_map.items():
            store_txn_mtd[_whs] = _cnt
        print('    MySQL fact_sales txn: %d stores loaded' % len(_txn_map))
    except Exception as _te:
        print('    WARNING: txn query failed: %s' % _te)

finalized_days   = sorted(d for d in range(1, DAYS_ELAPSED + 1) if day_totals[d] > 0)
unfinalized_days = sorted(d for d in range(1, DAYS_ELAPSED + 1) if d not in finalized_days)
max_fin_day      = max(finalized_days) if finalized_days else 0

if finalized_days:
    print('    Finalized (%s): days %d-%d' % (_whsdd_src, finalized_days[0], max_fin_day))
else:
    print('    No finalized days found in %s' % _whsdd_src)
if unfinalized_days:
    print('    Need factXX.txt for : days %s' % unfinalized_days)
else:
    print('    Data fully current -- no factXX.txt needed')

store_target_sales = {no: sum(store_target_days[no].values()) for no in store_target_days}

# STEP 1b: Query fact_sales directly (authoritative source — matches mobile app)
print('\n[1b] Querying fact_sales MTD (days 1-%d) for exact sales amounts ...' % DAYS_ELAPSED)
_fact_sales_mtd = {}   # {store_code: {sales, cost, txn}}  — primary source
_fact_max_day   = 0    # actual max day found in fact_sales
if _db_cfg:
    try:
        _fact_sales_mtd, _fact_max_day = _query_fact_sales_mtd(_db_cfg, YEAR, MONTH, DAYS_ELAPSED)
        # Count unique stores only (dict has 2-3 keys per store for code format matching)
        _unique_fs = {id(v): v for v in _fact_sales_mtd.values()}
        _fs_total  = sum(v['sales'] for v in _unique_fs.values())
        _fs_stores = len(_unique_fs)
        print('    fact_sales: %d stores | ฿%s MTD gross | max day: %d' % (
            _fs_stores, format(int(_fs_total), ','), _fact_max_day))
    except Exception as _fse:
        print('    WARNING: fact_sales query failed: %s -- will use whsddpact fallback' % _fse)
else:
    print('    No DB config -- skipping fact_sales query')

# FACT_DAYS = actual days with data in fact_sales (used as denominator for rates).
# DAYS_ELAPSED is the query window and displayed day number.
# fact_sales lags ~3 days, so FACT_DAYS < DAYS_ELAPSED is normal.
FACT_DAYS = _fact_max_day if _fact_max_day > 0 else DAYS_ELAPSED
if FACT_DAYS != DAYS_ELAPSED:
    print('    ⚠ fact_sales covers days 1-%d (not 1-%d) — using %d for rate/projection' % (
        FACT_DAYS, DAYS_ELAPSED, FACT_DAYS))

# Query previous-year same-month from fact_sales — authoritative YoY baseline (replaces whsddpact 2025)
_fact_sales_25 = {}
if _db_cfg:
    try:
        _fact_sales_25 = _query_fact_sales_may25(_db_cfg)
        _fs25_total = sum(v['s25'] for v in _fact_sales_25.values())
        print('    fact_sales %s/%s: %d stores | ฿%s (YoY baseline)' % (
            str(int(YEAR) - 1), MONTH, len(_fact_sales_25), format(int(_fs25_total), ',')))
    except Exception as _f25e:
        print('    WARNING: fact_sales YoY baseline query failed: %s -- keeping existing s25_may' % _f25e)

# STEP 2: factXX.txt
print('\n[2/7] Reading factXX.txt for unfinalized days ...')

# Build day_file_map by peeking at actual sodate inside each fact file
# (ETL sometimes names files by export date, not data date)
# Priority: clean (no NUL) > more rows > newer mtime
day_file_map = {}  # {day: (is_clean, row_count, fpath)}
for fpath in glob.glob(os.path.join(FOLDER, 'fact*.txt')):
    bn = os.path.basename(fpath)
    if not re.match(r'fact\d{1,2}\.txt$', bn, re.IGNORECASE):
        continue
    try:
        with open(fpath, 'rb') as _rb:
            _has_nul = b'\x00' in _rb.read(65536)  # sample first 64KB
        _is_clean = not _has_nul
        with open(fpath, encoding='utf-8', errors='replace') as _f:
            _cleaned = (_l.replace('\x00', '') for _l in _f)
            _reader = csv.DictReader(_cleaned, delimiter='\t')
            if 'sodate' not in (_reader.fieldnames or []):
                print('    SKIP %s -- no sodate column (not a sales file)' % bn)
                continue
            _row_count = 0
            _actual_day = None
            for _row in _reader:
                _sodate = (_row.get('sodate') or '')[:10]
                if _sodate.startswith(MONTH_KEY):
                    if _actual_day is None:
                        _actual_day = int(_sodate.split('-')[2])
                    _row_count += 1
            if _actual_day is None:
                continue
            _cur = day_file_map.get(_actual_day)
            # Prefer: clean over NUL, then more rows
            if (_cur is None or
                    (_is_clean and not _cur[0]) or
                    (_is_clean == _cur[0] and _row_count > _cur[1])):
                if _cur:
                    print('    DUPLICATE day %d: prefer %s(%s,%d rows) over %s(%s,%d rows)' % (
                        _actual_day, bn,
                        'clean' if _is_clean else 'NUL', _row_count,
                        os.path.basename(_cur[2]),
                        'clean' if _cur[0] else 'NUL', _cur[1]))
                day_file_map[_actual_day] = (_is_clean, _row_count, fpath)
    except Exception as _e:
        print('    SKIP %s -- error: %s' % (bn, _e))

store_fact_sales = defaultdict(float)
store_fact_txn   = defaultdict(set)
loaded_fact_days = []

for day in sorted(unfinalized_days):
    entry = day_file_map.get(day)
    if not entry:
        print('    WARNING: fact file for day %d not found' % day)
        continue
    fpath = entry[2]
    with open(fpath, encoding='utf-8', errors='replace') as f:
        cleaned = (line.replace('\x00', '') for line in f)
        reader = csv.DictReader(cleaned, delimiter='\t')
        for row in reader:
            whs  = row.get('sotowhs', '')
            if not valid_store(whs): continue
            if row.get('soretflag', '') == 'Y': continue
            amt  = float(row.get('net_sales_amt') or 0)
            sono = row.get('sono', '')
            store_fact_sales[whs] += amt
            store_fact_txn[whs].add((day, sono))
    loaded_fact_days.append(day)

if loaded_fact_days:
    print('    Loaded fact files for days : %s' % loaded_fact_days)
    print('    Fact sales total           : %s baht' % format(int(sum(store_fact_sales.values())), ','))
else:
    print('    No unfinalized days -- nothing to load from fact files')

# STEP 3: Returns — primary: MySQL fact_returns; fallback: static files
print('\n[3/7] Reading returns ...')
store_ret = defaultdict(float)
_ret_from_mysql = False

if _db_cfg:
    try:
        _ret_map, _ret_total, _ret_bills, _ret_maxday = _query_returns_mtd(_db_cfg, YEAR, MONTH)
        for _whs, _amt in _ret_map.items():
            store_ret[_whs] = _amt
        print('    MySQL fact_returns (May %s): %s baht | %d bills | days 1-%d' % (
            YEAR, format(int(_ret_total), ','), _ret_bills, _ret_maxday))
        _ret_from_mysql = True
    except Exception as _re:
        print('    MySQL returns error: %s -- falling back to static files' % _re)

if not _ret_from_mysql:
    if os.path.exists(RETURNS_SQL):
        with open(RETURNS_SQL, encoding='utf-8') as f:
            content = f.read()
        pat = re.compile(
            r"\('([^']+)','([^']*?)','([^']+)','([^']+)','([^']+)',"
            r"'([^']*?)','([^']+)','([^']+)',([^,]+),([^,]+),([^,]+),([^,]+),"
            r"'([^']+)','([^']+)'\)")
        sql_ret_total = 0.0; sql_max_day = 0
        for m in pat.findall(content):
            whs = m[7]; ret_mth = m[4][:7]; alloc = float(m[11])
            if ret_mth == MONTH_KEY and valid_store(whs):
                store_ret[whs] += alloc; sql_ret_total += alloc
                day_d = int(m[4][8:10])
                if day_d > sql_max_day: sql_max_day = day_d
        print('    fact_returns.sql (May %s): %s baht (days 1-%d)' % (
            YEAR, format(int(sql_ret_total), ','), sql_max_day))
    else:
        sql_max_day = 0
        print('    WARNING: fact_returns.sql not found')

    ret_files_loaded = []
    for rfpath in sorted(glob.glob(os.path.join(FOLDER, 'return*.txt'))):
        bn = os.path.basename(rfpath)
        m  = re.match(r'return(\d{1,2})\.txt$', bn, re.IGNORECASE)
        if not m: continue
        day_num = int(m.group(1))
        if day_num > DAYS_ELAPSED: continue
        if day_num <= sql_max_day: continue
        with open(rfpath, encoding='utf-8') as f:
            first_line = f.readline()
            sep = ',' if ',' in first_line and '\t' not in first_line else '\t'
            f.seek(0)
            reader = csv.DictReader(f, delimiter=sep)
            for row in reader:
                ret_date = (row.get('return_date') or '')[:7]
                if ret_date != MONTH_KEY: continue
                whs = row.get('warehouse_code', '')
                if not valid_store(whs): continue
                store_ret[whs] += float(row.get('allocated_net_amount') or 0)
        ret_files_loaded.append(bn)
    if ret_files_loaded:
        print('    returnXX.txt loaded        : %s' % ', '.join(ret_files_loaded))

_ret_display = int(_ret_total if _ret_from_mysql else sum(store_ret.values()))
print('    Combined returns (May)     : %s baht' % format(_ret_display, ','))

# STEP 4: Load existing dashboard
print('\n[4/7] Loading existing dashboard ...')
with open(DASHBOARD_FILE, encoding='utf-8') as f:
    html = f.read()
D, json_start, json_end = extract_json(html)
print('    %d stores / %d DMs / %d RMs loaded' % (len(D['stores']), len(D['dm']), len(D['rm'])))

# STEP 5: Update stores
print('\n[5/7] Updating stores ...')
_used_fact_sales = 0; _used_whsdd_fallback = 0
for s in D['stores']:
    code = s['code']
    ret  = store_ret.get(code, 0.0)
    tar_mo  = store_tar_monthly.get(code, s.get('target', 0))
    tar_mtd = store_tar_mtd.get(code, s.get('mtd_target', 0))

    # ── Sales source: fact_sales (primary) or whsddpact+factXX (fallback) ──
    fs = _fact_sales_mtd.get(code)
    if fs:
        # PRIMARY: fact_sales — authoritative, matches mobile app
        gross_sales = fs['sales']
        net_sales   = gross_sales - ret
        cost_mtd    = fs['cost']
        gp_mtd_amt  = gross_sales - cost_mtd - ret   # GP on net sales
        gp_pct      = round(gp_mtd_amt / net_sales * 100, 2) if net_sales else s.get('gp_pct', 33.0)
        txn_mtd     = fs['txn']
        _used_fact_sales += 1
    else:
        # FALLBACK: whsddpact + factXX.txt (for stores not in fact_sales)
        sales_target = store_target_sales.get(code, 0.0)
        sales_fact_f = store_fact_sales.get(code, 0.0)
        net_sales    = sales_target + sales_fact_f - ret
        gp_pct       = s.get('gp_pct', 33.0)
        gp_mtd_amt   = round(net_sales * gp_pct / 100)
        cost_mtd     = net_sales - gp_mtd_amt
        txn_target   = store_txn_mtd.get(code, 0)
        txn_fact_f   = len(store_fact_txn.get(code, set()))
        txn_mtd      = txn_target + txn_fact_f
        _used_whsdd_fallback += 1

    daily     = round(net_sales / FACT_DAYS) if FACT_DAYS else 0
    proj      = daily * DAYS_IN_MONTH
    daily_txn = round(txn_mtd / FACT_DAYS) if FACT_DAYS else 0
    ticket    = round(net_sales / txn_mtd) if txn_mtd else 0

    # YoY baseline: prefer fact_sales May 2025, fall back to existing HTML value
    fs25 = _fact_sales_25.get(code)
    if fs25:
        s25   = fs25['s25']
        txn25_store = fs25['txn25']
        t25   = round(s25 / txn25_store) if txn25_store else 0
        dtxn25 = round(txn25_store / DAYS_IN_MONTH) if txn25_store else 0
    else:
        s25    = s.get('s25_may', 0)
        txn25_store = s.get('txn_may25', 0)
        t25    = s.get('ticket_avg_25', 0)
        dtxn25 = s.get('daily_txn_25', 0)

    s.update({
        'sales_mtd': round(net_sales), 'target': round(tar_mo), 'mtd_target': round(tar_mtd),
        'daily': daily, 'proj': proj, 'txn_mtd': txn_mtd, 'daily_txn': daily_txn,
        'ticket_avg': ticket,
        'gp_mtd': round(gp_mtd_amt), 'gp_pct': round(gp_pct, 2),
        'gp_proj': round(proj * gp_pct / 100), 'ret_mtd': round(ret),
        'ret_daily': round(ret / DAYS_ELAPSED) if DAYS_ELAPSED else 0,
        's25_may': round(s25), 'txn_may25': txn25_store,
        'ticket_avg_25': t25, 'daily_txn_25': dtxn25,
        'pct_target': safe_pct(net_sales, tar_mtd), 'proj_vs_tgt': safe_pct(proj, tar_mo),
        'proj_yoy': safe_yoy(proj, s25), 'ticket_avg_yoy': safe_yoy(ticket, t25),
        'txn_yoy': safe_yoy(daily_txn, dtxn25),
    })
    s['m26'][MONTH_KEY] = round(net_sales)
    # Sync m25[prev-year-current-month] with s25_may (header card uses s25_may; list uses m25 → same source now)
    _prev_yr_key = '%d-%s' % (int(YEAR) - 1, MONTH)
    if 'm25' not in s or not isinstance(s.get('m25'), dict): s['m25'] = {}
    s['m25'][_prev_yr_key] = round(s25)
print('    fact_sales primary: %d stores | whsddpact fallback: %d stores' % (
    _used_fact_sales, _used_whsdd_fallback))

def aggregate(entity, stores):
    sm = sum(s['sales_mtd'] for s in stores); tar_mo = sum(s['target'] for s in stores)
    tar_mtd = sum(s['mtd_target'] for s in stores); txn = sum(s['txn_mtd'] for s in stores)
    gp_mtd = sum(s['gp_mtd'] for s in stores); ret_mtd = sum(s['ret_mtd'] for s in stores)
    s25 = sum(s.get('s25_may', 0) for s in stores); txn25 = sum(s.get('txn_may25', 0) for s in stores)
    cnt = entity.get('cnt', len(stores))
    daily = round(sm / FACT_DAYS) if FACT_DAYS else 0
    proj = daily * DAYS_IN_MONTH
    daily_txn = round(txn / FACT_DAYS) if FACT_DAYS else 0
    ticket = round(sm / txn) if txn else 0
    dtxn25 = round(txn25 / DAYS_IN_MONTH) if txn25 else 0
    ticket25 = round(s25 / txn25) if txn25 else 0
    entity.update({
        'sales_mtd': sm, 'target': round(tar_mo), 'mtd_target': round(tar_mtd),
        'daily': daily, 'proj': proj, 'txn_mtd': txn, 'daily_txn': daily_txn,
        'ticket_avg': ticket, 'gp_mtd': gp_mtd,
        'gp_pct': round(gp_mtd / sm * 100, 2) if sm else 0,
        'ret_mtd': ret_mtd, 'ret_daily': round(ret_mtd / FACT_DAYS) if FACT_DAYS else 0,
        'ret_per_store': round(ret_mtd / cnt) if cnt else 0,
        's25_may': s25, 'txn_may25': txn25, 'daily_txn_25': dtxn25, 'ticket_avg_25': ticket25,
        'pct_target': safe_pct(sm, tar_mtd), 'proj_vs_tgt': safe_pct(proj, tar_mo),
        'proj_yoy': safe_yoy(proj, s25), 'ticket_avg_yoy': safe_yoy(ticket, ticket25),
        'txn_yoy': safe_yoy(daily_txn, dtxn25),
    })
    entity['m26'][MONTH_KEY] = sm
    # Sync entity m25[prev-year-current-month] for RM/DM aggregate views (same-source as store level)
    _prev_yr_key_e = '%d-%s' % (int(YEAR) - 1, MONTH)
    if 'm25' not in entity or not isinstance(entity.get('m25'), dict): entity['m25'] = {}
    entity['m25'][_prev_yr_key_e] = s25

dm_stores = defaultdict(list); rm_stores = defaultdict(list)
for s in D['stores']:
    dm_stores[str(s.get('dm_code', ''))].append(s)
    rm_stores[str(s.get('rm', ''))].append(s)
for dm in D['dm']:
    stores = dm_stores.get(str(dm.get('dm_code', '')), [])
    if stores: aggregate(dm, stores)
for rm in D['rm']:
    stores = rm_stores.get(str(rm.get('rm', '')), [])
    if stores: aggregate(rm, stores)

# STEP 6: Summary
print('\n[6/7] Updating summary ...')
all_s = D['stores']
sm    = sum(s['sales_mtd'] for s in all_s); tar_mo = sum(s['target'] for s in all_s)
tar_mtd = sum(s['mtd_target'] for s in all_s); txn = sum(s['txn_mtd'] for s in all_s)
gp_mtd = sum(s['gp_mtd'] for s in all_s); ret_mtd = sum(s['ret_mtd'] for s in all_s)
s25 = sum(s.get('s25_may', 0) for s in all_s); txn25 = sum(s.get('txn_may25', 0) for s in all_s)
daily = round(sm / FACT_DAYS) if FACT_DAYS else 0
proj = daily * DAYS_IN_MONTH
daily_txn = round(txn / FACT_DAYS) if FACT_DAYS else 0
ticket = round(sm / txn) if txn else 0
dtxn25_tot = round(txn25 / DAYS_IN_MONTH) if txn25 else 0
ticket25 = round(s25 / txn25) if txn25 else 0
store_cnt = D['summary'].get('store_cnt', len(all_s))

D['summary'].update({
    'month_name': MONTH_NAME_TH, 'days_in_month': DAYS_IN_MONTH,
    'days_elapsed': DAYS_ELAPSED, 'days_remaining': DAYS_IN_MONTH - DAYS_ELAPSED,
    'fact_days': FACT_DAYS,
    'total_mtd': sm, 'total_daily': daily, 'total_proj': proj,
    'total_target': round(tar_mo), 'total_mtd_target': round(tar_mtd),
    'total_gp_mtd': gp_mtd, 'total_gp_pct': round(gp_mtd / sm * 100, 2) if sm else 0,
    'total_txn': txn, 'total_daily_txn': daily_txn, 'total_ticket_avg': ticket,
    'total_s25': s25, 'total_ret_mtd': ret_mtd,
    'total_ret_daily': round(ret_mtd / FACT_DAYS) if FACT_DAYS else 0,
    'total_ret_per_store': round(ret_mtd / store_cnt) if store_cnt else 0,
    'total_pct_target': safe_pct(sm, tar_mtd), 'total_proj_vs_tgt': safe_pct(proj, tar_mo),
    'total_proj_yoy': safe_yoy(proj, s25), 'total_txn_may25': txn25,
    'total_daily_txn_25': dtxn25_tot, 'total_ticket_avg_25': ticket25,
    'total_ticket_avg_yoy': safe_yoy(ticket, ticket25),
    'total_txn_yoy': safe_yoy(daily_txn, dtxn25_tot),
})
D['summary']['m26_tot'][MONTH_KEY] = sm
# Sync summary m25_tot[prev-year-current-month] so trend chart and home cards match (same source as per-store)
_prev_yr_key_t = '%d-%s' % (int(YEAR) - 1, MONTH)
if 'm25_tot' not in D['summary'] or not isinstance(D['summary'].get('m25_tot'), dict): D['summary']['m25_tot'] = {}
D['summary']['m25_tot'][_prev_yr_key_t] = s25

# Save sales_dashboard_v8.html
new_json = json.dumps(D, ensure_ascii=False)
html     = html[:json_start] + new_json + html[json_end:]
html     = re.sub(r'<span id="td-days">\d+</span>',
                  '<span id="td-days">%d</span>' % DAYS_ELAPSED, html)

# Replace hardcoded Thai month labels in sales_dashboard_v8.html
_mo_i  = int(MONTH)
_pm_i  = _mo_i - 1 if _mo_i > 1 else 12
_yr_i  = int(YEAR)
_be_i  = _yr_i + 543
for _old, _new in [
    (_TH_MONTHS[_pm_i] + ' ' + YEAR,                    _TH_MONTHS[_mo_i] + ' ' + YEAR),
    (_TH_MONTHS[_pm_i] + ' ' + str(_yr_i - 1),          _TH_MONTHS[_mo_i] + ' ' + str(_yr_i - 1)),
    (_TH_MONTHS[_pm_i] + ' ' + str(_be_i),               _TH_MONTHS[_mo_i] + ' ' + str(_be_i)),
    (_TH_MONTHS_SHORT[_pm_i] + ' ' + YEAR[-2:],         _TH_MONTHS_SHORT[_mo_i] + ' ' + YEAR[-2:]),
    (_TH_MONTHS_SHORT[_pm_i] + ' ' + str(_yr_i - 1)[-2:], _TH_MONTHS_SHORT[_mo_i] + ' ' + str(_yr_i - 1)[-2:]),
    (_TH_MONTHS_SHORT[_pm_i] + ' ' + YEAR,              _TH_MONTHS_SHORT[_mo_i] + ' ' + YEAR),
    (_TH_MONTHS_SHORT[_pm_i] + ' ' + str(_yr_i - 1),   _TH_MONTHS_SHORT[_mo_i] + ' ' + str(_yr_i - 1)),
    (_TH_MONTHS_SHORT[_pm_i] + '</',                     _TH_MONTHS_SHORT[_mo_i] + '</'),
    ('/' + str(_pm_i) + '/' + str(_be_i),                '/' + str(_mo_i) + '/' + str(_be_i)),
]:
    html = html.replace(_old, _new)

with open(DASHBOARD_FILE, 'w', encoding='utf-8') as f:
    f.write(html)

# Update index.html Hub (KPI numbers only)
print('  Updating index.html hub ...')
with open(INDEX_FILE, encoding='utf-8') as f:
    idx = f.read()

S = D['summary']
mtd_m = '%.1fM' % (sm / 1e6)
proj_m = '%.1fM' % (proj / 1e6)
pct_tgt = '%d%%' % round(S.get('total_pct_target') or 0)
gp_str = '%.2f%%' % S.get('total_gp_pct', 0)
proj_yoy_val = S.get('total_proj_yoy') or 0
yoy_str = ('+' if proj_yoy_val >= 0 else '') + ('%.1f%%' % proj_yoy_val)
txn_d = '%d' % daily_txn

def upd_hk(html, val, label):
    return re.sub(
        r'(<div class="hk-val">)[^<]+(</div><div class="hk-lab">' + re.escape(label) + ')',
        r'\g<1>' + val + r'\g<2>', html)

def upd_skpi(html, val, label):
    return re.sub(
        r'(<div class="skpi-label">' + re.escape(label) + r'</div>\s*<div class="skpi-val">)[^<]+(</div>)',
        r'\g<1>' + val + r'\g<2>', html)

# Day badge
idx = re.sub(r'(\d+ / \d+|Day \d+/\d+)', 'Day %d/%d' % (DAYS_ELAPSED, DAYS_IN_MONTH), idx)
idx = re.sub(r'(<div class="day-badge">)\d+(</div>)',
             r'\g<1>' + str(DAYS_ELAPSED) + r'\g<2>', idx)

# date-badge nav (e.g. "1 มิ.ย. 2569 · วัน 1/30")
THAI_MONTHS = ['','ม.ค.','ก.พ.','มี.ค.','เม.ย.','พ.ค.','มิ.ย.',
               'ก.ค.','ส.ค.','ก.ย.','ต.ค.','พ.ย.','ธ.ค.']
YEAR_BE = today.year + 543
THAI_MON = THAI_MONTHS[today.month]
new_badge = '%d %s %d · วัน %d/%d' % (DAYS_ELAPSED, THAI_MON, YEAR_BE, DAYS_ELAPSED, DAYS_IN_MONTH)
idx = re.sub(
    r'\d+\s+\S+\s+\d{4}\s+·\s+วัน\s+\d+/\d+',
    new_badge, idx)

# Hero KPIs (Thai labels)
idx = upd_hk(idx, mtd_m, '\xe0\xb8\xa2\xe0\xb8\xad\xe0\xb8\x94\xe0\xb8\x82\xe0\xb8\xb2\xe0\xb8\xa2 MTD (\xe0\xb8\x9f)'.encode().decode('unicode_escape') if False else 'ยอดขาย MTD (฿)')
idx = upd_hk(idx, pct_tgt, 'vs เป้า MTD')
idx = upd_hk(idx, proj_m, 'Projected (฿)')
idx = upd_hk(idx, yoy_str, 'YoY Projected')
idx = upd_hk(idx, gp_str, 'GP%')

# Sales card KPIs
idx = upd_skpi(idx, mtd_m, 'ยอดขาย MTD')
idx = upd_skpi(idx, proj_m, 'Projected เต็มเดือน')
idx = upd_skpi(idx, txn_d, 'บิล/วัน')

# ── KPI Detail Cards (11 cards) ──────────────────────────────────────────
def upd_kc(html, kc_id, val):
    """Replace content of <div id="kc_id">...</div>"""
    return re.sub(
        r'(<div[^>]+id="' + kc_id + r'"[^>]*>)[^<]*(</div>)',
        lambda m: m.group(1) + val + m.group(2),
        html
    )

daily_run   = sm / DAYS_ELAPSED if DAYS_ELAPSED else 0
s25_may     = S.get('total_s25', 0)
days_rem    = DAYS_IN_MONTH - DAYS_ELAPSED
mtd_target  = S.get('total_mtd_target', 0)
ticket_avg  = S.get('total_ticket_avg', 0)
ticket_25   = S.get('total_ticket_avg_25', 0)
ticket_yoy  = S.get('total_ticket_avg_yoy', 0)
txn_yoy     = S.get('total_txn_yoy', 0)
ret_per_st  = S.get('total_ret_per_store', 0)
ret_daily   = S.get('total_ret_daily', 0)
store_cnt   = S.get('store_cnt', 1)
bills_per   = round(daily_txn / store_cnt) if store_cnt else 0
bills_25    = S.get('total_daily_txn_25', 0)
bills_25_per= round(bills_25 / store_cnt) if store_cnt else 0

proj_yoy_str = ('▲ +' if proj_yoy_val >= 0 else '▼ ') + '%.1f%%' % abs(proj_yoy_val)
yoy_color   = 'pos' if proj_yoy_val >= 0 else 'neg'
tgt_color   = 'pos' if (S.get('total_pct_target', 0) or 0) >= 100 else 'neg'
txn_yoy_arrow = '▲' if txn_yoy >= 0 else '▼'
tk_yoy_arrow  = '▲' if ticket_yoy >= 0 else '▼'

# 4 KPI cards (ไม่ซ้ำ hero): Run Rate, Ticket, Bills, Returns
idx = upd_kc(idx, 'k-run',     '฿%.2fM' % (daily_run / 1e6))
idx = upd_kc(idx, 'k-ticket',  str(ticket_avg))
idx = upd_kc(idx, 'k-bills',   str(bills_per))
idx = upd_kc(idx, 'k-ret',     format(ret_per_st, ','))
idx = upd_kc(idx, 'k-ret-sub', 'รวม ฿%s | ฿%s/วัน' % (
    format(round(ret_mtd / 1000), ',') + 'K',
    format(ret_daily, ',')))

# Sub-badge: AVG Ticket YoY
idx = re.sub(
    r'(vs ปี25: ฿)\d+( <span class="kc-badge (?:pos|neg)">)([▲▼][\d.]+%)(</span>)',
    lambda m: m.group(1) + str(ticket_25) + m.group(2) +
              tk_yoy_arrow + '%.1f%%' % abs(ticket_yoy) + m.group(4),
    idx, count=1
)
# Sub-badge: Bills/day YoY
idx = re.sub(
    r'(vs ปี25: )\d+( <span class="kc-badge (?:pos|neg)">)([▲▼][\d.]+%)(</span>)',
    lambda m: m.group(1) + str(bills_25_per) + m.group(2) +
              txn_yoy_arrow + '%.1f%%' % abs(txn_yoy) + m.group(4),
    idx, count=1
)

# Update day-num + progress bar (hero right side)
idx = re.sub(r'(<div class="day-num">)\d+(</div>)',
             r'\g<1>' + str(DAYS_ELAPSED) + r'\g<2>', idx)
day_pct = round(DAYS_ELAPSED / DAYS_IN_MONTH * 100)
idx = re.sub(r'(class="day-bar-fill" style="width:)\d+(%")',
             r'\g<1>' + str(day_pct) + r'\g<2>', idx)

# RM_DATA JavaScript block
# Read existing RM names from current index.html to preserve Thai names
existing_rm_names = re.findall(r"name:'([^']+)'", idx)
rm_code_order = [str(r.get('rm', '')) for r in sorted(D['rm'], key=lambda r: str(r.get('rm', '')))]
rm_name_map = {}
for i, code in enumerate(rm_code_order):
    if i < len(existing_rm_names):
        nm = existing_rm_names[i]
        # Strip accidental double-prefix (e.g. 'RMRM1' -> 'RM1')
        if nm.startswith('RMRM'):
            nm = nm[2:]
        rm_name_map[code] = nm

rm_rows = []
for rm in sorted(D['rm'], key=lambda r: str(r.get('rm', ''))):
    code = str(rm.get('rm', ''))
    nm   = rm_name_map.get(code, code)
    cnt  = rm.get('cnt', 0)
    sal  = rm.get('sales_mtd', 0)
    prj  = rm.get('proj', 0)
    yoy  = rm.get('proj_yoy') or 0
    pct  = rm.get('pct_target') or 0
    rm_rows.append("  {name:'%s', stores:%s, sales:%s, proj:%s, yoy:%s, pct:%s}" % (nm, cnt, sal, prj, yoy, pct))
new_rm = 'const RM_DATA = [\n' + ',\n'.join(rm_rows) + '\n];'
idx = re.sub(r'const RM_DATA = \[[\s\S]*?\];', new_rm, idx)

# Trend chart -- rebuild months/m26vals/m25vals dynamically from D['summary']
_m26_tot = D['summary'].get('m26_tot', {})
_m25_tot = D['summary'].get('m25_tot', {})
_chart_mos, _v26, _v25 = [], [], []
for _mn in range(1, _mo_i + 1):
    _k26 = '%s-%02d' % (YEAR, _mn)
    _k25 = '%d-%02d' % (_yr_i - 1, _mn)
    _chart_mos.append(_TH_MONTHS_SHORT[_mn])
    _v26.append('%.1f' % (_m26_tot.get(_k26, 0) / 1e6))
    _v25.append('%.1f' % (_m25_tot.get(_k25, 0) / 1e6))
idx = re.sub(r"const months\s*=\s*\[[^\]]*\];",
             "const months = ['" + "','".join(_chart_mos) + "'];", idx)
idx = re.sub(r"const m26vals\s*=\s*\[[^\]]*\];[^\n]*",
             "const m26vals = [" + ','.join(_v26) + "];   // " + _TH_MONTHS_SHORT[_mo_i] + " = MTD", idx)
idx = re.sub(r"const m25vals\s*=\s*\[[^\]]*\];[^\n]*",
             "const m25vals = [" + ','.join(_v25) + "];   // " + _TH_MONTHS_SHORT[_mo_i] + " " + str(_yr_i - 1) + " full month", idx)

# Update h1 title and other month labels in index.html
for _old, _new in [
    (_TH_MONTHS[_pm_i] + ' ' + str(_be_i), _TH_MONTHS[_mo_i] + ' ' + str(_be_i)),
    (_TH_MONTHS[_pm_i] + ' ' + YEAR,       _TH_MONTHS[_mo_i] + ' ' + YEAR),
    (_TH_MONTHS[_pm_i] + ' ' + str(_yr_i - 1), _TH_MONTHS[_mo_i] + ' ' + str(_yr_i - 1)),
]:
    idx = idx.replace(_old, _new)

# Safety check -- ensure file ends properly
if not idx.rstrip().endswith('</html>'):
    print('  WARNING: index.html may be truncated -- appending closing tags')
    if '</script>' not in idx[-100:]:
        idx = idx + '</script>\n'
    if '</body>' not in idx[-100:]:
        idx = idx + '</body>\n'
    idx = idx + '</html>\n'

with open(INDEX_FILE, 'w', encoding='utf-8') as f:
    f.write(idx)

# Report
data_note = ('target(d1-%d) + fact(%s)' % (max_fin_day, loaded_fact_days)
             if loaded_fact_days else 'target(d1-%d)' % max_fin_day)
print('\n' + '=' * 62)
print('  OK Dashboard updated!')
print('=' * 62)
print('  Data source    : ' + data_note)
print('  Day            : %d / %d' % (DAYS_ELAPSED, DAYS_IN_MONTH))
print('  Total MTD      : %s baht' % format(sm, ','))
print('  vs Target MTD  : %s' % S.get('total_pct_target'))
print('  Projected      : %s baht  (%s%% YoY)' % (format(proj, ','), S.get('total_proj_yoy')))
print('  GP             : %s baht  (%s%%)' % (format(gp_mtd, ','), S.get('total_gp_pct')))
print('  Transactions   : %s  (%s/day)' % (format(txn, ','), format(daily_txn, ',')))
print('  Returns MTD    : %s baht' % format(ret_mtd, ','))
print('=' * 62)
print('  Saved: %s  +  %s\n' % (os.path.basename(DASHBOARD_FILE), os.path.basename(INDEX_FILE)))

# Sync returnXX.txt files into returnall.txt before fraud rebuild
# returnall.txt is the master file read by rebuild_fraud_analysis.py;
# any returnDD.txt for days not yet in returnall.txt must be appended first.
_returnall_path = os.path.join(FOLDER, 'returnall.txt')
try:
    import pandas as _rpd
    _ra = _rpd.read_csv(_returnall_path, sep='\t', dtype=str, usecols=['return_date'])
    _ra['_d'] = _rpd.to_datetime(_ra['return_date'], errors='coerce')
    _ra_may = _ra[_ra['_d'].dt.strftime('%Y-%m') == '%s-%s' % (YEAR, MONTH)]
    _days_in_returnall = set(_ra_may['_d'].dt.day.dropna().astype(int).tolist())
    _appended = []
    for _rfile in sorted(glob.glob(os.path.join(FOLDER, 'return*.txt'))):
        _bn = os.path.basename(_rfile)
        _m = re.match(r'return(\d{1,2})\.txt$', _bn, re.IGNORECASE)
        if not _m:
            continue
        _day_num = int(_m.group(1))
        if _day_num not in _days_in_returnall:
            with open(_rfile, encoding='utf-8') as _rf:
                _lines = _rf.readlines()
            _data_rows = _lines[1:]  # skip header
            if _data_rows:
                with open(_returnall_path, 'a', encoding='utf-8') as _raf:
                    for _row in _data_rows:
                        _raf.write(_row)
                _appended.append(_bn)
    if _appended:
        print('    returnall.txt updated      : appended %s' % ', '.join(_appended))
    else:
        print('    returnall.txt              : up to date')
except Exception as _re:
    print('    WARNING: returnall.txt sync failed: %s' % _re)

# NOTE: rebuild_fraud_analysis.py is run separately BEFORE this script
# (step 2 in run_daily_update.bat). Calling it again here causes a
# 5-minute MySQL timeout. The inject step below uses fraud_data.json
# that was already built by the batch job.

# Update fraud_dashboard.html \u2014 inject fresh data + nav-date
FRAUD_FILE = os.path.join(FOLDER, 'fraud_dashboard.html')
FRAUD_JSON  = os.path.join(FOLDER, 'fraud_data.json')
if os.path.exists(FRAUD_FILE) and os.path.exists(FRAUD_JSON):
    try:
        with open(FRAUD_JSON, encoding='utf-8') as _fj:
            _fd = json.load(_fj)

        # \u2500\u2500 Rename short field names \u2192 long field names used by fraud_dashboard JS \u2500\u2500
        def _rename_stats(s):
            return {
                'total_rows':      s.get('n',           s.get('total_rows', 0)),
                'total_amount':    s.get('total',        s.get('total_amount', 0)),
                'unique_rtu':      s.get('n_rtu',        s.get('unique_rtu', 0)),
                'unique_stores':   s.get('n_store',      s.get('unique_stores', 0)),
                'zero_rows':       s.get('n_zero',       s.get('zero_rows', 0)),
                'zero_amount':     s.get('zero_amt',     s.get('zero_amount', 0)),
                'multi_so_count':  s.get('n_so_dup',     s.get('multi_so_count', 0)),
                'multi_so_amount': s.get('so_dup_amt',   s.get('multi_so_amount', 0)),
                'night_amount':    s.get('night_amt',    s.get('night_amount', 0)),
            }
        def _rename_rtu(rows):
            out = []
            for r in rows:
                out.append({
                    'rtuname':    r.get('rtuname', ''),
                    'fullname':   r.get('fullname', ''),
                    'whs':        r.get('whs', ''),
                    'store_name': r.get('store_name', ''),
                    'dm':         r.get('dm', ''),
                    'rm':         r.get('rm', ''),
                    'returns':    r.get('returns', 0),
                    'amount':     r.get('amount', 0),
                    'zero_cust':  r.get('zero',       r.get('zero_cust', 0)),
                    'unique_so':  r.get('uso',         r.get('unique_so', 0)),
                    'repeat_so':  r.get('rep',         r.get('repeat_so', 0)),
                    'zero_pct':   r.get('zp',          r.get('zero_pct', 0)),
                    'fraud_score':r.get('score',       r.get('fraud_score', 0)),
                })
            return out
        def _rename_dm(rows):
            out = []
            for r in rows:
                out.append({
                    'dm':        r.get('dm', ''),
                    'rm':        r.get('rm', ''),
                    'returns':   r.get('returns', 0),
                    'amount':    r.get('amount', 0),
                    'stores':    r.get('stores', 0),
                    'cashiers':  r.get('cashiers', 0),
                    'zero_cust': r.get('zero',     r.get('zero_cust', 0)),
                    'zero_pct':  r.get('zp',       r.get('zero_pct', 0)),
                })
            return out
        def _rename_rm(rows):
            out = []
            for r in rows:
                out.append({
                    'rm':        r.get('rm', ''),
                    'returns':   r.get('returns', 0),
                    'amount':    r.get('amount', 0),
                    'stores':    r.get('stores', 0),
                    'cashiers':  r.get('cashiers', 0),
                    'zero_cust': r.get('zero',     r.get('zero_cust', 0)),
                    'dms':       r.get('dms', 0),
                    'zero_pct':  r.get('zp',       r.get('zero_pct', 0)),
                })
            return out
        def _rename_store(rows):
            out = []
            for r in rows:
                out.append({
                    'whs':        r.get('whs', ''),
                    'store_name': r.get('store_name', ''),
                    'dm':         r.get('dm', ''),
                    'rm':         r.get('rm', ''),
                    'returns':    r.get('returns', 0),
                    'amount':     r.get('amount', 0),
                    'cashiers':   r.get('cashiers', 0),
                    'zero_cust':  r.get('zero',     r.get('zero_cust', 0)),
                    'zero_pct':   r.get('zp',       r.get('zero_pct', 0)),
                })
            return out

        _new_data = {}
        for _mo, _md in _fd.get('data', {}).items():
            _new_data[_mo] = {
                'stats':     _rename_stats(_md.get('stats', {})),
                'rtu':       _rename_rtu(_md.get('rtu', [])),
                'store':     _rename_store(_md.get('store', [])),
                'dm':        _rename_dm(_md.get('dm', [])),
                'rm':        _rename_rm(_md.get('rm', [])),
                'hour':      _md.get('hour', []),
                'day':       _md.get('day', []),
                'multi_so':  _md.get('so', _md.get('multi_so', [])),
                'product':   _md.get('product', []),
                'reason':    _md.get('reason', []),
            }

        _new_D = {
            'generated':  _fd.get('gen', _fd.get('generated', '')),
            'months':     _fd.get('months', []),
            'data':       _new_data,
            'store_risk': _fd.get('sr', _fd.get('store_risk', [])),
        }
        _new_D_json = json.dumps(_new_D, ensure_ascii=False, separators=(',', ':'))

        with open(FRAUD_FILE, encoding='utf-8') as _ff:
            _fhtml = _ff.read()

        # If fraud_dashboard.html is truncated, regenerate from template
        _FRAUD_TMPL = os.path.join(FOLDER, 'fraud_analysis_template.html')
        _fraud_done = False
        if '</html>' not in _fhtml and os.path.exists(_FRAUD_TMPL):
            print('  NOTE: fraud_dashboard.html truncated — regenerating from template')
            with open(_FRAUD_TMPL, encoding='utf-8') as _ft:
                _fhtml = _ft.read()
            _fhtml = _fhtml.replace('PLACEHOLDER_DATA', _new_D_json)
            _fraud_badge = '%d %s %d · วัน 1–%d' % (DAYS_ELAPSED, THAI_MON, YEAR_BE, DAYS_IN_MONTH)
            _fraud_re = r'(?:\d{4}-\d{2}-\d{2}|\d+\s+\S+\s+\d{4})\s+·\s+วัน\s+1[–\-]\d+(?:\s+\S+)?'
            _fhtml = re.sub(_fraud_re, _fraud_badge, _fhtml)
            with open(FRAUD_FILE, 'w', encoding='utf-8') as _ff:
                _ff.write(_fhtml)
            print('  fraud_dashboard.html regenerated from template + data injected')
            _fraud_done = True

        if not _fraud_done:
            # Replace embedded const D = {...};  (normal brace-match path)
            _d_search = _fhtml.find('const D={')
            if _d_search < 0: _d_search = _fhtml.find('const D = {')
            _d_start = _fhtml.index('{', _d_search)
            _depth = 0; _i = _d_start
            while _i < len(_fhtml):
                if _fhtml[_i] == '{':  _depth += 1
                elif _fhtml[_i] == '}':
                    _depth -= 1
                    if _depth == 0: _d_end = _i + 1; break
                _i += 1
            _fhtml = _fhtml[:_d_start] + _new_D_json + _fhtml[_d_end:]

            # Update ML month-label lookup → dynamic (replaces old hardcoded version)
            _new_ml = ("const TH_MO_S=['','ม.ค.','ก.พ.','มี.ค.','เม.ย.','พ.ค.','มิ.ย.',"
                       "'ก.ค.','ส.ค.','ก.ย.','ต.ค.','พ.ย.','ธ.ค.'];\n"
                       "const ML=Object.fromEntries((D.months||[]).map(k=>{const[y,m]=k.split('-');return[k,TH_MO_S[+m]];}));")
            _fhtml = re.sub(r"const ML=\{[^}]+\};", _new_ml, _fhtml)

            # Update nav-date badge (matches both ISO and Thai date formats)
            _fraud_badge = '%d %s %d · วัน 1–%d' % (DAYS_ELAPSED, THAI_MON, YEAR_BE, DAYS_IN_MONTH)
            _fraud_re = r'(?:\d{4}-\d{2}-\d{2}|\d+\s+\S+\s+\d{4})\s+·\s+วัน\s+1[–\-]\d+(?:\s+\S+)?'
            _fhtml = re.sub(_fraud_re, _fraud_badge, _fhtml)

            with open(FRAUD_FILE, 'w', encoding='utf-8') as _ff:
                _ff.write(_fhtml)
            print('  fraud_dashboard.html data injected + nav-date -> day 1-%d/%d' % (DAYS_ELAPSED, DAYS_IN_MONTH))
    except Exception as _e:
        print('  WARNING fraud_dashboard.html data inject failed: %s' % _e)
        # Fallback: at least update the date badge
        try:
            with open(FRAUD_FILE, encoding='utf-8') as _ff: _fhtml = _ff.read()
            _fraud_badge = '%d %s %d · วัน 1–%d' % (DAYS_ELAPSED, THAI_MON, YEAR_BE, DAYS_IN_MONTH)
            _fraud_re = r'(?:\d{4}-\d{2}-\d{2}|\d+\s+\S+\s+\d{4})\s+·\s+วัน\s+1[–\-]\d+(?:\s+\S+)?'
            _fhtml = re.sub(_fraud_re, _fraud_badge, _fhtml)
            with open(FRAUD_FILE, 'w', encoding='utf-8') as _ff: _ff.write(_fhtml)
        except: pass

# STEP 7: Push to GitHub Pages
print('[7/7] Pushing to GitHub Pages ...')
try:
    if os.path.exists(os.path.join(REPO_DIR, '.git')):
        subprocess.run(['git', '-C', REPO_DIR, 'pull', '--ff-only'],
                       check=True, capture_output=True)
    else:
        subprocess.run(['git', 'clone', GITHUB_URL, REPO_DIR],
                       check=True, capture_output=True)

    # Stamp product_data.json with today's date so it always gets committed
    prod_json = os.path.join(FOLDER, 'product_data.json')
    if os.path.exists(prod_json):
        import json as _pj
        _pd = _pj.load(open(prod_json, encoding='utf-8'))
        _pd['generated'] = str(date.today())
        with open(prod_json, 'w', encoding='utf-8') as _pf:
            _pj.dump(_pd, _pf, ensure_ascii=False, separators=(',', ':'))
        print('    product_data.json generated -> %s' % date.today())

    push_files = ['index.html', 'sales_dashboard_v8.html', 'fraud_dashboard.html',
                  'fraud_analysis.html', 'fraud_data.json',
                  'product_dashboard.html', 'product_data.json', 'analytics.js']
    for fname in push_files:
        src = os.path.join(FOLDER, fname)
        dst = os.path.join(REPO_DIR, fname)
        if os.path.exists(src):
            shutil.copy2(src, dst)
    _env = os.environ.copy()
    _env['GIT_AUTHOR_NAME']     = 'Dashboard Bot'
    _env['GIT_AUTHOR_EMAIL']    = 'bot@dashboard'
    _env['GIT_COMMITTER_NAME']  = 'Dashboard Bot'
    _env['GIT_COMMITTER_EMAIL'] = 'bot@dashboard'
    subprocess.run(['git', '-C', REPO_DIR, 'add', '-A'],
                   capture_output=True, env=_env)
    _cr = subprocess.run(
        ['git', '-C', REPO_DIR, 'commit', '-m',
         'auto: Day %d/%d %s' % (DAYS_ELAPSED, DAYS_IN_MONTH, MONTH_NAME)],
        capture_output=True, text=True, env=_env)
    if 'nothing to commit' in (_cr.stdout + _cr.stderr):
        print('  GitHub: nothing to commit (data unchanged)')
    else:
        _pr = subprocess.run(['git', '-C', REPO_DIR, 'push', 'origin', 'main'],
                             capture_output=True, text=True, env=_env)
        if _pr.returncode == 0:
            print('  GitHub: pushed OK')
        else:
            print('  WARNING: push failed: ' + _pr.stderr[-200:])
except Exception as _e:
    print('  WARNING: GitHub push failed: ' + str(_e))
finally:
    if os.path.exists(REPO_DIR):
        shutil.rmtree(REPO_DIR, ignore_errors=True)

print()
print('All done.')
