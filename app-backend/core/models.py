"""
角色扮演记忆系统 — 完整数据库模型
SQLite (SQLAlchemy ORM) + ChromaDB (向量存储)

存储职责划分：
  SQLite   → 所有结构化数据（角色、会话、消息、记忆元数据、人格继承链）
  ChromaDB → 记忆片段的向量 embedding（以 memory_chunk.id 作为 document_id 关联）
"""

from sqlalchemy import (
    Table, Column, Integer, String, Text, Float, Boolean,
    ForeignKey, DateTime, Enum as SAEnum
)
from sqlalchemy.orm import declarative_base, relationship
from sqlalchemy.sql import func
import enum

Base = declarative_base()


# ──────────────────────────────────────────────
# Enum 定义
# ──────────────────────────────────────────────

class MessageRole(str, enum.Enum):
    user      = "user"
    assistant = "assistant"
    system    = "system"


class MemoryType(str, enum.Enum):
    event        = "event"         # 发生了什么事
    emotion      = "emotion"       # 角色的情绪体验
    relationship = "relationship"  # 与用户关系的变化
    fact         = "fact"          # 世界观/客观事实


# ──────────────────────────────────────────────
# 1. 角色蓝图表 (Character)
#    对接 SillyTavern 角色卡，纯静态设定，永不修改
# ──────────────────────────────────────────────

class Character(Base):
    __tablename__ = "characters"

    id = Column(Integer, primary_key=True, index=True)

    # SillyTavern 角色卡核心字段
    name                      = Column(String(50), nullable=False, index=True)
    description               = Column(Text,   nullable=False)   # 核心人设与外貌
    personality               = Column(Text,   nullable=True)    # 性格特点
    scenario                  = Column(Text,   nullable=True)    # 初始世界观/场景
    first_mes                 = Column(Text,   nullable=False)   # 默认开场白
    mes_example               = Column(Text,   nullable=True)    # Few-Shot 对话示例

    # 高级/系统设定
    creator_notes             = Column(Text,   nullable=True)    # 作者留言
    system_prompt_override    = Column(Text,   nullable=True)    # 覆盖全局 system prompt
    post_history_instructions = Column(Text,   nullable=True)    # 注入在历史末尾的指令
    tags                      = Column(String(255), nullable=True)    # 逗号分隔标签
    extensions                = Column(Text,   nullable=True)    # JSON，存扩展字段
    avatar_path               = Column(String(255), nullable=True)    # 头像路径

    created_at = Column(DateTime, default=func.now())            # 创作时间

    # 关联
    personas = relationship(
        "SessionPersona",
        back_populates="character",
        cascade="all, delete-orphan"
    )
    lorebooks = relationship(
        "Lorebook",
        secondary="character_lorebooks",
        back_populates="characters"
    )


# ──────────────────────────────────────────────
# 2. 会话表 (Session)
#    时间线容器。parent_session_id 记录"从哪条线继承而来"
# ──────────────────────────────────────────────

class Session(Base):
    __tablename__ = "sessions"

    id                = Column(Integer, primary_key=True, index=True)
    parent_session_id = Column(
        Integer,
        ForeignKey("sessions.id", ondelete="SET NULL"),
        nullable=True,
        index=True
    )

    title      = Column(String(50), default="New Story")
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    # 关联
    persona = relationship(
        "SessionPersona",
        back_populates="session",
        uselist=False,
        cascade="all, delete-orphan"
    )
    messages = relationship(
        "ChatMessage",
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="ChatMessage.id"  # 重构改进：使用主键排序，彻底防范 SQLite 并发插入微秒级排序错乱
    )
    children_sessions = relationship(
        "Session",
        backref="parent_session",
        remote_side=[id]
    )


# ──────────────────────────────────────────────
# 3. 子人格/动态状态表 (SessionPersona)
#    一个 Session 拥有唯一一个 Persona。
#
#    parent_persona_id 构成继承链：
#      session1.persona(id=1)
#        └── session2.persona(id=2, parent_persona_id=1)
#              └── session3.persona(id=3, parent_persona_id=2)
#
#    RAG 检索时沿链向上取所有祖先的 MemoryChunk，
#    实现跨会话的记忆透传。
# ──────────────────────────────────────────────

