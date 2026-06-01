# CLAUDE.md — Dashboard System Context

**Project:** Tuensjai Panichkroup Co., Ltd. — Data Dashboard Suite  
**Owner:** data.inwza.008@gmail.com (tumsbux)  
**Working directory:** `F:\co work dashboard\`  
**GitHub Pages:** https://tumsbux.github.io/daily-report/  
**Repo:** github.com/tumsbux/daily-report (branch: `main`)

---

## ⚡ Quick Context (อ่านก่อนเริ่ม)

ระบบ Dashboard อัปเดตอัตโนมัติทุกวัน 08:30 Bangkok ผ่าน **GitHub Actions** (ไม่ต้องเปิด laptop)
- MySQL อยู่บน cloud ✅
- GitHub Pages อยู่บน cloud ✅
- GitHub Actions รัน script บน cloud ✅

**เมื่อมีปัญหา dashboard ไม่แสดง:** ดู section "Known Issues & Fixes" ด้านล่าง

---

## System Overview

A fully automated daily reporting system. Python scripts query a cloud MySQL data lake, embed results as JSON blobs inside static HTML files, then push those files to GitHub Pages. No server required at runtime.

**Daily pipeline (GitHub Actions — 08:30 Bangkok / 01:30 UTC) — ไม่ต้องเปิด laptop:**
1. `rebuild_fraud_analysis.py --no-push` → builds fraud_data.json from MySQL  *(continue-on-error)*
2. `build_product_data_mysql.py --no-push` → builds product_data.json from MySQL  *(continue-on-error)*
3. `update_dashboard.py` → updates sales + injects fraud/product data → pushes all to GitHub Pages

**Note:** ตั้งแต่ June 2026 เป็นต้นไป workflow ใช้ auto-detect day จาก fact_sales (ลบ `--day 30` ออกแล้ว 2026-05-31)

**Cowork Scheduled Task:** ⛔ Disabled — replaced by GitHub Actions above

**Manual run (if needed):**
```powershell
# One-command script (auto-detect day)
& "F:\co work dashboard\run_manual_update.ps1"

