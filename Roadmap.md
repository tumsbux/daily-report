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

- [ ] ✅→⚠️ **IR-B/C/D: user accept แบบมีเงื่อนไข (2026-06-11 PM)** — เหลือเคลียร์ 3 เงื่อนไข:
  1. [ ] **Fraud cache lag 1 วัน** — fraud (step 1) อ่าน `sales_daily` cache ที่เขียนโดย step 5 ของเมื่อวาน → document หรือแก้ลำดับ pipeline — size: S
  2. [x] **Verify onhand patch** — ✅ verified 2026-06-12 (รันบน Windows): `936,307 (iprod, store) onhand rows from MYWMS ibl` (stream-cursor patch แก้ MemoryError สำเร็จ) — size: XS
     - ⚠️ **patch ยังไม่ deploy:** repo copy ของ `build_product_data_mysql.py` ยังเป็นตัวเก่า (เช็ค raw 2026-06-12) → user ต้อง `py push_py_to_github.py` + รัน `py build_product_data_mysql.py` (ไม่ใส่ --no-push) เพื่อให้เว็บได้ onhand
     - ⚠️ GHA 2026-06-12 ไม่ fire เลยทั้ง 5 cron slots (เช็ค 11:00 BKK) — ใช้ workflow_dispatch แทน
  3. [ ] **Repo bloat** — parquet cache push รายวัน โต GB/ปี → เสนอแนวแก้ (ไม่ commit parquet / orphan branch / etc.) — size: S
  - 🚫 ห้ามทั้ง 2 agents ขยาย IR เพิ่มจนกว่า 3 ข้อเคลียร์ — ADR Decisions.md `[2026-06-10]` updated

- [ ] 🚧 **Compact JSON encoding — user อนุมัติแล้ว (2026-06-11 PM), Claude implement** *(claimed by: Claude)*
  - แผน: ADR `[2026-06-11] Compact JSON encoding` — barcode index + array-form products, 74.2 → ~43 MB
  - Breaking format: แก้ `build_lost_product_data.py` + `index.html` (lost-Product) + XLSX export ใน commit เดียว + `_meta.schema` version
  - 🚫 **Antigravity ห้าม touch lost-product builder/frontend จนกว่างานนี้เสร็จ**
  - size: M

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

_Last updated: 2026-06-11 (PM)_
