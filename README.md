# 🚀 ระบบ Hybrid RAG ขั้นสูง (Ultimate Hybrid RAG System)

ระบบ Retrieval-Augmented Generation (RAG) ที่ทันสมัยและครบวงจรที่สุด ผสานพลังของ **Knowledge Graph (Neo4j)** และ **Vector Search** เข้าด้วยกัน รองรับการนำเข้าข้อมูลที่หลากหลาย (Multimodal) และมีระบบแชทบอทอัจฉริยะ พร้อม **Web Interface** สำหรับใช้งานผ่านเบราว์เซอร์

## ✨ คุณสมบัติเด่น (Features)

*   **🌐 แหล่งข้อมูลหลากหลาย (Multi-Source Ingestion):**
    *   **PDF:** อ่านข้อความ ตาราง (รักษาโครงสร้าง) และ **ดึงรูปภาพ/กราฟ** ออกมาวิเคราะห์
    *   **DOCX / TXT:** รองรับไฟล์เอกสารทั่วไป
    *   **Website:** ดึงข้อมูลจากเว็บไซต์ผ่านไฟล์ `data/urls.txt`
    *   **Images:** รองรับไฟล์รูปภาพ (.jpg, .png) โดยตรง

*   **🧠 การแบ่งข้อมูลอัจฉริยะ (Smart Hybrid Chunking):**
    *   **Table-Aware:** ตรวจจับหน้าที่มีตารางและเก็บไว้ทั้งหน้าเพื่อรักษาโครงสร้างข้อมูล
    *   **Semantic Chunking:** สำหรับเนื้อหาทั่วไป จะแบ่งตามความหมายของประโยค (ไม่ใช่แค่ตัดตามจำนวนคำ) ทำให้แม่นยำกว่า

*   **👁️ ความสามารถด้านการมองเห็น (Multimodal AI):**
    *   ใช้ **GPT-4o Vision** เพื่ออธิบายรูปภาพ กราฟ หรือแผนภูมิที่อยู่ในเอกสาร
    *   **บันทึกรูปภาพ:** รูปภาพที่เจอจะถูกบันทึกลงเครื่อง (`data/extracted_images/`) และแสดงผลเมื่อคุณถามถึง

*   **💬 แชทบอทอัจฉริยะ (Intelligent Chatbot):**
    *   **ความจำ (Memory):** จำบทสนทนาก่อนหน้าได้ (เช่น ถามต่อว่า "แล้วปีหน้าล่ะ?")
    *   **ภาษาไทย:** รองรับการถาม-ตอบเป็นภาษาไทยอย่างสมบูรณ์
    *   **แสดงรูป:** หากคำตอบอ้างอิงถึงรูปภาพ ระบบจะเปิดรูปภาพนั้นขึ้นมาให้ดูทันที
    *   **Re-ranking:** ระบบจัดอันดับความเกี่ยวข้องของข้อมูลอัจฉริยะ (รองรับ LLM, Cohere, Cross-Encoder)

*   **🌐 Web Interface (React):**
    *   **Real-time Chat:** สนทนาแบบเรียลไทม์
    *   **แสดงแหล่งที่มา:** อ้างอิงไฟล์และหน้าที่ใช้ตอบคำถาม
    *   **แสดงรูปภาพ:** รูปที่เกี่ยวข้องจะแสดงในหน้าเว็บ

---

## ⚡ Quick Setup & Start Guide (เริ่มใช้งานด่วน)

ทำตาม 4 ขั้นตอนง่ายๆ เพื่อรันระบบ Hybrid RAG ทั้งหมดบนเครื่องของคุณ:

**1. เปิดฐานข้อมูล (Database)**
```bash
docker compose up -d
```

**2. ตั้งค่า Backend & API**
ใส่คีย์ `OpenAi_api` และข้อมูลเชื่อมต่อ `Neo4j` ในไฟล์ `.env` (ดูได้ที่หัวข้อ การตั้งค่า) จากนั้นรัน:
```bash
pip install -r requirements.txt
python api.py
```
*(API จะเปิดทำงานที่ `http://localhost:5000`)*

**3. เปิดใช้งาน Frontend (หน้าเว็บ)**
เปิด Terminal หน้าต่างใหม่ และรัน:
```bash
cd frontend
npm install
npm start
```

**4. เริ่มต้นใช้งานได้ทันที!**
* เปิดเว็บเบราว์เซอร์ไปที่ `http://localhost:3000`
* ล็อกอินบัญชีแอดมินเริ่มต้น: **Username**: `admin` | **Password**: `admin`

---

## 🛠️ การติดตั้ง (Installation) แบบละเอียด

### 1. ติดตั้ง Neo4j
**ใช้ Docker-compose.yml สำหรับการติดตั้ง:**
```yaml
volumes:
   "C:/Users/******/Neo4j/data:/data"
   "C:/Users/******/Neo4j/logs:/logs"
   "C:/Users/******/Neo4j/import:/import"
   "C:/Users/******/Neo4j/plugins:/plugins"
```

