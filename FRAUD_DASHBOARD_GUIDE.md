# คู่มือ Fraud Detection Dashboard — ฉบับอัปเดต พ.ค. 2569

> **ระบบ:** Tuenjai Retail · 203 สาขา · อัปเดตอัตโนมัติทุกวัน 08:00 น.  
> **แหล่งข้อมูล:** MySQL `data-lake` @ 203.154.83.62:13306 (ดึงตรง — ไม่ต้องใช้ไฟล์ txt)

---

## 1. ไฟล์ Dashboard ทั้งหมด

| ไฟล์ | หน้าที่ | อัปเดตโดย |
|------|---------|-----------|
| `fraud_dashboard.html` | **Fraud Return Analysis หลัก** (8 แท็บ, ข้อมูลฝังใน HTML) | `rebuild_fraud_analysis.py` + `inject_fraud_only.py` |
| `fraud_data.json` | ข้อมูลดิบจาก MySQL (inject เข้า fraud_dashboard.html) | `rebuild_fraud_analysis.py` |
| `rebuild_fraud_analysis.py` | ดึง MySQL → คำนวณ → บันทึก fraud_data.json | — |
| `inject_fraud_only.py` | อ่าน fraud_data.json → inject → push GitHub | — |
| `run_inject_fraud.bat` | รัน inject_fraud_only.py (ดับเบิ้ลคลิกได้) | — |
| `update_dashboard.py` | อัปเดต sales_dashboard + index.html → push GitHub | `run_daily_update.bat` |
| `fetch_missing_facts.py` | ดึง factXX.txt ที่ขาดหายจาก MySQL | `run_daily_update.bat` |
| `fraud_analysis.html` | ~~Legacy (returnall.txt)~~ ไม่ใช้งานแล้ว | — |

---

## 2. fraud_dashboard.html — วิเคราะห์อะไรบ้าง?

Dashboard นี้ประกอบด้วย **8 แท็บ:**

| แท็บ | คำอธิบาย |
|------|---------|
| 📊 Overview | KPI รวม + กราฟ RM / Hour / Day |
| 🏪 Store Risk | อัตราคืนสินค้า % เทียบยอดขาย May + **GP DEV** |
| 👤 พนักงาน | rtuname + ชื่อเต็ม + Fraud Score + Repeat SO |
| 🧾 rtsono ซ้ำ | บิลที่มีการคืนมากกว่า 1 รายการ |
| 🕐 เวลา | วิเคราะห์เวลาคืน (ดึก/เช้า/บ่าย/เย็น) |
| 🗂️ ร้าน | ยอดคืนรวมต่อสาขา |
| 👔 DM | สรุประดับ DM + กราฟ |
| 🏢 RM | สรุประดับ RM + กราฟ |

**Filter ได้:** เดือน (มี.ค./เม.ย./พ.ค.) + RM + DM + ค้นหาข้อความ  
**Sort ได้:** กดหัวคอลัมน์ทุกคอลัมน์

### รูปแบบข้อมูลที่แสดง
- **วันที่:** dd-mm-yyyy (เช่น 03-05-2026)
- **เวลา:** HH:MM (เช่น 14:30)
- **คลังที่กรองออก:** whs 901 และ 999 (ไม่นำมาแสดง)

---

## 3. Fraud Score (พนักงาน)

```
Fraud Score = (Amount/MaxAmount × 40)
            + (ZeroCust%/100 × 35)
            + (RepeatSO/MaxRepeat × 25)

🔴 HIGH   ≥ 60   ตรวจสอบทันที
🟡 MEDIUM 35–59  ติดตามอย่างใกล้ชิด
🟢 LOW    < 35   อยู่ในเกณฑ์ปกติ
```

**สัญญาณ 3 ตัว:**
- **cust=0000** — คืนสินค้าโดยไม่ระบุเบอร์ลูกค้า (สูงผิดปกติ = น่าสงสัย)
- **Repeat SO** — บิลเดิมถูกคืนซ้ำหลายรายการ
- **Amount** — ยอดคืนรวม

---

## 4. GP DEV (แท็บ Store Risk)

```
GP DEV = GP% ของสาขา − GP% เฉลี่ยทั้งเชน

ค่าลบ (เช่น −3.50) = สาขามี GP% ต่ำกว่าเฉลี่ย → น่าสงสัย
ค่าบวก (เช่น +2.10) = สาขามี GP% สูงกว่าเฉลี่ย → ปกติ
```

**แหล่งข้อมูล GP DEV:**
- Primary: `data-lake.fact_sales` (net_sales_amt, total_cost)
- Fallback 1: `MYPOS2018_CENTER.whsdd` (whsddpnetamt, whsddpnetcost)
- Fallback 2: `target.txt` (offline เท่านั้น)

