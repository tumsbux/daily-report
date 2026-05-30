# CLAUDE.md — Dashboard System Context

**Project:** Tuensjai Panichkroup Co., Ltd. — Data Dashboard Suite  
**Owner:** data.inwza.008@gmail.com (tumsbux)  
**Working directory:** `F:\co work dashboard\`  
**GitHub Pages:** https://tumsbux.github.io/daily-report/  
**Repo:** github.com/tumsbux/daily-report (branch: `main`)

---

## ⚡ Quick Context (อ่านก่อนเริ่ม)

ระบบ Dashboard อัปเดตอัตโนมัติทุกวัน 08:30 Bangkok ผ่าน **GitHub Actions** (ไม่ต้องเปิด laptop)
- MySQL อยู่บน cloud ✅
- GitHub Pages อยู่บน cloud ✅
- GitHub Actions รัน script บน cloud ✅

**เมื่อมีปัญหา dashboard ไม่แสดง:** ดู section "Known Issues & Fixes" ด้านล่าง

---

## System Overview

A fully automated daily reporting system. Python scripts query a cloud MySQL data lake, embed results as JSON blobs inside static HTML files, then push those files to GitHub Pages. No server required at runtime.

**Daily pipeline (GitHub Actions — 08:30 Bangkok / 01:30 UTC):**
1. `rebuild_fraud_analysis.py --no-push` → builds fraud_data.json from MySQL
2. `update_dashboard.py` → updates all dashboards → pushes to GitHub Pages

**Manual run (if needed):**
```
py "F:\co work dashboard\rebuild_fraud_analysis.py" --no-push
py "F:\co work dashboard\update_dashboard.py" --day 29
```
(replace 29 with actual finalized day — MySQL whsddpact lags 1–2 days)

---

## GitHub Actions Workflow

**File:** `.github/workflows/daily-update.yml`  
**Schedule:** `cron: '30 1 * * *'` (08:30 Bangkok)  
**Secrets required** (set in github.com/tumsbux/daily-report/settings/secrets/actions):

| Secret | Source |
|--------|--------|
| `DB_HOST` | db_config.json → "host" |
| `DB_PORT` | db_config.json → "port" |
| `DB_USER` | db_config.json → "user" |
| `DB_PASSWORD` | db_config.json → "password" |
| `DB_DATABASE` | db_config.json → "database" |
| `GH_PAT` | db_config.json → "github_token" |

**Fraud step has `continue-on-error: true`** — if fraud rebuild fails, sales dashboard still updates.

**Manual trigger:** github.com/tumsbux/daily-report/actions/workflows/daily-update.yml → Run workflow

---

## File Inventory

| File | Purpose |
|------|---------|
| `update_dashboard.py` | Master daily runner. Queries MySQL, updates all dashboards, pushes to GitHub. |
| `rebuild_fraud_analysis.py` | Fraud ETL. Queries fact_returns, builds fraud_data.json. Run BEFORE update_dashboard.py. |
| `inject_fraud_only.py` | Fast re-inject. Updates fraud_dashboard.html from existing fraud_data.json without re-querying MySQL. |
| `build_product_data.py` | Builds product_data.json from fact_sales JOIN dim_product. |
| `push_py_to_github.py` | One-shot script to push Python scripts and HTML files to GitHub via API. |
| `test_mysql_connection.py` | Diagnostic: verifies MySQL connection and shows fact_returns row counts. |
| `test_rebuild_now.bat` | Runs rebuild_fraud_analysis.py with --no-push, logs to rebuild_test.log. |
| `run_inject_fraud.bat` | Runs inject_fraud_only.py, logs to inject_fraud.log. |
| `sales_dashboard_v8.html` | Main sales dashboard (served internally to team). |
| `index.html` | Dashboard Hub — KPI summary + navigation to all sub-dashboards. |
| `fraud_dashboard.html` | Fraud Detection Dashboard — tabs for Overview, Store Risk, Cashiers, Bills, Time, etc. |
| `fraud_analysis_template.html` | Template/reference version of the fraud dashboard (not the live file). |
| `fraud_data.json` | Serialised fraud analysis data; re-injected into fraud_dashboard.html daily. |
| `product_dashboard.html` | Top products by sales value with YoY; built by build_product_data.py. |
| `product_data.json` | Serialised product data; stamped with today's date on every push. |
| `db_config.json` | **SECRETS — never commit.** Contains MySQL host/user/password and github_token. |
| `target.txt` | Daily store targets from MYPOS2018_CENTER.whsdd (~29MB). Fallback if MySQL down. |
| `data-lake_fact_returns.sql` | Static export of fact_returns (~1MB). Fallback if MySQL down. |
| `DASHBOARD_UPDATE_GUIDE.md` | Thai-language data dictionary and manual update guide. |
| `Dashboard_Blueprint_2026.docx` | Full developer reference document (architecture, bug history, setup checklist). |

---

## Credentials

All secrets live in `db_config.json` (local only, never pushed to GitHub):

```json
{
  "host":         "<MySQL cloud host>",
  "port":         3306,
  "user":         "<db username>",
  "password":     "<db password>",
  "database":     "<schema name>",
  "github_token": "ghp_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
}
```

---

## Data Sources & Key Logic

### Source tables (MySQL cloud data lake)

| Table | Content |
|-------|---------|
| `MYPOS2018_CENTER.whsdd` | Daily store targets (`whsddptar`) and actuals (`whsddpact`). Also fallback: `target.txt`. |
| `fact_returns` | Return bills. Use `allocated_net_amount` (NOT `line_amount_inc_vat`). Filter `rtstatus='U'`. |
| `fact_sales` | Sales lines. Use `net_sales_amt`, `sotowhs` (store code), `sono` (bill no), `solinetype='N'`. |
| `dim_product` | Product dimension for the product dashboard. |

### Store filtering rule
```python
def valid_store(code):
    try:    return int(code) <= 500
    except: return False   # excludes 901, 902, 903, 904, 999, WBT, WHC, WPT etc.
