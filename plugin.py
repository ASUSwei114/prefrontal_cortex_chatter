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
class PFCConfig:
    """PFC 总配置"""
    enabled: bool = True
    waiting: WaitingConfig = field(default_factory=WaitingConfig)
    session: SessionConfig = field(default_factory=SessionConfig)
    reply_checker: ReplyCheckerConfig = field(default_factory=ReplyCheckerConfig)
    web_search: WebSearchConfig = field(default_factory=WebSearchConfig)
    
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


def _load_config() -> PFCConfig:
    """加载 PFC 配置"""
    holder = _get_config_holder()
    
    if holder["plugin_config"]:
        return _load_from_plugin_config(holder["plugin_config"])
    else:
        return _load_from_global_config()


def _load_from_plugin_config(cfg: dict[str, Any]) -> PFCConfig:
    """从插件配置字典加载配置"""
    config = PFCConfig()
    
    try:
        if "plugin" in cfg:
            config.enabled = cfg["plugin"].get("enabled", True)

        if "waiting" in cfg:
            w = cfg["waiting"]
            config.waiting = WaitingConfig(
                wait_timeout_seconds=w.get("wait_timeout_seconds", 300),
                block_ignore_seconds=w.get("block_ignore_seconds", 1800),
                enable_block_action=w.get("enable_block_action", True),
                clear_goals_on_timeout=w.get("clear_goals_on_timeout", False),
            )

        if "session" in cfg:
            s = cfg["session"]
            config.session = SessionConfig(
                session_expire_seconds=s.get("session_expire_seconds", 86400 * 7),
                max_history_entries=s.get("max_history_entries", 100),
                initial_history_limit=s.get("initial_history_limit", 30),
            )

        if "reply_checker" in cfg:
            r = cfg["reply_checker"]
            config.reply_checker = ReplyCheckerConfig(
                enabled=r.get("enabled", True),
                use_llm_check=r.get("use_llm_check", True),
                similarity_threshold=r.get("similarity_threshold", 0.9),
                max_retries=r.get("max_retries", 3),
            )

        if "web_search" in cfg:
            ws = cfg["web_search"]
            config.web_search = WebSearchConfig(
                enabled=ws.get("enabled", True),
                num_results=ws.get("num_results", 3),
                time_range=ws.get("time_range", "any"),
                answer_mode=ws.get("answer_mode", False),
            )

    except Exception as e:
        logger.warning(f"从插件配置加载失败，使用默认值: {e}")

    return config


def _load_from_global_config() -> PFCConfig:
    """从全局配置加载 PFC 配置（兼容旧版）"""
    from src.config.config import global_config

    config = PFCConfig()

    if not global_config:
        return config

    try:
        if hasattr(global_config, "prefrontal_cortex_chatter"):
            pfc_cfg = getattr(global_config, "prefrontal_cortex_chatter")

            if hasattr(pfc_cfg, "plugin"):
                plugin_cfg = pfc_cfg.plugin
                if hasattr(plugin_cfg, "enabled"):
                    config.enabled = plugin_cfg.enabled

            if hasattr(pfc_cfg, "waiting"):
                w = pfc_cfg.waiting
                config.waiting = WaitingConfig(
                    wait_timeout_seconds=getattr(w, "wait_timeout_seconds", 300),
                    block_ignore_seconds=getattr(w, "block_ignore_seconds", 1800),
                    enable_block_action=getattr(w, "enable_block_action", True),
                    clear_goals_on_timeout=getattr(w, "clear_goals_on_timeout", False),
                )

            if hasattr(pfc_cfg, "session"):
                s = pfc_cfg.session
                config.session = SessionConfig(
                    session_expire_seconds=getattr(s, "session_expire_seconds", 86400 * 7),
                    max_history_entries=getattr(s, "max_history_entries", 100),
                    initial_history_limit=getattr(s, "initial_history_limit", 30),
                )

            if hasattr(pfc_cfg, "reply_checker"):
                r = pfc_cfg.reply_checker
                config.reply_checker = ReplyCheckerConfig(
                    enabled=getattr(r, "enabled", True),
                    use_llm_check=getattr(r, "use_llm_check", True),
                    similarity_threshold=getattr(r, "similarity_threshold", 0.9),
                    max_retries=getattr(r, "max_retries", 3),
                )

            if hasattr(pfc_cfg, "web_search"):
                ws = pfc_cfg.web_search
                config.web_search = WebSearchConfig(
                    enabled=getattr(ws, "enabled", True),
                    num_results=getattr(ws, "num_results", 3),
                    time_range=getattr(ws, "time_range", "any"),
                    answer_mode=getattr(ws, "answer_mode", False),
                )

    except Exception as e:
        logger.warning(f"从全局配置加载失败，使用默认值: {e}")

    return config


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
CONFIG_VERSION = "1.4.0"


