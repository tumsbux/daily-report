# Roadmap

> งานค้าง + แผนต่อไป — เสร็จแล้วย้ายไป `Changelog.md`

---

## 🔥 Now (สัปดาห์นี้)

- [ ] **Tomorrow's auto-run sanity check (next 08:30 BKK)**
  - Visit https://tumsbux.github.io/lost-Product/
  - ตรวจ `อัปเดต: YYYY-MM-DD` chip
  - File size ~45-55 MB ใน github.com/tumsbux/lost-Product

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

- [ ] **Watch JSON size at end of June 2026**
  - If > 70 MB → growth faster than expected
  - Need option #2: sparse year encoding sooner

---

## 🧊 Icebox

- ~~Real-time stream processing~~ — daily batch ดีพอ
- ~~Move to self-hosted MySQL backend~~ — rejected (see Decisions.md)
- ~~Migrate all scripts to use `lib/`~~ — Phase 1 helpers ready แต่ Phase 3 strategy is better

---

## 🐛 Known Issues

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
- [ ] Phase 3c + 3d (continued refactor)

### Q3 2026
- [ ] Phase B (Days-until-OOS)
- [ ] Phase C (Dead Stock report)
- [ ] Phase D (Visual Adjustment audit / fraud signal)

---

_Last updated: 2026-06-10_
