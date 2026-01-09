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

本项目遵循 GNU General Public License v3.0 许可证。
详见 LICENSE 文件。

================================================================================

负责根据不同的行动类型生成相应的回复内容
"""

import time
from typing import Optional, List, Dict, Any
from src.common.logger import get_logger
from src.plugin_system.apis import llm_api
from src.individuality.individuality import get_individuality
from src.config.config import global_config

from .models import ObservationInfo, ConversationInfo

# PFCConfig 类型注解使用 TYPE_CHECKING
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from .plugin import PFCConfig

logger = get_logger("PFC-Replyer")


def translate_timestamp_to_human_readable(timestamp: float, mode: str = "relative") -> str:
    """
    将时间戳转换为人类可读的时间格式
    
    移植自原版 MaiM-with-u 的 src/plugins/chat/utils.py
    
    Args:
        timestamp: 时间戳
        mode: 转换模式，"normal"为标准格式，"relative"为相对时间格式
        
    Returns:
        str: 格式化后的时间字符串
    """
    if mode == "normal":
        return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(timestamp))
    elif mode == "relative":
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
            return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(timestamp))
    else:  # mode = "lite" or unknown
        # 只返回时分秒格式
        return time.strftime("%H:%M:%S", time.localtime(timestamp))


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
        
        # 人格信息将在异步方法中获取
        self.personality_info: Optional[str] = None
        
        # 获取机器人名称
        self.bot_name = global_config.bot.nickname if global_config else "Bot"
        
        logger.debug(f"[私聊][{user_name}]回复生成器初始化完成")
    
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
                logger.debug(f"[私聊][{self.user_name}]获取人格信息成功: {self.personality_info[:50]}...")
            except Exception as e:
                logger.warning(f"[私聊][{self.user_name}]获取人格信息失败: {e}，尝试从配置读取")
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
            logger.debug(f"[私聊][{self.user_name}]从配置构建人格信息: {result[:50]}...")
            return result
        except Exception as e:
            logger.error(f"[私聊][{self.user_name}]从配置构建人格信息失败: {e}")
            return "一个友善的AI助手"
    
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
            # 使用 utils 而非 replyer，避免自动注入 MoFox 系统提示词
            # replyer 配置会在 LLMRequest 中自动注入 SYSTEM_PROMPT
            replyer_config = models.get("utils")
            
            if not replyer_config:
                logger.warning("[PFC] 未找到 replyer 模型配置")
                return ""
            
            success, response, _, _ = await llm_api.generate_with_model(
                prompt=prompt,
                model_config=replyer_config,
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
        构建Prompt参数
        
        Args:
            observation_info: 观察信息
            conversation_info: 对话信息
            
        Returns:
            Prompt参数字典
        """
        # 确保人格信息已加载
        personality_info = await self._ensure_personality_info()
        
        # 构建对话目标字符串
        goals_str = self._build_goals_string(conversation_info.goal_list)
        
        # 构建知识信息字符串
        knowledge_info_str = self._build_knowledge_string(conversation_info)
        
        # 构建聊天历史文本
        chat_history_text = await self._build_chat_history_text(observation_info)
        
        # 构建人设文本
        persona_text = f"{personality_info}"
        
        # 获取回复风格
        reply_style = self._get_reply_style()
        
        # 获取当前时间字符串
        current_time_str = self._get_current_time_str()
        
        return {
            "persona_text": persona_text,
            "goals_str": goals_str,
            "knowledge_info_str": knowledge_info_str,
            "chat_history_text": chat_history_text,
            "reply_style": reply_style,
            "current_time_str": current_time_str,
        }
    
    def _get_reply_style(self) -> str:
        """
        从 bot_config 获取回复风格配置
        
        Returns:
            回复风格字符串
        """
        try:
            if global_config and hasattr(global_config, 'personality'):
                reply_style = getattr(global_config.personality, 'reply_style', None)
                if reply_style:
                    logger.debug(f"[私聊][{self.user_name}]获取回复风格: {reply_style[:50]}...")
                    return reply_style
        except Exception as e:
            logger.warning(f"[私聊][{self.user_name}]获取回复风格失败: {e}")
        
        # 默认回复风格
        return "回复简短自然，像正常聊天一样。"
    
    def _get_current_time_str(self) -> str:
        """获取当前时间的人类可读格式"""
        import datetime
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
    
    def _build_goals_string(self, goal_list: Optional[List[Dict[str, Any]]]) -> str:
        """
        构建对话目标字符串
        
        Args:
            goal_list: 目标列表
            
        Returns:
            格式化的目标字符串
        """
        if not goal_list:
            return "- 目前没有明确对话目标\n"
        
        goals_str = ""
        for goal_item in goal_list:
            if isinstance(goal_item, dict):
                goal = goal_item.get("goal", "目标内容缺失")
                reasoning = goal_item.get("reasoning", "没有明确原因")
            else:
                goal = str(goal_item)
                reasoning = "没有明确原因"
            
            goal = str(goal) if goal is not None else "目标内容缺失"
            reasoning = str(reasoning) if reasoning is not None else "没有明确原因"
            goals_str += f"- 目标：{goal}\n  原因：{reasoning}\n"
        
        return goals_str
    
    def _build_knowledge_string(self, conversation_info: ConversationInfo) -> str:
        """
        构建知识信息字符串
        
        Args:
            conversation_info: 对话信息
            
        Returns:
            格式化的知识字符串
        """
        knowledge_info_str = "【供参考的相关知识和记忆】\n"
        
        try:
            knowledge_list = getattr(conversation_info, 'knowledge_list', None)
            
            if not knowledge_list:
                knowledge_info_str += "- 暂无。\n"
                return knowledge_info_str
            
            # 最多只显示最近的 5 条知识
            recent_knowledge = knowledge_list[-5:]
            
            for i, knowledge_item in enumerate(recent_knowledge):
                if isinstance(knowledge_item, dict):
                    query = knowledge_item.get("query", "未知查询")
                    knowledge = knowledge_item.get("knowledge", "无知识内容")
                    source = knowledge_item.get("source", "未知来源")
                    
                    # 只取知识内容的前 2000 个字
                    knowledge_snippet = (
                        knowledge[:2000] + "..." 
                        if len(knowledge) > 2000 
                        else knowledge
                    )
                    knowledge_info_str += (
                        f"{i + 1}. 关于 '{query}' (来源: {source}): "
                        f"{knowledge_snippet}\n"
                    )
                else:
                    knowledge_info_str += (
                        f"{i + 1}. 发现一条格式不正确的知识记录。\n"
                    )
            
            if not recent_knowledge:
                knowledge_info_str += "- 暂无。\n"
                
        except AttributeError:
            logger.warning(
                f"[私聊][{self.user_name}]"
                "ConversationInfo 对象可能缺少 knowledge_list 属性。"
            )
            knowledge_info_str += "- 获取知识列表时出错。\n"
        except Exception as e:
            logger.error(
                f"[私聊][{self.user_name}]构建知识信息字符串时出错: {e}"
            )
            knowledge_info_str += "- 处理知识列表时出错。\n"
        
        return knowledge_info_str
    
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
        格式化消息列表为可读文本
        
        移植自原版 MaiM-with-u 的 build_readable_messages 函数，
        添加相对时间显示功能，让 LLM 知道每条消息是什么时候发送的。
        
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
            
            # 格式化时间
            readable_time = translate_timestamp_to_human_readable(timestamp, mode=timestamp_mode)
            
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
        """
        检查回复是否合适
        
        Args:
            reply: 生成的回复
            goal: 当前目标
            
        Returns:
            (is_suitable, reason, need_replan) 元组
        """
        # 基本检查
        if not reply or len(reply.strip()) == 0:
            return False, "回复为空", True
        
        # 检查是否过长
        if len(reply) > 500:
            return False, "回复过长", True
        
        # 检查是否包含不当内容
        inappropriate_patterns = [
            "作为AI", "作为一个AI", "作为人工智能",
            "我是AI", "我是一个AI", "我是人工智能",
            "抱歉，我无法", "对不起，我不能"
        ]
        
        for pattern in inappropriate_patterns:
            if pattern in reply:
                return False, f"包含不当内容: {pattern}", True
        
        # 检查是否与最近的回复重复
        chat_history = self.session.observation_info.chat_history
        if chat_history:
            recent_bot_replies = [
                msg.get("content", "")
                for msg in chat_history[-5:]
                if msg.get("type") == "bot_message"
            ]
            
            for recent_reply in recent_bot_replies:
                if self._is_similar(reply, recent_reply):
                    return False, "与最近的回复过于相似", True
        
        return True, "回复检查通过", False
    
    def _is_similar(self, text1: str, text2: str, threshold: float = 0.8) -> bool:
        """
        检查两段文本是否相似
        
        Args:
            text1: 文本1
            text2: 文本2
            threshold: 相似度阈值
            
        Returns:
            是否相似
        """
        if not text1 or not text2:
            return False
        
        # 简单的字符集重叠率
        set1 = set(text1)
        set2 = set(text2)
        
        intersection = len(set1 & set2)
        union = len(set1 | set2)
        
        if union == 0:
            return False
        
        similarity = intersection / union
        return similarity >= threshold
    
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
            return True, "检查器已禁用，直接通过", False
        
        # 基本检查
        if not reply or len(reply.strip()) == 0:
            return False, "回复为空", True
        
        # 检查是否过长
        if len(reply) > 500:
            return False, "回复过长", True
        
        # 检查是否包含不当内容
        inappropriate_patterns = [
            "作为AI", "作为一个AI", "作为人工智能",
            "我是AI", "我是一个AI", "我是人工智能",
            "抱歉，我无法", "对不起，我不能"
        ]
        
        for pattern in inappropriate_patterns:
            if pattern in reply:
                return False, f"包含不当内容: {pattern}", True
        
        # 相似度检查 - 检查是否与最近的 Bot 回复重复
        try:
            bot_messages = self._get_recent_bot_messages(chat_history)
            if bot_messages:
                # 完全相同检查
                if reply == bot_messages[0]:
                    logger.warning(
                        f"[私聊][{self.private_name}]ReplyChecker 检测到回复与上一条 Bot 消息完全相同: '{reply}'"
                    )
                    return (
                        False,
                        "被逻辑检查拒绝：回复内容与你上一条发言完全相同，可以选择深入话题或寻找其它话题或等待",
                        True,
                    )
                
                # 相似度检查
                import difflib
                similarity_ratio = difflib.SequenceMatcher(None, reply, bot_messages[0]).ratio()
                logger.debug(f"[私聊][{self.private_name}]ReplyChecker - 相似度: {similarity_ratio:.2f}")
                
                if similarity_ratio > self.checker_config.similarity_threshold:
                    logger.warning(
                        f"[私聊][{self.private_name}]ReplyChecker 检测到回复与上一条 Bot 消息高度相似 "
                        f"(相似度 {similarity_ratio:.2f}): '{reply}'"
                    )
                    return (
                        False,
                        f"被逻辑检查拒绝：回复内容与你上一条发言高度相似 (相似度 {similarity_ratio:.2f})，"
                        "可以选择深入话题或寻找其它话题或等待。",
                        True,
                    )
        except Exception as e:
            import traceback
            logger.error(f"[私聊][{self.private_name}]检查回复时出错: 类型={type(e)}, 值={e}")
            logger.error(f"[私聊][{self.private_name}]{traceback.format_exc()}")
        
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
    
    def _get_recent_bot_messages(self, chat_history: List[Dict[str, Any]]) -> List[str]:
        """获取最近的 Bot 消息"""
        bot_messages = []
        bot_qq = str(global_config.bot.qq_account) if global_config else ""
        
        for msg in reversed(chat_history):
            sender = msg.get("sender", {})
            user_id = str(sender.get("user_id", ""))
            
            if user_id == bot_qq:
                content = msg.get("processed_plain_text", msg.get("content", ""))
                if content:
                    bot_messages.append(content)
            
            if len(bot_messages) >= 2:
                break
        
        return bot_messages
    
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