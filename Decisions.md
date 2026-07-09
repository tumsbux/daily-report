# Decisions (ADR)

> **A**rchitecture **D**ecision **R**ecord
> **กฎ:** ก่อนเปลี่ยน/revert อะไรที่อยู่ในไฟล์นี้ → ต้องอ่าน + อัปเดต record ก่อน

---

## [2026-07-09] Store Price-Discount Dashboard — NEW dashboard

**Status:** Accepted (2026-07-09) — user confirmed data mapping + proration method + GP color thresholds

**Context:** User ต้องการแดชบอร์ดใหม่ติดตามการปรับลดราคาที่ "สาขา" กดเอง (ไม่รวมส่วนลดที่ส่วนกลาง/การตลาดสั่ง) โชว์ราคาปกติ vs ราคาที่ปรับลดจริง vs GP% ที่เหลือ แยกภาค/เขต/สาขา อัปเดตทุกวัน + ย้อนหลัง 3 เดือน

**การสำรวจ schema จริง (2026-07-09) พบว่าสมมติฐานแรกผิด — แก้ไขแล้ว:**
- `sodisc_bill` / `sodisc_coupon` / `sodisc_perc` / `sodisc_score` อยู่ใน **`fact_bill_header`** (ระดับบิล) **ไม่ใช่ `fact_sales`**
- `fact_sales.prorated_discount` = ส่วนลดรวม**ทุกประเภท**ปันส่วนลงรายการแล้ว (ยืนยันด้วย query จริงว่า `SUM(prorated_discount) ต่อบิล = fact_bill_header.sodisc` เป๊ะ — ไม่ใช่แค่ `sodisc_bill`)
- ราคาปกติ (list price) = `dim_product.ipunit3` (join ผ่าน `iprod`)
- RM/DM/ภาค mapping = `dim_branch` (คอลัมน์ `rm_code/rm`, `dm_code/dm`; ไม่มีคอลัมน์ "ภาค" ตรงๆ — ใช้ `prvn_name`/`rm` เป็น grouping ระดับบนสุดแทน หรือสร้าง mapping ภาค←RM เพิ่มถ้ามี)

**Decision — วิธีคำนวณส่วนลดเฉพาะสาขา (line-level) — FINAL แก้ไขครั้งที่ 2 (2026-07-09):**

user ยืนยันตรงๆ ว่าตัวจำแนก "สาขากดเอง" vs "การตลาด" คือ **`fact_sales.solinetype`**:
- `solinetype IN ('O','P','Y')` → **สาขากดเอง** (คลิกปรับราคา/ส่วนลดเองที่หน้าร้าน)
- `solinetype` อื่นๆ ทั้งหมด (N, Q, D, J, H, Z, S, F, B, C, U, ...) → **ลดตามการตลาด/โปรอัตโนมัติ** (ราคาสมาชิก/โปรที่ระบบตั้งไว้ล่วงหน้า)

ไม่ต้อง join `fact_bill_header` อีกต่อไป (bill-level `sodisc_bill/sodisc` ratio ที่ใช้ก่อนหน้านี้ยกเลิก — เป็นคนละกลไกกับที่ user ต้องการ) สูตรใหม่ง่ายกว่าเดิมมาก:

```
list_price_line   = dim_product.ipunit3 × fact_sales.net_qty     -- ยืนยันแล้ว sopricunit == ipunit3 ทุกแถว
line_discount     = list_price_line − fact_sales.net_sales_amt   -- ส่วนต่างเต็มจำนวนของบรรทัดนั้น (รวม sopricdisc + prorated ถ้ามี)
line_is_store     = fact_sales.solinetype IN ('O','P','Y')
store_discount    = SUM(line_discount) WHERE line_is_store
marketing_discount= SUM(line_discount) WHERE NOT line_is_store
actual_price_line = list_price_line − line_discount   (ใช้ store_discount อย่างเดียวเวลาโชว์ "ราคาขายจริงถ้าตัดผลการตลาดออก")
GP%_line          = (actual_price_line − total_cost) / actual_price_line
```
Join: เหลือแค่ `fact_sales.iprod = dim_product.iprod` (+ `dim_branch`/`dim_cache.json` สำหรับ RM/DM)

