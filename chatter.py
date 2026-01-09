"""
PFC - Chatter 主类

================================================================================
版权声明 (Copyright Notice)
================================================================================

原始代码来源: MaiM-with-u (https://github.com/MaiM-with-u/MaiBot)
原始版本: 0.6.3-fix4
原始代码路径: src/plugins/PFC/
原始许可证: GNU General Public License v3.0

本文件由 ASUSwei114 (https://github.com/ASUSwei114) 于 2024年12月 修改移植至 MoFox_Bot 项目。

主要修改内容:
- 适配 MoFox_Bot 插件系统架构
- 重构消息处理逻辑
- 添加会话循环管理
- 添加初始历史加载功能

本项目遵循 GNU General Public License v3.0 许可证。
详见 LICENSE 文件。

================================================================================

核心设计：
- 目标驱动的对话管理
- 多种行动类型（回复、等待、倾听、获取知识等）
- 回复质量检查
"""

import asyncio
import time
from typing import TYPE_CHECKING, Any, ClassVar

from src.chat.planner_actions.action_manager import ChatterActionManager
from src.common.data_models.message_manager_data_model import StreamContext
from src.common.logger import get_logger
from src.plugin_system.base.base_chatter import BaseChatter
from src.plugin_system.base.component_types import ChatType

from .models import ConversationState
from .session import PFCSession, get_session_manager

if TYPE_CHECKING:
    pass

logger = get_logger("pfc_chatter")


