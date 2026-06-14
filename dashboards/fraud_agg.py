"""
dashboards/fraud_agg.py — Fraud analysis aggregation functions (Phase 3d, 2026-06-14)

Extracted from rebuild_fraud_analysis.py:
  - _rec(d)
  - _build_product_agg(sub)
  - _build_reason_agg(sub)
  - build_month(sub)
"""

import json
import pandas as pd


# ── AGGREGATION HELPERS ────────────────────────────────────────────────────────
def _rec(d):
    return json.loads(d.fillna('?').to_json(orient='records', force_ascii=False))

def _build_product_agg(sub, barmap=None, prodmap=None):
    """Aggregate by product. Uses pre-joined parcode/idesc (barmap/prodmap ignored)."""
    agg = sub.groupby('iprod').agg(
        return_qty=('return_qty', 'sum'),
        bills=('rtsono', 'nunique'),
        amount=('amount', 'sum'),
        parcode=('parcode', 'first'),
        idesc=('idesc', 'first'),
    ).reset_index()
    agg['barcode']    = agg['iprod'].astype(str)
    agg['return_qty'] = agg['return_qty'].fillna(0).round(0).astype(int)
    agg = agg[['barcode', 'parcode', 'idesc', 'return_qty', 'bills', 'amount']]
    agg = agg.sort_values('amount', ascending=False)  # no cap — export all products
    records = json.loads(agg.fillna('').to_json(orient='records', force_ascii=False))

    for rec in records:
        bc = rec['barcode']
        sub_bc = sub[sub['iprod'] == bc].copy()
        grp = sub_bc.groupby('rtsono').agg(
            cashier=('rtuname', 'first'), fullname=('fullname', 'first'),
            whs=('whs', 'first'), store_name=('store_name', 'first'),
            return_date=('return_date', 'first'), rttime=('rttime', 'first'),
            return_qty=('return_qty', 'sum'), amt=('amount', 'sum'),
        ).reset_index()
        grp['return_qty'] = grp['return_qty'].fillna(0).round(0).astype(int)
        grp['amt']        = grp['amt'].fillna(0).round(0)
        grp = grp.sort_values('amt', ascending=False).head(50)
        if 'return_date' in grp.columns and pd.api.types.is_datetime64_any_dtype(grp['return_date']):
            grp = grp.copy()
            grp['return_date'] = grp['return_date'].dt.strftime('%Y-%m-%d').where(grp['return_date'].notna(), '')
        rec['bills_list'] = json.loads(grp.fillna('').to_json(orient='records', force_ascii=False))
    return records

def _build_reason_agg(sub):
    """Dominant-reason aggregation — no double-counting per bill."""
    if 'rtrdesc' not in sub.columns:
        return []
    sub = sub.copy()
    sub['rtrdesc'] = sub['rtrdesc'].fillna('').str.strip()
    sub.loc[sub['rtrdesc'] == '', 'rtrdesc'] = 'ไม่ระบุเหตุผล'

    dominant = (sub.sort_values('amount', ascending=False)
                   .groupby('rtsono')['rtrdesc'].first()
                   .reset_index()
                   .rename(columns={'rtrdesc': 'dominant_reason'}))
    sub = sub.merge(dominant, on='rtsono', how='left')

    returns_agg = sub.groupby('rtrdesc').agg(
        returns=('rtno', 'count'), amount=('amount', 'sum'),
        stores=('whs', 'nunique'), cashiers=('rtuname', 'nunique'),
    ).reset_index()
    bills_agg = sub.groupby('dominant_reason')['rtsono'].nunique().reset_index()
    bills_agg.columns = ['rtrdesc', 'bills']
    agg = returns_agg.merge(bills_agg, on='rtrdesc', how='left')
    agg['bills'] = agg['bills'].fillna(0).astype(int)
    agg = agg.sort_values('amount', ascending=False)
    records = json.loads(agg.fillna('').to_json(orient='records', force_ascii=False))

    dom_map = dominant.set_index('rtsono')['dominant_reason'].to_dict()
    for rec in records:
        reason = rec['rtrdesc']
        sonos  = [s for s, dr in dom_map.items() if dr == reason]
        sub_r  = sub[sub['rtsono'].isin(sonos)].copy()
        grp = sub_r.groupby('rtsono').agg(
            cashier=('rtuname', 'first'), fullname=('fullname', 'first'),
            whs=('whs', 'first'), store_name=('store_name', 'first'),
            return_date=('return_date', 'first'), rttime=('rttime', 'first'),
            amt=('amount', 'sum'),
        ).reset_index()
        grp['amt'] = grp['amt'].fillna(0).round(0)
        grp = grp.sort_values('amt', ascending=False).head(100)
        if 'return_date' in grp.columns and pd.api.types.is_datetime64_any_dtype(grp['return_date']):
            grp = grp.copy()
            grp['return_date'] = grp['return_date'].dt.strftime('%Y-%m-%d').where(grp['return_date'].notna(), '')
        rec['bills_list'] = json.loads(grp.fillna('').to_json(orient='records', force_ascii=False))
    return records

