"""PFC 共享工具模块 - 提供各模块共享的工具函数和类 (GPL-3.0)

本模块包含以下功能：
1. 时间格式化工具 - 将时间戳转换为人类可读格式
2. 人格信息助手 - 获取和管理 Bot 的人格信息
3. 文本构建工具 - 构建目标、知识、历史等格式化文本
4. JSON 解析工具 - 从 LLM 响应中提取 JSON 数据
5. 通用工具函数 - 文本处理、时间计算等
"""

import datetime
import json
import re
import time
from typing import Any, Optional

from src.common.logger import get_logger
from src.config.config import global_config
from src.individuality.individuality import get_individuality

logger = get_logger("pfc_shared")


def translate_timestamp(timestamp: float, mode: str = "relative") -> str:
    """将时间戳转换为人类可读的时间格式
    
    Args:
        timestamp: Unix 时间戳
        mode: 格式模式
            - "relative": 相对时间（如"刚刚"、"5分钟前"）
            - "normal": 完整日期时间（如"2024-12-01 14:30:00"）
            - "lite": 仅时间（如"14:30:00"）
    
    Returns:
        格式化后的时间字符串
    """
    formats = {"normal": "%Y-%m-%d %H:%M:%S", "lite": "%H:%M:%S"}
    if mode in formats:
        return time.strftime(formats[mode], time.localtime(timestamp))

    diff = time.time() - timestamp
    thresholds = [(20, "刚刚"), (60, f"{int(diff)}秒前"), (3600, f"{int(diff/60)}分钟前"),
                  (86400, f"{int(diff/3600)}小时前"), (86400*2, f"{int(diff/86400)}天前")]
    for threshold, result in thresholds:
        if diff < threshold:
            return result
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(timestamp))


def get_current_time_str() -> str:
    """获取当前时间的人类可读格式
    
    Returns:
        格式化的当前时间，如 "2024年12月01日 星期五 下午 14:30"
    """
    now = datetime.datetime.now()
    weekdays = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
    hour = now.hour
    periods = [(5, 9, "早上"), (9, 12, "上午"), (12, 14, "中午"), (14, 18, "下午"), (18, 22, "晚上")]
    time_period = "深夜"
    for start, end, period in periods:
        if start <= hour < end:
            time_period = period
            break
    return now.strftime(f"%Y年%m月%d日 {weekdays[now.weekday()]} {time_period} %H:%M")


class PersonalityHelper:
    """人格信息获取助手
    
    负责获取和管理 Bot 的人格信息，包括：
    - 基础人格信息（名字、别名、性格等）
    - 背景故事
    - 回复风格
    """

    def __init__(self, user_name: str = "用户"):
        """初始化人格助手
        
        Args:
            user_name: 对话用户的名称（用于日志记录）
        """
        self.user_name = user_name
        self._personality_info: Optional[str] = None
        self.bot_name = global_config.bot.nickname if global_config else "Bot"

    async def get_personality_info(self) -> str:
        if self._personality_info is None:
            self._personality_info = await self._load_personality_info()
        return self._personality_info

    async def _load_personality_info(self) -> str:
        try:
            individuality = get_individuality()
            base_personality = await individuality.get_personality_block()
            background = self._get_background_story()
            return f"{base_personality}\n\n【背景信息】\n{background}" if background else base_personality
        except Exception as e:
            logger.warning(f"[PFC][{self.user_name}] 获取人格信息失败: {e}")
            return self._build_personality_from_config()

    def _get_background_story(self) -> str:
        try:
            return getattr(global_config.personality, 'background_story', '') if global_config and hasattr(global_config, 'personality') else ''
        except Exception:
            return ''

    def _build_personality_from_config(self) -> str:
        try:
            bot_name = global_config.bot.nickname if global_config else "Bot"
            parts = [f"你的名字是{bot_name}"]
            if global_config:
                if global_config.bot.alias_names:
                    parts.append(f"也有人叫你{','.join(global_config.bot.alias_names)}")
                if global_config.personality.personality_core:
                    parts.append(f"你{global_config.personality.personality_core}")
                if global_config.personality.personality_side:
                    parts.append(global_config.personality.personality_side)
                if global_config.personality.identity:
                    parts.append(global_config.personality.identity)
            return "，".join(parts)
        except Exception:
            return "一个友善的AI助手"

    def get_reply_style(self) -> str:
        try:
            reply_style = getattr(global_config.personality, 'reply_style', None) if global_config and hasattr(global_config, 'personality') else None
            if reply_style:
                return reply_style
        except Exception:
            pass
        return "回复简短自然，像正常聊天一样。"


