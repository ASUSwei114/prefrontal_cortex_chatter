"""
PFC回复生成器模块

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
- 恢复原版 Prompt 模板的"简短20字以内"约束
- 修复聊天历史构建问题
- 使用共享模块精简代码

本项目遵循 GNU General Public License v3.0 许可证。
详见 LICENSE 文件。

================================================================================

负责根据不同的行动类型生成相应的回复内容
"""

import time
from typing import List, Dict, Any
from src.common.logger import get_logger
from src.plugin_system.apis import llm_api
from src.config.config import global_config

from .models import ObservationInfo, ConversationInfo
from .shared import (
    PersonalityHelper,
    get_current_time_str,
    translate_timestamp,
    build_goals_string,
    build_knowledge_string,
)

# PFCConfig 类型注解使用 TYPE_CHECKING
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from .plugin import PFCConfig

logger = get_logger("PFC-Replyer")


# ============== 共享检查逻辑 ==============

_INAPPROPRIATE_PATTERNS = [
    "作为AI", "作为一个AI", "作为人工智能",
    "我是AI", "我是一个AI", "我是人工智能",
    "抱歉，我无法", "对不起，我不能"
]


def check_basic_reply_quality(reply: str, max_length: int = 500) -> tuple[bool, str]:
    """基本回复质量检查"""
    if not reply or len(reply.strip()) == 0:
        return False, "回复为空"
    if len(reply) > max_length:
        return False, "回复过长"
    for pattern in _INAPPROPRIATE_PATTERNS:
        if pattern in reply:
            return False, f"包含不当内容: {pattern}"
    return True, ""


def check_reply_similarity(reply: str, chat_history: list, threshold: float = 0.8) -> tuple[bool, str]:
    """检查回复与历史消息的相似度"""
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


# ============== Prompt 模板 ==============

# Prompt for direct_reply (首次回复)
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


请根据上述信息，结合聊天记录，回复对方。该回复应该：
1. 符合对话目标，以"你"的角度发言（不要自己与自己对话！）
2. 符合你的性格特征和身份细节
3. 严格遵循上述回复风格要求
4. 通俗易懂，自然流畅，像正常聊天一样，简短（通常20字以内，除非特殊情况）
5. 可以适当利用相关知识，但不要生硬引用
6. 自然、得体，结合聊天记录逻辑合理，且没有重复表达同质内容

请注意把握聊天内容，不要回复的太有条理，可以有个性。请分清"你"和对方说的话，不要把"你"说的话当做对方说的话，这是你自己说的话。
可以回复得自然随意自然一些，就像真人一样，注意把握聊天内容，整体风格可以平和、简短，不要刻意突出自身学科背景，不要说你说过的话，可以简短，多简短都可以，但是避免冗长。
请你注意不要输出多余内容(包括前后缀，冒号和引号，括号，表情等)，只输出回复内容。
不要输出多余内容(包括前后缀，冒号和引号，括号，表情包，at或 @等 )。

请直接输出回复内容，不需要任何额外格式。"""

# Prompt for send_new_message (追问/补充)
PROMPT_SEND_NEW_MESSAGE = """{persona_text}

【回复风格要求】
{reply_style}

【当前时间】
{current_time_str}

现在你在参与一场QQ私聊，**刚刚你已经发送了一条或多条消息**，现在请根据以下信息再发一条新消息：

当前对话目标：{goals_str}

{knowledge_info_str}
{tool_info_str}

最近的聊天记录：
{chat_history_text}


请根据上述信息，结合聊天记录，继续发一条新消息（例如对之前消息的补充，深入话题，或追问等等）。该消息应该：
1. 符合对话目标，以"你"的角度发言（不要自己与自己对话！）
2. 符合你的性格特征和身份细节
3. 严格遵循上述回复风格要求
4. 通俗易懂，自然流畅，像正常聊天一样，简短（通常20字以内，除非特殊情况）
5. 可以适当利用相关知识，但不要生硬引用
6. 跟之前你发的消息自然的衔接，逻辑合理，且没有重复表达同质内容或部分重叠内容

