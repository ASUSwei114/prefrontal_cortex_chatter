"""
PFC聊天器工具函数模块

================================================================================
版权声明 (Copyright Notice)
================================================================================

原始代码来源: MaiM-with-u (https://github.com/MaiM-with-u/MaiBot)
原始版本: 0.6.3-fix4
原始代码路径: src/plugins/PFC/pfc_utils.py
原始许可证: GNU General Public License v3.0

本文件由 ASUSwei114 (https://github.com/ASUSwei114) 于 2024年12月 修改移植至 MoFox_Bot 项目。

本项目遵循 GNU General Public License v3.0 许可证。
详见 LICENSE 文件。

================================================================================

提供JSON解析、文本处理等通用工具函数
"""

import json
import re
from typing import Any, Optional
from src.common.logger import get_logger

logger = get_logger("PFC-Utils")


def get_items_from_json(
    text: str,
    *keys: str,
    default: Any = None
) -> tuple:
    """
    从文本中提取JSON并获取指定键的值
    
    Args:
        text: 包含JSON的文本
        *keys: 要提取的键名
        default: 默认值（当键不存在时返回）
        
    Returns:
        包含各键值的元组
    """
    json_obj = extract_json_from_text(text)
    
    if json_obj is None:
        return tuple(default for _ in keys)
    
    results = []
    for key in keys:
        value = json_obj.get(key, default)
        results.append(value)
    
    return tuple(results)


def extract_json_from_text(text: str) -> Optional[dict]:
    """
    从文本中提取JSON对象
    
    支持以下格式：
    1. 纯JSON文本
    2. ```json ... ``` 代码块
    3. { ... } 包裹的JSON
    
    Args:
        text: 包含JSON的文本
        
    Returns:
        解析后的字典，失败返回None
    """
    if not text:
        return None
    
    text = text.strip()
    
    # 尝试直接解析
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    
    # 尝试从markdown代码块提取
    json_block_pattern = r'```(?:json)?\s*\n?([\s\S]*?)\n?```'
    matches = re.findall(json_block_pattern, text)
    for match in matches:
        try:
            return json.loads(match.strip())
        except json.JSONDecodeError:
            continue
    
    # 尝试找到 { } 包裹的内容
    brace_pattern = r'\{[\s\S]*\}'
    matches = re.findall(brace_pattern, text)
    for match in matches:
        try:
            return json.loads(match)
        except json.JSONDecodeError:
            continue
    
    logger.warning(f"无法从文本中提取JSON: {text[:100]}...")
    return None


def extract_json_array_from_text(text: str) -> Optional[list]:
    """
    从文本中提取JSON数组
    
    Args:
        text: 包含JSON数组的文本
        
    Returns:
        解析后的列表，失败返回None
    """
    if not text:
        return None
    
    text = text.strip()
    
    # 尝试直接解析
    try:
        result = json.loads(text)
        if isinstance(result, list):
            return result
    except json.JSONDecodeError:
        pass
    
    # 尝试从markdown代码块提取
    json_block_pattern = r'```(?:json)?\s*\n?([\s\S]*?)\n?```'
    matches = re.findall(json_block_pattern, text)
    for match in matches:
        try:
            result = json.loads(match.strip())
            if isinstance(result, list):
                return result
        except json.JSONDecodeError:
            continue
    
    # 尝试找到 [ ] 包裹的内容
    bracket_pattern = r'\[[\s\S]*\]'
    matches = re.findall(bracket_pattern, text)
    for match in matches:
        try:
            result = json.loads(match)
            if isinstance(result, list):
                return result
        except json.JSONDecodeError:
            continue
    
    return None


def truncate_text(text: str, max_length: int = 100, suffix: str = "...") -> str:
    """
    截断文本到指定长度
    
    Args:
        text: 原始文本
        max_length: 最大长度
        suffix: 截断后的后缀
        
    Returns:
        截断后的文本
    """
    if not text:
        return ""
    
    if len(text) <= max_length:
        return text
    
    return text[:max_length - len(suffix)] + suffix


def format_time_delta(seconds: float) -> str:
    """
    格式化时间差为人类可读格式
    
    Args:
        seconds: 秒数
        
    Returns:
        格式化的时间字符串
    """
    if seconds < 60:
        return f"{int(seconds)}秒"
    elif seconds < 3600:
        minutes = int(seconds / 60)
        secs = int(seconds % 60)
        return f"{minutes}分{secs}秒" if secs > 0 else f"{minutes}分钟"
    elif seconds < 86400:
        hours = int(seconds / 3600)
        minutes = int((seconds % 3600) / 60)
        return f"{hours}小时{minutes}分" if minutes > 0 else f"{hours}小时"
    else:
        days = int(seconds / 86400)
        hours = int((seconds % 86400) / 3600)
        return f"{days}天{hours}小时" if hours > 0 else f"{days}天"


