"""
PFC目标分析器模块

================================================================================
版权声明 (Copyright Notice)
================================================================================

原始代码来源: MaiM-with-u (https://github.com/MaiM-with-u/MaiBot)
原始版本: 0.6.3-fix4
原始代码路径: src/plugins/PFC/pfc.py (GoalAnalyzer 类)
原始许可证: GNU General Public License v3.0

本文件由 ASUSwei114 (https://github.com/ASUSwei114) 于 2024年12月 修改移植至 MoFox_Bot 项目。

主要修改内容:
- 适配 MoFox_Bot 的 LLM API
- 重构人格信息获取逻辑
- 独立为单独模块
- 使用共享模块精简代码

本项目遵循 GNU General Public License v3.0 许可证。
详见 LICENSE 文件。

================================================================================

负责分析对话历史并设定/更新对话目标
"""

from typing import List, Tuple, Optional, Dict, Any
from src.common.logger import get_logger
from src.plugin_system.apis import llm_api
from src.config.config import global_config

from .models import ObservationInfo, ConversationInfo
from .shared import (
    PersonalityHelper,
    get_current_time_str,
    build_goals_string,
    extract_json_from_text,
    extract_json_array_from_text,
)

logger = get_logger("PFC-GoalAnalyzer")


# ============== Prompt 模板 ==============

PROMPT_ANALYZE_GOAL = """{persona_text}。现在你在参与一场QQ聊天，请分析以下聊天记录，并根据你的性格特征确定多个明确的对话目标。
这些目标应该反映出对话的不同方面和意图。

【当前时间】
{current_time_str}

{action_history_text}
当前对话目标：
{goals_str}

聊天记录：
{chat_history_text}

请分析当前对话并确定最适合的对话目标。你可以：
1. 保持现有目标不变
2. 修改现有目标
3. 添加新目标
4. 删除不再相关的目标
5. 如果你想结束对话，请设置一个目标，目标goal为"结束对话"，原因reasoning为你希望结束对话

请以JSON数组格式输出当前的所有对话目标，每个目标包含以下字段：
1. goal: 对话目标（简短的一句话）
2. reasoning: 对话原因，为什么设定这个目标（简要解释）

输出格式示例：
[
{{
    "goal": "回答用户关于Python编程的具体问题",
    "reasoning": "用户提出了关于Python的技术问题，需要专业且准确的解答"
}},
{{
    "goal": "回答用户关于python安装的具体问题",
    "reasoning": "用户提出了关于Python的技术问题，需要专业且准确的解答"
}}
]"""

PROMPT_ANALYZE_CONVERSATION = """{persona_text}。现在你在参与一场QQ聊天，

【当前时间】
{current_time_str}

当前对话目标：{goal}
产生该对话目标的原因：{reasoning}

请分析以下聊天记录，并根据你的性格特征评估该目标是否已经达到，或者你是否希望停止该次对话。
聊天记录：
{chat_history_text}
请以JSON格式输出，包含以下字段：
1. goal_achieved: 对话目标是否已经达到（true/false）
2. stop_conversation: 是否希望停止该次对话（true/false）
3. reason: 为什么希望停止该次对话（简要解释）   

输出格式示例：
{{
    "goal_achieved": true,
    "stop_conversation": false,
    "reason": "虽然目标已达成，但对话仍然有继续的价值"
}}"""


def _calculate_similarity(goal1: str, goal2: str) -> float:
    """计算两个目标之间的相似度（使用 SequenceMatcher，对中文更准确）"""
    if not goal1 or not goal2:
        return 0.0
    import difflib
    return difflib.SequenceMatcher(None, goal1, goal2).ratio()


