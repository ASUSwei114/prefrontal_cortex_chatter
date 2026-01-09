"""
PFC - 会话管理

================================================================================
版权声明 (Copyright Notice)
================================================================================

原始代码来源: MaiM-with-u (https://github.com/MaiM-with-u/MaiBot)
原始版本: 0.6.3-fix4
原始代码路径: src/plugins/PFC/
原始许可证: GNU General Public License v3.0

本文件由 ASUSwei114 (https://github.com/ASUSwei114) 于 2024年12月 修改移植至 MoFox_Bot 项目。

主要修改内容:
- 重构会话管理器架构
- 添加会话持久化功能
- 添加主动思考触发检测

本项目遵循 GNU General Public License v3.0 许可证。
详见 LICENSE 文件。

================================================================================

管理私聊会话状态：
- PFCSession: 单个会话
- SessionManager: 会话管理器
"""

import asyncio
import json
import os
import time
from pathlib import Path
from typing import Optional

from src.common.logger import get_logger

from .models import (
    ConversationInfo,
    ConversationState,
    ObservationInfo,
    WaitingConfig,
)

logger = get_logger("pfc_session")


class PFCSession:
    """
    PFC 会话

    为每个私聊用户维护一个独立的会话，包含：
    - 基本信息（user_id, stream_id）
    - 对话状态
    - 对话信息（目标、行动历史等）
    - 观察信息（聊天历史等）
    - 等待配置
    """

    MAX_HISTORY_SIZE = 100

    def __init__(
        self,
        user_id: str,
        stream_id: str,
    ):
        self.user_id = user_id
        self.stream_id = stream_id

        # 状态
        self._state: ConversationState = ConversationState.INIT
        self.should_continue: bool = True
        self.ignore_until_timestamp: Optional[float] = None

        # 对话信息
        self.conversation_info: ConversationInfo = ConversationInfo()

        # 观察信息
        self.observation_info: ObservationInfo = ObservationInfo()

        # 等待配置
        self.waiting_config: WaitingConfig = WaitingConfig()

        # 时间戳
        self.created_at: float = time.time()
        self.last_activity_at: float = time.time()

        # 统计
        self.total_interactions: int = 0

        # 上次主动思考时间
        self.last_proactive_at: float | None = None

        # 连续超时计数
        self.consecutive_timeout_count: int = 0

        # 用户最后发消息的时间
        self.last_user_message_at: float | None = None
        
        # 发言时间跟踪（与原版 ChatObserver 保持一致）
        self.last_bot_speak_time: float | None = None  # 机器人上次发言时间
        self.last_user_speak_time: float | None = None  # 用户上次发言时间

        # 生成的回复（临时存储）
        self.generated_reply: str = ""

        # 标记是否已从数据库加载历史（用于重启后刷新）
        self._history_loaded_from_db: bool = False

    @property
    def state(self) -> ConversationState:
        return self._state

    @state.setter
    def state(self, value: ConversationState) -> None:
        old_state = self._state
        self._state = value
        if old_state != value:
            logger.debug(f"Session {self.user_id} 状态变更: {old_state} → {value}")

    def update_activity(self) -> None:
        """更新活动时间"""
        self.last_activity_at = time.time()

    def add_user_message(
        self,
        content: str,
        user_name: str,
        user_id: str,
        timestamp: float | None = None,
    ) -> None:
        """添加用户消息"""
        msg_time = timestamp or time.time()

        msg_dict = {
            "type": "user_message",
            "content": content,
            "user_name": user_name,
            "user_id": user_id,
            "time": msg_time,
        }

        # 添加到未处理消息
        self.observation_info.unprocessed_messages.append(msg_dict)
        self.observation_info.new_messages_count += 1
        self.observation_info.last_message_time = msg_time
        self.observation_info.last_message_sender = user_id
        self.observation_info.last_message_content = content

        # 重置连续超时计数
        self.consecutive_timeout_count = 0
        self.last_user_message_at = msg_time
        
        # 更新用户发言时间（与原版 ChatObserver 保持一致）
        self.last_user_speak_time = msg_time
        
        # 清除超时相关的目标（用户发消息了，说明对话还在继续）
        self._clear_timeout_goals()
        
        self.update_activity()
    
    def _clear_timeout_goals(self) -> None:
        """
        清除超时相关的目标
        
        当用户发送新消息时，应该清除之前因等待超时而添加的目标，
        避免 AI 错误地认为"已经等待了X分钟"。
        
        超时目标的特征是包含"分钟，思考接下来要做什么"或类似的文本。
        """
        if not self.conversation_info.goal_list:
            return
        
        # 过滤掉超时相关的目标
        timeout_keywords = [
            "分钟，思考接下来要做什么",
            "分钟，注意可能在对方看来聊天已经结束",
            "对方似乎话说一半突然消失了",
        ]
        
        original_count = len(self.conversation_info.goal_list)
        filtered_goals = []
        
        for goal_item in self.conversation_info.goal_list:
            if isinstance(goal_item, dict):
                goal_text = goal_item.get("goal", "")
                if isinstance(goal_text, str):
                    # 检查是否是超时目标
                    is_timeout_goal = any(
                        keyword in goal_text for keyword in timeout_keywords
                    )
                    if not is_timeout_goal:
                        filtered_goals.append(goal_item)
                else:
                    filtered_goals.append(goal_item)
            else:
                filtered_goals.append(goal_item)
        
        removed_count = original_count - len(filtered_goals)
        if removed_count > 0:
            self.conversation_info.goal_list = filtered_goals
            logger.debug(
                f"Session {self.user_id} 清除了 {removed_count} 个超时目标"
            )

    def add_bot_message(
        self,
        content: str,
        timestamp: float | None = None,
    ) -> None:
        """添加 Bot 消息到历史"""
        from src.config.config import global_config
        
        msg_time = timestamp or time.time()

        msg_dict = {
            "type": "bot_message",
            "content": content,
            "time": msg_time,
        }

        self.observation_info.chat_history.append(msg_dict)
        self.observation_info.chat_history_count += 1
        
        # 更新机器人发言时间（与原版 ChatObserver 保持一致）
        self.last_bot_speak_time = msg_time
        
        # 同时更新 chat_history_str，使用相对时间格式
        bot_name = global_config.bot.nickname if global_config else "Bot"
        readable_time = self._translate_timestamp(msg_time)
        
        # 格式化内容
        stripped_content = content.strip()
        if stripped_content.endswith("。"):
            stripped_content = stripped_content[:-1]
        
        bot_block = f"{readable_time} {bot_name}(你) 说:\n{stripped_content};\n"
        
        if self.observation_info.chat_history_str:
            self.observation_info.chat_history_str += "\n" + bot_block
        else:
            self.observation_info.chat_history_str = bot_block
        
        self._trim_history()
        self.update_activity()
    
    def _translate_timestamp(self, timestamp: float) -> str:
        """将时间戳转换为相对时间格式"""
        now = time.time()
        diff = now - timestamp
        
        if diff < 20:
            return "刚刚"
        elif diff < 60:
            return f"{int(diff)}秒前"
        elif diff < 3600:
            return f"{int(diff / 60)}分钟前"
        elif diff < 86400:
            return f"{int(diff / 3600)}小时前"
        elif diff < 86400 * 2:
            return f"{int(diff / 86400)}天前"
        else:
            return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(timestamp))
    
    def get_time_info(self) -> str:
        """
        获取时间信息文本
        
        与原版 MaiM-with-u 的 ChatObserver.get_time_info() 保持一致，
        返回格式为：
        - "距离你上次发言已经过去了X秒"
        - "距离对方上次发言已经过去了X秒"
        
        Returns:
            时间信息文本
        """
        current_time = time.time()
        time_info = ""
        
        if self.last_bot_speak_time:
            bot_speak_ago = current_time - self.last_bot_speak_time
            time_info += f"\n距离你上次发言已经过去了{int(bot_speak_ago)}秒"
        
        if self.last_user_speak_time:
            user_speak_ago = current_time - self.last_user_speak_time
            time_info += f"\n距离对方上次发言已经过去了{int(user_speak_ago)}秒"
        
        return time_info

    def _trim_history(self) -> None:
        """裁剪历史记录"""
        if len(self.observation_info.chat_history) > self.MAX_HISTORY_SIZE:
            self.observation_info.chat_history = self.observation_info.chat_history[-self.MAX_HISTORY_SIZE:]
            self.observation_info.chat_history_count = len(self.observation_info.chat_history)

    async def clear_unprocessed_messages(self) -> None:
        """清理未处理消息"""
        await self.observation_info.clear_unprocessed_messages()
        self._trim_history()

    def start_waiting(self, max_wait_seconds: int = 300) -> None:
        """开始等待"""
        if max_wait_seconds <= 0:
            self.state = ConversationState.ANALYZING
            self.waiting_config.reset()
            return

        self.state = ConversationState.WAITING
        self.waiting_config = WaitingConfig(
            max_wait_seconds=max_wait_seconds,
            started_at=time.time(),
        )
        logger.debug(f"Session {self.user_id} 开始等待: max_wait={max_wait_seconds}s")

    def end_waiting(self) -> None:
        """结束等待"""
        self.state = ConversationState.ANALYZING
        self.waiting_config.reset()
        self.update_activity()

    def is_waiting_timeout(self) -> bool:
        """检查是否等待超时"""
        return self.waiting_config.is_timeout()

    def should_proactive_think(self, config) -> bool:
        """检查是否应该触发主动思考"""
        import random
        from datetime import datetime
        
        proactive_cfg = config.proactive
        
        # 检查是否启用
        if not proactive_cfg.enabled:
            return False
        
        # 检查是否在安静时间
        try:
            now = datetime.now()
            quiet_start = datetime.strptime(proactive_cfg.quiet_hours_start, "%H:%M").time()
            quiet_end = datetime.strptime(proactive_cfg.quiet_hours_end, "%H:%M").time()
            current_time = now.time()
            
            if quiet_start <= quiet_end:
                if quiet_start <= current_time <= quiet_end:
                    return False
            else:
                if current_time >= quiet_start or current_time <= quiet_end:
                    return False
        except Exception:
            pass
        
        # 检查上次主动思考时间
        if self.last_proactive_at:
            elapsed = time.time() - self.last_proactive_at
            if elapsed < proactive_cfg.min_interval_between_proactive:
                return False
        
        # 检查沉默时间
        if self.last_user_message_at:
            silence_time = time.time() - self.last_user_message_at
            if silence_time < proactive_cfg.silence_threshold_seconds:
                return False
        else:
            return False
        
        # 概率触发
        if random.random() > proactive_cfg.trigger_probability:
            return False
        
        return True

    def new_message_after(self, timestamp: float) -> bool:
        """检查是否有指定时间之后的新消息"""
        if not self.observation_info.unprocessed_messages:
            return False
        for msg in self.observation_info.unprocessed_messages:
            if msg.get("time", 0) > timestamp:
                return True
        return False

    def to_dict(self) -> dict:
        """转换为字典（用于持久化）"""
        return {
            "user_id": self.user_id,
            "stream_id": self.stream_id,
            "state": str(self.state),
            "should_continue": self.should_continue,
            "ignore_until_timestamp": self.ignore_until_timestamp,
            "conversation_info": self.conversation_info.to_dict(),
            "observation_info": self.observation_info.to_dict(),
            "waiting_config": {
                "max_wait_seconds": self.waiting_config.max_wait_seconds,
                "started_at": self.waiting_config.started_at,
            },
            "created_at": self.created_at,
            "last_activity_at": self.last_activity_at,
            "total_interactions": self.total_interactions,
            "last_proactive_at": self.last_proactive_at,
            "consecutive_timeout_count": self.consecutive_timeout_count,
            "last_user_message_at": self.last_user_message_at,
            "last_bot_speak_time": self.last_bot_speak_time,
            "last_user_speak_time": self.last_user_speak_time,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "PFCSession":
        """从字典创建会话"""
        session = cls(
            user_id=data.get("user_id", ""),
            stream_id=data.get("stream_id", ""),
        )

        # 状态
        state_str = data.get("state", "init")
        try:
            session._state = ConversationState(state_str)
        except ValueError:
            session._state = ConversationState.INIT

        session.should_continue = data.get("should_continue", True)
        session.ignore_until_timestamp = data.get("ignore_until_timestamp")

        # 对话信息
        conv_data = data.get("conversation_info", {})
        session.conversation_info = ConversationInfo.from_dict(conv_data)

        # 观察信息
        obs_data = data.get("observation_info", {})
        session.observation_info = ObservationInfo.from_dict(obs_data)

        # 等待配置
        wait_data = data.get("waiting_config", {})
        session.waiting_config = WaitingConfig(
            max_wait_seconds=wait_data.get("max_wait_seconds", 0),
            started_at=wait_data.get("started_at", 0.0),
        )

        # 时间戳
        session.created_at = data.get("created_at", time.time())
        session.last_activity_at = data.get("last_activity_at", time.time())
        session.total_interactions = data.get("total_interactions", 0)
        session.last_proactive_at = data.get("last_proactive_at")
        session.consecutive_timeout_count = data.get("consecutive_timeout_count", 0)
        session.last_user_message_at = data.get("last_user_message_at")
        session.last_bot_speak_time = data.get("last_bot_speak_time")
        session.last_user_speak_time = data.get("last_user_speak_time")

        return session


class SessionManager:
    """
    会话管理器

    负责会话的创建、获取、保存和清理。
    支持两种存储后端：
    - file: JSON 文件存储（默认）
    - database: 数据库存储（支持 SQLite/PostgreSQL）
    """

    _instance: Optional["SessionManager"] = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(
        self,
        data_dir: str = "data/prefrontal_cortex_chatter/sessions",
        max_session_age_days: int = 30,
        storage_backend: str = "file",
    ):
        if hasattr(self, "_initialized") and self._initialized:
            return

        self._initialized = True
        self.data_dir = Path(data_dir)
        self.max_session_age_days = max_session_age_days
        self.storage_backend = storage_backend

        # 内存缓存
        self._sessions: dict[str, PFCSession] = {}
        self._locks: dict[str, asyncio.Lock] = {}

        # 数据库存储后端（延迟初始化）
        self._db_storage = None

        # 根据存储后端初始化
        if storage_backend == "file":
            # 确保数据目录存在
            self.data_dir.mkdir(parents=True, exist_ok=True)
            logger.info(f"SessionManager 初始化完成 (file 后端): {self.data_dir}")
        elif storage_backend == "database":
            logger.info("SessionManager 初始化完成 (database 后端)")
        else:
            logger.warning(f"未知的存储后端 '{storage_backend}'，使用 file 后端")
            self.storage_backend = "file"
            self.data_dir.mkdir(parents=True, exist_ok=True)

    def _get_db_storage(self):
        """获取数据库存储后端（延迟初始化）"""
        if self._db_storage is None:
            from .db_storage import get_db_storage
            self._db_storage = get_db_storage()
        return self._db_storage

    def _get_lock(self, user_id: str) -> asyncio.Lock:
        """获取用户级别的锁"""
        if user_id not in self._locks:
            self._locks[user_id] = asyncio.Lock()
        return self._locks[user_id]

    def _get_file_path(self, user_id: str) -> Path:
        """获取会话文件路径"""
        safe_id = "".join(c if c.isalnum() or c in "-_" else "_" for c in user_id)
        return self.data_dir / f"{safe_id}.json"

    async def get_session(self, user_id: str, stream_id: str) -> PFCSession:
        """获取或创建会话"""
        async with self._get_lock(user_id):
            # 检查内存缓存
            if user_id in self._sessions:
                session = self._sessions[user_id]
                session.stream_id = stream_id
                return session

            # 根据存储后端加载
            if self.storage_backend == "database":
                session = await self._load_from_database(user_id)
            else:
                session = await self._load_from_file(user_id)

            if session:
                session.stream_id = stream_id
                self._sessions[user_id] = session
                return session

            # 创建新会话
            session = PFCSession(user_id=user_id, stream_id=stream_id)
            self._sessions[user_id] = session
            logger.info(f"创建新会话: {user_id}")
            return session

    async def _load_from_file(self, user_id: str) -> PFCSession | None:
        """从文件加载会话"""
        file_path = self._get_file_path(user_id)
        if not file_path.exists():
            return None

        try:
            with open(file_path, encoding="utf-8") as f:
                data = json.load(f)
            session = PFCSession.from_dict(data)
            logger.debug(f"从文件加载会话: {user_id}")
            return session
        except Exception as e:
            logger.error(f"加载会话失败 {user_id}: {e}")
            return None

    async def _load_from_database(self, user_id: str) -> PFCSession | None:
        """从数据库加载会话"""
        try:
            db_storage = self._get_db_storage()
            data = await db_storage.load_session(user_id)
            if data:
                session = PFCSession.from_dict(data)
                logger.debug(f"从数据库加载会话: {user_id}")
                return session
            return None
        except Exception as e:
            logger.error(f"从数据库加载会话失败 {user_id}: {e}")
            return None

    async def save_session(self, user_id: str) -> bool:
        """保存会话"""
        async with self._get_lock(user_id):
            if user_id not in self._sessions:
                return False

            session = self._sessions[user_id]

            if self.storage_backend == "database":
                return await self._save_to_database(session)
            else:
                return await self._save_to_file(session)

    async def _save_to_file(self, session: PFCSession) -> bool:
        """保存会话到文件"""
        file_path = self._get_file_path(session.user_id)

        try:
            data = session.to_dict()
            temp_path = file_path.with_suffix(".json.tmp")

            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

            os.replace(temp_path, file_path)
            return True
        except Exception as e:
            logger.error(f"保存会话到文件失败 {session.user_id}: {e}")
            return False

    async def _save_to_database(self, session: PFCSession) -> bool:
        """保存会话到数据库"""
        try:
            db_storage = self._get_db_storage()
            return await db_storage.save_session(session)
        except Exception as e:
            logger.error(f"保存会话到数据库失败 {session.user_id}: {e}")
            return False

    async def save_all(self) -> int:
        """保存所有会话"""
        count = 0
        for user_id in list(self._sessions.keys()):
            if await self.save_session(user_id):
                count += 1
        return count

    async def get_waiting_sessions(self) -> list[PFCSession]:
        """获取所有处于等待状态的会话"""
        return [s for s in self._sessions.values() if s.state == ConversationState.WAITING]

    async def get_all_sessions(self) -> list[PFCSession]:
        """获取所有会话"""
        return list(self._sessions.values())

    def get_session_sync(self, user_id: str) -> PFCSession | None:
        """同步获取会话（仅从内存）"""
        return self._sessions.get(user_id)


# 全局单例
_session_manager: SessionManager | None = None


def get_session_manager() -> SessionManager:
    """获取全局会话管理器
    
    根据配置自动选择存储后端：
    - file: JSON 文件存储（默认）
    - database: 数据库存储（使用 MoFox 数据库，支持 SQLite/PostgreSQL）
    """
    global _session_manager
    if _session_manager is None:
        from .plugin import get_config
        config = get_config()
        
        storage_backend = config.session.storage_backend
        session_dir = f"data/{config.session.session_dir}"
        
        _session_manager = SessionManager(
            data_dir=session_dir,
            storage_backend=storage_backend,
        )
    return _session_manager