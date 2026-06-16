# Gotchas

> ปัญหาที่เคยเจอ + วิธีแก้ — โหลดเมื่อ debug

---

### ⚠️ GitHub Contents API ปฏิเสธไฟล์ใหญ่ > ~50MB (พบ 2026-06-14)

**Symptom:** `push_to_github.py` อัปโหลดไฟล์ผ่าน GitHub Contents API → error 422 `"Sorry, the file is too large to be processed."`

**Root cause:** GitHub Contents API รองรับไฟล์ได้ถึง 100MB แต่ base64 payload JSON ใหญ่กว่านั้น — `data.json` 46MB → base64 ~61MB + JSON wrapper เกิน limit จริง

**Fix:** ใช้ `push_data_json.ps1` — git clone → copy file → git commit → git push (ไม่มี limit)

**Rule:** ไฟล์ใหญ่ (>30MB) ห้ามใช้ Contents API — ใช้ git clone เสมอ

**Tags:** `#github` `#push` `#large-file`

---

### ⚠️ MySQL `only_full_group_by`: ORDER BY ต้องใช้ aggregate function (พบ 2026-06-14)

**Symptom:** `ProgrammingError: 1055 (42000): Expression #1 of ORDER BY clause is not in GROUP BY clause...`

**Root cause:** `ORDER BY sodate` ใช้ raw column `f.sodate` แต่ GROUP BY ใช้ `DATE(f.sodate)` — MySQL strict mode ไม่ยอม

**Fix:** เปลี่ยน `ORDER BY sodate, ...` → `ORDER BY DATE(f.sodate), ...` ให้ตรงกับ expression ใน GROUP BY

**Rule:** ทุก column ใน ORDER BY ต้องอยู่ใน GROUP BY หรือเป็น aggregate function

**Tags:** `#mysql` `#sql` `#group-by`

---

### ⚠️ PowerShell `$ErrorActionPreference='Stop'` + git stderr = script ตาย (พบ 2026-06-14)

**Symptom:** `push_data_json.ps1` ตายหลัง `git clone` บรรทัดแรก — git output error `"NativeCommandError"` ทั้งที่ clone สำเร็จ

**Root cause:** git เขียน progress/info ไป stderr เสมอ (รวม "Cloning into..." ปกติ) — PowerShell `$ErrorActionPreference='Stop'` นับ stderr จาก native commands เป็น error → throw exception

**Fix:** redirect stderr ด้วย `2>&1 | Out-Null` ใน git commands ทุกบรรทัด — และลบ `$ErrorActionPreference='Stop'` ออก ใช้ `Test-Path` verify clone สำเร็จแทน

**Tags:** `#powershell` `#git` `#stderr`

---

### ⚠️ Cowork working copy ของ HTML อาจ truncated กลางไฟล์ (พบ 2026-06-14)

**Symptom:** `index.html` ใน `F:\lost-Product\thongfah_dashboard\` ขนาด 15KB แทนที่ควรเป็น 19KB — จบกลางฟังก์ชัน `getViewData` ตัด `</script></body></html>` ออกหมด

**Root cause:** ไม่ชัดเจน — น่าจะเกิดจาก write ถูก interrupt หรือ Cowork sync ผิดพลาด

**Fix:** fetch จาก GitHub raw content แทน (`https://raw.githubusercontent.com/...`) แล้ว overwrite ไฟล์ local

**Detect:** เช็ค `wc -c <file>` หรือ `python3 -c "...h[-50:]"` ว่าลงท้าย `</html>` — ถ้าไม่ = truncated

**Tags:** `#cowork` `#truncation` `#sync`

---

### ⚠️ CSS `tbody td.r` ไม่ cover `tfoot` — grand total ชิดซ้าย (พบ 2026-06-14)

**Symptom:** ตัวเลขใน grand total row (tfoot) ชิดซ้าย ไม่ตรงกับ column ด้านบน ทั้งที่ใส่ `class="r"` แล้ว

**Root cause:** CSS rule `tbody td.r{text-align:right}` ใช้ selector เฉพาะ `<tbody>` — `<tfoot>` ไม่ match

**Fix:** เปลี่ยนเป็น `tbody td.r,tfoot td.r{text-align:right}` หรือใส่ inline `style="text-align:right"` ในทุก tfoot cell

**Tags:** `#css` `#tfoot` `#alignment`

---

### ⚠️ `push_py_to_github.py` ทับ `.github/workflows/daily-update.yml` ด้วย local version เก่า (พบ 2026-06-13)

**Symptom:** หลัง `push_py_to_github.py` รัน (29 ไฟล์) GHA cache steps หายหมด — workflow ไม่มี "Restore cache" + "Push cache to orphan branch"

**Root cause:** `push_py_to_github.py` มี hardcoded list รวม `.github/workflows/daily-update.yml` — ถ้า local file เก่ากว่า GitHub (เช่น Antigravity แก้ GitHub แต่ local ยังเก่า) จะ **push local ทับ GitHub โดยไม่เตือน**

**Fix:** rebuild YAML ที่ถูกต้อง + push ผ่าน GitHub web editor (`e795c00`) เพราะ PAT ขาด `workflow` scope