请注意把握聊天内容，不用太有条理，可以有个性。请分清"你"和对方说的话，不要把"你"说的话当做对方说的话，这是你自己说的话。
这条消息可以自然随意自然一些，就像真人一样，注意把握聊天内容，整体风格可以平和、简短，不要刻意突出自身学科背景，不要说你说过的话，可以简短，多简短都可以，但是避免冗长。
请你注意不要输出多余内容(包括前后缀，冒号和引号，括号，表情等)，只输出消息内容。
不要输出多余内容(包括前后缀，冒号和引号，括号，表情包，at或 @等 )。

请直接输出回复内容，不需要任何额外格式。"""

# Prompt for say_goodbye (告别语生成)
PROMPT_FAREWELL = """{persona_text}

【回复风格要求】
{reply_style}

【当前时间】
{current_time_str}

你在参与一场 QQ 私聊，现在对话似乎已经结束，你决定再发一条最后的消息来圆满结束。

最近的聊天记录：
{chat_history_text}

请根据上述信息，结合聊天记录，构思一条**简短、自然、符合你人设**的最后的消息。
这条消息应该：
1. 从你自己的角度发言。
2. 符合你的性格特征和身份细节。
3. 严格遵循上述回复风格要求。
4. 通俗易懂，自然流畅，通常很简短。
5. 自然地为这场对话画上句号，避免开启新话题或显得冗长、刻意。

不要输出多余内容（包括前后缀、冒号、引号、括号、表情包、at或@等）。