# หรือระบุ day เอง
& "F:\co work dashboard\run_manual_update.ps1" -Day 30
```

หรือรันแยก step:
```
py "F:\co work dashboard\rebuild_fraud_analysis.py" --no-push
py "F:\co work dashboard\build_product_data_mysql.py" --no-push
py "F:\co work dashboard\update_dashboard.py"
```

---

## GitHub Actions Workflow

**File:** `.github/workflows/daily-update.yml`  
**Schedule:** `cron: '30 1 * * *'` (08:30 Bangkok)  
**Secrets required** (set in github.com/tumsbux/daily-report/settings/secrets/actions):

| Secret | Source |
|--------|--------|
| `DB_HOST` | db_config.json → "host" |
| `DB_PORT` | db_config.json → "port" |
| `DB_USER` | db_config.json → "user" |
| `DB_PASSWORD` | db_config.json → "password" |
| `DB_DATABASE` | db_config.json → "database" |
| `GH_PAT` | db_config.json → "github_token" |

**Fraud step has `continue-on-error: true`** — if fraud rebuild fails, sales dashboard still updates.

**Manual trigger:** github.com/tumsbux/daily-report/actions/workflows/daily-update.yml → Run workflow

---

## File Inventory

| File | Purpose |
|------|---------|
| `update_dashboard.py` | Master daily runner. Queries MySQL, updates all dashboards, pushes to GitHub. |
| `rebuild_fraud_analysis.py` | Fraud ETL. Queries fact_returns, builds fraud_data.json. Run BEFORE update_dashboard.py. |
| `inject_fraud_only.py` | Fast re-inject. Updates fraud_dashboard.html from existing fraud_data.json without re-querying MySQL. |
| `build_product_data.py` | Builds product_data.json from fact_sales JOIN dim_product. |
| `push_py_to_github.py` | One-shot script to push Python scripts and HTML files to GitHub via API. |
| `test_mysql_connection.py` | Diagnostic: verifies MySQL connection and shows fact_returns row counts. |
| `test_rebuild_now.bat` | Runs rebuild_fraud_analysis.py with --no-push, logs to rebuild_test.log. |
| `run_inject_fraud.bat` | Runs inject_fraud_only.py, logs to inject_fraud.log. |
| `sales_dashboard_v8.html` | Main sales dashboard (served internally to team). |
| `index.html` | Dashboard Hub — KPI summary + navigation to all sub-dashboards. |
| `fraud_dashboard.html` | Fraud Detection Dashboard — tabs for Overview, Store Risk, Cashiers, Bills, Time, etc. |
| `fraud_analysis_template.html` | Template/reference version of the fraud dashboard (not the live file). |
| `fraud_data.json` | Serialised fraud analysis data; re-injected into fraud_dashboard.html daily. |
| `product_dashboard.html` | Top products by sales value with YoY; built by build_product_data.py. |
| `product_data.json` | Serialised product data; stamped with today's date on every push. |
| `db_config.json` | **SECRETS — never commit.** Contains MySQL host/user/password and github_token. |
| `target.txt` | Daily store targets from MYPOS2018_CENTER.whsdd (~29MB). Fallback if MySQL down. |
| `data-lake_fact_returns.sql` | Static export of fact_returns (~1MB). Fallback if MySQL down. |
| `DASHBOARD_UPDATE_GUIDE.md` | Thai-language data dictionary and manual update guide. |
| `Dashboard_Blueprint_2026.docx` | Full developer reference document (architecture, bug history, setup checklist). |

---

## Credentials

All secrets live in `db_config.json` (local only, never pushed to GitHub):

```json
{
  "host":         "<MySQL cloud host>",
  "port":         3306,
  "user":         "<db username>",
  "password":     "<db password>",
  "database":     "<schema name>",
  "github_token": "ghp_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
}
```

---

## Data Sources & Key Logic

### Source tables (MySQL cloud data lake)

| Table | Content |
|-------|---------|
| `MYPOS2018_CENTER.whsdd` | Daily store targets (`whsddptar`) and actuals (`whsddpact`). Also fallback: `target.txt`. |
| `fact_returns` | Return bills. Use `allocated_net_amount` (NOT `line_amount_inc_vat`). Filter `rtstatus='U'`. |
| `fact_sales` | Sales lines. Use `net_sales_amt`, `sotowhs` (store code), `sono` (bill no), `solinetype='N'`. |
| `dim_product` | Product dimension for the product dashboard. |

### Store filtering rule
```python
def valid_store(code):
    try:    return int(code) <= 500
    except: return False   # excludes 901, 902, 903, 904, 999, WBT, WHC, WPT etc.
