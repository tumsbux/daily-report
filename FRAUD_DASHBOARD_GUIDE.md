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
| `fraud_analysis.html` | ~~Legacy (returnall.txt)~~ ไม่ใช้งานแล้ว | — |

---

## 2. fraud_dashboard.html — วิเคราะห์อะไรบ้าง?

Dashboard นี้ประกอบด้วย **8 แท็บ:**

| แท็บ | คำอธิบาย |
|------|---------|
| 📊 Overview | KPI รวม + กราฟ RM / Hour / Day |
| 🏪 Store Risk | อัตราคืนสินค้า % เทียบยอดขาย May |
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

## 4. วิธีอัปเดตข้อมูล

### อัตโนมัติ (ทุกวัน 08:00 น.)
`run_daily_update.bat` รัน `rebuild_fraud_analysis.py --no-push` แล้วรัน `update_dashboard.py`  
จากนั้น `inject_fraud_only.py` inject fraud_data.json → fraud_dashboard.html แล้ว push GitHub

### อัปเดต fraud_dashboard เพียงอย่างเดียว (รวดเร็ว)
ดับเบิ้ลคลิก `run_inject_fraud.bat` — ดึงข้อมูลจาก MySQL, inject ลงใน HTML, push GitHub  
หรือรันด้วย Terminal:
```
py rebuild_fraud_analysis.py --no-push
py inject_fraud_only.py
```

### ข้อมูลดึงจาก MySQL โดยตรง
| ตาราง | หน้าที่ |
|------|---------|
| `fact_returns` | บิลคืนสินค้า (rtstatus='U', 3 เดือนล่าสุด) |
| `dim_users` | rtuname → ชื่อเต็มพนักงาน |
| `dim_branch` | store_code → ชื่อร้าน / DM / RM |

**กรองออก:** `warehouse_code NOT IN ('901', '999')`

---

## 5. อัปเดต UI (เปลี่ยนหน้าตา Dashboard)

ถ้าต้องการเพิ่มคอลัมน์ / เปลี่ยนสี / เพิ่มกราฟ:

1. บอก Claude ว่าต้องการเปลี่ยนอะไรใน `fraud_dashboard.html`
2. Claude จะแก้ไข HTML โดยตรง (ไฟล์นี้เป็นทั้ง template และ data)
3. รัน `py inject_fraud_only.py` เพื่อ inject ข้อมูลล่าสุดและ push

**ข้อควรระวัง:** บล็อก `const D = {...}` จะถูก overwrite ทุกครั้งที่ inject — อย่าแก้ข้อมูลใน D โดยตรง

---

## 6. GitHub Pages

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

---

## 7. โครงสร้าง Flow

```
[ทุกวัน 08:00 น. — run_daily_update.bat]
        │
        ├─ [1] rebuild_fraud_analysis.py --no-push
        │         ├─ เชื่อม MySQL data-lake
        │         ├─ ดึง fact_returns (rtstatus='U', ยกเว้น whs 901/999)
        │         ├─ join dim_users (rtuname → ชื่อเต็ม)
        │         ├─ join dim_branch (store → DM/RM)
        │         ├─ คำนวณ fraud score per cashier
        │         ├─ คำนวณ store risk (return rate)
        │         └─ บันทึก fraud_data.json
        │
        ├─ [2] update_dashboard.py
        │         ├─ อ่าน target.txt + factDD.txt
        │         ├─ อัปเดต sales_dashboard_v8.html + index.html
        │         └─ push ทุกไฟล์ → GitHub Pages
        │
        └─ [3] inject_fraud_only.py (หรือ run_inject_fraud.bat)
                  ├─ อ่าน fraud_data.json
                  ├─ inject → fraud_dashboard.html (แทน const D = {...})
                  └─ push fraud_dashboard.html + fraud_data.json → GitHub
```

---

## 8. รูปแบบข้อมูล (Data Format)

| ฟิลด์ | รูปแบบ | ตัวอย่าง |
|-------|--------|---------|
| วันที่ (return_date) | dd-mm-yyyy | 03-05-2026 |
| เวลา (rttime) | HH:MM | 14:30 |
| คลังที่แสดง | whs ≤ 500 (ยกเว้น 901, 999) | 001–499 |

**หมายเหตุ (ภายใน):** MySQL TIME ถูก pandas serialize เป็น milliseconds (เช่น `53286000` = `14:48`) — JavaScript ใช้ฟังก์ชัน `fmtTime(ms)` แปลงก่อนแสดงผล ไม่ควรแก้ค่าใน fraud_data.json โดยตรง

---

## 9. การแก้ไขที่ผ่านมา (Fixes Log)

| วันที่ | ปัญหา | การแก้ไข |
|--------|-------|---------|
| 27-05-2026 | วันที่ในแท็บ Return Bill แสดงเป็น `yyyy-mm-dd` | แก้ JS ใช้ `dd-mm-yyyy` ทุกจุด |
| 27-05-2026 | เวลาแสดงเป็นตัวเลข ms (เช่น `77942000`) | เพิ่มฟังก์ชัน `fmtTime(ms)` แปลงเป็น `HH:MM` |
| 27-05-2026 | `inject_fraud_only.py` crash เมื่อชื่อสินค้า/ร้านมีวงเล็บ `{}` | เปลี่ยนจาก brace-counting เป็น `json.JSONDecoder.raw_decode()` |
| 27-05-2026 | fraud_dashboard.html เสียหาย (truncated) จาก inject ผิดพลาด | สร้างใหม่จาก git commit `08bfd04` + inject ข้อมูลสด |

---

*อัปเดตล่าสุด: 27 พฤษภาคม 2569 · MySQL live · สร้างโดย Claude (Cowork mode)*