class SessionPersona(Base):
    __tablename__ = "session_personas"

    id           = Column(Integer, primary_key=True, index=True)
    session_id   = Column(
        Integer,
        ForeignKey("sessions.id", ondelete="CASCADE"),
        unique=True,
        nullable=False
    )
    character_id = Column(
        Integer,
        ForeignKey("characters.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )

    # 继承链：指向上一代 Persona（NULL 表示从角色蓝图全新创建）
    parent_persona_id = Column(
        Integer,
        ForeignKey("session_personas.id", ondelete="SET NULL"),
        nullable=True,
        index=True
    )

    # ── 动态运行状态 ──

    # 好感度（继承时复制父值作为初始值，之后在本会话中独立累积）
    affection_score = Column(Integer, default=0)

    # 大模型定期提炼写入的角色认知摘要。
    # 职责：描述"角色此刻对自己/世界/用户的整体认知"，直接组装进 System Prompt。
    # 区别于 MemoryChunk：这是宏观认知总结，MemoryChunk 是可检索的具体事件记录。
    cognition_state = Column(Text, nullable=True)

    # 场景覆盖（覆盖 Character.scenario，例如角色从"学校"走到"医院"）
    current_scenario_override = Column(Text,   nullable=True)

    # 当前心情标签，如 "开心" / "恐惧" / "平静"
    current_mood = Column(String(50), nullable=True)

    # ── 进度追踪指针 ──

    # 记忆提纯进度：上一次 summarize_and_store_memory 处理到的最后一条消息 ID
    # NULL 表示该 Persona 从未进行过记忆提纯
    last_summarized_msg_id = Column(
        Integer,
        ForeignKey("chat_messages.id", ondelete="SET NULL"),
        nullable=True
    )

    # 认知更新进度：上一次 update_cognition_state 处理到的最后一条消息 ID
    # NULL 表示该 Persona 从未进行过认知更新
    last_cognition_update_msg_id = Column(
        Integer,
        ForeignKey("chat_messages.id", ondelete="SET NULL"),
        nullable=True
    )

    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    # 关联
    session   = relationship("Session",   back_populates="persona")
    character = relationship("Character", back_populates="personas")
    memories  = relationship(
        "MemoryChunk",
        back_populates="persona",
        cascade="all, delete-orphan",
        order_by="MemoryChunk.created_at"
    )
    children_personas = relationship(
        "SessionPersona",
        backref="parent_persona",
        remote_side=[id]
    )


# ──────────────────────────────────────────────
# 4. 记忆片段表 (MemoryChunk)
#    RAG 的基础数据层。每条记录在 ChromaDB 中有一个对应的 document。
#
#    关联规则：
#      persona_id        → 该记忆"属于"哪个 Persona（用于 ChromaDB collection 路由）
#      origin_session_id → 该记忆"产生于"哪个 Session（跨会话后不变，用于溯源展示）
#      source_message_id → 可追溯到哪条原始消息（可选，调试用）
#
#    ChromaDB 关联：
#      collection_name = f"persona_{persona_id}"
#      document_id     = f"mem_{id}"（同步存入 chroma_doc_id 字段）
# ──────────────────────────────────────────────

class MemoryChunk(Base):
    __tablename__ = "memory_chunks"

    id         = Column(Integer, primary_key=True, index=True)
    persona_id = Column(
        Integer,
        ForeignKey("session_personas.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )

    # 记忆产生于哪个 Session（继承到新 Session 后此字段保持原值，用于显示记忆来源）
    origin_session_id = Column(
        Integer,
        ForeignKey("sessions.id", ondelete="SET NULL"),
        nullable=True,
        index=True
    )

    # 可追溯到哪条原始消息
    source_message_id = Column(
        Integer,
        ForeignKey("chat_messages.id", ondelete="SET NULL"),
        nullable=True
    )

    content          = Column(Text,              nullable=False)           # 记忆的自然语言描述
    memory_type      = Column(SAEnum(MemoryType), nullable=False)
    importance_score = Column(Float,             default=0.5)             # 0.0~1.0，检索过滤用

    # ChromaDB 的 document_id，格式固定为 f"mem_{id}"，写入后不再修改
    chroma_doc_id = Column(String(50), nullable=True, unique=True)

    created_at = Column(DateTime, default=func.now())

    # 关联
    persona        = relationship("SessionPersona", back_populates="memories")
    source_message = relationship("ChatMessage",    back_populates="memory_chunks")


# ──────────────────────────────────────────────
# 4.5 知识图谱表 (Graph RAG)
# ──────────────────────────────────────────────

class GraphEntity(Base):
    __tablename__ = "graph_entities"

    id         = Column(Integer, primary_key=True, index=True)
    persona_id = Column(
        Integer,
        ForeignKey("session_personas.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    name        = Column(String(100), nullable=False, index=True)
    entity_type = Column(String(50), nullable=False)  # "person", "place", "object", "event", "concept"
    description = Column(Text, nullable=True)
    created_at  = Column(DateTime, default=func.now())


class GraphRelation(Base):
    __tablename__ = "graph_relations"

    id         = Column(Integer, primary_key=True, index=True)
    persona_id = Column(
        Integer,
        ForeignKey("session_personas.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    source_id = Column(
        Integer,
        ForeignKey("graph_entities.id", ondelete="CASCADE"),
        nullable=False
    )
    target_id = Column(
        Integer,
        ForeignKey("graph_entities.id", ondelete="CASCADE"),
        nullable=False
    )
    relation_type = Column(String(50), nullable=False)
    description   = Column(Text, nullable=True)
    importance    = Column(Float, default=0.5)
    created_at    = Column(DateTime, default=func.now())


# ──────────────────────────────────────────────
# 5. 消息表 (ChatMessage)
#    每条聊天记录，是生成 MemoryChunk 的原材料。
# ──────────────────────────────────────────────

class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id         = Column(Integer, primary_key=True, index=True)
    session_id = Column(
        Integer,
        ForeignKey("sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )

    role    = Column(SAEnum(MessageRole), nullable=False)
    content = Column(Text, nullable=False)

    # 消息级微状态（溯源用，不参与 RAG）
    emotion_tag      = Column(String(50),  nullable=True)  # 发出本条消息时角色的情绪标签
    affection_change = Column(Integer, nullable=True)  # 本条消息带来的好感度变动量（正/负）
    audio_path       = Column(String(255), nullable=True)  # 该条消息的 TTS 音频文件本地相对路径/URL

    # Swipe 候选回复支持
    parent_id  = Column(Integer, ForeignKey("chat_messages.id", ondelete="CASCADE"), nullable=True, index=True)
    is_active  = Column(Boolean, default=True, nullable=False)

    created_at = Column(DateTime, default=func.now())

    # 关联
    session       = relationship("Session",     back_populates="messages")
    memory_chunks = relationship("MemoryChunk", back_populates="source_message")


# ──────────────────────────────────────────────
# 6. 世界书关联与条目表 (Lorebooks)
# ──────────────────────────────────────────────

# 隐式中间关联表
character_lorebooks = Table(
    "character_lorebooks",
    Base.metadata,
    Column("character_id", Integer, ForeignKey("characters.id", ondelete="CASCADE"), primary_key=True),
    Column("lorebook_id", Integer, ForeignKey("lorebooks.id", ondelete="CASCADE"), primary_key=True)
)


class Lorebook(Base):
    __tablename__ = "lorebooks"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)

    # 局部检索配置覆盖（为 Null 时回退到全局默认配置）
    scan_depth = Column(Integer, nullable=True)
    token_budget = Column(Integer, nullable=True)
    recursive_scanning = Column(Boolean, nullable=True)

    # 世界书条目列表，序列化存储为 JSON 字符串以降低表结构复杂度
    # 结构: [{"keys": ["k1"], "content": "...", "enabled": true, "constant": false, ...}]
    entries = Column(Text, nullable=True)

    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    # 关联
    characters = relationship(
        "Character",
        secondary=character_lorebooks,
        back_populates="lorebooks"
    )
