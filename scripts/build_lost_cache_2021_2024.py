#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_lost_cache_2021_2024.py — Streaming Edition
===================================================
Queries MySQL historical tables (2021-2024) and streams the results directly to Parquet.
Keeps RAM usage extremely low (<50MB) to prevent NumPy ArrayMemoryError.
"""

import os
import json
import sys
from datetime import datetime
import mysql.connector
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

# Path setup
SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
FOLDER = os.path.dirname(SCRIPTS_DIR)
CACHE_DIR = os.path.join(FOLDER, 'cache')
DB_CONFIG_FILE = os.path.join(FOLDER, 'db_config.json')

YEAR_TABLES = {
    2021: ('bld_acc_2021_lake', 'blh_acc_2021_lake', None),
    2022: ('bld_acc_2022_lake', 'blh_acc_2022_lake', None),
    2023: ('bld_acc_2023_lake', 'blh_acc_2023_lake', None),
    2024: ('bld_acc_2024_lake', 'blh_acc_2024_lake', None),
    2025: ('bld_acc_lake', 'blh_acc_lake', 2025),
}

BATCH = 20000
ACCUM_BATCH = 100000
RULE_HASH = "MIN_QTY=15_MIN_AMT=3000"

def _load_cfg():
    if not os.path.exists(DB_CONFIG_FILE):
        raise FileNotFoundError(f"db_config.json not found in {FOLDER}")
    with open(DB_CONFIG_FILE, encoding='utf-8') as f:
        return json.load(f)

def _conn(cfg):
    return mysql.connector.connect(
        host=cfg['host'],
        port=cfg.get('port', 3306),
        user=cfg['user'],
        password=cfg['password'],
        database=cfg.get('database', 'data-lake'),
        connection_timeout=60,
    )

def _write_qty_chunk(rows, writer, schema):
    df = pd.DataFrame(rows, columns=['year', 'iprod', 'qty'])
    df['year'] = df['year'].astype('int16')
    df['iprod'] = df['iprod'].astype('string')
    df['qty'] = df['qty'].astype('float32')
    table = pa.Table.from_pandas(df, schema=schema)
    writer.write_table(table)

def _write_store_chunk(rows, writer, schema):
    df = pd.DataFrame(rows, columns=['year', 'whs', 'iprod', 'qty', 'amt'])
    df['year'] = df['year'].astype('int16')
    df['whs'] = df['whs'].astype('string')
    df['iprod'] = df['iprod'].astype('string')
    df['qty'] = df['qty'].astype('float32')
    df['amt'] = df['amt'].astype('float32')
    table = pa.Table.from_pandas(df, schema=schema)
    writer.write_table(table)

def query_and_write_year(conn, year, bld_table, blh_table, where_year, writer_qty, writer_store, schema_qty, schema_store):
    """Query MySQL for one year's data and stream-write to Parquet writers."""
    print(f"  [{year}] Querying total qty per product...", flush=True)
    if where_year is not None:
        year_filter = (
            f"AND blh.sodate >= '{where_year}-01-01' "
            f"AND blh.sodate <  '{where_year+1}-01-01'"
        )
        sql_tot = f"""
            SELECT bld.iprod, SUM(bld.soqty) AS qty
            FROM `{bld_table}` bld
            JOIN `{blh_table}` blh ON blh.sono = bld.sono
            WHERE bld.solinetype NOT IN ('C', 'R')
              {year_filter}
            GROUP BY bld.iprod
            HAVING qty > 0
        """
    else:
        sql_tot = f"""
            SELECT bld.iprod, SUM(bld.soqty) AS qty
            FROM `{bld_table}` bld
            WHERE bld.solinetype NOT IN ('C', 'R')
            GROUP BY bld.iprod
            HAVING qty > 0
        """
    
    qty_rows = []
    n_qty = 0
    cur = conn.cursor(buffered=False)
    cur.execute(sql_tot)
    while True:
        rows = cur.fetchmany(BATCH)
        if not rows:
            break
        for ip, qty in rows:
            qty_rows.append((int(year), str(ip).strip(), float(qty)))
            
        if len(qty_rows) >= ACCUM_BATCH:
            n_qty += len(qty_rows)
            _write_qty_chunk(qty_rows, writer_qty, schema_qty)
            qty_rows = []
            
    if qty_rows:
        n_qty += len(qty_rows)
        _write_qty_chunk(qty_rows, writer_qty, schema_qty)
    cur.close()
    
    print(f"  [{year}] Querying store-product breakdown...", flush=True)
    if where_year is not None:
        year_filter = (
            f"AND blh.sodate >= '{where_year}-01-01' "
            f"AND blh.sodate <  '{where_year+1}-01-01'"
        )
    else:
        year_filter = ""
        
    sql_store = f"""
        SELECT blh.sotowhs AS whs, bld.iprod,
               SUM(bld.soqty) AS qty,
               SUM(bld.solineamt) AS amt
        FROM `{bld_table}` bld
        JOIN `{blh_table}` blh ON blh.sono = bld.sono
        WHERE bld.solinetype NOT IN ('C', 'R')
          {year_filter}
          AND blh.sotowhs REGEXP '^[0-9]+$'
        GROUP BY blh.sotowhs, bld.iprod
        HAVING qty > 0
    """
    
    store_rows = []
    n_store = 0
    cur = conn.cursor(buffered=False)
    cur.execute(sql_store)
    while True:
        rows = cur.fetchmany(BATCH)
        if not rows:
            break
        for whs, ip, q, a in rows:
            try:
                n = int(str(whs))
                if 1 <= n <= 500:
                    store_rows.append((int(year), f'{n:03d}', str(ip).strip(), float(q), float(a or 0)))
            except (ValueError, TypeError):
                pass
                
        if len(store_rows) >= ACCUM_BATCH:
            n_store += len(store_rows)
            _write_store_chunk(store_rows, writer_store, schema_store)
            store_rows = []
            
    if store_rows:
        n_store += len(store_rows)
        _write_store_chunk(store_rows, writer_store, schema_store)
    cur.close()
    
    return n_qty, n_store

