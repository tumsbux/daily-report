# CLAUDE.md — Dashboard System Context

**Project:** Tuensjai Panichkroup Co., Ltd. — Data Dashboard Suite  
**Owner:** data.inwza.008@gmail.com (tumsbux)  
**Working directory:** `F:\co work dashboard\`  
**GitHub Pages:** https://tumsbux.github.io/daily-report/  
**Repo:** github.com/tumsbux/daily-report (branch: `main`)

---

## 🔔 Session Management Rules (user preference)

- **Warn at long context (~85%):** เมื่อรู้สึก conversation ยาวมาก (อ่านไฟล์ใหญ่ + tool หลายรอบ) ให้แจ้งผู้ใช้ **ทุกครั้ง** ก่อนทำงานต่อ — แนะนำให้เริ่มแชทใหม่ใน Cowork (CLAUDE.md auto-load ให้ session ใหม่)
- **Summary recap before session ends:** สรุปสิ่งที่ทำในเซสชันให้กระชับ (commit list + ผลลัพธ์หลัก) ทุกครั้งก่อน session อาจถูกตัด
- **Update CLAUDE.md every fix:** ทุกครั้งที่แก้/เพิ่ม feature ให้ sync CLAUDE.md ทันที + push ขึ้น main (CLAUDE.md อยู่ใน repo แล้วตั้งแต่ 2026-06-04 → session ใหม่ pickup ได้เลย)
- **ข้อจำกัด:** Cowork ไม่มี `/compact` (มีแต่ใน Claude Code CLI) — วิธีเดียวคือเริ่มแชทใหม่ Claude ไม่สามารถ monitor context % realtime ได้ ต้อง self-estimate จากความยาว
- **Model note:** Opus 4.7 burns limits fast — สำหรับงาน routine (update, push) ใช้ Sonnet ได้ ประหยัดกว่า

---

## ⚡ Quick Context

ระบบ Dashboard อัปเดตอัตโนมัติทุกวัน 08:30 Bangkok ผ่าน **GitHub Actions** (ไม่ต้องเปิด laptop)

**Daily pipeline (GitHub Actions — 08:30 Bangkok / 01:30 UTC):**
1. `rebuild_fraud_analysis.py --no-push` → builds fraud_data.json *(continue-on-error)*
2. `build_product_data_mysql.py --no-push` → builds product_data.json *(continue-on-error)*
3. `update_dashboard.py` → updates sales + injects fraud/product data → pushes to GitHub Pages

**Manual run:**
```powershell
& "F:\co work dashboard\run_manual_update.ps1"          # auto-detect day
& "F:\co work dashboard\run_manual_update.ps1" -Day 1   # specify day
```

---

## GitHub Actions Workflow

**File:** `.github/workflows/daily-update.yml`  
**Schedule (อัปเดต 2026-06-04 รอบ 2):** Multi-cron 5 slots ทุก 30 นาที จาก `30 0 * * *` ถึง `30 2 * * *` UTC (= **07:30–09:30 BKK**) — 08:30 BKK เป็น primary target รอบอื่น fallback ถ้า delay  
**เหตุผล data timing:** fact_sales / fact_returns ETL จริงเข้าที่ 07:00 BKK — รัน cron ก่อนหน้านั้นจะ query data เก่า ไม่มีประโยชน์ ต้องเริ่มที่ 07:30 BKK (+30 นาที buffer)  
**เหตุผล multi-slot:** GH Actions free tier cron delay 0-5 ชม. ขึ้นกับ queue ตั้งหลาย slot ดักให้รอบใดรอบหนึ่งใกล้ 08:30 มากที่สุด รอบที่ commit สำเร็จเป็นรอบแรก รอบที่เหลือ skip อัตโนมัติ (`if: steps.guard.outputs.skip != 'true'`)  
**Concurrency:** `group: daily-update, cancel-in-progress: false` — ป้องกัน race ถ้า 2 รอบยิงทับกัน  
**Fraud step:** `continue-on-error: true` — sales always updates even if fraud fails.  
**Manual trigger:** github.com/tumsbux/daily-report/actions/workflows/daily-update.yml → Run workflow (bypass guard)

**Secrets** (github.com/tumsbux/daily-report/settings/secrets/actions):
`DB_HOST`, `DB_PORT`, `DB_USER`, `DB_PASSWORD`, `DB_DATABASE`, `GH_PAT`

---

## File Inventory

### Shared library (`lib/`) — added 2026-06-05 (Phase 1 refactor)

| Module | Purpose |
|--------|---------|
| `lib/db.py` | `get_conn()` + `get_config()` — MySQL connection helper. Replaces 13 duplicate connect blocks across scripts. Also exposes `github_token()` / `github_repo()`. |
| `lib/dates.py` | `current_month()`, `thai_month_name()`, `TH_MONTHS` / `TH_MONTHS_SHORT`, `days_in_month()`, `month_key()`, `valid_store()`. Use these instead of redeclaring per script. |
| `lib/safe_write.py` | `safe_write_html()` + `safe_write_json()` — write then verify `</html>` / re-parse JSON; raises `HtmlTruncationError` / `JsonTruncationError` if truncated. **Use for all HTML > 200KB writes** (guards Edit tool truncation bug from CLAUDE.md 2026-06-04). |

Usage:
```python
from lib.db import get_conn
from lib.dates import current_month, thai_month_name, valid_store
from lib.safe_write import safe_write_html
```

**Migration status:** Scripts have NOT yet been migrated to use these helpers (Phase 3 work, on branch). Production scripts still have own connect blocks. New scripts MUST use `lib/`.

### Dashboard package (`dashboards/`) — added 2026-06-05 (Phase 3a refactor)

| Module | Purpose |
|--------|---------|
| `dashboards/helpers.py` | Pure functions extracted from `update_dashboard.py` lines 55-77 — `valid_store`, `extract_json`, `safe_pct`, `safe_yoy`. Behavior identical to originals. |
| `dashboards/mysql_queries.py` | DB query functions extracted from `update_dashboard.py` lines 79-286 + 299-321 — `query_returns_mtd`, `query_txn_mtd`, `query_prev_year_same_month` (renamed from `_query_fact_sales_may25`, now takes year/month as params), `query_fact_sales_mtd`, `query_whsdd`, `autodetect_max_day`. |

**Status (after Phase 3b — 2026-06-05):** `update_dashboard.py` now imports from `dashboards/` instead of defining duplicates. Reduced 1215 → 1006 lines (–209). Old names preserved via `as` aliases so call sites unchanged — zero blast radius.

Imports added at line ~54:
```python
from dashboards.helpers import valid_store, extract_json, safe_pct, safe_yoy
from dashboards.mysql_queries import (
    query_returns_mtd       as _query_returns_mtd,
    query_txn_mtd           as _query_txn_mtd,
    query_fact_sales_mtd    as _query_fact_sales_mtd,
    query_whsdd             as _query_whsdd,
    query_prev_year_same_month,
)
def _query_fact_sales_may25(cfg):  # backward-compat shim
    return query_prev_year_same_month(cfg, YEAR, MONTH)