```

### Core formulas
```
Net MTD Sales   = whsddpact − allocated_net_amount (returns)
GP Amount       = net_sales_amt − total_cost
GP%             = GP Amount / net_sales_amt × 100
Daily Rate      = Net MTD / days_elapsed
Projected       = Daily Rate × 31
Projected YoY   = (Projected / May 2025 full month − 1) × 100
Avg Ticket      = Net MTD / txn_mtd
vs Target MTD%  = Net MTD / Σ whsddptar (days 1–N)
Proj vs Target% = Projected / Σ whsddptar (days 1–31)
```

### Data embedded in HTML files
Each HTML file contains a `const D = {...}` JavaScript blob. Scripts use brace-matching to safely replace this block (see `extract_json()` in update_dashboard.py).

---

## update_dashboard.py — Step-by-Step Flow

1. Load targets from MySQL `MYPOS2018_CENTER.whsdd` (fallback: `target.txt`)
2. Load unfinalized days from `factDD.txt` files
3. Load returns from MySQL `fact_returns` (fallback: `data-lake_fact_returns.sql`)
4. Load existing dashboard HTML, extract `const D={}` JSON
5. Update each store — compute net sales, daily rate, projected, GP, txn, ticket avg, YoY
6. Aggregate stores → DM → RM → Summary
7. Save `sales_dashboard_v8.html` + update `<span id="td-days">N</span>`
8. Update `index.html` Hub — KPI values, day badge, RM table, trend chart
9. Sync returnXX.txt → `returnall.txt`
10. Inject fraud_data.json into `fraud_dashboard.html`
11. Push to GitHub (clone temp repo → copy files → commit → push → delete temp)

**Files pushed to GitHub:** `index.html`, `sales_dashboard_v8.html`, `fraud_dashboard.html`, `fraud_analysis.html`, `fraud_data.json`, `product_dashboard.html`, `product_data.json`

---

## Data Reconciliation Note (2026-05-31)

### Dashboard vs Mobile App (เตือนใจ) — May 1–30, 2026

| รายการ | Mobile App | Dashboard | หมายเหตุ |
|---|---|---|---|
| ยอดขาย net | 131,103,395 | 116,577,335 | ต่างกัน 14.5M |
| ยอดคืน | 540,758 | 540,758 | ✅ ตรงกันทุกบาท |
| GP% | 33.35% | 34.21% | App มี non-N lines ที่ GP ต่ำ |
| จำนวนบิล | 897,794 | 865,283 | |

**Root cause:** App ใช้ `solinetype NOT IN ('C', 'R')` แต่ dashboard ใช้ `solinetype = 'N'`  
ส่วนต่าง ~14.5M = sales จาก line types อื่น (promotions, services, etc.) ที่ไม่ใช่ N/C/R  
**Day 30 daily:** App 4,529,874 vs Dashboard 4,031,469 — ต่างกัน ~498K (same root cause)  
**Returns ตรงกันทุกบาท** = fact_returns query ถูกต้อง ✅  
**Fix applied (2026-05-31):** เปลี่ยน `solinetype = 'N'` → `solinetype NOT IN ('C', 'R')` ทุกจุดใน `update_dashboard.py` (3 queries) และ `build_product_data_mysql.py` (4 queries) → dashboard จะตรงกับ app

---

## Known Issues & Fixes (2026-05-31 session — part 7 — product dashboard)

### Problem: product_dashboard.html — Store-level YoY แสดงผิด (-98% แทน -7.9%)
**Symptom:** กรอง store 006 → ยอดขาย พ.ค.25 แสดง 28.2M แทนที่จะเป็น 989K → YoY = -98.2% (ผิดมาก)  
**Root cause:** `p.s25` ใน product JSON = all-stores total (ทุกร้านรวมกัน) ไม่ใช่ per-store  
  เมื่อกรอง store 006 → May26 = 498K (ถูก จาก store_breakdown) แต่ May25 = 28.2M (ผิด sum all products)  
**Fix applied:**
- **Python (`build_product_data_mysql.py`):** เพิ่ม `query_store_sales_may25(conn)` → query May 2025 per store → เพิ่ม `s25_may` ใน `store_info` ของ JSON
- **JS (`product_dashboard.html`):** เพิ่ม `s25Scope` variable → เมื่อมี filter (store/DM/RM) ใช้ `sum(store_info[whs].s25_may)` แทน `sum(p.s25)` ใน `renderSummary()`
**Pattern:** store_breakdown มีแค่ May 2026 per-store per-product — May 2025 ต้องแยก query และเก็บใน store_info
**Follow-up fix:** เพิ่ม `query_store_sales_may26()` → `s26_may` ใน store_info → JS ใช้ `s26Scope` แทน sum(p.s26) ใน header KPI เพื่อแก้ปัญหา HAVING>=500 ทำให้ header ต่ำกว่าจริง

---

## Known Issues & Fixes (2026-06-01) — product_dashboard & build_product_data_mysql

### Changes: product_dashboard.html — store-level KPI & Line Type button
**store-level s26 header KPI fix:**
- เพิ่ม `query_store_sales_may26(conn, days_elapsed)` → `s26_may` per store ใน `store_info`
- JS: `s26Scope` = sum of `store_info[whs].s26_may` เมื่อมี filter → header แสดงยอดจริงแทนที่จะ sum จาก HAVING>=500 products
- ก่อน fix: store 006 แสดง 645K (ขาด ~395K จาก products < 500฿) → หลัง fix: 1,040K ตรงกับ sales dashboard

**Line Type button:**
- เพิ่ม `query_sales_by_linetype(conn, days_elapsed)` → `linetype_breakdown` array ใน JSON
- JS: ปุ่ม "📋 Line Type" ใน filter bar → modal แสดงยอดขาย/บิล/ชิ้น per solinetype
- Responsive: `width:min(540px,96vw)`, `overflow-x:auto`, `@media(max-width:480px)`

**Full responsive CSS:**
- 900px: summary cards 3 คอลัมน์
- 600px: filter labels ซ่อน, selects ยืดเต็ม, cards 2 คอลัมน์
- 400px: font/padding เล็กสุด

---

## Known Issues & Fixes (2026-06-01) — GA4 Analytics

### GA4 Tracking Added
- **Measurement ID:** `G-E3ZFFKXFT8` (property: "Tuenjai Dashboard")
- **analytics.js** — shared tracking module, included in all 4 HTML files via `<script src="analytics.js">`
- **Events wired:** `dashboard_viewed`, `filter_applied`, `filter_reset`, `view_changed`, `sort_changed`, `linetype_modal_viewed`, `search_performed`, `data_load_failed`, `dashboard_navigated`
- **7 Custom Dimensions** registered in GA4 Admin: `dashboard_name`, `filter_scope`, `filter_rm`, `filter_dm`, `filter_store`, `days_elapsed`, `data_month`
- **Telemetry docs:** `.telemetry/` folder — `product.md`, `tracking-plan.yaml`, `delta.md`, `instrument.md`
- **Note:** `analytics.js` ต้องอยู่ใน push_files ของ `update_dashboard.py` — ตรวจสอบถ้า GA4 หายหลัง daily run

### Bug Fix: product_dashboard.html — pag-btns/pag-info null ref
**Symptom:** "โหลดข้อมูลล้มเหลว" error แสดงแม้ข้อมูลโหลดได้  
**Root cause:** `renderPagination()` เรียก `getElementById('pag-btns')` และ `getElementById('pag-info')` แต่ HTML มีแค่ `id="p-prev"`, `id="p-next"`, `id="p-info"` → null → TypeError → `.catch()` รับ  
**Fix:** เปลี่ยน HTML pagination container เป็น `<div id="pag-btns">` และ `<span id="pag-info">`

---

## Known Issues & Fixes (2026-06-01) — rebuild_fraud_analysis.py

### Problem: fraud script — MySQL sales MTD = 0 เมื่อรันวันที่ 1 ของเดือนใหม่
**Symptom:** `MySQL sales MTD: 0 stores | ฿0` → fall back to whsdd → แสดง 205 stores แทน 203
**Root cause 1:** `DATE_FORMAT(CURDATE(), '%Y-%m-01')` = '2026-06-01' เมื่อรันวัน 1 มิ.ย. → query June ซึ่งยังไม่มีข้อมูล
**Root cause 2:** `solinetype = 'N'` ไม่ตรงกับ app / scripts อื่น
**Root cause 3:** filter `NOT IN ('901','999')` รวม stores 501-900 → 205 stores แทน 203
**Fix applied:** auto-detect latest month ด้วย `MAX(DATE_FORMAT(sodate, '%Y-%m-01'))` จาก fact_sales + เปลี่ยนเป็น `solinetype NOT IN ('C','R')` + เพิ่ม `BETWEEN 1 AND 500` filter

## Known Issues & Fixes (2026-06-01)

### Problem: update_dashboard.py — DAYS_ELAPSED=1 เมื่อรันวันที่ 1 ของเดือนใหม่
**Symptom:** รันวัน 1 มิ.ย. → `today.day - 1 = 0` → `max(1,0) = 1` → query แค่ May day 1 → dashboard แสดง 4.8M MTD แทน ~135M  
**Root cause:** `DAYS_ELAPSED = max(1, today.day - 1)` ไม่รองรับ month boundary  
**Fix applied:** เพิ่ม fact_sales auto-detect ก่อน set DAYS_ELAPSED — query `MAX(DAY(sodate))` จาก fact_sales สำหรับ YEAR/MONTH ที่กำหนด → ถ้าพบ (เช่น 31) ใช้ค่านั้น; fallback ไป `today.day - 1` เฉพาะเมื่อ query ล้มเหลว  
**Pattern:** เมื่อเริ่มเดือนใหม่ ให้ใช้ `-Day 31` (manual) หรือ auto-detect จาก fact_sales แทน date.today()

---

## Known Issues & Fixes (2026-05-31 session — part 6)

### Problem: update_dashboard.py — "fact_sales MTD gross" ใน log แสดงตัวเลขพองผิด (double-count)
**Symptom:** Log แสดง `fact_sales: 278 stores | ฿166M MTD gross` แต่ Workbench query จริงๆ ได้แค่ ~117M สำหรับ stores 1–500  
**Root cause:** `_query_fact_sales_mtd` เก็บ dict entry เดียวกัน (same object reference) ใน 2–3 keys ต่อร้าน (`'1'`, `'001'`) เพื่อให้ lookup ได้ทุก format แต่ `sum(v['sales'] for v in result.values())` นับทุก key → double-count  
**Fix applied:** ใช้ `{id(v): v for v in _fact_sales_mtd.values()}` เพื่อ deduplicate by object identity ก่อน sum → แสดงตัวเลขที่ถูกต้อง  
**Note:** การคำนวณ sales จริงๆ ใน STEP 5 ถูกต้องตลอด (ใช้ `.get(code)` ทีละร้าน) — แค่ log line ผิด  
**Reconcile:** Workbench 131.7M (May 1–31, NOT IN 901/999) − day31 (4.55M) − stores>500 (~10M) − returns (0.54M) = 116.6M ✓

---

## Known Issues & Fixes (2026-05-31 session — part 5)

### Problem: update_dashboard.py — YoY Projected แสดง -1.3% แทนที่จะเป็น +11.4% (s25_may baseline ผิด)
**Symptom:** Sales dashboard แสดง Projected YoY = -1.3% แต่ product dashboard แสดง +11.4% YoY  
**Root cause:** `s25_may` ใน dashboard HTML ถูก populate จาก `whsddpact` May 2025 (~122M per RM total) ซึ่งสูงกว่า `fact_sales` May 2025 (105M) — สองระบบคำนวณยอด 2025 ต่างกัน  
**Fix applied:** เพิ่ม `_query_fact_sales_may25(cfg)` — query `fact_sales` สำหรับ May 2025 ต่อร้าน → ใน STEP 5 อัปเดต `s25_may`, `txn_may25`, `ticket_avg_25`, `daily_txn_25` ทุกรอบจาก fact_sales 2025 แทน HTML เดิม  
**Pattern:** ค่า YoY ต้องใช้ fact_sales ทั้งปี 2025 และ 2026 เพื่อให้ฐานเดียวกัน — whsddpact 2025 ≠ fact_sales 2025

---

## Known Issues & Fixes (2026-05-31 session — part 4)

### Problem: update_dashboard.py — Daily Rate / Projected ต่ำกว่าจริง (fact_sales ล้าหลัง ~3 วัน)
**Symptom:** `--day 30` ทำให้ `DAYS_ELAPSED=30` ถูกใช้เป็นตัวหาร แต่ `fact_sales` มีข้อมูลแค่ถึงวัน 27 → Daily Rate = 27วัน/30 ต่ำกว่าจริง → Projected ต่ำ → RM/DM/Store Projected ต่ำทุกระดับ  
**Root cause:** Same pattern as build_product_data_mysql.py — fact_sales lags ~3 days behind DAYS_ELAPSED  
**Fix applied:** เพิ่ม `MAX(DAY(sodate)) AS max_day_seen` ใน `_query_fact_sales_mtd()` → สร้าง `FACT_DAYS` global = actual max day in fact_sales → ใช้ `FACT_DAYS` แทน `DAYS_ELAPSED` เป็น denominator ใน daily/daily_txn/ret_daily ทุกจุด (store loop, `aggregate()`, summary)  
**Two separate variables:**
- `DAYS_ELAPSED` = query window + displayed day number (from `--day` or yesterday)  
- `FACT_DAYS` = actual coverage days in fact_sales (auto-detected, may be < DAYS_ELAPSED)  
**Pattern:** MTD totals ยังถูกต้อง (sum ตาม actual data), แต่ rate/projection ต้องหารด้วย FACT_DAYS ไม่ใช่ DAYS_ELAPSED

---

## Known Issues & Fixes (2026-05-31 session — part 3)

### Problem: build_product_data_mysql.py — ยอดขายต่ำกว่าความเป็นจริง (fact_sales ล้าหลัง ~3 วัน)
**Symptom:** Dashboard แสดง 117M แทน ~130M เพราะ `fact_sales` มีข้อมูลถึงแค่ ~27 พ.ค. แต่ `days_elapsed` คำนวณจาก `date.today()` = 30  
**Root cause:** `fact_sales` data lake ล้าหลัง ~3 วันเสมอ ทำให้วัน 28–30 มียอด 0 แต่ถูกนับรวมในช่วงเวลา  
**Fix applied:** เพิ่ม `detect_max_day(conn)` — query `MAX(DAY(sodate))` จาก `fact_sales` จริง (พร้อม store filter) แล้วใช้ค่านั้นเป็น `days_elapsed` แทน `date.today()`  
**Logic:** ถ้าไม่มี `--day` → auto-detect จาก fact_sales | ถ้ามี `--day N` → ใช้ N (override)  
**Pattern to remember:** `fact_sales` ล้าหลัง ~3 วัน, `whsddpact` ล้าหลัง 1–2 วัน — ทั้งคู่ต้อง detect จาก MySQL ไม่ใช่ `date.today()`

---

## Known Issues & Fixes (2026-05-31 session — part 2)

### Problem: build_product_data_mysql.py — MySQL GROUP BY error (only_full_group_by)
**Error:** `Expression #2 of SELECT list is not in GROUP BY clause ... incompatible with sql_mode=only_full_group_by`  
**Root cause:** The new dual-JOIN query (`dim_product dp` + `dim_product dp2` via `dim_item_barcode`) had non-aggregated columns from `dp2` not in GROUP BY.  
**Fix applied:** Wrapped all dp/dp2 text columns in `MIN()` → `GROUP BY fs.iprod` only.  
**Pattern to remember:** MySQL `only_full_group_by` mode requires every SELECT column to be either aggregated or in GROUP BY. Use `MIN(col)` for dimension columns when grouping by a key.

