"""
PFC - 行动规划器

================================================================================
版权声明 (Copyright Notice)
================================================================================

原始代码来源: MaiM-with-u (https://github.com/MaiM-with-u/MaiBot)
原始版本: 0.6.3-fix4
原始代码路径: src/plugins/PFC/
原始许可证: GNU General Public License v3.0

本文件由 ASUSwei114 (https://github.com/ASUSwei114) 于 2024年12月 修改移植至 MoFox_Bot 项目。

主要修改内容:
- 适配 MoFox_Bot 的 LLM API
- 重构人格信息获取逻辑
- 修复聊天历史构建问题
- 使用共享模块精简代码

本项目遵循 GNU General Public License v3.0 许可证。
详见 LICENSE 文件。

================================================================================

负责根据当前对话状态规划下一步行动
"""

import time
from typing import Tuple

from src.common.logger import get_logger
from src.config.config import global_config
from src.plugin_system.apis import llm_api

from .session import PFCSession
from .utils import get_items_from_json
from .shared import (
    PersonalityHelper,
    get_current_time_str,
    translate_timestamp,
    build_goals_string,
    build_knowledge_string,
    format_chat_history,
    format_new_messages,
    build_action_history_table,
    build_chat_history_table,
)

logger = get_logger("pfc_planner")


# --- 定义 Prompt 模板 ---

# 通用模板部分
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
{{
    "action": "选择的行动类型 (必须是上面列表中的一个)",
    "reason": "选择该行动的详细原因 ({reason_hint})"
}}

注意：请严格按照JSON格式输出，不要包含任何其他内容。"""

# 行动类型定义
_ACTIONS_BASE = """fetch_knowledge: 需要调取知识或记忆，当需要专业知识或特定信息时选择，对方若提到你不太认识的人名或实体也可以尝试选择
listening: 倾听对方发言，当你认为对方话才说到一半，发言明显未结束时选择
rethink_goal: 思考一个对话目标，当你觉得目前对话需要目标，或当前目标不再适用，或话题卡住时选择。注意私聊的环境是灵活的，有可能需要经常选择
end_conversation: 结束对话，对方长时间没回复或者当你觉得对话告一段落时可以选择"""

_ACTION_BLOCK = """block_and_ignore: 更加极端的结束对话方式，直接结束对话并在一段时间内无视对方所有发言（屏蔽），当对话让你感到十分不适，或你遭到各类骚扰时选择"""

_ACTION_DIRECT_REPLY = """direct_reply: 直接回复对方"""

_ACTION_FOLLOW_UP = """wait: 暂时不说话，留给对方交互空间，等待对方回复（尤其是在你刚发言后、或上次发言因重复、发言过多被拒时、或不确定做什么时，这是不错的选择）
send_new_message: 发送一条新消息继续对话，允许适当的追问、补充、深入话题，或开启相关新话题。**但是避免在因重复被拒后立即使用，也不要在对方没有回复的情况下过多的"消息轰炸"或重复发言**"""

_REASON_HINT_INITIAL = '必须有解释你是如何根据"上一次行动结果"、"对话记录"和自身设定人设做出合理判断的'
_REASON_HINT_FOLLOW_UP = '必须有解释你是如何根据"上一次行动结果"、"对话记录"和自身设定人设做出合理判断的。请说明你为什么选择继续发言而不是等待，以及打算发送什么类型的新消息连续发言，必须记录已经发言了几次'


def _build_planner_prompt(is_follow_up: bool, enable_block: bool) -> str:
    """构建规划器 Prompt"""
    if is_follow_up:
        intro = "{{persona_text}}。现在你在参与一场QQ私聊，刚刚你已经回复了对方，请根据以下【所有信息】审慎且灵活的决策下一步行动，可以继续发送新消息，可以等待，可以倾听，可以调取知识"
        actions = f"{_ACTION_FOLLOW_UP}\n{_ACTIONS_BASE}"
        reason_hint = _REASON_HINT_FOLLOW_UP
    else:
        intro = "{{persona_text}}。现在你在参与一场QQ私聊，请根据以下【所有信息】审慎且灵活的决策下一步行动，可以回复，可以倾听，可以调取知识"
        actions = f"{_ACTION_DIRECT_REPLY}\n{_ACTIONS_BASE}"
        reason_hint = _REASON_HINT_INITIAL
    
    if enable_block:
        intro += "，甚至可以屏蔽对方"
        actions += f"\n{_ACTION_BLOCK}"
    
    return f"{intro}：\n\n{_PROMPT_CONTEXT}\n可选行动类型以及解释：\n{actions}\n\n{_PROMPT_JSON_OUTPUT.format(reason_hint=reason_hint)}"


# 预构建的 Prompt 模板
PROMPT_INITIAL_REPLY_WITH_BLOCK = _build_planner_prompt(is_follow_up=False, enable_block=True)
PROMPT_INITIAL_REPLY_NO_BLOCK = _build_planner_prompt(is_follow_up=False, enable_block=False)
PROMPT_FOLLOW_UP_WITH_BLOCK = _build_planner_prompt(is_follow_up=True, enable_block=True)
PROMPT_FOLLOW_UP_NO_BLOCK = _build_planner_prompt(is_follow_up=True, enable_block=False)

# Prompt(3): 决定是否在结束对话前发送告别语
PROMPT_END_DECISION = """{persona_text}。刚刚你决定结束一场 QQ 私聊。

