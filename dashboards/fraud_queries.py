"""
dashboards/fraud_queries.py — MySQL data query helpers for fraud analysis (Phase 3d, 2026-06-14)

Extracted from rebuild_fraud_analysis.py:
  - _mysql_conn()
  - _load_sales_mtd_from_cache(max_mo, folder)
  - _get_frozen_returns(cfg, m3_str, folder, full_refresh)
  - _query_returns_full(cfg, folder, months_back, full_refresh)
  - _query_whsdd_sales_cost(cfg, year_month)
  - _query_sales_mtd(cfg)
"""

import os
import json
import pandas as pd
from datetime import datetime, date


def _mysql_conn(cfg):
    import mysql.connector
    return mysql.connector.connect(
        host=cfg['host'], port=cfg.get('port', 3306),
        user=cfg['user'], password=cfg['password'],
        database=cfg['database'], connection_timeout=30,
        charset='utf8mb4'
    )

def _load_sales_mtd_from_cache(max_mo, folder):
    cache_path = os.path.join(folder, 'cache', f'sales_daily_{max_mo}.json')
    if not os.path.exists(cache_path):
        return None
    try:
        with open(cache_path, encoding='utf-8') as f:
            cache_data = json.load(f)
        
        sales_map = {}
        cost_map = {}
        
        stores = cache_data.get('stores', {})
        for raw_whs, day_map in stores.items():
            whs = str(raw_whs).zfill(3)
            sales_sum = sum(day_data.get('sales', 0.0) for day_data in day_map.values())
            cost_sum = sum(day_data.get('cost', 0.0) for day_data in day_map.values())
            sales_map[whs] = sales_sum
            cost_map[whs] = cost_sum
            
        print(f"  Loaded MTD sales/costs from daily sales cache {cache_path} ({len(sales_map)} stores)")
        return sales_map, cost_map
    except Exception as e:
        print(f"  WARNING: Failed to load daily sales cache for fraud scoring: {e}")
        return None

def _get_frozen_returns(cfg, m3_str, folder, full_refresh=False):
    cache_dir = os.path.join(folder, 'cache')
    os.makedirs(cache_dir, exist_ok=True)
    cache_path = os.path.join(cache_dir, f'fraud_closed_{m3_str}.json')
    
    if not full_refresh and os.path.exists(cache_path):
        try:
            with open(cache_path, encoding='utf-8') as f:
                data = json.load(f)
            meta = data.get('_meta', {})
            if meta.get('v') == 2:
                print(f"  [FRAUD CACHE] Loaded frozen returns for {m3_str} from cache ({len(data['returns'])} rows)")
                return pd.DataFrame(data['returns'])
        except Exception as e:
            print(f"  [FRAUD CACHE] Failed to load cache for {m3_str}: {e}")
            
    print(f"  [FRAUD CACHE] Cache not found for {m3_str}. Querying database to freeze...")
    start_date = f"{m3_str}-01"
    from dateutil.relativedelta import relativedelta
    m3_dt = datetime.strptime(m3_str, "%Y-%m").date()
    end_date = (m3_dt + relativedelta(months=1)).strftime('%Y-%m-01')
    
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
          AND fr.return_date >= '{start_date}'
          AND fr.return_date < '{end_date}'
          AND fr.warehouse_code NOT IN ('901', '999')
    """
    conn = _mysql_conn(cfg)
    df = pd.read_sql(sql, conn)
    conn.close()
    
    df_serialized = df.copy()
    for col in df_serialized.columns:
        if df_serialized[col].dtype == 'object' or hasattr(df_serialized[col], 'dt'):
            df_serialized[col] = df_serialized[col].astype(str)
            
    cache_data = {
        '_meta': {
            'v': 2,
            'built_by': 'antigravity-gemini-3-flash',
            'timestamp': datetime.now().isoformat()
        },
        'returns': df_serialized.to_dict(orient='records')
    }
    
    from lib.safe_write import safe_write_json
    safe_write_json(cache_path, cache_data)
    print(f"  [FRAUD CACHE] Successfully froze {m3_str} returns to cache ({len(df)} rows)")
    return df

def _query_returns_full(cfg, folder, months_back=4, full_refresh=False):
    """
    Single JOIN: fact_returns + dim_branch + dim_item_barcode + dim_product.
    Returns enriched DataFrame — store_name, dm, rm, parcode, idesc pre-filled.
    Uses Phase IR-D caching: freezes M-3 and queries M-2 onwards.
    """
    from dateutil.relativedelta import relativedelta
    
    if months_back != 4:
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
        print(f'  MySQL returns (uncached): {len(df):,} rows | {bills:,} bills | from {start}')
        return df
        
    m3_date = date.today().replace(day=1) - relativedelta(months=3)
    m3_str = m3_date.strftime('%Y-%m')
    
    df_frozen = _get_frozen_returns(cfg, m3_str, folder, full_refresh=full_refresh)
    
    m2_date = date.today().replace(day=1) - relativedelta(months=2)
    start_hot = m2_date.strftime('%Y-%m-01')
    
    sql_hot = f"""
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
          AND fr.return_date >= '{start_hot}'
          AND fr.warehouse_code NOT IN ('901', '999')
    """
    
    print(f"  [FRAUD CACHE] Querying hot returns starting from {start_hot}...")
    conn = _mysql_conn(cfg)
    df_hot = pd.read_sql(sql_hot, conn)
    conn.close()
    
    df = pd.concat([df_frozen, df_hot], ignore_index=True)
    
    for col in ['amount', 'return_qty', 'unit_price', 'allocated_net_amount']:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
            
    df['return_date'] = df['return_date'].astype(str)
            
    bills = df['rtsono'].nunique()
    print(f'  MySQL returns (frozen+hot): {len(df):,} rows | {bills:,} bills | cache month: {m3_str} | hot start: {start_hot}')
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
    """Current-month net sales + cost per store from fact_sales.
    Returns (sales_map, cost_map) where each is {whs: float}."""
    sql = """
        SELECT LPAD(sotowhs, 3, '0') AS whs,
               SUM(net_sales_amt)    AS sales_mtd,
               SUM(total_cost)       AS cost_mtd
        FROM fact_sales
        WHERE sodate >= DATE_FORMAT(CURDATE(), '%Y-%m-01')
          AND solinetype = 'N'
          AND sotowhs NOT IN ('901','999','0901','0999')
        GROUP BY sotowhs
    """
    conn = _mysql_conn(cfg)
    df = pd.read_sql(sql, conn)
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
