"""PFC 回复生成器模块 - 根据不同行动类型生成回复内容 (GPL-3.0)"""

import time
from typing import List, Dict, Any, TYPE_CHECKING

from src.common.logger import get_logger
from src.plugin_system.apis import llm_api
from src.config.config import global_config
from .models import ObservationInfo, ConversationInfo
from .shared import PersonalityHelper, get_current_time_str, translate_timestamp, build_goals_string, build_knowledge_string

if TYPE_CHECKING:
    from .plugin import PFCConfig

logger = get_logger("PFC-Replyer")

_INAPPROPRIATE_PATTERNS = ["作为AI", "作为一个AI", "作为人工智能", "我是AI", "我是一个AI", "我是人工智能", "抱歉，我无法", "对不起，我不能"]


def check_basic_reply_quality(reply: str, max_length: int = 500) -> tuple[bool, str]:
    if not reply or len(reply.strip()) == 0:
        return False, "回复为空"
    if len(reply) > max_length:
        return False, "回复过长"
    for pattern in _INAPPROPRIATE_PATTERNS:
        if pattern in reply:
            return False, f"包含不当内容: {pattern}"
    return True, ""


def check_reply_similarity(reply: str, chat_history: list, threshold: float = 0.8) -> tuple[bool, str]:
    if not chat_history:
        return True, ""
    for msg in reversed(chat_history[-5:]):
        if msg.get("type") == "bot_message":
            content = msg.get("content", "")
            if content == reply:
                return False, "回复内容与你上一条发言完全相同"
            import difflib
            ratio = difflib.SequenceMatcher(None, reply, content).ratio()
            if ratio > threshold:
                return False, f"回复内容与你上一条发言高度相似 (相似度 {ratio:.2f})"
            break
    return True, ""


PROMPT_DIRECT_REPLY = """{persona_text}

【回复风格要求】
{reply_style}

【当前时间】
{current_time_str}

现在你在参与一场QQ私聊，请根据以下信息生成一条回复：

当前对话目标：{goals_str}

{knowledge_info_str}
{tool_info_str}

最近的聊天记录：
{chat_history_text}

请根据上述信息回复对方。要求：符合对话目标和你的性格特征，通俗易懂，自然流畅，简短（通常20字以内）。
请直接输出回复内容，不需要任何额外格式。"""

PROMPT_SEND_NEW_MESSAGE = """{persona_text}

【回复风格要求】
{reply_style}

【当前时间】
{current_time_str}

现在你在参与一场QQ私聊，**刚刚你已经发送了一条或多条消息**，现在请再发一条新消息：

当前对话目标：{goals_str}

{knowledge_info_str}
{tool_info_str}

最近的聊天记录：
{chat_history_text}

请继续发一条新消息（补充、深入话题或追问）。要求：符合对话目标，与之前消息自然衔接，简短（通常20字以内）。
请直接输出回复内容，不需要任何额外格式。"""

PROMPT_FAREWELL = """{persona_text}

【回复风格要求】
{reply_style}

【当前时间】
{current_time_str}

你在参与一场 QQ 私聊，现在对话似乎已经结束，你决定再发一条最后的消息来圆满结束。

最近的聊天记录：
{chat_history_text}

请构思一条简短、自然、符合你人设的告别消息。
请直接输出最终的告别消息内容，不需要任何额外格式。"""


