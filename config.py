"""
PFC - 配置

================================================================================
版权声明 (Copyright Notice)
================================================================================

原始代码来源: MaiM-with-u (https://github.com/MaiM-with-u/MaiBot)
原始版本: 0.6.3-fix4
原始许可证: GNU General Public License v3.0

本文件由 ASUSwei114 (https://github.com/ASUSwei114) 于 2024年12月 修改移植至 MoFox_Bot 项目。

本项目遵循 GNU General Public License v3.0 许可证。
详见 LICENSE 文件。

================================================================================

配置加载优先级：
1. 插件配置文件 (config/plugins/prefrontal_cortex_chatter/config.toml)
2. 全局配置文件中的 prefrontal_cortex_chatter 节（兼容旧版）
3. 默认值
"""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ReplyCheckerConfig:
    """回复检查器配置"""
    enabled: bool = True                  # 是否启用回复检查器
    use_llm_check: bool = True            # 是否使用 LLM 进行检查（否则只做基本检查）
    similarity_threshold: float = 0.9     # 相似度阈值（0-1）
    max_retries: int = 3                  # 最大重试次数


@dataclass
class WaitingConfig:
    """等待配置"""
    default_max_wait_seconds: int = 300  # 默认等待超时时间（秒）
    min_wait_seconds: int = 30           # 允许的最短等待时间
    max_wait_seconds: int = 1800         # 允许的最长等待时间（30分钟）


@dataclass
class SessionConfig:
    """会话配置"""
    session_dir: str = "prefrontal_cortex_chatter/sessions"
    session_expire_seconds: int = 86400 * 7  # 7 天
    max_history_entries: int = 100


@dataclass
class PFCConfig:
    """PFC 总配置"""
    enabled: bool = True
    enabled_stream_types: list[str] = field(default_factory=lambda: ["private"])
    waiting: WaitingConfig = field(default_factory=WaitingConfig)
    session: SessionConfig = field(default_factory=SessionConfig)
    reply_checker: ReplyCheckerConfig = field(default_factory=ReplyCheckerConfig)


# 全局配置单例
_config: PFCConfig | None = None
# 插件配置字典（由 plugin.py 设置）
_plugin_config: dict[str, Any] | None = None


def set_plugin_config(config_dict: dict[str, Any]) -> None:
    """设置插件配置（由 plugin.py 调用）"""
    global _plugin_config, _config
    _plugin_config = config_dict
    # 重置配置单例，强制重新加载
    _config = None


def get_config() -> PFCConfig:
    """获取全局配置"""
    global _config
    if _config is None:
        _config = load_config()
    return _config


def load_config() -> PFCConfig:
    """加载 PFC 配置
    
    优先从插件配置文件加载，如果没有则尝试从全局配置加载（兼容旧版）
    """
    config = PFCConfig()
    
    # 优先使用插件配置文件
    if _plugin_config:
        config = _load_from_plugin_config(_plugin_config)
    else:
        # 兼容旧版：从全局配置加载
        config = _load_from_global_config()
    
    return config


def _load_from_plugin_config(cfg: dict[str, Any]) -> PFCConfig:
    """从插件配置字典加载配置"""
    config = PFCConfig()
    
    try:
        # 基础配置
        if "plugin" in cfg:
            plugin_cfg = cfg["plugin"]
            config.enabled = plugin_cfg.get("enabled", True)
            if "enabled_stream_types" in plugin_cfg:
                config.enabled_stream_types = list(plugin_cfg["enabled_stream_types"])

        # 等待配置
        if "waiting" in cfg:
            wait_cfg = cfg["waiting"]
            config.waiting = WaitingConfig(
                default_max_wait_seconds=wait_cfg.get("default_max_wait_seconds", 300),
                min_wait_seconds=wait_cfg.get("min_wait_seconds", 30),
                max_wait_seconds=wait_cfg.get("max_wait_seconds", 1800),
            )

        # 会话配置
        if "session" in cfg:
            sess_cfg = cfg["session"]
            config.session = SessionConfig(
                session_dir=sess_cfg.get("session_dir", "prefrontal_cortex_chatter/sessions"),
                session_expire_seconds=sess_cfg.get("session_expire_seconds", 86400 * 7),
                max_history_entries=sess_cfg.get("max_history_entries", 100),
            )

        # 回复检查器配置
        if "reply_checker" in cfg:
            checker_cfg = cfg["reply_checker"]
            config.reply_checker = ReplyCheckerConfig(
                enabled=checker_cfg.get("enabled", True),
                use_llm_check=checker_cfg.get("use_llm_check", True),
                similarity_threshold=checker_cfg.get("similarity_threshold", 0.9),
                max_retries=checker_cfg.get("max_retries", 3),
            )

    except Exception as e:
        from src.common.logger import get_logger
        logger = get_logger("pfc_config")
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

            # 基础配置
            if hasattr(pfc_cfg, "plugin"):
                plugin_cfg = pfc_cfg.plugin
                if hasattr(plugin_cfg, "enabled"):
                    config.enabled = plugin_cfg.enabled
                if hasattr(plugin_cfg, "enabled_stream_types"):
                    config.enabled_stream_types = list(plugin_cfg.enabled_stream_types)

            # 等待配置
            if hasattr(pfc_cfg, "waiting"):
                wait_cfg = pfc_cfg.waiting
                config.waiting = WaitingConfig(
                    default_max_wait_seconds=getattr(wait_cfg, "default_max_wait_seconds", 300),
                    min_wait_seconds=getattr(wait_cfg, "min_wait_seconds", 30),
                    max_wait_seconds=getattr(wait_cfg, "max_wait_seconds", 1800),
                )

            # 会话配置
            if hasattr(pfc_cfg, "session"):
                sess_cfg = pfc_cfg.session
                config.session = SessionConfig(
                    session_dir=getattr(sess_cfg, "session_dir", "prefrontal_cortex_chatter/sessions"),
                    session_expire_seconds=getattr(sess_cfg, "session_expire_seconds", 86400 * 7),
                    max_history_entries=getattr(sess_cfg, "max_history_entries", 100),
                )

            # 回复检查器配置
            if hasattr(pfc_cfg, "reply_checker"):
                checker_cfg = pfc_cfg.reply_checker
                config.reply_checker = ReplyCheckerConfig(
                    enabled=getattr(checker_cfg, "enabled", True),
                    use_llm_check=getattr(checker_cfg, "use_llm_check", True),
                    similarity_threshold=getattr(checker_cfg, "similarity_threshold", 0.9),
                    max_retries=getattr(checker_cfg, "max_retries", 3),
                )

    except Exception as e:
        from src.common.logger import get_logger
        logger = get_logger("pfc_config")
        logger.warning(f"从全局配置加载失败，使用默认值: {e}")

    return config


def reload_config() -> PFCConfig:
    """重新加载配置"""
    global _config
    _config = load_config()
    return _config


def apply_wait_duration_rules(raw_wait_seconds: int) -> int:
    """根据配置计算最终的等待时间"""
    if raw_wait_seconds <= 0:
        return 0

    waiting_cfg = get_config().waiting

    min_wait = max(0, waiting_cfg.min_wait_seconds)
    max_wait = max(waiting_cfg.max_wait_seconds, 0)

    if max_wait > 0 and min_wait > 0 and max_wait < min_wait:
        max_wait = min_wait

    adjusted = raw_wait_seconds
    if max_wait > 0:
        adjusted = min(adjusted, max_wait)
    if min_wait > 0:
        adjusted = max(adjusted, min_wait)

    return max(adjusted, 0)