def clean_llm_response(text: str) -> str:
    """
    清理LLM响应文本
    
    移除常见的格式问题：
    - 多余的空白字符
    - markdown代码块标记
    - 引号包裹
    
    Args:
        text: 原始响应文本
        
    Returns:
        清理后的文本
    """
    if not text:
        return ""
    
    text = text.strip()
    
    # 移除markdown代码块
    if text.startswith("```") and text.endswith("```"):
        lines = text.split("\n")
        if len(lines) > 2:
            text = "\n".join(lines[1:-1])
    
    # 移除首尾引号
    if (text.startswith('"') and text.endswith('"')) or \
       (text.startswith("'") and text.endswith("'")):
        text = text[1:-1]
    
    return text.strip()


def safe_json_dumps(obj: Any, ensure_ascii: bool = False, indent: int = None) -> str:
    """
    安全的JSON序列化
    
    Args:
        obj: 要序列化的对象
        ensure_ascii: 是否转义非ASCII字符
        indent: 缩进空格数
        
    Returns:
        JSON字符串
    """
    try:
        return json.dumps(obj, ensure_ascii=ensure_ascii, indent=indent)
    except (TypeError, ValueError) as e:
        logger.error(f"JSON序列化失败: {e}")
        return "{}"


def merge_dicts(base: dict, override: dict) -> dict:
    """
    深度合并两个字典
    
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
    """
    从LLM响应中分离思考过程和实际内容
    
    支持格式：
    - <thinking>...</thinking>
    - [思考]...[/思考]
    
    Args:
        text: LLM响应文本
        
    Returns:
        (thinking, content) 元组
    """
    if not text:
        return "", ""
    
    thinking = ""
    content = text
    
    # 尝试提取 <thinking> 标签
    thinking_pattern = r'<thinking>([\s\S]*?)</thinking>'
    match = re.search(thinking_pattern, text, re.IGNORECASE)
    if match:
        thinking = match.group(1).strip()
        content = re.sub(thinking_pattern, '', text, flags=re.IGNORECASE).strip()
    
    # 尝试提取 [思考] 标签
    if not thinking:
        thinking_pattern_cn = r'\[思考\]([\s\S]*?)\[/思考\]'
        match = re.search(thinking_pattern_cn, text)
        if match:
            thinking = match.group(1).strip()
            content = re.sub(thinking_pattern_cn, '', text).strip()
    
    return thinking, content


def parse_action_from_response(text: str) -> Optional[dict]:
    """
    从LLM响应中解析行动信息
    
    Args:
        text: LLM响应文本
        
    Returns:
        行动字典，包含action_type和相关参数
    """
    json_obj = extract_json_from_text(text)
    
    if json_obj is None:
        return None
    
    # 验证必要字段
    if "action_type" not in json_obj:
        # 尝试其他可能的字段名
        for alt_key in ["action", "type", "行动类型"]:
            if alt_key in json_obj:
                json_obj["action_type"] = json_obj[alt_key]
                break
    
    if "action_type" not in json_obj:
        logger.warning(f"响应中缺少action_type字段: {json_obj}")
        return None
    
    return json_obj


def format_message_for_context(
    sender: str,
    content: str,
    timestamp: str = None,
    max_content_length: int = 500
) -> str:
    """
    格式化消息用于上下文展示
    
    Args:
        sender: 发送者名称
        content: 消息内容
        timestamp: 时间戳
        max_content_length: 内容最大长度
        
    Returns:
        格式化的消息字符串
    """
    content = truncate_text(content, max_content_length)
    
    if timestamp:
        return f"[{timestamp}] {sender}: {content}"
    else:
        return f"{sender}: {content}"


def calculate_response_urgency(
    time_since_last_message: float,
    is_mentioned: bool = False,
    is_direct_message: bool = False,
    message_count: int = 1
) -> float:
    """
    计算响应紧急度
    
    Args:
        time_since_last_message: 距离上条消息的秒数
        is_mentioned: 是否被@提及
        is_direct_message: 是否是私聊
        message_count: 未读消息数量
        
    Returns:
        紧急度分数 (0.0 - 1.0)
    """
    urgency = 0.0
    
    # 基于时间的紧急度
    if time_since_last_message < 10:
        urgency += 0.3
    elif time_since_last_message < 30:
        urgency += 0.2
    elif time_since_last_message < 60:
        urgency += 0.1
    
    # 被提及增加紧急度
    if is_mentioned:
        urgency += 0.3
    
    # 私聊增加紧急度
    if is_direct_message:
        urgency += 0.2
    
    # 消息数量影响
    if message_count > 3:
        urgency += 0.2
    elif message_count > 1:
        urgency += 0.1
    
    return min(urgency, 1.0)