**หมายเหตุ:** `solinetype='P'` พบเฉพาะที่ `sotowhs='901'` (คลัง/ช่องทางพิเศษ ไม่ใช่สาขาขายจริง 1-500) จึงแทบไม่ปรากฏใน dashboard นี้ (scope เฉพาะสาขา 1-500) — ตัวที่เห็นจริงในระบบคือ O กับ Y

**Verify (14 วันล่าสุด, เฉพาะสาขา 1-500):**
- ส่วนลดรวมทุกแบบ (ทุก linetype) ≈ 1,598,671 บาท
- ในนั้นเป็น "สาขากดเอง" (O+Y) แค่ ≈ 24,203 บาท (~1.5%)
- ที่เหลือ ≈ 1,574,467 บาท (~98.5%) เป็น "การตลาด/โปรอัตโนมัติ" (ส่วนใหญ่อยู่ใน linetype N — สอดคล้องกับที่ verify ครั้งก่อนว่า `sopricdisc` บน N-type คือราคาโปร/สมาชิกอัตโนมัติ)

**⚠️ ประวัติแก้สูตร:** รอบแรกใช้ `sodisc_bill/sodisc` bill-ratio (ผิด — คนละกลไก), รอบสองตัด `sopricdisc` ออกทั้งหมด (ผิด — บาง `sopricdisc` เป็นของสาขาจริงถ้าอยู่ใน line type O/P/Y), รอบนี้ (final) ใช้ `solinetype` เป็นตัวจำแนกตรงๆ ตามที่ user ยืนยัน

**เพิ่มเติม 2026-07-09 (หลัง push):** user แจ้งให้ตัด `solinetype='C'` ออกจากทุกที่ในแดชบอร์ด (ของแถม/free-gift — มูลค่า qty/cost/sales/discount = 0 อยู่แล้วทุกแถว ไม่กระทบตัวเลขรวม แต่ทำให้ chip linetype ในหน้า breakdown สะอาดขึ้น) — แก้ที่ dashboard JS เท่านั้น (`EXCLUDED_LINETYPES = {'C'}` กรองใน `addAgg` และ `linetypeBreakdown`) ไม่ต้อง rebuild ข้อมูล

**เพิ่ม level ที่ 4: คลิกสาขา → แยกตาม Linetype (2026-07-09):** เดิม drill-down หยุดที่ระดับสาขา (ภาพรวม→RM→DM→Store) user ขอให้คลิกสาขาแล้วเห็น breakdown ตาม linetype ของสาขานั้นต่อ — เพิ่ม `state.store` + `groupBy='linetype'` ใน `aggregateForDate()`, breadcrumb เพิ่ม crumb "สาขา: ...", ตารางหลักเปลี่ยนเป็นแสดงต่อ linetype (พร้อม tag 🏪 สาขา / 📢 การตลาด) เมื่อ drill ถึงระดับนี้ ซ่อน panel breakdown ล่างสุดที่ซ้ำซ้อน

