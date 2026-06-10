# Decisions (ADR)

> **A**rchitecture **D**ecision **R**ecord
> **กฎ:** ก่อนเปลี่ยน/revert อะไรที่อยู่ในไฟล์นี้ → ต้องอ่าน + อัปเดต record ก่อน

---

## [2026-06-04] GitHub Actions — Multi-cron 5 slots 07:30-09:30 BKK

**Status:** Accepted

**Context:** GH Actions free tier cron delay 0-5 ชม. รอบเดียวอาจ delay ไปหลายชั่วโมง

**Decision:** ตั้ง 5 cron slots ทุก 30 นาที (UTC `30 0`, `0 1`, `30 1`, `0 2`, `30 2`) = 07:30-09:30 BKK. รอบที่ commit สำเร็จเป็นรอบแรก รอบที่เหลือ skip ผ่าน guard step

**Consequences:**
- ✅ Hit เกือบ 08:30 BKK ทุกวัน
- ✅ Free tier ใช้ได้
- ⚠️ ต้อง skip-guard ป้องกัน duplicate run

---

## [2026-06-04] Data timing — เริ่ม cron ที่ 07:30 ไม่ใช่ 06:00

**Status:** Accepted

**Context:** fact_sales / fact_returns ETL จริงเข้าที่ 07:00 BKK. รัน cron ก่อนหน้านั้น query data เก่า

**Decision:** รอบเร็วสุด 07:30 BKK (+30 นาที buffer)

---

## [2026-06-XX] Fraud step `continue-on-error: true`

**Status:** Accepted

**Context:** ถ้า fraud rebuild fail → ไม่ควรหยุด sales pipeline เพราะ sales สำคัญกว่า

**Decision:** `continue-on-error: true` บน fraud step

**Consequences:**
- ✅ Sales updates แม้ fraud fail
- ⚠️ Yellow warning ใน Actions UI = ปกติ

---

## [2026-06-05] Phase 1: Extract shared library `lib/`

**Status:** Accepted (scripts not yet migrated — Phase 3 work)

**Context:** 13 duplicate `get_conn()` blocks กระจายทั่ว scripts

**Decision:** สร้าง `lib/db.py`, `lib/dates.py`, `lib/safe_write.py`

**Consequences:**
- ✅ Single source of truth
- ✅ `safe_write_*` ช่วยกัน Edit tool truncation bug
- ⚠️ Production scripts ยังไม่ได้ migrate — new scripts ต้องใช้ใหม่

---

## [2026-06-05] Phase 3a/3b: Extract `dashboards/` package

**Status:** Accepted, verified via byte-diff

**Context:** `update_dashboard.py` = 1215 บรรทัด มี helpers + queries ปนกัน

**Decision:** แตกเป็น `dashboards/helpers.py` + `dashboards/mysql_queries.py`. ใช้ `import ... as` alias

**Verification:** `test_phase3b_parity.bat` → `fc /b` รายงาน "no differences encountered" ทั้ง `sales_dashboard_v8.html` และ `index.html`

**Consequences:**
- ✅ 1215 → 1006 lines (–209)
- ✅ Helpers reusable
- ⚠️ One signature change wrapped in shim (`_query_fact_sales_may25` → `query_prev_year_same_month(cfg, YEAR, MONTH)`)
- Safety: `update_dashboard_v1_backup.py` retained

---

## [2026-06-04] YoY baseline — same-source sync

**Status:** Accepted

**Context:** Header card อ่าน `s.s25_may` (จาก fact_sales) แต่ monthly list อ่าน `s.m25[YYYY-MM]` (legacy) → ต่างกัน ~26 บาท/store

**Decision:** หลัง set `s.s25_may` → set `s.m25[YEAR-1-MONTH] = round(s25)` ด้วย (3 levels)

**Consequences:**
- ✅ Header + list อ่านจาก fact_sales เดียวกัน ตรงเป๊ะ
- ⚠️ ฟังก์ชันยังชื่อ legacy แต่ทำงาน dynamic

---

## [2026-06-04] sales_dashboard_v8.html `MTH` — JS Proxy dynamic

**Status:** Accepted

**Context:** `const MTH = {...}` (static dict) ขาด keys + label ผิด

**Decision:** แทนด้วย JS Proxy auto-format ทุก key `YYYY-MM` เป็น `ม.ค. 25` style

**Consequences:**
- ✅ Persist ข้าม daily run (ไฟล์ static ไม่ถูก regen)
- ✅ ไม่ต้อง update wired-up labels ทุกเดือน

---

## [2026-06-03] Fraud template — restore full-featured version

**Status:** Accepted

**Context:** ช่วงต้น มิ.ย. มี fraud template "ย่อ" มาแทน → Return Bill toolbar หาย

**Decision:** กู้กลับจาก git commit `afaa0d5` (29 พ.ค.) แปลงเป็น template (embed data → `PLACEHOLDER_DATA`)