请直接输出最终的告别消息内容，不需要任何额外格式。"""


class ReplyGenerator:
    """
    回复生成器
    
    负责根据不同的行动类型（direct_reply, send_new_message, say_goodbye）
    生成相应的回复内容
    """
    
    def __init__(self, session, user_name: str):
        """
        初始化回复生成器
        
        Args:
            session: PFCSession 会话对象
            user_name: 用户名称
        """
        from .plugin import get_config
        from .session import PFCSession
        
        self.session: PFCSession = session
        self.user_name = user_name
        self.config = get_config()
        
        # 使用共享的人格信息助手
        self._personality_helper = PersonalityHelper(user_name)
        self.bot_name = self._personality_helper.bot_name
        
        logger.debug(f"[私聊][{user_name}]回复生成器初始化完成")
    
    async def generate(self, action_type: str) -> str:
        """
        生成回复
        
        Args:
            action_type: 当前执行的动作类型
            
        Returns:
            生成的回复内容
        """
        observation_info = self.session.observation_info
        conversation_info = self.session.conversation_info
        
        logger.debug(
            f"[私聊][{self.user_name}]开始生成回复 "
            f"(动作类型: {action_type})：当前目标: {conversation_info.goal_list}"
        )
        
        # 构建通用 Prompt 参数
        prompt_params = await self._build_prompt_params(
            observation_info,
            conversation_info
        )
        
        # 选择对应的 Prompt 模板
        prompt_template = self._select_prompt_template(action_type)
        
        # 格式化最终的 Prompt
        prompt = prompt_template.format(**prompt_params)
        
        logger.debug(
            f"[私聊][{self.user_name}]发送到LLM的生成提示词:\n"
            f"------\n{prompt[:500]}...\n------"
        )
        
        # 调用 LLM 生成
        try:
            models = llm_api.get_available_models()
            
            # 根据配置决定是否注入系统提示词
            # replyer_private 配置会在 LLMRequest 中自动注入 SYSTEM_PROMPT
            # utils 配置不会注入系统提示词
            if self.config.prompt.inject_system_prompt:
                model_name = "replyer_private"
                logger.info(f"[PFC] 已启用系统提示词注入，使用 {model_name} 模型")
            else:
                model_name = "utils"
                logger.debug(f"[PFC] 未启用系统提示词注入，使用 {model_name} 模型")
            
            model_config = models.get(model_name)
            
            if not model_config:
                logger.warning(f"[PFC] 未找到 {model_name} 模型配置")
                return ""
            
            success, response, _, _ = await llm_api.generate_with_model(
                prompt=prompt,
                model_config=model_config,
                request_type="pfc.reply_generation",
            )
            
            if not success or not response:
                logger.warning(f"[私聊][{self.user_name}]LLM调用失败: {response}")
                return ""
            
            content = self._clean_response(response)
            logger.debug(f"[私聊][{self.user_name}]生成的回复: {content}")
            
            return content
            
        except Exception as e:
            logger.error(f"[私聊][{self.user_name}]生成回复时出错: {e}")
            return ""
    
    async def _build_prompt_params(
        self,
        observation_info: ObservationInfo,
        conversation_info: ConversationInfo
    ) -> Dict[str, str]:
        """
        构建Prompt参数（使用共享模块）
        
        Args:
            observation_info: 观察信息
            conversation_info: 对话信息
            
        Returns:
            Prompt参数字典
        """
        # 使用共享模块获取人格信息
        personality_info = await self._personality_helper.get_personality_info()
        
        # 使用共享模块构建对话目标字符串
        goals_str = build_goals_string(conversation_info.goal_list)
        
        # 使用共享模块构建知识信息字符串
        knowledge_info_str = build_knowledge_string(
            getattr(conversation_info, 'knowledge_list', None)
        )
        
        # 构建聊天历史文本
        chat_history_text = await self._build_chat_history_text(observation_info)
        
        # 构建人设文本
        persona_text = f"{personality_info}"
        
        # 使用共享模块获取回复风格
        reply_style = self._personality_helper.get_reply_style()
        
        # 使用共享模块获取当前时间字符串
        current_time_str = get_current_time_str()
        
        # ========== 新增：构建工具信息 ==========
        tool_info_str = await self._build_tool_info(chat_history_text, observation_info)
        # ========================================
        
        return {
            "persona_text": persona_text,
            "goals_str": goals_str,
            "knowledge_info_str": knowledge_info_str,
            "tool_info_str": tool_info_str,
            "chat_history_text": chat_history_text,
            "reply_style": reply_style,
            "current_time_str": current_time_str,
        }
    
    async def _build_tool_info(
        self,
        chat_history_text: str,
        observation_info: ObservationInfo
    ) -> str:
        """构建工具信息块
        
        使用 context_builder 中的 PFCContextBuilder 构建工具信息
        如果配置禁用了工具调用，则返回空字符串
        """
        # 检查是否启用工具调用
        if not self.config.tool.enabled:
            return ""
        
        # 检查是否在回复生成器中启用
        if not self.config.tool.enable_in_replyer:
            return ""
        
        try:
            from .context_builder import PFCContextBuilder
            
            builder = PFCContextBuilder(self.session.stream_id, self.config)
            
            # 获取最后一条消息作为目标消息
            target_message = ""
            if observation_info.chat_history:
                last_msg = observation_info.chat_history[-1]
                target_message = last_msg.get("content", "")
            
            # 构建工具信息
            tool_info = await builder.build_tool_info(
                chat_history=chat_history_text,
                sender_name=self.user_name,
                target_message=target_message,
                enable_tool=True,
            )
            
            return tool_info
            
        except Exception as e:
            logger.error(f"[私聊][{self.user_name}] 构建工具信息失败: {e}")
            import traceback
            traceback.print_exc()
            return ""
    
    async def _build_chat_history_text(
        self,
        observation_info: ObservationInfo
    ) -> str:
        """
        构建聊天历史文本
        
        PFC 使用自定义的消息格式，使用简单格式化方法。
        
        Args:
            observation_info: 观察信息
            
        Returns:
            格式化的聊天历史文本
        """
        chat_history_text = observation_info.chat_history_str
        
        # 如果有新消息，添加新消息部分
        if (observation_info.new_messages_count > 0 and
            observation_info.unprocessed_messages):
            
            new_messages_str = self._format_messages(
                observation_info.unprocessed_messages
            )
            
            if new_messages_str:  # 只有有内容时才添加
                chat_history_text += (
                    f"\n--- 以下是 {observation_info.new_messages_count} "
                    f"条新消息 ---\n{new_messages_str}"
                )
        
        if not chat_history_text:
            chat_history_text = "还没有聊天记录。"
        
        return chat_history_text
    
    def _format_messages(
        self,
        messages: List[Dict[str, Any]],
        timestamp_mode: str = "relative"
    ) -> str:
        """
        格式化消息列表为可读文本（使用共享模块）
        
        Args:
            messages: 消息列表
            timestamp_mode: 时间戳显示模式，"relative" 为相对时间，"normal" 为绝对时间
            
        Returns:
            格式化的消息文本
        """
        if not messages:
            return ""
        
        formatted_blocks = []
        
        for msg in messages:
            # 获取发送者信息
            sender = msg.get("sender", {})
            sender_name = sender.get("nickname", "未知用户")
            user_name = msg.get("user_name", sender_name)
            
            # 获取内容
            content = msg.get("processed_plain_text", msg.get("content", ""))
            
            # 获取时间戳
            timestamp = msg.get("time", time.time())
            
            # 替换机器人名称
            user_id = sender.get("user_id", msg.get("user_id", ""))
            if str(user_id) == str(global_config.bot.qq_account):
                sender_name = f"{self.bot_name}(你)"
            else:
                sender_name = user_name or sender_name
            
            # 使用共享模块格式化时间
            readable_time = translate_timestamp(timestamp, mode=timestamp_mode)
            
            # 构建消息块（模仿原版格式）
            header = f"{readable_time} {sender_name} 说:"
            formatted_blocks.append(header)
            
            # 添加内容（带缩进）
            if content:
                stripped_content = content.strip()
                if stripped_content:
                    # 移除末尾句号，添加分号（模仿原版行为）
                    if stripped_content.endswith("。"):
                        stripped_content = stripped_content[:-1]
                    formatted_blocks.append(f"{stripped_content};")
            
            formatted_blocks.append("")  # 空行分隔
        
        return "\n".join(formatted_blocks).strip()
    
    def _select_prompt_template(self, action_type: str) -> str:
        """
        根据动作类型选择Prompt模板
        
        Args:
            action_type: 动作类型
            
        Returns:
            对应的Prompt模板
        """
        if action_type == "send_new_message":
            logger.info(
                f"[私聊][{self.user_name}]"
                "使用 PROMPT_SEND_NEW_MESSAGE (追问生成)"
            )
            return PROMPT_SEND_NEW_MESSAGE
        
        elif action_type == "say_goodbye":
            logger.info(
                f"[私聊][{self.user_name}]"
                "使用 PROMPT_FAREWELL (告别语生成)"
            )
            return PROMPT_FAREWELL
        
        else:
            # 默认使用 direct_reply 的 prompt
            logger.info(
                f"[私聊][{self.user_name}]"
                "使用 PROMPT_DIRECT_REPLY (首次/非连续回复生成)"
            )
            return PROMPT_DIRECT_REPLY
    
    async def check_reply(self, reply: str, goal: str) -> tuple[bool, str, bool]:
        """检查回复是否合适"""
        valid, reason = check_basic_reply_quality(reply)
        if not valid:
            return False, reason, True
        
        valid, reason = check_reply_similarity(reply, self.session.observation_info.chat_history)
        if not valid:
            return False, reason, True
        
        return True, "回复检查通过", False
    
    def _clean_response(self, response: str) -> str:
        """
        清理LLM响应
        
        移除可能的格式问题
        
        Args:
            response: 原始响应
            
        Returns:
            清理后的响应
        """
        if not response:
            return ""
        
        content = response.strip()
        
        # 移除可能的引号包裹
        if (content.startswith('"') and content.endswith('"')) or \
           (content.startswith("'") and content.endswith("'")):
            content = content[1:-1]
        
        # 移除可能的前缀（如"回复："等）
        prefixes_to_remove = [
            "回复：", "回复:", "Reply:", "reply:",
            "消息：", "消息:", "Message:", "message:"
        ]
        for prefix in prefixes_to_remove:
            if content.startswith(prefix):
                content = content[len(prefix):].strip()
                break
        
        return content


class ReplyChecker:
    """
    回复检查器
    
    检查生成的回复是否合适，是否需要重新生成
    支持可配置的 LLM 检查功能
    """
    
    def __init__(
        self,
        stream_id: str,
        private_name: str,
        config: "PFCConfig"
    ):
        """
        初始化回复检查器
        
        Args:
            stream_id: 会话流ID
            private_name: 私聊对象名称
            config: PFC配置
        """
        self.stream_id = stream_id
        self.private_name = private_name
        self.config = config
        self.checker_config = config.reply_checker
        self.max_retries = self.checker_config.max_retries
        
        logger.debug(f"[私聊][{private_name}]回复检查器初始化完成 (LLM检查: {self.checker_config.use_llm_check})")
    
    async def check(
        self,
        reply: str,
        goal: str,
        chat_history: List[Dict[str, Any]],
        chat_history_str: str,
        retry_count: int = 0
    ) -> tuple[bool, str, bool]:
        """
        检查回复是否合适
        
        Args:
            reply: 生成的回复
            goal: 当前目标
            chat_history: 聊天历史
            chat_history_str: 聊天历史字符串
            retry_count: 重试次数
            
        Returns:
            (is_valid, reason, need_replan) 元组
        """
        # 如果检查器被禁用，直接返回通过
        if not self.checker_config.enabled:
            logger.debug(f"[私聊][{self.private_name}]回复检查器已禁用，直接通过")
            return True, "检查器已禁用，直接通过", False
        
        # 基本检查
        valid, reason = check_basic_reply_quality(reply)
        if not valid:
            return False, reason, True
        
        # 相似度检查
        valid, reason = check_reply_similarity(reply, chat_history, self.checker_config.similarity_threshold)
        if not valid:
            logger.warning(f"[私聊][{self.private_name}]ReplyChecker {reason}: '{reply}'")
            return False, f"被逻辑检查拒绝：{reason}，可以选择深入话题或寻找其它话题或等待。", True
        
        logger.debug(f"[私聊][{self.private_name}]ReplyChecker - 相似度检查通过")
        
        # 如果启用 LLM 检查，调用 LLM 进行深度检查
        if self.checker_config.use_llm_check:
            return await self._llm_check(reply, goal, chat_history_str, retry_count)
        
        # 如果重试次数过多，接受当前回复
        if retry_count >= self.max_retries:
            logger.warning(
                f"[私聊][{self.private_name}]"
                f"重试次数过多({retry_count})，接受当前回复"
            )
            return True, "重试次数过多，接受当前回复", False
        
        return True, "回复检查通过", False
    
    async def _llm_check(
        self,
        reply: str,
        goal: str,
        chat_history_str: str,
        retry_count: int
    ) -> tuple[bool, str, bool]:
        """
        使用 LLM 进行深度检查
        
        Args:
            reply: 生成的回复
            goal: 当前目标
            chat_history_str: 聊天历史字符串
            retry_count: 重试次数
            
        Returns:
            (is_valid, reason, need_replan) 元组
        """
        prompt = f"""你是一个聊天逻辑检查器，请检查以下回复或消息是否合适：