**เพิ่ม level ที่ 5: คลิก linetype → รายการสินค้า (2026-07-09):** user ขอ column: บาร์โค้ด, ชื่อสินค้า, จำนวนขาย, ราคาเต็ม, ราคาลด, ราคาขายสุทธิ ต่อสินค้า — ข้อมูลระดับนี้ (store × product × linetype) ใหญ่เกินกว่าจะเก็บ 92 วันย้อนหลังแบบ `store_discount_data.json` (ลองแล้ว 1 วันเดียวได้ ~50K แถว / 11.7MB) จึงแยกไฟล์ใหม่ **`store_discount_products.json`** เก็บเฉพาะ**วันล่าสุดวันเดียว** (overwrite ทุกวัน ไม่สะสมประวัติ) — โหลดแบบ lazy (fetch เฉพาะตอนคลิกลึกถึงระดับนี้ครั้งแรก ไม่โหลดพร้อมหน้าแรก) query: `fact_sales JOIN dim_product` (ชื่อ+ราคา) + subquery `dim_item_barcode` (barcode, `baractive='Y'`) กรองสาขา 1-500 — เพิ่ม `query_product_detail()` ใน `build_store_discount_data.py` รันทุกครั้งที่ build (backfill/incremental) โดยใช้วันล่าสุดใน `merged_days` เสมอ, push แยกไฟล์ผ่าน `push_github()` (refactor ให้รับ path+filename เป็นพารามิเตอร์ ใช้ได้กับทั้งสองไฟล์)
- ถ้าผู้ใช้เลือกดูวันที่เก่ากว่าวันล่าสุด แล้ว drill ถึงระดับสินค้า จะโชว์ข้อความแจ้งว่ามีแค่วันล่าสุด (ไม่มี fallback ไปวันอื่น)

**แก้ไข 2026-07-09 (ต่อ):** user ขอเก็บ **2 วัน** (ล่าสุด + เมื่อวาน) แทนวันเดียว เพื่อเทียบ day-on-day ระดับสินค้าได้ — เปลี่ยน schema `store_discount_products.json` จาก `{date, stores}` เป็น `{schema:2, dates:[...], days:{date:{store:[...]}}}`, เพิ่ม `PRODUCTS_DAYS_KEPT=2` ใน builder (เลือก N วันล่าสุดจาก `merged_days` มา query ทุกครั้ง ไม่สะสมยาว), ตารางสินค้าเพิ่มคอลัมน์ "เทียบเมื่อวาน" (จับคู่ตาม `iprod` เดียวกัน) — ไฟล์ใหญ่ขึ้นเป็น ~24MB (2 วัน) ยังอยู่ในขอบเขตที่ GitHub Contents API รับได้ (<100MB)

**GP% color threshold:** 🔴 <10%　🟡 10–20%　🟢 >20% (คำนวณหลังหักเฉพาะส่วนลดสาขา ไม่รวมคูปอง/คะแนน/เปอร์เซ็นต์การตลาด)

**Hierarchy drill-down:** ภาพรวม → RM → DM → Store (คลิก drill ลง) + breakdown ตาม `solinetype` ในทุก level + เทียบวันนี้ vs เมื่อวาน

**New buttons:** (1) สลับ trend ย้อนหลัง 3 เดือน (2) ดาวน์โหลด Excel/CSV ของ view ปัจจุบัน

**Update:** เข้า pipeline daily 08:30 BKK เดิม (stepใหม่ `continue-on-error: true`) ต่อท้าย repo `daily-report`

**Consequences:**
- ✅ ตัวเลขแยกสาขา vs การตลาดแม่นกว่าที่คาดไว้แรก (ไม่ใช่แค่อ่าน field เดียว ต้อง join + prorate)
- ✅ **Verification ผ่าน (2026-07-09):** sum(line_store_discount) ช่วง 14 วันล่าสุด = 176,356 บาท เทียบกับ sum(fact_bill_header.sodisc_bill) จริง = 224,283 บาท (~79% ตรงกัน) — ส่วนต่าง ~21% คาดว่ามาจาก bill ที่ join ไม่ครบ (คืนสินค้า/void, ขอบเขต store filter 1-500) ยอมรับได้ในระดับ dashboard เชิงเทรนด์ ไม่ใช่บัญชีที่ต้องเป๊ะ 100%
- ✅ Backfill 92 วันเสร็จแล้ว (2026-04-08 → 2026-07-08, 89,850 แถว, 3.8MB) เก็บที่ `store_discount_data.json`
- ⚠️ ไม่มีคอลัมน์ "ภาค" ตรงในระบบ — ต้องเช็คกับ user อีกครั้งถ้าต้องการ level ภาคจริงๆ แยกจาก RM