**Consequences:**
- ✅ Toolbar กลับมา + export ใช้ได้
- ⚠️ Data contract = LONG names — `inject_fraud_only.py` ต้องผลิตตรงนี้
- ⚠️ Backup minimal version ที่ `fraud_analysis_template_minimal_bak.html` — **อย่าใช้อีก**

---

## [2026-06-05] Phase A: Per-store onhand from MyWMS.ibl

**Status:** Accepted

**Decision:** Query `MYWMS2023_CENTER.ibl WHERE locno='stock' AND shelfno='shelfno'`. `iprod = ibl_parcode` direct match (86.6% verified). เพิ่มเป็น 3rd array element ใน `store_breakdown[whs][iprod] = [s26, q26, onhand]`

**Consequences:**
- ✅ Per-store onhand displays correctly
- ✅ Backward compatible

---

## [2026-06-05] ipunit3 source = `dim_product` not `dim_item_barcode`

**Status:** Accepted

**Context:** `dim_item_barcode` ไม่มี column `ipunit3` → ทั้ง 13,077 products `ipunit3=0`

**Decision:** Source `ipunit3` from `dim_product`. Defensive `_dim_product_columns()` helper

**Consequences:**
- ✅ 13,074/13,077 products มี ipunit3 nonzero

---

## [2026-06-05] Lost Product builder — JOIN bld_acc + blh_acc

**Status:** Accepted (replaces sono-substring extraction)

**Context:** เคย extract store จาก `SUBSTRING(sono,3,4)` → ได้ POS terminal ID, ไม่ใช่ store. Only 79 stores in store_breakdown (should be 210)

**Decision:** JOIN `bld_acc_*_lake` ↔ `blh_acc_*_lake` on `sono`. ใช้ `blh.sotowhs` (3-digit) + `blh.sodate` DATETIME

**Consequences:**
- ✅ 210 stores in store_breakdown
- ✅ Year filter ใช้ `YEAR(blh.sodate)` ตรงๆ
- ⚠️ Detail table alone ไม่มี store/date — ต้อง JOIN เสมอ

---

## [2026-06-05/06] Lost Product — split to separate repo → standalone

**Status:** Accepted (current state)

**Context:** `lost_product_data.json` หลัง JOIN+per-store = 50-120MB. GitHub hard-rejects > 100MB

**Decision (evolution):**
- 2026-06-05: แยก JSON ไป `tumsbux/lost-Product` repo (data only)
- 2026-06-06: ย้าย `index.html` (dashboard) เข้าไปด้วย → standalone, fetch URL relative `./lost_product_data.json`

**Consequences:**
- ✅ Clean URL: https://tumsbux.github.io/lost-Product/
- ✅ No cross-origin fetch
- ⚠️ Workflow ต้อง push 2 ไฟล์ไป repo แยก
- ⚠️ ลบ Hub link + quick-link card จาก index.html
- ⚠️ `daily-report/lost_product_dashboard.html` deprecated

---

## [2026-06-06] MIN_QTY 5 → 15 + MIN_AMT=3000 OR logic

**Status:** Accepted

**Context:** `lost_product_data.json` แตะ 97 MB (GitHub limit 100MB)

**Decision:** Pruning rule — drop `(whs, iprod)` if `total_qty < 15 AND total_amt < 3000`. Keep if qty≥15 OR amt≥3000

**Implementation:** `query_year()` returns `(tot_qty, {(whs, iprod): (qty, amt)})`

**Consequences:**
- ✅ 97 MB → ~45-55 MB (-40-50%)
- ✅ ~2 years headroom before next ceiling

---

## [2026-06-06] Self-hosted MySQL backend — Rejected

**Status:** Rejected

**Context:** Move dashboard data to own MySQL host?

**Decision (Rejected):**
- MySQL alone can't serve dashboards (browser can't talk MySQL directly)
- Would need: web server + PHP/Node + CORS + HTTPS + maintenance
- Cheap VPS ($5/mo) feasible but overkill
- GitHub Pages + pruning gives 2+ years headroom

**Revisit if:** growth > 70 MB by end June 2026

---

## [2026-06-09] Standalone dashboard deployment workflow implementation

**Status:** Accepted

**Context:**
หลังจากย้าย `index.html` ไปอยู่ใน `lost-Product` repo แยก, ตัว workflow daily update และสคริปต์ manual push ยังคง push แค่ `lost_product_data.json` ทำให้เวลาข้อมูลอัปเดต ตัว UI ใน standalone repo ไม่ได้รับอัปเดตล่าสุด และ GA4 analytics.js ขาดหายไปบน standalone domain

