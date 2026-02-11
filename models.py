"""PFC 数据模型 - 定义核心数据结构 (GPL-3.0)"""

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class ConversationState(Enum):
    """对话状态"""
    INIT = "init"
    ANALYZING = "analyzing"
    GENERATING = "generating"
    CHECKING = "checking"
    WAITING = "waiting"
    LISTENING = "listening"
    FETCHING = "fetching"
    RETHINKING = "rethinking"
    IGNORED = "ignored"

    def __str__(self) -> str:
        return self.value


class ActionType(Enum):
    """行动类型"""
    DIRECT_REPLY = "direct_reply"
    SEND_NEW_MESSAGE = "send_new_message"
    FETCH_KNOWLEDGE = "fetch_knowledge"
    WAIT = "wait"
    LISTENING = "listening"
    RETHINK_GOAL = "rethink_goal"
    USE_TOOL = "use_tool"
    END_CONVERSATION = "end_conversation"
    SAY_GOODBYE = "say_goodbye"
    BLOCK_AND_IGNORE = "block_and_ignore"

    def __str__(self) -> str:
        return self.value


@dataclass
class GoalItem:
    goal: str
    reasoning: str

    def to_dict(self) -> dict[str, str]:
        return {"goal": self.goal, "reasoning": self.reasoning}

    @classmethod
    def from_dict(cls, data: dict) -> "GoalItem":
        return cls(goal=data.get("goal", ""), reasoning=data.get("reasoning", ""))


@dataclass
class ActionRecord:
    action: str
    plan_reason: str
    status: str = "start"
    time: str = ""
    final_reason: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {"action": self.action, "plan_reason": self.plan_reason, "status": self.status,
                "time": self.time, "final_reason": self.final_reason}

    @classmethod
    def from_dict(cls, data: dict) -> "ActionRecord":
        return cls(action=data.get("action", ""), plan_reason=data.get("plan_reason", ""),
                   status=data.get("status", "start"), time=data.get("time", ""),
                   final_reason=data.get("final_reason"))


@dataclass
class KnowledgeItem:
    query: str
    knowledge: str
    source: str

    def to_dict(self) -> dict[str, str]:
        return {"query": self.query, "knowledge": self.knowledge, "source": self.source}


@dataclass
class ConversationInfo:
    """对话信息"""
    done_action: list[dict] = field(default_factory=list)
    goal_list: list[dict] = field(default_factory=list)
    knowledge_list: list[dict] = field(default_factory=list)
    memory_list: list[dict] = field(default_factory=list)
    tool_results: list[dict] = field(default_factory=list)
    last_successful_reply_action: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {"done_action": self.done_action, "goal_list": self.goal_list,
                "knowledge_list": self.knowledge_list, "memory_list": self.memory_list,
                "tool_results": self.tool_results,
                "last_successful_reply_action": self.last_successful_reply_action}

    @classmethod
    def from_dict(cls, data: dict) -> "ConversationInfo":
        return cls(done_action=data.get("done_action", []), goal_list=data.get("goal_list", []),
                   knowledge_list=data.get("knowledge_list", []), memory_list=data.get("memory_list", []),
                   tool_results=data.get("tool_results", []),
                   last_successful_reply_action=data.get("last_successful_reply_action"))


@dataclass
class ObservationInfo:
    """观察信息"""
    chat_history: list[dict] = field(default_factory=list)
    chat_history_str: str = ""
    chat_history_count: int = 0
    unprocessed_messages: list[dict] = field(default_factory=list)
    new_messages_count: int = 0
    last_message_time: Optional[float] = None
    last_message_sender: Optional[str] = None
    last_message_content: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"chat_history": self.chat_history, "chat_history_str": self.chat_history_str,
                "chat_history_count": self.chat_history_count, "unprocessed_messages": self.unprocessed_messages,
                "new_messages_count": self.new_messages_count, "last_message_time": self.last_message_time,
                "last_message_sender": self.last_message_sender, "last_message_content": self.last_message_content}

    @classmethod
    def from_dict(cls, data: dict) -> "ObservationInfo":
        return cls(chat_history=data.get("chat_history", []), chat_history_str=data.get("chat_history_str", ""),
                   chat_history_count=data.get("chat_history_count", 0),
                   unprocessed_messages=data.get("unprocessed_messages", []),
                   new_messages_count=data.get("new_messages_count", 0),
                   last_message_time=data.get("last_message_time"),
                   last_message_sender=data.get("last_message_sender"),
                   last_message_content=data.get("last_message_content", ""))

    async def clear_unprocessed_messages(self, bot_name: str = "Bot", truncate: bool = True) -> None:
        """将未处理消息移入历史记录，并更新聊天记录字符串
        
        Args:
            bot_name: Bot 名称
            truncate: 是否根据消息新旧程度截断过长内容
        """
        if not self.unprocessed_messages:
            return
        from src.config.config import global_config
        from .shared import format_chat_history

        self.chat_history.extend(self.unprocessed_messages)
        if len(self.chat_history) > 100:
            self.chat_history = self.chat_history[-100:]

        actual_bot_name = global_config.bot.nickname if global_config else bot_name
        self.chat_history_str = format_chat_history(
            self.chat_history[-20:], actual_bot_name, "用户", 20, truncate=truncate
        )
        self.unprocessed_messages = []
        self.new_messages_count = 0
        self.chat_history_count = len(self.chat_history)


@dataclass
class WaitingConfig:
    max_wait_seconds: int = 300
    started_at: float = 0.0

    def is_active(self) -> bool:
        return self.max_wait_seconds > 0 and self.started_at > 0

    def get_elapsed_seconds(self) -> float:
        return time.time() - self.started_at if self.is_active() else 0.0

    def is_timeout(self) -> bool:
        return self.is_active() and self.get_elapsed_seconds() >= self.max_wait_seconds

    def reset(self) -> None:
        self.max_wait_seconds = 0
        self.started_at = 0.0


@dataclass
class ActionModel:
    type: str
    params: dict[str, Any] = field(default_factory=dict)
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        result = {"type": self.type}
        if self.reason:
            result["reason"] = self.reason
        result.update(self.params)
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ActionModel":
        return cls(type=data.get("type", "wait"), reason=data.get("reason", ""),
                   params={k: v for k, v in data.items() if k not in ("type", "reason")})


@dataclass
class PlanResponse:
    action: str
    reason: str
    actions: list[ActionModel] = field(default_factory=list)
    max_wait_seconds: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {"action": self.action, "reason": self.reason,
                "actions": [a.to_dict() for a in self.actions], "max_wait_seconds": self.max_wait_seconds}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PlanResponse":
        return cls(action=data.get("action", "wait"), reason=data.get("reason", ""),
                   actions=[ActionModel.from_dict(a) for a in data.get("actions", [])],
                   max_wait_seconds=data.get("max_wait_seconds", 0))

    @classmethod
    def create_default(cls) -> "PlanResponse":
        return cls(action="wait", reason="默认等待")