**แก้ไข perf 2026-07-09: แยก `store_discount_products.json` (24MB รวมทุกสาขา) เป็นไฟล์รายสาขา:** user รายงานว่าหน้าคลิกดูสินค้าระดับสาขา "โหลดนานมาก" — root cause: ไฟล์เดียวรวม 202 สาขา × 2 วัน (~24MB) ถูก fetch ทั้งไฟล์ทุกครั้งที่ drill ลงดูแค่สาขาเดียว
- **Decision:** เปลี่ยนจากไฟล์รวม 1 ไฟล์ → โฟลเดอร์ `store_discount_products/<whs>.json` (202 ไฟล์ย่อย ~120KB/ไฟล์เฉลี่ย, schema 3: `{schema, whs, dates, generated_at, days:{date:[items]}}`)
- `build_store_discount_data.py`: เปลี่ยน `PRODUCTS_OUT_FILE` → `PRODUCTS_OUT_DIR`, reshape ข้อมูลจาก `{date:{whs:[...]}}` เป็นต่อสาขา, เขียนทีละไฟล์ผ่าน `safe_write_json`
- เพิ่ม `push_github_tree()` ใน builder — ใช้ Git Data API (blob+tree+commit) push 202 ไฟล์เป็น **1 commit เดียว** (กัน 202 commits/วัน)
- `push_files_api.py` เพิ่ม directory-argument expansion (walk โฟลเดอร์ที่ส่งเข้ามา รวมไฟล์ทั้งหมดในนั้นเข้า tree เดียวกัน)
- Dashboard JS: เปลี่ยนจาก global `PRODUCTS_DATA` object → `productsCache = new Map()` (key = รหัสสาขา), `ensureProductsLoaded(whs)` fetch เฉพาะไฟล์สาขาที่กำลังดู (lazy per-store), `renderProductLevel`/`downloadCSV` อ่านจาก cache แทน
- **Verification:** JS syntax check ผ่าน (`node --check`) หลัง reconstruct จากไฟล์เต็มผ่าน Read tool (bash mount มี stale-cache แสดงไฟล์ตัดที่ 18,383 bytes แต่ Read tool ยืนยันไฟล์จริงสมบูรณ์ 565 บรรทัด จบด้วย `</html>`)
- ไฟล์เก่า `store_discount_products.json` (24MB รวม, commit `0d1d59a8`) เหลือค้างใน repo แต่ dashboard ไม่อ้างอิงแล้ว — ยังไม่ลบ (รอ user ตัดสินใจ)
- **ยังไม่ push** ไฟล์ 202 ไฟล์ + build script + dashboard.html ตัวใหม่ — รอ user รันคำสั่ง push

---

## [2026-06-20] detect_max_day retry logic — product builder timing fix

**Status:** Accepted

**Context:** GHA pipeline รัน steps ตามลำดับ: fraud → product → lost-product → update_dashboard. ทุก step query `MAX(DAY(sodate))` จาก fact_sales เพื่อหา days_elapsed. พบว่า product builder (step 2) อาจ query ก่อนที่ data ของวันล่าสุดจะโหลดเสร็จ ทำให้ได้ max_day ต่ำกว่าจริง ขณะที่ update_dashboard (step 4) รันทีหลังไม่กี่นาทีได้ค่าถูก

**Decision:** เพิ่ม retry loop ใน `build_product_data_mysql.py` → `detect_max_day()`:
- เปรียบเทียบ detected day กับ `today.day - 1` (expected)
- ถ้าน้อยกว่า → รอ 60 วินาที แล้ว retry (สูงสุด 2 ครั้ง)
- ถ้ายังน้อยกว่าหลัง retry ครบ → ใช้ค่าที่ได้ + print WARN

**Consequences:**
- ✅ แก้ timing mismatch ระหว่าง product กับ sales dashboard
- ✅ worst case เพิ่มเวลารัน 2 นาที (ยังอยู่ใน timeout 10 min)
- ⚠️ `update_dashboard.py` มี fallback `max(1, today.day-1)` อยู่แล้ว ไม่ต้องเพิ่ม retry