```

**Verification on Windows (required before next daily push):**
1. Run `test_phase3b_parity.bat` — executes v1 backup and v2 new side-by-side with `--no-push`, diffs the generated HTML with `fc /b`. Expected: "no differences encountered" for both `sales_dashboard_v8` and `index.html`.
2. If diff found, inspect `*.v1.html` / `*.v2.html` snapshots side-by-side.

**Safety net:** `update_dashboard_v1_backup.py` retained as pre-Phase-3b copy. To revert: `copy update_dashboard_v1_backup.py update_dashboard.py`.

**Sandbox limitation noted:** sandbox cannot reach MySQL host `203.154.83.62:13306`, so byte-level parity must be verified on the Windows side.

**⚠️ Edit-tool null-byte padding (workaround applied 2026-06-05):** large Python file edits in this session left ~7.8KB of trailing `\x00` bytes (file size preserved but content was correct). Fix: `python3 -c "d=open('f','rb').read().rstrip(b'\\x00'); open('f','wb').write(d)"`. After any large `Edit` on a .py/.html file in the sandbox, verify with `python3 -c "print(b'\\x00' in open('f','rb').read())"` — should print `False`. py_compile catches this when nulls land mid-source but not if they're appended after the last newline.

Phase 3 staged plan:
- **3a ✅ DONE (2026-06-05)** — extract pure helpers + mysql_queries to `dashboards/`
- **3b ✅ DONE (2026-06-05)** — wired imports into `update_dashboard.py`, deleted 5 duplicate query defs + 4 helper defs (–209 lines), shim added for one signature change (`_query_fact_sales_may25` → `query_prev_year_same_month(cfg, YEAR, MONTH)`). **User must run `test_phase3b_parity.bat` on Windows before next daily push to confirm zero output drift.**
- **3c TODO** — extract `update_dashboard.py` STEP 1-7 sections to `dashboards/sales_data.py` + `dashboards/html_patch.py` + `dashboards/git_push.py`
- **3d TODO** — decompose `rebuild_fraud_analysis.py` (757 lines) similarly

### Archived (`scripts/`)

| Path | Reason |
|------|--------|
| `scripts/archive/build_product_data.py` | Legacy SQL-file-based product builder. Superseded by `build_product_data_mysql.py`. Moved 2026-06-05. |
| `scripts/explore/test_bld_acc_returns.py` | One-shot bld_acc returns exploration (June 2026). |
| `scripts/explore/test_bld_acc_vs_fact_sales.py` | One-shot sales source verification (June 2026, see Sales Data Source Verification section). |
| `scripts/explore/test_mysql_connection.py` | Connection smoke test. |
| `scripts/explore/test_rtd_acc_returns.py` | rtd_acc returns verification. |
| `scripts/explore/explore_schema.py` | One-shot schema dump. |
| `scripts/explore/fetch_missing_facts.py` | Backfill missing factXX.txt (rarely needed now). Auto-detects current month after 2026-06-05 fix. |
| `scripts/explore/fetch_old_html.py` | Recover old HTML from GH Pages. |

### Production scripts (root)

| File | Purpose |
|------|---------|
| `update_dashboard.py` | Master daily runner. MySQL → sales dashboard → index.html → inject fraud → push GitHub. |
| `rebuild_fraud_analysis.py` | Fraud ETL. Queries fact_returns → fraud_data.json. Run BEFORE update_dashboard.py. |
| `build_product_data_mysql.py` | Queries fact_sales + dim_product → product_data.json. |
| `inject_fraud_only.py` | Re-inject fraud_data.json into fraud_dashboard.html without MySQL query. |
| `run_manual_update.ps1` | One-command wrapper: runs all 3 scripts in order. Supports `-Day N`. |
| `sales_dashboard_v8.html` | Main sales dashboard. |
| `index.html` | Dashboard Hub — KPI summary + navigation. |
| `fraud_dashboard.html` | Fraud Detection Dashboard (rebuilt from template + fraud_data.json). |
| `fraud_analysis_template.html` | **Template base** for fraud_dashboard.html. Contains JS logic + `PLACEHOLDER_DATA`. Never overwrite. |
| `product_dashboard.html` | Top products by sales value with YoY. |
| `analytics.js` | Shared GA4 tracking module (included in all 4 dashboards). Must be in push_files. |
| `fraud_data.json` | Serialised fraud analysis data. |
| `product_data.json` | Serialised product data, stamped with today's date on every push. |
| `db_config.json` | **SECRETS — never commit.** MySQL credentials + github_token. |
| `target.txt` | Daily store targets fallback if MySQL down. |
| `data-lake_fact_returns.sql` | Static export of fact_returns. Fallback if MySQL down. |

**Files pushed to GitHub:** `index.html`, `sales_dashboard_v8.html`, `fraud_dashboard.html`, `fraud_analysis.html`, `fraud_data.json`, `product_dashboard.html`, `product_data.json`, `analytics.js`

---

## Credentials

```json
{
  "host": "<MySQL cloud host>", "port": 3306,
  "user": "<db username>", "password": "<db password>",
  "database": "<schema name>",
  "github_token": "ghp_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
}
```

---

## Data Sources & Key Logic

| Table | Content |
|-------|---------|
| `MYPOS2018_CENTER.whsdd` | Daily store targets (`whsddptar`) and actuals (`whsddpact`). Fallback: `target.txt`. |
| `fact_returns` | Return bills. Use `allocated_net_amount`. Filter `rtstatus='U'`. |
| `fact_sales` | Sales lines. Use `net_sales_amt`, `sotowhs`, `sono`. `solinetype NOT IN ('C','R')`. |
| `dim_product` | Product dimension for product dashboard. |

### Store filtering rule
```python
def valid_store(code):
    try:    return int(code) <= 500
    except: return False   # excludes 901-999, WBT, WHC, WPT etc.