**กฎ:** ห้ามใช้ `push_py_to_github.py` เด็ดขาด — ใช้ `push_files_api.py <file>` แทนเสมอ (เลือกไฟล์ได้ชัดเจน) — ถ้าต้อง push `.github/workflows/` ต้องใช้ GitHub web editor หรือ PAT ที่มี `workflow` scope

---

### ⚠️ Claude Desktop (Microsoft Store) ไม่อ่าน `%APPDATA%\Claude\claude_desktop_config.json` (พบ 2026-06-12)

**Symptom:** เพิ่ม MCP server ("mysql") ใน `%APPDATA%\Claude\claude_desktop_config.json` → JSON valid, server รัน standalone ได้, restart app จริง (verify ด้วย `Get-Process` StartTime) — แต่ MCP ไม่โผล่ใน Settings → Connectors

**Root cause:** Claude Desktop เครื่องนี้เป็น **Microsoft Store version** (package `Claude_pzs8sxrjxfjjc`) — อ่าน config จาก path virtualized:
`%LOCALAPPDATA%\Packages\Claude_pzs8sxrjxfjjc\LocalCache\Roaming\Claude\claude_desktop_config.json`
ไฟล์ `%APPDATA%\Claude\...` ตามเอกสารทั่วไป **ไม่ถูกอ่านเลย** (powerbi MCP ที่เห็นโหลดอยู่ มาจากไฟล์ฝั่ง LocalCache ที่ app เขียนเอง)

**วิธีรู้ว่าเป็น Store version:** `Get-ChildItem "$env:LOCALAPPDATA\Packages" -Directory -Filter "*Claude*"` — ถ้ามีโฟลเดอร์ = Store version

**Fix:** แก้ไฟล์ฝั่ง `LocalCache\Roaming\Claude\` แทน (backup ก่อน) → Quit จาก system tray → เปิดใหม่ → MCP ใหม่เห็นเฉพาะ**แชทใหม่**

**ชั้นที่ 2 (พบ 2026-06-12 PM4-PM5):** แก้ config ถูกไฟล์แล้วก็ยังไม่โหลด เพราะ **app ไม่ถูก Quit จริง** — กากบาท/ปิดหน้าต่างไม่พอ มี process `claude` ค้างถึง 10 ตัว → config เก่ายังถูกใช้ — ต้อง tray → Quit แล้วยืนยัน `Get-Process *claude*` **ว่างเปล่า** (ถ้าไม่ว่าง `Stop-Process -Name claude -Force`) ก่อนเปิดใหม่ — สังเกต: server ที่ app ไม่เคย spawn จะ**ไม่โผล่ใน Settings → Developer เลย** (ไม่ใช่ขึ้น failed) + ไม่มี log file

**Debug ladder ที่ใช้ได้ผล:** module import → connection ตรงด้วย python → รัน server standalone (stdin error จาก Enter = ปกติ ไม่ใช่ bug) → Settings → Developer ปุ่ม Edit Config เปิดไฟล์ที่ app ใช้จริง → `Get-Process *claude*` พิสูจน์ restart จริง

**Tags:** `#mcp` `#claude-desktop` `#windows-store` `#config`

---

### ⚠️ Field naming trap: JSON `parcode` = barcode จริง, `iprod` = parcode จริงใน DB (พบ 2026-06-12)

**Symptom:** xlsx จาก `build_lost_onhand_xlsx.py` หัวคอลัมน์ `parcode` แต่ข้างในเป็น barcode (เช่น `4446669973`) ส่วนคอลัมน์ `iprod` กลับเป็นรหัสสินค้าหลัก (`011033123`) — สับสนเมื่อเทียบกับ DB

**Root cause:** ชื่อ field ใน `lost_product_data.json` สลับกับ schema DB:
- DB: `parcode` (`ibl_parcode`, ตาราง barcode) = **รหัสสินค้าหลัก**, 1 parcode มีได้หลาย `barcode`
- JSON: `iprod` = parcode จริงใน DB / `parcode` = barcode ตัวหนึ่งของสินค้านั้น

**Fix (✅ 2026-06-12):** เปลี่ยนหัวคอลัมน์ xlsx ใน `build_lost_onhand_xlsx.py` (Detail + ByProduct) เป็น `barcode | parcode` — internal dict keys คงเดิม ไม่กระทบ logic (onhand join ใช้ `ibl_parcode AS iprod` ถูกอยู่แล้ว)

**Avoid:**
- ทุก output ที่ user เห็น (xlsx/report) ให้ label ตาม DB: คอลัมน์ที่มาจาก JSON `parcode` → label `barcode`, จาก `iprod` → label `parcode`
- Join onhand/stock กับ ibl ต้องใช้ JSON `iprod` เสมอ — ห้ามใช้ JSON `parcode` (จะ match ไม่เจอ)

**Tags:** `#schema` `#naming` `#lost-product` `#xlsx`

---

### ⚠️ Exception message ว่าง = อย่าเชื่อ `{e}` — ใช้ `{type(e).__name__}: {e!r}` + traceback (พบ 2026-06-11)