### Problem: Product name shows barcode instead of product name (e.g. 8859828701185)
**Root cause:** Some `fact_sales` rows store the barcode value as `iprod` instead of the product code. `LEFT JOIN dim_product ON dp.iprod = fs.iprod` fails (no match). `COALESCE(dp.idesc, fs.iprod)` returns the barcode string as the name.  
**Example:** `fs.iprod = '8859828701185'`, `dim_item_barcode.parcode = '011033123'`, `dim_product.idesc = 'ถังฝา20gl.สีดำ(CNN)'`  
**Fix applied:** Added `LEFT JOIN dim_item_barcode dib ON dib.barcode = fs.iprod` + `LEFT JOIN dim_product dp2 ON dp2.iprod = dib.parcode` → `COALESCE(MIN(dp.idesc), MIN(dp2.idesc), fs.iprod) AS name`

### Problem: Store filter shows wrong products (top-500 only, wrong amounts)
**Root cause 1:** `store_breakdown` was product-indexed (`{iprod: {whs: {sales,qty}}}`) with top-500 limit. Products outside top-500 fell through and returned global data → wrong totals.  
**Root cause 2:** Structure didn't support efficient RM/DM aggregation.  
**Fix applied:** Changed to store-indexed `{whs: {iprod: [s26, q26]}}` covering ALL products (threshold ≥500 baht). JS now aggregates across all stores in scope.