```

### Closed Branches (ปิดถาวร — มีใน whsdd แต่ไม่มียอดใน fact_sales)
| Branch | Name | หมายเหตุ |
|--------|------|---------|
| 213 | เยาณิเวศน์ (สน-4) | ปิดแล้ว — Target = 0 |
| 217 | ย่องสระแก (พบ-3) | ปิดแล้ว — Target = 0 |
| 230 | สะพานดำ (สย-14) | ปิดแล้ว — Target = 0 |

ทั้ง 3 สาขานี้ทำให้ fraud script count ได้ 203 stores แต่ sales MTD query ได้ 202 — **ปกติ ไม่ใช่ bug**

### Core formulas
```
Net MTD Sales   = whsddpact − allocated_net_amount (returns)
GP Amount       = net_sales_amt − total_cost
Daily Rate      = Net MTD / FACT_DAYS  (ไม่ใช่ DAYS_ELAPSED)
Projected       = Daily Rate × days_in_month
vs Target MTD%  = Net MTD / Σ whsddptar (days 1–N)
```

**Two separate day variables:**
- `DAYS_ELAPSED` = query window / displayed day number (from `--day` or fact_sales auto-detect)
- `FACT_DAYS` = actual max day seen in fact_sales (may lag ~3 days behind DAYS_ELAPSED)

### Data lag
- `fact_sales` ล้าหลัง ~3 วัน → ใช้ `MAX(DAY(sodate))` auto-detect
- `whsddpact` ล้าหลัง 1–2 วัน → ใช้ `--day N` หรือ auto-detect

### solinetype
Dashboard ใช้ `solinetype NOT IN ('C', 'R')` (ตรงกับ mobile app)  
หมายเหตุ: ก่อนหน้านี้ใช้ `solinetype = 'N'` ซึ่งต่างจาก app ~14.5M/เดือน — แก้แล้ว 2026-05-31

---

## update_dashboard.py — Key Behaviors

**Month auto-detect** (ตั้งแต่ 2026-06-02):
- `YEAR`, `MONTH`, `MONTH_NAME_TH` auto-detect จาก `date.today()` ทุกต้นเดือน
- `_TH_MONTHS`, `_TH_MONTHS_SHORT` — Thai month names/abbreviations ทั้งยาวและย่อ
- ก่อน save HTML: replace month labels อัตโนมัติ (CE year, BE year, bare abbr `พ.ค.</div>`, `/5/2569`)

**index.html chart rebuild** (ตั้งแต่ 2026-06-02):
- `const months`, `m26vals`, `m25vals` rebuild จาก `D.summary.m26_tot`/`m25_tot` — เพิ่มเดือนใหม่อัตโนมัติ

**YoY baseline auto-detect + same-source** (แก้ 2026-06-04):
- `_query_fact_sales_may25()` เดิม hardcode `MONTH(sodate) = 5` → header card "YYYY (ทั้งเดือน)" โชว์ May 2025 ทั้งที่ label เป็น มิ.ย.
- แก้ query: `YEAR(sodate) = {YEAR-1} AND MONTH(sodate) = {MONTH}` — auto-detect
- **Same-source sync (2nd fix):** Header card อ่าน `s.s25_may` (จาก fact_sales) แต่ list "ยอดขายรายเดือน 2025" อ่าน `s.m25[YYYY-MM]` (legacy data) → ต่างกัน ~26 บาท/store เพราะคนละ table
- แก้: ใน update_dashboard.py หลัง set `s.s25_may` แล้ว → set `s.m25[YEAR-1-MONTH] = round(s25)` ด้วย (store + entity + summary.m25_tot ทั้ง 3 levels) → ทั้งสองอ่านจาก fact_sales เดียวกัน ตรงเป๊ะ
- ฟังก์ชันยังชื่อ `_query_fact_sales_may25` + field `s25_may` (legacy name) แต่ทำงาน dynamic

**sales_dashboard_v8.html `MTH` dynamic** (แก้ 2026-06-04):
- เปลี่ยน `const MTH = {...}` (static dict ขาด 2025-01..04, 2026-06, label ผิด `2025-05`/`2026-05` เป็น "มิ.ย.") → **JS Proxy auto-format** ทุก key `YYYY-MM` เป็น `ม.ค. 25` style
- MTD key auto-detect จาก `new Date()` → ต่อท้าย ` (MTD)` ให้เดือนปัจจุบัน
- ไฟล์ static ไม่ถูก regenerate ใน `update_dashboard.py` → fix นี้ persist ข้าม daily run
- ตำแหน่ง: `sales_dashboard_v8.html` บรรทัด 221-223 (`_TH_MO_S`, `_MTD_KEY`, `MTH` Proxy)

**Fraud injection** (ตั้งแต่ 2026-06-02):
- ถ้า `fraud_dashboard.html` local truncated (ไม่มี `</html>`) → regenerate จาก `fraud_analysis_template.html` + inject data
- Template ใช้ `PLACEHOLDER_DATA` แทน embedded JSON

**Files pushed:** `index.html`, `sales_dashboard_v8.html`, `fraud_dashboard.html`, `fraud_analysis.html`, `fraud_data.json`, `product_dashboard.html`, `product_data.json`, `analytics.js`

---

## build_product_data_mysql.py

**MONTH auto-detect** (แก้ 2026-06-05 — Phase 2 refactor):
```python
_today = date.today()
YEAR26, MONTH = _today.year, _today.month
YEAR25        = YEAR26 - 1
```
ไม่ต้อง edit ทุกต้นเดือนอีก ✅
**days_elapsed** — auto-detect จาก `MAX(DAY(sodate))` ใน fact_sales (`--day N` override ได้)

**Line Type modal** (`query_sales_by_linetype`) — แก้ 2026-06-03: เพิ่ม `AND solinetype NOT IN ('C','R')` ให้ตรงกับ canonical rule (เดิมไม่มี → modal โชว์ C/R ทำให้ total bills เกิน เช่น C=1,236 บิล ฿0)

---

## fraud_analysis_template.html

Template base สำหรับ fraud_dashboard.html. มี `const D = PLACEHOLDER_DATA;` — inject ด้วย fraud_data.json

**⚠️ RESTORED 2026-06-03 — full-featured version (จาก git commit `afaa0d5`):**
ช่วงต้น มิ.ย. เคยมีเวอร์ชัน "ย่อ" มาแทน ทำให้ **Return Bill toolbar หาย** (ปุ่ม ดูตามพนักงาน/สินค้า/ร้าน + จัดกลุ่มตามเหตุผล + export XLSX/PDF) กู้กลับจาก `afaa0d5` (29 พ.ค. — เวอร์ชันสุดท้ายที่มี export) แล้วแปลงเป็น template (embed data → `PLACEHOLDER_DATA`) + patch month label เป็น dynamic
- **Data contract = LONG names**: JS อ่าน `D.generated`, `D.data[mo].stats.total_rows/total_amount/...`, `D.store_risk` (ไม่ใช่ `D.gen`/`n`/`D.sr`)
- `update_dashboard.py` ผลิต contract นี้อยู่แล้ว (`_rename_stats` ฯลฯ → `_new_D={generated,months,data:_new_data,store_risk}`) ✅
- `inject_fraud_only.py` แก้ 2026-06-03 ให้ตรง (เดิมผลิต `gen`/short-name/`sr` → ใช้กับ template นี้ไม่ได้) ตอนนี้ผลิต `generated`/`new_data`(long)/`store_risk`
- View toggle buttons: `so-view-btn`/`so-prod-btn`/`so-store-btn`/`so-reason-btn` (handlers `soToggle*`) · Export: SheetJS (cdnjs xlsx 0.18.5) + `window.print` สำหรับ PDF
- **อย่าใช้เวอร์ชันย่ออีก** (backup ไว้ที่ `fraud_analysis_template_minimal_bak.html`)
- หากต้องกู้ full version อีก: `git show afaa0d5:fraud_dashboard.html` แต่ **ต้อง byte-faithful** (PowerShell `>` ทำ Thai เป็น mojibake — ใช้ `git checkout afaa0d5 -- <file>` + `Copy-Item` แทน)

**Month label** — dynamic ไม่ hardcode (restored template ใช้ตัวแปร `monthLabels`):
```js
const TH_MO_S=['','ม.ค.','ก.พ.','มี.ค.','เม.ย.','พ.ค.','มิ.ย.','ก.ค.','ส.ค.','ก.ย.','ต.ค.','พ.ย.','ธ.ค.'];
const monthLabels=Object.fromEntries((D.months||[]).map(k=>{const p=k.split('-');return[k,(TH_MO_S[+p[1]]||k)+' '+p[0]];}));
// dropdown: o.textContent = monthLabels[m]||m   → '2026-06' => 'มิ.ย. 2026'
```
ก่อนหน้านี้ hardcode `{'2026-03':'มี.ค. 2026',...}` → ทำให้เดือนใหม่แสดงเป็น raw key เช่น "2026-06"
หมายเหตุ: `update_dashboard.py` normal-path มี regex แทน `const ML={...}` (ของ template เก่า) — กับ template ใหม่ที่ใช้ `monthLabels` regex นี้ no-op (ไม่กระทบ เพราะ dynamic อยู่แล้ว)

**renderSoProduct arrow bug** (แก้ 2026-06-04): View "ดูตามสินค้า" ใน Return Bill เดิม render `▶ ` ที่ cells[3] (ชื่อสินค้า) ใน `renderSoProduct` แต่ `prodRowClick` ไป modify cells[1] (PARENT CODE) ด้วย `substring(2)` ตอน expand/collapse → ตัดอักษร 2 ตัวแรกของ parcode ทิ้ง (เช่น `5729500000291` → `▶ 29500000291`). ลบ ▶ ออกทั้งใน initial render + handler ลบ substring corruption — ตอนนี้ row คลิก expand/collapse ได้เฉยๆ ไม่มี indicator (เพิ่มกลับใน cells[3] ได้ถ้าต้องการ)

**Overview KPI card #3** (แก้ 2026-06-02): เปลี่ยนจาก "Repeat rtsono" (`n_so_dup`/`so_dup_amt` = 8 bills) → **"Return Bill"** (`n`/`total` = ยอดบิล return ทั้งหมด เช่น 131 bills · ฿18,270)
```js
{l:'🧾 Return Bill',v:fmt(n)+' bills',sub:'฿'+fmt(total),c:'kr'},
```
หมายเหตุ: doughnut "Fraud Signals" ยังใช้ label "Repeat rtsono" ถูกต้อง (เป็น fraud-signal breakdown คนละตัวกับ KPI card)

---

## rebuild_fraud_analysis.py

- ดึง returns 3 เดือนย้อนหลัง + current month
- **ไม่ exclude partial month** (ลบ `day <= 6` exclusion ออกแล้ว 2026-06-02) → June แสดงใน dropdown ทันที
- fraud script count 203 stores (รวม branch ปิด) vs sales 202 — ปกติ
- **`so` = บิลคืนทั้งหมด (แก้ 2026-06-03)**: เดิม `so = so[so['lines']>1]` (เฉพาะบิล >1 ไลน์) ทำให้ Return Bill tab โชว์แค่ subset (เช่น 14 จาก 235) เปลี่ยนเป็น `so_all` (ทุกบิล, `so_list = so.head(500)` cap 500) ส่วน **`so_dup = so_all[lines>1]`** เก็บไว้ทำ stat `n_so_dup`/`so_dup_amt` (Fraud Signals doughnut ยังถูก) · template `renderSo` count = `rows.length` (ตรงกับที่แสดงจริง ไม่ใช่ total_rows)

---

## GA4 Analytics

**Measurement ID:** `G-E3ZFFKXFT8` (property: "Tuenjai Dashboard")  
**File:** `analytics.js` — shared module, included ทุก dashboard  
**Events:** `dashboard_viewed`, `filter_applied`, `filter_reset`, `view_changed`, `sort_changed`, `linetype_modal_viewed`, `search_performed`, `data_load_failed`, `dashboard_navigated`  
**Custom Dimensions (7):** `dashboard_name`, `filter_scope`, `filter_rm`, `filter_dm`, `filter_store`, `days_elapsed`, `data_month`  
**⚠️ ถ้า GA4 หายหลัง daily run:** ตรวจสอบว่า `analytics.js` อยู่ใน `push_files` ใน `update_dashboard.py`

---

## Dashboard Views

### index.html — Hub
Hero KPIs: ยอดขาย MTD, vs เป้า MTD, Projected, YoY Projected, GP% | 4 KPI cards | RM table | Monthly trend chart

### sales_dashboard_v8.html — Sales
| View | Content |
|------|---------|
| Home | KPI cards, Gauge YoY, Monthly Trend chart |
| RM/DM/Store | Detail tables + charts |
| Executive | 7-section report; `excTarget = total_target × 1.155` (+15.5% challenge) |
| Report | RM cards + DM table + charts |

### fraud_dashboard.html — Fraud Detection
Tabs: Overview · Store Risk · พนักงาน (rtuname) · Return Bill · เวลา · ร้าน · DM · RM  
Risk badges: HIGH / MEDIUM / LOW

### product_dashboard.html — Products
Top products by sales value. Store/DM/RM filter. YoY comparison. Line Type modal.

---

## D.summary JSON Key Fields

```
days_elapsed, days_remaining, total_mtd, total_target, total_mtd_target,
total_pct_target, total_proj, total_proj_vs_tgt, total_s25, total_proj_yoy,
total_gp_mtd, total_gp_pct, total_txn, total_daily_txn, total_ticket_avg,
total_ticket_avg_25, total_ticket_avg_yoy, total_txn_yoy, total_ret_mtd,
total_ret_daily, total_ret_per_store, month_name (Thai),
m26_tot {YYYY-MM: amount}, m25_tot {YYYY-MM: amount}
```

---

## Common Pitfalls & Prevention

- **File truncation:** HTML files ขนาดใหญ่อาจ truncated ถ้า write crash กลางทาง → dashboard blank หรือ JS ไม่ทำงาน  
  Restore: `git show <commit>:<file> > <file>` then re-inject data  
  Prevention: ตรวจ `tail -5 <file>` ให้ลงท้ายด้วย `</html>`  
  Sizes: `sales_dashboard_v8.html` ≈ 290KB+, `index.html` ≈ 19KB+, `product_dashboard.html` ≈ 31KB+

- **⚠️ Edit tool truncation on long-line HTML (พบ 2026-06-04):** Claude `Edit` tool บนไฟล์ที่มีบรรทัดยาวมาก (เช่น `sales_dashboard_v8.html` ที่ embed D เป็น minified JSON บรรทัดเดียว ~243KB) อาจ **ตัดท้ายไฟล์เงียบๆ** หลัง replace สำเร็จ — ไม่มี error report  
  Case: แก้ `const MTH` บรรทัด 221 สำเร็จ แต่ท้ายไฟล์หาย `updateTopDate(); goHome(); ...</html>` → dashboard render แค่ header (D โหลดได้) body ว่าง (`goHome()` ไม่ถูกเรียก)  
  Prevention: หลัง `Edit`/`Write` ไฟล์ HTML ขนาด > 200KB **ต้องเช็ค** `tail -c 200 <file>` ว่าลงท้าย `</html>` ทุกครั้ง  
  Recovery: `python3 -c "open('f','a').write('();\ngoHome();\n...</html>\n')"` ต่อท้าย หรือ `git show <prev>:<file> | tail -c 500` เทียบหาส่วนที่หาย

- **fraud_dashboard.html truncated:** `update_dashboard.py` จะ auto-detect และ regenerate จาก `fraud_analysis_template.html` อัตโนมัติ (ตั้งแต่ 2026-06-02)

- **fraud_data.json truncated:** ถ้า JSON ขาดกลางคัน (`Unterminated string` ตอน parse / tail ไม่ปิด `}`) → ต้อง regenerate จาก MySQL ด้วย `rebuild_fraud_analysis.py` (`inject_fraud_only.py` แก้ไม่ได้เพราะอ่าน json เดิม). วิธีฟื้นเร็วสุด: รัน `run_manual_update.ps1` บนเครื่อง Windows (sandbox เข้า MySQL host `203.154.83.62:13306` ไม่ได้). ตรวจ json ดี: `tail -c 50 fraud_data.json` ต้องลงท้ายด้วย `}]}` ไม่ใช่ขาดกลาง

- **Chart.js SRI hash:** อย่าใส่ `integrity=` attribute ใน Chart.js CDN tag — breaks silently

- **Store code padding:** MySQL อาจ return `'1'`, `'001'`, หรือ `1` (int) — scripts เก็บทั้ง raw และ padded keys

- **rebuild_fraud_analysis.py ต้องรันก่อน update_dashboard.py** — master runner อ่าน fraud_data.json ที่ rebuild สร้าง

- **whsddpact lag 1–2 วัน** — ใช้ `--day N` ถ้าจำเป็น หรือ auto-detect จาก fact_sales

- **GitHub Actions fraud step:** `continue-on-error: true` — yellow warning = ปกติ

- **analytics.js ต้องอยู่ใน push_files** ของ update_dashboard.py

---

## Developer Setup (New Machine)

1. Install Python 3 + `pip install mysql-connector-python pandas openpyxl`
2. Create `db_config.json` with MySQL credentials + GitHub PAT (repo write scope)
3. Test: `py test_mysql_connection.py`
4. Full run: `py rebuild_fraud_analysis.py --no-push && py build_product_data_mysql.py --no-push && py update_dashboard.py`
5. GitHub Secrets: DB_HOST, DB_PORT, DB_USER, DB_PASSWORD, DB_DATABASE, GH_PAT
6. **Never commit `db_config.json`**

---

## Data Reconciliation Reference

**Dashboard vs Mobile App** (as of June 2026, `solinetype NOT IN ('C','R')` fix applied):
- Dashboard ควรตรงกับ mobile app — returns ตรงทุกบาทเสมอ ✅
- ถ้าต่างกัน: ตรวจสอบ solinetype filter ใน queries

**fact_sales lag:** ล้าหลัง ~3 วัน — FACT_DAYS auto-detect ป้องกัน projected ต่ำเกิน  
**whsddpact lag:** ล้าหลัง 1–2 วัน — ใช้ `--day N` ถ้า day ล่าสุดยังไม่ finalize

Check last finalized day:
```sql
SELECT MAX(whsdddd) FROM MYPOS2018_CENTER.whsdd 
WHERE whsddyyyy=2026 AND whsddmm=6 AND whsddpact > 0
```

---

## 🗄️ Database Knowledge Base — MyPOS 2018 + MyWMS 2023

> Source: Google Drive / "database - tj" (`1a1t3DlWvoIQmDzpCxCr4BfGxra7rt5Ou`)
> Files: `mypos-dbml.txt` (130KB, ~101 tables) · `mywms-dbml-rag.txt` (52KB, ~52 tables)
> Owner: bopitbopit@gmail.com | Added: 2026-06-04

### System Overview

| System | Name | Purpose |
|--------|------|---------|
| **MyPOS 2018** | Point-of-Sale | Cashier, sales, returns, invoices, promotions, loyalty/score |
| **MyWMS 2023** | Warehouse Management | Stock movements, transfers, inventory balances, analytics |

Both are bilingual (TH/EN notes per column), built on **PowerBuilder** frontend, for a **multi-branch Thai retail chain** with two legal entities: **MNI** and **TJ**. WMS integrates with **Odoo ERP** for supplier/cost data.

---

### MyPOS 2018 — Key Tables

**Transactions**

| Table | Purpose |
|-------|---------|
| `bl_header` | Sales bill header — amounts, discounts, payment methods, score/loyalty |
| `bl_detail` | Bill line items — product, qty, price, cost, discount |
| `rt_header` / `rt_detail` | Return/refund documents |
| `bi_header` / `bi_detail` | Tax invoice (ใบกำกับภาษี) — Thai VAT compliance |
| `bill_offline` | Offline POS bills pending reconciliation |
| `bill_payment` | Payment method breakdown per bill |
| `discount_otp` | OTP-validated discount authorizations |
| `price_overline_log` | Audit log for discount overrides |

**Accounting Staging (Buffer)**

`blh_acc`/`bld_acc`, `blh_acc_blank`/`bld_acc_blank`, `rth_acc`/`rtd_acc`, `bih_acc`/`bid_acc` — staging copies of transactions pending accounting confirmation or voided.

**Daily Summary & Shifts**

| Table | Purpose |
|-------|---------|
| `whsdd` | End-of-day totals per warehouse/branch |
| `whsdh` | Month-level summary and close status |
| `whsdd_ccfh` / `whsdd_ccfd` | Shift header + cash drop detail |
| `whsdd_shsry` | Sub-shift summary |
| `whsdd_pettycash` | Petty cash disbursement per shift |
| `exchange_log` / `exchange_point_log` | Cash exchange + loyalty points redemption |

**Customer Master**

| Table | Purpose |
|-------|---------|
| `customer` | Member record — demographics, score balance, address |
| `customer_branch` | Branch-level customer profile |
| `customer_group` / `customer_type` | Segmentation |
| `customer_gender` / `customer_religion` / `customer_occupation` / `customer_age` | Demographics lookups (Thai retail custom) |
| `company` | Store owner company — registration, tax info |

**Item / Product Master**

| Table | Purpose |
|-------|---------|
| `item` | Core product — code, brand, group, unit, cost, **5 price tiers** (ipunit1–5), tax type |
| `item_barcode` | Multiple barcodes per item |
| `unit` | Sub-unit pricing for alternate pack sizes |
| `item_unit` | Unit-of-measure definitions |
| `item_group` / `item_type` / `item_dept` / `item_brand` | Product hierarchy |
| `item_cnsup` | Consignment (ฝากขาย) supplier per item |
| `wholesale` | Quantity-break wholesale pricing |
| `item_set` | Bundle: parent → component items |
| `warehouse` | Branch/warehouse master — price tier, tax, active flag |

**Promotion Engine (7 types)**

| Table | Promotion Type |
|-------|---------------|
| `discount_bill_period` | Time-of-day / date-range bill discount |
| `item_discount` / `item_line_discount` | Step-quantity discount per item/group |
| `item_freebies` / `item_free` / `item_free_branch` | Buy-X-Get-Y freebie |
| `item_buff_header` / `item_buff_detail` / `item_buff_header_step` / `bill_buffet` | Mix & Match bundle |
| `item_premium_rate` / `item_premium` | Spend-threshold premium/gift reward |
| `pro_score` | Day-specific bonus points |
| `coupon` / `coupon_expire` / `customer_coupon` / `customer_coupon_acc` | Coupon wallet |
| `pro_date` / `pro_rate` | Promotion schedule + spend-tier rules |
| `amn` / `item_point` / `item_mem` / `item_exchange` | Rate multipliers, item-level point overrides, member pricing, point top-up |

**Store & System Config**

| Table | Purpose |
|-------|---------|
| `configuration` | Single-row master — print settings, score rules, max discount %, return days, bag ban flag, staff multiplier |
| `running` / `running_online` | Document sequence generators |
| `rt_reason` | Return reason lookup |
| `province` / `amphur` / `tambon` | Thai 3-tier address hierarchy |

**Sync / Integration Queues**

| Table | Purpose |
|-------|---------|
| `mypos2018_link_mywms2023_sale_log` | POS → WMS: push sale bills |
| `mypos2018_link_mywms2023_log` | POS → WMS: push master data |
| `mypos2018_downlink_branch_log` | WMS → POS: pull updated master data |
| `mypos2018_daily_trans_acc_log` | POS → ERP: daily GL entries |
| `mypos2018_dtm_trans_log` | Cross-branch data ownership transfers |
| `item_price_change_history` / `item_price_change_log` | Price change audit |
| `item_cost_change_history` / `item_cost_change_log` | Cost change audit |

**Security**: `xun` (users), `xua` (menu access), `xsm` (modules), `xmn` (forms), `ln_mb` (POS terminal sessions)

**PowerBuilder internal** (ignore for business logic): `pbcatfmt`, `pbcattbl`, `pbcatvld`, `pbcatedt`

---

### MyWMS 2023 — Key Tables

**Warehouse & Location**

| Table | Purpose |
|-------|---------|
| `warehouse` / `warehouse_copy` | Warehouse master (type P=Physical, group B default) |
| `warehouse_size` | Size classification ranges |
| `whsno` | Lightweight warehouse code reference |
| `location` | 3-level: warehouse → location → shelf |
| `location_master` | Template layout per warehouse group |

**Item Master**: same structure as POS — `item`, `item_barcode`, `item_unit`, `item_type`, `item_class`, `item_group`, `item_brand`, `item_promotion`

**Item Cost**: `item_cost` — per-barcode cost for **MNI** and **TJ** entities + pack size, grade, purchase team

**Item Hierarchy**: `itt` (main type, 2-char) → `itg` (sub-group, PK: itt_code + itg_code)

**Inventory Balance & Movement**

| Table | Purpose |
|-------|---------|
| `ibl` / `ibl_id` | Running inventory balance per item+warehouse+location+shelf |
| `iml` / `iml_id` | Individual stock movement events (before/after balances) |

**Transaction Documents**

| Table | Purpose |
|-------|---------|
| `tr_header` / `tr_detail` | Transfer documents — from/to warehouse+location+shelf |
| `tr_reset_whsno` | Warehouse doc number reset log |
| `itd` / `itd_acc` / `itd_log` | Inventory transaction detail + accounting ledger mirror + status log |

**Sales Analytics**

| Table | Purpose |
|-------|---------|
| `itd_sale` | Daily sale summary — qty, returns, revenue, cost, profit, onhand days |
| `itd_sale_log` | Log that a sale was processed for date+item+warehouse |
| `itd_sale_whs` | Cumulative sale summary per item+warehouse |
| `onhand_balance_product` | Current onhand qty+cost per barcode+location + purchase metadata |
| `onhand` | Simplified onhand summary (periodically updated) |

**Org Structure**: `retail_structure` — branch → DM → RM hierarchy

**Odoo Integration**: `product_supplier_from_odoo` — synced barcode, cost, MOQ, supplier name/code/type, pack size from Odoo ERP

**Temp/Batch**: `temp01`, `itd_tempolary_date`, `proc_zero_whs`

**Security + PB internal**: same pattern as POS (`xun`, `xua`, `xmn`, `xsm`, `ln_mb`, `pbcat*`)

---

### Key Business Rules

**Pricing**
- Items have 5 price tiers (`ipunit1`–`ipunit5`); `warehouse.wmpricetype` selects default tier per branch
- Wholesale: quantity-break pricing in `wholesale`
- Member-exclusive: `item_mem`


**Loyalty / Score System**
- Earn: `score_from_baht` (X baht = 1 pt) · Staff multiplier: `emp_get_multi_score`
- Redeem: `perc_baht_score` · Referral bonus: `mem_recommend_score`
- Bill tracking: `score_blf` (before) / `score_rec` (earned) / `score_use` (used) / `score_bal` (balance)
- Thailand bag-ban eco-points: `is_no_bag_status` + `no_bag_point` in `configuration`

**Multi-Entity Costs**: `item_cost` stores separate cost for MNI and TJ

**Status Codes (char(1))**

| Code | Meaning |
|------|---------|
| `N` | New / Not processed |
| `Y` | Processed / Active |
| `C` | Cash (payment) |
| `G` | General (analysis/status) |
| `P` | Physical (warehouse) / Pick (location) |

**Thai Address Hierarchy**: `province` -> `amphur` -> `tambon`

---

### Returns Data Source Verification (2026-06-05)

ยืนยัน: `rtd_acc + rth_acc rtstatus='U' + rtlinetype='R'` ตรงกับ `fact_returns` 100% (477 บิล intersection, June 2026)

| rth_acc | fact_returns | Diff |
|---|---|---|
| `rtnetamt` | `allocated_net_amount` | 0.01 (rounding) |
| `rtamount` | `line_amount_inc_vat` | 0.00 |
| `rtsono` | `rtsono` | exact join key |

- `rth_acc.rtno` = return doc ID (RT0721-...) · `rth_acc.rtsono` = original sale bill (BL0721-...)
- `rtd_acc.rtlinetype` = 100% 'R' · `bld_acc + solinetype='R'` = 0 rows
- Fallback: ถ้า fact_returns พัง -> query rth_acc + rtd_acc โดยตรง

---

### Sales Data Source Verification (2026-06-05)

ยืนยัน: `bld_acc + blh_acc + solinetype NOT IN ('C','R')` ตรง `fact_sales` 99.8% (132,219 บิล intersection)

| Metric | bld_acc | fact_sales | Diff |
|---|---:|---:|---:|
| bills | 134,645 | 132,219 | +2,426 |
| rows (intersection) | 384,632 | 384,632 | 0 |
| amount | 23,369,477 | 23,319,084 | 50,393 (0.2%) |

- `bld_acc.iprod = fact_sales.iprod` · `solineamt` ตรง `net_sales_amt`
- linetype: `N`=ขายปกติ · `C`=Cancel · `R` ไม่อยู่ใน bld_acc (อยู่ที่ rtd_acc)
- 2,426 บิลขาดจาก fact_sales = sotype 1/2 (special transactions)
- Fallback: ถ้า fact_sales พัง -> `bld_acc JOIN blh_acc ON sono + linetype NOT IN ('C','R')`

---

### Table Naming Conventions

| Prefix | System | Meaning |
|--------|--------|---------|
| `bl_*` | POS | Bill (sale) |
| `rt_*` | POS | Return |
| `bi_*` | POS | Tax invoice |
| `*_acc` | POS | Accounting staging buffer |
| `whsdd*` | POS | Daily/shift warehouse summaries |
| `tr_*` | WMS | Transfer |
| `itd*` | WMS | Inventory transaction detail |
| `ibl*` | WMS | Inventory balance log |
| `iml*` | WMS | Inventory movement log |
| `itt`/`itg` | WMS | Item type hierarchy |
| `mypos2018_*` | POS | Integration sync queues |
| `xun`,`xua`,`xsm`,`xmn` | Both | User security & menu |
| `pbcat*` | Both | PowerBuilder metadata (ignore) |

---

## Session 2026-06-05 — Updates (Phase 3b + product fixes + Phase A)

### Phase 3b refactor (PUSHED to main)
- `update_dashboard.py`: **1215 -> 1006 lines** (-209). Imports from `dashboards/helpers.py` + `dashboards/mysql_queries.py` instead of inline duplicates. Old names preserved via `as` aliases - zero call-site changes.
- One signature change wrapped in shim: `_query_fact_sales_may25(cfg)` -> `query_prev_year_same_month(cfg, YEAR, MONTH)`
- **Verification:** `test_phase3b_parity.bat` ran v1-backup vs v2-new with `--no-push` -> `fc /b` reported **"no differences encountered"** on both `sales_dashboard_v8.html` and `index.html`. Zero output drift confirmed.
- **Safety net:** `update_dashboard_v1_backup.py` preserved at root.

### product_dashboard.html (PUSHED commit 73dd90d)
1. **Month label dynamic** - 4 hardcoded "พ.ค." replaced with `_TH_MO_S[currentMonth]` + spans `id=lt-modal-month` / `id=s-sales-label-mo`. Set in `init()` via `new Date()`.
2. **HAVING s26 >= 500 threshold removed** in `build_product_data_mysql.py` line ~295 -> changed to `HAVING s26 > 0`. Small stores now show all SKUs they actually sold (was 46 for store 001, now hundreds).
3. **Column rename** line 286: `เลื่อน/วัน` -> `เฉลี่ย/วัน`

### Phase A — per-store onhand from MyWMS ibl (READY, not yet pushed)
- Added `query_onhand_per_store(conn)` to `build_product_data_mysql.py`:
```sql
SELECT LPAD(ibl_whsno,3,'0') AS whs, ibl_parcode AS iprod,
       SUM(ibl_qty_beg_bal + ibl_qty_rec - ibl_qty_iss) AS onhand
