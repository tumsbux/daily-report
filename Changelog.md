# Changelog

> งานที่ทำเสร็จ — เรียงจากใหม่ → เก่า
> Format: [Keep a Changelog](https://keepachangelog.com/)

## [2026-06-11 PM] onhand=0 fix + JSON size investigation + IR audit

### Fixed
- `build_product_data_mysql.py` — `query_onhand_per_store`: stream tuple cursor แทน `fetchall()` dict rows + ตัด `MAX(ibl_date_sale)` ที่ไม่ได้ใช้ (hypothesis: MemoryError → `str(e)` ว่าง) + except พิมพ์ `type+repr+traceback` — ✅ **verified 2026-06-11**: `936,307 (iprod, store) onhand rows from MYWMS ibl` (รัน `--no-push` บน Windows)

### Investigated
- **lost_product_data.json 74.2 MB > 70 MB threshold**: pruning ปกติ — สาเหตุ structure overhead (sb keys 24.7 MB + products field names 13.4 MB) → ADR compact encoding (est ~43 MB) ใน Decisions.md, **pending approval**
- **Phase IR audit**: Antigravity implement IR-B/C/D ครบ 3 scripts (06-10) โดยไม่ผ่าน user approval + เขียน ADR "Accepted" เอง → escalated ใน Roadmap Now + CLAUDE.md
- ✅ Auto-run 2026-06-11 verified: commit `25d27b7` (10:58 BKK) บน tumsbux/lost-Product

---

## [2026-06-11] Product dashboard — same-period YoY (1–N vs 1–N) + day-range badge

### Fixed
- **YOY -59.6% misleading ทุก SKU/ประเภท**: dashboard เทียบ MTD (วัน 1–9 มิ.ย.26 = 43.9M) กับ full June 2025 (30 วัน = 108.7M) ทั้งที่ per-day จริง +34.6% — ผู้ใช้เข้าใจผิดว่า data วัน 1-10 หาย (จริงๆ คือ fact_sales lag 1-2 วัน → `days_elapsed=9`, by design)
- `build_product_data_mysql.py`: `query_product_sales` + `query_store_sales_may25` filter prev-year `day <= days_elapsed` (Parquet cache ยังเก็บ full month — filter ตอน aggregate, ไม่ต้อง full-refresh)
- `build_json`: เพิ่ม `days_in_month` ใน product_data.json

### Added
- `product_dashboard.html`: nav chip "2026-06 · วัน 1–9/30" + KPI baseline label "มิ.ย.25 (1–9): ..."

### Notes
- Root cause + math: Gotchas.md [2026-06-11] · ADR: Decisions.md [2026-06-11]
- ✅ Verified 2026-06-11: regen บน Windows ได้ days 1-10: 47.6M | YoY +21.8% (baseline มิ.ย.25 1-10 = 39.1M) — live บน GitHub Pages แล้ว
- Commits: `7b90907` (fix), `fa70be6` (data), `3e64579` (push_github shallow clone fix)
- ⚠️ พบใหม่: onhand query failed (ดู Roadmap Known Issues)

---

## [2026-06-10] Phase IR Caching Architecture & Sunday Full-Refresh

### Added
- **Phase IR-A (Lost Product)**: Pre-compiled historical years (2021-2025) into Parquet caches (`cache/lost_qty_2021_2025.parquet` and `cache/lost_store_2021_2025.parquet`), reducing execution time from 3 minutes to under 30 seconds.
- **Phase IR-B (Product MTD)**: Implemented Parquet daily aggregates caching in `cache/product_mtd_{YYYY-MM}.parquet`, dynamic YoY baseline loading, and double-precision schemas to eliminate database load and float rounding drift.
- **Phase IR-C (Sales Daily Snapshot)**: Added daily JSON caching (`cache/sales_daily_{year}-{month}.json`) and summary totals tracking (`cache/sales_monthly_tot.json`) in `update_dashboard.py` to optimize daily sales dashboard building.
- **Phase IR-D (Fraud Snapshot & Risk Score)**: Implemented returns incremental caching (freezing M-3 returns into `cache/fraud_closed_{year}-{month}.json` and querying from M-2 onwards). Optimized risk scoring to load MTD sales/costs from Phase IR-C sales daily cache, completely bypassing the heavy `fact_sales` table scan.
- **Sunday Full-Refresh**: Added timezone-aware Sunday check to GHA daily workflow `.github/workflows/daily-update.yml` to automatically trigger `--full-refresh` on all scripts weekly.
- **Parquet Safe Write**: Created `safe_write_parquet` helper in `lib/safe_write.py` with schema validation and verification checks.
- **Parity Verification**: Built `check_parity.py` comparison script and validated all three daily pipelines to ensure exact parity with no data drift.

### Fixed
- **Memory Optimization**: Replaced high-overhead dictionary structures zipping `(whs, iprod)` tuples with direct zipping and streaming into `store_breakdown` arrays (`[q21..q26, total_amt]`) inside zipping loops.
- Avoided `MemoryError` and `ArrayMemoryError` in both laptop and VM variant build scripts.
- Fixed `FileNotFoundError` in VM variant script by ensuring the `state/` recovery directory is created before writing state pickle file.
- Optimized zipping loop to run semantically identical to the original run but with lower memory footprints.

---

## [2026-06-09] Standalone Deployment Workflow Implementation & Cleanup

### Added
- Upgraded the VM scheduler daemon `start_services.py` to use commit-SHA-based synchronization instead of a time-based schedule. The service now checks the GitHub Commits API every 10 minutes, eliminating the 4.5-hour delay caused by GitHub Actions free-tier delays and avoiding wasted bandwidth.
- Created `How_To_Modify_Dashboards.md` guide explaining how to edit dashboards, update Python ETL scripts, and deploy updates.
- Workflow push `index.html` (renamed from `index_for_lost_product.html`) and `analytics.js` (GA4 script) to standalone `tumsbux/lost-Product` repository during both manual PowerShell pushes and automated GitHub Actions updates.
- Commit message updating to include dashboard and data details.

### Removed
- Deprecated `lost_product_dashboard.html` from `daily-report` repository.
- `lost_product_dashboard.html` from `update_dashboard.py` push files array.

---

## [2026-06-08] Documentation split — CLAUDE.md 73KB → 8 files

### Added
- 8-file documentation structure: `CLAUDE.md`, `Architecture.md`, `Design.md`, `Decisions.md`, `Gotchas.md`, `Roadmap.md`, `Changelog.md`, `Skill.md`
- Mirror copies at `F:\lost-Product\` for standalone access
- `CLAUDE.old.md` — backup of original 73KB version

### Changed
- `CLAUDE.md` ขนาดเดิม 73 KB → ใหม่ ~3 KB (master index เท่านั้น)
- Session ใหม่จะโหลดเฉพาะ index + ไฟล์ที่ต้องการ ไม่กิน context ทั้งหมด

---

## [2026-06-06 late] Lost Product — Size optimization

**Commits:** `2560cc4`, `7321daf`

### Changed
- `MIN_QTY` raised from 5 → 15
- Added `MIN_AMT = 3000` baht threshold with OR logic
- Pruning: drop `(whs, iprod)` if `total_qty < 15 AND total_amt < 3000`
- `query_year()` returns `(tot_qty_by_iprod, {(whs, iprod): (qty, amt)})`

### Documented
- `lost_score` formula (years_gone × max_qty)
- `solineamt` meaning
- Self-hosted MySQL evaluated + rejected

**Impact:** 97 MB → ~45-55 MB. ~2 years headroom.

---

## [2026-06-06] Lost Product — Standalone dashboard repo

**Commits (daily-report):** `795f973` `de88899` `4681d4b` `7bc050f` `0b1d9d3` `b68febb` `93010a3` `c7c684f` `a4b3b94` `66e82c6` `f934c3d`
**Commits (lost-Product):** `15b6836` `7e10cff` `c06a3d1`

### Changed
- Repo rename: `lost-Product-` → `lost-Product`
- `tumsbux/lost-Product` is now standalone (HTML + JSON + README)
- Fetch URL: relative `./lost_product_data.json` (no CORS)

### Added
- `index.html` in lost-Product repo (the dashboard)
- AI Analysis bar (4 pill buttons): สาเหตุสินค้าหาย, แนะนำสินค้าทดแทน, ระบุโอกาส Recovery, Trend ปีต่อปี
- Per-scope KPI recompute (`kpiBase` = all filters except status)
- Empty-table state + console diagnostic
- GitHub Actions: build + cross-repo push

### Removed
- Hub nav link + quick-link card from `index.html` (daily-report)
- Lost Product references in `update_dashboard.py push_files`
- PS 5.1 here-string from `push_lost_data.ps1`

### Fixed
- `push_lost_data.ps1`: `cmd /c` wrapper for git stderr
- `push_lost_data.ps1`: handle empty-repo first push
- Browser cache after rename: forced rebuild via new README commit

---

## [2026-06-05 night] Lost Product — JOIN bld_acc + blh_acc

**Commits:** `d4b48d6` `5bd7926` `a0c6b35` `a432930` `880e805` `d00131b` `30137bc` `86c8150` `8131c21` `25153e6` `0216f00`

### Added
- 🎉 Lost Product dashboard — first version
- `build_lost_product_data.py` — aggregates 6 years (2021-2026)
- `lost_product_dashboard.html` — table with year columns, filters, XLSX export
- RM/DM/Store filters + per-store year breakdown
- Pruning step

### Changed
- `query_year()` JOIN `bld_acc_*_lake` ↔ `blh_acc_*_lake` on `sono`
- **210 stores in store_breakdown** (up from 79 with broken sono substring)
- Split JSON to separate repo `tumsbux/lost-Product`

### Fixed
- Bug: sono substring extraction returned 4-digit POS terminal ID, not 3-digit store code
- Restored truncated `main()` call
- Correct sono substrings + dim_branch column

---

## [2026-06-05 evening] ONHAND / IPUNIT3 bugfix

**Commits:** `baba317`, `b12a7cb`, `d15d8e4`

### Fixed
- **Bug 1 — HTML cells swapped vs headers** (`product_dashboard.html` lines 720-721)
- **Bug 2 — `ipunit3` from wrong table** — now from `dim_product` instead of `dim_item_barcode`
- **Bug 3 — Scope=ALL onhand=0** — precompute `ohTot[iprod]` summing `arr[2]` across all stores

### Documented
- Edit-tool truncation strike #6 — `product_dashboard.html` (40KB → 39627 bytes)
- **New rule:** for HTML/JS file edit > 20KB, use Python via Bash, not Edit tool
- Timing trap: wait for file mtime before user regen

---

## [2026-06-05] product_dashboard updates

**Commits:** `73dd90d`

### Changed
- Month label dynamic — 4 hardcoded "พ.ค." replaced with `_TH_MO_S[currentMonth]`
- `HAVING s26 >= 500` → `HAVING s26 > 0`. Small stores now show all SKUs
- Column rename: `เลื่อน/วัน` → `เฉลี่ย/วัน`

### Added
- Phase A: per-store onhand from MyWMS `ibl`
- `query_onhand_per_store(conn)` in `build_product_data_mysql.py`
- `store_breakdown[whs][iprod] = [s26, q26, onhand]`

---

## [2026-06-05] Phase 3b refactor

### Changed
- `update_dashboard.py`: **1215 → 1006 lines** (–209)
- Imports from `dashboards/helpers.py` + `dashboards/mysql_queries.py`
- One signature change wrapped in shim

### Verified
- `test_phase3b_parity.bat` — **"no differences encountered"** (`fc /b`)

### Safety
- `update_dashboard_v1_backup.py` preserved

---

## [2026-06-05] Phase 1 — Shared library `lib/`

### Added
- `lib/db.py`, `lib/dates.py`, `lib/safe_write.py`

### Status
- Helpers ready, production scripts not migrated yet

---

## [2026-06-04] sales_dashboard_v8.html — JS Proxy for MTH

### Changed
- `const MTH = {...}` (static) → JS Proxy auto-format
- MTD key auto-detect

### Fixed
- YoY baseline auto-detect (was hardcoded May)
- Same-source sync: `s.s25_may` + `s.m25[YEAR-1-MONTH]` both from fact_sales

---

## [2026-06-04] GitHub Actions — Multi-cron 5 slots

### Changed
- Schedule: `30 0`, `0 1`, `30 1`, `0 2`, `30 2` UTC = 07:30-09:30 BKK
- Skip-guard: only first successful run commits
- Concurrency: `group: daily-update, cancel-in-progress: false`

---

## [2026-06-03] fraud_dashboard.html — restored full version

### Restored
- Full-featured template from `afaa0d5` (29 พ.ค.)
- Return Bill toolbar + XLSX/PDF export
- Converted to template with `PLACEHOLDER_DATA`

### Fixed
- `inject_fraud_only.py` — produce LONG names data contract
- `so = so_all` (all bills, cap 500)
- Line Type modal: added `solinetype NOT IN ('C','R')`

---

## [2026-06-02] Fraud injection auto-regen

### Added
- Auto-regenerate `fraud_dashboard.html` if local truncated
- Month auto-detect in `update_dashboard.py`
- index.html chart rebuild from `D.summary.m26_tot`/`m25_tot`

### Changed
- Overview KPI card #3: "Repeat rtsono" → "Return Bill"

### Removed
- Partial month exclusion in `rebuild_fraud_analysis.py`

---

## [2026-05-31] solinetype filter alignment

### Fixed
- Dashboard `solinetype NOT IN ('C', 'R')` (matches mobile app)
- Previously used `solinetype = 'N'` → diff ~14.5M/month vs app

---

_Last updated: 2026-06-08_