## Known Issues & Fixes (2026-05-31 session)

### Problem: product_dashboard.html shows no data (all "—")
**Root cause:** `Write` tool truncated the file mid-JavaScript at line 447 (~20KB). The `</script></body></html>` tail was missing, so the browser couldn't parse the script.  
**Symptom:** Filter bar and table headers render but all cards show "—" and table bodies are empty.  
**Fix applied:** Appended missing JS functions (renderTypeCats, renderGrpCats, renderProdPage, pagination, sort) + closing tags.  
**Prevention:** After any Write of large HTML files, verify with `tail -5` that the file ends with `</html>`. Complete `product_dashboard.html` ≈ 31KB+. If smaller, it's truncated.

### Problem: GitHub Actions didn't update dashboard at 08:30 on May 31
**Root cause:** `update_dashboard.py` auto-detects "yesterday" = May 30, but `whsddpact` in MySQL lags 1-2 days. May 30 data may not be finalized, causing wrong projections or a crash.  
**Fix applied:** Hardcoded `--day 30` in workflow (`daily-update.yml`) for May 2026.  
**⚠️ Action required June 1:** Remove `--day 30` from workflow so it auto-detects again.

### Problem: days_elapsed shows 31 on May 31 (too high, data only through day 30)
**Root cause:** `build_product_data_mysql.py` set `days_elapsed = date.today().day` = 31, inflating เลื่อน/วัน and เฉลี่ย/สัปดาห์ calculations.  
**Fix applied:** Changed to `days_elapsed = min(today.day - 1, 30)` for May (capped at 30, uses yesterday).