**Commit:** `7e698af7` (Claude, 2026-06-20)

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

**Status:** ✅ Accepted with conditions — **user approved 2026-06-11 PM** (หลัง Claude code review เต็มทั้ง 3 scripts)

> **Annotation [2026-06-11]:** ADR นี้ Antigravity ใส่สถานะ "Accepted" เอง **โดย user ยังไม่ได้อนุมัติ** — ขัด collab rule Claude review แล้วพบคุณภาพ code ดี (rule_hash/v:2/built_by ครบ, safe_write จริง, fallback chain เดิมอยู่ครบ, upsert ถูกต้อง, Sunday full-refresh ใน GHA) → user ตัดสินใจ **accept แบบมีเงื่อนไข 3 ข้อ** (ดู Roadmap Now):
>
> 1. **Fraud cache lag 1 วัน** — ✅ **resolved 2026-06-12: document-only (user decision)** — แก้ลำดับไม่ได้เพราะ circular dependency (update_dashboard ต้องใช้ fraud_data.json inject HTML) + fact_sales lag 1-2 วัน by design + Sunday full-refresh reconcile รายสัปดาห์ — ดู Gotchas "Fraud risk score — MTD sales/cost lag 1 วัน"
> 2. **Verify onhand patch** — IR-B memory pressure เป็น suspect ของ onhand=0 (patched 2026-06-11, รอรันบน Windows)
> 3. **Repo bloat** — parquet cache 4-10 MB push ขึ้น repo รายวัน → โตหลัก GB/ปี ต้องหาทางแก้ (เช่น ไม่ commit parquet)
>
> ห้ามทั้ง 2 agents ขยาย IR เพิ่มจนกว่าเงื่อนไข 3 ข้อจะเคลียร์

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

## [2026-06-11] Product dashboard YOY → same-period MTD baseline

**Status:** ✅ Accepted + implemented 2026-06-11 (user approved)

**Context:**
Product dashboard เทียบ `s26` (MTD วัน 1–9 มิ.ย. 2026, จาก fact_sales auto-detect ที่ lag ~1-2 วัน) กับ `s25` (full June 2025, 30 วัน) → YOY **-59.6%** misleading ทุก SKU/ทุกประเภท ทั้งที่ per-day จริงคือ +34.6%. ผู้ใช้เข้าใจผิดว่า data วัน 1-10 มิ.ย. หาย (เคสจริง 2026-06-11). Math check: ดู Gotchas.md [2026-06-11]

**Decision:**
1. `build_product_data_mysql.py` — filter prev-year cache `df_prev[df_prev['day'] <= days_elapsed]` ใน `query_product_sales` + `query_store_sales_may25` (Parquet cache ของ Antigravity ยังเก็บ full month — filter ตอน aggregate เท่านั้น, ไม่กระทบ cache structure, ไม่ต้อง full-refresh)
2. `build_json` — เพิ่ม `days_in_month`
3. `product_dashboard.html` — nav chip "· วัน 1–N/30" + KPI baseline label "(1–N)"

**Consequences:**
- ✅ YOY apples-to-apples — สอดคล้องกับ sales dashboard (YoY same-source sync 2026-06-04)
- ✅ ผู้ใช้เห็นชัดว่า data ครอบคลุมถึงวันไหน (ตัด confusion "ทำไมไม่ใช่ 1-10")
- ⚠️ `s25/q25` จะเปลี่ยนค่าทุกวันจนสิ้นเดือน (expected — เป็น MTD baseline)
- ⚠️ Verification ต้องรันบน Windows (sandbox เข้า MySQL ไม่ได้): `py build_product_data_mysql.py --no-push` แล้วเช็ค s25 รวม ~36M (ไม่ใช่ 108.7M)

---

## [2026-06-11] Compact JSON encoding — global barcode index + array-form products

