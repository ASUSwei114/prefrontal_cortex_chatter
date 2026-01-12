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

本项目遵循 GNU General Public License v3.0 许可证。
详见 LICENSE 文件。

================================================================================

负责根据当前对话状态规划下一步行动
"""

import time
import datetime
from typing import Tuple, Optional

from src.common.logger import get_logger
from src.config.config import global_config
from src.individuality.individuality import get_individuality
from src.plugin_system.apis import llm_api

from .session import PFCSession
from .utils import get_items_from_json

logger = get_logger("pfc_planner")


# --- 定义 Prompt 模板 ---

# Prompt(1): 首次回复或非连续回复时的决策 Prompt
PROMPT_INITIAL_REPLY = """{persona_text}。现在你在参与一场QQ私聊，请根据以下【所有信息】审慎且灵活的决策下一步行动，可以回复，可以倾听，可以调取知识，甚至可以屏蔽对方：

【当前时间】
{current_time_str}

【当前对话目标】
{goals_str}
{knowledge_info_str}

【最近行动历史概要】
{action_history_summary}
【上一次行动的详细情况和结果】
{last_action_context}
【时间和超时提示】
{time_info}{time_since_last_bot_message_info}{timeout_context}
【最近的对话记录】(包括你已成功发送的消息 和 新收到的消息)
{chat_history_text}

------
可选行动类型以及解释：
fetch_knowledge: 需要调取知识或记忆，当需要专业知识或特定信息时选择，对方若提到你不太认识的人名或实体也可以尝试选择
listening: 倾听对方发言，当你认为对方话才说到一半，发言明显未结束时选择
direct_reply: 直接回复对方
rethink_goal: 思考一个对话目标，当你觉得目前对话需要目标，或当前目标不再适用，或话题卡住时选择。注意私聊的环境是灵活的，有可能需要经常选择
end_conversation: 结束对话，对方长时间没回复或者当你觉得对话告一段落时可以选择
block_and_ignore: 更加极端的结束对话方式，直接结束对话并在一段时间内无视对方所有发言（屏蔽），当对话让你感到十分不适，或你遭到各类骚扰时选择

请以JSON格式输出你的决策：
{{
    "action": "选择的行动类型 (必须是上面列表中的一个)",
    "reason": "选择该行动的详细原因 (必须有解释你是如何根据"上一次行动结果"、"对话记录"和自身设定人设做出合理判断的)"
}}

注意：请严格按照JSON格式输出，不要包含任何其他内容。"""

# Prompt(2): 上一次成功回复后，决定继续发言时的决策 Prompt
PROMPT_FOLLOW_UP = """{persona_text}。现在你在参与一场QQ私聊，刚刚你已经回复了对方，请根据以下【所有信息】审慎且灵活的决策下一步行动，可以继续发送新消息，可以等待，可以倾听，可以调取知识，甚至可以屏蔽对方：

【当前时间】
{current_time_str}

【当前对话目标】
{goals_str}
{knowledge_info_str}

【最近行动历史概要】
{action_history_summary}
【上一次行动的详细情况和结果】
{last_action_context}
【时间和超时提示】
{time_info}{time_since_last_bot_message_info}{timeout_context}
【最近的对话记录】(包括你已成功发送的消息 和 新收到的消息)
{chat_history_text}

------
可选行动类型以及解释：
fetch_knowledge: 需要调取知识，当需要专业知识或特定信息时选择，对方若提到你不太认识的人名或实体也可以尝试选择
wait: 暂时不说话，留给对方交互空间，等待对方回复（尤其是在你刚发言后、或上次发言因重复、发言过多被拒时、或不确定做什么时，这是不错的选择）
listening: 倾听对方发言（虽然你刚发过言，但如果对方立刻回复且明显话没说完，可以选择这个）
send_new_message: 发送一条新消息继续对话，允许适当的追问、补充、深入话题，或开启相关新话题。**但是避免在因重复被拒后立即使用，也不要在对方没有回复的情况下过多的"消息轰炸"或重复发言**
rethink_goal: 思考一个对话目标，当你觉得目前对话需要目标，或当前目标不再适用，或话题卡住时选择。注意私聊的环境是灵活的，有可能需要经常选择
end_conversation: 结束对话，对方长时间没回复或者当你觉得对话告一段落时可以选择
block_and_ignore: 更加极端的结束对话方式，直接结束对话并在一段时间内无视对方所有发言（屏蔽），当对话让你感到十分不适，或你遭到各类骚扰时选择

请以JSON格式输出你的决策：
{{
    "action": "选择的行动类型 (必须是上面列表中的一个)",
    "reason": "选择该行动的详细原因 (必须有解释你是如何根据"上一次行动结果"、"对话记录"和自身设定人设做出合理判断的。请说明你为什么选择继续发言而不是等待，以及打算发送什么类型的新消息连续发言，必须记录已经发言了几次)"
}}

