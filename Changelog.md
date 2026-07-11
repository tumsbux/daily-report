# Changelog

> งานที่ทำเสร็จ — เรียงจากใหม่ → เก่า
> Format: [Keep a Changelog](https://keepachangelog.com/)

## [2026-07-11] Fix: MySQL disconnect in lost-Product's build_lost_product_data.py + dual-pipeline race on lost_product_data.json (Claude, Cowork)

### Root cause 1 — MySQL disconnect (same bug as [2026-07-10] store discount fix, this time in lost-Product repo)
- GHA run #87/#88 in `tumsbux/lost-Product` today: job "Success" but "Build lost product data" step failed exit code 1 (masked by `continue-on-error`)
- Fixed directly in `F:\lost-Product\build_lost_product_data.py` (user granted folder access) — same fresh-connection-per-query + retry-on-errno-2013/2006 pattern. See that repo's Decisions.md/Changelog `[2026-07-11]`. Pushed by user via `push_lost_product_files.py`.

### Root cause 2 — dual-pipeline race on lost_product_data.json (found after fix #1 deployed — GHA run #89)
- With the MySQL bug fixed, a NEW failure appeared: "Commit and push rebuilt JSON" step in `lost-Product`'s own workflow hit a `git pull --rebase` conflict on `lost_product_data.json`
- Cause: this repo (`daily-report`) ALSO built + pushed its own copy of `lost_product_data.json` to `tumsbux/lost-Product`, racing against `lost-Product`'s own daily-update.yml doing the same. Minified single-line JSON can't be 3-way-merged by git — second pusher always conflicts.
- Verified the local build in this repo was unused (`lost_product_dashboard.html` fetches cross-origin from `tumsbux.github.io/lost-Product/lost_product_data.json`, not the local file)

### Fixed — `.github/workflows/daily-update.yml` (this repo)
- Removed "Build lost product data" step entirely
- "Push lost-Product dashboard and data..." step renamed, no longer pushes `lost_product_data.json` — only `index.html`/`analytics.js`
- ADR: Decisions.md `[2026-07-11]`

### Not yet pushed
- Fix is local only — needs `push_files_api.py` to deploy `.github/workflows/daily-update.yml`, Decisions.md, Changelog.md to `tumsbux/daily-report`

## [2026-07-10] Fix: silent MySQL disconnect crash in build_store_discount_data.py (Claude, Cowork)

### Root cause
- GHA run #187 (Jul 10, manual, "succeeded" green ✓ in 24m24s) actually had **2 failed steps** masked by `continue-on-error: true`:
  - `Build store discount data` → `mysql.connector.errors.OperationalError: 2013 (HY000): Lost connection to MySQL server during query` (crashed inside the 92-day `query_range()` query)
  - `Build lost product data` → same exit-code-1 pattern (different script, not touched in this fix)
- Because both steps have `continue-on-error: true`, the job showed all-green even though `store_discount_data.json` never got rebuilt/pushed — this is why the live dashboard kept showing `generated_at: 2026-07-09T20:30:00` no matter how many times the pipeline ran afterward
- Likely trigger: this step runs LAST (after ~17 min of other DB-heavy steps), and/or the 92-day×203-store aggregation query itself is heavy enough to exceed the MySQL server's connection/read timeout

### Fixed — `build_store_discount_data.py`
- `query_range()`: no longer takes one long-lived connection for the whole window. Now chunks the date range into `CHUNK_DAYS=14`-day pieces, each on its **own fresh connection**, with retry (`MAX_QUERY_RETRIES=3`, 5s backoff) on errno 2013/2006 ("lost connection"/"server has gone away")
- `query_product_detail()`: same fix — opens its own connection per call with the same retry wrapper (was sharing one connection across both product-detail days)
- `build()`: updated call sites accordingly (`load_branches` still uses one short-lived conn; the two heavy queries manage their own now)
- Verified via reconstructed-copy `python3 -m py_compile` (bash mount shows stale content immediately after Write/Edit — established workaround from earlier in this project)

### Fixed — `.github/workflows/daily-update.yml`
- Job-level `timeout-minutes: 30` → `65`. Step-level timeouts sum to 55 min (15+10+15+15) which could exceed the old 30-min job cap and force-kill the run mid-pipeline before it reached `store_discount_data.json`/`update_dashboard.py`

### Not yet done
- `build_lost_product_data.py` has the identical exit-code-1 symptom — not investigated/fixed in this pass (different script, out of scope for this dashboard fix)

### Push
- Pushed commit `5d90b8a0` (fix above) — verified via commit `f1244bb` on `store_discount_data.json` showing fresh `generated_at: 2026-07-10T03:47:07`, schema 2 (correct)

## [2026-07-10] Fix: `generated_at` timestamp was UTC, not Bangkok time (Claude, Cowork)

### Root cause
- `datetime.now()` on the GHA runner (Ubuntu, UTC) was used directly for `generated_at` in `store_discount_data.json` / per-store product files / commit messages — dashboard displayed it raw, so it showed 7 hours behind actual Bangkok time (e.g. `03:47` instead of `10:47`)

### Fixed — `build_store_discount_data.py`
- Added `now_bkk()` helper using `zoneinfo.ZoneInfo('Asia/Bangkok')`, replacing all `datetime.now()` calls used for `generated_at` and commit messages (4 call sites)
- Verified via `python3 -m py_compile` (reconstructed-copy method — bash mount showed stale/truncated content immediately after the edit, established gotcha, not a real syntax error)

### Push
- Pushed commit `708f404e`

## [2026-07-10] Fix: `push_github_tree()` 401 Unauthorized on per-store product bulk push (Claude, Cowork)

### Root cause (probable — not 100% confirmed, monitor next runs)
- Discovered only after the MySQL disconnect fix above let the pipeline get further: `push_github_tree()` (bulk-pushes ~202 `store_discount_products/<whs>.json` files as one commit) started failing with `HTTP Error 401: Unauthorized` on `POST repos/{repo}/git/blobs`
- Same GitHub token succeeded on the main `store_discount_data.json` push moments earlier in the same run — rules out expired/bad token
- Likely cause: ~202 sequential POST requests in a tight loop trips GitHub's secondary rate-limit/abuse-detection system, which is known to sometimes report `401` instead of the usual `403` for this failure mode

### Fixed — `build_store_discount_data.py`
- `push_github_tree()`'s inner `api()` helper: now retries on `401`/`403` (in addition to `5xx`) with the same backoff, instead of raising immediately
- Added a 1-second pause every 20 blob-upload calls to reduce the chance of tripping the rate limiter in the first place (~10s added to a 202-file run)

### Push
- Pushed commit `630bf450`

### Not yet done
- Root cause is a theory based on symptoms (same token worked seconds before failing) — not confirmed against GitHub's own rate-limit docs/support. **Watch the next 1-2 automatic runs**: if 401 recurs even with the retry+pacing fix, escalate (check token scope/expiration in GitHub settings, consider batching into fewer, larger requests instead of 202 sequential blob calls)

## [2026-07-10] Month-on-month comparison view (Claude, Cowork)

### Added
- New toggle mode "📅 เทียบรายเดือน (MoM)" ในหน้า `store_discount_dashboard.html` (ปุ่มที่ 3 ต่อจาก รายวัน/แนวโน้ม 3 เดือน)
- เปรียบเทียบยอดขายสุทธิ (ทุก type รวมกัน ไม่รวม C/F) และส่วนลดสาขา (O/P/Y) ระหว่าง "เดือนนี้" กับ "เดือนที่แล้ว" โดยเทียบวันที่เท่ากัน (วันที่ 1 ถึงวันปัจจุบันของเดือน) — คำนวณจากข้อมูล 92 วันเดิมที่มีอยู่แล้ว ไม่ query DB เพิ่ม
- Reuse โครง drill-down เดิม (Company → RM → DM → Store → Linetype) — คลิกแถวเพื่อ drill ได้เหมือนโหมดรายวัน ยกเว้นระดับ product ที่ไม่รองรับ (ข้อมูลสินค้ารายชิ้นมีแค่ 2 วันล่าสุด ไม่พอสำหรับ MoM)
- ฟังก์ชันใหม่: `computeMonthRanges()`, `aggregateForDateRange()`, `renderMonthView()`, `renderMonthSummaryCards()`, `renderMonthTable()`
- Summary cards แสดง: ยอดขายสุทธิเดือนนี้/เดือนที่แล้ว + %MoM, ส่วนลดสาขาเดือนนี้/เดือนที่แล้ว + %MoM, GP% ทั้งสองเดือน
- ตารางแสดง: ยอดขายสุทธิ + ส่วนลดสาขา ของทั้งสองเดือน พร้อม Δ MoM ต่อแถว (RM/DM/Store/Linetype)

### Verification
- Syntax verified via reconstructed script + `node --check` (bash mount ยังโชว์ไฟล์เก่า ใช้ Read tool เป็น ground truth ตามเดิม)
- ยังไม่ได้ push ขึ้น GitHub — รอ user รันคำสั่ง push (ดู pending diagnostic เรื่องไฟล์ live ล้าหลังจากรอบก่อนหน้าด้วย)

## [2026-07-10] Product-level table: GP%, RM/DM/store columns, hide zero-discount (Claude, Cowork)

### Added
- GP% per product row — added `SUM(s.total_cost) AS cost` to `query_product_detail()` in `build_store_discount_data.py`
- Columns: ชื่อสาขา, ชื่อเขต (DM), ชื่อภาค (RM), Type (linetype badge) in the level-5 product table
- Filter: hide rows where discount = 0 (`p.discount > 0`)
- CSV export updated to match new columns (list_price, sale_price, discount_baht, gp_pct, type, store_name, dm_name, rm_name)

### Fixed
- Column label mix-up: "ราคาลด" used to show the discount *amount* — renamed so ราคาลด = ราคาหลังลด (net sales price), ลดไปกี่บาท = discount amount, matching user's wording

### UI
- Header font size increased and centered (h1 20→30px, subtitle 12→16px)
- Pastel red/green colors made more saturated for clearer emphasis; GP% pill given bolder border

### Deferred (user confirmed not needed yet)
- "เหตุผลในการลด" (discount reason) — no such field exists in `fact_sales`/`fact_bill_header` (checked `soremark`, blank on every row); `rt_reason_lake` is unrelated (return reasons, not discount reasons)
- Excluding "ราคาขั้นบันได" (tiered pricing) — no identifiable field/table for this in current schema
- Restricting product-detail query to O/P/Y only at the source (currently filtered client-side)

### Investigated
- User asked to recheck auto-update: GHA run #187 succeeded (24m30s) at today's 08:30 BKK cron slot, but `store_discount_products/*.json` still shows yesterday's 2-day window (07-07/07-08), not yet 07-09, despite MySQL confirming 07-09 data is available now — root cause not fully isolated, flagged for tomorrow's verification
- Manually patched `cost` into 26 already-matching O/P/Y product entries (07-08) in the pushed per-store files so GP% shows correctly without waiting for a full rebuild

## [2026-07-09] New: Store Price-Discount Dashboard (Claude, Cowork)

### Added
- **`build_store_discount_data.py`** — builder ใหม่ ดึงส่วนลดที่**สาขากดเองท้ายบิลเท่านั้น** (ไม่รวมคูปอง/แลกคะแนน/โปรโมชั่น% จากส่วนกลาง, ไม่รวมราคาโปร/สมาชิกอัตโนมัติ `sopricdisc`) — สูตร: `prorated_discount × (sodisc_bill/sodisc)` join `fact_sales` + `fact_bill_header` + `dim_product` (ราคาปกติ = `ipunit3`)
- **`store_discount_dashboard.html`** — drill-down ภาพรวม→RM→DM→Store, breakdown ตาม linetype, เทียบวันก่อนหน้า, ปุ่มสลับ trend ย้อนหลัง 92 วัน, ปุ่มดาวน์โหลด CSV, สีเตือน GP% (แดง<10% / เหลือง10-20% / เขียว>20%)
- **`store_discount_data.json`** — backfill ย้อนหลัง 92 วัน (2026-04-08 → 2026-07-08) แล้ว 89,850 แถว 3.8MB
- เพิ่ม step `Build store discount data` ใน `.github/workflows/daily-update.yml` ต่อจาก build lost product (continue-on-error: true)

### Verified
- sum(line_store_discount) ช่วง 14 วันล่าสุด = 176,356 บาท เทียบ `fact_bill_header.sodisc_bill` จริง = 224,283 บาท (~79% ตรงกัน — ส่วนต่างจาก bill คืนสินค้า/void ที่ join ไม่ครบ ยอมรับได้ระดับ trend dashboard)

### Known limitation
- **ยังไม่ได้ push ขึ้น GitHub** — sandbox ของ Cowork เข้า `api.github.com` ไม่ได้ (403 บน tunnel) ต้องรัน `push_files_api.py` บน Windows เพื่อ publish จริง (ดู "งานที่เหลือ" ด้านล่าง)
- ไม่มีคอลัมน์ "ภาค" แยกจาก RM ในระบบ — ใช้ RM เป็น level บนสุดแทน

### Fixed (same day, after user correction)
- **เปลี่ยนตัวจำแนกสาขา vs การตลาดเป็น `solinetype`** — user ยืนยันตรงๆ ว่า linetype `O`, `P`, `Y` = สาขากดเอง ที่เหลือ = การตลาด/โปรอัตโนมัติ (คนละกลไกกับ `sodisc_bill/sodisc` ที่ใช้ตอนแรก) แก้ `build_store_discount_data.py` (ตัด join `fact_bill_header` ทิ้ง, schema v2) และ `store_discount_dashboard.html` (คำนวณ store vs marketing discount จาก linetype key ตอน render) — verify แล้วตรงกับข้อมูลเดิมที่ backfill ไว้ (ไม่ต้อง rebuild JSON) — ดู Decisions.md `[2026-07-09]` ฉบับ FINAL
- **แก้ Edit tool truncation** บน `store_discount_dashboard.html` (18KB, โดนตัดกลาง JS ตอนใช้ Edit หลายรอบ) — เขียนใหม่เต็มไฟล์ด้วย Write tool ครั้งเดียวแทน + verify ด้วย Read tool (bash mount ใน sandbox มี stale cache ไม่สะท้อนไฟล์จริง — ใช้ Read tool เป็น ground truth)
- **ตัด linetype `C` (ของแถม) และ `F` (สินค้าสมนาคุณ)** ออกจากทุกที่ในแดชบอร์ด — `F` ไม่รวมใน GP% calc ด้วย (ราคาเต็ม>0 ขายจริง 0 บาททำให้ GP บิดเบือน เช่น -239900%)
- **เพิ่ม drill level 4-5**: คลิกสาขา → breakdown ตาม linetype → คลิก linetype → รายการสินค้า (บาร์โค้ด/ชื่อ/จำนวน/ราคาเต็ม/ราคาลด/ราคาขายสุทธิ + เทียบเมื่อวาน) — ข้อมูลสินค้าเก็บแยกไฟล์ `store_discount_products.json` (โหลด lazy เฉพาะตอน drill ถึงระดับนี้), ขยายจาก 1 วัน → 2 วัน (ล่าสุด+เมื่อวาน) เพื่อเทียบ day-on-day
- **สีพาสเทล** ตามที่ user ขอ (--lavender/--mint/--peach/--sky/--butter) + format วันที่เป็น dd-mm-yyyy ทุกจุดที่แสดงผล

### Perf fix (2026-07-09, หลัง user รายงาน "โหลดข้อมูลสินค้านานจัง")
- Root cause: `store_discount_products.json` รวมทุกสาขา (202 สาขา × 2 วัน) เป็นไฟล์เดียว ~24MB — โหลดทั้งไฟล์ทุกครั้งที่ดูแค่สาขาเดียว
- **แยกเป็นไฟล์รายสาขา** `store_discount_products/<whs>.json` (~120KB เฉลี่ย/ไฟล์) — dashboard ใช้ `productsCache` (Map) โหลด lazy ทีละสาขา
- เพิ่ม `push_github_tree()` push 202 ไฟล์เป็น 1 commit (Git Data API), `push_files_api.py` รองรับ push ทั้งโฟลเดอร์
- Verify: `node --check` ผ่าน, ไฟล์ HTML ครบ 565 บรรทัดจบด้วย `</html>` (ยืนยันผ่าน Read tool เนื่องจาก bash mount stale)
- **ยังไม่ push** — ดูคำสั่ง push ด้านล่าง

### Data bug fix (2026-07-09, จาก user ขอ verify ตัวเลขการ์ด)
- พบว่า RM/DM mapping (`branches` dict) ใช้ cache ค้างจาก `dim_cache.json` (สร้างโดย `rebuild_fraud_analysis.py` คนละสคริปต์) — ไม่ sync กับ `dim_branch` จริงเมื่อมีการย้ายสาขาข้าม RM
- ตัวอย่างจริงที่เจอ: สาขา `080` (คลองสงค์) ย้ายไป RM จินตนา (36299) แล้วในระบบจริง แต่ cache ยังผูกกับ RM สุพรรษา (36285) — ทำให้ยอด RM จินตนาขาดไป ~12,009 บาท/วัน (~1%) และไปโป่งที่ RM สุพรรษาแทน
- **Fix:** `load_branches()` เปลี่ยนไป query `dim_branch` สดทุกครั้งที่ build แทนพึ่ง `dim_cache.json` — ตัด cross-script dependency, ลบ `BRANCH_CACHE` ที่ไม่ใช้แล้ว
- **Hotfix ทันที:** patch คีย์ `branches` ใน `store_discount_data.json` ที่มีอยู่ด้วยข้อมูลสดจาก `dim_branch` (203 สาขา) ไม่ต้องรอ query 92 วันใหม่ (ข้อมูลยอดขายเดิมไม่กระทบ)
- Verify: คำนวณจากไฟล์หลัง patch ตรงกับ query MySQL สดเป๊ะทุกหลัก (RM 36299, 2026-07-07: list_amt 1,275,713 / store_disc 85 / marketing 26,004.66)

## [2026-06-23] Trigger lost-Product Daily GP Analysis Rebuild automatically (Antigravity)

### Fixed
- **📅 GP Analysis Dashboard Auto-Update**: Resolved the issue where the GP Analysis dashboard was showing June 1-21 instead of June 1-22 because GitHub Actions' native scheduler on `tumsbux/lost-Product` was severely delayed or skipped.
- **⚙️ Cross-Repository Trigger**: Added a workflow step using `curl` at the end of the `daily-update.yml` workflow in `daily-report` repository. This step uses the `GH_PAT` secret to programmatically trigger the `Daily GP Analysis Rebuild` workflow in the `lost-Product` repository via `workflow_dispatch` immediately after the daily dashboard updates complete.
- **🚀 Manual Trigger**: Manually triggered the GP Analysis rebuild, updating the live dashboard to correctly display the data for **June 1-22** (วัน 1-22).

## [2026-06-20] Fix: detect_max_day retry logic for product builder (Claude)

### Problem
- Product dashboard แสดง 1–18 มิ.ย. ขณะที่ Sales/Fraud/Hub แสดง 1–19 มิ.ย.
- Root cause: `build_product_data_mysql.py` รันก่อน `update_dashboard.py` ใน GHA pipeline — ตอน product builder query fact_sales ได้ max_day=18 (data วัน 19 ยังโหลดไม่เสร็จ) แต่ update_dashboard รันทีหลังไม่กี่นาทีได้ max_day=19

### Fixed
- เพิ่ม **retry logic** ใน `detect_max_day()` — ถ้า detected day < `today.day - 1` (expected) จะรอ 60 วินาทีแล้ว retry สูงสุด 2 ครั้ง
- Commit: `7e698af7` → push via `push_files_api.py`
- GHA run #125 verified — Product dashboard อัปเป็น 1–19/30 ✅

### Note for Antigravity
- ถ้าแก้ `build_product_data_mysql.py` ให้รักษา retry logic ใน `detect_max_day()` ไว้
- `update_dashboard.py` มี fallback `max(1, today.day - 1)` อยู่แล้ว ไม่ต้องแก้

---

## [2026-06-19] Bill-Level Comparison Analysis — corrected report + docs update (Claude)

### Analyzed
- **Bill-level comparison** (Google Sheet `bill_level_comparison`): 231,088 bills, 1-7 Jan 2025
- พบ **2 BUGs ในรายงานเดิม** (`comparison_blh_bld_vs_fact_sales`):
  1. `SUM(net_sales_amt - prorated_discount)` หักส่วนลดซ้ำ (net_sales_amt หัก prorated ไว้แล้ว)
  2. sodisc 390,752 คิดซ้ำ (จริง = 195,376 — sodisc เป็น rollup ไม่ใช่ channel แยก)
- **ยืนยัน data quality 99.95%** — ผลต่างทั้งหมดอธิบายได้ (prorated_discount + sotype=3 + rounding)
- Correct net sales = `SUM(net_sales_amt)` ไม่ต้องหักอะไรเพิ่ม
- Benchmark GP%: ร้าน 33.61% (ดี — CPALL 29%, Makro 16-19%, Walmart 24.9%, 7-11 JP 32%)

### Updated
- **Architecture.md**: เพิ่ม §Bill-Level Comparison (ตัวเลข, สาเหตุผลต่าง, data quality, SQL ที่ถูก/ผิด, BUG report) + แก้ §Sales Data Source Verification (solineamt ≠ net_sales_amt)
- **Decisions.md**: ADR [2026-06-19] — SUM(net_sales_amt) เป็น correct formula, fact_sales เป็น primary source
- **Gotchas.md**: เพิ่ม gotcha double-subtraction bug + update sodisc entry ด้วยตัวเลขยืนยัน
- **Roadmap.md**: เพิ่ม action items จาก analysis (GP% control, discount blocking, category management, margin dashboard)
- **CLAUDE.md**: เพิ่ม §Data Quality Rules + reference ไปยัง Google Sheets + Column_Reference

---

## [2026-06-19] Bugfix: Non-clickable "Executive Report" button & template store count sync (Antigravity)

### Fixed
- **Dashboard "Executive Report" Button**: Fixed a critical condition-checking bug in all patch files (`patch_exec_sales.py`, `patch_exec_fraud.py`, `patch_exec_product.py`, and `patch_exec_fraud_template.py`) where injecting the button (which contains the string `onclick="openSalesExecReport()"`) caused subsequent checks for JavaScript functions and modal HTML to falsely trigger "already present" skips. Updated checks to target class selectors, ID attributes, and function declarations specifically.
- **HTML Modal String Collision**: Fixed a JS syntax error in `fraud_analysis_template.html` and `fraud_dashboard.html` where injecting modal HTML using simple `.replace('</body>')` matched a string literal within a print function (`+'</body></html>';`) instead of the true closing tag. Fixed by using `.rfind('</body>')` to locate the true end-of-file closing tag.
- **Fraud Executive Report Store Counts**: Fixed a bug where the counts of HIGH/MEDIUM/LOW risk stores in the Fraud Executive Report modal showed `0` (even though the main page showed correct numbers). The modal's JS function expected `D.store_risk` (top-level key) but was reading from `allData.stores` (which was undefined due to the builder outputting `store` singular without risk levels). Updated JavaScript to read from `D.store_risk || D.sr || []`.

### Deployed
- Commits pushed to GitHub main branch:
  - Updated `fraud_analysis_template.html` template.
  - Re-run `update_dashboard.py` and `inject_fraud_only.py` to regenerate dashboards.
  - Pushed template and updated patch/updater scripts via `py push_py_to_github.py`.
  - Triggered and verified successful run of `daily-update.yml` GHA pipeline (Run ID: 27805001440).

## [2026-06-15] Phase C+D: fixes + GHA weekly-rebuild (Claude)

### Fixed
- **Dead Stock**: กรองกลุ่มสินค้าที่ไม่ใช่ retail ออก — `EXCLUDED_ITY = {'03','12','15','20','26'}` + `EXCLUDED_IGRCODE = {'10006'}` (Supply Use, สินทรัพย์, ค่าใช้จ่าย, อุปกรณ์ไฟฟ้า, สินค้าสมนาคุณ, อุปกรณ์ตกปลา) → ลด 6,917 → 6,474 products
- **Dead Stock**: กรอง null parcode + สินค้าที่ไม่อยู่ใน `dim_product` (name = '—') ออกทั้งหมด
- **Dead Stock**: dropdown กลุ่มสินค้าแสดง `igrdesc` (ชื่อเต็ม) แทนรหัส — เพิ่ม `query_group_names()` จาก `MYPOS2018_CENTER.item_group` + field `group_name` ใน JSON
- **Visual Adj**: ลบ LIMIT 500 ออกจาก `query_ibl_products()` → แสดง all SKUs (49,094)
- **Visual Adj**: แก้ `→` UnicodeEncodeError (cp874) + `datetime.utcnow()` deprecation → `datetime.now(timezone.utc)`
- **Push target**: สร้าง `push_lost_product_files.py` ใหม่ — target `tumsbux/lost-Product` via Contents API (แก้ bug เดิมที่ push ไป `daily-report` เพราะ db_config.json `github_repo` ชี้ผิด)
- **Sales/Fraud/Thongfah day 12→14**: GHA ไม่รัน 2 วัน — manual push `index.html`, `sales_dashboard_v8.html`, `fraud_dashboard.html` → commit `0a47f95a`; Thongfah → commit manual ผ่าน `push_data_json.ps1`
- **`gc.collect()`**: เพิ่มระหว่าง step ใน `build_dead_stock.py` ป้องกัน `MemoryError` บน Windows

### Added
- **`push_lost_product_files.py`**: push ไฟล์ไป `tumsbux/lost-Product` ผ่าน Contents API พร้อม `--repo-path` flag สำหรับ push ไป subdirectory (เช่น `.github/workflows/`)
- **`.github/workflows/weekly-rebuild.yml`** (ใน lost-Product): GHA รันทุกวันอาทิตย์ 09:00 BKK — `build_dead_stock.py --no-push` → `build_visual_adj.py --no-push` → `git commit + push` — manual trigger ผ่าน `workflow_dispatch` — ✅ test run สำเร็จ 7m 36s

### Deployed
- lost-Product commits: `038d284d` (dead_stock_data.json, 6.4MB) + `316367a5` (dead_stock_dashboard.html + build_dead_stock.py) + `22c92f7b` (push_lost_product_files.py) + `26575150` (weekly-rebuild.yml)
- Secrets เพิ่มใน lost-Product repo: DB_HOST, DB_PORT, DB_USER, DB_PASSWORD, DB_DATABASE, GH_PAT

---

## [2026-06-15] Phase D: Visual Adjustment Audit — deployed (Claude)

### Added
- **`build_visual_adj.py`** — 4 steps: dim_branch → ibl store summary → ibl all SKUs → itd_acc UNION sessions
  - `ibl` (locno='visual', shelfno='adjustment'): cumulative all-time per store (204) + product (49,094 SKUs)
  - `itd_acc UNION itd_acc_20260610`: 41,205 sessions (full history)
  - valid_store filter 1-500 ทั้งสอง sources
  - Result: net_qty=-10,455,868 / net_value=฿-332,447,546
  - Output: `visual_adj_data.json` (13.6 MB) — sections: stores, products, sessions
- **`visual_adj_dashboard.html`** — 3 tabs:
  - ตามร้าน: risk badge HIGH/MED/LOW by |net_value|, filter DM/RM/ทิศทาง, color-coded net
  - ตามสินค้า: all 49,094 SKUs by |net_qty|, filter group/search
  - Sessions: 41,205 sessions, filter by store/date
- ⚠️ ไม่มี cashier column ใน MYWMS — fraud signal = store-level + session (itd_refno)
- Commits: `e95cf2a7` (data) + `a75e68f5` (dashboards + scripts)

---

## [2026-06-14] Phase C: Dead Stock report (Claude)

### Added
- **`build_dead_stock.py`** — chain-level dead stock builder
  - Step 1: `data-lake.fact_sales` → last_sale per iprod (stream cursor)
  - Step 2: `MYWMS2023_CENTER.ibl` → onhand qty + value per (iprod, whsno), valid_store 1-500
  - Step 3: join in Python → filter onhand > 0 + last_sale < cutoff (default 90 วัน)
  - Result: 6,917 dead-stock products / ฿12,163,121 total value
  - Output: `dead_stock_data.json` — schema 1, built_by, as_of, threshold_days
  - CLI: `py build_dead_stock.py [--no-push] [--days N]`
- **`dead_stock_dashboard.html`** — filters วันค้าง/กลุ่ม/ค้นหา, expand → store breakdown, export CSV
- Commits: `a75e68f5` (dashboards + scripts) — data pushed previous session

---

## [2026-06-14] bugfix(fraud): rttime ทุก record stack ที่ 07:00 — deeper root cause fix (Antigravity)

### Fixed
- **Fraud Dashboard → เวลา tab → กราฟ**: return bills ทั้งหมดกระจุกอยู่ที่ 07:00 ทุก record
  - Root cause จริง: `rttime.astype(str).str[:2]` บน string format `"0 days 18:00:20"` → ได้ `"0 "` → hour=0 → frontend +7 ICT = 07:00 ทุกตัว
  - Fix: `_parse_time_row()` ใน `rebuild_fraud_analysis.py` แก้ให้ parse จาก timedelta/string format ได้ถูก (extract `18` จาก `"0 days 18:00:20"`)
- **GHA ModuleNotFoundError**: `dashboards/fraud_queries.py` + `dashboards/fraud_agg.py` ไม่ได้อยู่ใน `push_py_to_github.py` file list → GHA fail ทุก run ตั้งแต่ Phase 3d
  - Fix: เพิ่ม `dashboards/` files เข้า push list
- **GHA git push auth**: `dashboards/git_push.py` ไม่ใช้ authenticated URL → credential helper ล้มเหลวใน GHA runner
  - Fix: ใช้ `github_url` (with token) แทน bare URL
- GHA Run `27503699346` — succeeded ✅
- VM synced + verified: hours กระจาย `14:00–23:00` แทน stack ที่ `07:00`
- Cleaned up `upload_script_vm.py` (temp script)

---

## [2026-06-14] bugfix(fraud): rttime "0 day" → HH:MM — Phase 3d rebuild (Claude)

### Fixed
- **Fraud Dashboard → Return Bill tab → เวลาคอลัมน์**: แสดง "0 day" ทุก record (8,816 bills)
  - Root cause: Pre-Phase-3d code ใช้ `pd.Timedelta.days` = 0 เสมอสำหรับ intraday time → `str(0) + ' day'`
  - Fix: Phase 3d `_parse_time_row()` ใน `rebuild_fraud_analysis.py` ใช้ `.components.hours` + `.components.minutes` → HH:MM
  - `fraud_data.json` rebuilt + pushed (commit `3302c2f2`) — verified `"time": "22:24"` ✅
  - Phase 3d scripts pushed (commit `da46c8d7`): `rebuild_fraud_analysis.py`, `dashboards/fraud_queries.py`, `dashboards/fraud_agg.py`
  - `fraud_dashboard.html` regenerated + pushed ผ่าน `run_manual_update.ps1` (709s)

---

## [2026-06-14] กิจกรรมธงฟ้า Dashboard — grand total + date filter + GitHub Actions (Claude)

### Fixed
- `thongfah_dashboard/index.html`: grand total %GP ผิดคอลัมน์ — แสดง GP฿ amount แทน %
  - Root cause: `if(c.k==='g'||c.k==='gp')` ใน tfoot match `k='gp'` ใน aggregate views (ที่ `gp` = %GP)
  - Fix: check `curView` — `if(c.k==='gpp'||(c.k==='gp'&&curView!=='detail'))` → %GP, `if(c.k==='g'||(c.k==='gp'&&curView==='detail'))` → GP฿
  - `totG` ก็ต้อง check: `curView==='detail'?r.gp:r.g`
- `tfoot td.r` ชิดซ้าย: CSS `tbody td.r{text-align:right}` ไม่ cover `<tfoot>` → เพิ่ม `tfoot td.r`
- `build_data.py`: SQL `ORDER BY sodate` ผิด `only_full_group_by` (sodate ไม่อยู่ใน GROUP BY) → `ORDER BY DATE(f.sodate)`
- `push_data_json.ps1`: `$ErrorActionPreference='Stop'` + git stderr → script ตาย → redirect `2>&1 | Out-Null`
- `index.html` ใน Cowork working copy truncated (15KB แทน 19KB) — rebuild จาก GitHub raw content

### Added
- Date range filter (📅 ตั้งแต่วันที่ / ถึงวันที่) — auto min/max จาก data, reset button
- `DT=14` constant (index 14 = date string `YYYY-MM-DD`)
- `build_data.py`: env var support (`MYSQL_HOST/PORT/USER/PASSWORD`) เพื่อรันใน GitHub Actions + fallback `db_config.json`
- `push_data_json.ps1`: push 46MB data.json ผ่าน git clone (bypass GitHub Contents API 422 limit)
- `push_thongfah_update.py`: push index.html + build_data.py ผ่าน GitHub Contents API
- `daily-update.yml` (saved to outputs): GHA workflow รันทุกวัน 08:35 BKK — pip install → build_data.py → git push

### Pushed
- `tumsbux/thongfah-dashboard`: index.html (fixed) + data.json (160,753 rows, 2026-05-01–2026-06-12, 45.3MB) + build_data.py

### Pending (user ทำเอง — ทำครั้งเดียว)
- เพิ่ม 4 MySQL Secrets ใน thongfah-dashboard repo → Settings → Secrets → Actions: `MYSQL_HOST/PORT/USER/PASSWORD`
- สร้าง `.github/workflows/daily-update.yml` ผ่าน GitHub web UI (PAT ขาด `workflow` scope) — YAML อยู่ใน outputs

---

## [2026-06-14] bugfix(3c): whsdd loop body missing — day_totals/targets never populated (Claude)

### Fixed
- `update_dashboard.py`: Phase 3c surgery accidentally dropped 7 lines from the `_whsdd_rows` loop body
  - Missing: `store_tar_monthly[no] += tar`, `store_tar_mtd[no] += tar`, `day_totals[day] += act`, `store_target_days[no][day] = act`, `store_txn_mtd[no] += txn`
  - Effect: `day_totals = {}` every run → `finalized_days = []` → `max_fin_day = 0` → `data_note = 'target(d1-0)'` always (misleading)
  - Also: target comparisons used stale JSON values instead of fresh whsdd targets
  - Sales totals were still correct (fact_sales primary path unaffected)
  - Fix: restored 7 lines from `update_dashboard_v1_backup.py` reference
  - 939 → 946 lines

---

## [2026-06-14] Phase B — วันหมด (Days-until-OOS) column ใน product_dashboard (Claude)

### Added
- `product_dashboard.html`: คอลัมน์ **วันหมด** (Days until OOS) — col 12 ในตารางสินค้า
  - Formula: `onhand ÷ (q26 / days_elapsed)` — JS-only, ข้อมูลมีอยู่ใน JSON แล้ว
  - แสดง: 🔴 ≤7 วัน (`#e74c3c`) / 🟠 ≤14 วัน (`#e67e22`) / 🔵 >14 วัน (`#2e86ab`) / "OOS" (onhand=0) / "—" (ไม่มียอดขาย)
  - Sortable: เรียง 0 (OOS ก่อน) → ascending days → 999999 (ไม่ขาย = ท้ายสุด)
  - Shifted existing cols: ipunit3 (12→13), Dif Ly QTY (13→14), YoY ยอดขาย (14→15)
  - ไม่แตะ backend / JSON schema — JS-only change

---

## [2026-06-14] Phase 3d — decompose rebuild_fraud_analysis.py (Claude)

### Changed
- `rebuild_fraud_analysis.py`: **934 → 458 lines (−476 lines, −51%)**
  - Extracted **`dashboards/fraud_queries.py`** (303 lines): `_mysql_conn`, `_load_sales_mtd_from_cache`, `_get_frozen_returns`, `_query_returns_full`, `_query_whsdd_sales_cost`, `_query_sales_mtd` — added `folder` keyword param to 3 functions that previously used FOLDER global
  - Extracted **`dashboards/fraud_agg.py`** (211 lines): `_rec`, `_build_product_agg`, `_build_reason_agg`, `build_month`
  - Kept in main: `_load_db_config`, `load_users`, legacy file parsers, `load_returns`, `compute_store_risk`, `push_github`, `main`
  - Call site patches: `_query_returns_full(cfg, FOLDER, ...)` + `_load_sales_mtd_from_cache(max_mo, FOLDER)`

---

## [2026-06-14] Phase 3c bugfix — THAI_MON + factXX.txt suppression (Claude)

### Fixed
- **`THAI_MON` not defined** (WARNING เวลา fraud inject): Phase 3c surgery ลบ script code ที่อยู่ระหว่าง function defs ออกด้วยโดยไม่ตั้งใจ (original lines 764-791 — Day badge, THAI_MONTHS, YEAR_BE, THAI_MON, upd_hk/skpi calls) — restored ที่ `update_dashboard.py` line 619-644
- **factXX.txt warnings suppressed**: Step 2 wrapped ด้วย `if not _fact_sales_mtd:` guard — เมื่อ MySQL fact_sales มีข้อมูลครบ (normal case) จะ skip scan ทั้งหมดและ print `[2/7] Skipping factXX.txt — MySQL fact_sales covers days 1-N` แทน

---

## [2026-06-12 PM8] Product dashboard — label เฉลี่ยชิ้น/วัน + sort bug (Claude)

### Fixed
- `product_dashboard.html`: label คอลัมน์ "เฉลี่ย/สัปดาห์" → **"เฉลี่ยชิ้น/วัน"** — ค่าที่ render คือ `q26/days_elapsed` (ชิ้น/วัน) มาตลอด แค่ label ผิด (user ขอเพิ่มคอลัมน์ชิ้น/วัน → พบว่ามีอยู่แล้ว เลยแก้ label แทน ตาราง 15 คอลัมน์เท่าเดิม)
- **Sort bug 2 จุด**: คอลัมน์ "เฉลี่ย/วัน" โชว์บาท/วัน (`s26/d`) แต่ sort ใช้ชิ้น/วัน → แก้ `pSortVal` case 9 เป็น `s26/d` + case 10 `q26/(d/7)` → `q26/d` ให้ตรงค่าที่โชว์
- Edit ผ่าน Python via bash (HTML 40KB ตามกฎ Gotchas) — verified: 3 substitutions / ลงท้าย `</html>` / no null bytes

### Added
- `push_files_api.py` — generic selective push ขึ้น main ผ่าน Git Data API (`py push_files_api.py <files> -m "msg"`) — retry 5xx + block db_config.json/cache — ใช้แทนการสร้าง script push เฉพาะกิจรายครั้ง

---

## [2026-06-12 PM6] Repo bloat — cache ย้ายไป orphan branch `cache` (ADR approved + implemented, Claude)

### Added
- **ADR [2026-06-12] Cache persistence Option A — user approved → implement ครบ:**
  - `daily-update.yml`: step "Restore cache from orphan cache branch" (ก่อน Sunday check) + step "Push cache to orphan cache branch (force, single commit)" (หลัง update_dashboard, `always()` + continue-on-error) — branch history = 1 commit เสมอ ไม่มี bloat
  - `update_dashboard.py`: ตัด cache 8 รายการออกจาก `push_files` (STEP 7)
  - `push_py_to_github.py`: ตัด cache 7 รายการออกจาก `FILES_TO_PUSH` + เพิ่ม `.gitignore` เข้า list
  - `.gitignore` ใหม่: `cache/`, `db_config.json`, `__pycache__`, VM scripts ที่ฝัง creds
  - `setup_cache_branch.py` (one-time, Git Data API): seed orphan branch จาก cache/ local + ลบ cache/* ออกจาก main + commit .gitignore
  - `push_cache_migration.py` (one-time): push เฉพาะไฟล์ migration + docs — **ไม่ใช้ `push_py_to_github.py`** เพราะ list มี dashboard HTML รายวัน จะ push build เก่าทับของ GHA (Gotchas "push ทับด้วยไฟล์เก่า")
- Sandbox verified: YAML parse 14 steps ✓ / py_compile ✓ / no null bytes ✓ (sandbox ยิง api.github.com ไม่ได้ — push ต้องรันบน Windows)

### Deployed (✅ 2026-06-12 PM7, user รันบน Windows)
- main **`d57451ee`** (workflow + update_dashboard + .gitignore + docs ผ่าน `push_cache_migration.py`) → branch **`cache`** seeded **`b42be68c`** (11 ไฟล์ รวม superseded 2021_2024 parquet ที่ค้างใน local) → main cleaned **`dd6fb478`** (ลบ cache 8 ไฟล์ + commit .gitignore)
- หมายเหตุ: blob upload parquet ใหญ่ (29-32MB) เจอ GitHub 502 — เพิ่ม retry 5xx/timeout ใน `setup_cache_branch.py` (4 attempts, backoff) แล้วผ่าน
- ⏳ เหลือ verify GHA รุ่งขึ้น: step "Restore cache from orphan cache branch" + "Push cache to orphan cache branch" เขียวทั้งคู่ → ปลดล็อกขยาย IR

### Verified
- `build_grouped_with_barcodes.py` — ✅ **จบ:** pre-verify ผ่าน MySQL MCP (join key `iprod` = `dim_item_barcode.parcode` ตรงทุก sample รวม bridge case, coverage 145/150) + **รันจริงบน Windows ผ่านทั้ง 2 schema**: v1 passthrough และ v2 decoded — ตัวเลข parity เป๊ะทุก count (65,812 products / 74,747 barcode rows / ACTIVE 117,019 / STALE 39,698 / LOST 65,714 / DISCONTINUED 1,109) + `lost_product_grouped_with_barcodes.xlsx` saved

### Docs
- Sync docs lost-Product → co work dashboard (ฝั่ง co work ค้างเก่า ขาด update 06-12 PM2/PM5 ทั้ง Decisions/Roadmap/Changelog/CLAUDE/Gotchas/How_To)

---

## [2026-06-12 PM5] MySQL MCP live + VM mirror recovery + data day-11 (Claude + user)

### Added
- **MySQL MCP ใช้งานได้ใน Cowork** — tools `mcp__mysql__execute_sql / get_schema_info / get_table_sample` — root cause สุดท้าย: app ไม่ถูก Quit จริงจาก tray (process ค้าง 10 ตัว) — verify: dim_branch 203 / cross-DB ครบ 3 ฐาน / READ-only denied (ดู Architecture.md §MySQL MCP + Gotchas)

### Fixed
- **VM Dashboard Hub (`agent-ab-sandbox:48081`) กู้คืน** — identify ได้ว่าเป็น container mirror sync จาก GitHub ทุก 10 นาที (`How_To_Modify_Dashboards.md` มี doc แต่ไม่มี ADR) — service ตายตั้งแต่ 11 มิ.ย. 13:05 (รันโดยไม่มี nohup + ไม่มี auto-restart) → restart ผ่าน SSH ด้วย nohup + กวาด duplicate instance — auto-restart ทำในเครื่องไม่ได้ (container PID1=sh, ไม่มี cron/systemd) ต้องขอ IT
- **Dashboard Hub ข้อมูลถอยหลังเป็นวัน 9** — push v2 schema (`858db387`) พ่วง `index.html` เก่าทับ build ล่าสุด (Gotchas entry ใหม่) → user รัน `run_manual_update.ps1` rebuild วัน 11 + push สำเร็จ (MTD 51.5M, +24.3% YoY proj, lost-Product `0a5b414`) — verify raw GitHub = วัน 11 ✓

### Security (ค้าง)
- ⚠️ `run_vm_command.py` / `check_vm_status.py` / `push_to_vm.py` / `upload_test.py` ใน `F:\lost-Product` ฝัง SSH password — เช็คแล้ว**ยังไม่หลุดขึ้น repo** — ควรย้าย creds เป็น config แยก + SSH password และ MySQL password หลุดในแชท Cowork → พิจารณาให้ IT rotate

---

## [2026-06-12 PM2] IR conditions cleanup + build_grouped v2 fix (Claude)

### Fixed
- **`build_grouped_with_barcodes.py`** — รองรับ JSON schema v2 (decode codes/products_header/status_codes แบบเดียวกับ `build_lost_onhand_xlsx.py`) + v1 passthrough + แก้ DB join key จาก JSON `parcode` (barcode) → JSON `iprod` (DB parcode จริง) ตาม Gotchas naming trap — sandbox tested (syntax + mock v2/v1 decode + join key), ยังไม่ได้รันจริงบน Windows

### Resolved
- **IR เงื่อนไข 1 (fraud cache lag 1 วัน)** — user เลือก **document-only**: circular dependency (update_dashboard ใช้ fraud_data.json inject HTML → reorder ไม่ได้) + fact_sales lag 1-2 วัน by design + Sunday full-refresh — Gotchas entry ใหม่ + ADR annotation
- **GHA 2026-06-12 "ไม่ fire"** — จริงๆ **fire แล้ว แค่ delay ~5.4 ชม.** (4 scheduled runs 12:53–13:59 BKK, success ทุก run) — free-tier delay ไม่ใช่ cron พัง — Roadmap note แก้แล้ว

### Proposed
- **IR เงื่อนไข 3 (repo bloat)** — ADR `[2026-06-12]` ใน Decisions.md: orphan branch `cache` + force-push (เทียบ 4 options) — **รอ user approve**

### Noted
- Cowork sandbox mount stale ซ้ำอีกครั้ง (build_grouped หลัง Edit → mount เห็น snapshot เก่า+truncated เกิน 45 วิ) — verify โดย copy ผ่าน Write tool ไป outputs แล้วทดสอบที่นั่นแทน (Gotchas 2026-06-11 ยังใช้ได้)

---

## [2026-06-12] Lost Product × Onhand Excel report (one-off, user request)

### Added
- **`build_lost_onhand_xlsx.py`** — รวม LOST+STALE products (chain-level) × onhand ต่อร้านจาก query MYWMS ibl สด (สูตร Phase A: `locno='stock' AND shelfno='shelfno'`, join `iprod = ibl_parcode`, stream tuple cursor กัน MemoryError) → **1 ไฟล์ต่อสถานะ** `lost_onhand_YYYY-MM-DD_<STATUS>.xlsx` (query ibl ครั้งเดียว แยกตอนเขียน) แต่ละไฟล์ 3 sheets: Detail (เฉพาะ onhand > 0, เรียงมูลค่า) / ByProduct / ByStore — flags: default LOST+STALE, `--all` +ACTIVE, `--lost` LOST เดี่ยว — Excel เขียนแบบ streaming (`write_only`, ~100K แถว/นาที RAM ต่ำ; รุ่นแรกโหมดปกติ RAM บวม 97K แถวค้างที่ wb.save — แก้ 2026-06-15) — รันจริง 2026-06-15: 97,475 แถว มูลค่ารวม ฿68.5M
- อ่าน `lost_product_data.json` ได้ทั้ง schema v2 (decode) และ v1 เก่า — ✅ tested ใน sandbox ด้วย mock data (decode, join/filter, xlsx rollups, v1 passthrough)
- รันบน Windows: `py build_lost_onhand_xlsx.py` (ต้องมี db_config.json — script ค้นหา 3 path เอง) — ไม่แตะ daily pipeline

### Changed (2026-06-12 PM)
- หัวคอลัมน์ xlsx (Detail + ByProduct) เปลี่ยน `parcode | iprod` → **`barcode | parcode`** ให้ตรง schema DB — internal keys คงเดิม ไม่กระทบ logic — รันจริง `--all`: LOST 79,033 / STALE 18,433 / ACTIVE 502,640 rows, มูลค่ารวม ฿407.8M (ดู Gotchas "Field naming trap")

### Known issue (flagged)
- ⚠️ **`build_grouped_with_barcodes.py` (script เก่า) อ่าน products แบบ v1** — **จะพังแล้วจริงตอนนี้** (JSON บน repo เป็น v2 ตั้งแต่ 2026-06-12 PM) — ถ้ายังใช้อยู่ต้องเพิ่ม decode แบบเดียวกับ `build_lost_onhand_xlsx.py::load_lost_data()`

---

## [2026-06-12] Compact JSON encoding schema v2 (lost_product_data.json)

### Changed
- **`build_lost_product_data.py`** — emit compact format v2 (ADR `[2026-06-11]`): global `codes` table (66,245 unique barcodes/iprods, สตริงเก็บครั้งเดียว), `store_breakdown` inner keys → int index, `products` → array-of-arrays + `products_header` row เดียว, status → int (`_meta.status_codes`)
- **`index.html` + `index_for_lost_product.html`** (byte-identical, md5 ตรงกัน) — เพิ่ม `decodeData()`: one-time decode หลัง fetch กลับเป็น shape v1 ใน memory → filters / scope aggregation / XLSX export ไม่ต้องแก้; v1 JSON เก่า pass-through ได้ (รองรับช่วง transition); schema อื่น throw error ชัดเจน
- `_meta` ใน JSON: `{schema: 2, built_by, status_codes}` per collab rules

### Verified (sandbox)
- ✅ `py_compile` builder + `node --check` JS + ไฟล์ลงท้าย `</html>` + ไม่มี null bytes
- ✅ Round-trip test ด้วย code จริง (encode block จาก builder + `decodeData` จาก index.html): deep-equal ทั้ง 7 sections + v1 passthrough + กรณี parcode≠iprod (barcode bridge) + Thai strings
- ✅ Re-encode JSON จริง: **77.9 → 51.9 MB (−33%)** — sb 47.0→35.0, products 30.8→15.9, codes +1.0
- ⚠️ ต่ำกว่า estimate ADR (~43 MB) เพราะ (1) data โตจาก 74.2→77.9 MB ระหว่างรอ approve (2) ADR ประเมิน products หลัง encode ต่ำไป — payload ที่เหลือคือชื่อสินค้าภาษาไทย บีบด้วย index ไม่ได้ — ยังต่ำกว่า threshold 70 MB ชัดเจน

### Deployed (✅ 2026-06-12 PM)
- ✅ Windows rebuild ผ่าน: **49.5 MB** (data วันที่ 12, ต่ำกว่าที่วัด 51.9 เพราะคนละวัน) + `_meta.schema: 2` + dashboard render ผ่าน (localhost:8000 — JSON fetch 200, console error ที่เห็นเป็น Chrome extension noise)
- ✅ Pushed สองคอมมิต: **daily-report `858db387`** (builder + `index_for_lost_product.html` commit เดียว ผ่าน `push_v2_schema.py` ตัวใหม่ — Git Data API แบบเลือกไฟล์ได้ ไม่ force-push) + **lost-Product `fdeacd1`** (JSON v2 + index.html + analytics.js ผ่าน `push_lost_data.ps1`) — verify raw บน GitHub แล้วทั้งคู่
- 🔓 **Antigravity ปลดล็อก lost-product builder/frontend ได้**
- 📝 หมายเหตุ: `F:\co work dashboard\` ไม่ใช่ git clone — push ของ repo นี้ทำผ่าน GitHub API scripts เท่านั้น (`push_py_to_github.py` / `push_v2_schema.py` / `push_lost_data.ps1`)

---

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
- Pruning: drop `(whs, iprod)` if `total_qty < 15 AND tot