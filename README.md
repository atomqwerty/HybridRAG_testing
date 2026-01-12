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

## 🛠️ การติดตั้ง (Installation)

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
├── ingest_graph.py          # นำเข้าข้อมูล
├── run_qa.py                # แชทบอท CLI
├── api.py                   # Flask API สำหรับ Web
├── vision_utils.py          # จัดการรูปภาพ
├── data/
│   ├── *.pdf, *.docx, *.jpg # ไฟล์ต้นฉบับ
│   ├── urls.txt             # URL เว็บไซต์
│   └── extracted_images/    # รูปที่ดึงจาก PDF
└── frontend/
    ├── src/
    │   ├── App.jsx          # React Component
    │   └── App.css          # Styling
    └── package.json
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