---

## Known Issues & Fixes (2026-05-30 session)

### Problem: Dashboard shows blank white page (no content rendered)
**Root cause:** `sales_dashboard_v8.html` was truncated — file cut off mid-JavaScript inside `render()` function. Missing closing braces, `goHome()` init call, `</script></body></html>`.  
**Symptom:** Header/topbar renders (static HTML) but `#app` div is empty.  
**Fix applied:** Appended missing JS tail to restore complete file.  
**Prevention:** If dashboard goes blank again, check file size. Complete file ≈ 290KB+. If smaller, the file is truncated.

### Problem: Charts not rendering (blank chart boxes, no graphs)
**Root cause:** Chart.js `integrity` (SRI) attribute in `<script>` tag had wrong hash — browser blocks the script silently.  
**Fix applied:** Removed `integrity` and `crossorigin` attributes from the Chart.js `<script>` tag in `sales_dashboard_v8.html`.  
**Prevention:** Never add `integrity=` attribute to CDN script tags unless you have verified the exact hash. Use:
```html
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.5.0/dist/chart.umd.js"></script>
```

### Problem: index.html Hub charts blank (monthly trend + RM chart)
**Root cause:** `index.html` was truncated — cut off mid-JavaScript at `font:{size:` inside the Chart.js options block.  
**Symptom:** KPI cards render fine but chart areas are blank.  
**Fix applied:** Appended missing 90 chars of JS tail + `</script></body></html>`.  
**Prevention:** Complete `index.html` ≈ 18,968 bytes. If smaller, it's truncated. Restore from git: `git show ff2f7b5:index.html > index.html`