当前对话目标：{goal}
最新的对话记录：
{chat_history_str}

待检查的消息：
{reply}

请结合聊天记录检查以下几点：
1. 这条消息是否依然符合当前对话目标和实现方式
2. 这条消息是否与最新的对话记录保持一致性
3. 是否存在重复发言，或重复表达同质内容（尤其是只是换一种方式表达了相同的含义）
4. 这条消息是否包含违规内容（例如血腥暴力，政治敏感等）
5. 这条消息是否以发送者的角度发言（不要让发送者自己回复自己的消息）
6. 这条消息是否通俗易懂
7. 这条消息是否有些多余，例如在对方没有回复的情况下，依然连续多次"消息轰炸"（尤其是已经连续发送3条信息的情况，这很可能不合理，需要着重判断）
8. 这条消息是否使用了完全没必要的修辞
9. 这条消息是否逻辑通顺
10. 这条消息是否太过冗长了（通常私聊的每条消息长度在20字以内，除非特殊情况）
11. 在连续多次发送消息的情况下，这条消息是否衔接自然，会不会显得奇怪（例如连续两条消息中部分内容重叠）

请以JSON格式输出，包含以下字段：
1. suitable: 是否合适 (true/false)
2. reason: 原因说明
3. need_replan: 是否需要重新决策 (true/false)，当你认为此时已经不适合发消息，需要规划其它行动时，设为true

