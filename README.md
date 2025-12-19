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
- 重构为独立插件模块，支持热插拔
- 使用 MoFox_Bot 的配置系统和日志系统

### 功能重构
- 重构消息处理和回复生成逻辑
- 重构会话管理器 (SessionManager)
- 重构对话循环 (ConversationLoop)

### 新增功能
- 添加 PFC 专属 Reply 动作
- 支持多行回复拆分发送

### Bug 修复
- 修复聊天历史构建问题
- 修复人格获取逻辑
- 修复对话循环结束后新消息无法触发新循环的问题
- 恢复原版 Prompt 模板的"简短20字以内"约束

### 可配置功能
- 添加可配置的回复检查器（支持启用/禁用 LLM 检查）
- 添加配置文件版本控制，支持自动更新配置结构

## ✨ 功能特性

- 🎯 **目标驱动对话** - 基于对话目标进行智能规划
- 🧠 **多种行动类型** - 支持回复、等待、倾听、获取知识等
- ✅ **回复质量检查** - 可配置的回复质量检查，支持 LLM 深度检查
- 📚 **知识获取** - 支持从外部获取知识辅助回复

## 📁 文件结构

```
prefrontal_cortex_chatter/
├── __init__.py          # 模块入口和导出
├── plugin.py            # 插件注册
├── chatter.py           # 聊天器主类
├── planner.py           # 行动规划器
├── replyer.py           # 回复生成器
├── goal_analyzer.py     # 目标分析器
├── waiter.py            # 等待器
├── knowledge_fetcher.py # 知识获取器
├── session.py           # 会话管理器
├── conversation_loop.py # 对话循环
├── models.py            # 数据模型
├── config.py            # 配置管理
├── utils.py             # 工具函数
├── manifest.toml        # 插件清单
├── LICENSE              # GPL-3.0 许可证
├── README.md            # 本文件
└── actions/
    ├── __init__.py
    └── reply.py         # PFC 专属回复动作
```

## ⚙️ 配置说明

配置文件位于 `config/plugins/prefrontal_cortex_chatter/config.toml`。

### 配置文件版本控制

插件使用 `inner.version` 字段进行配置文件版本控制。当插件更新导致配置结构变化时：
- MoFox 会自动检测版本差异
- 自动备份旧配置文件到 `backup/` 目录
- 自动补全新增的配置项
- 自动移除废弃的配置项
- 保留用户已修改的配置值

### 配置示例

```toml
# 配置元信息
[inner]
version = "1.0.0"  # 配置文件版本号，请勿手动修改

# 插件基础配置
[plugin]
enabled = true
enabled_stream_types = ["private"]

# 等待行为配置
[waiting]
default_max_wait_seconds = 300  # 默认等待超时时间(秒)
min_wait_seconds = 30           # 最短等待时间
max_wait_seconds = 1800         # 最长等待时间(30分钟)

# 会话管理配置
[session]
session_dir = "prefrontal_cortex_chatter/sessions"
session_expire_seconds = 604800  # 会话过期时间(7天)
max_history_entries = 100        # 最大历史记录条数

# 回复检查器配置
[reply_checker]
enabled = true              # 是否启用回复检查器
use_llm_check = true        # 是否使用 LLM 进行深度检查
similarity_threshold = 0.9  # 相似度阈值(0-1)，超过此值判定为重复
max_retries = 3             # 最大重试次数
```

### 回复检查器配置说明

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `enabled` | `true` | 是否启用回复检查器。设为 `false` 则跳过所有检查 |
| `use_llm_check` | `true` | 是否使用 LLM 进行深度检查。设为 `false` 只做基本检查（空回复、过长、相似度） |
| `similarity_threshold` | `0.9` | 相似度阈值，超过此值判定为与上一条回复重复 |
| `max_retries` | `3` | 回复生成的最大重试次数 |

## 📄 许可证

本项目继续遵循 **GNU General Public License v3.0** 许可证。

详见 [LICENSE](LICENSE) 文件。

## 🙏 致谢

感谢 [MaiM-with-u](https://github.com/MaiM-with-u/MaiBot) 团队开发的原版 PFC 系统。