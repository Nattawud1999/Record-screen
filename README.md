# 🖥️ ScreenMonitor

ระบบ Monitor หน้าจอคอมพิวเตอร์แบบ Real-time สำหรับองค์กร
ดู Live View, ดูย้อนหลัง, และจัดการเครื่องลูกข่ายทั้งหมดจาก Dashboard เดียว

---

## 📋 Features

- **Live View** — ดูหน้าจอ Real-time ของทุกเครื่องพร้อมกัน
- **บันทึกย้อนหลัง** — Slideshow ดูภาพย้อนหลัง กรอง วันที่ / เวลา
- **Multi-monitor** — รองรับหลายจอ (ซูมเข้าดูแต่ละจอได้)
- **Zoom & Pan** — ซูมและลากภาพได้ทั้งใน Live View และ Slideshow
- **รายชื่อคอมพิวเตอร์** — ดู online/offline, ส่ง uninstall command จากระยะไกล
- **Auto-delete** — ตั้งค่าลบภาพเก่าอัตโนมัติ
- **3 ภาษา** — ไทย / English / 中文
- **Dark Theme** — UI โทนสีม่วง/indigo สวยงาม

---

## 🏗️ Architecture

```
┌─────────────────────────────────────┐
│           Dashboard (Browser)        │
│        http://SERVER_IP:5000         │
└─────────────────┬───────────────────┘
                  │
┌─────────────────▼───────────────────┐
│         Server (app.exe)             │
│   Flask API + Embedded Web UI        │
│   - รับภาพจาก Client               │
│   - เก็บไฟล์ลง Storage             │
│   - Heartbeat / Config API          │
└─────────────────┬───────────────────┘
                  │  HTTP
     ┌────────────┴────────────┐
     │                         │
┌────▼─────┐             ┌─────▼────┐
│ Client A  │             │ Client B  │
│recorder   │    ...      │recorder   │
│launcher   │             │launcher   │
└──────────┘             └──────────┘
```

**Server** รัน `app.exe` บนเครื่อง Server
**Client** ติดตั้ง `recorder.exe` + `launcher.exe` บนทุกเครื่อง Client ผ่าน `setup.bat`

---

## 📁 Project Structure

```
ScreenMonitor/
├── server/                  # ฝั่ง Server
│   ├── app.py               # Flask backend
│   ├── app.spec             # PyInstaller spec
│   ├── config.example.json  # ตัวอย่าง config
│   └── static/
│       └── index.html       # Dashboard UI (Single-page app)
│
├── client/                  # ฝั่ง Client
│   ├── recorder.py          # จับภาพหน้าจอ + upload
│   ├── recorder.spec        # PyInstaller spec
│   ├── launcher.py          # Launch recorder เข้าทุก user session (SYSTEM)
│   ├── launcher.spec        # PyInstaller spec
│   ├── config.example.json  # ตัวอย่าง config (ระบุ IP Server)
│   ├── setup.bat            # Script ติดตั้ง (Run as Admin)
│   ├── uninstall.bat        # Script ถอนการติดตั้ง
│   └── launcher_task.xml    # Windows Task Scheduler XML
│
└── README.md
```

---

## 🚀 Getting Started

### Requirements

- Python 3.10+
- Windows 10/11 (Server และ Client)

### Server — Dependencies

```bash
pip install flask flask-cors werkzeug
```

### Client — Dependencies

```bash
pip install requests opencv-python numpy mss
```

---

## ⚙️ Server Setup

### 1. Config

คัดลอก `server/config.example.json` → `server/config.json` และแก้ไข:

```json
{
    "storage_path": "D:\\ScreenData",
    "auto_delete_enabled": false,
    "auto_delete_days": 30,
    "client_config": {
        "recording_active": true,
        "screenshot_interval_seconds": 5,
        "quality": 80
    }
}
```

| Key | คำอธิบาย |
|-----|---------|
| `storage_path` | Path เก็บรูปภาพ เช่น `D:\\ScreenData` |
| `screenshot_interval_seconds` | ความถี่การจับภาพ (วินาที) |
| `quality` | คุณภาพ JPEG (1-100) |
| `auto_delete_days` | ลบภาพเก่ากว่ากี่วัน |