### Problem: fraud_dashboard.html showing blank charts
**Root cause:** `fraud_dashboard.html` was also truncated (local file corrupted, overwritten to GitHub).  
**Fix applied:** Restored complete template from git history (`ff2f7b5`) and re-injected current `fraud_data.json`.  
**Prevention:** If fraud charts go blank, restore from git history:
```bash
git show ff2f7b5:fraud_dashboard.html > fraud_dashboard.html
py inject_fraud_only.py
```
Or run the full rebuild: `py rebuild_fraud_analysis.py`

### Problem: GitHub Actions workflow failing on fraud step
**Root cause:** Unknown (possibly large query timeout or network issue).  
**Fix applied:** Added `continue-on-error: true` and `timeout-minutes: 15` to fraud rebuild step.  
**Result:** Sales dashboard always updates even if fraud rebuild fails.

### Problem: Day count shows wrong number (30 instead of 29)
**Root cause:** `whsddpact` in MySQL lags 1–2 days. Running with `--day 30` when MySQL only has day 29 data gives wrong projections.  
**Fix:** Always use `--day N` where N = last day with finalized `whsddpact` data. Check via:
```sql
SELECT MAX(whsdddd) FROM MYPOS2018_CENTER.whsdd 
WHERE whsddyyyy=2026 AND whsddmm=5 AND whsddpact > 0
```

---

## Dashboard Views

