"""
PFC - 数据库存储后端

================================================================================
版权声明 (Copyright Notice)
================================================================================

本文件为 MoFox_Bot 项目的一部分。

本项目遵循 GNU General Public License v3.0 许可证。
详见 LICENSE 文件。

================================================================================

提供基于数据库的会话存储，支持 SQLite 和 PostgreSQL。

注意：PFC 的数据库模型（PFCSession, PFCChatHistory）继承自 MoFox 的 Base，
会在数据库迁移时自动创建表。
"""

import json
import time
from typing import TYPE_CHECKING

from sqlalchemy import delete, select

from src.common.database.api.crud import CRUDBase
from src.common.database.core.session import get_db_session
from src.common.logger import get_logger

# 导入 PFC 数据库模型（这会将它们注册到 Base.metadata）
from .db_models import PFCChatHistory, PFCSession as PFCSessionModel

if TYPE_CHECKING:
    from .session import PFCSession

logger = get_logger("pfc_db_storage")


class PFCSessionCRUD(CRUDBase[PFCSessionModel]):
    """PFC 会话 CRUD 操作"""

    def __init__(self):
        super().__init__(PFCSessionModel)

    async def get_by_user_id(self, user_id: str) -> PFCSessionModel | None:
        """根据用户 ID 获取会话"""
        return await self.get_by(user_id=user_id, use_cache=False)

    async def get_waiting_sessions(self) -> list[PFCSessionModel]:
        """获取所有等待状态的会话"""
        return await self.get_multi(state="waiting", limit=1000, use_cache=False)

    async def delete_by_user_id(self, user_id: str) -> bool:
        """根据用户 ID 删除会话"""
        async with get_db_session() as session:
            stmt = delete(PFCSessionModel).where(PFCSessionModel.user_id == user_id)
            result = await session.execute(stmt)
            return result.rowcount > 0  # type: ignore


class PFCChatHistoryCRUD(CRUDBase[PFCChatHistory]):
    """PFC 聊天历史 CRUD 操作"""

    def __init__(self):
        super().__init__(PFCChatHistory)

    async def get_history_by_user(
        self,
        user_id: str,
        limit: int = 100,
    ) -> list[PFCChatHistory]:
        """获取用户的聊天历史"""
        async with get_db_session() as session:
            stmt = (
                select(PFCChatHistory)
                .where(PFCChatHistory.user_id == user_id)
                .order_by(PFCChatHistory.message_time.desc())
                .limit(limit)
            )
            result = await session.execute(stmt)
            # 返回时反转顺序，使最早的消息在前
            return list(reversed(result.scalars().all()))

    async def add_message(
        self,
        user_id: str,
        message_type: str,
        content: str,
        sender_name: str | None = None,
        sender_id: str | None = None,
        message_time: float | None = None,
    ) -> PFCChatHistory:
        """添加聊天消息"""
        msg_time = message_time or time.time()
        return await self.create({
            "user_id": user_id,
            "message_type": message_type,
            "content": content,
            "sender_name": sender_name,
            "sender_id": sender_id,
            "message_time": msg_time,
            "created_at": time.time(),
        })

    async def clear_history(self, user_id: str) -> int:
        """清除用户的聊天历史"""
        async with get_db_session() as session:
            stmt = delete(PFCChatHistory).where(PFCChatHistory.user_id == user_id)
            result = await session.execute(stmt)
            return result.rowcount  # type: ignore

    async def trim_history(self, user_id: str, max_count: int = 100) -> int:
        """裁剪用户的聊天历史，保留最近的 max_count 条"""
        async with get_db_session() as session:
            # 获取需要保留的消息的最小 ID
            subquery = (
                select(PFCChatHistory.id)
                .where(PFCChatHistory.user_id == user_id)
                .order_by(PFCChatHistory.message_time.desc())
                .limit(max_count)
            )
            result = await session.execute(subquery)
            keep_ids = [row[0] for row in result.fetchall()]

            if not keep_ids:
                return 0

            # 删除不在保留列表中的消息
            stmt = delete(PFCChatHistory).where(
                PFCChatHistory.user_id == user_id,
                PFCChatHistory.id.notin_(keep_ids),
            )
            result = await session.execute(stmt)
            return result.rowcount  # type: ignore


