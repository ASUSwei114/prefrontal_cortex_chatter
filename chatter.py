"""PFC - Chatter 主类 (移植自 MaiM-with-u 0.6.3-fix4, GPL-3.0)"""

import asyncio
import time
from typing import Any, ClassVar

from src.chat.planner_actions.action_manager import ChatterActionManager
from src.common.data_models.message_manager_data_model import StreamContext
from src.common.logger import get_logger
from src.plugin_system.base.base_chatter import BaseChatter
from src.plugin_system.base.component_types import ChatType

from .models import ConversationState
from .session import PFCSession, get_session_manager

logger = get_logger("pfc_chatter")


class PrefrontalCortexChatter(BaseChatter):
    """目标驱动的私聊聊天器"""

    chatter_name: str = "PrefrontalCortexChatter"
    chatter_description: str = "目标驱动的私聊聊天器"
    chat_types: ClassVar[list[ChatType]] = [ChatType.PRIVATE]

    def __init__(self, stream_id: str, action_manager: "ChatterActionManager", plugin_config: dict | None = None):
        super().__init__(stream_id, action_manager, plugin_config)
        self.session_manager = get_session_manager()
        from .plugin import get_config
        self._config = get_config()
        self._lock = asyncio.Lock()
        self._processing = False
        self._stats: dict[str, Any] = {"messages_processed": 0, "successful_responses": 0, "failed_responses": 0}
        logger.info(f"[PFC] 初始化完成: stream_id={stream_id}")

    async def execute(self, context: StreamContext) -> dict:
        """执行聊天处理"""
        async with self._lock:
            self._processing = True
            try:
                unread_messages = context.get_unread_messages()
                if not unread_messages:
                    return self._build_result(success=True, message="no_unread_messages")

                user_info = unread_messages[-1].user_info
                if not user_info:
                    return self._build_result(success=False, message="no_user_info")

                user_id, user_name = str(user_info.user_id), user_info.user_nickname or str(user_info.user_id)
                session = await self.session_manager.get_session(user_id, self.stream_id)
                session.update_activity()

                if not session._history_loaded_from_db:
                    await self._load_initial_history(session, user_name)
                    session._history_loaded_from_db = True

                if session.ignore_until_timestamp and time.time() < session.ignore_until_timestamp:
                    return self._build_result(success=True, message="ignored")

                if session.state == ConversationState.WAITING:
                    session.end_waiting()
                    await self.session_manager.save_session(user_id)

                for msg in unread_messages:
                    session.add_user_message(
                        content=msg.processed_plain_text or msg.display_message or "",
                        user_name=msg.user_info.user_nickname if msg.user_info else user_name,
                        user_id=str(msg.user_info.user_id) if msg.user_info else user_id,
                        timestamp=msg.time,
                    )

                await self._build_chat_history_str(session, user_name)
                from .conversation_loop import get_loop_manager
                session.should_continue = True
                await get_loop_manager().get_or_create_loop(session, user_name)

                for msg in unread_messages:
                    context.mark_message_as_read(str(msg.message_id))
                await self.session_manager.save_session(user_id)

                self._stats["messages_processed"] += len(unread_messages)
                return self._build_result(success=True, message="loop_running", user_id=user_id,
                                         user_name=user_name, new_messages=len(unread_messages))
            except Exception as e:
                self._stats["failed_responses"] += 1
                logger.error(f"[PFC] 处理失败: {e}")
                import traceback
                traceback.print_exc()
                return self._build_result(success=False, message=str(e), error=True)
            finally:
                self._processing = False

    async def _load_initial_history(self, session: PFCSession, user_name: str) -> None:
        """从数据库加载初始聊天历史"""
        try:
            from src.chat.utils.chat_message_builder import build_readable_messages, get_raw_msg_before_timestamp_with_chat
            from src.config.config import global_config

            bot_qq = str(global_config.bot.qq_account) if global_config else ""
            history_limit = self._config.session.initial_history_limit

            initial_messages = await get_raw_msg_before_timestamp_with_chat(
                chat_id=self.stream_id, timestamp=time.time(), limit=history_limit)

            if not initial_messages:
                return

            chat_history_str = await build_readable_messages(
                initial_messages, replace_bot_name=True, merge_messages=False, timestamp_mode="relative", read_mark=0.0)

            session.observation_info.chat_history = []
            for msg in initial_messages:
                sender_id = str(msg.get("user_id", ""))
                content = msg.get("processed_plain_text", "") or msg.get("display_message", "")
                msg_time = msg.get("time", 0)

                if sender_id == bot_qq:
                    session.observation_info.chat_history.append({"type": "bot_message", "content": content, "time": msg_time})
                    if msg_time and (session.last_bot_speak_time is None or msg_time > session.last_bot_speak_time):
                        session.last_bot_speak_time = msg_time
                else:
                    sender_name = msg.get("user_nickname", "") or msg.get("user_cardname", "") or user_name
                    session.observation_info.chat_history.append({
                        "type": "user_message", "content": content, "user_name": sender_name, "user_id": sender_id, "time": msg_time})
                    if msg_time and (session.last_user_speak_time is None or msg_time > session.last_user_speak_time):
                        session.last_user_speak_time = msg_time

            session.observation_info.chat_history_str = chat_history_str + "\n"
            session.observation_info.chat_history_count = len(initial_messages)

            if initial_messages:
                last_msg = initial_messages[-1]
                session.observation_info.last_message_time = last_msg.get("time")
                session.observation_info.last_message_sender = str(last_msg.get("user_id", ""))
                session.observation_info.last_message_content = last_msg.get("processed_plain_text", "") or last_msg.get("display_message", "")

            logger.info(f"[PFC] 成功加载 {len(initial_messages)} 条初始聊天记录")
        except Exception as e:
            logger.error(f"[PFC] 加载初始聊天记录时出错: {e}")

    async def _build_chat_history_str(self, session: PFCSession, user_name: str) -> None:
        """构建聊天历史字符串"""
        from .shared import translate_timestamp
        from src.config.config import global_config

        bot_name = global_config.bot.nickname if global_config else "Bot"
        formatted_blocks = []

        for msg in session.observation_info.chat_history[-30:]:
            msg_type = msg.get("type", "")
            if msg_type not in ["user_message", "bot_message"]:
                continue
            content = msg.get("content", "").strip()
            if not content:
                continue
            readable_time = translate_timestamp(msg.get("time", time.time()), mode="relative")
            sender = msg.get("user_name", user_name) if msg_type == "user_message" else f"{bot_name}(你)"
            if content.endswith("。"):
                content = content[:-1]
            formatted_blocks.extend([f"{readable_time} {sender} 说:", f"{content};", ""])

        session.observation_info.chat_history_str = "\n".join(formatted_blocks).strip()

    def _build_result(self, success: bool, message: str = "", error: bool = False, **kwargs) -> dict:
        return {"success": success, "stream_id": self.stream_id, "message": message, "error": error, "timestamp": time.time(), **kwargs}

    def get_stats(self) -> dict[str, Any]:
        return self._stats.copy()

    @property
    def is_processing(self) -> bool:
        return self._processing