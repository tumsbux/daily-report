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