**Symptom:** `WARNING: onhand query failed: ` — ข้อความหลัง colon ว่างเปล่า → debug ไม่ได้

**Root cause:** exception บางตัว `str()` แล้วได้สตริงว่าง — ตัวคลาสสิกคือ **`MemoryError`** (`str(MemoryError()) == ''`) ซึ่งตรงกับเคส onhand=0: `query_onhand_per_store` ใช้ `cur.fetchall()` + `dictionary=True` โหลด ibl ทั้งตาราง (ล้าน rows × dict overhead) เข้า RAM ทีเดียว

**Fix (2026-06-11, `build_product_data_mysql.py`):**
1. Log: `print(f'... {type(_e).__name__}: {_e!r}')` + `traceback.print_exc()` — error จะไม่มีวันว่างอีก
2. Memory: stream tuple cursor (`for whs, iprod, onhand in cur:`) แทน fetchall dict rows + ตัด `MAX(ibl_date_sale)` ที่ SELECT มาแต่ไม่ใช้

**Rule of thumb:** ทุก `except ... print` ใน ETL scripts ให้พิมพ์ `type + repr + traceback` เสมอ — `{e}` เฉยๆ ไม่พอ

---

### ⚠️ Edit-tool truncation on long-line HTML (พบ 2026-06-04)

**Symptom:**
Claude `Edit` tool บนไฟล์ที่มีบรรทัดยาวมาก (เช่น `sales_dashboard_v8.html` ที่ embed D เป็น minified JSON บรรทัดเดียว ~243KB) อาจ **ตัดท้ายไฟล์เงียบๆ** หลัง replace สำเร็จ — ไม่มี error report

**Case:** แก้ `const MTH` บรรทัด 221 สำเร็จ แต่ท้ายไฟล์หาย `updateTopDate(); goHome(); ...</html>` → dashboard render แค่ header (D โหลดได้) body ว่าง (`goHome()` ไม่ถูกเรียก)

**Prevention:** หลัง `Edit`/`Write` ไฟล์ HTML ขนาด > 200KB **ต้องเช็ค** `tail -c 200 <file>` ว่าลงท้าย `</html>` ทุกครั้ง

**Recovery:**
```bash
python3 -c "open('f','a').write('();\ngoHome();\n...</html>\n')"  # ต่อท้าย
# หรือ
git show <prev>:<file> | tail -c 500   # เทียบหาส่วนที่หาย
```

**Strike count this codebase:** ≥7 — Edit tool ทำพังหลายไฟล์รวมถึง `product_dashboard.html` (40KB → 39627 bytes), `build_lost_product_data.py` (mid-`main()`)

**New rule:** สำหรับ HTML/JS file edit > 20KB → ใช้ Python via Bash (`Path.write_text()`) **ไม่ใช่** Edit tool

**Tags:** `#edit-tool` `#truncation`

---

### ⚠️ Edit-tool null-byte padding (2026-06-05)

**Symptom:**
ไฟล์ Python ใหญ่ๆ หลัง Edit จะมี ~7.8KB trailing `\x00` bytes (size preserved, content correct)

**Fix:**
```bash
python3 -c "d=open('f','rb').read().rstrip(b'\\x00'); open('f','wb').write(d)"
```

**Verify:**
```bash
python3 -c "print(b'\\x00' in open('f','rb').read())"  # ต้อง print False
```

**Note:** `py_compile` catches this เมื่อ nulls land mid-source แต่ **ไม่catch** ถ้า nulls appended after last newline

**Tags:** `#edit-tool` `#python` `#nullbyte`

---

### File truncation (HTML files)

**Symptom:**
Dashboard blank หรือ JS ไม่ทำงาน หลัง write crash กลางทาง

**Sizes (reference):**
- `sales_dashboard_v8.html` ≈ 290KB+
- `index.html` ≈ 19KB+
- `product_dashboard.html` ≈ 31KB+

**Recovery:** `git show <commit>:<file> > <file>` then re-inject data

**Prevention:** ตรวจ `tail -5 <file>` ให้ลงท้ายด้วย `</html>`

**Tags:** `#html` `#truncation`

---

### fraud_dashboard.html truncated

**Symptom:** Dashboard ไม่โหลด

**Fix:** `update_dashboard.py` auto-detect และ regenerate จาก `fraud_analysis_template.html` อัตโนมัติ (ตั้งแต่ 2026-06-02)

**Tags:** `#fraud` `#html`

---

### fraud_data.json truncated

**Symptom:** `Unterminated string` ตอน parse / tail ไม่ปิด `}`

**Fix:** ต้อง regenerate จาก MySQL ด้วย `rebuild_fraud_analysis.py` (`inject_fraud_only.py` แก้ไม่ได้เพราะอ่าน json เดิม)

**วิธีฟื้นเร็วสุด:** รัน `run_manual_update.ps1` บน Windows (sandbox เข้า MySQL ไม่ได้)

**Verify JSON ดี:** `tail -c 50 fraud_data.json` ต้องลงท้าย `}]}` ไม่ใช่ขาดกลาง

**Tags:** `#fraud` `#json`

---

### Chart.js SRI hash breaks silently

**Symptom:** Chart ไม่ render เงียบๆ