**Decision:**
1. ปรับปรุง `.github/workflows/daily-update.yml` และ `push_lost_data.ps1` ให้ copy `index_for_lost_product.html` (เปลี่ยนชื่อเป็น `index.html`) และ `analytics.js` ไปยัง temp clone folder แล้วทำการ stage + commit + push ไปยัง standalone repo พร้อมกับ JSON data
2. ลบ `lost_product_dashboard.html` ที่ deprecated ออกจาก `daily-report` repository และอัปเดต `update_dashboard.py` เพื่อนำออกจาก push list

**Consequences:**
- ✅ หน้า dashboard standalone (https://tumsbux.github.io/lost-Product/) ได้รับการอัปเดตทุกวัน
- ✅ แก้ไขปัญหา GA4 `analytics.js` 404 บน standalone repo
- ✅ ทำความสะอาดไฟล์ที่ deprecated ใน `daily-report` เรียบร้อย

---

## [2026-06-10] Phase IR-A: Lost Product Caching via Parquet & Caching 2025

**Status:** Accepted

**Context:**
Lost Product dashboard ETL queries 6 years of transaction history. Static historical years (2021-2025) do not change but querying them daily from cloud MySQL caused slow builds (~3 minutes) and MemoryError when loaded into memory structures on the VM (2.0 GB ceiling). The year 2025 is fully finalized and closed but resides in the active `bld_acc_lake`/`blh_acc_lake` tables, making dynamic queries scan half the active tables (~7 million rows) and taking over 2-3 minutes.

**Decision:**
1. Pre-compile 2021-2025 data into compressed Parquet cache files (`cache/lost_qty_2021_2025.parquet` and `cache/lost_store_2021_2025.parquet`).
2. Load the cache files using Pandas/PyArrow and run sargable range queries only on the current year table (2026).
3. Eliminate `store_amt_total` mapping table to prevent MemoryError under 2GB ceiling.
4. Add `pyarrow` to the GitHub Actions daily update runner to support Parquet deserialization.

**Consequences:**
- ✅ Query time dropped from 3 minutes to under 30 seconds (over 6x faster).
- ✅ DB load reduced dramatically.
- ✅ Eliminated MemoryError on both laptop and VM.

---

## [2026-06-10] Phase IR-B, IR-C, and IR-D Caching Architecture

**Status:** Accepted

**Context:**
The rest of the daily ETL scripts (Product MTD, Sales Daily Snapshot, and Fraud Risk scoring) still query large tables like `fact_sales` and `fact_returns` for full month or multi-month intervals. This triggers full table scans on MySQL, causing the daily pipeline to take over 2 minutes and pushing memory usage close to the VM's 2GB ceiling.

**Decision:**
1. **Phase IR-B (Product MTD)**: Implement `cache/product_mtd_{YYYY-MM}.parquet` file keyed on `(whs, iprod, day)` to store daily aggregates. Daily run queries `fact_sales` only for the last 7 days (`D-7..D-1`), upserts them into the cache, and aggregates MTD from the cache. Prior year same month baseline is queried once, frozen, and loaded from cache.
2. **Phase IR-C (Sales Daily Snapshot)**: Implement `cache/sales_daily_{YYYY-MM}.json` to store daily store sales `{store: {day: {sales, cost, txn}}}`. Daily run queries `D-7..D-1` of `fact_sales` and `whsdd` actuals to patch the cache. Past months' trend totals are read from `cache/sales_monthly_tot.json`.
3. **Phase IR-D (Fraud Returns)**: Freeze `M-3` historical returns as `cache/fraud_closed_{YYYY-MM}.json`. Daily run only queries returns starting from `M-2` start and merges with frozen history. For risk scoring, read current month's MTD sales and cost from Phase IR-C sales daily cache, completely bypassing the heavy `fact_sales` query.
4. **Sundays Full-Refresh**: Auto-detect Sunday (Bangkok time) in the GitHub Actions runner, and execute daily scripts with `--full-refresh` flag to fully rebuild caches.
5. **Safeguards**: Add `safe_write_parquet()` in `lib/safe_write.py` with schema validation and re-read checks. Cache files include version `v: 2` and rule hash in headers; any mismatch triggers automatic full-refresh.

**Consequences:**
- ✅ All daily dashboard ETL runs will finish in under 30 seconds.
- ✅ Memory overhead on the VM remains extremely low (well below 2GB).
- ✅ Eliminates redundant queries to database tables.
- ✅ Transparent Sunday reconciliation window handles late POS adjustments automatically.

---

## 📚 Superseded

- ~~`solinetype = 'N'` filter~~ (pre-2026-05-31) → `solinetype NOT IN ('C','R')` to match mobile app
- ~~Static `const MTH = {...}`~~ (pre-2026-06-04) → JS Proxy dynamic
- ~~`fact_sales` only for YoY card~~ (pre-2026-06-04) → same-source sync
- ~~`so = so[so['lines']>1]` for Return Bill~~ (pre-2026-06-03) → `so_all` (all bills, cap 500)

---

_Last updated: 2026-06-10_

