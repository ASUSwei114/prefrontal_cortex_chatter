"""
Prefrontal Cortex Chatter - 插件注册

从 MaiM-with-u 0.6.3-fix4 移植的 PFC 私聊系统
"""

from typing import Any, ClassVar

from src.common.logger import get_logger
from src.plugin_system import register_plugin
from src.plugin_system.base.base_plugin import BasePlugin

from .chatter import PrefrontalCortexChatter
from .config import get_config

logger = get_logger("pfc_plugin")


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

    async def on_plugin_loaded(self):
        """插件加载时"""
        config = get_config()

        if not config.enabled:
            logger.info("[PFC] 插件已禁用")
            return

        logger.info("[PFC] 插件已加载")

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