**Cause:** ใส่ `integrity=` attribute ใน Chart.js CDN tag

**Fix:** อย่าใส่ `integrity` attribute

**Tags:** `#chartjs` `#frontend`

---

### Store code padding inconsistency

**Symptom:** Store lookup miss

**Cause:** MySQL อาจ return `'1'`, `'001'`, หรือ `1` (int)

**Fix:** Scripts เก็บทั้ง raw และ padded keys

**Tags:** `#mysql` `#data`

---

### whsddpact lag 1–2 วัน

**Symptom:** Latest day ยังไม่ finalize

**Fix:** ใช้ `--day N` ถ้าจำเป็น หรือ auto-detect จาก fact_sales

**Check last finalized day:**
```sql
SELECT MAX(whsdddd) FROM MYPOS2018_CENTER.whsdd
WHERE whsddyyyy=2026 AND whsddmm=6 AND whsddpact > 0
```

**Tags:** `#mysql` `#data-lag`

---

### analytics.js หาย จาก push_files

**Symptom:** GA4 tracking หาย หลัง daily run

**Fix:** ตรวจสอบว่า `analytics.js` อยู่ใน `push_files` ใน `update_dashboard.py`

**Tags:** `#analytics` `#push`

---

### renderSoProduct arrow bug (2026-06-04)

**Symptom:**
View "ดูตามสินค้า" ใน Return Bill expand/collapse ตัดอักษร 2 ตัวแรกของ parcode ทิ้ง (เช่น `5729500000291` → `▶ 29500000291`)

**Root cause:**
`renderSoProduct` render `▶ ` ที่ cells[3] (ชื่อสินค้า) แต่ `prodRowClick` ไป modify cells[1] (PARENT CODE) ด้วย `substring(2)` ตอน expand/collapse

**Fix:**
ลบ ▶ ออกทั้งใน initial render + handler ลบ substring corruption — row click expand/collapse เฉยๆ ไม่มี indicator

**Tags:** `#fraud-dashboard` `#javascript`

---

### sono format trap — BL{4-digit}-YYMMDD ไม่ใช่ 3-digit store

**Symptom:**
Only 79 of 203 stores appear in `store_breakdown` of lost_product_data.json. Store-filter returns 0 products

**Root cause:**
- sono format: `BL0011-250101-0001` — 4 digits before dash
- เป็น POS terminal ID, **ไม่ใช่** store code
- `dim_branch.code` uses 3-digit padded `'001'`-`'500'` — mismatch

**Fix:**
JOIN `bld_acc_*_lake` ↔ `blh_acc_*_lake` on `sono`. ใช้ `blh.sotowhs` (3-digit, matches `dim_branch.code` directly) + `blh.sodate` DATETIME

**Trap variants:**
- `SUBSTRING(sono,3,4)` → `'0011'` (POS ID, ผิด)
- `SUBSTRING(sono,3,3)` → `'001'` (works only stores 1-9, off by 10x for 10-500)
- `SUBSTRING(sono,7,2)` → `'-2'` (hits the dash)

**Lesson:** **ห้าม extract store จาก sono ด้วย SUBSTRING. JOIN to header เสมอ**

**Tags:** `#sono` `#sql` `#data-lake`

---

### PowerShell + git stderr — wrap with cmd /c

**Symptom:**
PS 5.1 strict mode + git stderr ("Cloning into ...") triggers false failures

**Fix:**
Wrap every git call via `cmd /c "git ... 2>&1"` so PowerShell `$ErrorActionPreference` doesn't choke on git's normal stderr

**Lesson:** PowerShell ดู git stderr เป็น error เสมอ. ต้อง redirect or wrap

**Tags:** `#powershell` `#git`

---

### PowerShell 5.1 here-string indentation

**Symptom:**
`@"..."@` ใน PS 5.1 throws parse error ถ้า indent

**Fix:** `@"` และ `"@` ต้องอยู่ column 0 (ไม่มี indent)

**Tags:** `#powershell`

---

### pandas only supports SQLAlchemy connectable warning

**Symptom:**
```
UserWarning: pandas only supports SQLAlchemy connectable (engine/connection)
or database string URI or sqlite3 DBAPI2 connection.
```

**Cause:**
ส่ง raw `mysql.connector` connection เข้า `pd.read_sql(sql, conn)` — pandas อยากได้ SQLAlchemy engine

**Fix:**
```python
from sqlalchemy import create_engine
engine = create_engine(f"mysql+mysqlconnector://{user}:{pw}@{host}/{db}")
df = pd.read_sql(sql, engine)
```

**Tags:** `#pandas` `#mysql`

---

### GitHub repo rename ≠ Pages auto-rebuild

**Symptom:**
หลัง rename repo (เช่น `lost-Product-` → `lost-Product`), Pages อาจ serve old paths

**Fix:** เพิ่ม commit ใหม่ (เช่น README) → force Pages redeploy at new name

**Tags:** `#github-pages` `#repo-rename`

---

### Browser caching aggressive across renamed repos

**Symptom:**
"Unexpected token '<'" after a rename

**Suspect:** Browser cache ก่อน suspect code

**Tags:** `#caching` `#github-pages`