class DatabaseSessionStorage:
    """数据库会话存储
    
    提供与 JSON 文件存储相同的接口，但使用数据库作为后端。
    """

    def __init__(self):
        self._session_crud = PFCSessionCRUD()
        self._history_crud = PFCChatHistoryCRUD()

    async def load_session(self, user_id: str) -> dict | None:
        """从数据库加载会话数据"""
        db_session = await self._session_crud.get_by_user_id(user_id)
        if db_session is None:
            return None

        # 转换为字典格式
        try:
            conversation_info = json.loads(db_session.conversation_info_json or "{}")
        except json.JSONDecodeError:
            conversation_info = {}

        try:
            observation_info = json.loads(db_session.observation_info_json or "{}")
        except json.JSONDecodeError:
            observation_info = {}

        # 从数据库加载聊天历史
        history_records = await self._history_crud.get_history_by_user(user_id)
        chat_history = []
        for record in history_records:
            msg_dict = {
                "type": record.message_type,
                "content": record.content,
                "time": record.message_time,
            }
            if record.sender_name:
                msg_dict["user_name"] = record.sender_name
            if record.sender_id:
                msg_dict["user_id"] = record.sender_id
            chat_history.append(msg_dict)

        # 更新 observation_info 中的聊天历史
        observation_info["chat_history"] = chat_history
        observation_info["chat_history_count"] = len(chat_history)

        return {
            "user_id": db_session.user_id,
            "stream_id": db_session.stream_id,
            "state": db_session.state,
            "should_continue": db_session.should_continue,
            "ignore_until_timestamp": db_session.ignore_until_timestamp,
            "conversation_info": conversation_info,
            "observation_info": observation_info,
            "waiting_config": {
                "max_wait_seconds": db_session.waiting_max_seconds,
                "started_at": db_session.waiting_started_at,
            },
            "created_at": db_session.created_at,
            "last_activity_at": db_session.last_activity_at,
            "total_interactions": db_session.total_interactions,
            "last_proactive_at": db_session.last_proactive_at,
            "consecutive_timeout_count": db_session.consecutive_timeout_count,
            "last_user_message_at": db_session.last_user_message_at,
        }

    async def save_session(self, session: "PFCSession") -> bool:
        """保存会话到数据库"""
        try:
            # 准备数据
            conversation_info_json = json.dumps(
                session.conversation_info.to_dict(),
                ensure_ascii=False,
            )

            # 观察信息不包含聊天历史（聊天历史单独存储）
            obs_dict = session.observation_info.to_dict()
            obs_dict.pop("chat_history", None)
            obs_dict.pop("chat_history_str", None)
            observation_info_json = json.dumps(obs_dict, ensure_ascii=False)

            session_data = {
                "user_id": session.user_id,
                "stream_id": session.stream_id,
                "state": str(session.state),
                "should_continue": session.should_continue,
                "ignore_until_timestamp": session.ignore_until_timestamp,
                "conversation_info_json": conversation_info_json,
                "observation_info_json": observation_info_json,
                "waiting_max_seconds": session.waiting_config.max_wait_seconds,
                "waiting_started_at": session.waiting_config.started_at,
                "created_at": session.created_at,
                "last_activity_at": session.last_activity_at,
                "total_interactions": session.total_interactions,
                "last_proactive_at": session.last_proactive_at,
                "consecutive_timeout_count": session.consecutive_timeout_count,
                "last_user_message_at": session.last_user_message_at,
            }

            # 检查是否存在
            existing = await self._session_crud.get_by_user_id(session.user_id)
            if existing:
                # 更新
                await self._session_crud.update(existing.id, session_data)
            else:
                # 创建
                await self._session_crud.create(session_data)

            # 保存聊天历史（增量保存）
            await self._save_chat_history(session)

            return True
        except Exception as e:
            logger.error(f"保存会话到数据库失败 {session.user_id}: {e}")
            return False

    async def _save_chat_history(self, session: "PFCSession") -> None:
        """保存聊天历史到数据库"""
        # 获取数据库中已有的最新消息时间
        existing_history = await self._history_crud.get_history_by_user(
            session.user_id, limit=1
        )
        last_saved_time = 0.0
        if existing_history:
            last_saved_time = existing_history[-1].message_time

        # 只保存新消息
        for msg in session.observation_info.chat_history:
            msg_time = msg.get("time", 0)
            if msg_time > last_saved_time:
                await self._history_crud.add_message(
                    user_id=session.user_id,
                    message_type=msg.get("type", "unknown"),
                    content=msg.get("content", ""),
                    sender_name=msg.get("user_name"),
                    sender_id=msg.get("user_id"),
                    message_time=msg_time,
                )

        # 裁剪历史
        await self._history_crud.trim_history(session.user_id, max_count=100)

    async def delete_session(self, user_id: str) -> bool:
        """删除会话"""
        try:
            await self._session_crud.delete_by_user_id(user_id)
            await self._history_crud.clear_history(user_id)
            return True
        except Exception as e:
            logger.error(f"删除会话失败 {user_id}: {e}")
            return False

    async def get_waiting_sessions_data(self) -> list[dict]:
        """获取所有等待状态的会话数据"""
        db_sessions = await self._session_crud.get_waiting_sessions()
        result = []
        for db_session in db_sessions:
            data = await self.load_session(db_session.user_id)
            if data:
                result.append(data)
        return result


# 全局单例
_db_storage: DatabaseSessionStorage | None = None


def get_db_storage() -> DatabaseSessionStorage:
    """获取数据库存储单例"""
    global _db_storage
    if _db_storage is None:
        _db_storage = DatabaseSessionStorage()
    return _db_storage