**Status:** ✅ Accepted + **deployed 2026-06-12 PM (Claude)** — verified บน Windows (49.5 MB) + pushed daily-report `858db387` + lost-Product `fdeacd1` — **Antigravity ปลดล็อกแล้ว**

> **Annotation [2026-06-12] (Claude, post-implement):** ผลจริงจาก re-encode JSON ปัจจุบัน = **77.9 → 51.9 MB (−33%)** ไม่ใช่ ~43 MB — เพราะ (1) data โต 74.2→77.9 MB (2) products หลัง encode = 15.9 MB ไม่ใช่ 9.2 MB: payload ที่เหลือคือชื่อ/แบรนด์/กลุ่มภาษาไทย (UTF-8 3 bytes/ตัวอักษร) ซึ่ง index ไม่ช่วย — ยังต่ำกว่า threshold 70 MB. ถ้าอยากบีบต่อในอนาคต: ตัด derived fields (first_year..lost_score, ~2.5 MB) แล้วคำนวณใน decodeData ฝั่ง JS (logic มีอยู่แล้วใน scope aggregation)

**Context:**
`lost_product_data.json` = **74.2 MB** ตั้งแต่ IR-A build 2026-06-10 (walkthrough.md ระบุเอง) — เกิน revisit threshold 70 MB (ADR [2026-06-06] คาด 45-55 MB). ตรวจ 2026-06-11: **pruning ยังทำงานปกติ** (MIN_QTY/MIN_AMT OR logic + trailing-zero trim intact ใน `build_lost_product_data.py` L287-311) — ขนาดมาจาก **structure overhead** ไม่ใช่ regression:

| ส่วน | ขนาด | สาเหตุ |
|---|---|---|
| store_breakdown | 47.0 MB | keys = barcode 13 หลัก ×1.62M pairs = **24.7 MB**, arrays 20.6 MB |
| products | 24.1 MB | field names ซ้ำ 65,790 รอบ = **13.4 MB** + parcode==iprod ซ้ำ 50,926 รายการ |

**Decision (proposed):**
1. Global barcode table `codes: [...]` (58,643 unique = 0.9 MB) — ทุกที่อ้างด้วย int index
2. `store_breakdown` keys → int index → 33.3 MB
3. `products` → array-of-arrays + header row เดียว → 9.2 MB
4. JS loader ใน `index.html` decode หลัง fetch (one-time pass)

**Measured estimate: 74.2 → ~43 MB (−42%)** — headroom จริง ~2-3 ปี

**Consequences:**
- ✅ กลับลงใต้ threshold ระยะยาว โดยไม่เสีย data
- ⚠️ **Breaking format** — `index.html` + XLSX export ต้องแก้พร้อม builder ใน commit เดียว
- ⚠️ ต้องใส่ format version ใน JSON (`_meta.schema`) per collab rules — กัน agent อ่าน format เก่า
- 📝 Note ถึง Antigravity: walkthrough.md (06-10) เขียนว่า 74.2 MB = "~2 years headroom" — **ไม่ตรง ADR threshold 70 MB** — ใช้ ADR นี้เป็น source of truth

---

## [2026-06-12] Cache persistence — หยุด commit cache ลง main (แก้ repo bloat, IR เงื่อนไข 3)

**Status:** ✅ Accepted — **user approved 2026-06-12 PM6** (Claude เสนอ + implement)

**Context:**
Phase IR ทำให้ GHA daily run ต้อง persist cache ข้าม run (runner ephemeral) — ปัจจุบันแก้ด้วยการ **commit cache files (parquet 4-10 MB + JSON) ลง main ทุกวัน** → git history โต ~2-3.5 GB/ปี (binary diff ไม่ได้) ทำให้ clone ช้า (เคยโดน timeout 60s — Gotchas) และเปลือง bandwidth

**Options พิจารณา:**

