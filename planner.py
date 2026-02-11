"""PFC 行动规划器 - 根据当前对话状态规划下一步行动 (GPL-3.0)"""

import time
from typing import Tuple

from src.common.logger import get_logger
from src.plugin_system.apis import llm_api
from .session import PFCSession
from .shared import (PersonalityHelper, get_current_time_str, build_goals_string, build_knowledge_string,
                     format_chat_history, format_new_messages, build_action_history_table, build_chat_history_table,
                     get_items_from_json)

logger = get_logger("pfc_planner")

# Prompt 模板
_PROMPT_CONTEXT = """【当前时间】
{current_time_str}

【当前对话目标】
{goals_str}
{knowledge_info_str}
{tool_info_str}

【最近行动历史概要】
{action_history_summary}
【上一次行动的详细情况和结果】
{last_action_context}
【时间和超时提示】
{time_info}{time_since_last_bot_message_info}{timeout_context}
【最近的对话记录】(包括你已成功发送的消息 和 新收到的消息)
{chat_history_text}

------"""

_PROMPT_JSON_OUTPUT = """请以JSON格式输出你的决策：
{{{{
    "action": "选择的行动类型 (必须是上面列表中的一个)",
    "reason": "选择该行动的原因 (简要说明，30字以内)"
}}}}

注意：请严格按照JSON格式输出，不要包含任何其他内容。"""

_ACTIONS_BASE = """fetch_knowledge: 需要调取知识或记忆，当需要专业知识或特定信息时选择，对方若提到你不太认识的人名或实体也可以尝试选择
listening: 倾听对方发言，当你认为对方话才说到一半，发言明显未结束时选择
rethink_goal: 思考一个对话目标，当你觉得目前对话需要目标，或当前目标不再适用，或话题卡住时选择。注意私聊的环境是灵活的，有可能需要经常选择
use_tool: 使用工具获取信息，当你需要搜索、查询或执行特定操作时选择（需要在reason中说明要使用的工具名称）
end_conversation: 结束对话，对方长时间没回复或者当你觉得对话告一段落时可以选择"""

_ACTION_BLOCK = """block_and_ignore: 更加极端的结束对话方式，直接结束对话并在一段时间内无视对方所有发言（屏蔽），当对话让你感到十分不适，或你遭到各类骚扰时选择"""
_ACTION_DIRECT_REPLY = """direct_reply: 直接回复对方"""
_ACTION_FOLLOW_UP = """wait: 暂时不说话，留给对方交互空间，等待对方回复（尤其是在你刚发言后、或上次发言因重复、发言过多被拒时、或不确定做什么时，这是不错的选择）
send_new_message: 发送一条新消息继续对话，允许适当的追问、补充、深入话题，或开启相关新话题。**但是避免在因重复被拒后立即使用，也不要在对方没有回复的情况下过多的"消息轰炸"或重复发言**"""

def _build_planner_prompt(is_follow_up: bool, enable_block: bool) -> str:
    intro = "{persona_text}。现在你在参与一场QQ私聊，"
    if is_follow_up:
        intro += "刚刚你已经回复了对方，请根据以下【所有信息】审慎且灵活的决策下一步行动"
        actions = f"{_ACTION_FOLLOW_UP}\n{_ACTIONS_BASE}"
    else:
        intro += "请根据以下【所有信息】审慎且灵活的决策下一步行动"
        actions = f"{_ACTION_DIRECT_REPLY}\n{_ACTIONS_BASE}"
    if enable_block:
        actions += f"\n{_ACTION_BLOCK}"
    return f"{intro}：\n\n{_PROMPT_CONTEXT}\n可选行动类型以及解释：\n{actions}\n\n{_PROMPT_JSON_OUTPUT}"


PROMPT_INITIAL_REPLY_WITH_BLOCK = _build_planner_prompt(False, True)
PROMPT_INITIAL_REPLY_NO_BLOCK = _build_planner_prompt(False, False)
PROMPT_FOLLOW_UP_WITH_BLOCK = _build_planner_prompt(True, True)
PROMPT_FOLLOW_UP_NO_BLOCK = _build_planner_prompt(True, False)

