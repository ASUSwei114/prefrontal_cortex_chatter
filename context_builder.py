"""PFC 上下文构建器 - 为 PFC 提供情境感知能力 (GPL-3.0)"""

import asyncio
import time
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from src.common.logger import get_logger
from src.config.config import global_config
from src.person_info.person_info import get_person_info_manager

if TYPE_CHECKING:
    from .plugin import PFCConfig

logger = get_logger("pfc_context_builder")

# 模块级别的 ToolExecutor 缓存，按 stream_id 索引
_tool_executor_cache: dict[str, Any] = {}

# 模块级别的工具决策缓存，按 stream_id 索引
_tool_decision_cache: dict[str, dict[str, Any]] = {}


def _get_config():
    assert global_config is not None, "global_config 未初始化"
    return global_config


def _get_cached_tool_executor(stream_id: str):
    """获取或创建缓存的 ToolExecutor 实例"""
    if stream_id not in _tool_executor_cache:
        from src.plugin_system.core.tool_use import ToolExecutor
        _tool_executor_cache[stream_id] = ToolExecutor(chat_id=stream_id)
    return _tool_executor_cache[stream_id]


def get_tool_decision_cache(stream_id: str) -> dict[str, Any]:
    """获取工具决策缓存"""
    if stream_id not in _tool_decision_cache:
        _tool_decision_cache[stream_id] = {
            "pending_tools": [],  # 待执行的工具列表
            "executed_results": [],  # 已执行的工具结果
            "last_decision_time": 0,  # 上次决策时间
        }
    return _tool_decision_cache[stream_id]


def clear_tool_decision_cache(stream_id: str):
    """清除工具决策缓存"""
    if stream_id in _tool_decision_cache:
        _tool_decision_cache[stream_id] = {
            "pending_tools": [],
            "executed_results": [],
            "last_decision_time": 0,
        }