---

### GitHub Pages 100 MB hard limit per file

**Symptom:**
Push fails silently or rejects file > 100MB

**Scope:** Applies to EVERY repo (not specific ones)

**Mitigation:** Separating into a data repo helps with history bloat but doesn't bypass the cap. Pruning logic is permanent.

**Tags:** `#github-pages` `#size-limit`

---

### Console cmd window ค้างทั้งวัน (cosmetic)

**Symptom:**
cmd window ของ scheduled task เปิดค้าง ปิดเองไม่ได้

**Fix:**
- ใช้ `pythonw.exe` แทน `python.exe` (no console)
- หรือเช็ค "Hidden" ใน Task Scheduler settings
- หรือ wrap ด้วย `start /min` ใน batch file

**Tags:** `#windows` `#scheduled-task`

---

### `fetch_missing_facts.py` not found warning

**Symptom:**
```
python.exe: can't open file 'F:\co work dashboard\fetch_missing_facts.py':
[Errno 2] No such file or directory
WARNING: fetch_missing_facts.py failed - continuing anyway
```

**Cause:** File `fetch_missing_facts.py` ถูกย้ายไป `scripts/explore/fetch_missing_facts.py` (auto-detect current month after 2026-06-05 fix)

**Fix:** อัปเดต wrapper ให้ชี้ที่ `scripts/explore/fetch_missing_facts.py` หรือลบ block ที่เรียก

**Status:** Pipeline log warning + ข้ามไปก็ได้ ไม่ critical

**Tags:** `#pipeline` `#python`

---

### Timing trap — verify file mtime before user regen (2026-06-05)

**Symptom:**
User regenerated JSON at 11:23 UTC, but code edits weren't fully landed on disk until 11:30 UTC → JSON had ipunit3=0 not because code was wrong but because regen ran with partial edits

**Lesson:** **After editing scripts via Cowork Edit tool, wait until all edits land + verify file mtime BEFORE telling user to regen.**

**Tags:** `#workflow` `#cowork`

---

### PowerShell session pitfall — wrong cwd

**Symptom:**
Opening fresh terminal in wrong folder → file lookups silently fail

**Fix:** Always `cd "F:\co work dashboard"` first in any one-liner block

**Tags:** `#powershell` `#workflow`

---

### ⚠️ Late-arriving data + incremental cache (ANTICIPATED — Phase IR proposed 2026-06-10)

**Symptom (anticipated):**
หลังเปิดใช้ incremental refresh, ถ้า POS แก้ bill ย้อนหลังเกิน 7 วัน (เช่น void bill เก่า, แก้ amount), cache จะมี stale value → dashboard แสดงตัวเลขไม่ตรง MySQL

**Root cause:**
- `bld_acc`/`fact_sales` ไม่ใช่ append-only — POS แก้ย้อนหลังได้
- Incremental query เฉพาะ `D-7..D-1` → correction > 7 วัน ตกหล่น

**Mitigation (ที่ออกแบบไว้):**
1. **7-day safety window** — re-query `D-7..D-1` ทุก daily run + upsert เข้า cache (overwrite cached values)
2. **Weekly full-refresh** — อาทิตย์ตี 1 BKK รัน `--full-refresh` ทุก builder → rebuild cache ตั้งแต่ต้น
3. **Manual `--full-refresh` flag** — emergency rebuild
4. **Schema/rule hash header** — เปลี่ยน MIN_QTY, MIN_AMT ฯลฯ → auto invalidate cache

**Verify cache ดี:**
```bash
python3 -c "import json; m=json.load(open('cache/lost_2026_incremental.parquet'))['_meta']; print(m)"
# ต้องเห็น schema_hash + max_date + built_at recent
```

**Recovery ถ้า cache เสีย:**
```bash
del cache\*  # หรือ rm -f cache/*
py build_lost_product_data.py --full-refresh  # rebuild
```

**Tags:** `#incremental-refresh` `#cache` `#late-arriving-data` `#phase-ir`

---

### ⚠️ Multi-agent cache contention (ANTICIPATED — 2026-06-10)

**Symptom (anticipated):**
ถ้า Claude กับ Antigravity (Gemini) ทำงาน dashboard เดียวกันใน window time ใกล้กัน → คนหนึ่ง schema เปลี่ยน คนนึงอ่าน cache เดิม

**Mitigation:**
- `_meta.built_by` ใน cache header — ดูได้ว่าคนไหน build ล่าสุด
- `schema_hash`/`rule_hash` mismatch = auto full-refresh
- Decisions.md ADR ก่อนทำ schema change เสมอ

**Tags:** `#multi-agent` `#cache` `#phase-ir`

---

### ⚠️ `sodisc` เป็น bill-level ไม่ใช่ line-level (พบ 2026-06-10)

**Symptom:**
อ่าน dbml ว่า `sodisc decimal note: 'TH: ส่วนลดรายการ | EN: Item Disc'` → คิดว่าเป็น line-level discount, ลอง `* soqty` หรือ `solineamt - sodisc` → ทั้งคู่ผิด