注意：请严格按照JSON格式输出，不要包含任何其他内容。"""

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

        # 人格信息将在异步方法中获取
        self.personality_info: Optional[str] = None

        self.bot_name = global_config.bot.nickname if global_config else "Bot"
    
    async def _ensure_personality_info(self) -> str:
        """
        确保人格信息已加载（异步获取）
        
        Returns:
            人格信息字符串
        """
        if self.personality_info is None:
            try:
                individuality = get_individuality()
                base_personality = await individuality.get_personality_block()
                # 追加 background_story（包含人际关系等重要信息）
                background_story = self._get_background_story()
                if background_story:
                    self.personality_info = f"{base_personality}\n\n【背景信息】\n{background_story}"
                else:
                    self.personality_info = base_personality
                logger.debug(f"[PFC][{self.user_name}]获取人格信息成功: {self.personality_info[:50]}...")
            except Exception as e:
                logger.warning(f"[PFC][{self.user_name}]获取人格信息失败: {e}，尝试从配置读取")
                # 从配置文件读取人格信息作为备选
                self.personality_info = self._build_personality_from_config()
        return self.personality_info
    
    def _get_background_story(self) -> str:
        """
        获取背景故事（包含人际关系等信息）
        
        Returns:
            背景故事字符串
        """
        try:
            if global_config and hasattr(global_config, 'personality'):
                return getattr(global_config.personality, 'background_story', '') or ''
        except Exception:
            pass
        return ''
    
    def _build_personality_from_config(self) -> str:
        """
        从配置文件构建人格信息（备选方案）
        
        Returns:
            人格信息字符串
        """
        try:
            bot_name = global_config.bot.nickname if global_config else "Bot"
            alias_names = global_config.bot.alias_names if global_config else []
            personality_core = global_config.personality.personality_core if global_config else ""
            personality_side = global_config.personality.personality_side if global_config else ""
            identity = global_config.personality.identity if global_config else ""
            
            # 构建人格信息
            parts = [f"你的名字是{bot_name}"]
            if alias_names:
                parts.append(f"也有人叫你{','.join(alias_names)}")
            if personality_core:
                parts.append(f"你{personality_core}")
            if personality_side:
                parts.append(personality_side)
            if identity:
                parts.append(identity)
            
            result = "，".join(parts)
            logger.debug(f"[PFC][{self.user_name}]从配置构建人格信息: {result[:50]}...")
            return result
        except Exception as e:
            logger.error(f"[PFC][{self.user_name}]从配置构建人格信息失败: {e}")
            return "一个友善的AI助手"

    async def plan(self) -> Tuple[str, str]:
        """规划下一步行动

        Returns:
            Tuple[str, str]: (行动类型, 行动原因)
        """
        # 确保人格信息已加载
        personality_info = await self._ensure_personality_info()
        
        # 获取 Bot 上次发言时间信息
        time_since_last_bot_message_info = self._get_time_since_last_bot_message()

        # 获取超时提示信息
        timeout_context = self._get_timeout_context()

        # 构建通用 Prompt 参数
        goals_str = self._build_goals_str()
        knowledge_info_str = self._build_knowledge_info_str()
        chat_history_text = self._get_chat_history_text()
        persona_text = f"{personality_info}"
        action_history_summary, last_action_context = self._build_action_history()

        # 选择 Prompt
        last_successful_reply_action = self.session.conversation_info.last_successful_reply_action
        if last_successful_reply_action in ["direct_reply", "send_new_message"]:
            prompt_template = PROMPT_FOLLOW_UP
            logger.debug(f"[PFC][{self.user_name}] 使用 PROMPT_FOLLOW_UP (追问决策)")
        else:
            prompt_template = PROMPT_INITIAL_REPLY
            logger.debug(f"[PFC][{self.user_name}] 使用 PROMPT_INITIAL_REPLY (首次/非连续回复决策)")

        # 获取当前时间字符串
        current_time_str = self._get_current_time_str()
        
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

            # 验证 action 类型
            valid_actions = [
                "direct_reply",
                "send_new_message",
                "fetch_knowledge",
                "wait",
                "listening",
                "rethink_goal",
                "end_conversation",
                "block_and_ignore",
                "say_goodbye",
            ]
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

    def _get_current_time_str(self) -> str:
        """获取当前时间的人类可读格式"""
        now = datetime.datetime.now()
        
        # 获取星期几
        weekday_names = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
        weekday = weekday_names[now.weekday()]
        
        # 获取时间段描述
        hour = now.hour
        if 5 <= hour < 9:
            time_period = "早上"
        elif 9 <= hour < 12:
            time_period = "上午"
        elif 12 <= hour < 14:
            time_period = "中午"
        elif 14 <= hour < 18:
            time_period = "下午"
        elif 18 <= hour < 22:
            time_period = "晚上"
        else:
            time_period = "深夜"
        
        # 格式化时间字符串
        time_str = now.strftime(f"%Y年%m月%d日 {weekday} {time_period} %H:%M")
        return time_str

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

    def _build_goals_str(self) -> str:
        """构建对话目标字符串"""
        goals_str = ""
        try:
            goal_list = self.session.conversation_info.goal_list
            if goal_list:
                for goal_reason in goal_list:
                    if isinstance(goal_reason, dict):
                        goal = goal_reason.get("goal", "目标内容缺失")
                        reasoning = goal_reason.get("reasoning", "没有明确原因")
                    else:
                        goal = str(goal_reason)
                        reasoning = "没有明确原因"

                    goal = str(goal) if goal is not None else "目标内容缺失"
                    reasoning = str(reasoning) if reasoning is not None else "没有明确原因"
                    goals_str += f"- 目标：{goal}\n  原因：{reasoning}\n"

                if not goals_str:
                    goals_str = "- 目前没有明确对话目标，请考虑设定一个。\n"
            else:
                goals_str = "- 目前没有明确对话目标，请考虑设定一个。\n"
        except Exception as e:
            logger.error(f"[PFC][{self.user_name}] 构建对话目标字符串时出错: {e}")
            goals_str = "- 构建对话目标时出错。\n"

        return goals_str

    def _build_knowledge_info_str(self) -> str:
        """构建知识信息字符串"""
        knowledge_info_str = "【已获取的相关知识和记忆】\n"
        try:
            knowledge_list = self.session.conversation_info.knowledge_list
            if knowledge_list:
                recent_knowledge = knowledge_list[-5:]
                for i, knowledge_item in enumerate(recent_knowledge):
                    if isinstance(knowledge_item, dict):
                        query = knowledge_item.get("query", "未知查询")
                        knowledge = knowledge_item.get("knowledge", "无知识内容")
                        source = knowledge_item.get("source", "未知来源")
                        knowledge_snippet = knowledge[:2000] + "..." if len(knowledge) > 2000 else knowledge
                        knowledge_info_str += (
                            f"{i + 1}. 关于 '{query}' 的知识 (来源: {source}):\n   {knowledge_snippet}\n"
                        )
                    else:
                        knowledge_info_str += f"{i + 1}. 发现一条格式不正确的知识记录。\n"

                if not recent_knowledge:
                    knowledge_info_str += "- 暂无相关知识和记忆。\n"
            else:
                knowledge_info_str += "- 暂无相关知识记忆。\n"
        except Exception as e:
            logger.error(f"[PFC][{self.user_name}] 构建知识信息字符串时出错: {e}")
            knowledge_info_str += "- 处理知识列表时出错。\n"

        return knowledge_info_str

    def _get_chat_history_text(self) -> str:
        """获取聊天历史文本
        
        PFC 使用自定义的消息格式，使用相对时间格式让 LLM 理解时间上下文。
        
        重要：每次调用都重新计算相对时间，避免缓存导致时间不准确。
        """
        formatted_blocks = []
        
        # 历史消息 - 每次都重新计算相对时间
        for msg in self.session.observation_info.chat_history[-30:]:
            msg_type = msg.get("type", "")
            content = msg.get("content", "")
            msg_time = msg.get("time", time.time())

            # 使用相对时间格式（每次重新计算）
            readable_time = self._translate_timestamp(msg_time)

            if msg_type == "user_message":
                sender = msg.get("user_name", self.user_name)
                header = f"{readable_time} {sender} 说:"
            elif msg_type == "bot_message":
                header = f"{readable_time} {self.bot_name}(你) 说:"
            else:
                continue
            
            formatted_blocks.append(header)
            
            # 添加内容
            if content:
                stripped_content = content.strip()
                if stripped_content:
                    if stripped_content.endswith("。"):
                        stripped_content = stripped_content[:-1]
                    formatted_blocks.append(f"{stripped_content};")
            
            formatted_blocks.append("")  # 空行分隔

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
                
                new_blocks = []
                actual_new_count = 0
                for msg in unprocessed:
                    msg_time = msg.get("time", time.time())
                    if msg_time and msg_time in processed_times:
                        continue
                    
                    content = msg.get("content", "")
                    if not content:
                        continue
                    user_name = msg.get("user_name", "用户")
                    msg_type = msg.get("type", "")
                    
                    readable_time = self._translate_timestamp(msg_time)
                    
                    if msg_type == "bot_message":
                        header = f"{readable_time} {self.bot_name}(你) 说:"
                    else:
                        header = f"{readable_time} {user_name} 说:"
                    
                    new_blocks.append(header)
                    
                    stripped_content = content.strip()
                    if stripped_content:
                        if stripped_content.endswith("。"):
                            stripped_content = stripped_content[:-1]
                        new_blocks.append(f"{stripped_content};")
                    
                    new_blocks.append("")
                    actual_new_count += 1
                
                if new_blocks:
                    new_messages_str = "\n".join(new_blocks).strip()
                    formatted_blocks.append(f"--- 以下是 {actual_new_count} 条新消息 ---")
                    formatted_blocks.append(new_messages_str)

        chat_history_text = "\n".join(formatted_blocks).strip()
        
        if not chat_history_text:
            chat_history_text = "还没有聊天记录。"

        return chat_history_text
    
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
            import datetime
            return datetime.datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S")

    def _build_action_history(self) -> Tuple[str, str]:
        """构建行动历史和上一次行动结果"""
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
                action_history_summary += summary_line + "\n"

                if i == len(action_history_list) - 1:
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