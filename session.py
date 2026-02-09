"""PFC 会话管理 - 管理私聊会话状态 (GPL-3.0)"""

import asyncio
import time
from typing import Optional

from src.common.logger import get_logger
from .models import ConversationInfo, ConversationState, ObservationInfo, WaitingConfig
from .shared import translate_timestamp

logger = get_logger("pfc_session")


class PFCSession:
    """PFC 会话"""
    MAX_HISTORY_SIZE = 100

    def __init__(self, user_id: str, stream_id: str):
        self.user_id = user_id
        self.stream_id = stream_id
        self._state: ConversationState = ConversationState.INIT
        self.should_continue: bool = True
        self.ignore_until_timestamp: Optional[float] = None
        self.conversation_info: ConversationInfo = ConversationInfo()
        self.observation_info: ObservationInfo = ObservationInfo()
        self.waiting_config: WaitingConfig = WaitingConfig()
        self.created_at: float = time.time()
        self.last_activity_at: float = time.time()
        self.total_interactions: int = 0
        self.last_proactive_at: float | None = None
        self.consecutive_timeout_count: int = 0
        self.last_user_message_at: float | None = None
        self.last_bot_speak_time: float | None = None
        self.last_user_speak_time: float | None = None
        self.generated_reply: str = ""
        self._history_loaded_from_db: bool = False

    @property
    def state(self) -> ConversationState:
        return self._state

    @state.setter
    def state(self, value: ConversationState) -> None:
        if self._state != value:
            logger.debug(f"Session {self.user_id} 状态变更: {self._state} → {value}")
        self._state = value

    def update_activity(self) -> None:
        self.last_activity_at = time.time()

    def add_user_message(self, content: str, user_name: str, user_id: str, timestamp: float | None = None) -> None:
        msg_time = timestamp or time.time()
        self.observation_info.unprocessed_messages.append({
            "type": "user_message", "content": content, "user_name": user_name, "user_id": user_id, "time": msg_time})
        self.observation_info.new_messages_count += 1
        self.observation_info.last_message_time = msg_time
        self.observation_info.last_message_sender = user_id
        self.observation_info.last_message_content = content
        self.consecutive_timeout_count = 0
        self.last_user_message_at = msg_time
        self.last_user_speak_time = msg_time
        self._clear_timeout_goals()
        self.update_activity()

    def _clear_timeout_goals(self) -> None:
        if not self.conversation_info.goal_list:
            return
        timeout_keywords = ["分钟，思考接下来要做什么", "分钟，注意可能在对方看来聊天已经结束", "对方似乎话说一半突然消失了"]
        filtered = []
        for goal_item in self.conversation_info.goal_list:
            if isinstance(goal_item, dict):
                goal_text = goal_item.get("goal", "")
                if isinstance(goal_text, str):
                    if any(kw in goal_text for kw in timeout_keywords) or goal_text == "结束对话":
                        continue
            filtered.append(goal_item)
        if len(filtered) != len(self.conversation_info.goal_list):
            self.conversation_info.goal_list = filtered

    def add_bot_message(self, content: str, timestamp: float | None = None) -> None:
        from src.config.config import global_config
        msg_time = timestamp or time.time()
        self.observation_info.chat_history.append({"type": "bot_message", "content": content, "time": msg_time})
        self.observation_info.chat_history_count += 1
        self.last_bot_speak_time = msg_time

        bot_name = global_config.bot.nickname if global_config else "Bot"
        readable_time = translate_timestamp(msg_time)
        stripped = content.strip()
        if stripped.endswith("。"):
            stripped = stripped[:-1]
        bot_block = f"{readable_time} {bot_name}(你) 说:\n{stripped};\n"
        self.observation_info.chat_history_str = (self.observation_info.chat_history_str + "\n" + bot_block
                                                   if self.observation_info.chat_history_str else bot_block)
        self._trim_history()
        self.update_activity()

    def get_time_info(self) -> str:
        current_time = time.time()
        time_info = ""
        if self.last_bot_speak_time:
            time_info += f"\n距离你上次发言已经过去了{int(current_time - self.last_bot_speak_time)}秒"
        if self.last_user_speak_time:
            time_info += f"\n距离对方上次发言已经过去了{int(current_time - self.last_user_speak_time)}秒"
        return time_info

    def _trim_history(self) -> None:
        if len(self.observation_info.chat_history) > self.MAX_HISTORY_SIZE:
            self.observation_info.chat_history = self.observation_info.chat_history[-self.MAX_HISTORY_SIZE:]
            self.observation_info.chat_history_count = len(self.observation_info.chat_history)

    async def clear_unprocessed_messages(self) -> None:
        await self.observation_info.clear_unprocessed_messages()
        self._trim_history()

    def start_waiting(self, max_wait_seconds: int = 300) -> None:
        if max_wait_seconds <= 0:
            self.state = ConversationState.ANALYZING
            self.waiting_config.reset()
            return
        self.state = ConversationState.WAITING
        self.waiting_config = WaitingConfig(max_wait_seconds=max_wait_seconds, started_at=time.time())

    def end_waiting(self) -> None:
        self.state = ConversationState.ANALYZING
        self.waiting_config.reset()
        self.update_activity()

    def is_waiting_timeout(self) -> bool:
        return self.waiting_config.is_timeout()

    def should_proactive_think(self, config) -> bool:
        import random
        from datetime import datetime
        proactive_cfg = config.proactive
        if not proactive_cfg.enabled:
            return False
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
        if self.last_proactive_at and time.time() - self.last_proactive_at < proactive_cfg.min_interval_between_proactive:
            return False
        if not self.last_user_message_at or time.time() - self.last_user_message_at < proactive_cfg.silence_threshold_seconds:
            return False
        return random.random() <= proactive_cfg.trigger_probability

    def new_message_after(self, timestamp: float) -> bool:
        return any(msg.get("time", 0) > timestamp for msg in self.observation_info.unprocessed_messages)

    def to_dict(self) -> dict:
        return {
            "user_id": self.user_id, "stream_id": self.stream_id, "state": str(self.state),
            "should_continue": self.should_continue, "ignore_until_timestamp": self.ignore_until_timestamp,
            "conversation_info": self.conversation_info.to_dict(), "observation_info": self.observation_info.to_dict(),
            "waiting_config": {"max_wait_seconds": self.waiting_config.max_wait_seconds, "started_at": self.waiting_config.started_at},
            "created_at": self.created_at, "last_activity_at": self.last_activity_at,
            "total_interactions": self.total_interactions, "last_proactive_at": self.last_proactive_at,
            "consecutive_timeout_count": self.consecutive_timeout_count, "last_user_message_at": self.last_user_message_at,
            "last_bot_speak_time": self.last_bot_speak_time, "last_user_speak_time": self.last_user_speak_time,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "PFCSession":
        session = cls(user_id=data.get("user_id", ""), stream_id=data.get("stream_id", ""))
        try:
            session._state = ConversationState(data.get("state", "init"))
        except ValueError:
            session._state = ConversationState.INIT
        session.should_continue = data.get("should_continue", True)
        session.ignore_until_timestamp = data.get("ignore_until_timestamp")
        session.conversation_info = ConversationInfo.from_dict(data.get("conversation_info", {}))
        session.observation_info = ObservationInfo.from_dict(data.get("observation_info", {}))
        wait_data = data.get("waiting_config", {})
        session.waiting_config = WaitingConfig(max_wait_seconds=wait_data.get("max_wait_seconds", 0),
                                                started_at=wait_data.get("started_at", 0.0))
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
    """会话管理器"""
    _instance: Optional["SessionManager"] = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, max_session_age_days: int = 30):
        if hasattr(self, "_initialized") and self._initialized:
            return
        self._initialized = True
        self.max_session_age_days = max_session_age_days
        self._sessions: dict[str, PFCSession] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._db_storage = None
        logger.info("SessionManager 初始化完成")

    def _get_db_storage(self):
        if self._db_storage is None:
            from .db_storage import get_db_storage
            self._db_storage = get_db_storage()
        return self._db_storage

    def _get_lock(self, user_id: str) -> asyncio.Lock:
        if user_id not in self._locks:
            self._locks[user_id] = asyncio.Lock()
        return self._locks[user_id]

    async def get_session(self, user_id: str, stream_id: str) -> PFCSession:
        async with self._get_lock(user_id):
            if user_id in self._sessions:
                self._sessions[user_id].stream_id = stream_id
                return self._sessions[user_id]
            session = await self._load_from_database(user_id)
            if session:
                session.stream_id = stream_id
                self._sessions[user_id] = session
                return session
            session = PFCSession(user_id=user_id, stream_id=stream_id)
            self._sessions[user_id] = session
            return session

    async def _load_from_database(self, user_id: str) -> PFCSession | None:
        try:
            data = await self._get_db_storage().load_session(user_id)
            return PFCSession.from_dict(data) if data else None
        except Exception as e:
            logger.error(f"从数据库加载会话失败 {user_id}: {e}")
            return None

    async def save_session(self, user_id: str) -> bool:
        async with self._get_lock(user_id):
            if user_id not in self._sessions:
                return False
            return await self._save_to_database(self._sessions[user_id])

    async def _save_to_database(self, session: PFCSession) -> bool:
        try:
            return await self._get_db_storage().save_session(session)
        except Exception as e:
            logger.error(f"保存会话到数据库失败 {session.user_id}: {e}")
            return False

    async def save_all(self) -> int:
        count = 0
        for user_id in list(self._sessions.keys()):
            if await self.save_session(user_id):
                count += 1
        return count

    async def get_waiting_sessions(self) -> list[PFCSession]:
        return [s for s in self._sessions.values() if s.state == ConversationState.WAITING]

    async def get_all_sessions(self) -> list[PFCSession]:
        return list(self._sessions.values())

    def get_session_sync(self, user_id: str) -> PFCSession | None:
        return self._sessions.get(user_id)


_session_manager: SessionManager | None = None


def get_session_manager() -> SessionManager:
    global _session_manager
    if _session_manager is None:
        _session_manager = SessionManager()
    return _session_manager