PROMPT_END_DECISION = """{persona_text}。刚刚你决定结束一场 QQ 私聊。

【你们之前的聊天记录】
{chat_history_text}

你觉得你们的对话已经完整结束了吗？如果觉得确实有必要再发一条简短的告别消息，就输出 "yes"。否则输出 "no"。

请以 JSON 格式输出你的选择：
{{
    "say_bye": "yes/no",
    "reason": "选择 yes 或 no 的原因 (简要说明)"
}}"""


class ActionPlanner:
    """行动规划器"""

    def __init__(self, session: PFCSession, user_name: str):
        self.session = session
        self.user_name = user_name
        self._personality_helper = PersonalityHelper(user_name)
        self.bot_name = self._personality_helper.bot_name
        from .plugin import get_config
        self._config = get_config()

    async def plan(self) -> Tuple[str, str]:
        """规划下一步行动"""
        personality_info = await self._personality_helper.get_personality_info()
        time_since_last_bot_message_info = self._get_time_since_last_bot_message()
        timeout_context = self._get_timeout_context()
        goals_str = build_goals_string(self.session.conversation_info.goal_list)
        knowledge_info_str = build_knowledge_string(self.session.conversation_info.knowledge_list)
        chat_history_text = self._get_chat_history_text()
        action_history_summary, last_action_context = self._build_action_history()
        tool_info_str = await self._build_tool_info()

        last_action = self.session.conversation_info.last_successful_reply_action
        enable_block = getattr(self._config.waiting, 'enable_block_action', True)

        if last_action in ["direct_reply", "send_new_message"]:
            prompt_template = PROMPT_FOLLOW_UP_WITH_BLOCK if enable_block else PROMPT_FOLLOW_UP_NO_BLOCK
        else:
            prompt_template = PROMPT_INITIAL_REPLY_WITH_BLOCK if enable_block else PROMPT_INITIAL_REPLY_NO_BLOCK

        prompt = prompt_template.format(
            persona_text=personality_info,
            goals_str=goals_str or "- 目前没有明确对话目标，请考虑设定一个。",
            action_history_summary=action_history_summary,
            last_action_context=last_action_context,
            time_info=self.session.get_time_info(),
            time_since_last_bot_message_info=time_since_last_bot_message_info,
            timeout_context=timeout_context,
            chat_history_text=chat_history_text or "还没有聊天记录。",
            knowledge_info_str=knowledge_info_str,
            tool_info_str=tool_info_str or "- 暂无工具信息",
            current_time_str=get_current_time_str(),
        )

        try:
            models = llm_api.get_available_models()
            planner_config = models.get("planner") or models.get("normal")
            if not planner_config:
                return "wait", "未找到模型配置"

            success, content, _, _ = await llm_api.generate_with_model(
                prompt=prompt, model_config=planner_config, request_type="pfc.action_planning")

            if not success or not content:
                return "wait", "LLM 调用失败"

            # 调试日志：记录 LLM 原始响应
            logger.debug(f"[PFC][{self.user_name}] LLM 原始响应: {content[:500]}...")
            
            action_val, reason_val = get_items_from_json(content, "action", "reason", default="wait")
            
            # 调试日志：记录解析结果
            logger.debug(f"[PFC][{self.user_name}] JSON 解析结果: action_val={action_val!r}, reason_val={reason_val!r}")
            
            action = action_val or "wait"
            reason = reason_val or "LLM未提供原因，默认等待"

            if action == "end_conversation":
                return await self._handle_end_decision(personality_info, chat_history_text, reason)

            valid_actions = ["direct_reply", "send_new_message", "fetch_knowledge", "wait",
                           "listening", "rethink_goal", "use_tool", "end_conversation", "say_goodbye"]
            if self._config.waiting.enable_block_action:
                valid_actions.append("block_and_ignore")
            if action not in valid_actions:
                reason = f"(原始行动'{action}'无效，已强制改为wait) {reason}"
                action = "wait"

            logger.info(f"[PFC][{self.user_name}] 规划的行动: {action}, 原因: {reason}")
            return action, reason

        except Exception as e:
            logger.error(f"[PFC][{self.user_name}] 规划行动时出错: {e}")
            return "wait", f"行动规划处理中发生错误: {e}"

    async def _handle_end_decision(self, persona_text: str, chat_history_text: str, initial_reason: str) -> Tuple[str, str]:
        """处理结束对话决策"""
        try:
            models = llm_api.get_available_models()
            planner_config = models.get("planner") or models.get("normal")
            if not planner_config:
                return "end_conversation", initial_reason

            prompt = PROMPT_END_DECISION.format(persona_text=persona_text, chat_history_text=chat_history_text)
            success, content, _, _ = await llm_api.generate_with_model(
                prompt=prompt, model_config=planner_config, request_type="pfc.end_decision")

            if not success or not content:
                return "end_conversation", initial_reason

            say_bye_val, end_reason_val = get_items_from_json(content, "say_bye", "reason", default="no")
            if (say_bye_val or "no").lower() == "yes":
                return "say_goodbye", f"决定发送告别语。原因: {end_reason_val} (原结束理由: {initial_reason})"
            return "end_conversation", initial_reason
        except Exception as e:
            logger.error(f"[PFC][{self.user_name}] 结束决策出错: {e}")
            return "end_conversation", initial_reason

    def _get_time_since_last_bot_message(self) -> str:
        try:
            for msg in reversed(self.session.observation_info.chat_history):
                if msg.get("type") == "bot_message":
                    msg_time = msg.get("time", 0)
                    if msg_time:
                        time_diff = time.time() - msg_time
                        if time_diff < 60.0:
                            return f"提示：你上一条成功发送的消息是在 {time_diff:.1f} 秒前。\n"
                        break
        except Exception:
            pass
        return ""

    def _get_timeout_context(self) -> str:
        try:
            goal_list = self.session.conversation_info.goal_list
            if goal_list:
                last_goal = goal_list[-1]
                if isinstance(last_goal, dict):
                    goal_text = last_goal.get("goal", "")
                    if isinstance(goal_text, str) and "分钟，思考接下来要做什么" in goal_text:
                        try:
                            timeout_minutes_text = goal_text.split("，")[0].replace("你等待了", "")
                            return f"重要提示：对方已经长时间（{timeout_minutes_text}）没有回复你的消息了（这可能代表对方繁忙/不想回复/没注意到你的消息等情况，或在对方看来本次聊天已告一段落），请基于此情况规划下一步。\n"
                        except Exception:
                            return "重要提示：对方已经长时间没有回复你的消息了（这可能代表对方繁忙/不想回复/没注意到你的消息等情况，或在对方看来本次聊天已告一段落），请基于此情况规划下一步。\n"
        except Exception:
            pass
        return ""

    def _get_chat_history_text(self) -> str:
        prompt_cfg = getattr(self._config, "prompt", None)
        stream_format = getattr(prompt_cfg, "activity_stream_format", "narrative") if prompt_cfg else "narrative"
        max_entry_length = getattr(prompt_cfg, "max_entry_length", 500) if prompt_cfg else 500
        stream_format = (stream_format or "narrative").strip().lower()

        if stream_format == "table":
            chat_history_text = build_chat_history_table(
                self.session.observation_info.chat_history, self.bot_name, self.user_name, 30, max_entry_length)
        elif stream_format == "both":
            table = build_chat_history_table(
                self.session.observation_info.chat_history, self.bot_name, self.user_name, 30, max_entry_length)
            narrative = format_chat_history(
                self.session.observation_info.chat_history, self.bot_name, self.user_name, 30)
            chat_history_text = f"{table}\n\n{narrative}"
        else:
            chat_history_text = format_chat_history(
                self.session.observation_info.chat_history, self.bot_name, self.user_name, 30)

        new_count = self.session.observation_info.new_messages_count
        if new_count > 0:
            unprocessed = self.session.observation_info.unprocessed_messages
            if unprocessed:
                processed_times = set()
                for msg in self.session.observation_info.chat_history:
                    t = msg.get("time")
                    if t is not None:
                        processed_times.add(float(t))
                new_str, actual_count = format_new_messages(unprocessed, processed_times, self.bot_name)
                if new_str and actual_count > 0:
                    chat_history_text += f"\n--- 以下是 {actual_count} 条新消息 ---\n{new_str}"

        return chat_history_text or "还没有聊天记录。"

    def _build_action_history(self) -> Tuple[str, str]:
        prompt_cfg = getattr(self._config, "prompt", None)
        stream_format = getattr(prompt_cfg, "activity_stream_format", "narrative") if prompt_cfg else "narrative"
        max_entry_length = getattr(prompt_cfg, "max_entry_length", 500) if prompt_cfg else 500

        action_history_summary = "你最近执行的行动历史：\n"
        last_action_context = "关于你【上一次尝试】的行动：\n"

        try:
            action_history_list = (self.session.conversation_info.done_action or [])[-5:]
        except Exception:
            action_history_list = []

        if not action_history_list:
            return action_history_summary + "- 还没有执行过行动。\n", last_action_context + "- 这是你规划的第一个行动。\n"

        stream_format = (stream_format or "narrative").strip().lower()
        if stream_format == "table":
            action_history_summary = build_action_history_table(action_history_list, max_entry_length)
        elif stream_format == "both":
            table = build_action_history_table(action_history_list, max_entry_length)
            narrative = self._build_narrative_action_history(action_history_list)
            action_history_summary = f"{table}\n\n{narrative}"
        else:
            action_history_summary = self._build_narrative_action_history(action_history_list)

        last = action_history_list[-1]
        if isinstance(last, dict):
            action_type = last.get("action", "未知")
            plan_reason = last.get("plan_reason", "未知规划原因")
            status = last.get("status", "未知")
            final_reason = last.get("final_reason", "")
            last_action_context += f"- 上次【规划】的行动是: '{action_type}'\n- 当时规划的【原因】是: {plan_reason}\n"
            if status == "done":
                last_action_context += "- 该行动已【成功执行】。\n"
            elif status == "recall":
                last_action_context += f"- 但该行动最终【未能执行/被取消】。\n- 【重要】失败原因: {final_reason or '未明确记录'}\n"
            else:
                last_action_context += f"- 该行动当前状态: {status}\n"

        return action_history_summary, last_action_context

    def _build_narrative_action_history(self, action_history_list: list) -> str:
        summary = "你最近执行的行动历史：\n"
        for action_data in action_history_list:
            if isinstance(action_data, dict):
                action_type = action_data.get("action", "未知")
                status = action_data.get("status", "未知")
                final_reason = action_data.get("final_reason", "")
                action_time = action_data.get("time", "")
                reason_text = f", 失败原因: {final_reason}" if final_reason else ""
                summary += f"- 时间:{action_time}, 行动:'{action_type}', 状态:{status}{reason_text}\n"
        return summary

    async def _build_tool_info(self) -> str:
        if not self._config.tool.enabled or not self._config.tool.enable_in_planner:
            return ""
        try:
            from .context_builder import PFCContextBuilder
            builder = PFCContextBuilder(self.session.stream_id, self._config)
            chat_history_text = format_chat_history(
                self.session.observation_info.chat_history, self.bot_name, self.user_name, 10)
            target_message = ""
            if self.session.observation_info.chat_history:
                target_message = self.session.observation_info.chat_history[-1].get("content", "")
            return await builder.build_tool_info(chat_history_text, self.user_name, target_message, True)
        except Exception as e:
            logger.error(f"[PFC][{self.user_name}] 构建工具信息失败: {e}")
            return ""