输出格式示例：
{{
    "suitable": true,
    "reason": "回复符合要求，虽然有可能略微偏离目标，但是整体内容流畅得体",
    "need_replan": false
}}

注意：请严格按照JSON格式输出，不要包含任何其他内容。"""

        try:
            models = llm_api.get_available_models()
            checker_config = models.get("utils")
            
            if not checker_config:
                logger.warning("[PFC] 未找到 utils 模型配置，跳过 LLM 检查")
                return True, "LLM 检查跳过（无模型配置）", False
            
            success, content, _, _ = await llm_api.generate_with_model(
                prompt=prompt,
                model_config=checker_config,
                request_type="pfc.reply_check",
            )
            
            if not success or not content:
                logger.warning(f"[私聊][{self.private_name}]LLM 检查调用失败")
                return True, "LLM 检查跳过（调用失败）", False
            
            logger.debug(f"[私聊][{self.private_name}]检查回复的原始返回: {content}")
            
            # 解析 JSON 响应
            return self._parse_llm_response(content, retry_count)
            
        except Exception as e:
            logger.error(f"[私聊][{self.private_name}]LLM 检查时出错: {e}")
            if retry_count >= self.max_retries:
                return False, "多次检查失败，建议重新规划", True
            return False, f"检查过程出错，建议重试: {str(e)}", False
    
    def _parse_llm_response(
        self,
        content: str,
        retry_count: int
    ) -> tuple[bool, str, bool]:
        """解析 LLM 响应"""
        import json
        import re
        
        content = content.strip()
        
        try:
            result = json.loads(content)
        except json.JSONDecodeError:
            # 尝试提取 JSON 部分
            json_pattern = r"\{[^{}]*\}"
            json_match = re.search(json_pattern, content)
            if json_match:
                try:
                    result = json.loads(json_match.group())
                except json.JSONDecodeError:
                    return self._fallback_parse(content, retry_count)
            else:
                return self._fallback_parse(content, retry_count)
        
        # 验证 JSON 字段
        suitable = result.get("suitable", None)
        reason = result.get("reason", "未提供原因")
        need_replan = result.get("need_replan", False)
        
        # 如果 suitable 字段是字符串，转换为布尔值
        if isinstance(suitable, str):
            suitable = suitable.lower() == "true"
        
        # 如果 suitable 字段不存在或不是布尔值，从 reason 中判断
        if suitable is None:
            suitable = "不合适" not in reason.lower() and "违规" not in reason.lower()
        
        # 如果不合适且未达到最大重试次数，返回需要重试
        if not suitable and retry_count < self.max_retries:
            return False, reason, False
        
        # 如果不合适且已达到最大重试次数，返回需要重新规划
        if not suitable and retry_count >= self.max_retries:
            return False, f"多次重试后仍不合适: {reason}", True
        
        return suitable, reason, need_replan
    
    def _fallback_parse(self, content: str, retry_count: int) -> tuple[bool, str, bool]:
        """从文本中判断结果（备选方案）"""
        is_suitable = "不合适" not in content.lower() and "违规" not in content.lower()
        reason = content[:100] if content else "无法解析响应"
        need_replan = "重新规划" in content.lower() or "目标不适合" in content.lower()
        return is_suitable, reason, need_replan