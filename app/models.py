from sqlalchemy import Column, String, DateTime, JSON, Text, ForeignKey
from app.db import Base
from datetime import datetime, timezone
import uuid

class User(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    username = Column(String, unique=True, nullable=False, index=True)
    password_hash = Column(String, nullable=False)
    role = Column(String, nullable=False, default="user")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    def to_dict(self):
        return {
            "id": self.id,
            "username": self.username,
            "role": self.role,
            "created_at": self.created_at.isoformat() if self.created_at else None
        }

class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    actor = Column(String, nullable=False, index=True)
    action = Column(String, nullable=False)
    detail = Column(String)
    before = Column(JSON)
    after = Column(JSON)

    def to_dict(self):
        return {
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "actor": self.actor,
            "action": self.action,
            "detail": self.detail,
            "before": self.before,
            "after": self.after
        }

class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id         = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id    = Column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    session_id = Column(String, nullable=False, index=True)
    role       = Column(String, nullable=False)   # 'user' | 'bot'
    content    = Column(Text, nullable=False)
    sources    = Column(JSON)                     # list of source citations
    timestamp  = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    def to_dict(self):
        return {
            "id":        self.id,
            "role":      self.role,
            "content":   self.content,
            "sources":   self.sources or [],
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
        }


class RagConfig(Base):
    """Table storing runtime RAG tuning parameters. Row ID=1 is Live, ID=2 is Draft."""
    __tablename__ = "rag_config"

    id             = Column(String, primary_key=True)
    k              = Column(String, nullable=False, default="10")    # vector chunks per query
    k_keyword      = Column(String, nullable=False, default="15")    # keyword chunks
    min_score      = Column(String, nullable=False, default="0.50")  # vector similarity threshold
    top_k_rerank   = Column(String, nullable=False, default="10")    # chunks kept after reranking
    multi_query    = Column(String, nullable=False, default="true")  # query expansion enabled
    system_prompt  = Column(Text, nullable=True)                     # custom bot personality
    persona_name   = Column(String, nullable=True, default="Default")
    updated_at     = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    updated_by     = Column(String, nullable=True)

    def to_dict(self):
        return {
            "id":           self.id,
            "k":            int(self.k),
            "k_keyword":    int(self.k_keyword),
            "min_score":    float(self.min_score),
            "top_k_rerank": int(self.top_k_rerank),
            "multi_query":  self.multi_query == "true",
            "system_prompt": self.system_prompt or "",
            "persona_name":  self.persona_name or "Default",
            "updated_at":   self.updated_at.isoformat() if self.updated_at else None,
            "updated_by":   self.updated_by,
        }