【你们之前的聊天记录】
{chat_history_text}

你觉得你们的对话已经完整结束了吗？有时候，在对话自然结束后再说点什么可能会有点奇怪，但有时也可能需要一条简短的消息来圆满结束。
如果觉得确实有必要再发一条简短、自然、符合你人设的告别消息（比如 "好，下次再聊~" 或 "嗯，先这样吧"），就输出 "yes"。
如果觉得当前状态下直接结束对话更好，没有必要再发消息，就输出 "no"。

请以 JSON 格式输出你的选择：
{{
    "say_bye": "yes/no",
    "reason": "选择 yes 或 no 的原因和内心想法 (简要说明)"
}}

注意：请严格按照 JSON 格式输出，不要包含任何其他内容。"""


class ActionPlanner:
    """行动规划器"""

    def __init__(self, session: PFCSession, user_name: str):
        self.session = session
        self.user_name = user_name

        # 使用共享的人格信息助手
        self._personality_helper = PersonalityHelper(user_name)
        self.bot_name = self._personality_helper.bot_name
        
        # 加载配置
        from .plugin import get_config
        self._config = get_config()

    async def plan(self) -> Tuple[str, str]:
        """规划下一步行动

        Returns:
            Tuple[str, str]: (行动类型, 行动原因)
        """
        # 使用共享模块获取人格信息
        personality_info = await self._personality_helper.get_personality_info()
        
        # 获取 Bot 上次发言时间信息
        time_since_last_bot_message_info = self._get_time_since_last_bot_message()

        # 获取超时提示信息
        timeout_context = self._get_timeout_context()

        # 构建通用 Prompt 参数（使用共享模块）
        goals_str = build_goals_string(self.session.conversation_info.goal_list)
        knowledge_info_str = build_knowledge_string(self.session.conversation_info.knowledge_list)
        chat_history_text = self._get_chat_history_text()
        persona_text = f"{personality_info}"
        action_history_summary, last_action_context = self._build_action_history()

        # ========== 新增：构建工具信息 ==========
        tool_info_str = await self._build_tool_info()
        # ========================================

        # 选择 Prompt（根据配置决定是否包含 block_and_ignore 动作）
        last_successful_reply_action = self.session.conversation_info.last_successful_reply_action
        # 使用 getattr 安全访问，兼容旧版配置文件
        enable_block = getattr(self._config.waiting, 'enable_block_action', True)
        
        if last_successful_reply_action in ["direct_reply", "send_new_message"]:
            if enable_block:
                prompt_template = PROMPT_FOLLOW_UP_WITH_BLOCK
                logger.debug(f"[PFC][{self.user_name}] 使用 PROMPT_FOLLOW_UP_WITH_BLOCK (追问决策)")
            else:
                prompt_template = PROMPT_FOLLOW_UP_NO_BLOCK
                logger.debug(f"[PFC][{self.user_name}] 使用 PROMPT_FOLLOW_UP_NO_BLOCK (追问决策，无屏蔽选项)")
        else:
            if enable_block:
                prompt_template = PROMPT_INITIAL_REPLY_WITH_BLOCK
                logger.debug(f"[PFC][{self.user_name}] 使用 PROMPT_INITIAL_REPLY_WITH_BLOCK (首次/非连续回复决策)")
            else:
                prompt_template = PROMPT_INITIAL_REPLY_NO_BLOCK
                logger.debug(f"[PFC][{self.user_name}] 使用 PROMPT_INITIAL_REPLY_NO_BLOCK (首次/非连续回复决策，无屏蔽选项)")

        # 获取当前时间字符串（使用共享模块）
        current_time_str = get_current_time_str()
        
        # 获取时间信息（与原版 ChatObserver.get_time_info() 保持一致）
        time_info = self.session.get_time_info()
        
        # 格式化最终的 Prompt
        prompt = prompt_template.format(
            persona_text=persona_text,
            goals_str=goals_str if goals_str.strip() else "- 目前没有明确对话目标，请考虑设定一个。",
            action_history_summary=action_history_summary,
            last_action_context=last_action_context,
            time_info=time_info,
            time_since_last_bot_message_info=time_since_last_bot_message_info,
            timeout_context=timeout_context,
            chat_history_text=chat_history_text if chat_history_text.strip() else "还没有聊天记录。",
            knowledge_info_str=knowledge_info_str,
            tool_info_str=tool_info_str if tool_info_str.strip() else "- 暂无工具信息",
            current_time_str=current_time_str,
        )

        logger.debug(f"[PFC][{self.user_name}] 发送到LLM的最终提示词:\n------\n{prompt[:500]}...\n------")

        try:
            # 调用 LLM
            models = llm_api.get_available_models()
            planner_config = models.get("planner") or models.get("normal")

            if not planner_config:
                logger.warning("[PFC] 未找到 planner 模型配置，使用默认等待")
                return "wait", "未找到模型配置"

            success, content, _, model_name = await llm_api.generate_with_model(
                prompt=prompt,
                model_config=planner_config,
                request_type="pfc.action_planning",
            )

            if not success or not content:
                logger.warning(f"[PFC] LLM 调用失败: {content}")
                return "wait", "LLM 调用失败"

            logger.debug(f"[PFC][{self.user_name}] LLM (行动规划) 原始返回内容: {content}")

            # 解析 JSON
            action_val, reason_val = get_items_from_json(
                content,
                "action",
                "reason",
                default="wait",
            )

            initial_action = action_val if action_val else "wait"
            initial_reason = reason_val if reason_val else "LLM未提供原因，默认等待"

            # 检查是否需要进行结束对话决策
            if initial_action == "end_conversation":
                return await self._handle_end_decision(persona_text, chat_history_text, initial_reason)

            # 验证 action 类型（根据配置决定是否包含 block_and_ignore）
            valid_actions = [
                "direct_reply",
                "send_new_message",
                "fetch_knowledge",
                "wait",
                "listening",
                "rethink_goal",
                "end_conversation",
                "say_goodbye",
            ]
            # 仅在启用时添加 block_and_ignore 到有效动作列表
            if self._config.waiting.enable_block_action:
                valid_actions.append("block_and_ignore")
            if initial_action not in valid_actions:
                logger.warning(f"[PFC][{self.user_name}] LLM返回了未知的行动类型: '{initial_action}'，强制改为 wait")
                initial_reason = f"(原始行动'{initial_action}'无效，已强制改为wait) {initial_reason}"
                initial_action = "wait"

            logger.info(f"[PFC][{self.user_name}] 规划的行动: {initial_action}")
            logger.info(f"[PFC][{self.user_name}] 行动原因: {initial_reason}")
            return initial_action, initial_reason

        except Exception as e:
            logger.error(f"[PFC][{self.user_name}] 规划行动时调用 LLM 或处理结果出错: {str(e)}")
            return "wait", f"行动规划处理中发生错误，暂时等待: {str(e)}"

    async def _handle_end_decision(
        self,
        persona_text: str,
        chat_history_text: str,
        initial_reason: str,
    ) -> Tuple[str, str]:
        """处理结束对话决策"""
        logger.info(f"[PFC][{self.user_name}] 初步规划结束对话，进入告别决策...")

        end_decision_prompt = PROMPT_END_DECISION.format(
            persona_text=persona_text,
            chat_history_text=chat_history_text,
        )

        try:
            models = llm_api.get_available_models()
            planner_config = models.get("planner") or models.get("normal")

            if not planner_config:
                return "end_conversation", initial_reason

            success, end_content, _, _ = await llm_api.generate_with_model(
                prompt=end_decision_prompt,
                model_config=planner_config,
                request_type="pfc.end_decision",
            )

            if not success or not end_content:
                return "end_conversation", initial_reason

            logger.debug(f"[PFC][{self.user_name}] LLM (结束决策) 原始返回内容: {end_content}")

            say_bye_val, end_reason_val = get_items_from_json(
                end_content,
                "say_bye",
                "reason",
                default="no",
            )

            say_bye_decision = (say_bye_val if say_bye_val else "no").lower()
            end_decision_reason = end_reason_val if end_reason_val else "未提供原因"

            if say_bye_decision == "yes":
                logger.info(f"[PFC][{self.user_name}] 结束决策: yes, 准备生成告别语. 原因: {end_decision_reason}")
                final_action = "say_goodbye"
                final_reason = f"决定发送告别语。决策原因: {end_decision_reason} (原结束理由: {initial_reason})"
                return final_action, final_reason
            else:
                logger.info(f"[PFC][{self.user_name}] 结束决策: no, 直接结束对话. 原因: {end_decision_reason}")
                return "end_conversation", initial_reason

        except Exception as e:
            logger.error(f"[PFC][{self.user_name}] 调用结束决策LLM或处理结果时出错: {str(e)}")
            return "end_conversation", initial_reason

    def _get_time_since_last_bot_message(self) -> str:
        """获取距离 Bot 上次发言的时间信息"""
        time_since_last_bot_message_info = ""
        try:
            chat_history = self.session.observation_info.chat_history

            for msg in reversed(chat_history):
                if msg.get("type") == "bot_message":
                    msg_time = msg.get("time", 0)
                    if msg_time:
                        time_diff = time.time() - msg_time
                        if time_diff < 60.0:
                            time_since_last_bot_message_info = (
                                f"提示：你上一条成功发送的消息是在 {time_diff:.1f} 秒前。\n"
                            )
                        break
        except Exception as e:
            logger.warning(f"[PFC][{self.user_name}] 获取 Bot 上次发言时间时出错: {e}")

        return time_since_last_bot_message_info

    def _get_timeout_context(self) -> str:
        """获取超时提示信息"""
        timeout_context = ""
        try:
            goal_list = self.session.conversation_info.goal_list
            if goal_list:
                last_goal_dict = goal_list[-1]
                if isinstance(last_goal_dict, dict) and "goal" in last_goal_dict:
                    last_goal_text = last_goal_dict["goal"]
                    if isinstance(last_goal_text, str) and "分钟，思考接下来要做什么" in last_goal_text:
                        try:
                            timeout_minutes_text = last_goal_text.split("，")[0].replace("你等待了", "")
                            timeout_context = f"重要提示：对方已经长时间（{timeout_minutes_text}）没有回复你的消息了（这可能代表对方繁忙/不想回复/没注意到你的消息等情况，或在对方看来本次聊天已告一段落），请基于此情况规划下一步。\n"
                        except Exception:
                            timeout_context = "重要提示：对方已经长时间没有回复你的消息了（这可能代表对方繁忙/不想回复/没注意到你的消息等情况，或在对方看来本次聊天已告一段落），请基于此情况规划下一步。\n"
        except Exception as e:
            logger.warning(f"[PFC][{self.user_name}] 检查超时目标时出错: {e}")

        return timeout_context

    def _get_chat_history_text(self) -> str:
        """获取聊天历史文本（使用共享模块）"""
        # 获取配置
        prompt_cfg = getattr(self._config, "prompt", None)
        stream_format = getattr(prompt_cfg, "activity_stream_format", "narrative") if prompt_cfg else "narrative"
        max_entry_length = getattr(prompt_cfg, "max_entry_length", 500) if prompt_cfg else 500
        
        stream_format = (stream_format or "narrative").strip().lower()
        
        # 根据配置选择格式
        if stream_format == "table":
            # 使用表格格式
            chat_history_text = build_chat_history_table(
                self.session.observation_info.chat_history,
                bot_name=self.bot_name,
                user_name=self.user_name,
                max_messages=30,
                max_cell_length=max_entry_length,
            )
        elif stream_format == "both":
            # 两种格式都给
            table_history = build_chat_history_table(
                self.session.observation_info.chat_history,
                bot_name=self.bot_name,
                user_name=self.user_name,
                max_messages=30,
                max_cell_length=max_entry_length,
            )
            narrative_history = format_chat_history(
                self.session.observation_info.chat_history,
                bot_name=self.bot_name,
                user_name=self.user_name,
                max_messages=30,
            )
            chat_history_text = "\n\n".join([table_history, narrative_history])
        else:
            # 默认使用线性叙事格式
            chat_history_text = format_chat_history(
                self.session.observation_info.chat_history,
                bot_name=self.bot_name,
                user_name=self.user_name,
                max_messages=30,
            )

        # 添加新消息（仅添加尚未在历史中的消息）
        new_messages_count = self.session.observation_info.new_messages_count
        if new_messages_count > 0:
            unprocessed = self.session.observation_info.unprocessed_messages
            if unprocessed:
                # 获取已处理消息的时间戳集合，用于去重
                processed_times = set()
                for msg in self.session.observation_info.chat_history:
                    msg_time = msg.get("time")
                    if msg_time:
                        processed_times.add(msg_time)
                
                # 使用共享模块格式化新消息
                new_messages_str, actual_new_count = format_new_messages(
                    unprocessed,
                    processed_times,
                    self.bot_name,
                )
                
                if new_messages_str and actual_new_count > 0:
                    chat_history_text += f"\n--- 以下是 {actual_new_count} 条新消息 ---\n{new_messages_str}"

        if not chat_history_text:
            chat_history_text = "还没有聊天记录。"

        return chat_history_text

    def _build_action_history(self) -> Tuple[str, str]:
        """构建行动历史和上一次行动结果"""
        # 获取配置
        prompt_cfg = getattr(self._config, "prompt", None)
        stream_format = getattr(prompt_cfg, "activity_stream_format", "narrative") if prompt_cfg else "narrative"
        max_entry_length = getattr(prompt_cfg, "max_entry_length", 500) if prompt_cfg else 500
        
        action_history_summary = "你最近执行的行动历史：\n"
        last_action_context = "关于你【上一次尝试】的行动：\n"

        action_history_list = []
        try:
            done_action = self.session.conversation_info.done_action
            if done_action:
                action_history_list = done_action[-5:]
        except Exception as e:
            logger.error(f"[PFC][{self.user_name}] 访问行动历史时出错: {e}")

        if not action_history_list:
            action_history_summary += "- 还没有执行过行动。\n"
            last_action_context += "- 这是你规划的第一个行动。\n"
        else:
            # 根据配置选择格式
            stream_format = (stream_format or "narrative").strip().lower()
            
            if stream_format == "table":
                # 使用表格格式
                action_history_summary = build_action_history_table(
                    action_history_list,
                    max_cell_length=max_entry_length
                )
            elif stream_format == "both":
                # 两种格式都给
                table_summary = build_action_history_table(
                    action_history_list,
                    max_cell_length=max_entry_length
                )
                narrative_summary = self._build_narrative_action_history(action_history_list)
                action_history_summary = "\n\n".join([table_summary, narrative_summary])
            else:
                # 默认使用线性叙事格式
                action_history_summary = self._build_narrative_action_history(action_history_list)
            
            # 构建上一次行动上下文（始终使用叙事格式）
            last_action_data = action_history_list[-1]
            if isinstance(last_action_data, dict):
                action_type = last_action_data.get("action", "未知")
                plan_reason = last_action_data.get("plan_reason", "未知规划原因")
                status = last_action_data.get("status", "未知")
                final_reason = last_action_data.get("final_reason", "")
                
                last_action_context += f"- 上次【规划】的行动是: '{action_type}'\n"
                last_action_context += f"- 当时规划的【原因】是: {plan_reason}\n"
                if status == "done":
                    last_action_context += "- 该行动已【成功执行】。\n"
                elif status == "recall":
                    last_action_context += "- 但该行动最终【未能执行/被取消】。\n"
                    if final_reason:
                        last_action_context += f'- 【重要】失败/取消的具体原因是: "{final_reason}"\n'
                    else:
                        last_action_context += "- 【重要】失败/取消原因未明确记录。\n"
                else:
                    last_action_context += f"- 该行动当前状态: {status}\n"

        return action_history_summary, last_action_context
    
    def _build_narrative_action_history(self, action_history_list: list) -> str:
        """构建线性叙事格式的行动历史"""
        summary = "你最近执行的行动历史：\n"
        
        for i, action_data in enumerate(action_history_list):
            action_type = "未知"
            plan_reason = "未知"
            status = "未知"
            final_reason = ""
            action_time = ""

            if isinstance(action_data, dict):
                action_type = action_data.get("action", "未知")
                plan_reason = action_data.get("plan_reason", "未知规划原因")
                status = action_data.get("status", "未知")
                final_reason = action_data.get("final_reason", "")
                action_time = action_data.get("time", "")

            reason_text = f", 失败/取消原因: {final_reason}" if final_reason else ""
            summary_line = f"- 时间:{action_time}, 尝试行动:'{action_type}', 状态:{status}{reason_text}"
            summary += summary_line + "\n"
        
        return summary
    
    async def _build_tool_info(self) -> str:
        """构建工具信息块
        
        使用 context_builder 中的 PFCContextBuilder 构建工具信息
        如果配置禁用了工具调用，则返回空字符串
        """
        # 检查是否启用工具调用
        if not self._config.tool.enabled:
            return ""
        
        # 检查是否在规划器中启用
        if not self._config.tool.enable_in_planner:
            return ""
        
        try:
            from .context_builder import PFCContextBuilder
            
            builder = PFCContextBuilder(self.session.stream_id, self._config)
            
            # 获取聊天历史文本
            chat_history_text = format_chat_history(
                self.session.observation_info.chat_history,
                bot_name=self.bot_name,
                user_name=self.user_name,
                max_messages=10,
            )
            
            # 获取最后一条消息作为目标消息
            target_message = ""
            if self.session.observation_info.chat_history:
                last_msg = self.session.observation_info.chat_history[-1]
                target_message = last_msg.get("content", "")
            
            # 构建上下文
            context_data = await builder.build_tool_info(
                chat_history=chat_history_text,
                sender_name=self.user_name,
                target_message=target_message,
                enable_tool=True,
            )
            
            return context_data
            
        except Exception as e:
            logger.error(f"[PFC][{self.user_name}] 构建工具信息失败: {e}")
            import traceback
            traceback.print_exc()
            return ""