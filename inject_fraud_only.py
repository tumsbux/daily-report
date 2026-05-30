#!/usr/bin/env python3
"""
inject_fraud_only.py
Reads fraud_data.json and injects it into fraud_dashboard.html, then pushes to GitHub.
Run: py inject_fraud_only.py
"""
import os, json, re, subprocess, tempfile, uuid, shutil

FOLDER     = os.path.dirname(os.path.abspath(__file__))
FRAUD_FILE = os.path.join(FOLDER, 'fraud_dashboard.html')
FRAUD_JSON = os.path.join(FOLDER, 'fraud_data.json')

# Read token from db_config.json (never hardcode secrets in source)
def _read_github_token():
    cfg_path = os.path.join(FOLDER, 'db_config.json')
    try:
        with open(cfg_path, encoding='utf-8') as _f:
            return json.load(_f).get('github_token', '')
    except Exception:
        return ''

def _read_github_repo():
    cfg_path = os.path.join(FOLDER, 'db_config.json')
    try:
        with open(cfg_path, encoding='utf-8') as _f:
            return json.load(_f).get('github_repo', 'tumsbux/daily-report')
    except Exception:
        return 'tumsbux/daily-report'

GITHUB_TOKEN = _read_github_token()
GITHUB_REPO  = _read_github_repo()
GITHUB_URL   = 'https://' + GITHUB_TOKEN + '@github.com/' + GITHUB_REPO + '.git'

print('=' * 60)
print('  inject_fraud_only.py')
print('=' * 60)

# --- Load fraud_data.json ---
print('[1/4] Loading fraud_data.json ...')
with open(FRAUD_JSON, encoding='utf-8') as f:
    fd = json.load(f)
print(f'      gen={fd.get("gen","?")}  months={fd.get("months",[])}')

# --- Rename fields to match fraud_dashboard.html JS expectations ---
def rename_stats(s):
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

def rename_rtu(rows):
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
            'zero_cust':  r.get('zero',   r.get('zero_cust', 0)),
            'unique_so':  r.get('uso',    r.get('unique_so', 0)),
            'repeat_so':  r.get('rep',    r.get('repeat_so', 0)),
            'zero_pct':   r.get('zp',     r.get('zero_pct', 0)),
            'fraud_score':r.get('score',  r.get('fraud_score', 0)),
        })
    return out

def rename_store(rows):
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
            'zero_cust':  r.get('zero',   r.get('zero_cust', 0)),
            'zero_pct':   r.get('zp',     r.get('zero_pct', 0)),
        })
    return out

def rename_dm(rows):
    out = []
    for r in rows:
        out.append({
            'dm':        r.get('dm', ''),
            'rm':        r.get('rm', ''),
            'returns':   r.get('returns', 0),
            'amount':    r.get('amount', 0),
            'stores':    r.get('stores', 0),
            'cashiers':  r.get('cashiers', 0),
            'zero_cust': r.get('zero',   r.get('zero_cust', 0)),
            'zero_pct':  r.get('zp',     r.get('zero_pct', 0)),
        })
    return out

def rename_rm(rows):
    out = []
    for r in rows:
        out.append({
            'rm':        r.get('rm', ''),
            'returns':   r.get('returns', 0),
            'amount':    r.get('amount', 0),
            'stores':    r.get('stores', 0),
            'cashiers':  r.get('cashiers', 0),
            'zero_cust': r.get('zero',   r.get('zero_cust', 0)),
            'dms':       r.get('dms', 0),
            'zero_pct':  r.get('zp',     r.get('zero_pct', 0)),
        })
    return out

new_data = {}
for mo, md in fd.get('data', {}).items():
    new_data[mo] = {
        'stats':    rename_stats(md.get('stats', {})),
        'rtu':      rename_rtu(md.get('rtu', [])),
        'store':    rename_store(md.get('store', [])),
        'dm':       rename_dm(md.get('dm', [])),
        'rm':       rename_rm(md.get('rm', [])),
        'hour':     md.get('hour', []),
        'day':      md.get('day', []),
        'multi_so': md.get('so', md.get('multi_so', [])),
        'product':  md.get('product', []),
        'reason':   md.get('reason', []),
    }

new_D = {
    'generated':  fd.get('gen', fd.get('generated', '')),
    'months':     fd.get('months', []),
    'data':       new_data,
    'store_risk': fd.get('sr', fd.get('store_risk', [])),
}
new_D_json = json.dumps(new_D, ensure_ascii=False, separators=(',', ':'))
print(f'      JSON blob size: {len(new_D_json):,} chars')

