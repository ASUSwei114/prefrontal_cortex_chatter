"""
PFC Reply Action - PFC专属回复动作

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
    """
    PFC专属回复动作
    
    处理PFC聊天器生成的回复，支持：
    - 直接回复 (direct_reply)
    - 发送新消息 (send_new_message)
    - 告别消息 (say_goodbye)
    """
    
    # Action 基本信息
    action_name: str = "pfc_reply"
    action_description: str = "PFC私聊回复动作"
    
    # 激活配置
    focus_activation_type: ClassVar = ActionActivationType.NEVER
    normal_activation_type: ClassVar = ActionActivationType.NEVER
    
    # 模式配置
    mode_enable: ClassVar = ChatMode.ALL
    chat_type_allow: ClassVar = ChatType.PRIVATE  # 仅私聊
    parallel_action: bool = False
    
    # 关联的Chatter
    chatter_allow: ClassVar[list[str]] = ["prefrontal_cortex"]
    
    # Action 参数
    action_parameters: ClassVar[dict] = {
        "content": "回复内容",
        "action_type": "动作类型 (direct_reply/send_new_message/say_goodbye)",
    }
    
    action_require: ClassVar[list[str]] = [
        "由PFC聊天器触发",
        "私聊场景",
    ]
    
    async def execute(self) -> tuple[bool, str]:
        """执行回复动作"""
        try:
            # 获取回复内容
            content = self.action_data.get("content", "")
            action_type = self.action_data.get("action_type", "direct_reply")
            
            if not content:
                logger.warning(f"{self.log_prefix} 回复内容为空")
                return False, "回复内容为空"
            
            logger.info(
                f"{self.log_prefix} 执行PFC回复: "
                f"类型={action_type}, 内容={content[:50]}..."
            )
            
            # 发送消息
            success = await self.send_text(
                content=content,
                typing=True
            )
            
            if success:
                # 存储动作信息
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
        """
        激活判断
        
        PFC Reply Action 不通过常规激活机制触发，
        而是由PFC Chatter直接调用
        """
        # 检查是否由PFC Chatter触发
        triggered_by = self.action_data.get("triggered_by", "")
        if triggered_by == "pfc_chatter":
            return True
        
        return False