def build_goals_string(goal_list: list[dict[str, Any]] | None) -> str:
    """构建对话目标字符串
    
    Args:
        goal_list: 目标列表，每项包含 "goal" 和 "reasoning" 字段
    
    Returns:
        格式化的目标字符串，用于提示词
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
    return "".join(goals) or "- 目前没有明确对话目标，请考虑设定一个。\n"


def build_knowledge_string(knowledge_list: list[dict[str, Any]] | None) -> str:
    """构建知识信息字符串
    
    Args:
        knowledge_list: 知识列表，每项包含 "query"、"knowledge"、"source" 字段
    
    Returns:
        格式化的知识字符串，用于提示词
    """
    result = "【已获取的相关知识和记忆】\n"
    if not knowledge_list:
        return result + "- 暂无相关知识和记忆。\n"
    try:
        for i, item in enumerate(knowledge_list[-5:]):
            if isinstance(item, dict):
                query = item.get("query", "未知查询")
                knowledge = item.get("knowledge", "无知识内容")
                source = item.get("source", "未知来源")
                snippet = knowledge[:2000] + "..." if len(knowledge) > 2000 else knowledge
                result += f"{i + 1}. 关于 '{query}' 的知识 (来源: {source}):\n   {snippet}\n"
    except Exception as e:
        logger.error(f"[PFC] 构建知识信息字符串时出错: {e}")
        result += "- 处理知识列表时出错。\n"
    return result


def _truncate_message_content(content: str, index: int, total: int) -> str:
    """根据消息在列表中的位置智能截断内容
    
    模拟人类记忆特点：越久远的消息记得越模糊，越近期的消息记得越清楚
    
    Args:
        content: 消息内容
        index: 消息在列表中的索引
        total: 消息总数
        
    Returns:
        截断后的内容
    """
    if total <= 0 or not content:
        return content
    
    percentile = index / total
    original_len = len(content)
    
    # 根据位置百分比确定截断限制
    if percentile < 0.2:  # 最旧的 20%
        limit, suffix = 50, "......（记不清了）"
    elif percentile < 0.5:  # 20% - 50%
        limit, suffix = 100, "......（有点记不清了）"
    elif percentile < 0.7:  # 50% - 70%
        limit, suffix = 200, "......（内容太长了）"
    elif percentile < 1.0:  # 70% - 100%
        limit, suffix = 400, "......（太长了）"
    else:
        return content
    
    if limit > 0 and original_len > limit:
        return f"{content[:limit]}{suffix}"
    return content


def format_chat_history(chat_history: list[dict[str, Any]], bot_name: str = "Bot",
                        user_name: str = "用户", max_messages: int = 30,
                        truncate: bool = False) -> str:
    """格式化聊天历史为可读文本
    
    Args:
        chat_history: 聊天历史列表
        bot_name: Bot 名称
        user_name: 用户名称
        max_messages: 最多保留的消息条数
        truncate: 是否根据消息新旧程度截断过长内容
    
    Returns:
        格式化的聊天历史文本
    """
    if not chat_history:
        return "还没有聊天记录。"

    messages_slice = chat_history[-max_messages:]
    total_messages = len(messages_slice)

    def format_message(msg: dict, index: int) -> list[str]:
        msg_type = msg.get("type", "")
        content = msg.get("content", "").strip()
        readable_time = translate_timestamp(msg.get("time", time.time()))
        if msg_type == "user_message":
            header = f"{readable_time} {msg.get('user_name', user_name)} 说:"
        elif msg_type == "bot_message":
            header = f"{readable_time} {bot_name}(你) 说:"
        else:
            return []
        
        # 应用截断逻辑
        if truncate and content:
            content = _truncate_message_content(content, index, total_messages)
        
        result = [header]
        if content:
            # 如果内容已被截断（以特定后缀结尾），不再添加分号
            if content.endswith("）"):
                result.append(content)
            else:
                result.append(f"{content[:-1] if content.endswith('。') else content};")
        result.append("")
        return result

    formatted = [line for i, msg in enumerate(messages_slice) for line in format_message(msg, i)]
    return "\n".join(formatted).strip() or "还没有聊天记录。"


def format_new_messages(unprocessed_messages: list[dict[str, Any]], processed_times: set[float] | None = None,
                        bot_name: str = "Bot") -> tuple[str, int]:
    """格式化新消息"""
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
        sender = f"{bot_name}(你)" if msg.get("type") == "bot_message" else msg.get("user_name", "用户")
        content = content[:-1] if content.endswith("。") else content
        new_blocks.extend([f"{readable_time} {sender} 说:", f"{content};", ""])
    return "\n".join(new_blocks).strip(), len(new_blocks) // 3


def _truncate_text(text: str, limit: int) -> str:
    if not text or limit <= 0:
        return text or ""
    text = text.strip()
    return text if len(text) <= limit else (text[:max(0, limit - 1)] + "…")


def _format_md_cell(value: str, max_length: int = 500) -> str:
    value = (value or "").replace("\r\n", "\n").replace("\n", "<br>").replace("|", "\\|")
    return _truncate_text(value, max_length)


def _build_md_table(header: list[str], rows: list[list[str]], title: str = "") -> str:
    lines = ["|" + "|".join(header) + "|", "|" + "|".join(["---"] * len(header)) + "|"]
    lines.extend("|" + "|".join(row) + "|" for row in rows)
    return (f"{title}\n" if title else "") + "\n".join(lines)


_ACTION_TYPE_ALIAS = {
    "direct_reply": "直接回复", "send_new_message": "发送新消息", "fetch_knowledge": "调取知识",
    "wait": "等待", "listening": "倾听", "rethink_goal": "重新思考目标",
    "end_conversation": "结束对话", "say_goodbye": "告别", "block_and_ignore": "屏蔽忽略",
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
        status = action_data.get("status", "未知")
        rows.append([
            str(idx), _format_md_cell(str(action_data.get("time", "")), max_cell_length),
            _format_md_cell(_ACTION_TYPE_ALIAS.get(action_type, action_type) or action_type, max_cell_length),
            _format_md_cell(str(action_data.get("plan_reason", "未知规划原因")), max_cell_length),
            _format_md_cell(_STATUS_ALIAS.get(status, status) or status, max_cell_length),
            _format_md_cell(str(action_data.get("final_reason", "")), max_cell_length),
        ])
    return _build_md_table(["#", "时间", "行动类型", "规划原因", "状态", "失败原因"], rows, "（结构化行动历史表）")


def build_chat_history_table(chat_history: list[dict[str, Any]], bot_name: str = "Bot",
                             user_name: str = "用户", max_messages: int = 30, max_cell_length: int = 500) -> str:
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
            str(idx), _format_md_cell(translate_timestamp(msg.get("time", time.time()), mode="lite"), max_cell_length),
            _format_md_cell(speaker, max_cell_length), _format_md_cell(content, max_cell_length),
        ])
    return _build_md_table(["#", "时间", "发言人", "内容"], rows, "（结构化聊天历史表）")


# ============================================================================
# JSON 解析和文本处理工具函数 (原 utils.py)
# ============================================================================

def get_items_from_json(text: str, *keys: str, default: Any = None) -> tuple:
    """从文本中提取 JSON 并获取指定键的值
    
    Args:
        text: 包含 JSON 的文本
        *keys: 要提取的键名
        default: 键不存在时的默认值
    
    Returns:
        按键顺序返回的值组成的元组
    """
    json_obj = extract_json_from_text(text)
    if json_obj is None:
        return tuple(default for _ in keys)
    return tuple(json_obj.get(key, default) for key in keys)


def extract_json_from_text(text: str) -> Optional[dict]:
    """从文本中提取 JSON 对象
    
    支持多种格式：
    - 纯 JSON 字符串
    - Markdown 代码块中的 JSON
    - 文本中嵌入的 JSON
    
    Args:
        text: 包含 JSON 的文本
    
    Returns:
        解析后的字典，失败返回 None
    """
    if not text:
        logger.debug("[PFC] extract_json_from_text: 输入为空")
        return None
    text = text.strip()
    logger.debug(f"[PFC] extract_json_from_text: 输入文本长度={len(text)}, 前100字符={text[:100]!r}")

    patterns = [
        (lambda t: t, None, "直接解析"),
        (lambda t: re.findall(r'```(?:json)?\s*\n?([\s\S]*?)\n?```', t), 'strip', "Markdown代码块"),
        (lambda t: re.findall(r'\{[\s\S]*\}', t), None, "花括号匹配")
    ]

    for pattern_func, process, pattern_name in patterns:
        try:
            if process is None and callable(pattern_func):
                result = pattern_func(text)
                if isinstance(result, str):
                    parsed = json.loads(result)
                    logger.debug(f"[PFC] extract_json_from_text: 使用'{pattern_name}'成功解析")
                    return parsed
            matches = pattern_func(text)
            if isinstance(matches, list):
                logger.debug(f"[PFC] extract_json_from_text: '{pattern_name}'找到{len(matches)}个匹配")
                for i, match in enumerate(matches):
                    try:
                        parsed = json.loads(match.strip() if process == 'strip' else match)
                        logger.debug(f"[PFC] extract_json_from_text: 使用'{pattern_name}'第{i+1}个匹配成功解析")
                        return parsed
                    except json.JSONDecodeError as e:
                        logger.debug(f"[PFC] extract_json_from_text: '{pattern_name}'第{i+1}个匹配解析失败: {e}")
                        continue
        except json.JSONDecodeError as e:
            logger.debug(f"[PFC] extract_json_from_text: '{pattern_name}'解析失败: {e}")
            continue
    logger.warning(f"[PFC] extract_json_from_text: 所有模式都无法解析JSON, 文本={text[:200]!r}")
    return None


def extract_json_array_from_text(text: str) -> Optional[list]:
    """从文本中提取 JSON 数组
    
    Args:
        text: 包含 JSON 数组的文本
    
    Returns:
        解析后的列表，失败返回 None
    """
    if not text:
        return None
    text = text.strip()

    patterns = [lambda t: t, lambda t: [m.strip() for m in re.findall(r'```(?:json)?\s*\n?([\s\S]*?)\n?```', t)],
                lambda t: re.findall(r'\[[\s\S]*\]', t)]

    for pattern_func in patterns:
        candidates = [pattern_func(text)] if not isinstance(pattern_func(text), list) else pattern_func(text)
        for candidate in candidates:
            try:
                result = json.loads(candidate)
                if isinstance(result, list):
                    return result
            except (json.JSONDecodeError, TypeError):
                continue
    return None


def truncate_text(text: str, max_length: int = 100, suffix: str = "...") -> str:
    """截断文本到指定长度
    
    Args:
        text: 要截断的文本
        max_length: 最大长度
        suffix: 截断后添加的后缀
    
    Returns:
        截断后的文本
    """
    if not text or len(text) <= max_length:
        return text or ""
    return text[:max_length - len(suffix)] + suffix


def format_time_delta(seconds: float) -> str:
    """格式化时间差为人类可读格式
    
    Args:
        seconds: 时间差（秒）
    
    Returns:
        格式化的时间差，如 "3小时25分"、"5分30秒"
    """
    units = [(86400, "天", 3600), (3600, "小时", 60), (60, "分", 1), (1, "秒", 0)]
    for divisor, unit, sub_divisor in units:
        if seconds >= divisor:
            main = int(seconds / divisor)
            if sub_divisor:
                sub = int((seconds % divisor) / sub_divisor)
                return f"{main}{unit}{sub}{units[units.index((divisor, unit, sub_divisor)) + 1][1]}" if sub > 0 else f"{main}{unit}"
            return f"{main}{unit}"
    return f"{int(seconds)}秒"


def clean_llm_response(text: str) -> str:
    """清理 LLM 响应文本
    
    移除 Markdown 代码块标记和多余的引号
    
    Args:
        text: LLM 原始响应
    
    Returns:
        清理后的文本
    """
    if not text:
        return ""
    text = text.strip()
    if text.startswith("```") and text.endswith("```"):
        lines = text.split("\n")
        if len(lines) > 2:
            text = "\n".join(lines[1:-1])
    if (text.startswith('"') and text.endswith('"')) or (text.startswith("'") and text.endswith("'")):
        text = text[1:-1]
    return text.strip()


def safe_json_dumps(obj: Any, ensure_ascii: bool = False, indent: Optional[int] = None) -> str:
    """安全的 JSON 序列化
    
    Args:
        obj: 要序列化的对象
        ensure_ascii: 是否转义非 ASCII 字符
        indent: 缩进空格数
    
    Returns:
        JSON 字符串，失败返回 "{}"
    """
    try:
        return json.dumps(obj, ensure_ascii=ensure_ascii, indent=indent)
    except (TypeError, ValueError) as e:
        logger.error(f"JSON序列化失败: {e}")
        return "{}"


def merge_dicts(base: dict, override: dict) -> dict:
    """深度合并两个字典
    
    Args:
        base: 基础字典
        override: 覆盖字典
    
    Returns:
        合并后的新字典
    """
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = merge_dicts(result[key], value)
        else:
            result[key] = value
    return result


def extract_thinking_and_content(text: str) -> tuple[str, str]:
    """从 LLM 响应中分离思考过程和实际内容
    
    支持以下标记：
    - <thinking>...</thinking>
    - [思考]...[/思考]
    
    Args:
        text: LLM 响应文本
    
    Returns:
        (思考过程, 实际内容) 元组
    """
    if not text:
        return "", ""
    patterns = [(r'<thinking>([\s\S]*?)</thinking>', re.IGNORECASE), (r'\[思考\]([\s\S]*?)\[/思考\]', 0)]
    for pattern, flags in patterns:
        match = re.search(pattern, text, flags) if flags else re.search(pattern, text)
        if match:
            thinking = match.group(1).strip()
            content = re.sub(pattern, '', text, flags=flags if flags else 0).strip()
            return thinking, content
    return "", text


def parse_action_from_response(text: str) -> Optional[dict]:
    """从 LLM 响应中解析行动信息
    
    Args:
        text: LLM 响应文本
    
    Returns:
        包含 "action_type" 字段的字典，失败返回 None
    """
    json_obj = extract_json_from_text(text)
    if json_obj is None:
        return None
    if "action_type" not in json_obj:
        action_type = next((json_obj[k] for k in ["action", "type", "行动类型"] if k in json_obj), None)
        if action_type:
            json_obj["action_type"] = action_type
        else:
            return None
    return json_obj


def format_message_for_context(sender: str, content: str, timestamp: Optional[str] = None, max_content_length: int = 500) -> str:
    """格式化消息用于上下文展示
    
    Args:
        sender: 发送者名称
        content: 消息内容
        timestamp: 时间戳（可选）
        max_content_length: 内容最大长度
    
    Returns:
        格式化的消息字符串
    """
    content = truncate_text(content, max_content_length)
    return f"[{timestamp}] {sender}: {content}" if timestamp else f"{sender}: {content}"


def calculate_response_urgency(time_since_last_message: float, is_mentioned: bool = False,
                               is_direct_message: bool = False, message_count: int = 1) -> float:
    """计算响应紧急度
    
    Args:
        time_since_last_message: 距上次消息的时间（秒）
        is_mentioned: 是否被提及
        is_direct_message: 是否为私聊
        message_count: 消息数量
    
    Returns:
        紧急度分数 (0.0 - 1.0)
    """
    urgency = 0.0
    if time_since_last_message < 10:
        urgency += 0.3
    elif time_since_last_message < 30:
        urgency += 0.2
    elif time_since_last_message < 60:
        urgency += 0.1
    if is_mentioned:
        urgency += 0.3
    if is_direct_message:
        urgency += 0.2
    if message_count > 3:
        urgency += 0.2
    elif message_count > 1:
        urgency += 0.1
    return min(urgency, 1.0)