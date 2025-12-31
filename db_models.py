"""
PFC - 数据库模型

================================================================================
版权声明 (Copyright Notice)
================================================================================

本文件为 MoFox_Bot 项目的一部分。

本项目遵循 GNU General Public License v3.0 许可证。
详见 LICENSE 文件。

================================================================================

定义 PFC 会话的数据库模型，支持 SQLite 和 PostgreSQL。
"""

import datetime
import time

from sqlalchemy import Boolean, Float, Index, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from src.common.database.core.models import Base, get_string_field


class PFCSession(Base):
    """PFC 会话模型
    
    存储私聊会话的状态和历史信息。
    """

    __tablename__ = "pfc_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    
    # 基本信息
    user_id: Mapped[str] = mapped_column(get_string_field(100), nullable=False, unique=True, index=True)
    stream_id: Mapped[str] = mapped_column(get_string_field(100), nullable=False)
    
    # 状态
    state: Mapped[str] = mapped_column(get_string_field(50), nullable=False, default="init")
    should_continue: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    ignore_until_timestamp: Mapped[float | None] = mapped_column(Float, nullable=True)
    
    # 对话信息 (JSON 格式存储)
    conversation_info_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    
    # 观察信息 (JSON 格式存储)
    observation_info_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    
    # 等待配置
    waiting_max_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    waiting_started_at: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    
    # 时间戳
    created_at: Mapped[float] = mapped_column(Float, nullable=False, default=time.time)
    last_activity_at: Mapped[float] = mapped_column(Float, nullable=False, default=time.time)
    
    # 统计
    total_interactions: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    
    # 主动思考
    last_proactive_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    
    # 超时计数
    consecutive_timeout_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    
    # 用户最后发消息时间
    last_user_message_at: Mapped[float | None] = mapped_column(Float, nullable=True)

    __table_args__ = (
        Index("idx_pfc_session_user_id", "user_id"),
        Index("idx_pfc_session_state", "state"),
        Index("idx_pfc_session_last_activity", "last_activity_at"),
    )


class PFCChatHistory(Base):
    """PFC 聊天历史模型
    
    存储私聊的消息历史，用于重启后恢复上下文。
    """

    __tablename__ = "pfc_chat_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    
    # 关联信息
    user_id: Mapped[str] = mapped_column(get_string_field(100), nullable=False, index=True)
    
    # 消息信息
    message_type: Mapped[str] = mapped_column(get_string_field(50), nullable=False)  # user_message, bot_message
    content: Mapped[str] = mapped_column(Text, nullable=False)
    sender_name: Mapped[str | None] = mapped_column(get_string_field(100), nullable=True)
    sender_id: Mapped[str | None] = mapped_column(get_string_field(100), nullable=True)
    
    # 时间戳
    message_time: Mapped[float] = mapped_column(Float, nullable=False, default=time.time)
    created_at: Mapped[float] = mapped_column(Float, nullable=False, default=time.time)

    __table_args__ = (
        Index("idx_pfc_history_user_id", "user_id"),
        Index("idx_pfc_history_time", "message_time"),
        Index("idx_pfc_history_user_time", "user_id", "message_time"),
    )