"""
Prefrontal Cortex Chatter - 插件注册

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

from typing import Any, ClassVar

from src.common.logger import get_logger
from src.plugin_system import register_plugin
from src.plugin_system.base.base_plugin import BasePlugin
from src.plugin_system.base.config_types import ConfigField

from .chatter import PrefrontalCortexChatter
from .config import get_config, set_plugin_config

logger = get_logger("pfc_plugin")

# 配置文件版本号 - 更新配置结构时递增此版本
CONFIG_VERSION = "1.0.1"


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
            "enabled_stream_types": ConfigField(
                type=list,
                default=["private"],
                description="启用的消息源类型",
                example='["private"]',
            ),
        },
        "waiting": {
            "default_max_wait_seconds": ConfigField(
                type=int,
                default=300,
                description="默认等待超时时间（秒）",
            ),
            "min_wait_seconds": ConfigField(
                type=int,
                default=30,
                description="允许的最短等待时间（秒）",
            ),
            "max_wait_seconds": ConfigField(
                type=int,
                default=1800,
                description="允许的最长等待时间（秒，30分钟）",
            ),
        },
        "session": {
            "storage_backend": ConfigField(
                type=str,
                default="file",
                description="存储后端：file（JSON文件）或 database（使用 MoFox 数据库，支持 SQLite/PostgreSQL）",
            ),
            "session_dir": ConfigField(
                type=str,
                default="prefrontal_cortex_chatter/sessions",
                description="会话数据存储目录（相对于 data/，仅 file 后端使用）",
            ),
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

        # 如果使用数据库后端，确保表已创建
        if config.session.storage_backend == "database":
            await self._ensure_database_tables()

        logger.info(
            f"[PFC] 插件已加载 "
            f"(配置版本: {self.config.get('inner', {}).get('version', 'unknown')}, "
            f"存储后端: {config.session.storage_backend})"
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
            logger.warning("[PFC] 将回退到文件存储后端")
            # 回退到文件存储
            from .config import get_config
            config = get_config()
            config.session.storage_backend = "file"

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
            # 注册 Chatter
            components.append((
                PrefrontalCortexChatter.get_chatter_info(),
                PrefrontalCortexChatter,
            ))
            logger.debug("[PFC] 成功加载 PrefrontalCortexChatter 组件")
        except Exception as e:
            logger.error(f"[PFC] 加载 Chatter 组件失败: {e}")

        try:
            # 注册 PFC 专属 Reply 动作
            from .actions.reply import PFCReplyAction

            components.append((
                PFCReplyAction.get_action_info(),
                PFCReplyAction,
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