def build_month(sub, barmap=None, prodmap=None):
    """Build all aggregations for one month (or ALL). barmap/prodmap ignored."""
    sub = sub.copy()

    # All return bills (per rtsono). The Return Bill table shows EVERY bill.
    # so_dup (>1 line) is kept separately for the Repeat-SO fraud-signal stats.
    so_all = sub.groupby('rtsono').agg(
        lines=('rtno', 'count'), amount=('amount', 'sum'),
        cashier=('rtuname', 'first'), fname=('fullname', 'first'),
        store=('whs', 'first'), store_name=('store_name', 'first'),
        dm=('dm', 'first'), rm=('rm', 'first'),
        zero=('is_zero', 'sum'), date=('return_date', 'first'),
        time=('rttime', 'first'),
    ).reset_index()
    so_dup = so_all[so_all['lines'] > 1]                  # >1 line — Fraud Signals stat only
    so = so_all.sort_values('amount', ascending=False)    # ALL bills — Return Bill table
    # Convert date (datetime64 → 'dd-mm-yyyy') before JSON serialization
    if 'date' in so.columns and pd.api.types.is_datetime64_any_dtype(so['date']):
        so = so.copy()
        so['date'] = so['date'].dt.strftime('%d-%m-%Y')
    so_list = json.loads(so.fillna('?').to_json(orient='records', date_format='iso', force_ascii=False))

    # Product detail per rtsono — for every bill shown (all of them, no cap)
    _shown = {r.get('rtsono') for r in so_list}
    detail_map = (
        sub[sub['rtsono'].isin(_shown)]
        .groupby(['rtsono', 'iprod'])
        .agg(amount=('amount', 'sum'), return_qty=('return_qty', 'sum'),
             parcode=('parcode', 'first'), idesc=('idesc', 'first'))
        .reset_index()
        .sort_values(['rtsono', 'amount'], ascending=[True, False])
    )
    detail_dict = {}
    for sono, grp in detail_map.groupby('rtsono'):
        items = []
        for _, row in grp.iterrows():
            items.append({
                'barcode': str(row['iprod']),
                'parcode': str(row['parcode']),
                'idesc':   str(row['idesc']),
                'qty':     int(row['return_qty']) if not pd.isna(row['return_qty']) else 0,
                'amt':     round(float(row['amount']), 2),
            })
        detail_dict[sono] = items
    for r in so_list:
        r['detail'] = detail_dict.get(r.get('rtsono'), [])

    # rtuname
    rtu = sub.groupby(['rtuname', 'fullname', 'whs', 'store_name', 'dm', 'rm']).agg(
        returns=('rtno', 'count'), amount=('amount', 'sum'),
        zero=('is_zero', 'sum'), uso=('rtsono', 'nunique'),
    ).reset_index()
    rtu['rep']   = rtu['returns'] - rtu['uso']
    rtu['zp']    = (rtu['zero'] / rtu['returns'] * 100).round(1)
    mx_a = max(rtu['amount'].max(), 1); mx_r = max(rtu['rep'].max(), 1)
    rtu['score'] = ((rtu['amount']/mx_a*40) + (rtu['zp']/100*35) + (rtu['rep']/mx_r*25)).round(1)
    rtu = rtu.sort_values('amount', ascending=False)

    # Store
    st = sub.groupby(['whs', 'store_name', 'dm', 'rm']).agg(
        returns=('rtno', 'count'), amount=('amount', 'sum'),
        cashiers=('rtuname', 'nunique'), zero=('is_zero', 'sum'),
    ).reset_index()
    st['zp'] = (st['zero'] / st['returns'] * 100).round(1)
    st = st.sort_values('amount', ascending=False)

    # DM
    dm = sub.groupby(['dm', 'rm']).agg(
        returns=('rtsono', 'nunique'), amount=('amount', 'sum'),
        stores=('whs', 'nunique'), cashiers=('rtuname', 'nunique'),
        zero=('is_zero', 'sum'), row_cnt=('rtno', 'count'),
    ).reset_index()
    dm['zp'] = (dm['zero'] / dm['row_cnt'] * 100).round(1)
    dm = dm.drop(columns=['row_cnt']).sort_values('amount', ascending=False)

    # RM
    rm = sub.groupby('rm').agg(
        returns=('rtsono', 'nunique'), amount=('amount', 'sum'),
        stores=('whs', 'nunique'), cashiers=('rtuname', 'nunique'),
        zero=('is_zero', 'sum'), dms=('dm', 'nunique'),
        row_cnt=('rtno', 'count'),
    ).reset_index()
    rm['zp'] = (rm['zero'] / rm['row_cnt'] * 100).round(1)
    rm = rm.drop(columns=['row_cnt']).sort_values('amount', ascending=False)

    # Hour / Day
    hr = sub.groupby('hour').agg(returns=('rtno', 'count'), amount=('amount', 'sum')).reset_index()
    hr = hr[hr['hour'].notna()].copy(); hr['hour'] = hr['hour'].astype(int); hr = hr.sort_values('hour')
    dy = sub.groupby('day').agg(returns=('rtno', 'count'), amount=('amount', 'sum')).reset_index()
    dy['day'] = dy['day'].astype(int); dy = dy.sort_values('day')

    za = float(sub[sub['is_zero']]['amount'].sum())
    na = float(hr[hr['hour'].isin([22, 23])]['amount'].sum()) if len(hr) else 0.0

    return {
        'stats': {
            'n':          int(sub['rtsono'].nunique()),
            'total':      float(sub['allocated_net_amount'].sum() if 'allocated_net_amount' in sub.columns else sub['amount'].sum()),
            'n_rtu':      int(sub['rtuname'].nunique()),
            'n_store':    int(sub['whs'].nunique()),
            'n_zero':     int(sub['is_zero'].sum()),
            'zero_amt':   za,
            'n_so_dup':   int(len(so_dup)),
            'so_dup_amt': float(so_dup['amount'].sum()),
            'night_amt':  na,
        },
        'rtu':     _rec(rtu.head(600)),
        'store':   _rec(st.head(250)),
        'dm':      _rec(dm),
        'rm':      _rec(rm),
        'hour':    _rec(hr),
        'day':     _rec(dy),
        'so':      so_list,
        'product': _build_product_agg(sub),
        'reason':  _build_reason_agg(sub),
    }