**Root cause (verified via `information_schema.COLUMNS`):**
`sodisc` อยู่ใน **header tables เท่านั้น**:
- `MYPOS2018_CENTER.bl_header`
- `MYPOS2018_CENTER.blh_acc`, `blh_acc_2021..2024`, `blh_acc_blank`
- `MYPOS2018_CENTER.so_header`

**ไม่มีใน detail tables** (`bl_detail`, `bld_acc`, `bld_acc_*_lake`, `data-lake.bld_acc_lake`)

แม้ note ใน dbml จะเขียน "ส่วนลดรายการ" แต่ตำแหน่งใน schema บอกชัด: **bill-level (1 ค่าต่อบิล)**

**ใช้งานถูกต้อง:**
```sql
-- ❌ ผิด: bld.solineamt - sodisc  (mix line + bill level)
-- ❌ ผิด: bld.solineamt - sodisc * soqty  (* soqty ไม่ make sense กับ bill-level)
-- ✅ ถูก: allocate proportional
SELECT bld.*, blh.sodisc,
  blh.sodisc * bld.solineamt / SUM(bld.solineamt) OVER (PARTITION BY bld.sono)
    AS line_share_of_disc
FROM `data-lake`.bld_acc_lake bld
JOIN MYPOS2018_CENTER.blh_acc blh ON blh.sono = bld.sono;
```

**Update 2026-06-10 — verified relationship (final):**
`blh_acc` มี 6 discount columns. **`sodisc` = rollup ของ 4 channels** (ไม่ใช่ 5!):
```
sodisc = sodisc_bill + sodisc_coupon + sodisc_perc + sodisc_score
```
- `sodisc_bath` คือ **subset ภายใน `sodisc_bill`** (ส่วน baht-fixed ของ bill discount) — ห้ามรวมใน breakdown!
- ทุกแถวที่ probe `sodisc_bath == sodisc_bill` เลขเดียวกัน
- **Trap:** ก่อนหน้านี้คิดว่า 5 subs (รวม bath) เป็น parallel channels → ผิด, double-count ~29% ของบิล
- **ใช้ `sodisc` ตัวเดียวเพียงพอ** สำหรับ Total Discount

**Power BI DAX (correct):**
```dax
total disc = SUM('blh_acc'[sodisc])    -- ✅ rollup, ใช้ตัวเดียวพอ
```

**หมายเหตุ:**
- `solineamt` ใน `bld_acc_lake` คือ **line total หลังหัก line-level discount แล้ว** (Changelog 2026-06-06)
- ระบบนี้ **ไม่มี per-line discount column** — ส่วนลดทุกตัวเป็น bill-level
- `data-lake.blh_acc_*_lake` (ที่ใช้ใน Lost Product builder) อาจ**ไม่มี** `sodisc` column — ต้องไป join `MYPOS2018_CENTER.blh_acc` แทน → verify ก่อน
- `bld_acc.soafterdisc` คือคอลัมน์ที่อาจเป็น "ยอด line หลังหัก allocated discount" — ยัง TBD (probe ก่อนใช้)

**Lesson:**
- **dbml note ≠ implementation** — schema location คือ truth, doc note อาจ misleading
- เห็น "Item Disc" ใน note + อยู่ header table = น่าจะหมายถึง "discount applied to bill" ไม่ใช่ "per item line"
- Probe `information_schema.COLUMNS` เสมอ ก่อนใช้ column ที่ไม่คุ้น

**Tags:** `#sql` `#mypos` `#dbml-trap` `#discount`

---

### ⚠️ Product dashboard YOY ติดลบ ~-60% ทุกตัว — MTD vs full-month trap (พบ 2026-06-11)

**Symptom:**
Product dashboard (2026-06, generated 2026-06-11) แสดง ยอดขาย มิ.ย.26 = 43.9M เทียบ มิ.ย.25 = 108.7M → **-59.6%** และ YOY ติดลบ -55%..-68% **ทุกประเภทสินค้า** — ดูเหมือนยอดขายพังทั้งระบบ / ดูเหมือน data วัน 1-10 มิ.ย. หาย

**Root cause (2 ชั้น — verified จาก product_data.json จริง):**
1. **Data ครอบคลุมวัน 1–9 ไม่ใช่ 1–10:** `days_elapsed=9` auto-detect จาก `MAX(DAY(sodate))` ใน fact_sales ซึ่ง lag ~1–2 วัน (รันเช้า 11 มิ.ย. → วันที่ 10 ยังไม่ finalize) — **by design ไม่ใช่ bug** (ดู Architecture.md "Data lag")
2. **YOY baseline เป็น full month:** `s25/q25` query `sodate BETWEEN '2025-06-01' AND '2025-06-30'` (30 วันเต็ม) แต่ `s26/q26` มีแค่ 9 วัน → เทียบ 9 วัน vs 30 วัน ติดลบ ~-60-70% โดยอัตโนมัติ ไม่ว่ายอดจริงจะดีแค่ไหน

**Math check:** 43.9M ÷ 9 วัน = **4.88M/วัน** vs 108.7M ÷ 30 วัน = **3.62M/วัน** → per-day จริงๆ คือ **+34.6% YoY** ไม่ใช่ -59.6%

