


# Prefrontal Cortex Chatter (PFC)

基于前额叶皮层概念的智能私聊系统，支持目标导向对话、知识获取等功能。

## 📋 版权声明

本插件移植自 **MaiM-with-u** 项目的 PFC 私聊系统。

| 项目 | 信息 |
|------|------|
| **原始项目** | [MaiM-with-u/MaiBot](https://github.com/MaiM-with-u/MaiBot/releases/tag/0.6.3-fix4-alpha) |
| **原始版本** | 0.6.3-fix4 |
| **原始代码路径** | `src/plugins/PFC/` |
| **原始许可证** | GNU General Public License v3.0 |
| **移植日期** | 2024年12月 |
| **移植者** | [ASUSwei114](https://github.com/ASUSwei114) |

## 🔧 主要修改内容

相比原版 PFC，本移植版本进行了以下修改：

### 架构适配
- 适配 MoFox_Bot 的插件系统架构
- 使用 MoFox_Bot 的配置系统和日志系统

### 功能重构
- 重构消息处理和回复生成逻辑
- 重构会话管理器 (SessionManager)
- 重构对话循环 (ConversationLoop)

### 可配置功能
- 添加可配置的回复检查器（支持启用/禁用 LLM 检查）
- 添加配置文件版本控制，支持自动更新配置结构

## ✨ 功能特性

- 🎯 **目标驱动对话** - 基于对话目标进行智能规划
- 🧠 **多种行动类型** - 支持回复、等待、倾听、获取知识等
- ✅ **回复质量检查** - 可配置的回复质量检查，支持 LLM 深度检查
- 📚 **知识获取** - 支持从外部获取知识辅助回复

## ⚙️ 配置说明

配置文件位于 `config/plugins/prefrontal_cortex_chatter/config.toml`。

### 配置示例

```toml
# 配置元信息
[inner]

# 配置文件版本号（用于配置文件升级与兼容性检查）
version = "1.3.0"


# 插件基础配置
[plugin]

# 是否启用 PFC 私聊聊天器
enabled = true


# 等待行为配置
[waiting]

# 等待超时时间（秒），超时后AI会重新思考下一步行动
wait_timeout_seconds = 300

# 屏蔽忽略时间（秒，默认30分钟）- 执行 block_and_ignore 动作后忽略对方消息的时长
#说人话就是bot使用黑名单后的屏蔽时间
block_ignore_seconds = 1800


# 会话管理配置
[session]

# 存储后端：file（JSON文件）或 database（使用 MoFox 数据库，支持 SQLite/PostgreSQL）
storage_backend = "file"

# 会话数据存储目录（相对于 data/，仅 file 后端使用）
session_dir = "prefrontal_cortex_chatter/sessions"

# 会话过期时间（秒，默认7天）
session_expire_seconds = 604800

# 最大历史记录条数
max_history_entries = 100

# 从数据库加载的初始历史消息条数（启动时加载）
initial_history_limit = 30


# 回复检查器配置
[reply_checker]

# 是否启用回复检查器
enabled = false

# 是否使用 LLM 进行深度检查（否则只做基本检查）
use_llm_check = true

# 相似度阈值（0-1），超过此值认为回复重复
similarity_threshold = 0.9

# 回复检查失败时的最大重试次数
max_retries = 3


# 联网搜索配置
[web_search]

# 是否启用联网搜索功能（需要 WEB_SEARCH_TOOL 插件）
enabled = true

# 每次搜索返回的结果数量
num_results = 3

# 搜索时间范围：any（任意时间）、week（一周内）、month（一月内）
time_range = "any"

# 是否启用答案模式（仅 Exa 搜索引擎支持，返回更精简的答案）
answer_mode = false



```

### 回复检查器配置说明

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `enabled` | `true` | 是否启用回复检查器。设为 `false` 则跳过所有检查 |
| `use_llm_check` | `true` | 是否使用 LLM 进行深度检查。设为 `false` 只做基本检查（空回复、过长、相似度） |
| `similarity_threshold` | `0.9` | 相似度阈值，超过此值判定为与上一条回复重复 |
| `max_retries` | `3` | 回复生成的最大重试次数 |

## ⚠️ 注意事项
使用本插件时，请确保已在 `config/bot_config.toml` 中关闭 `[kokoro_flow_chatter]`（心流聊天器）相关配置，否则私聊将不会由本插件接管，可能导致冲突或功能异常。**

## 📄 许可证

本项目继续遵循 **GNU General Public License v3.0** 许可证。

详见 [LICENSE](LICENSE) 文件。

## 🙏 致谢

感谢 [MaiM-with-u](https://github.com/MaiM-with-u/MaiBot) 团队开发的原版 PFC 系统。