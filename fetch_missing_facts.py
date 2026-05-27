#!/usr/bin/env python3
"""
fetch_missing_facts.py
Checks which factXX.txt files are missing for the current month,
queries MySQL fact_sales for those days, and writes the files.
Run this before update_dashboard.py, or add to run_daily_update.bat.
"""
import os, json, csv, glob, re
from datetime import date, timedelta

FOLDER     = os.path.dirname(os.path.abspath(__file__))
DB_CONFIG  = os.path.join(FOLDER, 'db_config.json')
YEAR       = '2026'
MONTH      = '05'
MONTH_KEY  = f'{YEAR}-{MONTH}'

# ── Columns matching existing factXX.txt files ────────────────────────────────
COLUMNS = [
    'sono','soserlno','iprod','sodate','cstcode','soqty','retqty','net_qty',
    'sopricunit','sopricamt','sopricdisc','solineamt','socstunit','total_cost',
    'untcode','sotowhs','soretflag','bldstatus','prorated_discount','net_sales_amt',
    'tblupdate','etl_at','net_return_amt','solinetype','uname',
]

def load_cfg():
    with open(DB_CONFIG, encoding='utf-8') as f:
        return json.load(f)

def get_existing_days():
    """Return set of days (int) that already have factXX.txt files."""
    days = set()
    for fpath in glob.glob(os.path.join(FOLDER, 'fact*.txt')):
        bn = os.path.basename(fpath)
        m = re.match(r'fact(\d{1,2})\.txt$', bn, re.IGNORECASE)
        if m:
            days.add(int(m.group(1)))
    return days

def fetch_day(cfg, day):
    """Query MySQL for one day's fact_sales rows and return list of dicts."""
    import mysql.connector
    date_str = f'{YEAR}-{MONTH}-{day:02d}'
    sql = f"""
        SELECT
            sono, soserlno, iprod, sodate, cstcode,
            soqty, retqty, net_qty,
            sopricunit, sopricamt, sopricdisc, solineamt,
            socstunit, total_cost, untcode, sotowhs,
            soretflag, bldstatus, prorated_discount, net_sales_amt,
            tblupdate, etl_at, net_return_amt, solinetype, uname
        FROM `data-lake`.fact_sales
        WHERE DATE(sodate) = '{date_str}'
        ORDER BY sono, soserlno
    """
    conn = mysql.connector.connect(
        host=cfg['host'], port=cfg.get('port', 3306),
        user=cfg['user'], password=cfg['password'],
        database=cfg['database'], connection_timeout=30,
        use_pure=True
    )
    cursor = conn.cursor(dictionary=True)
    cursor.execute(sql)
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    return rows

def write_fact_file(day, rows):
    fpath = os.path.join(FOLDER, f'fact{day}.txt')
    with open(fpath, 'w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS, delimiter='\t',
                                extrasaction='ignore', lineterminator='\n')
        writer.writeheader()
        for r in rows:
            # Convert all values to string, handle None
            out = {}
            for col in COLUMNS:
                v = r.get(col, '')
                if v is None:
                    out[col] = ''
                else:
                    out[col] = str(v)
            writer.writerow(out)
    return fpath

def main():
    print('=' * 55)
    print('  fetch_missing_facts.py')
    print('=' * 55)

    today = date.today()
    # Update through yesterday (today-1)
    target_day = today.day - 1
    if today.month != int(MONTH) or today.year != int(YEAR):
        print(f'  Note: current month is {today.year}-{today.month:02d}, '
              f'configured for {YEAR}-{MONTH}')

    existing = get_existing_days()
    needed = [d for d in range(1, target_day + 1) if d not in existing]

    if not needed:
        print(f'  All days 1-{target_day} already have fact files. Nothing to do.')
        return

    print(f'  Existing fact days : {sorted(existing)}')
    print(f'  Missing days       : {needed}')

    try:
        cfg = load_cfg()
    except Exception as e:
        print(f'  ERROR loading db_config.json: {e}')
        return

    for day in needed:
        date_str = f'{YEAR}-{MONTH}-{day:02d}'
        print(f'\n  Fetching day {day} ({date_str}) ...', end=' ', flush=True)
        try:
            rows = fetch_day(cfg, day)
            if not rows:
                print(f'0 rows -- skipping (no data in MySQL for this day)')
                continue
            fpath = write_fact_file(day, rows)
            print(f'{len(rows):,} rows → {os.path.basename(fpath)}')
        except Exception as e:
            print(f'ERROR: {e}')

    print('\n  Done.')
    print('=' * 55)

if __name__ == '__main__':
    main()
