"""
Prefrontal Cortex Chatter (PFC) - 私聊特化聊天器

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
- 重构消息处理和回复生成逻辑
- 添加主动思考功能
- 重构会话管理器
- 修复聊天历史构建问题
- 修复人格获取逻辑

本项目遵循 GNU General Public License v3.0 许可证。
详见 LICENSE 文件。

================================================================================

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
    author="ASUSwei114 (基于 MaiM-with-u)",
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