```

### Core formulas
```
Net MTD Sales   = whsddpact − allocated_net_amount (returns)
GP Amount       = net_sales_amt − total_cost
GP%             = GP Amount / net_sales_amt × 100
Daily Rate      = Net MTD / days_elapsed
Projected       = Daily Rate × 31
Projected YoY   = (Projected / May 2025 full month − 1) × 100
Avg Ticket      = Net MTD / txn_mtd
vs Target MTD%  = Net MTD / Σ whsddptar (days 1–N)
Proj vs Target% = Projected / Σ whsddptar (days 1–31)
```

### Data embedded in HTML files
Each HTML file contains a `const D = {...}` JavaScript blob. Scripts use brace-matching to safely replace this block (see `extract_json()` in update_dashboard.py).

---

## update_dashboard.py — Step-by-Step Flow

1. Load targets from MySQL `MYPOS2018_CENTER.whsdd` (fallback: `target.txt`)
2. Load unfinalized days from `factDD.txt` files
3. Load returns from MySQL `fact_returns` (fallback: `data-lake_fact_returns.sql`)
4. Load existing dashboard HTML, extract `const D={}` JSON
5. Update each store — compute net sales, daily rate, projected, GP, txn, ticket avg, YoY
6. Aggregate stores → DM → RM → Summary
7. Save `sales_dashboard_v8.html` + update `<span id="td-days">N</span>`
8. Update `index.html` Hub — KPI values, day badge, RM table, trend chart
9. Sync returnXX.txt → `returnall.txt`
10. Inject fraud_data.json into `fraud_dashboard.html`
11. Push to GitHub (clone temp repo → copy files → commit → push → delete temp)

**Files pushed to GitHub:** `index.html`, `sales_dashboard_v8.html`, `fraud_dashboard.html`, `fraud_analysis.html`, `fraud_data.json`, `product_dashboard.html`, `product_data.json`

---

## Known Issues & Fixes (2026-05-30 session)

### Problem: Dashboard shows blank white page (no content rendered)
**Root cause:** `sales_dashboard_v8.html` was truncated — file cut off mid-JavaScript inside `render()` function. Missing closing braces, `goHome()` init call, `</script></body></html>`.  
**Symptom:** Header/topbar renders (static HTML) but `#app` div is empty.  
**Fix applied:** Appended missing JS tail to restore complete file.  
**Prevention:** If dashboard goes blank again, check file size. Complete file ≈ 290KB+. If smaller, the file is truncated.

### Problem: Charts not rendering (blank chart boxes, no graphs)
**Root cause:** Chart.js `integrity` (SRI) attribute in `<script>` tag had wrong hash — browser blocks the script silently.  
**Fix applied:** Removed `integrity` and `crossorigin` attributes from the Chart.js `<script>` tag in `sales_dashboard_v8.html`.  
**Prevention:** Never add `integrity=` attribute to CDN script tags unless you have verified the exact hash. Use:
```html
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.5.0/dist/chart.umd.js"></script>
```

### Problem: index.html Hub charts blank (monthly trend + RM chart)
**Root cause:** `index.html` was truncated — cut off mid-JavaScript at `font:{size:` inside the Chart.js options block.  
**Symptom:** KPI cards render fine but chart areas are blank.  
**Fix applied:** Appended missing 90 chars of JS tail + `</script></body></html>`.  
**Prevention:** Complete `index.html` ≈ 18,968 bytes. If smaller, it's truncated. Restore from git: `git show ff2f7b5:index.html > index.html`