### 2. ติดตั้ง Python Dependencies
```bash
# แนะนำให้ใช้ Python 3.10+
pip install -r requirements.txt
```

### 3. ติดตั้ง Frontend (Web Interface)
```bash
cd frontend
npm install
```

---

## ⚙️ การตั้งค่า (Configuration)

สร้างไฟล์ `.env` ในโฟลเดอร์หลัก และใส่คีย์ดังนี้:

```env
# Neo4j Config
NEO4J_URI=bolt://localhost:7687
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=your_password
ALLOWED_NODES="OPEN"
ALLOWED_RELATIONSHIPS="OPEN"

# OpenAI API
OpenAi_api=sk-proj-...
OpenAi_api_embbeding=sk-proj-...

# Re-ranker (Optional)
RERANKER_METHOD=llm  # Options: "llm", "cohere", "cross-encoder"
# COHERE_API_KEY=your_cohere_key  # If using Cohere
```

---

## 🚀 การใช้งาน (Usage)

### วิธีที่ 1: Command Line (Terminal)

#### 1. เตรียมข้อมูล
*   วางไฟล์ PDF, DOCX, TXT หรือรูปภาพลงใน `data/`
*   ใส่ URL ลงใน `data/urls.txt` (ถ้าต้องการ)

#### 2. นำเข้าข้อมูล
```bash
python ingest_graph.py
```

#### 3. รันแชทบอท
```bash
python run_qa.py
```

---

### วิธีที่ 2: Web Interface (แนะนำ) 🌐

#### 1. เตรียมข้อมูล (เหมือนวิธีที่ 1)
```bash
python ingest_graph.py
```

#### 2. เปิด Backend API
```bash
python api.py
```
API จะรันที่ `http://localhost:5000`

#### 3. เปิด Frontend (Terminal ใหม่)
```bash
cd frontend
npm start
```
Web Interface จะเปิดที่ `http://localhost:3000`

#### 4. เริ่มใช้งาน!
- เปิดเบราว์เซอร์ไปที่ `http://localhost:3000`
- พิมพ์คำถามในช่องแชท
- ระบบจะแสดง:
  - คำตอบ
  - แหล่งที่มา (ไฟล์ + หน้า)
  - รูปภาพที่เกี่ยวข้อง

---

## 📂 โครงสร้างไฟล์ (Project Structure)

```
HybridRAG_testing/
├── main.py                        # App entrypoint
├── docker-compose.yml             # Docker services
├── Dockerfile
├── requirements.txt
├── source_config.json             # Trust Rules config
│
├── app/
│   ├── __init__.py                # Flask app factory
│   ├── config.py                  # All env vars & paths
│   ├── router.py                  # Semantic route classifier
│   ├── run_qa.py                  # Core hybrid RAG retrieval
│   ├── crawler.py                 # Web scraper (Selenium + BS4)
│   ├── database.py                # Neo4j index helpers
│   ├── utils.py                   # update_status(), trust helpers
│   ├── vision_utils.py            # Image encode / GPT-4o describe
│   ├── mineru_utils.py            # MinerU PDF extraction
│   │
│   ├── agents/                    # ★ NEW: Multi-Agent system
│   │   ├── supervisor.py          # Intent classifier → routes to agent
│   │   ├── image_agent.py         # Graph Filter → Filtered Vector Search
│   │   ├── table_agent.py         # Pandas + LLM code → Markdown table
│   │   └── text_agent.py          # Wrapper around run_qa hybrid RAG
│   │
│   ├── api/                       # Flask Blueprints
│   │   ├── chat_routes.py         # /api/chat, /api/chat/stream
│   │   ├── file_routes.py         # /api/ingest/*, /api/config/trust, etc.
│   │   └── crawl_routes.py        # /api/crawl/*, /api/export/*
│   │
│   ├── ingest/                    # Ingestion strategies
│   │   ├── base.py                # Abstract BaseIngestor
│   │   ├── dlt_ingest.py          # DLT pipeline (primary)
│   │   └── native_ingest.py       # Native Python (placeholder)
│   │
│   └── services/                  # Business logic layer
│       ├── chat_service.py        # Orchestrates Supervisor → Agents
│       ├── crawl_service.py       # Job queue + crawl execution
│       ├── file_service.py        # File save, delete, clear DB
│       └── ingest_service.py      # Facade for ingest strategies
│
├── frontend/
│   ├── src/
│   │   ├── App.jsx                # Main React component
│   │   └── App.css
│   └── package.json
│
├── scripts/                       # Utility & test scripts
└── data/                          # Runtime data (gitignored)
    ├── extracted_images/
    └── chat_sessions.json
```

---

## 🔧 คุณสมบัติขั้นสูง (Advanced Features)

### Re-Ranking
ระบบรองรับ 3 วิธีในการจัดอันดับความเกี่ยวข้อง:

1. **LLM** (Default) - ใช้ GPT-4o
2. **Cohere** - เร็วและแม่นยำ (แนะนำสำหรับ Production)
3. **Cross-Encoder** - รันบนเครื่อง ฟรี

