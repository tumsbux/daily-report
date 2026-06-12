# Roadmap

> งานค้าง + แผนต่อไป — เสร็จแล้วย้ายไป `Changelog.md`

---

## 🔥 Now (สัปดาห์นี้)

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
  3. [ ] **Repo bloat** — ✅ **approved + implemented 2026-06-12 PM6 (Claude)**: workflow +2 steps / ตัด cache จาก push lists / `.gitignore` / `setup_cache_branch.py` — ⏳ **เหลือ user รัน:** (1) `py push_cache_migration.py` (2) `py setup_cache_branch.py` แล้วเช็ค GHA รุ่งขึ้น (restore จาก origin/cache + force-push กลับ) → เคลียร์เงื่อนไขครบ — size: S
  - 🚫 ห้ามทั้ง 2 agents ขยาย IR เพิ่มจนกว่า 3 ข้อเคลียร์ — ADR Decisions.md `[2026-06-10]` updated — เหลือข้อ 3 ข้อเดียว

> ✅ **`build_grouped_with_barcodes.py` — fixed 2026-06-12 PM (Claude):** เพิ่ม v2 decode (v1 passthrough) + แก้ DB join key เป็น JSON `iprod` ตาม naming trap — PM6: pre-verify ผ่าน MySQL MCP แล้ว (join key ตรงทุก sample รวม bridge case, coverage 145/150) — เหลือรันจริงบน Windows: copy JSON v2 จาก `F:\co work dashboard` มาก่อน (local เป็น v1 เก่า) แล้ว `py build_grouped_with_barcodes.py`

> ✅ **Compact JSON v2 — deployed + pushed 2026-06-12 PM** (daily-report `858db387` + lost-Product `fdeacd1`) → ย้ายไป Changelog แล้ว — **Antigravity ปลดล็อก lost-product builder/frontend**

---

## 📅 Next (Sprint หน้า)

- [ ] **Phase 3c** — extract `update_dashboard.py` sections to `dashboards/sales_data.py` + `dashboards/html_patch.py` + `dashboards/git_push.py`
  - size: M
  - depends: Phase 3b verification (done)

- [ ] **Phase 3d** — decompose `rebuild_fraud_analysis.py` (757 lines) similarly
  - size: M
  - depends: Phase 3c pattern established

- [ ] **Phase B: Days-until-OOS column on product_dashboard**
  - Formula: `onhand ÷ avg_daily_run_rate`
  - JS-only change (data already in JSON)
  - size: S

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

- [ ] `fetch_missing_facts.py` warning ในทุก daily run — severity: low
- [ ] pandas SQLAlchemy warning ทุกครั้งที่รัน — severity: low
- [ ] Console cmd window ค้างทั้งวัน — severity: low (cosmetic)
- [ ] `update_dashboard_v1_backup.py` ยังอยู่ root — clean up after stable Phase 3b — severity: trivial
- [ ] `CLAUDE.old.md` (73KB backup) — เก็บไว้ก่อน ลบทีหลังเมื่อมั่นใจ split สมบูรณ์

---

## 🎯 Quarterly Goals

### Q2 2026
- [x] Lost Product dashboard (live at https://tumsbux.github.io/lost-Product/)
- [x] Phase 3b refactor (–209 lines, verified zero drift)
- [x] Documentation split (CLAUDE.md 73KB → 8 files)
- [x] Phase IR-A: Lost Product Caching via Parquet
- [x] Phase IR-B, IR-C, and IR-D Caching Architecture & Sunday Full-Refresh ⚠️ *unilateral by Antigravity — under review (ดู Now)*
- [ ] Phase 3c + 3d (continued refactor)

### Q3 2026
- [ ] Phase B (Days-until-OOS)
- [ ] Phase C (Dead Stock report)
- [ ] Phase D (Visual Adjustment audit / fraud signal)

---

_Last updated: 2026-06-12 (PM6)_