def main():
    print("=" * 60)
    print("  Lost Product Historical Cache Builder (2021-2025) — Streaming")
    print("=" * 60)
    
    os.makedirs(CACHE_DIR, exist_ok=True)
    cfg = _load_cfg()
    conn = _conn(cfg)
    print(f"Connected to data-lake at {cfg['host']}")
    
    custom_metadata = {
        b'built_by': b'antigravity-gemini-3-flash',
        b'rule_hash': RULE_HASH.encode('utf-8'),
        b'timestamp': datetime.now().isoformat().encode('utf-8')
    }
    
    schema_qty = pa.schema([
        ('year', pa.int16()),
        ('iprod', pa.string()),
        ('qty', pa.float32())
    ]).with_metadata(custom_metadata)
    
    schema_store = pa.schema([
        ('year', pa.int16()),
        ('whs', pa.string()),
        ('iprod', pa.string()),
        ('qty', pa.float32()),
        ('amt', pa.float32())
    ]).with_metadata(custom_metadata)
    
    qty_path = os.path.join(CACHE_DIR, 'lost_qty_2021_2025.parquet')
    store_path = os.path.join(CACHE_DIR, 'lost_store_2021_2025.parquet')
    
    print(f"Initializing ParquetWriter for:\n  -> {qty_path}\n  -> {store_path}")
    writer_qty = pq.ParquetWriter(qty_path, schema_qty, compression='SNAPPY')
    writer_store = pq.ParquetWriter(store_path, schema_store, compression='SNAPPY')
    
    total_qty_rows = 0
    total_store_rows = 0
    
    try:
        for year, config in sorted(YEAR_TABLES.items()):
            bld, blh, filter_yr = config
            print(f"\nProcessing year {year} tables...", flush=True)
            t_start = datetime.now()
            n_qty, n_store = query_and_write_year(
                conn, year, bld, blh, filter_yr,
                writer_qty, writer_store, 
                schema_qty, schema_store
            )
            total_qty_rows += n_qty
            total_store_rows += n_store
            duration = (datetime.now() - t_start).total_seconds()
            print(f"  Done in {duration:.1f}s | {n_qty:,} products | {n_store:,} store-product entries streamed", flush=True)
    finally:
        conn.close()
        print("\nClosing Parquet writers...", flush=True)
        writer_qty.close()
        writer_store.close()
        
    print("\nCache generation completed successfully!", flush=True)
    print(f"  Total product-qty rows saved: {total_qty_rows:,}", flush=True)
    print(f"  Total store-product rows saved: {total_store_rows:,}", flush=True)
    print("=" * 60)

if __name__ == '__main__':
    main()