FROM MYWMS2023_CENTER.ibl
WHERE ibl_locno='stock' AND ibl_shelfno='shelfno'
  AND CAST(ibl_whsno AS UNSIGNED) BETWEEN 1 AND 500
GROUP BY whs, ibl_parcode HAVING onhand > 0
```
- **iprod = ibl_parcode direct match** - confirmed 86.6% via `scripts/explore/test_iprod_vs_ibl.py` (no item_barcode bridge needed)
- `build_json()` merges onhand into `store_breakdown[whs][iprod]` as 3rd array element: `[s26, q26, onhand]` (backward compatible)
- `product_dashboard.html` JS destructures `arr[2]||0`, aggregates onhand across scope stores, sets `p.onhand` in override
- Push: clone -> copy `build_product_data_mysql.py` + `product_dashboard.html` + `product_data.json` -> commit "feat: per-store onhand (Phase A)" -> push

### Phase B/C/D — queued for next session
- **Phase B:** Days-until-OOS column (onhand ÷ avg daily run rate) - small JS-only change
- **Phase C:** Dead Stock report (no sale > 90 days + onhand > 0) - new dashboard page
- **Phase D:** Visual Adjustment audit (track `ibl_locno='visual'` adjustments per cashier/store) - fraud signal

### Product dashboard bugfix — ONHAND/IPUNIT3 (2026-06-05 evening)

User reported "ONHAND column = all '—', IPUNIT3 column = numbers" in store-filtered view. Two distinct bugs:

**Bug 1 — HTML cells swapped vs headers** (`product_dashboard.html` lines 720-721)
Header order: col 11 = `Onhand`, col 12 = `ipunit3`. Cell render order was reversed: `${p.ipunit3}` then `${p.onhand}`. Real onhand values from `store_breakdown[whs][iprod][2]` (ibl) were appearing under the "IPUNIT3" header. Verified by sampling store 001 against screenshot: barcode 8851869010226 → `[935,5,10]`, IPUNIT3 column showed 10. **Fix:** swap the two `<td>` lines so cell order matches header order. Sort comparator (cases 11/12) was already correct, no change needed.

**Bug 2 — `ipunit3` sourced from wrong table** (`build_product_data_mysql.py`)
`query_barcodes()` was probing `dim_item_barcode` for an `ipunit3` column that doesn't exist there → all 13,077 products had `ipunit3=0` in JSON. Should pull from `dim_product` (per user). **Fix:**
- Added `_dim_product_columns()` helper (defensive `SHOW COLUMNS`)
- `_query_dim_product()` now includes `ipunit3` in SELECT if column exists (both direct + barcode-bridge paths)
- `query_with_dim()` adds `df['ipunit3']` column from `dim_map`
- `build_json()` reads `row['ipunit3']` instead of `info.get('ipunit3')` (info still owns `onhand` from barcode probe — backward-compat preserved)
- Old `query_barcodes()` ipunit3 probe left in place (returns 0, harmless) — `dim_product` value now wins via `row` lookup

**JSON regen required:** Bug 2 fix only takes effect after `build_product_data_mysql.py` runs against MySQL. Sandbox cannot reach `203.154.83.62:13306` — Windows must run it (manual: `py build_product_data_mysql.py --no-push` then re-push, or wait for next 08:30 BKK cron). Bug 1 (HTML cell swap) takes effect immediately on next browser load — onhand values already in JSON will now appear under correct header.

### Session 2026-06-05 (late evening) — ONHAND/IPUNIT3 follow-through

**Commits pushed:**
- `baba317` — fix(product): swap onhand/ipunit3 cells + source ipunit3 from dim_product
- `b12a7cb` — data: regen product_data.json with ipunit3 from dim_product (13,074/13,077 nonzero)
- `d15d8e4` — fix(product): aggregate onhand across all stores when scope=ALL

**Bug 3 (d15d8e4):** When no RM/DM/store filter is active, the ONHAND column was showing 0 chain-wide because `wProds=prods` falls back to `p.onhand` from `dim_item_barcode` (which has no onhand column → always 0). Real onhand is in `store_breakdown[whs][iprod][2]` (from MyWMS ibl). **Fix:** in `product_dashboard.html` `if(!scopeStores)` branch, precompute `ohTot[iprod]` by summing `arr[2]` across all stores, then `wProds=prods.map(p=>({...p, onhand: ohTot[p.iprod]||0}))`. Store-filtered scope already did this correctly via aggMap.

**Timing trap that wasted 30 min:** User regenerated JSON at 11:23 UTC, but my code edits weren't fully landed on disk until 11:30 UTC. JSON had ipunit3=0 not because code was wrong but because regen ran with partial edits. Probes confirmed code worked. Lesson: **after editing scripts via Cowork Edit tool, wait until all edits land + verify file mtime BEFORE telling user to regen.**

**Edit-tool truncation strike #6 this session:** Editing `product_dashboard.html` (40KB) silently truncated the file from 40KB → 39627 bytes with no `</html>`. No null bytes this time — just plain truncation mid-`.forEach(...)`. Recovery: `cp /tmp/check_pushed/product_dashboard.html F:\co work dashboard\` (restore from GH clone), then re-apply via Python `Path.write_text()` instead of Edit tool. **New rule: for any HTML/JS file edit >20KB, use Python via Bash, not the Edit tool.**

### Phase B/C/D — still queued for next session
(see earlier section)

---

### MyWMS Database Knowledge (added 2026-06-05)

**Schemas available on host:**
`MYPOS2018_CENTER`, `MYPOS2018_CENTER_BACKUP`, `MYPOS_LINK_HR`, `MYPOS_LINK_ODOO`, **`MYWMS2023_CENTER`**, `crm_system`, **`data-lake`**, `data-service`, `pos_analytic`, `qa-system`, `qa-system-test`, `mysql`, `sys`, `test`

**`MYWMS2023_CENTER.ibl`** - 6,752,728 rows (inventory balance log)

Columns: `ibl_id` PK, `ibl_parcode` (=barcode), `ibl_whsno` (store 1-500), `ibl_locno`, `ibl_shelfno`, `ibl_qty_beg_bal`/`rec`/`iss`, `ibl_cst_beg_bal`/`rec`/`iss`, `ibl_qty_sale`, `ibl_cst_sale`, `ibl_date_sale`

Each (parcode, whsno) has **3 rows** by (locno, shelfno):

| locno | shelfno | Meaning | Use for |
|-------|---------|---------|---------|
| `stock` | `shelfno` | Real shelf stock | onhand calc |
| `visual` | `adjustment` | Count discrepancies | fraud audit (Phase D) |
| `partner` | `customer` | Consignment to partner | exclude |

**Onhand formula:** `SUM(ibl_qty_beg_bal + ibl_qty_rec - ibl_qty_iss) WHERE locno='stock' AND shelfno='shelfno'`

**Partner table `iml`** = movement log (