class PrefrontalCortexChatter(BaseChatter):
    """
    Prefrontal Cortex Chatter - 目标驱动的私聊聊天器

    从 MaiM-with-u 0.6.3-fix4 移植

    核心特性：
    - 目标驱动的对话管理
    - 多种行动类型
    - 回复质量检查
    - 主动思考能力
    """

    chatter_name: str = "PrefrontalCortexChatter"
    chatter_description: str = "目标驱动的私聊聊天器 - 从 MaiM-with-u 移植"
    chat_types: ClassVar[list[ChatType]] = [ChatType.PRIVATE]

    def __init__(
        self,
        stream_id: str,
        action_manager: "ChatterActionManager",
        plugin_config: dict | None = None,
    ):
        super().__init__(stream_id, action_manager, plugin_config)

        # 核心组件
        self.session_manager = get_session_manager()

        # 延迟导入配置以避免循环导入
        from .plugin import get_config
        self._config = get_config()

        # 并发控制
        self._lock = asyncio.Lock()
        self._processing = False

        # 统计
        self._stats: dict[str, Any] = {
            "messages_processed": 0,
            "successful_responses": 0,
            "failed_responses": 0,
        }

        logger.info(f"[PFC] 初始化完成: stream_id={stream_id}")

    async def execute(self, context: StreamContext) -> dict:
        """
        执行聊天处理 - 复刻原版PFC的持续循环行为

        流程：
        1. 获取 Session
        2. 获取未读消息
        3. 记录用户消息
        4. 启动或唤醒会话循环（持续运行的后台任务）
        """
        async with self._lock:
            self._processing = True

            try:
                # 1. 获取未读消息
                unread_messages = context.get_unread_messages()
                if not unread_messages:
                    return self._build_result(success=True, message="no_unread_messages")

                # 2. 取最后一条消息作为主消息
                target_message = unread_messages[-1]
                user_info = target_message.user_info

                if not user_info:
                    return self._build_result(success=False, message="no_user_info")

                user_id = str(user_info.user_id)
                user_name = user_info.user_nickname or user_id

                # 3. 获取或创建 Session
                session = await self.session_manager.get_session(user_id, self.stream_id)

                # 立即更新活动时间
                session.update_activity()

                # 3.5 如果本次运行还没有从数据库加载过历史，则加载（确保包含重启前的消息）
                if not session._history_loaded_from_db:
                    await self._load_initial_history(session, user_name)
                    session._history_loaded_from_db = True

                # 4. 检查是否在忽略期
                if session.ignore_until_timestamp and time.time() < session.ignore_until_timestamp:
                    logger.info(f"[PFC] 用户 {user_id} 在忽略期内，跳过处理")
                    return self._build_result(success=True, message="ignored")

                # 5. 结束等待状态（如果有新消息）
                if session.state == ConversationState.WAITING:
                    session.end_waiting()
                    await self.session_manager.save_session(user_id)

                # 6. 记录用户消息
                for msg in unread_messages:
                    msg_content = msg.processed_plain_text or msg.display_message or ""
                    msg_user_name = msg.user_info.user_nickname if msg.user_info else user_name
                    msg_user_id = str(msg.user_info.user_id) if msg.user_info else user_id

                    session.add_user_message(
                        content=msg_content,
                        user_name=msg_user_name,
                        user_id=msg_user_id,
                        timestamp=msg.time,
                    )

                # 7. 构建聊天历史字符串
                await self._build_chat_history_str(session, user_name)

                # 8. 启动或获取会话循环（复刻原版PFC的持续循环）
                from .conversation_loop import get_loop_manager
                
                loop_manager = get_loop_manager()
                
                # 确保会话应该继续
                session.should_continue = True
                
                # 获取或创建循环
                await loop_manager.get_or_create_loop(session, user_name)

                # 9. 标记消息为已读
                for msg in unread_messages:
                    context.mark_message_as_read(str(msg.message_id))

                # 10. 保存 Session
                await self.session_manager.save_session(user_id)

                # 11. 更新统计
                self._stats["messages_processed"] += len(unread_messages)

                logger.info(
                    f"[PFC] 消息已记录，会话循环运行中: user={user_name}, "
                    f"new_messages={len(unread_messages)}"
                )

                return self._build_result(
                    success=True,
                    message="loop_running",
                    user_id=user_id,
                    user_name=user_name,
                    new_messages=len(unread_messages),
                )

            except Exception as e:
                self._stats["failed_responses"] += 1
                logger.error(f"[PFC] 处理失败: {e}")
                import traceback
                traceback.print_exc()
                return self._build_result(success=False, message=str(e), error=True)

            finally:
                self._processing = False

    async def _load_initial_history(self, session: PFCSession, user_name: str) -> None:
        """从数据库加载初始聊天历史（复刻原版PFC的初始化逻辑）"""
        try:
            from src.chat.utils.chat_message_builder import (
                build_readable_messages,
                get_raw_msg_before_timestamp_with_chat,
            )
            from src.config.config import global_config
            
            bot_qq = str(global_config.bot.qq_account) if global_config else ""
            
            # 从配置获取加载条数
            history_limit = self._config.session.initial_history_limit
            logger.info(f"[PFC] 为 {self.stream_id} 加载初始聊天记录 (limit={history_limit})...")
            
            # 从数据库加载消息
            initial_messages = await get_raw_msg_before_timestamp_with_chat(
                chat_id=self.stream_id,
                timestamp=time.time(),
                limit=history_limit,
            )
            
            if initial_messages:
                # 构建可读的聊天记录字符串
                chat_history_str = await build_readable_messages(
                    initial_messages,
                    replace_bot_name=True,
                    merge_messages=False,
                    timestamp_mode="relative",
                    read_mark=0.0,
                )
                
                # 转换为 PFC 内部格式并填充到 session
                # 清空旧的历史记录
                session.observation_info.chat_history = []
                
                for msg in initial_messages:
                    # 数据库返回的消息是扁平化的，user_id 直接在顶层
                    sender_id = str(msg.get("user_id", ""))
                    sender_name = msg.get("user_nickname", "") or msg.get("user_cardname", "") or user_name
                    content = msg.get("processed_plain_text", "") or msg.get("display_message", "")
                    msg_time = msg.get("time", 0)
                    
                    if sender_id == bot_qq:
                        # Bot 消息
                        session.observation_info.chat_history.append({
                            "type": "bot_message",
                            "content": content,
                            "time": msg_time,
                        })
                        # 更新机器人发言时间（与原版 ChatObserver 保持一致）
                        if msg_time and (session.last_bot_speak_time is None or msg_time > session.last_bot_speak_time):
                            session.last_bot_speak_time = msg_time
                    else:
                        # 用户消息
                        session.observation_info.chat_history.append({
                            "type": "user_message",
                            "content": content,
                            "user_name": sender_name,
                            "user_id": sender_id,
                            "time": msg_time,
                        })
                        # 更新用户发言时间（与原版 ChatObserver 保持一致）
                        if msg_time and (session.last_user_speak_time is None or msg_time > session.last_user_speak_time):
                            session.last_user_speak_time = msg_time
                
                session.observation_info.chat_history_str = chat_history_str + "\n"
                session.observation_info.chat_history_count = len(initial_messages)
                
                # 更新最后消息信息
                if initial_messages:
                    last_msg = initial_messages[-1]
                    session.observation_info.last_message_time = last_msg.get("time")
                    # 数据库返回的消息是扁平化的，user_id 直接在顶层
                    session.observation_info.last_message_sender = str(last_msg.get("user_id", ""))
                    session.observation_info.last_message_content = last_msg.get("processed_plain_text", "") or last_msg.get("display_message", "")
                
                logger.info(f"[PFC] 成功加载 {len(initial_messages)} 条初始聊天记录")
            else:
                logger.info("[PFC] 没有找到初始聊天记录")
                
        except Exception as e:
            logger.error(f"[PFC] 加载初始聊天记录时出错: {e}")
            import traceback
            traceback.print_exc()

    async def _build_chat_history_str(self, session: PFCSession, user_name: str) -> None:
        """
        构建聊天历史字符串
        
        使用相对时间格式（如"刚刚"、"5分钟前"），与原版 MaiM-with-u 保持一致，
        让 LLM 能够理解消息的时间上下文。
        """
        from .replyer import translate_timestamp_to_human_readable
        from src.config.config import global_config
        
        formatted_blocks = []
        bot_name = global_config.bot.nickname if global_config else "Bot"

        # 历史消息
        for msg in session.observation_info.chat_history[-30:]:
            msg_type = msg.get("type", "")
            content = msg.get("content", "")
            msg_time = msg.get("time", time.time())

            # 使用相对时间格式
            readable_time = translate_timestamp_to_human_readable(msg_time, mode="relative")

            if msg_type == "user_message":
                sender = msg.get("user_name", user_name)
                header = f"{readable_time} {sender} 说:"
            elif msg_type == "bot_message":
                header = f"{readable_time} {bot_name}(你) 说:"
            else:
                continue
            
            formatted_blocks.append(header)
            
            # 添加内容
            if content:
                stripped_content = content.strip()
                if stripped_content:
                    # 移除末尾句号，添加分号（模仿原版行为）
                    if stripped_content.endswith("。"):
                        stripped_content = stripped_content[:-1]
                    formatted_blocks.append(f"{stripped_content};")
            
            formatted_blocks.append("")  # 空行分隔

        session.observation_info.chat_history_str = "\n".join(formatted_blocks).strip()

    def _build_result(
        self,
        success: bool,
        message: str = "",
        error: bool = False,
        **kwargs,
    ) -> dict:
        """构建返回结果"""
        result = {
            "success": success,
            "stream_id": self.stream_id,
            "message": message,
            "error": error,
            "timestamp": time.time(),
        }
        result.update(kwargs)
        return result

    def get_stats(self) -> dict[str, Any]:
        """获取统计信息"""
        return self._stats.copy()

    @property
    def is_processing(self) -> bool:
        """是否正在处理"""
        return self._processing