class PFCContextBuilder:
    """PFC 上下文构建器"""

    def __init__(self, stream_id: str, pfc_config: "PFCConfig"):
        self.stream_id = stream_id
        self.pfc_config = pfc_config
        self.platform = "qq"
        self.is_group_chat = False

    async def build_all_context(self, sender_name: str, target_message: str, chat_history: str = "",
                                 user_id: str | None = None, enable_tool: bool = True) -> dict[str, str]:
        """并行构建所有上下文模块"""
        tasks = {
            "relation_info": self._build_relation_info(sender_name, target_message, user_id),
            "memory_block": self._build_memory_block(chat_history, target_message),
            "tool_info": self._build_tool_info(chat_history, sender_name, target_message, enable_tool),
            "expression_habits": self._build_expression_habits(chat_history, target_message),
            "schedule": self._build_schedule_block(),
            "time": self._build_time_block(),
        }

        task_names = {"relation_info": "感受关系", "memory_block": "回忆", "tool_info": "使用工具",
                      "expression_habits": "选取表达方式", "schedule": "日程", "time": "时间"}
        results, timing_logs = {}, []

        try:
            task_results = await asyncio.gather(
                *[self._wrap_task_with_timing(name, coro) for name, coro in tasks.items()],
                return_exceptions=True)

            for result in task_results:
                if isinstance(result, tuple) and len(result) == 3:
                    name, value, duration = result
                    results[name] = value
                    timing_logs.append(f"{task_names.get(name, name)}: {duration:.1f}s")
                    if duration > 8:
                        logger.warning(f"PFC 上下文构建耗时过长: {task_names.get(name, name)} 耗时: {duration:.1f}s")
        except Exception as e:
            logger.error(f"并行构建上下文失败: {e}")

        if timing_logs:
            logger.info(f"[PFC] 在回复前的步骤耗时: {'; '.join(timing_logs)}")
        return results

    async def build_tool_info(self, chat_history: str, sender_name: str, target_message: str, enable_tool: bool = True) -> str:
        """公开方法：构建工具信息块"""
        return await self._build_tool_info(chat_history, sender_name, target_message, enable_tool)

    async def _wrap_task_with_timing(self, name: str, coro) -> tuple[str, str, float]:
        start_time = time.time()
        try:
            result = await coro
            return (name, result or "", time.time() - start_time)
        except Exception as e:
            logger.error(f"构建 {name} 失败: {e}")
            return (name, "", time.time() - start_time)

    async def _build_relation_info(self, sender_name: str, target_message: str, user_id: str | None = None) -> str:
        """构建关系信息块"""
        config = _get_config()
        if sender_name == f"{config.bot.nickname}(你)":
            return "你将要回复的是你自己发送的消息。"

        person_info_manager = get_person_info_manager()
        person_id = person_info_manager.get_person_id(self.platform, user_id) if user_id else None
        if not person_id:
            person_id = await person_info_manager.get_person_id_by_person_name(sender_name)
        if not person_id:
            return f"你与{sender_name}还没有建立深厚的关系，这是早期的互动阶段。"

        try:
            from src.person_info.relationship_fetcher import relationship_fetcher_manager
            fetcher = relationship_fetcher_manager.get_fetcher(self.stream_id)
            user_relation_info = await fetcher.build_relation_info(person_id, points_num=5)
            stream_impression = await fetcher.build_chat_stream_impression(self.stream_id)

            parts = []
            if user_relation_info:
                parts.append(f"### 你与 {sender_name} 的关系\n{user_relation_info}")
            if stream_impression:
                parts.append(f"### 你对你们的私聊的印象\n{stream_impression}")
            return "\n\n".join(parts) if parts else f"你与{sender_name}还没有建立深厚的关系，这是早期的互动阶段。"
        except Exception as e:
            logger.error(f"获取关系信息失败: {e}")
            return f"你与{sender_name}是普通朋友关系。"

    async def _build_memory_block(self, chat_history: str, target_message: str) -> str:
        """构建记忆块"""
        config = _get_config()
        if not (config.memory and config.memory.enable):
            return ""

        try:
            from src.memory_graph.manager_singleton import ensure_unified_memory_manager_initialized
            from src.memory_graph.utils.three_tier_formatter import memory_formatter

            unified_manager = await ensure_unified_memory_manager_initialized()
            if not unified_manager:
                return ""

            query_text = target_message or chat_history[:500]
            search_result = await unified_manager.search_memories(
                query_text=query_text, use_judge=config.memory.use_judge, recent_chat_history=chat_history)

            if not search_result:
                return ""

            perceptual = search_result.get("perceptual_blocks", [])
            short_term = search_result.get("short_term_memories", [])
            long_term = search_result.get("long_term_memories", [])

            formatted = await memory_formatter.format_all_tiers(
                perceptual_blocks=perceptual, short_term_memories=short_term, long_term_memories=long_term)

            total = len(perceptual) + len(short_term) + len(long_term)
            if total > 0 and formatted.strip():
                logger.info(f"[PFC记忆] 检索到 {total} 条记忆")
                return f"### 🧠 相关记忆\n\n{formatted}"
            return ""
        except Exception as e:
            logger.error(f"[PFC记忆] 检索失败: {e}")
            return ""

    async def _build_tool_info(self, chat_history: str, sender_name: str, target_message: str, enable_tool: bool = True) -> str:
        """构建工具信息块 - 只提供可用工具列表和历史，不自动执行"""
        if not enable_tool:
            return ""

        try:
            tool_executor = _get_cached_tool_executor(self.stream_id)
            info_parts = []

            # 1. 召回联网搜索缓存
            try:
                from src.common.cache_manager import tool_cache
                query_text = chat_history or target_message
                recalled = await tool_cache.recall_relevant_cache(
                    query_text=query_text, tool_name="web_search", top_k=2, similarity_threshold=0.65)

                if recalled:
                    recall_parts = ["### 🔍 相关的历史搜索结果"]
                    for item in recalled:
                        content = item.get("content", "")
                        if content:
                            content = content[:500] + "..." if len(content) > 500 else content
                            recall_parts.append(f"**搜索「{item.get('query', '')}」** (相关度:{item.get('similarity', 0):.0%})\n{content}")
                    info_parts.append("\n\n".join(recall_parts))
            except Exception:
                pass

            # 2. 工具调用历史
            tool_history = tool_executor.history_manager.format_for_prompt(max_records=3, include_results=True)
            if tool_history:
                info_parts.append(tool_history)

            # 3. 获取可用工具列表（不自动执行）
            available_tools = await self._get_available_tools_description()
            if available_tools:
                info_parts.append(available_tools)

            # 4. 检查是否有已执行的工具结果（来自 use_tool 行动）
            decision_cache = get_tool_decision_cache(self.stream_id)
            if decision_cache.get("executed_results"):
                parts = ["### 🔧 刚获取的工具信息"]
                for r in decision_cache["executed_results"]:
                    parts.append(f"- **{r.get('tool_name', 'unknown')}**: {r.get('content', '')}")
                info_parts.append("\n".join(parts))
                # 清除已使用的结果
                decision_cache["executed_results"] = []

            return "\n\n".join(info_parts) if info_parts else ""
        except Exception as e:
            logger.error(f"[PFC工具调用] 工具信息获取失败: {e}")
            return ""

    async def _get_available_tools_description(self) -> str:
        """获取可用工具的描述列表"""
        try:
            from src.plugin_system.apis.tool_api import get_llm_available_tool_definitions
            
            tool_definitions = get_llm_available_tool_definitions(self.stream_id)
            if not tool_definitions:
                return ""
            
            parts = ["### 🛠️ 可用工具列表"]
            parts.append("如果你认为需要使用工具来获取信息，可以选择 `use_tool` 行动并指定要使用的工具。")
            parts.append("")
            
            for tool_def in tool_definitions:
                tool_name = tool_def.get("name", "unknown")
                description = tool_def.get("description", "无描述")
                # 截断过长的描述
                if len(description) > 150:
                    description = description[:150] + "..."
                parts.append(f"- **{tool_name}**: {description}")
            
            return "\n".join(parts)
        except Exception as e:
            logger.error(f"[PFC] 获取可用工具列表失败: {e}")
            return ""

    async def execute_tool_decision(self, tool_name: str, tool_args: dict[str, Any] | None = None,
                                     chat_history: str = "", sender_name: str = "",
                                     target_message: str = "") -> dict[str, Any]:
        """执行工具决策 - 由 PFC 决策后调用
        
        Args:
            tool_name: 要执行的工具名称
            tool_args: 工具参数（可选，如果不提供则由 LLM 自动推断）
            chat_history: 聊天历史
            sender_name: 发送者名称
            target_message: 目标消息
            
        Returns:
            工具执行结果
        """
        try:
            tool_executor = _get_cached_tool_executor(self.stream_id)
            decision_cache = get_tool_decision_cache(self.stream_id)
            
            if tool_args:
                # 直接执行指定工具和参数
                result = await tool_executor.execute_specific_tool_simple(tool_name, tool_args)
                if result:
                    decision_cache["executed_results"].append(result)
                    logger.info(f"[PFC工具决策] 执行工具 {tool_name} 成功")
                    return {"success": True, "result": result}
                else:
                    logger.warning(f"[PFC工具决策] 执行工具 {tool_name} 返回空结果")
                    return {"success": False, "error": "工具返回空结果"}
            else:
                # 让 LLM 决定参数并执行
                simplified = '\n'.join(chat_history.strip().split('\n')[-5:]) if chat_history else ""
                tool_results, used_tools, _ = await tool_executor.execute_from_chat_message(
                    sender=sender_name, target_message=target_message,
                    chat_history=simplified, return_details=False)
                
                if tool_results:
                    decision_cache["executed_results"].extend(tool_results)
                    logger.info(f"[PFC工具决策] 执行工具成功: {used_tools}")
                    return {"success": True, "results": tool_results, "used_tools": used_tools}
                else:
                    return {"success": False, "error": "未执行任何工具"}
                    
        except Exception as e:
            logger.error(f"[PFC工具决策] 执行失败: {e}")
            return {"success": False, "error": str(e)}

    async def execute_specific_tools(self, tool_requests: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """执行指定的多个工具
        
        Args:
            tool_requests: 工具请求列表，每个请求包含 {"tool_name": str, "args": dict}
            
        Returns:
            工具执行结果列表
        """
        results = []
        tool_executor = _get_cached_tool_executor(self.stream_id)
        decision_cache = get_tool_decision_cache(self.stream_id)
        
        for request in tool_requests:
            tool_name = request.get("tool_name", "")
            tool_args = request.get("args", {})
            
            if not tool_name:
                continue
                
            try:
                result = await tool_executor.execute_specific_tool_simple(tool_name, tool_args)
                if result:
                    results.append(result)
                    decision_cache["executed_results"].append(result)
                    logger.info(f"[PFC工具决策] 执行工具 {tool_name} 成功")
            except Exception as e:
                logger.error(f"[PFC工具决策] 执行工具 {tool_name} 失败: {e}")
                results.append({
                    "tool_name": tool_name,
                    "content": f"执行失败: {e}",
                    "type": "error"
                })
        
        return results

    async def _build_expression_habits(self, chat_history: str, target_message: str) -> str:
        """构建表达习惯块"""
        config = _get_config()
        use_expression, _, _ = config.expression.get_expression_config_for_chat(self.stream_id)
        if not use_expression:
            return ""

        try:
            from src.chat.express.expression_selector import expression_selector
            style_habits, grammar_habits = [], []

            selected = await expression_selector.select_suitable_expressions(
                chat_id=self.stream_id, chat_history=chat_history, target_message=target_message, max_num=8, min_num=2)

            for expr in (selected or []):
                if isinstance(expr, dict) and "situation" in expr and "style" in expr:
                    habit = f"当{expr['situation']}时，使用 {expr['style']}"
                    (grammar_habits if expr.get("type") == "grammar" else style_habits).append(habit)

            parts = []
            if style_habits:
                parts.append("**语言风格习惯**：\n" + "\n".join(f"- {h}" for h in style_habits))
            if grammar_habits:
                parts.append("**句法习惯**：\n" + "\n".join(f"- {h}" for h in grammar_habits))
            return "### 💬 你的表达习惯\n\n" + "\n\n".join(parts) if parts else ""
        except Exception as e:
            logger.error(f"构建表达习惯失败: {e}")
            return ""

    async def _build_schedule_block(self) -> str:
        """构建日程信息块"""
        config = _get_config()
        if not config.planning_system.schedule_enable:
            return ""

        try:
            from src.schedule.schedule_manager import schedule_manager
            activity_info = schedule_manager.get_current_activity()
            if not activity_info:
                return ""

            activity = activity_info.get("activity")
            time_range = activity_info.get("time_range")
            now = datetime.now()

            if time_range:
                try:
                    start_str, end_str = time_range.split("-")
                    start_time = datetime.strptime(start_str.strip(), "%H:%M").replace(year=now.year, month=now.month, day=now.day)
                    end_time = datetime.strptime(end_str.strip(), "%H:%M").replace(year=now.year, month=now.month, day=now.day)
                    if end_time < start_time:
                        end_time += timedelta(days=1)
                    if now < start_time:
                        now += timedelta(days=1)
                    duration = (now - start_time).total_seconds() / 60
                    remaining = (end_time - now).total_seconds() / 60
                    return f"你当前正在「{activity}」，从{start_time.strftime('%H:%M')}开始，预计{end_time.strftime('%H:%M')}结束，已进行{duration:.0f}分钟，还剩约{remaining:.0f}分钟。"
                except (ValueError, AttributeError):
                    pass
            return f"你当前正在「{activity}」"
        except Exception as e:
            logger.error(f"构建日程块失败: {e}")
            return ""

    async def _build_time_block(self) -> str:
        """构建时间信息块"""
        now = datetime.now()
        weekdays = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
        return f"{now.strftime('%Y年%m月%d日')} {weekdays[now.weekday()]} {now.strftime('%H:%M:%S')}"


async def build_pfc_context(stream_id: str, pfc_config: "PFCConfig", sender_name: str, target_message: str,
                            chat_history: str = "", user_id: str | None = None, enable_tool: bool = True) -> dict[str, str]:
    """便捷函数：构建 PFC 所需的所有上下文"""
    return await PFCContextBuilder(stream_id, pfc_config).build_all_context(sender_name, target_message, chat_history, user_id, enable_tool)


__all__ = ["PFCContextBuilder", "build_pfc_context", "get_tool_decision_cache", "clear_tool_decision_cache"]