| Option | วิธี | ข้อดี | ข้อเสีย |
|---|---|---|---|
| **A. Orphan branch `cache` + force-push** ⭐ | GHA push cache ไป branch แยก ด้วย `--force` (history = 1 commit เสมอ) — daily run `fetch origin cache` ก่อน build | ไม่มี bloat ถาวร (branch ขนาด ≈ cache จริง), ไม่มี eviction, ใช้ git เดิม, Windows run ก็ใช้ได้ | ต้องแก้ workflow + push scripts (S) |
| B. `actions/cache` | ใช้ GHA cache action, key = month + rule_hash | สะอาดสุด, ไม่แตะ repo เลย | evict ได้ (7-day unused / 10GB), ไม่ช่วย Windows manual run, ผูกกับ GHA |
| C. Separate cache repo | repo ใหม่ force-push | เหมือน A แต่แยก repo | repo เพิ่มอีกตัว ไม่จำเป็น |
| D. ไม่ commit เลย + full-refresh ทุกวัน | ตัด cache persistence | ง่ายสุด | เสียประโยชน์ IR ทั้งหมด (กลับไป 2-3 นาที + DB load) |

**Decision (proposed): Option A** — orphan branch `cache` ใน daily-report:
1. สร้าง orphan branch ครั้งเดียว: `git checkout --orphan cache && git rm -rf . && cp cache/* && commit && push`
2. GHA workflow: ก่อน build → `git fetch origin cache && git checkout origin/cache -- cache/` (หรือ clone branch แยก depth 1); หลัง build → commit cache ใหม่บน orphan + `push --force`
3. ลบ `cache/` ออกจาก main + เพิ่ม `.gitignore` — main เหลือเฉพาะ code + dashboard files
4. fallback เดิมอยู่แล้ว: cache หาย/hash mismatch → auto `--full-refresh`
5. (optional, ทีหลัง) `git filter-repo` ล้าง cache เก่าใน history main — ทำหลัง rotate PAT + ตกลง Antigravity เพราะ rewrite history กระทบทุก clone