class GoalAnalyzer:
    """
    对话目标分析器
    
    负责分析对话历史并设定/更新对话目标
    """
    
    def __init__(self, session):
        """
        初始化目标分析器
        
        Args:
            session: PFCSession 会话对象
        """
        from .plugin import get_config
        from .session import PFCSession
        
        self.session: PFCSession = session
        self.config = get_config()
        
        # 使用共享的人格信息助手
        self._personality_helper = PersonalityHelper("")
        
        # 获取机器人名称
        self.bot_name = self._personality_helper.bot_name
        
        # 多目标存储结构
        self.goals: List[Tuple[str, str, str]] = []  # (goal, method, reasoning)
        self.max_goals = 3  # 同时保持的最大目标数量
        self.current_goal_and_reason = None
        
        logger.debug("[PFC]目标分析器初始化完成")
    
    async def analyze_goal(self) -> Tuple[str, str, str]:
        """
        分析对话历史并设定目标
            
        Returns:
            (目标, 方法, 原因) 元组
        """
        conversation_info = self.session.conversation_info
        observation_info = self.session.observation_info
        
        logger.debug("[PFC]开始分析对话目标...")
        
        # 构建Prompt参数
        prompt_params = await self._build_prompt_params(
            conversation_info,
            observation_info
        )
        
        # 格式化Prompt
        prompt = PROMPT_ANALYZE_GOAL.format(**prompt_params)
        
        logger.debug(f"[PFC]发送到LLM的提示词: {prompt[:500]}...")
        
        try:
            models = llm_api.get_available_models()
            planner_config = models.get("planner") or models.get("normal")
            
            if not planner_config:
                logger.warning("[PFC] 未找到 planner 模型配置")
                return "", "", ""
            
            success, content, _, _ = await llm_api.generate_with_model(
                prompt=prompt,
                model_config=planner_config,
                request_type="pfc.goal_analysis",
            )
            
            if not success or not content:
                logger.warning(f"[PFC]LLM调用失败: {content}")
                return "", "", ""
            
            logger.debug(f"[PFC]LLM原始返回内容: {content}")
        except Exception as e:
            logger.error(f"[PFC]分析对话目标时出错: {e}")
            return "", "", ""
        
        # 解析JSON响应
        result = self._parse_goal_response(content, conversation_info)
        
        return result
    
    async def _build_prompt_params(
        self,
        conversation_info: ConversationInfo,
        observation_info: ObservationInfo
    ) -> Dict[str, str]:
        """
        构建Prompt参数（使用共享模块）
        
        Args:
            conversation_info: 对话信息
            observation_info: 观察信息
            
        Returns:
            Prompt参数字典
        """
        # 使用共享模块获取人格信息
        personality_info = await self._personality_helper.get_personality_info()
        
        # 使用共享模块构建对话目标字符串
        goals_str = build_goals_string(conversation_info.goal_list)
        
        # 获取聊天历史记录
        chat_history_text = await self._build_chat_history_text(observation_info)
        
        # 构建人设文本
        persona_text = f"{personality_info}"
        
        # 构建action历史文本
        action_history_text = self._build_action_history_text(
            conversation_info.done_action
        )
        
        # 使用共享模块获取当前时间字符串
        current_time_str = get_current_time_str()
        
        return {
            "persona_text": persona_text,
            "goals_str": goals_str,
            "chat_history_text": chat_history_text,
            "action_history_text": action_history_text,
            "current_time_str": current_time_str
        }
    
    async def _build_chat_history_text(
        self,
        observation_info: ObservationInfo
    ) -> str:
        """
        构建聊天历史文本
        
        Args:
            observation_info: 观察信息
            
        Returns:
            格式化的聊天历史文本
        """
        chat_history_text = observation_info.chat_history_str
        
        # 如果有新消息，添加新消息部分
        if (observation_info.new_messages_count > 0 and 
            observation_info.unprocessed_messages):
            
            new_messages_str = self._format_messages(
                observation_info.unprocessed_messages
            )
            chat_history_text += (
                f"\n--- 以下是 {observation_info.new_messages_count} "
                f"条新消息 ---\n{new_messages_str}"
            )
        
        return chat_history_text
    
    def _format_messages(self, messages: List[Dict[str, Any]]) -> str:
        """
        格式化消息列表为可读文本
        
        Args:
            messages: 消息列表
            
        Returns:
            格式化的消息文本
        """
        if not messages:
            return ""
        
        formatted_lines = []
        for msg in messages:
            sender = msg.get("sender", {})
            sender_name = sender.get("nickname", "未知用户")
            content = msg.get("processed_plain_text", msg.get("content", ""))
            
            # 替换机器人名称
            if sender.get("user_id") == str(global_config.bot.qq_account):
                sender_name = self.bot_name
            
            formatted_lines.append(f"{sender_name}: {content}")
        
        return "\n".join(formatted_lines)
    
    def _build_action_history_text(
        self,
        done_action: Optional[List[Dict[str, Any]]]
    ) -> str:
        """
        构建行动历史文本
        
        Args:
            done_action: 已完成的行动列表
            
        Returns:
            格式化的行动历史文本
        """
        if not done_action:
            return "你之前做的事情是：暂无\n"
        
        action_history_text = "你之前做的事情是：\n"
        for action in done_action:
            action_history_text += f"{action}\n"
        
        return action_history_text
    
    def _parse_goal_response(
        self,
        content: str,
        conversation_info: ConversationInfo
    ) -> Tuple[str, str, str]:
        """
        解析LLM返回的目标响应
        
        Args:
            content: LLM响应内容
            conversation_info: 对话信息（用于更新目标列表）
            
        Returns:
            (目标, 方法, 原因) 元组
        """
        # 尝试解析JSON数组
        result = extract_json_array_from_text(content)
        
        if result and isinstance(result, list):
            # 清空现有目标列表并添加新目标（限制最多 max_goals 个）
            conversation_info.goal_list = []
            
            for item in result[:self.max_goals]:
                if isinstance(item, dict):
                    goal = item.get("goal", "")
                    reasoning = item.get("reasoning", "")
                    
                    if goal:
                        conversation_info.goal_list.append({
                            "goal": goal,
                            "reasoning": reasoning
                        })
            
            # 返回第一个目标作为当前主要目标
            if conversation_info.goal_list:
                first_goal = conversation_info.goal_list[0]
                return (
                    first_goal.get("goal", ""),
                    "",
                    first_goal.get("reasoning", "")
                )
        
        # 尝试解析单个JSON对象
        result = extract_json_from_text(content)
        
        if result and isinstance(result, dict):
            goal = result.get("goal", "")
            reasoning = result.get("reasoning", "")
            
            if goal:
                conversation_info.goal_list.append({
                    "goal": goal,
                    "reasoning": reasoning
                })
                return goal, "", reasoning
        
        logger.warning(
            f"[PFC]无法解析目标响应: {content[:100]}..."
        )
        return "", "", ""
    
    async def analyze_conversation(
        self,
        goal: str,
        reasoning: str,
        chat_history_text: str
    ) -> Tuple[bool, bool, str]:
        """
        分析对话状态，判断目标是否达成
        
        Args:
            goal: 当前目标
            reasoning: 目标原因
            chat_history_text: 聊天历史文本
            
        Returns:
            (goal_achieved, stop_conversation, reason) 元组
        """
        # 使用共享模块获取人格信息
        personality_info = await self._personality_helper.get_personality_info()
        persona_text = f"你的名字是{self.bot_name}，{personality_info}。"
        current_time_str = get_current_time_str()
        
        prompt = PROMPT_ANALYZE_CONVERSATION.format(
            persona_text=persona_text,
            goal=goal,
            reasoning=reasoning,
            chat_history_text=chat_history_text,
            current_time_str=current_time_str
        )
        
        try:
            models = llm_api.get_available_models()
            planner_config = models.get("planner") or models.get("normal")
            
            if not planner_config:
                logger.warning("[PFC] 未找到 planner 模型配置")
                return False, False, "未找到模型配置"
            
            success, content, _, _ = await llm_api.generate_with_model(
                prompt=prompt,
                model_config=planner_config,
                request_type="pfc.conversation_analysis",
            )
            
            if not success or not content:
                logger.warning(f"[PFC]LLM调用失败: {content}")
                return False, False, "LLM调用失败"
            
            logger.debug(f"[PFC]LLM原始返回内容: {content}")
            
            # 解析JSON响应
            result = extract_json_from_text(content)
            
            if result and isinstance(result, dict):
                goal_achieved = result.get("goal_achieved", False)
                stop_conversation = result.get("stop_conversation", False)
                reason = result.get("reason", "")
                
                # 确保类型正确
                if isinstance(goal_achieved, str):
                    goal_achieved = goal_achieved.lower() == "true"
                if isinstance(stop_conversation, str):
                    stop_conversation = stop_conversation.lower() == "true"
                
                return goal_achieved, stop_conversation, reason
            
            logger.error(
                f"[PFC]无法解析对话分析结果JSON"
            )
            return False, False, "解析结果失败"
            
        except Exception as e:
            logger.error(
                f"[PFC]分析对话状态时出错: {e}"
            )
            return False, False, f"分析出错: {e}"
    
    async def _update_goals(
        self,
        new_goal: str,
        method: str,
        reasoning: str
    ):
        """
        更新目标列表
        
        Args:
            new_goal: 新的目标
            method: 实现目标的方法
            reasoning: 目标的原因
        """
        # 检查新目标是否与现有目标相似
        for i, (existing_goal, _, _) in enumerate(self.goals):
            if _calculate_similarity(new_goal, existing_goal) > 0.7:
                # 更新现有目标
                self.goals[i] = (new_goal, method, reasoning)
                # 将此目标移到列表前面（最主要的位置）
                self.goals.insert(0, self.goals.pop(i))
                return
        
        # 添加新目标到列表前面
        self.goals.insert(0, (new_goal, method, reasoning))
        
        # 限制目标数量
        if len(self.goals) > self.max_goals:
            self.goals.pop()  # 移除最老的目标
    
    async def get_all_goals(self) -> List[Tuple[str, str, str]]:
        """
        获取所有当前目标
        
        Returns:
            目标列表，每项为(目标, 方法, 原因)
        """
        return self.goals.copy()
    
    async def get_alternative_goals(self) -> List[Tuple[str, str, str]]:
        """
        获取除了当前主要目标外的其他备选目标
        
        Returns:
            备选目标列表
        """
        if len(self.goals) <= 1:
            return []
        return self.goals[1:].copy()
    
    def has_end_goal(self, conversation_info: ConversationInfo) -> bool:
        """
        检查是否有结束对话的目标
        
        Args:
            conversation_info: 对话信息
            
        Returns:
            是否有结束对话的目标
        """
        if not conversation_info.goal_list:
            return False
        
        for goal_item in conversation_info.goal_list:
            if isinstance(goal_item, dict):
                goal = goal_item.get("goal", "")
                if goal == "结束对话":
                    return True
        
        return False