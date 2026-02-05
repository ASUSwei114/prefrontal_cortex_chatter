"""
Prefrontal Cortex Chatter - 插件注册与配置

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
- 重构为独立插件模块

本项目遵循 GNU General Public License v3.0 许可证。
详见 LICENSE 文件。

================================================================================
"""

import dataclasses
import sys
from dataclasses import dataclass, field
from typing import Any, ClassVar

from src.common.logger import get_logger
from src.plugin_system import register_plugin
from src.plugin_system.base.base_plugin import BasePlugin
from src.plugin_system.base.config_types import ConfigField

logger = get_logger("pfc_plugin")


# ============================================================================
# 配置数据类
# ============================================================================

@dataclass
class ReplyCheckerConfig:
    """回复检查器配置"""
    enabled: bool = True
    use_llm_check: bool = True
    similarity_threshold: float = 0.9
    max_retries: int = 3

@dataclass
class ToolConfig:
    """工具调用配置"""
    enabled: bool = True
    enable_in_planner: bool = True
    enable_in_replyer: bool = False

@dataclass
class WebSearchConfig:
    """联网搜索配置"""
    enabled: bool = True
    num_results: int = 3
    time_range: str = "any"
    answer_mode: bool = False

@dataclass
class WaitingConfig:
    """等待配置"""
    wait_timeout_seconds: int = 300
    block_ignore_seconds: int = 1800
    enable_block_action: bool = True
    clear_goals_on_timeout: bool = False

@dataclass
class SessionConfig:
    """会话配置"""
    session_expire_seconds: int = 86400 * 7
    max_history_entries: int = 100
    initial_history_limit: int = 30

@dataclass
class PromptConfig:
    """提示词配置"""
    activity_stream_format: str = "narrative"
    max_activity_entries: int = 30
    max_entry_length: int = 500
    inject_system_prompt: bool = False

@dataclass
class PFCConfig:
    """PFC 总配置"""
    enabled: bool = True
    waiting: WaitingConfig = field(default_factory=WaitingConfig)
    session: SessionConfig = field(default_factory=SessionConfig)
    reply_checker: ReplyCheckerConfig = field(default_factory=ReplyCheckerConfig)
    web_search: WebSearchConfig = field(default_factory=WebSearchConfig)
    tool: ToolConfig = field(default_factory=ToolConfig)
    prompt: PromptConfig = field(default_factory=PromptConfig)

    @property
    def enabled_stream_types(self) -> list[str]:
        return ["private"]


# ============================================================================
# 全局配置管理
# ============================================================================

_CONFIG_KEY = "_pfc_plugin_config_holder"

def _get_holder() -> dict[str, Any]:
    """获取全局配置持有者"""
    if _CONFIG_KEY not in sys.modules:
        sys.modules[_CONFIG_KEY] = {"config": None, "plugin_config": None}  # type: ignore
    return sys.modules[_CONFIG_KEY]  # type: ignore

def set_plugin_config(config_dict: dict[str, Any]) -> None:
    """设置插件配置"""
    holder = _get_holder()
    holder["plugin_config"] = config_dict
    holder["config"] = None
    logger.info("[PFC] 已设置插件配置")

def get_config() -> PFCConfig:
    """获取全局配置"""
    holder = _get_holder()
    if holder["config"] is None:
        holder["config"] = _load_config(holder["plugin_config"])
    return holder["config"]

def reload_config() -> PFCConfig:
    """重新加载配置"""
    holder = _get_holder()
    holder["config"] = _load_config(holder["plugin_config"])
    return holder["config"]

def _dict_to_dataclass(cls, data: dict):
    """将字典转换为 dataclass 实例"""
    defaults = {f.name: f.default for f in dataclasses.fields(cls)}
    return cls(**{k: data.get(k, v) for k, v in defaults.items()})

def _load_config(plugin_cfg: dict[str, Any] | None) -> PFCConfig:
    """加载 PFC 配置"""
    try:
        if plugin_cfg:
            cfg, get = plugin_cfg, lambda k: plugin_cfg.get(k, {})
            enabled = cfg.get("plugin", {}).get("enabled", True)
        else:
            from src.config.config import global_config
            if not global_config or not hasattr(global_config, "prefrontal_cortex_chatter"):
                return PFCConfig()
            pfc = global_config.prefrontal_cortex_chatter
            get = lambda k: {a: getattr(getattr(pfc, k, None), a)
                            for a in dir(getattr(pfc, k, None) or object()) if not a.startswith('_')}
            enabled = getattr(getattr(pfc, "plugin", None), "enabled", True)
        
        return PFCConfig(
            enabled=enabled,
            waiting=_dict_to_dataclass(WaitingConfig, get("waiting")),
            session=_dict_to_dataclass(SessionConfig, get("session")),
            reply_checker=_dict_to_dataclass(ReplyCheckerConfig, get("reply_checker")),
            web_search=_dict_to_dataclass(WebSearchConfig, get("web_search")),
            tool=_dict_to_dataclass(ToolConfig, get("tool")),
            prompt=_dict_to_dataclass(PromptConfig, get("prompt")),
        )
    except Exception as e:
        logger.warning(f"配置加载失败，使用默认值: {e}")
        return PFCConfig()


# ============================================================================
# 插件类
# ============================================================================

