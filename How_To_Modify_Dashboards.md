# 🛠️ How to Modify and Update Dashboards

This guide explains how to modify the dashboard layouts (UI), update database queries (Python ETL scripts), and deploy changes to both GitHub Pages and the VM server.

---

## 🏗️ System Architecture Overview

The system consists of **two parts**:
1. **GitHub Pages (Public URLs)**: Serves static HTML pages using the data stored in JSON files.
2. **VM Server (`http://agent-ab-sandbox.tjinternal.com:48081/`)**: Serves the exact same dashboards and datasets, automatically keeping itself in sync with GitHub commits.

---

## 📝 1. Modifying Dashboard UI/UX (HTML & Javascript)

If you want to edit styling, layout, charts, or labels, modify the relevant HTML template files:

| Dashboard / UI Component | Local File to Modify | Target Repository |
| :--- | :--- | :--- |
| **Dashboard Hub** | `F:\co work dashboard\index.html` | `daily-report` |
| **Sales Dashboard** | `F:\co work dashboard\sales_dashboard_v8.html` | `daily-report` |
| **Fraud Dashboard** | `F:\co work dashboard\fraud_analysis_template.html` <br>*(Do not edit `fraud_dashboard.html` directly; it is compiled from this template)* | `daily-report` |
| **Product Dashboard** | `F:\co work dashboard\product_dashboard.html` | `daily-report` |
| **Lost Product Dashboard** | `F:\co work dashboard\index_for_lost_product.html` | `daily-report` and `lost-Product` |

### Steps to Apply UI Changes:
1. Edit the HTML file in your local workspace editor.
2. Save the file.
3. Run the push script to upload the updated files to GitHub:
   ```powershell
   py "F:\co work dashboard\push_py_to_github.py"
   ```
4. Within **10 minutes**, the VM daemon will detect the new commit on GitHub and automatically download the updated page.

---

## 🐍 2. Modifying Data Calculations & Queries (Python ETL)

If you want to modify how metrics are calculated, add new database columns, or optimize SQL queries, edit the Python scripts:

| Component | local ETL Script | Purpose | Output File |
| :--- | :--- | :--- | :--- |
| **Sales & Hub** | `update_dashboard.py` | Runs MTD sales queries, compiles KPI summary, and injects into `sales_dashboard_v8.html`. | `index.html` <br> `sales_dashboard_v8.html` |
| **Fraud** | `rebuild_fraud_analysis.py` | Queries return records and compiles fraud metrics. | `fraud_data.json` <br> `fraud_dashboard.html` |
| **Product** | `build_product_data_mysql.py` | Queries top products and on-hand balances. | `product_data.json` |
| **Lost Product** | `build_lost_product_data.py` | Queries historical sales tables (2021-2026) to identify lost products. | `lost_product_data.json` |
| **Query Library** | `dashboards/mysql_queries.py` | Stores shared database query functions. | Used by update scripts |
| **Helper Library** | `dashboards/helpers.py` | Stores calculations, filters, and parsing functions. | Used by update scripts |

### Steps to Apply ETL Script Changes:
1. Edit the Python script locally.
2. If you added a new script, ensure it is added to the `FILES_TO_PUSH` list in `push_py_to_github.py`.
3. Push the updated scripts to GitHub:
   ```powershell
   py "F:\co work dashboard\push_py_to_github.py"
   ```
4. Run a manual update to generate new data files (see below), or let the nightly GitHub Actions trigger them automatically.

---

## 🔄 3. Deploying and Triggering Data Updates

Once you have pushed your changes, you can trigger a data rebuild in one of three ways:

### Method A: Manual Update from Your Laptop (Recommended for testing)
Open PowerShell on your Windows laptop and run the manual runner wrapper:
```powershell
& "F:\co work dashboard\run_manual_update.ps1"
```
*This script runs all ETL scripts locally, queries the MySQL database, generates new HTML/JSON files, and pushes them to GitHub. The VM will pull them within 10 minutes.*

