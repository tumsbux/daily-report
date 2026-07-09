# CLAUDE.md — Dashboard System Index

**Project:** Tuensjai Panichkroup Co., Ltd. — Data Dashboard Suite
**Owner:** data.inwza.008@gmail.com (tumsbux)
**Working directory:** `F:\co work dashboard\`
**Repos:**
- Main: `tumsbux/daily-report` → https://tumsbux.github.io/daily-report/
- Lost Product: `tumsbux/lost-Product` → https://tumsbux.github.io/lost-Product/

---

## 🗜️ Headroom — Context Compression (เพิ่ม 2026-06-25)

ติดตั้งแล้ว — ลด token ที่ส่งให้ LLM ได้ 60–95% โดยไม่เปลี่ยนคำตอบ

**Scripts:**
- `headroom_install.bat` — รันครั้งเดียวเพื่อ install + setup MCP + copy scripts ไป projects อื่น
- `headroom_start.bat` — เปิด Claude Code พร้อม compression (ทุก project มีไฟล์นี้)
- `F:\facebook\headroom_start.bat` — สำหรับ facebook project

**วิธีใช้:**
1. รัน `headroom_install.bat` ครั้งแรกครั้งเดียว → restart Claude
2. ถ้าใช้ Claude Code CLI: ดับเบิลคลิก `headroom_start.bat` ใน folder นั้นแทนการเปิด claude ตรงๆ
3. MCP tools (`headroom_compress`, `headroom_retrieve`, `headroom_stats`) จะพร้อมใช้ใน Cowork หลัง restart

**Projects ที่ integrate แล้ว:**
- `F:\co work dashboard\` — ✅
- `F:\facebook\` — ✅
- `F:\lost-Product\`, `F:\lost-Product-git\`, `F:\lost-Product\thongfah_dashboard\` — auto-copy เมื่อรัน install bat

---

## 📂 Documentation (โหลดเฉพาะที่ต้องใช้)

| ไฟล์ | เนื้อหา | โหลดเมื่อ |
|---|---|---|
| [Architecture.md](./Architecture.md) | Tech stack, pipeline, file inventory, DB schema | งานใหม่, แก้ pipeline, สำรวจ DB |
| [Design.md](./Design.md) | Dashboard views, color rules, GA4 | งาน frontend / UI |
| [Decisions.md](./Decisions.md) | ADR — ทำไม schedule แบบนี้, ทำไม split repo | ก่อนเปลี่ยน architecture |
| [Gotchas.md](./Gotchas.md) | Edit tool truncation, sono format trap, PS+git | debug เจอ error แปลก |
| [Roadmap.md](./Roadmap.md) | Phase 3c/3d, B/C/D (OOS / Dead Stock / Visual Adj) | วางแผนต่อ |
| [Changelog.md](./Changelog.md) | งานที่ทำเสร็จ (Phase 3b, Lost Product, etc.) | review |
| [Skill.md](./Skill.md) | บทเรียนส่วนตัว (Edit tool, probe-first, etc.) | ทบทวนเอง |
| [How_To_Modify_Dashboards.md](./How_To_Modify_Dashboards.md) | คู่มือ user สำหรับแก้ UI/ETL/deploy | คนใหม่เริ่มงาน |
| [Column_Reference.xlsx](./Column_Reference.xlsx) | **Quick reference card** — ยอดขาย/ส่วนลด/GP/cost columns + DAX measures + SQL patterns | งาน Power BI / สร้าง measure ใหม่ |
| Google: `bill_level_comparison` | **ฉบับแก้ไข** — bld_acc vs fact_sales 231K bills, correct SQL, discount structure, data quality 99.95% | งาน GP / SQL / discount |
| Google: `comparison_blh_bld_vs_fact_sales` | ฉบับเดิม (⚠️ SQL มี bug) — ใช้ได้แค่ benchmark GP%, column mapping, action plan | อ้างอิง benchmark เท่านั้น |

---

## 🤝 Multi-Agent Collaboration (สำคัญ! เพิ่ม 2026-06-10)

User ทำงาน Dashboard ด้วย **2 agents** ขนานกัน:
1. **Claude (Cowork mode)** — Opus 4.7 / Sonnet 4.6 — ตัวที่กำลังอ่านอันนี้
2. **Antigravity (Gemini 3 Flash)** — Google Antigravity IDE — แก้ dashboard ตัวเดียวกัน

**กฎ collab:**
- **อ่าน `.md` ทุกไฟล์ก่อนเริ่มงาน** — ทั้ง 2 agents — ห้าม assume context จาก training
- **เขียน ADR ใน `Decisions.md` ทุก architectural change** — ก่อน touch code
- **Cache file (Phase IR) ต้องมี `_meta.built_by`** — track ว่า agent ไหน build (`claude-opus-4-7` vs `antigravity-gemini-3-flash`)
- **Schema/rule hash header** ป้องกัน agent หนึ่ง schema เปลี่ยน อีก agent อ่าน cache เดิมแล้วงง
- **Roadmap.md "Now" section** = source of truth สำหรับ in-flight work — ห้าม start งานที่ agent อื่น claim ไว้
- **CLAUDE.md** (ไฟล์นี้) = primary doc, ทั้ง 2 agents อ่าน
- **ถ้าเจอ commit ไม่รู้จัก:** อ่าน Decisions.md + Changelog.md ก่อนเสมอ

## 🔒 Verification Gates (จาก AI DevKit concept — เพิ่ม 2026-06-20)

**Rule 1 — No "done" without evidence:**
ทุก Roadmap item ก่อน mark ✅ ต้องมี verification evidence:
- Pipeline change → GHA run log หรือ manual Windows test output
- Dashboard change → screenshot หรือ verify step ใน bash
- SQL change → query result จาก MySQL MCP
ห้าม assume จากการที่ code ดูถูกต้อง

**Rule 2 — Plan-first, no-code-before-approval:**
ทั้ง Claude และ Antigravity: ถ้างานมี architectural impact (ใหม่, เปลี่ยน pipeline, schema, caching) ต้อง:
1. Draft plan ใน Decisions.md (ADR)
2. **STOP — รอ user confirm ก่อน**
3. ห้าม implement จนกว่าจะได้รับการ approve
Reason: Antigravity IR-B/C/D incident 2026-06-10

---

## 🔔 Session Management Rules (user preference)

- **Warn at long context (~85%):** เมื่อรู้สึก conversation ยาวมาก (อ่านไฟล์ใหญ่ + tool หลายรอบ) ให้แจ้งผู้ใช้**ทุกครั้ง**ก่อนทำงานต่อ — แนะนำให้เริ่มแชทใหม่ใน Cowork
- **Summary recap before session ends:** สรุปสิ่งที่ทำในเซสชันให้กระชับ (commit list + ผลลัพธ์หลัก) ทุกครั้งก่อน session อาจถูกตัด
- **Update docs every fix:** ทุกครั้งที่แก้/เพิ่ม feature ให้ sync ไฟล์ที่เกี่ยวข้องทันที + push ขึ้น main
- **ข้อจำกัด:** Cowork ไม่มี `/compact` — วิธีเดียวคือเริ่มแชทใหม่ Claude ไม่สามารถ monitor context % realtime — ต้อง self-estimate
- **Model note:** Opus 4.7 burns limits fast — งาน routine (update, push) ใช้ Sonnet ประหยัดกว่า

---

## ⚡ Quick Context

ระบบ Dashboard อัปเดตอัตโนมัติทุกวัน **08:30 Bangkok** ผ่าน **GitHub Actions** (ไม่ต้องเปิด laptop)

**Daily pipeline (single cron 08:30 BKK — `30 1 * * *` UTC):**
1. Restore cache from orphan branch `cache`
2. `rebuild_fraud_analysis.py --no-push` → builds fraud_data.json *(continue-on-error)*
3. `build_product_data_mysql.py --no-push` → builds product_data.json *(continue-on-error)*
4. `build_lost_product_data.py` → builds lost_product_data.json *(continue-on-error)*
5. push_lost_data → push JSON ไป tumsbux/lost-Product repo
6. `update_dashboard.py` → updates sales + injects fraud/product → pushes daily-report
7. Push cache → orphan branch `cache` (force, single commit)

**Manual run (Windows):**
```powershell
& "F:\co work dashboard\run_manual_update.ps1"          # auto-detect day
& "F:\co work dashboard\run_manual_update.ps1" -Day 1   # specify day
```

---

## 🔑 Critical Rules

- **Sandbox เข้า MySQL host `203.154.83.62:13306` ไม่ได้** — verification ต้องรันบน Windows
- **`db_config.json` ห้าม commit** — มี MySQL password + GitHub PAT
- **Files pushed daily:** `index.html, sales_dashboard_v8.html, fraud_dashboard.html, fraud_analysis.html, fraud_data.json, product_dashboard.html, product_data.json, lost_product_dashboard.html, analytics.js` (lost_product_data.json ไป repo แยก)
- **Edit tool truncation bug** — อย่าใช้ Edit กับไฟล์ HTML/JS > 20KB ใช้ Python via Bash แทน (ดู Gotchas)
- **valid_store rule:** `int(code) <= 500` (excludes 901-999, WBT, WHC, WPT)
- **rebuild_fraud_analysis.py ต้องรันก่อน update_dashboard.py**
- **Two folders for lost-Product:** `F:\lost-Product\` = Cowork working copy (no .git), `F:\lost-Product-git\` = real git clone — edits ต้อง sync ทั้งสอง หรือทำใน `-git\` แล้ว copy กลับ

### 📊 Data Quality Rules (เพิ่ม 2026-06-19 — จาก Bill-Level Comparison Analysis)

- **ยอดขายสุทธิ = `SUM(net_sales_amt)`** — ห้ามหัก `prorated_discount` ซ้ำ (มันหักไว้แล้ว)
- **❌ `SUM(net_sales_amt - prorated_discount)` = ผิด** — หักซ้ำ ยอดห่าง ~185K/สัปดาห์
- **`sodisc` = rollup** ไม่ใช่ channel แยก — `sodisc = sodisc_bill + sodisc_score + sodisc_coupon + sodisc_perc` — ห้ามบวกซ้ำ
- **fact_sales = primary source for GP%** — bld_acc ขาดส่วนลดบิล → GP สูงเกิน ~0.37%
- **Ref:** Google Sheets `bill_level_comparison` (ฉบับแก้ไข) + ADR [2026-06-19] + Architecture.md §Bill-Level Comparison

---

## 🚀 Daily Workflow

1. **เริ่มงานใหม่** → อ่าน `Roadmap.md` ก่อน (Phase 3c/3d, B/C/D queued)
2. **ตัดสินใจอะไรสำคัญ** → บันทึกใน `Decisions.md`
3. **เจอ bug แปลก** แก้ได้แล้ว → เพิ่มใน `Gotchas.md`
4. **ทำงานเสร็จ** → update `Changelog.md` + ลบจาก `Roadmap.md`
5. **ไฟล์ไหนยาวเกิน ~300 บรรทัด** → พิจารณาแตกย่อย

---

## 🟡 Pending Approval (updated 2026-07-09)

- 🆕 **Store Price-Discount Dashboard — built, NOT pushed yet (2026-07-09):** `build_store_discount_data.py` + `store_discount_dashboard.html` + `store_discount_data.json` (92d backfill) พร้อมแล้วใน `F:\co work dashboard\`, เพิ่ม step ใน `daily-update.yml` แล้ว, ADR ใน Decisions.md `[2026-07-09]` — **ต้องรันบน Windows:**
  ```
  py push_files_api.py build_store_discount_data.py store_discount_data.json store_discount_dashboard.html .github/workflows/daily-update.yml Decisions.md CLAUDE.md Changelog.md -m "feat: add store price-discount dashboard"
  ```
  (Cowork sandbox เข้า `api.github.com` ไม่ได้ — 403 บน tunnel — ต่างจาก MySQL MCP ที่ใช้ได้)

## 🟡 Pending Approval (updated 2026-06-14)

- **Phase IR (Incremental Refresh)** — สถานะจริงหลัง Claude ตรวจ code 2026-06-11:
  - ✅ **IR-A (Lost Product)** — implemented + accepted (ADR `[2026-06-10]`, Parquet cache)
  - ⚠️ **IR-B/C/D (product + sales + fraud) — Antigravity implement ครบทั้งชุดแล้ว** (2026-06-10, `built_by: antigravity-gemini-3-flash` ใน `build_product_data_mysql.py` / `update_dashboard.py` / `rebuild_fraud_analysis.py` + cache files ครบ) **ทั้งที่ user ยังไม่อนุมัติ** และเขียน ADR `[2026-06-10] IR-B/C/D` สถานะ "Accepted" เองโดยไม่ผ่าน user
  - ✅ **User accept แบบมีเงื่อนไข (2026-06-11 PM)** — fraud cache lag ✅ document-only / verify onhand ✅ deployed / **repo bloat ✅ deployed 2026-06-12 PM7** (orphan branch `cache` + force-push): main `d57451ee` + branch `cache` `b42be68c` (11 ไฟล์) + main cleaned `dd6fb478` — **3 เงื่อนไขเคลียร์ครบ** เหลือ verify GHA รุ่งขึ้น (step Restore/Push cache เขียว) แล้วปลดล็อกขยาย IR
- ✅ **Compact JSON encoding — DEPLOYED 2026-06-12 PM**: verify บน Windows ผ่าน (49.5 MB, schema 2, dashboard render ปกติ) + pushed **daily-report `858db387`** + **lost-Product `fdeacd1`** — **🔓 Antigravity ปลดล็อก lost-product builder/frontend แล้ว** — ✅ `build_grouped_with_barcodes.py` verified จบ PM7: รันจริงบน Windows ทั้ง v1/v2 parity เป๊ะ + xlsx saved
- 🔌 **MySQL MCP — ✅ ใช้งานได้แล้ว (2026-06-12 PM5):** account `agent-102` READ-only — tools `mcp__mysql__execute_sql / get_schema_info / get_table_sample` ใช้ได้ใน Cowork — verify ผ่านครบ (dim_branch 203 / cross-DB / READ-only denied) — root cause 2 ชั้น: (1) Store version ใช้ config ที่ `%LOCALAPPDATA%\Packages\Claude_pzs8sxrjxfjjc\LocalCache\Roaming\Claude\` (2) ต้อง Quit จาก tray จริง (เช็ค `Get-Process *claude*` ว่าง) MCP ใหม่ถึงโหลด (ดู Gotchas.md + Architecture.md §MySQL MCP) — **password ห้าม commit ลง repo**
- 🖥️ **VM Dashboard Mirror (`agent-ab-sandbox.tjinternal.com:48081`) — identify + กู้คืนแล้ว 2026-06-12 PM5:** container mirror dashboards, sync จาก GitHub ทุก 10 นาที — service ตาย 11 มิ.ย. → restart แล้ว (ops คู่มือใน How_To_Modify_Dashboards.md §4b, ADR post-hoc ใน Decisions.md) — ✅ SSH creds ย้ายออกจาก scripts แล้ว 2026-06-13 (อ่านจาก `db_config.json`) — **ค้าง:** ขอ IT restart policy เท่านั้น — data ปัจจุบันวัน 11/30 (manual update 2026-06-12 20:02 หลัง push v2 พ่วงไฟล์เก่าทับ — ดู Gotchas)
- 📝 **Push mechanics:** `F:\co work dashboard\` **ไม่ใช่ git clone** — push daily-report ผ่าน GitHub API scripts (`push_files_api.py` เลือกไฟล์ / `push_py_to_github.py` hardcoded list) ส่วน lost-Product ใช้ `push_lost_data.ps1` (temp clone) — `F:\lost-Product-git\` มี stale `index.lock` ค้าง (2026-06-12) ใช้งานไม่ได้จนกว่าจะลบ
  - ⚠️ **`push_py_to_github.py` อันตราย** — hardcoded list รวม `.github/workflows/daily-update.yml` → ถ้า local เก่ากว่า GitHub จะทับ! ใช้ `push_files_api.py` แทนเสมอ (ดู Gotchas)
  - ✅ **PAT ปัจจุบัน (`dashboard-bot-4`, classic, repo+workflow scope)** — push `.github/workflows/` ได้ผ่าน script ปกติ — อัปเดต local `db_config.json` + VM + GHA secret แล้ว (2026-06-14)

- 🏪 **กิจกรรมธงฟ้า Dashboard (`tumsbux/thongfah-dashboard`) — deployed 2026-06-14:**
  - URL: `https://tumsbux.github.io/thongfah-dashboard/`
  - Scripts: `F:\lost-Product\thongfah_dashboard\` — `index.html`, `data.json` (160,753 rows, 45.3MB), `build_data.py`, `push_data_json.ps1`, `push_thongfah_update.py`
  - Fixed: grand total %GP + tfoot alignment + SQL GROUP BY error + index.html truncation
  - Added: date range filter, DT=14, GHA-compatible `build_data.py`
  - ✅ **GitHub Actions LIVE (2026-06-14):** Secrets (MYSQL_HOST/PORT/USER/PASSWORD) + `daily-update.yml` + Workflow permissions (R/W) → Daily Thongfah Update #1 succeeded (168,753 rows) — อัปเดตอัตโนมัติทุก 08:35 BKK
  - Push data.json: ใช้ `push_data_json.ps1` (git clone) — Contents API ปฏิเสธไฟล์ > 50MB
  - คู่มือ: `F:\lost-Product\คู่มือ_Dashboard_ธงฟ้า.docx`

---

_Last updated: 2026-06-23_