**ถ้า GP DEV = 0.00 ทุกสาขา** → รัน `py rebuild_fraud_analysis.py --no-push` แล้ว `py inject_fraud_only.py` เพื่อรีเฟรชข้อมูล

---

## 5. แหล่งข้อมูล Sales Dashboard (update_dashboard.py)

| ลำดับ | แหล่งข้อมูล | ใช้สำหรับ |
|-------|------------|----------|
| Primary | `MYPOS2018_CENTER.whsdd` | เป้า (whsddptar) + ยอดขายจริงรายวัน (whsddpnetamt) |
| Fallback | `target.txt` | ใช้ถ้า MySQL ไม่ได้ → ข้อมูลอาจล้าช้า |
| Supplement | `factXX.txt` | วันที่ยังไม่ Finalize ใน whsdd |

**หมายเหตุ:** `whsddpact` อาจอัปเดตช้า 1–2 วัน ระบบจะใช้ `whsddpnetamt` แทนโดยอัตโนมัติ เพื่อให้วันที่ Dashboard ถูกต้อง (today − 1)

---

## 6. วิธีอัปเดตข้อมูล

### อัตโนมัติ (ทุกวัน 08:00 น.)
`run_daily_update.bat` รันตามลำดับ:
1. `fetch_missing_facts.py` — ดึง factXX.txt ที่ขาดหายจาก MySQL
2. `rebuild_fraud_analysis.py --no-push` — คำนวณ GP DEV + fraud score → บันทึก fraud_data.json
3. `update_dashboard.py` — ดึงเป้าจาก `MYPOS2018_CENTER.whsdd` → อัปเดต sales dashboard → push GitHub
4. `inject_fraud_only.py` — inject fraud_data.json → fraud_dashboard.html → push GitHub

### อัปเดต fraud_dashboard เพียงอย่างเดียว (รวดเร็ว)
ดับเบิ้ลคลิก `run_inject_fraud.bat` หรือรันด้วย Terminal:
```
cd "F:\co work dashboard"
py rebuild_fraud_analysis.py --no-push
py inject_fraud_only.py
```

### ข้อมูลดึงจาก MySQL โดยตรง
| ตาราง | หน้าที่ |
|------|---------|
| `data-lake.fact_returns` | บิลคืนสินค้า (rtstatus='U', 3 เดือนล่าสุด) |
| `data-lake.fact_sales` | ยอดขาย MTD + ต้นทุน (GP DEV) |
| `data-lake.dim_branch` | store_code → ชื่อร้าน / DM / RM |
| `MYPOS2018_CENTER.whsdd` | เป้ารายวัน (whsddptar) + ยอดขายจริง (whsddpnetamt) |

**กรองออก:** `warehouse_code NOT IN ('901', '999')`

---

## 7. อัปเดต UI (เปลี่ยนหน้าตา Dashboard)

ถ้าต้องการเพิ่มคอลัมน์ / เปลี่ยนสี / เพิ่มกราฟ:

1. บอก Claude ว่าต้องการเปลี่ยนอะไรใน `fraud_dashboard.html`
2. Claude จะแก้ไข HTML โดยตรง (ไฟล์นี้เป็นทั้ง template และ data)
3. รัน `py inject_fraud_only.py` เพื่อ inject ข้อมูลล่าสุดและ push

**ข้อควรระวัง:** บล็อก `const D = {...}` จะถูก overwrite ทุกครั้งที่ inject — อย่าแก้ข้อมูลใน D โดยตรง

---

## 8. GitHub Pages

| URL | ไฟล์ |
|-----|------|
| `https://tumsbux.github.io/daily-report/fraud_dashboard.html` | **Fraud Dashboard หลัก** |
| `https://tumsbux.github.io/daily-report/` | Hub (index.html) |

ไฟล์ที่ push ทุกวัน:
- `index.html`
- `sales_dashboard_v8.html`
- `fraud_dashboard.html` ← Fraud Return Analysis
- `fraud_data.json` ← ข้อมูลดิบ
- `product_dashboard.html`
- `product_data.json`

**หมายเหตุ:** `update_dashboard.py` และ `db_config.json` ไม่ถูก push ขึ้น GitHub (มีข้อมูล credentials)

---

## 9. โครงสร้าง Flow

```
[ทุกวัน 08:00 น. — run_daily_update.bat]
        │
        ├─ [1] fetch_missing_facts.py
        │         └─ ดึง fact_sales จาก MySQL → เขียน factXX.txt ที่ขาดหาย
        │
        ├─ [2] rebuild_fraud_analysis.py --no-push
        │         ├─ เชื่อม MySQL data-lake
        │         ├─ ดึง fact_returns (rtstatus='U', ยกเว้น whs 901/999)
        │         ├─ join dim_branch (store → DM/RM)
        │         ├─ คำนว