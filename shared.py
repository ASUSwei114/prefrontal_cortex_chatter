"""
PFC - 共享工具模块

================================================================================
版权声明 (Copyright Notice)
================================================================================

本文件为 MoFox_Bot 项目的一部分。

本项目遵循 GNU General Public License v3.0 许可证。
详见 LICENSE 文件。

================================================================================

提供 PFC 插件各模块共享的工具函数和类：
- 人格信息获取
- 时间格式化
- 聊天历史构建
- 目标字符串构建
- 知识信息构建
"""

import datetime
import time
from typing import Any, Optional

from src.common.logger import get_logger
from src.config.config import global_config
from src.individuality.individuality import get_individuality

logger = get_logger("pfc_shared")


# ============================================================================
# 时间格式化工具
# ============================================================================

def translate_timestamp(timestamp: float, mode: str = "relative") -> str:
    """
    将时间戳转换为人类可读的时间格式
    
    Args:
        timestamp: 时间戳
        mode: 转换模式
            - "relative": 相对时间格式（如"刚刚"、"5分钟前"）
            - "normal": 标准格式（如"2024-01-01 12:00:00"）
            - "lite": 简洁格式（如"12:00:00"）
        
    Returns:
        格式化后的时间字符串
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
        return time.strftime("%H:%M:%S", time.localtime(timestamp))


def get_current_time_str() -> str:
    """
    获取当前时间的人类可读格式
    
    Returns:
        格式化的时间字符串，如"2024年01月01日 星期一 上午 10:30"
    """
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


# ============================================================================
# 人格信息获取
# ============================================================================

class PersonalityHelper:
    """
    人格信息获取助手
    
    提供统一的人格信息获取接口，避免在 planner.py、replyer.py 等模块中重复代码。
    """
    
    def __init__(self, user_name: str = "用户"):
        """
        初始化人格信息助手
        
        Args:
            user_name: 用户名称（用于日志）
        """
        self.user_name = user_name
        self._personality_info: Optional[str] = None
        self.bot_name = global_config.bot.nickname if global_config else "Bot"
    
    async def get_personality_info(self) -> str:
        """
        获取人格信息（异步，带缓存）
        
        Returns:
            人格信息字符串
        """
        if self._personality_info is None:
            self._personality_info = await self._load_personality_info()
        return self._personality_info
    
    async def _load_personality_info(self) -> str:
        """
        加载人格信息
        
        Returns:
            人格信息字符串
        """
        try:
            individuality = get_individuality()
            base_personality = await individuality.get_personality_block()
            
            # 追加 background_story（包含人际关系等重要信息）
            background_story = self._get_background_story()
            if background_story:
                personality_info = f"{base_personality}\n\n【背景信息】\n{background_story}"
            else:
                personality_info = base_personality
            
            logger.debug(f"[PFC][{self.user_name}] 获取人格信息成功: {personality_info[:50]}...")
            return personality_info
            
        except Exception as e:
            logger.warning(f"[PFC][{self.user_name}] 获取人格信息失败: {e}，尝试从配置读取")
            return self._build_personality_from_config()
    
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
            logger.debug(f"[PFC][{self.user_name}] 从配置构建人格信息: {result[:50]}...")
            return result
            
        except Exception as e:
            logger.error(f"[PFC][{self.user_name}] 从配置构建人格信息失败: {e}")
            return "一个友善的AI助手"
    
    def get_reply_style(self) -> str:
        """
        从 bot_config 获取回复风格配置
        
        Returns:
            回复风格字符串
        """
        try:
            if global_config and hasattr(global_config, 'personality'):
                reply_style = getattr(global_config.personality, 'reply_style', None)
                if reply_style:
                    logger.debug(f"[PFC][{self.user_name}] 获取回复风格: {reply_style[:50]}...")
                    return reply_style
        except Exception as e:
            logger.warning(f"[PFC][{self.user_name}] 获取回复风格失败: {e}")
        
        # 默认回复风格
        return "回复简短自然，像正常聊天一样。"


# ============================================================================
# Prompt 构建工具
# ============================================================================

def build_goals_string(goal_list: list[dict[str, Any]] | None) -> str:
    """
    构建对话目标字符串
    
    Args:
        goal_list: 目标列表
        
    Returns:
        格式化的目标字符串
    """
    if not goal_list:
        return "- 目前没有明确对话目标，请考虑设定一个。\n"
    
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
    
    if not goals_str:
        goals_str = "- 目前没有明确对话目标，请考虑设定一个。\n"
    
    return goals_str


def build_knowledge_string(knowledge_list: list[dict[str, Any]] | None) -> str:
    """
    构建知识信息字符串
    
    Args:
        knowledge_list: 知识列表
        
    Returns:
        格式化的知识字符串
    """
    knowledge_info_str = "【已获取的相关知识和记忆】\n"
    
    if not knowledge_list:
        knowledge_info_str += "- 暂无相关知识和记忆。\n"
        return knowledge_info_str
    
    try:
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
                    f"{i + 1}. 关于 '{query}' 的知识 (来源: {source}):\n"
                    f"   {knowledge_snippet}\n"
                )
            else:
                knowledge_info_str += f"{i + 1}. 发现一条格式不正确的知识记录。\n"
        
        if not recent_knowledge:
            knowledge_info_str += "- 暂无相关知识和记忆。\n"
            
    except Exception as e:
        logger.error(f"[PFC] 构建知识信息字符串时出错: {e}")
        knowledge_info_str += "- 处理知识列表时出错。\n"
    
    return knowledge_info_str


def format_chat_history(
    chat_history: list[dict[str, Any]],
    bot_name: str = "Bot",
    user_name: str = "用户",
    max_messages: int = 30,
) -> str:
    """
    格式化聊天历史为可读文本
    
    Args:
        chat_history: 聊天历史列表
        bot_name: 机器人名称
        user_name: 用户名称
        max_messages: 最大消息数量
        
    Returns:
        格式化的聊天历史文本
    """
    if not chat_history:
        return "还没有聊天记录。"
    
    formatted_blocks = []
    
    # 只取最近的消息
    recent_history = chat_history[-max_messages:]
    
    for msg in recent_history:
        msg_type = msg.get("type", "")
        content = msg.get("content", "")
        msg_time = msg.get("time", time.time())
        
        # 使用相对时间格式
        readable_time = translate_timestamp(msg_time)
        
        if msg_type == "user_message":
            sender = msg.get("user_name", user_name)
            header = f"{readable_time} {sender} 说:"
        elif msg_type == "bot_message":
            header = f"{readable_time} {bot_name}(你) 说:"
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
    
    chat_history_text = "\n".join(formatted_blocks).strip()
    
    if not chat_history_text:
        chat_history_text = "还没有聊天记录。"
    
    return chat_history_text


def format_new_messages(
    unprocessed_messages: list[dict[str, Any]],
    processed_times: set[float] | None = None,
    bot_name: str = "Bot",
) -> tuple[str, int]:
    """
    格式化新消息
    
    Args:
        unprocessed_messages: 未处理的消息列表
        processed_times: 已处理消息的时间戳集合（用于去重）
        bot_name: 机器人名称
        
    Returns:
        (格式化的新消息文本, 实际新消息数量)
    """
    if not unprocessed_messages:
        return "", 0
    
    if processed_times is None:
        processed_times = set()
    
    new_blocks = []
    actual_new_count = 0
    
    for msg in unprocessed_messages:
        msg_time = msg.get("time", time.time())
        
        # 跳过已处理的消息
        if msg_time and msg_time in processed_times:
            continue
        
        content = msg.get("content", "")
        if not content:
            continue
        
        user_name = msg.get("user_name", "用户")
        msg_type = msg.get("type", "")
        
        readable_time = translate_timestamp(msg_time)
        
        if msg_type == "bot_message":
            header = f"{readable_time} {bot_name}(你) 说:"
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
    
    return "\n".join(new_blocks).strip(), actual_new_count