**หมายเหตุ:** full-month baseline มีมาตั้งแต่แรก (`YEAR(sodate)=2025 AND MONTH(sodate)=6`) — sargable optimization 2026-06-11 (`BETWEEN '2025-06-01' AND '2025-06-30'`) แค่คง behavior เดิม ไม่ได้ทำให้แย่ลง

**Fix (✅ applied 2026-06-11, ดู Decisions.md ADR [2026-06-11] + Changelog):**
ใน `build_product_data_mysql.py` — prev-year cache ยังเก็บ full month แต่ filter ตอน aggregate:
```python
# query_product_sales + query_store_sales_may25
df_prev_f = df_prev[df_prev['day'] <= days_elapsed]   # same-period 1–N
```
- `build_json`: เพิ่ม `days_in_month` ใน JSON
- UI (`product_dashboard.html`): nav chip "2026-06 · วัน 1–9/30" + KPI label "มิ.ย.25 (1–9): ..."
- ไม่ต้อง `--full-refresh` — cache structure ไม่เปลี่ยน (filter at aggregation only)

**Avoid:** Dashboard ไหนแสดง YOY ของเดือนที่ยังไม่จบ ต้องเทียบ same-period (1–N vs 1–N) เสมอ — sales dashboard แก้แล้ว 2026-06-04 (YoY same-source sync), product dashboard แก้แล้ว 2026-06-11

**Tags:** `#product-dashboard` `#yoy` `#mtd` `#data-lag`

---

### push_github clone timeout 60s (พบ 2026-06-11)

**Symptom:** `build_product_data_mysql.py` build สำเร็จแต่ตาย `TimeoutExpired` ตอน push — `git clone` full history ของ daily-report (มี JSON ใหญ่ใน history) เกิน 60 วิ

**Fix (✅ 2026-06-11, commit `3e64579`):** `git clone --depth 1` + timeout 300s ใน `push_github()`

**Avoid:** clone repo ที่มี data file ใหญ่ใน history ต้อง `--depth 1` เสมอ

**Tags:** `#git` `#push` `#timeout`

---

### ⚠️ Cowork sandbox mount stale → bash cp ทำไฟล์ปลายทาง truncated (พบ 2026-06-11)

**Symptom:** docs ใน `F:\lost-Product` (Decisions/Roadmap/Changelog) จบกลางประโยค — เนื้อหาท้ายไฟล์หาย (ADR Compact encoding หายทั้งอัน) ทั้งที่ต้นฉบับใน `F:\co work dashboard` ครบ; ฝั่ง `F:\co work dashboard\Gotchas.md` ก็เคยเสีย 3 entries (06-10) จาก sync ทิศกลับ

**Root cause:** Linux sandbox ของ Cowork mount โฟลเดอร์ Windows แบบไม่ realtime — ไฟล์ที่เพิ่ง Edit บน host อาจปรากฏใน mount เป็น snapshot เก่า/ตัดท้าย → `cp` ข้ามโฟลเดอร์ผ่าน bash copy ของ stale ไปทับไฟล์ดีบน host

**Mechanism (ยืนยัน 2026-06-12 PM2, เคส `build_grouped_with_barcodes.py`):**
mount cache **content กับ size metadata แยกกัน** — หลัง Edit ไฟล์บน host, bash เห็น **content ใหม่ แต่ size ค้างเท่าไฟล์เก่า** → อ่านได้แค่ N bytes แรก = ไฟล์ใหม่ถูกตัดกลางบรรทัดพอดีขนาดเก่า (grep เจอ string ใหม่ แต่ `wc -c` = ขนาดเก่า, `py_compile` fail ที่ท้ายไฟล์) — **ค้างนาน 30+ นาที** ไม่ใช่แค่ไม่กี่วินาที, sleep/retry ไม่ช่วย

**Fix (✅ 2026-06-11):** กู้จากฝั่งที่ครบด้วย Read/Write tool (host-side) — ซ่อม Decisions/Roadmap/Changelog (lost-Product) + Gotchas (co work dashboard)

**Avoid:**
- Sync ไฟล์ระหว่างโฟลเดอร์ host ใช้ **Read + Write tool** เท่านั้น — ห้าม `cp`/`cat` ผ่าน bash sandbox
- **ห้าม verify/compile/test ไฟล์ที่เพิ่ง Edit ผ่าน mount path เดิม** — sleep ไม่ช่วย (ค้าง 30+ นาที)
- ✅ Workaround ที่ใช้ได้จริง: **Write tool สร้างไฟล์ใหม่** (ชื่อใหม่) ลง outputs แล้ว test ที่นั่น — ไฟล์สร้างใหม่ propagate ทันที ปัญหาเกิดเฉพาะไฟล์ที่ edit-in-place
- หลัง verify เสร็จ ให้ Write ทับไฟล์จริงบน host ด้วยเนื้อหาที่ verify แล้ว (ได้ไฟล์สะอาด ไม่มี null-byte risk ด้วย)
- หลัง sync ทุกครั้ง verify ปลายทางด้วย Read tool (เช็ค tail + footer `_Last updated_`)

**Tags:** `#cowork` `#sandbox` `#mount` `#sync` `#truncation` `#multi-agent`