### index.html — Hub
- Hero KPIs: ยอดขาย MTD, vs เป้า MTD, Projected, YoY Projected, GP%
- 4 KPI cards: Run Rate, Avg Ticket, Bills/store/day, Returns/store
- RM table with progress bars
- Monthly trend chart (m25vals / m26vals)

### sales_dashboard_v8.html — Sales
| View | Content |
|------|---------|
| Home (`home`) | KPI cards, Gauge YoY, Monthly Trend chart |
| RM (`rm`) | RM detail + DM sub-table + chart |
| DM (`dm`) | DM detail + Store table + chart |
| Store (`store`) | Store KPI + Monthly chart |
| Executive (`exec`) | 7-section executive report; `excTarget = total_target × 1.155` (+15.5% corporate challenge) |
| Report (`report`) | RM cards + DM table + charts |

### fraud_dashboard.html — Fraud Detection
Tabs: Overview · Store Risk · พนักงาน (rtuname) · rtsono ซ้ำ · เวลา · ร้าน · DM · RM  
Risk badges: HIGH / MEDIUM / LOW in nav bar.

---

## D.summary JSON Key Fields

```
days_elapsed, days_remaining, total_mtd, total_target, total_mtd_target,
total_pct_target, total_proj, total_proj_vs_tgt, total_s25, total_proj_yoy,
total_gp_mtd, total_gp_pct, total_txn, total_daily_txn, total_ticket_avg,
total_ticket_avg_25, total_ticket_avg_yoy, total_txn_yoy, total_ret_mtd,
total_ret_daily, total_ret_per_store, m26_tot {YYYY-MM: amount}, m25_tot {YYYY-MM: amount}
```

---

## Daily Manual Update Checklist

When running manually (or when auto-scheduler missed a day):

1. Ensure `db_config.json` is present with valid credentials
2. Run: `py "F:\co work dashboard\rebuild_fraud_analysis.py" --no-push`
3. Run: `py "F:\co work dashboard\update_dashboard.py" --day N`
   - N = last day with finalized MySQL data (check whsddpact)
   - Omit `--day` to auto-detect (yesterday's date)
4. Verify printed summary for MTD total, GP%, transactions
5. Dashboard live at https://tumsbux.github.io/daily-report/ within ~1 min

**If only fraud dashboard needs updating:** `run_inject_fraud.bat`

---

## Developer Setup (New Machine)

1. Install Python 3 + `pip install mysql-connector-python pandas openpyxl`
2. Create `F:\co work dashboard\db_config.json` with MySQL credentials + GitHub PAT (repo write scope)
3. Test MySQL: `py test_mysql_connection.py`
4. Full run: `py rebuild_fraud_analysis.py --no-push && py build_product_data_mysql.py --no-push && py update_dashboard.py`
5. Add the 6 secrets to GitHub repo → Settings → Secrets → Actions (DB_HOST, DB_PORT, DB_USER, DB_PASSWORD, DB_DATABASE, GH_PAT)
6. **Never commit `db_config.json`**
7. Cowork Scheduled Task: already disabled — GitHub Actions handles everything

---

## Common Pitfalls

- **`<span id="td-days">N</span>`** must be updated every run. If skipped, dashboard shows stale day number.
- **Both files must match:** `sales_dashboard_v8.html` and `index.html` must always contain the same underlying data.
- **Store code padding:** MySQL may return `'1'`, `'001'`, or `1` (int). Scripts store both raw and padded keys.
- **rebuild_fraud_analysis.py must run BEFORE update_dashboard.py** — master runner reads `fraud_data.json` that rebuild produces.
- **`whsddpact` may lag 1–2 days** — use `--day N` with N = last finalized day, not today.
- **File truncation:** If a script crashes mid-write, HTML files can be truncated (missing JS tail). Dashboard goes blank. Restore from git: `git show <commit>:<file> > <file>` then re-inject data.
- **Chart.js SRI hash:** Never add `integrity=` attribute to Chart.js CDN tag — it breaks silently if hash mismatches.
- **GitHub Actions fraud step:** Has `continue-on-error: true` — a yellow warning on fraud step is normal and safe.
