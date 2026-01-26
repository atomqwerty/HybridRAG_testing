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
    logger.warning("semantic-router not installed. Using fallback manual router.")
    HAS_SEMANTIC_ROUTER = False
    from sentence_transformers import SentenceTransformer, util

class ThaiRouter:
    def __init__(self):
        self.layer = None
        self.manual_model = None
        self.routes = {}
        
        # Define Routes Data
        self.route_definitions = {
            "fast_fact": [
                "เบอร์ติดต่อคืออะไร", "ออฟฟิศอยู่ที่ไหน", "ขออีเมลติดต่อ", 
                "ใครเป็นผู้จัดการ", "ราคาเท่าไหร่", "เบอร์โทร", 
                "ที่อยู่บริษัท", "ติดต่อใคร", "What is the phone number?",
                "Where is the office?", "Contact info"
            ],
            "visual_layout": [
                "ในตารางหน้า 3 บอกว่าอะไร", "ลายเซ็นใครอยู่ในไฟล์นี้", "ขอดูตารางสรุป",
                "กราฟนี้แสดงอะไร", "รูปภาพในหน้า 5", "แคปชั่นใต้ภาพ",
                "ตารางราคา", "ลายเซ็น", "โลโก้", "What does the table on page 3 say?",
                "Show me the graph", "Whose signature is this?"
            ],
            "deep_reasoning": [
                "วิเคราะห์ความเสี่ยง", "ความสัมพันธ์ระหว่าง A กับ B", "สรุปใจความสำคัญ",
                "เปรียบเทียบข้อดีข้อเสีย", "วิเคราะห์แนวโน้ม", "อธิบายเหตุผล",
                "ทำไมถึงเป็นแบบนั้น", "ความเชื่อมโยง", "Analyze risks",
                "Relationship between", "Summarize the key points", "Reasoning"
            ]
        }
        
        self._initialize_router()

    def _initialize_router(self):
        if HAS_SEMANTIC_ROUTER:
            try:
                # Use OpenAI Encoder for simplicity and speed if key exists
                if Config.OPENAI_API_KEY:
                    encoder = OpenAIEncoder(
                        openai_api_key=Config.OPENAI_API_KEY,
                        model="text-embedding-3-small" # Efficient
                    )
                else:
                    # Fallback to HF Local
                    encoder = HuggingFaceEncoder(name="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")

                routes = []
                for name, utterances in self.route_definitions.items():
                    routes.append(Route(name=name, utterances=utterances))

                self.layer = RouteLayer(encoder=encoder, routes=routes)
                logger.info("✅ Semantic Router Initialized (Library)")
            except Exception as e:
                logger.error(f"Failed to init semantic-router lib: {e}")
                self._init_manual_fallback()
        else:
            self._init_manual_fallback()

    def _init_manual_fallback(self):
        logger.info("Initializing Manual Fallback Router (SentenceTransformers)...")
        self.manual_model = SentenceTransformer("sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")
        # Pre-encode route utterances
        self.route_embeddings = {}
        for name, texts in self.route_definitions.items():
            self.route_embeddings[name] = self.manual_model.encode(texts)
        logger.info("✅ Manual Router Initialized")

    def route(self, query: str) -> str:
        """Returns: 'fast_fact', 'visual_layout', or 'deep_reasoning'"""
        if not query: return "fast_fact"

        if self.layer:
            try:
                # semantic-router call
                res = self.layer(query)
                if res.name:
                    logger.info(f"Router Decision: {res.name} (Score: {res.similarity})")
                    return res.name
            except Exception as e:
                logger.error(f"Router Lib failed: {e}")
        
        # Manual Fallback Logic
        if self.manual_model:
            q_emb = self.manual_model.encode(query)
            best_score = -1
            best_route = "fast_fact" # Default
            
            for name, route_embs in self.route_embeddings.items():
                # Compare query to all route examples, take Max Sim
                scores = util.cos_sim(q_emb, route_embs)[0]
                max_score = float(scores.max())
                
                if max_score > best_score:
                    best_score = max_score
                    best_route = name
            
            logger.info(f"Router Decision (Manual): {best_route} (Score: {best_score:.4f})")
            
            # Confidence Threshold
            if best_score < 0.4:
                logger.info("Low confidence, defaulting to deep_reasoning (Safe Path)")
                return "deep_reasoning"
                
            return best_route
            
        return "fast_fact"

# Global Instance
global_router = ThaiRouter()

def get_route(query):
    return global_router.route(query)
