import os
from typing import List, Optional
from config import Config
from logger import setup_logger

logger = setup_logger(__name__)

# Try importing semantic_router, else fallback to manual implementation
try:
    from semantic_router import Route
    from semantic_router.encoders import OpenAIEncoder, HuggingFaceEncoder
    from semantic_router.layer import RouteLayer
    HAS_SEMANTIC_ROUTER = True
except ImportError:
    HAS_SEMANTIC_ROUTER = False
    
try:
    from sentence_transformers import SentenceTransformer, util
    HAS_SENTENCE_TRANSFORMERS = True
except ImportError:
    HAS_SENTENCE_TRANSFORMERS = False
    # Fallback to LangChain OpenAI
    from langchain_openai import OpenAIEmbeddings
    import numpy as np
    
    def cosine_similarity(a, b):
        return np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b))

class ThaiRouter:
    def __init__(self):
        self.layer = None
        self.manual_model = None
        self.openai_backup = None
        self.routes = {}
        
        # Define Routes Data
        self.route_definitions = {
            "fast_fact": [
                "เบอร์ติดต่อคืออะไร", "ออฟฟิศอยู่ที่ไหน", "ขออีเมลติดต่อ", 
                "ใครเป็นผู้จัดการ", "ราคาเท่าไหร่", "เบอร์โทร", 
                "ที่อยู่บริษัท", "ติดต่อใคร", "What is the phone number?"
            ],
            "visual_layout": [
                "ในตารางหน้า 3 บอกว่าอะไร", "ลายเซ็นใครอยู่ในไฟล์นี้", "ขอดูตารางสรุป",
                "กราฟนี้แสดงอะไร", "รูปภาพในหน้า 5", "แคปชั่นใต้ภาพ",
                "ตารางราคา", "ลายเซ็น", "โลโก้"
            ],
            "deep_reasoning": [
                "วิเคราะห์ความเสี่ยง", "ความสัมพันธ์ระหว่าง A กับ B", "สรุปใจความสำคัญ",
                "เปรียบเทียบข้อดีข้อเสีย", "วิเคราะห์แนวโน้ม", "อธิบายเหตุผล",
                "ทำไมถึงเป็นแบบนั้น", "ความเชื่อมโยง", "Analyze risks"
            ]
        }
        
        self._initialize_router()

    def _initialize_router(self):
        if HAS_SEMANTIC_ROUTER:
            try:
                if Config.OPENAI_API_KEY:
                    encoder = OpenAIEncoder(
                        openai_api_key=Config.OPENAI_API_KEY,
                        model="text-embedding-3-small"
                    )
                else:
                    encoder = HuggingFaceEncoder(name="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")

                routes = []
                for name, utterances in self.route_definitions.items():
                    routes.append(Route(name=name, utterances=utterances))

                self.layer = RouteLayer(encoder=encoder, routes=routes)
                logger.info("✅ Semantic Router Initialized (Library)")
            except Exception as e:
                logger.warning(f"Failed to init semantic-router lib: {e}")
                self._init_manual_fallback()
        else:
            self._init_manual_fallback()

    def _init_manual_fallback(self):
        if HAS_SENTENCE_TRANSFORMERS:
            logger.info("Initializing Manual Fallback Router (SentenceTransformers)...")
            try:
                self.manual_model = SentenceTransformer("sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")
                self.route_embeddings = {}
                for name, texts in self.route_definitions.items():
                    self.route_embeddings[name] = self.manual_model.encode(texts)
                logger.info("✅ Manual Router Initialized (ST)")
            except Exception as e:
                logger.error(f"Failed to init ST router: {e}")
                self._init_openai_fallback()
        else:
            self._init_openai_fallback()
            
    def _init_openai_fallback(self):
        logger.info("Initializing Backup Router (OpenAI Embeddings)...")
        try:
            self.openai_backup = OpenAIEmbeddings(
                model=Config.OPENAI_EMBEDDING_MODEL,
                openai_api_key=Config.OPENAI_API_KEY,
                openai_api_base=Config.OPENAI_BASE_URL
            )
            self.route_embeddings = {}
            for name, texts in self.route_definitions.items():
                self.route_embeddings[name] = self.openai_backup.embed_documents(texts) # List of lists
            logger.info("✅ Backup Router Initialized (OpenAI)")
        except Exception as e:
            logger.error(f"Failed to init OpenAI router: {e}")

    def route(self, query: str) -> str:
        """Returns: 'fast_fact', 'visual_layout', or 'deep_reasoning'"""
        if not query: return "fast_fact"

        # 1. Lib
        if self.layer:
            try:
                res = self.layer(query)
                if res.name: return res.name
            except: pass
        
        # 2. Manual ST
        if self.manual_model:
            q_emb = self.manual_model.encode(query)
            best_score = -1
            best_route = "fast_fact"
            
            for name, route_embs in self.route_embeddings.items():
                scores = util.cos_sim(q_emb, route_embs)[0]
                if float(scores.max()) > best_score:
                    best_score = float(scores.max())
                    best_route = name
            
            if best_score < 0.4: return "deep_reasoning"
            return best_route
            
        # 3. Backup OpenAI
        if self.openai_backup:
            try:
                q_emb = self.openai_backup.embed_query(query)
                best_score = -1
                best_route = "fast_fact"
                
                for name, route_embs in self.route_embeddings.items():
                    # manual max cosine sim
                    # route_embs is list of vectors
                    for r_emb in route_embs:
                        score = cosine_similarity(q_emb, r_emb)
                        if score > best_score:
                            best_score = score
                            best_route = name
                
                logger.info(f"Router (OpenAI) Score: {best_score} -> {best_route}")
                if best_score < 0.75: return "deep_reasoning"
                return best_route
            except Exception as e:
                logger.error(f"OpenAI routing failed: {e}")
                
        return "fast_fact"

# Global Instance (Lazy)
global_router = None

def get_route(query):
    global global_router
    if global_router is None:
        logger.info("Initializing Lazy Router...")
        global_router = ThaiRouter()
    return global_router.route(query)
