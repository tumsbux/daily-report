# Roadmap

> งานค้าง + แผนต่อไป — เสร็จแล้วย้ายไป `Changelog.md`

---

## 🔥 Now (สัปดาห์นี้)

- [ ] 🏪 **กิจกรรมธงฟ้า Dashboard — ตั้ง GitHub Actions auto-update** (user ทำเอง — ทำครั้งเดียว)
  1. ไปที่ `github.com/tumsbux/thongfah-dashboard` → Settings → Secrets → Actions → เพิ่ม 4 secrets: `MYSQL_HOST=203.154.83.62`, `MYSQL_PORT=13306`, `MYSQL_USER`, `MYSQL_PASSWORD`
  2. Actions → New workflow → "set up a workflow yourself" → วาง YAML จาก `daily-update.yml` (อยู่ใน Cowork outputs) → Commit
  3. ทดสอบ: กด "Run workflow" → ดูว่า data.json commit ใหม่ขึ้น
  - Dashboard URL: `https://tumsbux.github.io/thongfah-dashboard/`
  - หลังทำแล้ว: อัปเดตอัตโนมัติทุก 08:35 BKK ไม่ต้องเปิด laptop
  - size: XS

- [ ] 🔐 **Rotate GitHub PAT** — PAT หลุดใน log (2026-06-11) — **user ต้องทำเอง** (agents แตะ secrets ไม่ได้)
  1. github.com → Settings → Developer settings → สร้าง fine-grained PAT ใหม่ (repos: `daily-report` + `lost-Product`, permission: Contents RW)
  2. อัปเดต `F:\co work dashboard\db_config.json` (key เก็บ PAT)
  3. อัปเดต GHA secret `GH_PAT` ใน `tumsbux/daily-report` → Settings → Secrets → Actions
  4. เช็คจุดอื่นที่อาจฝัง PAT: VM env / `push_to_vm.py` / `run_vm_command.py` / PS scripts
  5. **Revoke PAT เก่า** แล้วทดสอบ `run_manual_update.ps1` + ดู GHA run ถัดไปเขียว
  - ⚠️ Antigravity ก็ใช้ push — rotate แล้วแจ้งทั้ง 2 agents / อัปเดต config ที่ Antigravity ใช้ด้วย
  - size: XS