### Method B: Manual Trigger on GitHub (Without your laptop)
1. Go to your GitHub repository: [tumsbux/daily-report Actions](https://github.com/tumsbux/daily-report/actions).
2. Click on the **Daily Dashboard Update** workflow in the left sidebar.
3. Click **Run workflow** and select the `main` branch.
4. *GitHub Actions will compile the new data in the cloud and push it to GitHub. The VM will automatically pull it.*

### Method C: Wait for Automatic Daily Updates
1. Every morning between **07:30 AM and 09:30 AM Bangkok time**, GitHub Actions runs a multi-cron scheduler.
2. The workflow compiles Sales, Fraud, and Lost Product data and commits the output directly to GitHub.
3. The VM's background synchronization daemon polls GitHub for new commits every 10 minutes. When it detects the Actions commit, it pulls the updated dashboards and files immediately.

---

## 📊 Column Reference Workbook (สำคัญสำหรับ Power BI)

**File:** `Column_Reference.xlsx` ใน repo root

มี 6 sheets:
1. **Summary** — Metric → Table.Column quick lookup
2. **Discount Structure** — `sodisc` 4-channel rollup (verified 100%)
3. **GP Calculator** — เปลี่ยน input ฟ้า → output คำนวณอัตโนมัติ
4. **Power BI DAX** — measures ready-to-paste
5. **SQL Reference** — query patterns ใช้รันได้ทันที
6. **Changelog** — track verifications

**ใช้เมื่อ:**
- สร้าง measure ใหม่ใน Power BI → ดู sheet "Power BI DAX"
- ต้อง query MySQL ใหม่ → ดู sheet "SQL Reference"
- ลืมว่า GP คิดยังไง → ดู sheet "GP Calculator"
- ตอบคำถาม "ยอดขายใช้ column ไหน" → ดู sheet "Summary"

---

## ⚡ 4. Incremental Refresh (Phase IR) — 🟡 PROPOSED 2026-06-10, awaiting approval

> ห้ามแตะ code จนกว่า user จะอนุมัติ — ดู `Decisions.md` ADR `[2026-06-10]`

### หลักการ
แทนที่จะ query MySQL ใหม่ทุกวันสำหรับ data 6 ปี (Lost Product) หรือ MTD เต็มเดือน (Product/Sales), จะแบ่งเป็น:
- **Frozen zone** — past years + days ก่อน `D-7` → cache บน disk (`cache/*.parquet`, `cache/*.json`)
- **Hot zone** — `D-7` ถึง `D-1` → query สดทุก daily run แล้ว merge เข้า cache

### Daily run flow (หลังเปิด IR)
```
1. Load cache/* → frozen data
2. Query MySQL: WHERE sodate BETWEEN D-7 AND D-1
3. Upsert hot data into cache (overwrite D-7..D-1 slots)
4. Verify schema_hash + rule_hash match
5. Aggregate frozen + hot → output JSON/HTML
6. Push
```

### Flags
- `--full-refresh` — ละ cache, rebuild ทั้งหมด (สำหรับ emergency หรือ rule change)
- ไม่มี flag = incremental default

### Weekly full-refresh cron
ทุกวันอาทิตย์ตี 1 BKK (`0 18 * * 6` UTC) — รัน `--full-refresh` ทุก builder รับมือ late-arriving data > 7 วัน

### Cache file structure
```
F:\co work dashboard\cache\
├─ lost_2021_2024.parquet         (immutable — build once)
├─ lost_2025_final.parquet        (build once after 2026-01-15)
├─ lost_2026_incremental.parquet  (daily upsert)
├─ product_mtd_2026-06.parquet    (reset monthly)
├─ sales_daily_2026-06.json
├─ sales_monthly_tot.json
└─ fraud_closed_2026-05.json
```

**Gitignore:** ทุกไฟล์ใน `cache/` — never commit

### Verify cache health
```powershell
py -c "import json,glob; [print(f, json.load(open(f))['_meta']) for f in glob.glob('cache/*.json')]"
```

### หาก cache เสีย / dashboard ตัวเลขไม่ตรง
```powershell
del F:\co work dashboard\cache\*
& "F:\co work dashboard\run_manual_update.ps1"   # rebuild from scratch
```

---

## 🖥️ 4b. VM Mirror Operations (`agent-ab-sandbox:48081`) — เพิ่ม 2026-06-12

VM (จริงๆ คือ container) serve dashboards ชุดเดียวกับ GitHub Pages + ดึง commit ใหม่เองทุก ~10 นาที — **ไม่มี auto-restart** ถ้า service ตายต้อง start มือ

**เช็คสถานะ** (จาก Windows — scripts อยู่ `F:\lost-Product\`):
```powershell
py "F:\lost-Product\run_vm_command.py" "pgrep -af 'python3 start_services.py'; tail -5 /home/agent-worker/dashboard/services.log"
```
ต้องเห็น `python3 start_services.py` **1 บรรทัดเดียว** (2+ = duplicate, kill PID ตัวใหม่)

**Restart เมื่อตาย:**
```powershell
py "F:\lost-Product\run_vm_command.py" "cd /home/agent-worker/dashboard && nohup python3 start_services.py >> services.log 2>&1 < /dev/null & sleep 3; pgrep -af start_services"
```

**ข้อจำกัด:** container ไม่มี `cron`/`systemd`/`curl`/`ss` — ขอ IT ทำ restart policy (Roadmap) | ⚠️ scripts ฝัง SSH password — ห้าม push ขึ้น repo | หน้าเว็บโชว์ข้อมูลเก่า → เช็คว่า GitHub main fresh ก่อน (ดู Gotchas "push ทับด้วยไฟล์เก่า") แล้วค่อย hard refresh เบราว์เซอร์ (`Ctrl+Shift+R`)

---

## 🤝 5. Multi-Agent Workflow Note

User ทำงาน dashboard ด้วย **2 agents**: Claude (Cowork) + Antigravity (Gemini 3 Flash).

**กฎ:**
- อ่าน `Decisions.md` + `Roadmap.md` ก่อนเริ่มงานใหม่ทุกครั้ง
- ทุก architectural change ต้อง add ADR ก่อน touch code
- Cache file ที่ build ต้องมี `_meta.built_by` (agent identifier)
- งานที่ "Now" ใน Roadmap = source of truth สำหรับ in-flight work — อย่า claim งานซ้ำ
