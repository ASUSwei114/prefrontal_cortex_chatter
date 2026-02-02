"""
PFC - 共享工具模块

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
- 添加人格信息获取助手
- 添加时间格式化工具
- 添加聊天历史构建工具
- 添加 Prompt 构建工具

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
    formats = {
        "normal": "%Y-%m-%d %H:%M:%S",
        "lite": "%H:%M:%S"
    }
    
    if mode in formats:
        return time.strftime(formats[mode], time.localtime(timestamp))
    
    # relative mode
    diff = time.time() - timestamp
    thresholds = [(20, "刚刚"), (60, f"{int(diff)}秒前"), (3600, f"{int(diff/60)}分钟前"),
                  (86400, f"{int(diff/3600)}小时前"), (86400*2, f"{int(diff/86400)}天前")]
    
    for threshold, result in thresholds:
        if diff < threshold:
            return result
    
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(timestamp))


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
            return getattr(global_config.personality, 'background_story', '') if global_config and hasattr(global_config, 'personality') else ''
        except Exception:
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
            reply_style = getattr(global_config.personality, 'reply_style', None) if global_config and hasattr(global_config, 'personality') else None
            if reply_style:
                logger.debug(f"[PFC][{self.user_name}] 获取回复风格: {reply_style[:50]}...")
                return reply_style
        except Exception as e:
            logger.warning(f"[PFC][{self.user_name}] 获取回复风格失败: {e}")
        
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
    
    goals = []
    for item in goal_list:
        if isinstance(item, dict):
            goal = str(item.get("goal") or "目标内容缺失")
            reasoning = str(item.get("reasoning") or "没有明确原因")
        else:
            goal, reasoning = str(item), "没有明确原因"
        goals.append(f"- 目标：{goal}\n  原因：{reasoning}\n")
    
    return "".join(goals) if goals else "- 目前没有明确对话目标，请考虑设定一个。\n"


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
    
    def format_message(msg: dict) -> list[str]:
        msg_type = msg.get("type", "")
        content = msg.get("content", "").strip()
        readable_time = translate_timestamp(msg.get("time", time.time()))
        
        if msg_type == "user_message":
            header = f"{readable_time} {msg.get('user_name', user_name)} 说:"
        elif msg_type == "bot_message":
            header = f"{readable_time} {bot_name}(你) 说:"
        else:
            return []
        
        result = [header]
        if content:
            content = content[:-1] if content.endswith("。") else content
            result.append(f"{content};")
        result.append("")
        return result
    
    formatted_blocks = [line for msg in chat_history[-max_messages:] for line in format_message(msg)]
    return "\n".join(formatted_blocks).strip() or "还没有聊天记录。"


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
    
    processed_times = processed_times or set()
    new_blocks = []
    
    for msg in unprocessed_messages:
        msg_time = msg.get("time", time.time())
        content = msg.get("content", "").strip()
        
        if msg_time in processed_times or not content:
            continue
        
        readable_time = translate_timestamp(msg_time)
        msg_type = msg.get("type", "")
        sender = f"{bot_name}(你)" if msg_type == "bot_message" else msg.get("user_name", "用户")
        
        content = content[:-1] if content.endswith("。") else content
        new_blocks.extend([f"{readable_time} {sender} 说:", f"{content};", ""])
    
    return "\n".join(new_blocks).strip(), len(new_blocks) // 3


def _truncate_text(text: str, limit: int) -> str:
    """截断文本到指定长度"""
    if not text or limit <= 0:
        return text or ""
    text = text.strip()
    return text if len(text) <= limit else (text[:max(0, limit - 1)] + "…")


def _format_md_cell(value: str, max_length: int = 500) -> str:
    """格式化为 Markdown 表格单元格"""
    value = (value or "").replace("\r\n", "\n").replace("\n", "<br>").replace("|", "\\|")
    return _truncate_text(value, max_length)


def _build_md_table(header: list[str], rows: list[list[str]], title: str = "") -> str:
    """构建 Markdown 表格"""
    lines = [
        "|" + "|".join(header) + "|",
        "|" + "|".join(["---"] * len(header)) + "|",
    ]
    lines.extend("|" + "|".join(row) + "|" for row in rows)
    return (f"{title}\n" if title else "") + "\n".join(lines)


# 行动类型和状态的中文映射
_ACTION_TYPE_ALIAS = {
    "direct_reply": "直接回复", "send_new_message": "发送新消息",
    "fetch_knowledge": "调取知识", "wait": "等待", "listening": "倾听",
    "rethink_goal": "重新思考目标", "end_conversation": "结束对话",
    "say_goodbye": "告别", "block_and_ignore": "屏蔽忽略",
}
_STATUS_ALIAS = {"done": "成功", "recall": "取消/失败"}


def build_action_history_table(action_history: list[dict[str, Any]], max_cell_length: int = 500) -> str:
    """构建结构化表格形式的行动历史"""
    if not action_history:
        return "- 还没有执行过行动。\n"
    
    rows = []
    for idx, action_data in enumerate(action_history, 1):
        if not isinstance(action_data, dict):
            continue
        action_type = action_data.get("action", "未知")
        rows.append([
            str(idx),
            _format_md_cell(str(action_data.get("time", "")), max_cell_length),
            _format_md_cell(_ACTION_TYPE_ALIAS.get(action_type, action_type), max_cell_length),
            _format_md_cell(str(action_data.get("plan_reason", "未知规划原因")), max_cell_length),
            _format_md_cell(_STATUS_ALIAS.get(action_data.get("status", ""), action_data.get("status", "未知")), max_cell_length),
            _format_md_cell(str(action_data.get("final_reason", "")), max_cell_length),
        ])
    
    return _build_md_table(
        ["#", "时间", "行动类型", "规划原因", "状态", "失败原因"],
        rows, "（结构化行动历史表；按时间顺序）"
    )


def build_chat_history_table(
    chat_history: list[dict[str, Any]], bot_name: str = "Bot",
    user_name: str = "用户", max_messages: int = 30, max_cell_length: int = 500,
) -> str:
    """构建结构化表格形式的聊天历史"""
    if not chat_history:
        return "还没有聊天记录。"
    
    rows = []
    for idx, msg in enumerate(chat_history[-max_messages:], 1):
        msg_type = msg.get("type", "")
        if msg_type == "user_message":
            speaker = msg.get("user_name", user_name)
        elif msg_type == "bot_message":
            speaker = f"{bot_name}(你)"
        else:
            continue
        
        content = msg.get("content", "").strip()
        if content.endswith("。"):
            content = content[:-1]
        
        rows.append([
            str(idx),
            _format_md_cell(translate_timestamp(msg.get("time", time.time()), mode="lite"), max_cell_length),
            _format_md_cell(speaker, max_cell_length),
            _format_md_cell(content, max_cell_length),
        ])
    
    return _build_md_table(["#", "时间", "发言人", "内容"], rows, "（结构化聊天历史表；按时间顺序）")