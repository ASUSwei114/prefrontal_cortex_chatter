"""
PFC Reply Action - PFC专属回复动作

================================================================================
版权声明 (Copyright Notice)
================================================================================

原始代码来源: MaiM-with-u (https://github.com/MaiM-with-u/MaiBot)
原始版本: 0.6.3-fix4
原始许可证: GNU General Public License v3.0

本文件由 ASUSwei114 (https://github.com/ASUSwei114) 于 2024年12月 修改移植至 MoFox_Bot 项目。

主要修改内容:
- 适配 MoFox_Bot 的 Action 系统

本项目遵循 GNU General Public License v3.0 许可证。
详见 LICENSE 文件。

================================================================================

用于处理PFC聊天器的回复行为
"""

from typing import ClassVar

from src.common.logger import get_logger
from src.plugin_system.base.base_action import BaseAction
from src.plugin_system.base.component_types import (
    ActionActivationType,
    ChatMode,
    ChatType,
)

logger = get_logger("PFC-ReplyAction")


class PFCReplyAction(BaseAction):
    """PFC专属回复动作"""
    
    action_name: str = "pfc_reply"
    action_description: str = "PFC私聊回复动作"
    focus_activation_type: ClassVar = ActionActivationType.NEVER
    normal_activation_type: ClassVar = ActionActivationType.NEVER
    mode_enable: ClassVar = ChatMode.ALL
    chat_type_allow: ClassVar = ChatType.PRIVATE
    parallel_action: bool = False
    chatter_allow: ClassVar[list[str]] = ["prefrontal_cortex"]
    action_parameters: ClassVar[dict] = {
        "content": "回复内容",
        "action_type": "动作类型 (direct_reply/send_new_message/say_goodbye)",
    }
    action_require: ClassVar[list[str]] = ["由PFC聊天器触发", "私聊场景"]
    
    async def execute(self) -> tuple[bool, str]:
        """执行回复动作"""
        try:
            content = self.action_data.get("content", "")
            if not content:
                logger.warning(f"{self.log_prefix} 回复内容为空")
                return False, "回复内容为空"
            
            action_type = self.action_data.get("action_type", "direct_reply")
            logger.info(f"{self.log_prefix} 执行PFC回复: {action_type}, {content[:50]}...")
            
            success = await self.send_text(content=content, typing=True)
            
            if success:
                await self.store_action_info(
                    action_build_into_prompt=True,
                    action_prompt_display=f"[PFC回复] {content[:100]}",
                    action_done=True
                )
                logger.info(f"{self.log_prefix} PFC回复发送成功")
                return True, content
            else:
                logger.error(f"{self.log_prefix} PFC回复发送失败")
                return False, "发送失败"
                
        except Exception as e:
            logger.error(f"{self.log_prefix} 执行PFC回复时出错: {e}")
            return False, f"执行出错: {e}"
    
    async def go_activate(self, llm_judge_model=None) -> bool:
        """激活判断 - PFC Reply Action 由 PFC Chatter 直接调用"""
        return self.action_data.get("triggered_by", "") == "pfc_chatter"