@register_plugin
class PrefrontalCortexChatterPlugin(BasePlugin):
    """
    Prefrontal Cortex Chatter 插件

    从 MaiM-with-u 0.6.3-fix4 移植的私聊系统：
    - 目标驱动的对话管理
    - 多种行动类型（回复、等待、倾听、获取知识等）
    - 回复质量检查
    """

    plugin_name: str = "prefrontal_cortex_chatter"
    enable_plugin: bool = True
    plugin_priority: int = 55  # 高于 KFC
    dependencies: ClassVar[list[str]] = []
    python_dependencies: ClassVar[list[str]] = []
    config_file_name: str = "config.toml"

    # 配置节描述
    config_section_descriptions: ClassVar[dict[str, str]] = {
        "inner": "配置元信息",
        "plugin": "插件基础配置",
        "waiting": "等待行为配置",
        "session": "会话管理配置",
        "reply_checker": "回复检查器配置",
        "web_search": "联网搜索配置",
    }

    # 配置 Schema - 用于自动生成和同步配置文件
    config_schema: ClassVar[dict[str, dict[str, ConfigField]]] = {
        "inner": {
            "version": ConfigField(
                type=str,
                default=CONFIG_VERSION,
                description="配置文件版本号（用于配置文件升级与兼容性检查）",
            ),
        },
        "plugin": {
            "enabled": ConfigField(
                type=bool,
                default=True,
                description="是否启用 PFC 私聊聊天器",
            ),
            # enabled_stream_types 已硬编码为 ["private"]，不再作为配置项
        },
        "waiting": {
            "wait_timeout_seconds": ConfigField(
                type=int,
                default=300,
                description="等待超时时间（秒），超时后AI会重新思考下一步行动",
            ),
            "block_ignore_seconds": ConfigField(
                type=int,
                default=1800,
                description="屏蔽忽略时间（秒，默认30分钟）- 执行 block_and_ignore 动作后忽略对方消息的时长",
            ),
            "enable_block_action": ConfigField(
                type=bool,
                default=True,
                description="是否启用 block_and_ignore 动作（屏蔽对方）。设为 false 可禁用此功能",
            ),
            "clear_goals_on_timeout": ConfigField(
                type=bool,
                default=False,
                description="等待超时时是否清空旧目标。true=清空旧目标只保留超时提示，false=保留旧目标并追加超时提示",
            ),
        },
        "session": {
            "session_expire_seconds": ConfigField(
                type=int,
                default=604800,
                description="会话过期时间（秒，默认7天）",
            ),
            "max_history_entries": ConfigField(
                type=int,
                default=100,
                description="最大历史记录条数",
            ),
            "initial_history_limit": ConfigField(
                type=int,
                default=30,
                description="从数据库加载的初始历史消息条数（启动时加载）",
            ),
        },
        "reply_checker": {
            "enabled": ConfigField(
                type=bool,
                default=True,
                description="是否启用回复检查器",
            ),
            "use_llm_check": ConfigField(
                type=bool,
                default=True,
                description="是否使用 LLM 进行深度检查（否则只做基本检查）",
            ),
            "similarity_threshold": ConfigField(
                type=float,
                default=0.9,
                description="相似度阈值（0-1），超过此值认为回复重复",
            ),
            "max_retries": ConfigField(
                type=int,
                default=3,
                description="回复检查失败时的最大重试次数",
            ),
        },
        "web_search": {
            "enabled": ConfigField(
                type=bool,
                default=True,
                description="是否启用联网搜索功能（需要 WEB_SEARCH_TOOL 插件）",
            ),
            "num_results": ConfigField(
                type=int,
                default=3,
                description="每次搜索返回的结果数量",
            ),
            "time_range": ConfigField(
                type=str,
                default="any",
                description="搜索时间范围：any（任意时间）、week（一周内）、month（一月内）",
            ),
            "answer_mode": ConfigField(
                type=bool,
                default=False,
                description="是否启用答案模式（仅 Exa 搜索引擎支持，返回更精简的答案）",
            ),
        },
    }

    async def on_plugin_loaded(self):
        """插件加载时"""
        # 将插件配置传递给 config 模块
        set_plugin_config(self.config)
        
        config = get_config()

        if not config.enabled:
            logger.info("[PFC] 插件已禁用")
            return

        # 确保数据库表已创建
        await self._ensure_database_tables()

        logger.info(
            f"[PFC] 插件已加载 "
            f"(配置版本: {self.config.get('inner', {}).get('version', 'unknown')})"
        )

    async def _ensure_database_tables(self):
        """确保 PFC 数据库表已创建"""
        try:
            # 导入 PFC 数据库模型（这会将它们注册到 Base.metadata）
            from .db_models import PFCChatHistory, PFCSession  # noqa: F401
            
            # 使用 MoFox 的数据库迁移功能创建表
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
        config = get_config()

        if not config.enabled:
            return []

        components = []

        try:
            # 注册 Chatter（延迟导入）
            ChatterClass = _get_chatter_class()
            components.append((
                ChatterClass.get_chatter_info(),
                ChatterClass,
            ))
            logger.debug("[PFC] 成功加载 PrefrontalCortexChatter 组件")
        except Exception as e:
            logger.error(f"[PFC] 加载 Chatter 组件失败: {e}")

        try:
            # 注册 PFC 专属 Reply 动作（延迟导入）
            ReplyActionClass = _get_reply_action_class()
            components.append((
                ReplyActionClass.get_action_info(),
                ReplyActionClass,
            ))
            logger.debug("[PFC] 成功加载 PFCReplyAction 组件")
        except Exception as e:
            logger.error(f"[PFC] 加载 Reply 动作失败: {e}")

        return components

    def get_plugin_info(self) -> dict[str, Any]:
        """获取插件信息"""
        return {
            "name": self.plugin_name,
            "display_name": "Prefrontal Cortex Chatter",
            "version": "1.0.0",
            "author": "MaiM-with-u",
            "description": "从 MaiM-with-u 0.6.3-fix4 移植的私聊系统",
            "features": [
                "目标驱动的对话管理",
                "多种行动类型",
                "回复质量检查",
                "主动思考能力",
            ],
        }