---

### ⚠️ Fraud risk score — MTD sales/cost lag 1 วัน (documented 2026-06-12, by design)

**Symptom:**
Risk score ใน fraud dashboard ใช้ MTD sales/cost ที่ "ขาดวันล่าสุด" เทียบกับ returns ที่ query สด — ตัวเลข denominator เก่ากว่า numerator 1 รอบ pipeline

**Root cause:**
Pipeline order: fraud (step 1) อ่าน `cache/sales_daily_{YYYY-MM}.json` ที่เขียนโดย `update_dashboard.py` (step 5) **ของเมื่อวาน** (Phase IR-D อ่าน IR-C cache) — แก้ลำดับตรงๆ ไม่ได้เพราะ**วงกลม**: update_dashboard ต้องใช้ `fraud_data.json` inject เข้า HTML ก่อน

**Decision (user 2026-06-12): ยอมรับ + document — ไม่แก้ code** เหตุผล:
1. `fact_sales` เอง lag 1-2 วัน by design (ดู "whsddpact lag") — cache lag เพิ่มอีก 1 วันบน MTD aggregate มีผลน้อยมาก
2. Sunday `--full-refresh` reconcile ทุกสัปดาห์
3. แก้ลำดับ = เพิ่ม circular dependency risk / duplicate IR-C logic ใน fraud script

**Avoid:** ถ้าอนาคต risk score ต้อง realtime กว่านี้ → ให้ fraud เรียก IR-C patch logic (D-7..D-1) เองก่อน score — อย่า reorder pipeline

**Tags:** `#fraud` `#cache` `#phase-ir` `#data-lag`

---

### ⚠️ push script พ่วงไฟล์ dashboard เก่าทับ build ล่าสุด (พบ 2026-06-12)

**Symptom:** Dashboard Hub บน GitHub main ถอยหลังจากข้อมูลวัน 10 → วัน 9 ทั้งที่ fact_sales มีถึงวัน 11 — VM mirror sync ตัวถอยหลังไปแสดงต่อ

**Root cause:** push เฉพาะกิจ (เช่น `push_v2_schema.py` ตอน deploy compact JSON) มี `index.html`/dashboard HTML อยู่ใน file list → push สำเนาจาก working copy ที่เป็น build เก่า (เช้า 11 มิ.ย. = วัน 9) ขึ้นทับ build ล่าสุดที่ daily run เพิ่ง push

**Fix:** รัน `run_manual_update.ps1` rebuild + push ใหม่ด้วยข้อมูลปัจจุบัน

**Avoid:** push เฉพาะกิจให้จำกัด file list เฉพาะไฟล์ที่แก้จริง — **ห้ามใส่ dashboard HTML ที่ pipeline generate รายวัน** (index.html, sales_dashboard_v8.html, fraud_dashboard.html, product_dashboard.html) เว้นแต่เพิ่ง rebuild สดๆ

**Tags:** `#push` `#stale-data` `#dashboard-hub`

---

### Template for new entry

```markdown
### หัวข้อปัญหาสั้นๆ
**Symptom:** อาการที่เห็น
**Root cause:** สาเหตุจริงๆ
**Fix:** วิธีแก้
**Avoid:** ทำยังไงไม่ให้เกิดอีก
**Tags:** `#area`
```

---

### ⚠️ `rttime` แสดง "0 day" ใน Return Bill tab ของ Fraud Dashboard (พบ 2026-06-14)

**Symptom:** เวลาคอลัมน์ใน Return Bill tab แสดง "0 day" ทุก record แทนที่จะเป็น "HH:MM"

**Root cause:** `pd.Timedelta.days` = **0 เสมอ** สำหรับค่า TIME ภายใน 1 วัน — code เก่า (pre-Phase 3d) ที่ GHA รัน build `fraud_data.json` ใช้ attribute `.days` แทน `.components.hours`:
```python
# BUG (pre-Phase 3d): str(timedelta.days) + ' day'  →  '0 day' ทุก record
pd.Timedelta('18:00:20').days = 0  →  "0 day"

# FIX (Phase 3d _parse_time_row):
pd.Timedelta('18:00:20').components.hours = 18  →  "18:00"
```

**Fix (Phase 3d — ใช้งานแล้วใน local):** `_parse_time_row()` ใน `rebuild_fraud_analysis.py` แก้แล้ว — ต้อง push scripts + rebuild:
```powershell
cd "F:\co work dashboard"
py push_files_api.py rebuild_fraud_analysis.py dashboards/fraud_queries.py dashboards/fraud_agg.py -m "fix(fraud): Phase 3d rttime parse HH:MM"
py rebuild_fraud_analysis.py --no-push
# verify: data['data']['ALL']['so'][0]['time'] ต้องได้ HH:MM format
py push_files_api.py fraud_data.json -m "fix(fraud): correct time HH:MM"
```

**Avoid:** ห้ามใช้ `.days` attribute กับ time-of-day timedelta — ใช้ `.components.hours` หรือ parse string `'0 days HH:MM:SS'` แทน

**Tags:** `#fraud` `#rttime` `#timedelta` `#phase-3d`

---

_Last updated: 2026-06-14_