**Consequences:**
- ✅ main history หยุดโต — เหลือ commit code/data dashboard ตามปกติ
- ✅ ไม่มี eviction risk, Windows/VM ใช้ branch เดียวกันได้
- ⚠️ force-push = ไม่มี cache history (ไม่ต้องการอยู่แล้ว)
- ✅ **Implemented 2026-06-12 PM6 (Claude):** `daily-update.yml` (+2 steps: Restore ก่อน build / force-push หลัง build), `update_dashboard.py` + `push_py_to_github.py` (ตัด cache ออกจาก push list), `.gitignore` ใหม่, `setup_cache_branch.py` (one-time: seed branch + ลบ cache/* จาก main ผ่าน Git Data API) — sandbox verified (YAML/py_compile/no null bytes) — ✅ **Deployed 2026-06-12 PM7:** main `d57451ee` → branch `cache` seeded `b42be68c` (11 ไฟล์) → main cleaned `dd6fb478` — เหลือ verify GHA รุ่งขึ้น (push ใช้ `push_cache_migration.py` เฉพาะกิจ — `push_py_to_github.py` พ่วง dashboard HTML เก่า)

---

## [2026-06-12] VM Dashboard Mirror (agent-ab-sandbox) — documented post-hoc

**Status:** 📝 Documented post-hoc (setup เกิดก่อนหน้าโดยไม่มี ADR — ไม่ทราบว่า agent ไหน/เมื่อไหร่)

**Context:**
พบว่ามี container `agent-ab-sandbox.tjinternal.com` (122.155.213.17) serve dashboards ชุดเดียวกับ GitHub Pages ที่ port 48081 (NAT → http.server 8080) + scheduler ดึง commit ใหม่จาก GitHub ทุก 10 นาที (`start_services.py` + `sync_files.py`) — มี user doc ใน `How_To_Modify_Dashboards.md` แต่ไม่มี ADR ตาม collab rules

**Decision (โดยพฤตินัย):**
ยอมรับเป็นส่วนหนึ่งของระบบ — internal mirror ใช้ดู dashboard โดยไม่พึ่ง GitHub Pages — รายละเอียด operations ดู Architecture.md §VM Dashboard Mirror

**Consequences:**
- ไม่มี auto-restart (container PID1=`sh`, ไม่มี cron/systemd) — ตาย 11 มิ.ย. แล้วไม่มีใครรู้จนวันถัดไป → ขอ IT ตั้ง restart policy (Roadmap)
- SSH creds ฝังใน scripts ฝั่ง Windows — ต้องย้ายเป็น config แยก (Roadmap)
- เป็น consumer ของ GitHub main → bug "push ทับด้วยไฟล์เก่า" กระจายถึง VM ด้วย (Gotchas 2026-06-12)

---

## [2026-06-19] ยอดขายสุทธิ = SUM(net_sales_amt) ห้ามหัก prorated_discount ซ้ำ

**Status:** ✅ Accepted

**Context:**
รายงานเปรียบเทียบ bld_acc vs fact_sales ฉบับเดิม (Google Sheet `comparison_blh_bld_vs_fact_sales`) มี **2 BUGs**:
1. ใช้ `SUM(net_sales_amt - prorated_discount)` → หักส่วนลดซ้ำ เพราะ `net_sales_amt = solineamt - prorated_discount` อยู่แล้ว → ตัวเลข 34,083,851 ผิด
2. นับส่วนลดรวม 390,752 = บวก sodisc + sodisc_bill + sodisc_score ซ้ำ → จริงคือ 195,376 (sodisc = rollup ของ breakdown)

ฉบับแก้ไข (`bill_level_comparison`) ยืนยัน:
- ข้อมูล 99.95% ตรงสมบูรณ์ (231,088 บิล, 1-7 ม.ค. 2025)
- ผลต่าง 110,228 ฿ = prorated_discount (185K) + sotype=3 (75K) + rounding (207 ฿)
- **ไม่มี data mismatch จริงแม้แต่บิลเดียว**

**Decision:**
1. **ใช้ `SUM(net_sales_amt)` เป็นยอดขายสุทธิจาก fact_sales** — ห้ามหักอะไรเพิ่ม
2. **ใช้ fact_sales เป็นแหล่งข้อมูลหลักสำหรับ GP%** — bld_acc ขาดส่วนลดบิล → GP สูงเกิน ~0.37%
3. ทุก query/measure/DAX ที่ยังใช้ `net_sales_amt - prorated_discount` ต้องแก้เป็น `net_sales_amt`
4. `sodisc` ใช้ตัวเดียวเป็น total discount — ห้ามบวก breakdown ซ้ำ

**Consequences:**
- ✅ GP% ถูกต้อง (33.61% จาก fact_sales แทน 33.25% ที่คิดซ้ำ / 33.98% จาก bld_acc ที่ขาดส่วนลด)
- ✅ แก้ SQL ในรายงานเดิม + Column_Reference.xlsx + Power BI measures
- ⚠️ ตัวเลข GP ที่เคยรายงานไปแล้ว (ถ้ามี) อาจต้อง restate

**References:**
- Google Sheet: `bill_level_comparison` (ฉบับแก้ไข, 6 sheets)
- Google Sheet: `comparison_blh_bld_vs_fact_sales` (ฉบับเดิม มี bug — อ้างอิงได้แค่ benchmark GP% + column mapping)

---

## 📚 Superseded

- ~~`solinetype = 'N'` filter~~ (pre-2026-05-31) → `solinetype NOT IN ('C','R')` to match mobile app
- ~~Static `const MTH = {...}`~~ (pre-2026-06-04) → JS Proxy dynamic
- ~~`fact_sales` only for YoY card~~ (pre-2026-06-04) → same-source sync
- ~~`so = so[so['lines']>1]` for Return Bill~~ (pre-2026-06-03) → `so_all` (all bills, cap 500)

---

_Last updated: 2026-06-19_