ดูรายละเอียดใน `RERANKER_GUIDE.md`

### การปรับแต่ง
- **จำนวนผลลัพธ์:** แก้ `k=5` ใน `run_qa.py`
- **คะแนนขั้นต่ำ:** แก้ `min_score=0.7`
- **จำนวนผลลัพธ์หลัง Re-rank:** แก้ `top_k=3`

---

## 💡 Tips & Tricks

- ถามเป็นภาษาไทยได้เลย ระบบจะตอบเป็นภาษาไทย
- ถามเป็นภาษาอังกฤษ ระบบจะตอบเป็นภาษาอังกฤษ
- ถ้ามีรูปภาพที่เกี่ยวข้อง ระบบจะแสดงให้ดูอัตโนมัติ
- ระบบจำบทสนทนาได้ สามารถถามต่อเนื่องได้

---

## 🆘 Troubleshooting

**ปัญหา: รูปภาพไม่แสดงใน Web**
- ตรวจสอบว่า `python api.py` รันอยู่
- เช็คว่ารูปอยู่ใน `data/extracted_images/`

**ปัญหา: ตอบช้า**
- ลดค่า `k` ใน `run_qa.py`
- ใช้ Cohere Reranker แทน LLM

**ปัญหา: ตอบไม่ตรงคำถาม**
- เพิ่มค่า `min_score` เป็น 0.8
- ตรวจสอบว่าข้อมูลถูกนำเข้าครบแล้ว

---

## 📚 เอกสารเพิ่มเติม

- `RERANKER_GUIDE.md` - คู่มือการตั้งค่า Re-ranker
- `WEB_README.md` - รายละเอียด Web Interface (เก่า - รวมในไฟล์นี้แล้ว)

---

**พัฒนาด้วย ❤️ โดย Hybrid RAG Team**

---

## 🔌 API Reference

Base URL: `http://localhost:8080/api`

### Chat

| Method | Endpoint | Body | Description |
|---|---|---|---|
| POST | `/chat` | `{message, session_id, temperature}` | Standard blocking chat |
| POST | `/chat/stream` | `{message, session_id}` | Streaming NDJSON response |

### Ingestion & Files

| Method | Endpoint | Description |
|---|---|---|
| POST | `/ingest/upload` | Upload file(s) → background ingestion (returns 202) |
| POST | `/ingest/url` | Crawl URL → background ingestion (returns 202) |
| GET | `/ingest/status` | Poll progress `{percent, message, status}` |
| GET | `/files` | List uploaded files |
| POST | `/delete` | Delete a file `{filename}` |
| GET | `/download/<filename>` | Download a raw file |
| POST | `/admin/clear_db` | Wipe Neo4j + Trust Rules |
| GET | `/config/trust` | Get trust rules config |
| POST | `/config/trust` | Save trust rules config |
| DELETE | `/source` | Delete Neo4j nodes by source pattern `{pattern}` |
| POST | `/clear` | Clear session chat history `{session_id}` |
| GET | `/images/<filename>` | Serve a stored image file |

### Crawler Jobs

| Method | Endpoint | Description |
|---|---|---|
| POST | `/crawl` | Submit a new crawl job |
| GET | `/crawl/<job_id>` | Poll job status & results |
| DELETE | `/crawl/<job_id>` | Cancel a running job |
| GET | `/results/<job_id>` | Fetch scraped page results |
| GET | `/export/<job_id>` | Export results `?format=json\|csv\|xml` |
| GET | `/crawl/queue` | List all pending jobs |
| POST | `/crawl/queue/pause` | Pause the job queue |
| POST | `/crawl/queue/resume` | Resume the job queue |

---

## 🤖 Multi-Agent Architecture

```
User Message
     │
     ▼
 Supervisor (app/agents/supervisor.py)
  - Keyword fast-path (visual / table keywords)
  - LLM intent classification fallback
  - Extracts car model entity name
     │
     ├── intent="visual"  ──▶ ImageAgent (app/agents/image_agent.py)
     │                          1. Graph Filter: find Car node by entity name
     │                          2. Filtered Vector Search (restricted to that source)
     │
     ├── intent="table"   ──▶ TableAgent (app/agents/table_agent.py)
     │                          1. Load Car specs from Neo4j → Pandas DataFrame
     │                          2. LLM generates Pandas code → Markdown table
     │
     └── intent="text"    ──▶ TextAgent (app/agents/text_agent.py)
                                Wraps existing hybrid RAG (run_qa.py)
```

| File | Role |
|---|---|
| `app/agents/supervisor.py` | Intent classification + entity extraction |
| `app/agents/image_agent.py` | Graph-filtered image retrieval |
| `app/agents/table_agent.py` | Pandas spec comparison |
| `app/agents/text_agent.py` | General hybrid RAG wrapper |
| `app/services/chat_service.py` | Orchestration: Supervisor → Agent dispatch |