class ReplyGenerator:
    """回复生成器"""

    def __init__(self, session, user_name: str):
        from .plugin import get_config
        from .session import PFCSession
        self.session: PFCSession = session
        self.user_name = user_name
        self.config = get_config()
        self._personality_helper = PersonalityHelper(user_name)
        self.bot_name = self._personality_helper.bot_name

    async def generate(self, action_type: str) -> str:
        prompt_params = await self._build_prompt_params(self.session.observation_info, self.session.conversation_info)
        prompt_template = {"send_new_message": PROMPT_SEND_NEW_MESSAGE, "say_goodbye": PROMPT_FAREWELL}.get(action_type, PROMPT_DIRECT_REPLY)
        prompt = prompt_template.format(**prompt_params)

        try:
            models = llm_api.get_available_models()
            model_name = "replyer_private" if self.config.prompt.inject_system_prompt else "utils"
            model_config = models.get(model_name)
            if not model_config:
                return ""

            success, response, _, _ = await llm_api.generate_with_model(
                prompt=prompt, model_config=model_config, request_type="pfc.reply_generation")

            if not success or not response:
                return ""
            return self._clean_response(response)
        except Exception as e:
            logger.error(f"[私聊][{self.user_name}]生成回复时出错: {e}")
            return ""

    async def _build_prompt_params(self, observation_info: ObservationInfo, conversation_info: ConversationInfo) -> Dict[str, str]:
        personality_info = await self._personality_helper.get_personality_info()
        goals_str = build_goals_string(conversation_info.goal_list)
        knowledge_info_str = build_knowledge_string(getattr(conversation_info, 'knowledge_list', None))
        chat_history_text = await self._build_chat_history_text(observation_info)
        tool_info_str = await self._build_tool_info(chat_history_text, observation_info)
        
        # 添加会话中的工具结果
        tool_results_str = self._build_tool_results_string(conversation_info)
        if tool_results_str:
            tool_info_str = f"{tool_info_str}\n\n{tool_results_str}" if tool_info_str else tool_results_str

        return {
            "persona_text": personality_info,
            "goals_str": goals_str,
            "knowledge_info_str": knowledge_info_str,
            "tool_info_str": tool_info_str,
            "chat_history_text": chat_history_text,
            "reply_style": self._personality_helper.get_reply_style(),
            "current_time_str": get_current_time_str(),
        }

    def _build_tool_results_string(self, conversation_info: ConversationInfo) -> str:
        """构建工具结果字符串"""
        tool_results = getattr(conversation_info, 'tool_results', None)
        if not tool_results:
            return ""
        
        # 只显示最近的工具结果
        recent_results = tool_results[-5:]
        if not recent_results:
            return ""
        
        parts = ["### 🔧 最近的工具执行结果"]
        for result in recent_results:
            tool_name = result.get("tool_name", "unknown")
            content = result.get("content", "")
            # 截断过长的内容
            if len(content) > 300:
                content = content[:300] + "..."
            parts.append(f"- **{tool_name}**: {content}")
        
        return "\n".join(parts)

    async def _build_tool_info(self, chat_history_text: str, observation_info: ObservationInfo) -> str:
        if not self.config.tool.enabled or not self.config.tool.enable_in_replyer:
            return ""
        try:
            from .context_builder import PFCContextBuilder
            builder = PFCContextBuilder(self.session.stream_id, self.config)
            target_message = observation_info.chat_history[-1].get("content", "") if observation_info.chat_history else ""
            return await builder.build_tool_info(chat_history_text, self.user_name, target_message, True)
        except Exception as e:
            logger.error(f"[私聊][{self.user_name}] 构建工具信息失败: {e}")
            return ""

    async def _build_chat_history_text(self, observation_info: ObservationInfo) -> str:
        chat_history_text = observation_info.chat_history_str
        if observation_info.new_messages_count > 0 and observation_info.unprocessed_messages:
            new_messages_str = self._format_messages(observation_info.unprocessed_messages)
            if new_messages_str:
                chat_history_text += f"\n--- 以下是 {observation_info.new_messages_count} 条新消息 ---\n{new_messages_str}"
        return chat_history_text or "还没有聊天记录。"

    def _format_messages(self, messages: List[Dict[str, Any]], timestamp_mode: str = "relative") -> str:
        if not messages:
            return ""
        formatted_blocks = []
        for msg in messages:
            sender = msg.get("sender", {})
            sender_name = sender.get("nickname", "未知用户")
            user_name = msg.get("user_name", sender_name)
            content = msg.get("processed_plain_text", msg.get("content", ""))
            timestamp = msg.get("time", time.time())
            user_id = sender.get("user_id", msg.get("user_id", ""))
            if global_config and global_config.bot and str(user_id) == str(global_config.bot.qq_account):
                sender_name = f"{self.bot_name}(你)"
            else:
                sender_name = user_name or sender_name
            readable_time = translate_timestamp(timestamp, mode=timestamp_mode)
            formatted_blocks.append(f"{readable_time} {sender_name} 说:")
            if content:
                stripped = content.strip()
                if stripped:
                    if stripped.endswith("。"):
                        stripped = stripped[:-1]
                    formatted_blocks.append(f"{stripped};")
            formatted_blocks.append("")
        return "\n".join(formatted_blocks).strip()

    async def check_reply(self, reply: str, goal: str) -> tuple[bool, str, bool]:
        valid, reason = check_basic_reply_quality(reply)
        if not valid:
            return False, reason, True
        valid, reason = check_reply_similarity(reply, self.session.observation_info.chat_history)
        if not valid:
            return False, reason, True
        return True, "回复检查通过", False

    def _clean_response(self, response: str) -> str:
        if not response:
            return ""
        content = response.strip()
        if (content.startswith('"') and content.endswith('"')) or (content.startswith("'") and content.endswith("'")):
            content = content[1:-1]
        for prefix in ["回复：", "回复:", "Reply:", "reply:", "消息：", "消息:", "Message:", "message:"]:
            if content.startswith(prefix):
                content = content[len(prefix):].strip()
                break
        return content


