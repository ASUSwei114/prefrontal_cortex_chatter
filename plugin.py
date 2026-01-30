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

import sys
from dataclasses import dataclass, field
from typing import Any, ClassVar, TYPE_CHECKING

from src.common.logger import get_logger
from src.plugin_system import register_plugin
from src.plugin_system.base.base_plugin import BasePlugin
from src.plugin_system.base.config_types import ConfigField

if TYPE_CHECKING:
    from .chatter import PrefrontalCortexChatter as _PrefrontalCortexChatter

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
    enable_block_action: bool = True  # 是否启用 block_and_ignore 动作
    clear_goals_on_timeout: bool = False  # 等待超时时是否清空旧目标


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
    inject_system_prompt: bool = False  # 是否注入 MoFox 系统提示词


@dataclass
class PFCConfig:
    """PFC 总配置"""
    enabled: bool = True
    waiting: WaitingConfig = field(default_factory=WaitingConfig)
    session: SessionConfig = field(default_factory=SessionConfig)
    reply_checker: ReplyCheckerConfig = field(default_factory=ReplyCheckerConfig)
    web_search: WebSearchConfig = field(default_factory=WebSearchConfig)
    prompt: PromptConfig = field(default_factory=PromptConfig)
    
    @property
    def enabled_stream_types(self) -> list[str]:
        """启用的消息源类型（硬编码为 private）"""
        return ["private"]


# 全局配置单例 - 使用 sys.modules 确保跨模块实例共享
# 由于插件管理器使用 spec_from_file_location 加载模块，可能导致模块被多次实例化
# 使用 sys.modules 中的特殊键来存储配置，确保所有导入都共享同一份配置
_CONFIG_KEY = "_pfc_plugin_config_holder"

def _get_config_holder() -> dict[str, Any]:
    """获取全局配置持有者字典"""
    if _CONFIG_KEY not in sys.modules:
        sys.modules[_CONFIG_KEY] = {"config": None, "plugin_config": None}  # type: ignore
    return sys.modules[_CONFIG_KEY]  # type: ignore


def set_plugin_config(config_dict: dict[str, Any]) -> None:
    """设置插件配置（由插件调用）"""
    holder = _get_config_holder()
    holder["plugin_config"] = config_dict
    holder["config"] = None  # 重置缓存，下次获取时重新加载
    logger.info("[PFC] set_plugin_config: 已设置插件配置")


def get_config() -> PFCConfig:
    """获取全局配置"""
    holder = _get_config_holder()
    if holder["config"] is None:
        holder["config"] = _load_config()
    return holder["config"]


def _load_config_internal(
    enabled: bool,
    waiting: dict,
    session: dict,
    reply_checker: dict,
    web_search: dict,
    prompt: dict
) -> PFCConfig:
    """内部配置加载函数（统一加载逻辑）"""
    try:
        return PFCConfig(
            enabled=enabled,
            waiting=WaitingConfig(
                wait_timeout_seconds=waiting.get("wait_timeout_seconds", 300),
                block_ignore_seconds=waiting.get("block_ignore_seconds", 1800),
                enable_block_action=waiting.get("enable_block_action", True),
            ),
            session=SessionConfig(
                session_expire_seconds=session.get("session_expire_seconds", 86400 * 7),
                max_history_entries=session.get("max_history_entries", 100),
                initial_history_limit=session.get("initial_history_limit", 30),
            ),
            reply_checker=ReplyCheckerConfig(
                enabled=reply_checker.get("enabled", True),
                use_llm_check=reply_checker.get("use_llm_check", True),
                similarity_threshold=reply_checker.get("similarity_threshold", 0.9),
                max_retries=reply_checker.get("max_retries", 3),
            ),
            web_search=WebSearchConfig(
                enabled=web_search.get("enabled", True),
                num_results=web_search.get("num_results", 3),
                time_range=web_search.get("time_range", "any"),
                answer_mode=web_search.get("answer_mode", False),
            ),
            prompt=PromptConfig(
                activity_stream_format=prompt.get("activity_stream_format", "narrative"),
                max_activity_entries=prompt.get("max_activity_entries", 30),
                max_entry_length=prompt.get("max_entry_length", 500),
                inject_system_prompt=prompt.get("inject_system_prompt", False),
            )
        )
    except Exception as e:
        logger.warning(f"配置加载失败，使用默认值: {e}")
        return PFCConfig()


def _load_config() -> PFCConfig:
    """加载 PFC 配置"""
    holder = _get_config_holder()
    
    if holder["plugin_config"]:
        return _load_from_plugin_config(holder["plugin_config"])
    else:
        return _load_from_global_config()


