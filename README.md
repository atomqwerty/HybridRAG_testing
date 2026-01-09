# 🚀 ระบบ Hybrid RAG ขั้นสูง (Ultimate Hybrid RAG System)

ระบบ Retrieval-Augmented Generation (RAG) ที่ทันสมัยและครบวงจรที่สุด ผสานพลังของ **Knowledge Graph (Neo4j)** และ **Vector Search** เข้าด้วยกัน รองรับการนำเข้าข้อมูลที่หลากหลาย (Multimodal) และมีระบบแชทบอทอัจฉริยะ

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

---

## 🛠️ การติดตั้ง (Installation)

1.  **Clone โปรเจกต์** หรือเตรียมโฟลเดอร์ให้พร้อม
2.  **ติดตั้ง Neo4j Desktop** และสร้าง Project ใหม่ (Local Database)
    *   ใช้ Docker-compose.yml สำหรับการติดตั้ง
    *   ตั้งค่า volumes ให้ตรงกับโฟลเดอร์ที่ต้องการ
    เช่น
    volumes:
      - "C:/Users/Dashboard/Documents/Neo4j/data:/data"
      - "C:/Users/Dashboard/Documents/Neo4j/logs:/logs"
      - "C:/Users/Dashboard/Documents/Neo4j/import:/import"
      - "C:/Users/Dashboard/Documents/Neo4j/plugins:/plugins"
3.  **สร้าง Environment และติดตั้ง Library:**

```bash
# แนะนำให้ใช้ Python 3.10+
pip install -r requirements.txt
```

---

## ⚙️ การตั้งค่า (Configuration)

สร้างไฟล์ `.env` ในโฟลเดอร์หลัก และใส่คีย์ดังนี้:

```env
# Neo4j Config
NEO4J_URI=bolt://localhost:7687
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=your_password
ALLOWED_NODES="OPEN"/Node ที่อนุญาติให้ตั้งค่า
ALLOWED_RELATIONSHIPS="OPEN"/Relationship ที่อนุญาติให้ตั้งค่า

# OpenAI API
OpenAi_api=sk-proj-...
OpenAi_api_embbeding=sk-proj-...


```

---

## 🚀 การใช้งาน (Usage)

### 1. เตรียมข้อมูล (Prepare Data)
*   วางไฟล์ PDF, DOCX, TXT หรือรูปภาพที่ต้องการลงในโฟลเดอร์ `data/`
*   หากต้องการดึงข้อมูลจากเว็บ ให้ใส่ URL ลงในไฟล์ `data/urls.txt` (บรรทัดละ 1 URL)

### 2. นำเข้าข้อมูล (Ingestion)
รันไฟล์ `ingest_graph.py` เพื่อเริ่มกระบวนการ:
*   สแกนไฟล์ทั้งหมด
*   ดึงข้อความ/รูปภาพ และอธิบายรูปด้วย AI
*   สร้าง Vector Embeddings และ Graph
*   บันทึกรูปลง `data/extracted_images/`

```bash
python ingest_graph.py
```
*(ขั้นตอนนี้อาจใช้เวลาหลายนาที ขึ้นอยู่กับจำนวนไฟล์และความละเอียดของ Semantic Chunking)*

### 3. รันแชทบอท (Run Chatbot)
เมื่อนำเข้าข้อมูลเสร็จสิ้น ให้รันไฟล์ `run_qa.py` เพื่อเริ่มคุย:

```bash
python run_qa.py
```

*   **ตัวอย่างการถาม:** "ใครได้คะแนนเยอะที่สุดในปี 2024?"
*   ถ้าข้อมูลคำตอบอยู่ในรูปภาพ ระบบจะเปิดรูปภาพขึ้นมาให้ดูโดยอัตโนมัติ

---

## 📂 โครงสร้างไฟล์ (Project Structure)

*   `ingest_graph.py`: สคริปต์หลักสำหรับนำเข้าข้อมูล (Data Pipeline)
*   `run_qa.py`: สคริปต์แชทบอท (RAG Chain, Memory, Image Display)
*   `vision_utils.py`: ฟังก์ชันเสริมสำหรับจัดการรูปภาพและ Vision API
*   `data/`: โฟลเดอร์เก็บเอกสารต้นฉบับ
    *   `urls.txt`: ลิงก์เว็บที่ต้องการสแครป
    *   `extracted_images/`: รูปภาพที่ระบบดึงออกมาจาก PDF (สร้างอัตโนมัติ)

---