# --- Inject into HTML ---
print('[2/4] Reading fraud_dashboard.html ...')
with open(FRAUD_FILE, encoding='utf-8') as f:
    html = f.read()
print(f'      HTML size: {len(html):,} chars')

MARKER = 'const D = {'
if MARKER not in html:
    print('ERROR: marker "const D = {" not found in fraud_dashboard.html')
    raise SystemExit(1)

d_start = html.index(MARKER) + len('const D = ')
# Use json.JSONDecoder for accurate block boundary (handles { } inside strings)
import json as _json
try:
    _decoder = _json.JSONDecoder()
    _obj, _end_offset = _decoder.raw_decode(html, d_start)
    d_end = _end_offset
except _json.JSONDecodeError as e:
    print(f'ERROR: Could not parse D block as JSON: {e}')
    raise SystemExit(1)

print(f'      Found D block at [{d_start}:{d_end}]')
html = html[:d_start] + new_D_json + html[d_end:]
print(f'      New HTML size: {len(html):,} chars')

# --- Update nav-date badge (e.g. "28 พ.ค. 2569 · วัน 1–27") ---
import re as _re
from datetime import date as _date
_THAI_MONTHS = ['','ม.ค.','ก.พ.','มี.ค.','เม.ย.','พ.ค.','มิ.ย.',
                'ก.ค.','ส.ค.','ก.ย.','ต.ค.','พ.ย.','ธ.ค.']
_today      = _date.today()
_year_be    = _today.year + 543
_thai_mon   = _THAI_MONTHS[_today.month]
_days_elapsed = max(1, _today.day - 1)
# Get max day from latest month data
_cur_mo = fd.get('months', [])
_cur_mo = _cur_mo[-1] if _cur_mo else None
if _cur_mo and _cur_mo in new_D.get('data', {}):
    _ret_rows = new_D['data'][_cur_mo].get('rtu', [])
    # use days_elapsed from data gen date if available
    pass
_fraud_badge = '%d %s %d · วัน 1–%d' % (
    _today.day, _thai_mon, _year_be, _days_elapsed)
html = _re.sub(
    r'\d+\s+\S+\s+\d{4}\s+·\s+วัน\s+1–\d+',
    _fraud_badge, html)
print(f'      Date badge updated -> {_fraud_badge}')

print('[3/4] Writing fraud_dashboard.html ...')
with open(FRAUD_FILE, 'w', encoding='utf-8') as f:
    f.write(html)
print('      Done.')

# --- Push to GitHub ---
print('[4/4] Pushing to GitHub ...')
# Use a fresh unique temp dir every run to avoid Windows file-lock issues
_repo_dir = os.path.join(tempfile.gettempdir(), f'dlr-{uuid.uuid4().hex[:8]}')
try:
    subprocess.run(['git', 'clone', '--depth=1', GITHUB_URL, _repo_dir],
                   check=True, capture_output=True)

    for fname in ['fraud_dashboard.html', 'fraud_data.json']:
        src = os.path.join(FOLDER, fname)
        dst = os.path.join(_repo_dir, fname)
        if os.path.exists(src):
            shutil.copy2(src, dst)

    _env = os.environ.copy()
    _env['GIT_AUTHOR_NAME']     = 'Dashboard Bot'
    _env['GIT_AUTHOR_EMAIL']    = 'bot@dashboard'
    _env['GIT_COMMITTER_NAME']  = 'Dashboard Bot'
    _env['GIT_COMMITTER_EMAIL'] = 'bot@dashboard'

    subprocess.run(['git', '-C', _repo_dir, 'add', 'fraud_dashboard.html', 'fraud_data.json'],
                   check=True, capture_output=True, env=_env)
    _cr = subprocess.run(
        ['git', '-C', _repo_dir, 'commit', '-m', 'fraud data update'],
        capture_output=True, text=True, env=_env)
    if 'nothing to commit' in (_cr.stdout + _cr.stderr):
        print('      GitHub: nothing to commit')
    else:
        subprocess.run(['git', '-C', _repo_dir, 'push'], check=True, capture_output=True, env=_env)
        print('      GitHub push OK')
except subprocess.CalledProcessError as e:
    print(f'      Git error: {e}')
    print(f'      stderr: {e.stderr}')
except Exception as e:
    print(f'      Push failed: {e}')
finally:
    shutil.rmtree(_repo_dir, ignore_errors=True)

print('=' * 60)
print('  All done!')
print('=' * 60)