### 2. Run (Python)

```bash
cd server
python app.py
```

เปิด browser → `http://localhost:5000`

### 3. Build EXE (สำหรับ deploy)

```bash
cd server
pip install pyinstaller
python -m PyInstaller app.spec --noconfirm
# ได้ไฟล์ที่ dist/app.exe
```

วาง `app.exe` + `config.json` ไว้ใน folder เดียวกัน แล้วรัน

---

## 💻 Client Setup

### 1. Config

คัดลอก `client/config.example.json` → `client/config.json` และแก้ IP Server:

```json
{
    "backend_url": "http://192.168.1.100:5000"
}
```

### 2. Build EXE

```bash
cd client

# Build recorder
python -m PyInstaller recorder.spec --noconfirm

# Build launcher
python -m PyInstaller launcher.spec --noconfirm
```

### 3. ติดตั้งบนเครื่อง Client

วาง folder `client/` ไว้บนเครื่อง Client แล้ว:

```
คลิกขวา setup.bat → Run as administrator
```

สคริปจะ:
1. คัดลอกไฟล์ไปที่ `C:\ProgramData\ScreenMonitor\`
2. สร้าง Windows Scheduled Task (รันทุก 1 นาทีในฐานะ SYSTEM)
3. Launch recorder เข้าทุก user session อัตโนมัติ

### 4. ถอนการติดตั้ง

```
คลิกขวา uninstall.bat → Run as administrator
```

---

## 🔒 How It Works

### recorder.exe
- รันซ่อนใน background ของ user session
- จับภาพทุก N วินาที (ตาม config จาก Server)
- ตรวจจับ black screen (ล็อกหน้าจอ) → ไม่บันทึก
- ส่ง heartbeat ทุก cycle → Server รู้ว่า online/offline
- รับ command `uninstall` จาก Server ได้

### launcher.exe
- รันเป็น SYSTEM ผ่าน Task Scheduler ทุก 1 นาที
- ตรวจสอบทุก Windows user session ที่ active
- Launch `recorder.exe` เข้าไปใน session ของแต่ละ user
- `recorder.exe` มี mutex → ไม่รันซ้ำถ้ามีอยู่แล้ว

---

## 📡 API Endpoints

| Method | Path | คำอธิบาย |
|--------|------|---------|
| `GET` | `/api/latest` | ภาพล่าสุดของทุกเครื่อง (Live View) |
| `GET` | `/api/clients` | รายชื่อเครื่องและ online status |
| `GET` | `/api/images` | รายการภาพ (รองรับ filter) |
| `GET` | `/api/images/view/<path>` | ดูภาพ |
| `POST` | `/api/upload` | Client อัปโหลดภาพ |
| `POST` | `/api/heartbeat` | Client แจ้ง online status |
| `GET` | `/api/config` | ดึง config ไปใช้งาน |
| `POST` | `/api/config` | บันทึก config |
| `GET` | `/api/disk-space` | ดู disk usage |
| `POST` | `/api/cleanup` | ลบภาพเก่าทันที |

---

## 📂 Storage Structure

ภาพถูกเก็บในรูปแบบ:

```
storage_path/
├── HOSTNAME_A/
│   └── USERNAME_1/
│       ├── capture_1700000001.jpg
│       └── capture_1700000006.jpg
└── HOSTNAME_B/
    └── USERNAME_2/
        └── capture_1700000001.jpg
```

---

## ⚡ Performance

| จำนวน Client | Request/วินาที (ประมาณ) |
|---|---|
| 10 เครื่อง | ~6 req/s |
| 50 เครื่อง | ~13 req/s |
| 100 เครื่อง | ~26 req/s |

- Config จาก Server จะถูก cache ไว้ 60 วินาที (ไม่ดึงทุก cycle)
- Flask `threaded=True` รองรับ concurrent requests
- Bottleneck จริงคือ Disk I/O ตอนเขียนไฟล์

---

## 📝 License

MIT License
