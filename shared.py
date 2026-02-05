"""PFC 共享工具模块 - 提供各模块共享的工具函数和类 (GPL-3.0)"""

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
    """将时间戳转换为人类可读的时间格式"""
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
    """获取当前时间的人类可读格式"""
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
    """人格信息获取助手"""

    def __init__(self, user_name: str = "用户"):
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
    """构建对话目标字符串"""
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
    """构建知识信息字符串"""
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


def format_chat_history(chat_history: list[dict[str, Any]], bot_name: str = "Bot",
                        user_name: str = "用户", max_messages: int = 30) -> str:
    """格式化聊天历史为可读文本"""
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
            result.append(f"{content[:-1] if content.endswith('。') else content};")
        result.append("")
        return result

    formatted = [line for msg in chat_history[-max_messages:] for line in format_message(msg)]
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
    """从文本中提取JSON并获取指定键的值"""
    json_obj = extract_json_from_text(text)
    if json_obj is None:
        return tuple(default for _ in keys)
    return tuple(json_obj.get(key, default) for key in keys)


def extract_json_from_text(text: str) -> Optional[dict]:
    """从文本中提取JSON对象"""
    if not text:
        return None
    text = text.strip()

    patterns = [
        (lambda t: t, None),
        (lambda t: re.findall(r'```(?:json)?\s*\n?([\s\S]*?)\n?```', t), 'strip'),
        (lambda t: re.findall(r'\{[\s\S]*\}', t), None)
    ]

    for pattern_func, process in patterns:
        try:
            if process is None and callable(pattern_func):
                result = pattern_func(text)
                if isinstance(result, str):
                    return json.loads(result)
            matches = pattern_func(text)
            if isinstance(matches, list):
                for match in matches:
                    try:
                        return json.loads(match.strip() if process == 'strip' else match)
                    except json.JSONDecodeError:
                        continue
        except json.JSONDecodeError:
            continue
    return None


def extract_json_array_from_text(text: str) -> Optional[list]:
    """从文本中提取JSON数组"""
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
    """截断文本到指定长度"""
    if not text or len(text) <= max_length:
        return text or ""
    return text[:max_length - len(suffix)] + suffix


def format_time_delta(seconds: float) -> str:
    """格式化时间差为人类可读格式"""
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
    """清理LLM响应文本"""
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
    """安全的JSON序列化"""
    try:
        return json.dumps(obj, ensure_ascii=ensure_ascii, indent=indent)
    except (TypeError, ValueError) as e:
        logger.error(f"JSON序列化失败: {e}")
        return "{}"


def merge_dicts(base: dict, override: dict) -> dict:
    """深度合并两个字典"""
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = merge_dicts(result[key], value)
        else:
            result[key] = value
    return result


def extract_thinking_and_content(text: str) -> tuple[str, str]:
    """从LLM响应中分离思考过程和实际内容"""
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
    """从LLM响应中解析行动信息"""
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
    """格式化消息用于上下文展示"""
    content = truncate_text(content, max_content_length)
    return f"[{timestamp}] {sender}: {content}" if timestamp else f"{sender}: {content}"


def calculate_response_urgency(time_since_last_message: float, is_mentioned: bool = False,
                               is_direct_message: bool = False, message_count: int = 1) -> float:
    """计算响应紧急度 (0.0 - 1.0)"""
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