"""
PFC - 数据模型

================================================================================
版权声明 (Copyright Notice)
================================================================================

原始代码来源: MaiM-with-u (https://github.com/MaiM-with-u/MaiBot)
原始版本: 0.6.3-fix4
原始代码路径: src/plugins/PFC/
原始许可证: GNU General Public License v3.0

本文件由 ASUSwei114 (https://github.com/ASUSwei114) 于 2024年12月 修改移植至 MoFox_Bot 项目。

主要修改内容:
- 重构数据模型为 dataclass
- 添加序列化/反序列化方法
- 修复聊天历史构建逻辑
- 使用共享模块精简代码

本项目遵循 GNU General Public License v3.0 许可证。
详见 LICENSE 文件。

================================================================================

定义核心数据结构：
- ConversationState: 对话状态
- ActionType: 行动类型
- ConversationInfo: 对话信息
- ObservationInfo: 观察信息
"""

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
    END_CONVERSATION = "end_conversation"
    SAY_GOODBYE = "say_goodbye"
    BLOCK_AND_IGNORE = "block_and_ignore"

    def __str__(self) -> str:
        return self.value


@dataclass
class GoalItem:
    """目标项"""
    goal: str
    reasoning: str

    def to_dict(self) -> dict[str, str]:
        return {"goal": self.goal, "reasoning": self.reasoning}

    @classmethod
    def from_dict(cls, data: dict) -> "GoalItem":
        return cls(
            goal=data.get("goal", ""),
            reasoning=data.get("reasoning", ""),
        )


@dataclass
class ActionRecord:
    """行动记录"""
    action: str
    plan_reason: str
    status: str = "start"  # start, done, recall
    time: str = ""
    final_reason: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "plan_reason": self.plan_reason,
            "status": self.status,
            "time": self.time,
            "final_reason": self.final_reason,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ActionRecord":
        return cls(
            action=data.get("action", ""),
            plan_reason=data.get("plan_reason", ""),
            status=data.get("status", "start"),
            time=data.get("time", ""),
            final_reason=data.get("final_reason"),
        )


@dataclass
class KnowledgeItem:
    """知识项"""
    query: str
    knowledge: str
    source: str

    def to_dict(self) -> dict[str, str]:
        return {"query": self.query, "knowledge": self.knowledge, "source": self.source}


@dataclass
class ConversationInfo:
    """对话信息 - 存储对话过程中的决策相关信息"""
    done_action: list[dict] = field(default_factory=list)
    goal_list: list[dict] = field(default_factory=list)
    knowledge_list: list[dict] = field(default_factory=list)
    memory_list: list[dict] = field(default_factory=list)
    last_successful_reply_action: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "done_action": self.done_action,
            "goal_list": self.goal_list,
            "knowledge_list": self.knowledge_list,
            "memory_list": self.memory_list,
            "last_successful_reply_action": self.last_successful_reply_action,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ConversationInfo":
        return cls(
            done_action=data.get("done_action", []),
            goal_list=data.get("goal_list", []),
            knowledge_list=data.get("knowledge_list", []),
            memory_list=data.get("memory_list", []),
            last_successful_reply_action=data.get("last_successful_reply_action"),
        )


@dataclass
class ObservationInfo:
    """观察信息 - 存储从消息流观察到的信息"""
    chat_history: list[dict] = field(default_factory=list)
    chat_history_str: str = ""
    chat_history_count: int = 0
    unprocessed_messages: list[dict] = field(default_factory=list)
    new_messages_count: int = 0
    last_message_time: Optional[float] = None
    last_message_sender: Optional[str] = None
    last_message_content: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "chat_history": self.chat_history,
            "chat_history_str": self.chat_history_str,
            "chat_history_count": self.chat_history_count,
            "unprocessed_messages": self.unprocessed_messages,
            "new_messages_count": self.new_messages_count,
            "last_message_time": self.last_message_time,
            "last_message_sender": self.last_message_sender,
            "last_message_content": self.last_message_content,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ObservationInfo":
        return cls(
            chat_history=data.get("chat_history", []),
            chat_history_str=data.get("chat_history_str", ""),
            chat_history_count=data.get("chat_history_count", 0),
            unprocessed_messages=data.get("unprocessed_messages", []),
            new_messages_count=data.get("new_messages_count", 0),
            last_message_time=data.get("last_message_time"),
            last_message_sender=data.get("last_message_sender"),
            last_message_content=data.get("last_message_content", ""),
        )

    async def clear_unprocessed_messages(self, bot_name: str = "Bot") -> None:
        """清理未处理消息，将其合并到历史并更新历史字符串"""
        if not self.unprocessed_messages:
            return
        
        from src.config.config import global_config
        from .shared import translate_timestamp, format_chat_history
        
        # 合并到历史列表（最多保留100条）
        self.chat_history.extend(self.unprocessed_messages)
        if len(self.chat_history) > 100:
            self.chat_history = self.chat_history[-100:]
        
        # 使用共享模块格式化历史字符串
        actual_bot_name = global_config.bot.nickname if global_config else bot_name
        self.chat_history_str = format_chat_history(
            self.chat_history[-20:], actual_bot_name, "用户", 20
        )
        
        # 清空未处理消息
        self.unprocessed_messages = []
        self.new_messages_count = 0
        self.chat_history_count = len(self.chat_history)


@dataclass
class WaitingConfig:
    """等待配置"""
    max_wait_seconds: int = 300
    started_at: float = 0.0

    def is_active(self) -> bool:
        return self.max_wait_seconds > 0 and self.started_at > 0

    def get_elapsed_seconds(self) -> float:
        if not self.is_active():
            return 0.0
        return time.time() - self.started_at

    def is_timeout(self) -> bool:
        if not self.is_active():
            return False
        return self.get_elapsed_seconds() >= self.max_wait_seconds

    def reset(self) -> None:
        self.max_wait_seconds = 0
        self.started_at = 0.0


@dataclass
class ActionModel:
    """动作模型"""
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
        action_type = data.get("type", "wait")
        reason = data.get("reason", "")
        params = {k: v for k, v in data.items() if k not in ("type", "reason")}
        return cls(type=action_type, params=params, reason=reason)


@dataclass
class PlanResponse:
    """规划响应"""
    action: str
    reason: str
    actions: list[ActionModel] = field(default_factory=list)
    max_wait_seconds: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "reason": self.reason,
            "actions": [a.to_dict() for a in self.actions],
            "max_wait_seconds": self.max_wait_seconds,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PlanResponse":
        actions_data = data.get("actions", [])
        actions = [ActionModel.from_dict(a) for a in actions_data]
        return cls(
            action=data.get("action", "wait"),
            reason=data.get("reason", ""),
            actions=actions,
            max_wait_seconds=data.get("max_wait_seconds", 0),
        )

    @classmethod
    def create_default(cls) -> "PlanResponse":
        return cls(action="wait", reason="默认等待")