def _load_from_plugin_config(cfg: dict[str, Any]) -> PFCConfig:
    """从插件配置字典加载配置"""
    return _load_config_internal(
        enabled=cfg.get("plugin", {}).get("enabled", True),
        waiting=cfg.get("waiting", {}),
        session=cfg.get("session", {}),
        reply_checker=cfg.get("reply_checker", {}),
        web_search=cfg.get("web_search", {}),
        prompt=cfg.get("prompt", {})
    )


def _load_from_global_config() -> PFCConfig:
    """从全局配置加载 PFC 配置（兼容旧版）"""
    from src.config.config import global_config

    if not global_config or not hasattr(global_config, "prefrontal_cortex_chatter"):
        return PFCConfig()

    pfc_cfg = getattr(global_config, "prefrontal_cortex_chatter")
    
    # 提取配置对象或使用空字典
    def get_config_dict(cfg, attr):
        obj = getattr(cfg, attr, None) if hasattr(cfg, attr) else None
        if obj is None:
            return {}
        return {k: getattr(obj, k, None) for k in dir(obj) if not k.startswith('_')}
    
    return _load_config_internal(
        enabled=getattr(getattr(pfc_cfg, "plugin", None), "enabled", True) if hasattr(pfc_cfg, "plugin") else True,
        waiting=get_config_dict(pfc_cfg, "waiting"),
        session=get_config_dict(pfc_cfg, "session"),
        reply_checker=get_config_dict(pfc_cfg, "reply_checker"),
        web_search=get_config_dict(pfc_cfg, "web_search"),
        prompt=get_config_dict(pfc_cfg, "prompt")
    )


def reload_config() -> PFCConfig:
    """重新加载配置"""
    holder = _get_config_holder()
    holder["config"] = _load_config()
    return holder["config"]


# ============================================================================
# 插件组件（延迟导入以避免循环导入）
# ============================================================================


def _get_chatter_class():
    """延迟获取 PrefrontalCortexChatter 类"""
    from .chatter import PrefrontalCortexChatter
    return PrefrontalCortexChatter


def _get_reply_action_class():
    """延迟获取 PFCReplyAction 类"""
    from .actions.reply import PFCReplyAction
    return PFCReplyAction


# 配置文件版本号 - 更新配置结构时递增此版本
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
        "inner": "配置元信息",
        "plugin": "插件基础配置",
        "waiting": "等待行为配置",
        "session": "会话管理配置",
        "reply_checker": "回复检查器配置",
        "web_search": "联网搜索配置",
        "prompt": "提示词配置",
    }

    config_schema: ClassVar[dict[str, dict[str, ConfigField]]] = {
        "inner": {
            "version": ConfigField(type=str, default=CONFIG_VERSION, description="配置文件版本号"),
        },
        "plugin": {
            "enabled": ConfigField(type=bool, default=True, description="是否启用 PFC 私聊聊天器"),
        },
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
        "prompt": {
            "activity_stream_format": ConfigField(
                type=str,
                default="narrative",
                description="活动流格式：narrative（线性叙事）/ table（结构化表格）/ both（两者都给）"
            ),
            "max_activity_entries": ConfigField(type=int, default=30, description="活动记录保留条数"),
            "max_entry_length": ConfigField(type=int, default=500, description="每条记录最大字符数"),
            "inject_system_prompt": ConfigField(
                type=bool,
                default=False,
                description="是否注入 MoFox 系统提示词（启用后会使用 replyer_private 模型配置）"
            ),
        },
    }

    async def on_plugin_loaded(self):
        """插件加载时"""
        set_plugin_config(self.config)
        config = get_config()

        if not config.enabled:
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
        """插件卸载时"""
        logger.info("[PFC] 插件已卸载")

    def get_plugin_components(self):
        """返回组件列表"""
        if not get_config().enabled:
            return []

        components = []
        for name, loader in [("Chatter", _get_chatter_class), ("ReplyAction", _get_reply_action_class)]:
            try:
                cls = loader()
                components.append((cls.get_chatter_info() if name == "Chatter" else cls.get_action_info(), cls))
                logger.debug(f"[PFC] 成功加载 {name} 组件")
            except Exception as e:
                logger.error(f"[PFC] 加载 {name} 组件失败: {e}")

        return components

    def get_plugin_info(self) -> dict[str, Any]:
        """获取插件信息"""
        return {
            "name": self.plugin_name,
            "display_name": "Prefrontal Cortex Chatter",
            "version": "1.0.0",
            "author": "MaiM-with-u",
            "description": "目标驱动的私聊系统",
            "features": ["目标驱动对话", "多种行动类型", "回复质量检查", "主动思考"],
        }