CONFIG_VERSION = "1.5.0"

@register_plugin
class PrefrontalCortexChatterPlugin(BasePlugin):
    """Prefrontal Cortex Chatter 插件 - 目标驱动的私聊系统"""

    plugin_name: str = "prefrontal_cortex_chatter"
    enable_plugin: bool = True
    plugin_priority: int = 55
    dependencies: ClassVar[list[str]] = []
    python_dependencies: ClassVar[list[str]] = []
    config_file_name: str = "config.toml"

    config_section_descriptions: ClassVar[dict[str, str]] = {
        "inner": "配置元信息", "plugin": "插件基础配置", "waiting": "等待行为配置",
        "session": "会话管理配置", "reply_checker": "回复检查器配置",
        "web_search": "联网搜索配置", "tool": "工具调用配置", "prompt": "提示词配置",
    }

    config_schema: ClassVar[dict[str, dict[str, ConfigField]]] = {
        "inner": {"version": ConfigField(type=str, default=CONFIG_VERSION, description="配置文件版本号")},
        "plugin": {"enabled": ConfigField(type=bool, default=True, description="是否启用 PFC 私聊聊天器")},
        "waiting": {
            "wait_timeout_seconds": ConfigField(type=int, default=300, description="等待超时时间（秒）"),
            "block_ignore_seconds": ConfigField(type=int, default=1800, description="屏蔽忽略时间（秒）"),
            "enable_block_action": ConfigField(type=bool, default=True, description="是否启用屏蔽动作"),
        },
        "session": {
            "session_expire_seconds": ConfigField(type=int, default=604800, description="会话过期时间（秒）"),
            "max_history_entries": ConfigField(type=int, default=100, description="最大历史记录条数"),
            "initial_history_limit": ConfigField(type=int, default=30, description="初始历史消息条数"),
        },
        "reply_checker": {
            "enabled": ConfigField(type=bool, default=True, description="是否启用回复检查器"),
            "use_llm_check": ConfigField(type=bool, default=True, description="是否使用 LLM 深度检查"),
            "similarity_threshold": ConfigField(type=float, default=0.9, description="相似度阈值（0-1）"),
            "max_retries": ConfigField(type=int, default=3, description="最大重试次数"),
        },
        "web_search": {
            "enabled": ConfigField(type=bool, default=True, description="是否启用联网搜索"),
            "num_results": ConfigField(type=int, default=3, description="搜索结果数量"),
            "time_range": ConfigField(type=str, default="any", description="搜索时间范围"),
            "answer_mode": ConfigField(type=bool, default=False, description="是否启用答案模式"),
        },
        "tool": {
            "enabled": ConfigField(type=bool, default=True, description="是否启用工具调用"),
            "enable_in_planner": ConfigField(type=bool, default=True, description="是否在规划器中显示工具信息"),
            "enable_in_replyer": ConfigField(type=bool, default=True, description="是否在回复生成器中显示工具信息"),
        },
        "prompt": {
            "activity_stream_format": ConfigField(type=str, default="narrative", description="活动流格式"),
            "max_activity_entries": ConfigField(type=int, default=30, description="活动记录保留条数"),
            "max_entry_length": ConfigField(type=int, default=500, description="每条记录最大字符数"),
            "inject_system_prompt": ConfigField(type=bool, default=False, description="是否注入 MoFox 系统提示词"),
        },
    }

    async def on_plugin_loaded(self):
        """插件加载时"""
        set_plugin_config(self.config)
        if not get_config().enabled:
            logger.info("[PFC] 插件已禁用")
            return
        await self._ensure_database_tables()
        logger.info(f"[PFC] 插件已加载 (v{self.config.get('inner', {}).get('version', 'unknown')})")

    async def _ensure_database_tables(self):
        """确保 PFC 数据库表已创建"""
        try:
            from .db_models import PFCChatHistory, PFCSession  # noqa: F401
            from src.common.database.core.migration import check_and_migrate_database
            await check_and_migrate_database()
            logger.info("[PFC] 数据库表初始化完成")
        except Exception as e:
            logger.error(f"[PFC] 数据库表初始化失败: {e}")
            raise RuntimeError(f"PFC 数据库初始化失败: {e}")

    async def on_plugin_unloaded(self):
        logger.info("[PFC] 插件已卸载")

    def get_plugin_components(self):
        """返回组件列表"""
        if not get_config().enabled:
            return []
        
        components = []
        loaders = [
            ("chatter", "PrefrontalCortexChatter", "get_chatter_info"),
            ("actions.reply", "PFCReplyAction", "get_action_info"),
        ]
        for module, cls_name, info_method in loaders:
            try:
                from importlib import import_module
                mod = import_module(f".{module}", package=__package__)
                cls = getattr(mod, cls_name)
                components.append((getattr(cls, info_method)(), cls))
            except Exception as e:
                logger.error(f"[PFC] 加载 {cls_name} 失败: {e}")
        return components

    def get_plugin_info(self) -> dict[str, Any]:
        return {
            "name": self.plugin_name, "display_name": "Prefrontal Cortex Chatter",
            "version": "1.0.0", "author": "MaiM-with-u", "description": "目标驱动的私聊系统",
            "features": ["目标驱动对话", "多种行动类型", "回复质量检查", "主动思考"],
        }