# Prefrontal Cortex Chatter (PFC)

基于前额叶皮层概念的智能私聊系统，支持目标导向对话、多种行动类型、知识获取和联网搜索等功能。

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
- 支持双存储后端（文件/数据库）

### 功能重构
- 重构消息处理和回复生成逻辑
- 重构会话管理器 (SessionManager)，支持持久化存储
- 重构对话循环 (ConversationLoop)，保持与原版一致的循环行为
- 重构行动规划器 (ActionPlanner)，支持多种决策 Prompt

### 可配置功能
- 添加可配置的回复检查器（支持启用/禁用 LLM 检查）
- 添加可配置的联网搜索功能（需要 WEB_SEARCH_TOOL 插件）
- 添加配置文件版本控制，支持自动更新配置结构

## ✨ 功能特性

### 核心功能
- 🎯 **目标驱动对话** - 基于对话目标进行智能规划，自动设定和调整对话目标
- 🧠 **多种行动类型** - 支持回复、等待、倾听、获取知识、结束对话、屏蔽等多种行动
- ✅ **回复质量检查** - 可配置的回复质量检查，支持 LLM 深度检查和相似度检测
- 📚 **知识获取** - 支持从记忆系统和知识库中获取相关知识辅助回复
- 🌐 **联网搜索** - 支持联网搜索获取最新信息（需要 WEB_SEARCH_TOOL 插件）

### 行动类型说明

| 行动类型 | 说明 |
|---------|------|
| `direct_reply` | 直接回复对方消息 |
| `send_new_message` | 发送新消息继续对话（追问、补充、深入话题等） |
| `wait` | 暂时不说话，等待对方回复 |
| `listening` | 倾听对方发言，当对方话还没说完时使用 |
| `fetch_knowledge` | 调取知识或记忆，获取专业知识或特定信息 |
| `rethink_goal` | 重新思考对话目标 |
| `end_conversation` | 结束对话 |
| `say_goodbye` | 发送告别语后结束对话 |
| `block_and_ignore` | 屏蔽对方，忽略一段时间内的所有消息 |

## 📁 模块结构

```
prefrontal_cortex_chatter/
├── plugin.py           # 插件注册与配置定义
├── chatter.py          # Chatter 主类，处理消息入口
├── session.py          # 会话管理，持久化存储
├── conversation_loop.py # 对话循环，持续运行的后台任务
├── planner.py          # 行动规划器，决策下一步行动
├── replyer.py          # 回复生成器
├── reply_checker.py    # 回复质量检查器
├── knowledge_fetcher.py # 知识获取器
├── models.py           # 数据模型定义
├── utils.py            # 工具函数
├── db_models.py        # 数据库模型（可选）
├── db_storage.py       # 数据库存储后端（可选）
└── actions/            # 行动组件
    └── reply.py        # PFC 专属回复动作
```

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
block_ignore_seconds = 1800

# 是否启用 block_and_ignore 动作（屏蔽对方）。设为 false 可禁用此功能
enable_block_action = true


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
enabled = true

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

### 配置项说明

#### 插件基础配置 `[plugin]`

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `enabled` | bool | `true` | 是否启用 PFC 私聊聊天器 |

#### 等待行为配置 `[waiting]`

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `wait_timeout_seconds` | int | `300` | 等待超时时间（秒），超时后 AI 会重新思考下一步行动 |
| `block_ignore_seconds` | int | `1800` | 屏蔽忽略时间（秒），执行 block_and_ignore 动作后忽略对方消息的时长 |
| `enable_block_action` | bool | `true` | 是否启用 block_and_ignore 动作。设为 `false` 可禁用屏蔽功能 |

#### 会话管理配置 `[session]`

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `storage_backend` | str | `"file"` | 存储后端：`file`（JSON文件）或 `database`（数据库） |
| `session_dir` | str | `"prefrontal_cortex_chatter/sessions"` | 会话数据存储目录（相对于 data/） |
| `session_expire_seconds` | int | `604800` | 会话过期时间（秒，默认7天） |
| `max_history_entries` | int | `100` | 最大历史记录条数 |
| `initial_history_limit` | int | `30` | 从数据库加载的初始历史消息条数 |

#### 回复检查器配置 `[reply_checker]`

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `enabled` | bool | `true` | 是否启用回复检查器 |
| `use_llm_check` | bool | `true` | 是否使用 LLM 进行深度检查 |
| `similarity_threshold` | float | `0.9` | 相似度阈值（0-1），超过此值认为回复重复 |
| `max_retries` | int | `3` | 回复检查失败时的最大重试次数 |

#### 联网搜索配置 `[web_search]`

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `enabled` | bool | `true` | 是否启用联网搜索功能 |
| `num_results` | int | `3` | 每次搜索返回的结果数量 |
| `time_range` | str | `"any"` | 搜索时间范围：`any`/`week`/`month` |
| `answer_mode` | bool | `false` | 是否启用答案模式（仅 Exa 支持） |

## 🔄 工作流程

1. **消息接收** - Chatter 接收私聊消息，获取或创建会话
2. **历史加载** - 首次启动时从数据库加载历史消息
3. **消息记录** - 将新消息记录到会话中
4. **循环启动** - 启动或唤醒会话循环（后台持续运行）
5. **行动规划** - ActionPlanner 根据当前状态决定下一步行动
6. **行动执行** - 根据规划执行相应行动（回复、等待、获取知识等）
7. **状态更新** - 更新会话状态，保存到持久化存储
8. **循环继续** - 继续监听新消息或等待超时

## ⚠️ 注意事项

1. **与心流聊天器冲突**：使用本插件时，请确保已在 `config/bot_config.toml` 中关闭 `[kokoro_flow_chatter]`（心流聊天器）相关配置，否则私聊将不会由本插件接管。

2. **存储后端选择**：
   - `file` 后端：简单易用，数据以 JSON 文件存储，适合单机部署
   - `database` 后端：支持 SQLite/PostgreSQL，适合需要数据持久化或多实例部署的场景

3. **联网搜索依赖**：联网搜索功能需要 `WEB_SEARCH_TOOL` 插件支持，请确保该插件已正确安装和配置。

4. **LLM 模型要求**：PFC 使用 `planner` 模型进行行动规划，如果未配置则回退到 `normal` 模型。

## 📄 许可证

本项目继续遵循 **GNU General Public License v3.0** 许可证。

详见 [LICENSE](LICENSE) 文件。

## 🙏 致谢

感谢 [MaiM-with-u](https://github.com/MaiM-with-u/MaiBot) 团队开发的原版 PFC 系统。