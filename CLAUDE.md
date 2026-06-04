# CLAUDE.md — Dashboard System Context

**Project:** Tuensjai Panichkroup Co., Ltd. — Data Dashboard Suite  
**Owner:** data.inwza.008@gmail.com (tumsbux)  
**Working directory:** `F:\co work dashboard\`  
**GitHub Pages:** https://tumsbux.github.io/daily-report/  
**Repo:** github.com/tumsbux/daily-report (branch: `main`)

---

## 🔔 Session Management Rules (user preference)

- **Warn at 85% context usage:** เมื่อรู้สึก conversation ยาวมาก (รวมไฟล์ใหญ่ที่อ่าน + ผลลัพธ์ tool หลายรอบ) ให้แจ้งผู้ใช้ **ทุกครั้ง** ก่อนทำงานต่อ — แนะนำให้ `/compact` หรือเริ่ม session ใหม่
- **Compact every time at 85%:** สรุปสิ่งที่ทำในเซสชันให้กระชับ (commit list + ผลลัพธ์หลัก) ก่อน user สั่ง compact
- **Update CLAUDE.md every time:** ทุกครั้งที่ compact หรือก่อน session จบ ให้ sync CLAUDE.md ด้วยการแก้ไข/fix ใหม่ที่เพิ่งทำ — push ขึ้น repo ด้วย (CLAUDE.md อยู่ใน main แล้ว ตั้งแต่ 2026-06-04)
- หมายเหตุ: Claude ไม่สามารถ monitor context % แบบ realtime ได้ ต้อง self-estimate จากความยาวของ conversation

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
**Schedule (ตั้งแต่ 2026-06-04):** Multi-cron 8 slots ทุก 30 นาที จาก `0 22 * * *` ถึง `30 1 * * *` UTC (= **05:00–08:30 BKK**) — รอบไหน delay น้อยที่สุดยิงใกล้ 08:30 BKK ที่สุด รอบที่เหลือเจอ commit `auto:` ของวันนี้แล้วจะ skip ทันที (steps `if: steps.guard.outputs.skip != 'true'`)  
**เหตุผล:** GH Actions free tier cron delay 0-5 ชม. ขึ้นกับ queue ตั้งหลาย slot ดักให้รอบใดรอบหนึ่งใกล้ 08:30 มากที่สุด  
**Concurrency:** `group: daily-update, cancel-in-progress: false` — ป้องกัน race ถ้า 2 รอบยิงทับกัน  
**Fraud step:** `continue-on-error: true` — sales always updates even if fraud fails.  
**Manual trigger:** github.com/tumsbux/daily-report/actions/workflows/daily-update.yml → Run workflow (bypass guard)

**Secrets** (github.com/tumsbux/daily-report/settings/secrets/actions):
`DB_HOST`, `DB_PORT`, `DB_USER`, `DB_PASSWORD`, `DB_DATABASE`, `GH_PAT`

---

## File Inventory

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

**YoY baseline auto-detect** (แก้ 2026-06-04):
- `_query_fact_sales_may25()` เดิม hardcode `MONTH(sodate) = 5` → bug: ข้ามเดือนแล้ว header card "YYYY (ทั้งเดือน)" ยังโชว์ May 2025 (เพราะ label ถูก regex แทน "พ.ค.→มิ.ย." แต่ value ยังเป็น May)
- แก้: query เป็น `YEAR(sodate) = {YEAR-1} AND MONTH(sodate) = {MONTH}` — auto-detect ตามเดือนปัจจุบัน
- ฟังก์ชันยังชื่อ `_query_fact_sales_may25` และ field `s25_may` (legacy name คงไว้ backward-compat) แต่ทำงานเดือนปัจจุบันแล้ว

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

**MONTH hardcoded** — ยังต้องอัปเดตทุกต้นเดือน:
```python
YEAR26, MONTH = 2026, 6  # ← อัปเดตทุกต้นเดือน (TODO: true auto-detect)
```
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
total_ret_d