### Problem: fraud_dashboard.html showing blank charts
**Root cause:** `fraud_dashboard.html` was also truncated (local file corrupted, overwritten to GitHub).  
**Fix applied:** Restored complete template from git history (`ff2f7b5`) and re-injected current `fraud_data.json`.  
**Prevention:** If fraud charts go blank, restore from git history:
```bash
git show ff2f7b5:fraud_dashboard.html > fraud_dashboard.html
py inject_fraud_only.py
```
Or run the full rebuild: `py rebuild_fraud_analysis.py`

### Problem: GitHub Actions workflow failing on fraud step
**Root cause:** Unknown (possibly large query timeout or network issue).  
**Fix applied:** Added `continue-on-error: true` and `timeout-minutes: 15` to fraud rebuild step.  
**Result:** Sales dashboard always updates even if fraud rebuild fails.

### Problem: Day count shows wrong number (30 instead of 29)
**Root cause:** `whsddpact` in MySQL lags 1–2 days. Running with `--day 30` when MySQL only has day 29 data gives wrong projections.  
**Fix:** Always use `--day N` where N = last day with finalized `whsddpact` data. Check via:
```sql
SELECT MAX(whsdddd) FROM MYPOS2018_CENTER.whsdd 
WHERE whsddyyyy=2026 AND whsddmm=5 AND whsddpact > 0
```

---

## Dashboard Views

### index.html — Hub
- Hero KPIs: ยอดขาย MTD, vs เป้า MTD, Projected, YoY Projected, GP%
- 4 KPI cards: Run Rate, Avg Ticket, Bills/store/day, Returns/store
- RM table with progress bars
- Monthly trend chart (m25vals / m26vals)

### sales_dashboard_v8.html — Sales
| View | Content |
|------|---------|
| Home (`home`) | KPI cards, Gauge YoY, Monthly Trend chart |
| RM (`rm`) | RM detail + DM sub-table + chart |
| DM (`dm`) | DM detail + Store table + chart |
| Store (`store`) | Store KPI + Monthly chart |
| Executive (`exec`) | 7-section executive report; `excTarget = total_target × 1.155` (+15.5% corporate challenge) |
| Report (`report`) | RM cards + DM table + charts |

### fraud_dashboard.html — Fraud Detection
Tabs: Overview · Store Risk · พนักงาน (rtuname) · rtsono ซ้ำ · เวลา · ร้าน · DM · RM  
Risk badges: HIGH / MEDIUM / LOW in nav bar.

---

## D.summary JSON Key Fields

```
days_elapsed, days_remaining, total_mtd, total_target, total_mtd_target,
total_pct_target, total_proj, total_proj_vs_tgt, total_s25, total_proj_yoy,
total_gp_mtd, total_gp_pct, total_txn, total_daily_txn, total_ticket_avg,
total_ticket_avg_25, total_ticket_avg_yoy, total_txn_yoy, total_ret_mtd,
total_ret_daily, total_ret_per_store, m26_tot {YYYY-MM: amount}, m25_tot {YYYY-MM: amount}
```

---

## Daily Manual Update Checklist

When running manually (or when auto-scheduler missed a day):

1. Ensure `db_config.json` is present with valid credentials
2. Run: `py "F:\co work dashboard\rebuild_fraud_analysis.py" --no-push`
3. Run: `py "F:\co work dashboard\update_dashboard.py" --day N`
   - N = last day with finalized MySQL data (check whsddpact)
   - Omit `--day` to auto-detect (yesterday's date)
4. Verify printed summary for MTD total, GP%, transactions
5. Dashboard live at https://tumsbux.github.io/daily-report/ within ~1 min

**If only fraud dashboard needs updating:** `run_inject_fraud.bat`

---

## Developer Setup (New Machine)

1. Install Python 3 + `pip install mysql-connector-python pandas openpyxl`
2. Create `F:\co work dashboard\db_config.json` with MySQL credentials + GitHub PAT (repo write scope)
3. Test MySQL: `py test_mysql_connection.py`
4. Full run: `py rebuild_fraud_analysis.py --no-push && py update_dashboard.py`
5. **Never commit `db_config.json`**

---

## Common Pitfalls

- **`<span id="td-days">N</span>`** must be updated every run. If skipped, dashboard shows stale day number.
- **Both files must match:** `sales_dashboard_v8.html` and `index.html` must always contain the same underlying data.
- **Store code padding:** MySQL may return `'1'`, `'001'`, or `1` (int). Scripts store both raw and padded keys.
- **rebuild_fraud_analysis.py must run BEFORE update_dashboard.py** — master runner reads `fraud_data.json` that rebuild produces.
- **`whsddpact` may lag 1–2 days** — use 