- [ ] 🔐 **ย้าย SSH creds ออกจาก VM scripts** — `run_vm_command.py` / `check_vm_status.py` / `push_to_vm.py` / `upload_test.py` ใน `F:\lost-Product` ฝัง password (ยังไม่หลุดขึ้น repo แต่อยู่ใน working copy ของ repo public) → ย้ายเป็น config แยกแบบ `db_config.json` หรือย้าย scripts ไป `F:\co work dashboard\` — พ่วง: SSH+MySQL password หลุดในแชท Cowork 2026-06-12 → แจ้ง IT rotate ถ้ากังวล — size: XS

- [ ] 🖥️ **ขอ IT ตั้ง restart policy ให้ VM container** (`agent-ab-sandbox`) — `start_services.py` ไม่มี auto-restart (container ไม่มี cron/systemd) ตายแล้วต้อง start มือ — ถามด้วยว่า endpoint นี้ใครเป็นคน setup (ไม่มี ADR) — size: XS

- [ ] ✅→⚠️ **IR-B/C/D: user accept แบบมีเงื่อนไข (2026-06-11 PM)** — เหลือเคลียร์ 3 เงื่อนไข:
  1. [x] **Fraud cache lag 1 วัน** — ✅ resolved 2026-06-12: **document-only** (user decision — circular dependency + fact_sales lag by design) — ดู Gotchas entry ใหม่ + ADR annotation
  2. [x] **Verify onhand patch** — ✅ verified + **deployed 2026-06-12 PM**: `py push_py_to_github.py` (35 ไฟล์, parent `858db387`) + รัน `py build_product_data_mysql.py` จริง → `936,433 onhand rows` + product_data.json pushed OK (51.7M / +20.5% YoY, days 1-11) — size: XS
     - ✅ GHA 2026-06-12 **fire แล้ว แค่ delay หนัก**: 4 scheduled runs 12:53–13:59 BKK (delay ~5.4 ชม. จาก slot แรก 07:30) ทุก run success — เช็คตอน 11:00 BKK เลยยังไม่เห็น — free-tier delay ปกติ ไม่ใช่ cron พัง
  3. [x] **Repo bloat** — ✅ **deployed 2026-06-12 PM7**: main `d57451ee` (workflow + update_dashboard + .gitignore + docs) → branch `cache` seeded `b42be68c` (11 ไฟล์) → main cleaned `dd6fb478` (ลบ cache 8 ไฟล์ + .gitignore) — size: S
  - 🟡 **3 เงื่อนไขเคลียร์ครบแล้ว** — เหลือ verify GHA รุ่งขึ้น (step "Restore cache" + "Push cache to orphan cache branch" เขียวทั้งคู่) แล้วค่อยปลดล็อกขยาย IR เป็นทางการ

> ✅ **`build_grouped_with_barcodes.py` — verified จบ 2026-06-12 PM7:** รันจริงบน Windows ผ่านทั้ง v1 passthrough และ v2 decoded — ตัวเลข parity เป๊ะทุก count (65,812 products / 74,747 barcode rows / ACTIVE 117,019 / STALE 39,698 / LOST 65,714 / DISC 1,109) + xlsx saved → ย้ายไป Changelog

> ✅ **Compact JSON v2 — deployed + pushed 2026-06-12 PM** (daily-report `858db387` + lost-Product `fdeacd1`) → ย้ายไป Changelog แล้ว — **Antigravity ปลดล็อก lost-product builder/frontend**

---

## 📅 Next (Sprint หน้า)

- [x] ✅ **Phase 3c** — extracted to `dashboards/sales_data.py` + `html_patch.py` + `git_push.py` — `update_dashboard.py` 1160→939 lines (bugfix THAI_MON + factXX suppress) — 2026-06-14

- [x] ✅ **Phase 3d** — extracted to `dashboards/fraud_queries.py` (303L) + `fraud_agg.py` (211L) — `rebuild_fraud_analysis.py` 934→458 lines (−51%) — 2026-06-14

- [x] ✅ **Phase B: วันหมด (Days-until-OOS) column ใน product_dashboard** — JS-only, sortable, color-coded (≤7🔴 ≤14🟠 >14🔵 OOS/—) — 2026-06-14

- [x] ✅ **bugfix(3c): whsdd loop body** — 7 assignment lines dropped by Phase 3c surgery → `day_totals` never populated → `data_note='target(d1-0)'` every run + stale targets — restored, 939→946 lines — 2026-06-14

- [ ] **Verify all 210 stores in store_breakdown match expectations**
  - vs 203 in dim_branch
  - Check non-BL sono prefixes (WB? BC?) or non-POS warehouses
  - size: S

---

## 💭 Later (อยากทำ ยังไม่เร่ง)

- [ ] **Phase C: Dead Stock report** — no sale > 90 days + onhand > 0
  - New dashboard page
  - size: M

- [ ] **Phase D: Visual Adjustment audit** — track `ibl_locno='visual'` adjustments per cashier/store as fraud signal
  - Schema: `MYWMS2023_CENTER.ibl WHERE locno='visual' AND shelfno='adjustment'`
  - size: L

---

## 🧊 Icebox

- ~~Real-time stream processing~~ — daily batch ดีพอ
- ~~Move to self-hosted MySQL backend~~ — rejected (see Decisions.md)
- ~~Migrate all scripts to use `lib/`~~ — Phase 1 helpers ready แต่ Phase 3 strategy is better

---

## 🐛 Known Issues

- [x] **onhand = 0 ทั้ง JSON** — ✅ **resolved 2026-06-11**: หลัง patch stream cursor รันบน Windows ได้ 936,307 onhand rows — severity: medium
  - 🔬 Hypothesis (Claude 2026-06-11): **MemoryError** (`str(MemoryError()) == ''` = ตรงอาการ error ว่าง) — `query_onhand_per_store` ใช้ `fetchall()` + dict rows ทั้งตาราง ibl
  - 🩹 **Patched 2026-06-11** ใน `build_product_data_mysql.py`: stream tuple cursor แทน fetchall + ตัด `MAX(ibl_date_sale)` ที่ไม่ได้ใช้ + except พิมพ์ `type+repr+traceback` (ครั้งหน้า error จะไม่ว่าง)
  - ▶️ **Verify บน Windows:** `py build_product_data_mysql.py --no-push` → เช็ค log "N (iprod, store) onhand rows" > 0 + คอลัมน์ ONHAND บน dashboard มีค่า
  - หมายเหตุ: เริ่ม fail หลัง IR-B cache implement พอดี (06-10) — อาจเกี่ยว (memory pressure จาก parquet/pandas load ก่อนถึง onhand step)

- [ ] `fetch_missing_facts.py` warning ในทุก daily run — severi