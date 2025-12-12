"""
Prefrontal Cortex Chatter (PFC) - 私聊特化聊天器

从 MaiM-with-u 0.6.3-fix4 移植的 PFC 私聊系统

主要组件：
- PrefrontalCortexChatterPlugin: 插件主类
- PrefrontalCortexChatter: 聊天器实现
- ActionPlanner: 行动规划器
- ReplyGenerator: 回复生成器
- GoalAnalyzer: 目标分析器
- Waiter: 等待器
- KnowledgeFetcher: 知识获取器
- SessionManager: 会话管理器
"""

from src.plugin_system.base.plugin_metadata import PluginMetadata

from .chatter import PrefrontalCortexChatter
from .config import PFCConfig
from .goal_analyzer import GoalAnalyzer
from .knowledge_fetcher import KnowledgeFetcher
from .models import (
    ActionType,
    ConversationInfo,
    ConversationState,
    ObservationInfo,
)
from .planner import ActionPlanner
from .plugin import PrefrontalCortexChatterPlugin
from .replyer import ReplyChecker, ReplyGenerator
from .session import PFCSession, SessionManager, get_session_manager
from .waiter import Waiter

__plugin_meta__ = PluginMetadata(
    name="Prefrontal Cortex Chatter",
    description="从 MaiM-with-u 0.6.3-fix4 移植的私聊系统，支持目标驱动的对话管理",
    usage="在私聊场景中自动启用，可通过 [prefrontal_cortex_chatter].enable 配置",
    version="1.0.0",
    author="MaiM-with-u",
    keywords=["chatter", "pfc", "private", "goal-driven", "planning"],
    categories=["Chat", "AI", "Planning"],
    extra={"is_built_in": True, "chat_type": "private"},
)

__all__ = [
    # 元数据
    "__plugin_meta__",
    # 插件
    "PrefrontalCortexChatterPlugin",
    # 聊天器
    "PrefrontalCortexChatter",
    # 核心组件
    "ActionPlanner",
    "ReplyGenerator",
    "ReplyChecker",
    "GoalAnalyzer",
    "Waiter",
    "KnowledgeFetcher",
    # 会话管理
    "PFCSession",
    "SessionManager",
    "get_session_manager",
    # 数据模型
    "ConversationState",
    "ActionType",
    "ConversationInfo",
    "ObservationInfo",
    # 配置
    "PFCConfig",
]