class ReplyChecker:
    """回复检查器"""

    def __init__(self, stream_id: str, private_name: str, config: "PFCConfig"):
        self.stream_id = stream_id
        self.private_name = private_name
        self.config = config
        self.checker_config = config.reply_checker
        self.max_retries = self.checker_config.max_retries

    async def check(self, reply: str, goal: str, chat_history: List[Dict[str, Any]],
                   chat_history_str: str, retry_count: int = 0) -> tuple[bool, str, bool]:
        if not self.checker_config.enabled:
            return True, "检查器已禁用，直接通过", False

        valid, reason = check_basic_reply_quality(reply)
        if not valid:
            return False, reason, True

        valid, reason = check_reply_similarity(reply, chat_history, self.checker_config.similarity_threshold)
        if not valid:
            return False, f"被逻辑检查拒绝：{reason}", True

        if self.checker_config.use_llm_check:
            return await self._llm_check(reply, goal, chat_history_str, retry_count)

        if retry_count >= self.max_retries:
            return True, "重试次数过多，接受当前回复", False
        return True, "回复检查通过", False

    async def _llm_check(self, reply: str, goal: str, chat_history_str: str, retry_count: int) -> tuple[bool, str, bool]:
        prompt = f"""你是一个聊天逻辑检查器，请检查以下回复是否合适：

当前对话目标：{goal}
最新的对话记录：
{chat_history_str}

待检查的消息：
{reply}

请检查：1.是否符合目标 2.是否与记录一致 3.是否重复发言 4.是否违规 5.是否通俗易懂 6.是否过于冗长

请以JSON格式输出：{{"suitable": true/false, "reason": "原因", "need_replan": true/false}}"""

        try:
            models = llm_api.get_available_models()
            checker_config = models.get("utils")
            if not checker_config:
                return True, "LLM 检查跳过（无模型配置）", False

            success, content, _, _ = await llm_api.generate_with_model(
                prompt=prompt, model_config=checker_config, request_type="pfc.reply_check")

            if not success or not content:
                return True, "LLM 检查跳过（调用失败）", False
            return self._parse_llm_response(content, retry_count)
        except Exception as e:
            logger.error(f"[私聊][{self.private_name}]LLM 检查时出错: {e}")
            return False if retry_count >= self.max_retries else False, "检查过程出错", retry_count >= self.max_retries

    def _parse_llm_response(self, content: str, retry_count: int) -> tuple[bool, str, bool]:
        import json
        import re
        content = content.strip()
        try:
            result = json.loads(content)
        except json.JSONDecodeError:
            json_match = re.search(r"\{[^{}]*\}", content)
            if json_match:
                try:
                    result = json.loads(json_match.group())
                except json.JSONDecodeError:
                    return self._fallback_parse(content, retry_count)
            else:
                return self._fallback_parse(content, retry_count)

        suitable = result.get("suitable")
        reason = result.get("reason", "未提供原因")
        need_replan = result.get("need_replan", False)

        if isinstance(suitable, str):
            suitable = suitable.lower() == "true"
        if suitable is None:
            suitable = "不合适" not in reason.lower() and "违规" not in reason.lower()

        if not suitable:
            if retry_count >= self.max_retries:
                return False, f"多次重试后仍不合适: {reason}", True
            return False, reason, False
        return suitable, reason, need_replan

    def _fallback_parse(self, content: str, retry_count: int) -> tuple[bool, str, bool]:
        is_suitable = "不合适" not in content.lower() and "违规" not in content.lower()
        reason = content[:100] if content else "无法解析响应"
        need_replan = "重新规划" in content.lower() or "目标不适合" in content.lower()
        return is_suitable, reason, need_replan