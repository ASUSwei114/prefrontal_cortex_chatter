"""
PFC 会话循环管理器

================================================================================
版权声明 (Copyright Notice)
================================================================================

原始代码来源: MaiM-with-u (https://github.com/MaiM-with-u/MaiBot)
原始版本: 0.6.3-fix4
原始代码路径: src/plugins/PFC/
原始许可证: GNU General Public License v3.0

本文件由 ASUSwei114 (https://github.com/ASUSwei114) 于 2024年12月 修改移植至 MoFox_Bot 项目。

主要修改内容:
- 重构为独立的会话循环管理器
- 添加循环生命周期管理
- 支持多行回复拆分发送
- 修复循环结束后新消息无法触发新循环的问题

本项目遵循 GNU General Public License v3.0 许可证。
详见 LICENSE 文件。

================================================================================

复刻原版PFC的持续循环行为：
- 为每个活跃会话维护一个独立的后台循环
- 循环中持续规划和执行行动
- 支持新消息检测和重新规划
"""

import asyncio
import datetime
import time
from typing import Dict, Optional

from src.common.logger import get_logger

from .models import ConversationState
from .session import PFCSession

logger = get_logger("pfc_loop")


class ConversationLoop:
    """
    单个会话的持续循环
    
    复刻原版PFC的 _plan_and_action_loop
    """
    
    def __init__(self, session: PFCSession, user_name: str):
        self.session = session
        self.user_name = user_name
        # 延迟导入配置以避免循环导入
        from .plugin import get_config
        self.config = get_config()
        
        self._task: Optional[asyncio.Task] = None
        self._running = False
        
    async def start(self):
        """启动循环"""
        if self._running:
            return
        
        self._running = True
        self._task = asyncio.create_task(self._loop())
        logger.info(f"[PFC][{self.user_name}] 会话循环已启动")
    
    async def stop(self):
        """停止循环"""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info(f"[PFC][{self.user_name}] 会话循环已停止")
    
    async def _loop(self):
        """
        PFC核心循环 - 复刻原版 _plan_and_action_loop
        """
        logger.debug(f"[PFC][{self.user_name}] 循环开始: _running={self._running}, should_continue={self.session.should_continue}")
        
        while self._running and self.session.should_continue:
            # 忽略逻辑
            if self.session.ignore_until_timestamp and time.time() < self.session.ignore_until_timestamp:
                await asyncio.sleep(30)
                continue
            elif self.session.ignore_until_timestamp and time.time() >= self.session.ignore_until_timestamp:
                logger.info(f"[PFC][{self.user_name}] 忽略时间已到，准备结束对话")
                self.session.ignore_until_timestamp = None
                self.session.should_continue = False
                continue
            
            try:
                # 记录规划前的新消息数量
                initial_new_message_count = self.session.observation_info.new_messages_count + 1
                
                # 调用 ActionPlanner
                from .planner import ActionPlanner
                planner = ActionPlanner(self.session, self.user_name)
                action, reason = await planner.plan()
                
                # 规划后检查是否有更多新消息
                current_new_message_count = self.session.observation_info.new_messages_count
                
                if current_new_message_count > initial_new_message_count + 2:
                    logger.info(
                        f"[PFC][{self.user_name}] 规划期间发现新增消息 "
                        f"({initial_new_message_count} -> {current_new_message_count})，跳过本次行动，重新规划"
                    )
                    self.session.conversation_info.last_successful_reply_action = None
                    await asyncio.sleep(0.1)
                    continue
                
                # 清理未处理消息（如果要回复）
                if initial_new_message_count > 0 and action in ["direct_reply", "send_new_message"]:
                    logger.debug(
                        f"[PFC][{self.user_name}] 准备执行 {action}，清理 {initial_new_message_count} 条规划时已知的新消息"
                    )
                    await self.session.clear_unprocessed_messages()
                    self.session.observation_info.new_messages_count = 0
                
                # 执行行动
                await self._handle_action(action, reason)
                
                # 检查是否需要结束对话
                goal_ended = False
                if self.session.conversation_info.goal_list:
                    for goal_item in self.session.conversation_info.goal_list:
                        if isinstance(goal_item, dict):
                            current_goal = goal_item.get("goal")
                            if current_goal == "结束对话":
                                goal_ended = True
                                break
                
                if goal_ended:
                    self.session.should_continue = False
                    logger.info(f"[PFC][{self.user_name}] 检测到'结束对话'目标，停止循环")
                
            except Exception as loop_err:
                logger.error(f"[PFC][{self.user_name}] PFC主循环出错: {loop_err}")
                import traceback
                traceback.print_exc()
                await asyncio.sleep(1)
            
            if self.session.should_continue:
                await asyncio.sleep(0.1)
        
        # 循环结束时，标记为不再运行
        self._running = False
        logger.info(f"[PFC][{self.user_name}] PFC循环结束")
    
    def _check_new_messages_after_planning(self) -> bool:
        """检查在规划后是否有新消息"""
        if self.session.observation_info.new_messages_count > 2:
            logger.info(
                f"[PFC][{self.user_name}] 生成/执行动作期间收到 "
                f"{self.session.observation_info.new_messages_count} 条新消息，取消当前动作并重新规划"
            )
            self.session.conversation_info.last_successful_reply_action = None
            return True
        return False
    
    async def _handle_action(self, action: str, reason: str):
        """处理规划的行动"""
        logger.debug(f"[PFC][{self.user_name}] 执行行动: {action}, 原因: {reason}")
        
        # 记录action历史
        current_action_record = {
            "action": action,
            "plan_reason": reason,
            "status": "start",
            "time": datetime.datetime.now().strftime("%H:%M:%S"),
            "final_reason": None,
        }
        self.session.conversation_info.done_action.append(current_action_record)
        action_index = len(self.session.conversation_info.done_action) - 1
        
        action_successful = False
        
        if action == "direct_reply":
            action_successful = await self._handle_reply_action("direct_reply", action_index)
        
        elif action == "send_new_message":
            action_successful = await self._handle_reply_action("send_new_message", action_index)
        
        elif action == "fetch_knowledge":
            action_successful = await self._handle_fetch_knowledge(reason, action_index)
        
        elif action == "rethink_goal":
            action_successful = await self._handle_rethink_goal(action_index)
        
        elif action == "listening":
            action_successful = await self._handle_listening(action_index)
        
        elif action == "wait":
            action_successful = await self._handle_wait(action_index)
        
        elif action == "say_goodbye":
            action_successful = await self._handle_say_goodbye(action_index)
        
        elif action == "end_conversation":
            action_successful = await self._handle_end_conversation(action_index)
        
        elif action == "block_and_ignore":
            action_successful = await self._handle_block_and_ignore(action_index)
        
        # 更新行动状态
        if action_successful:
            self.session.conversation_info.done_action[action_index].update({
                "status": "done",
                "time": datetime.datetime.now().strftime("%H:%M:%S"),
            })
            # 重置状态: 对于非回复类动作的成功，清除上次回复状态
            # 这样下次规划时会使用 PROMPT_INITIAL_REPLY 而不是 PROMPT_FOLLOW_UP
            if action not in ["direct_reply", "send_new_message"]:
                self.session.conversation_info.last_successful_reply_action = None
                logger.debug(f"[PFC][{self.user_name}] 动作 {action} 成功完成，重置 last_successful_reply_action")
    
    async def _handle_reply_action(self, action_type: str, action_index: int) -> bool:
        """处理回复类行动（direct_reply 或 send_new_message）"""
        from .replyer import ReplyGenerator, ReplyChecker
        
        # 从配置获取最大重试次数
        max_reply_attempts = self.config.reply_checker.max_retries
        reply_attempt_count = 0
        is_suitable = False
        need_replan = False
        check_reason = "未进行尝试"
        final_reply_to_send = ""
        
        replyer = ReplyGenerator(self.session, self.user_name)
        checker = ReplyChecker(
            self.session.stream_id,
            self.user_name,
            self.config
        )
        
        while reply_attempt_count < max_reply_attempts and not is_suitable:
            reply_attempt_count += 1
            logger.info(
                f"[PFC][{self.user_name}] 尝试生成回复 (第 {reply_attempt_count}/{max_reply_attempts} 次)..."
            )
            self.session.state = ConversationState.GENERATING
            
            # 1. 生成回复
            reply_content = await replyer.generate(action_type=action_type)
            logger.info(
                f"[PFC][{self.user_name}] 第 {reply_attempt_count} 次生成的回复: "
                f"{reply_content[:50] if reply_content else '空'}..."
            )
            
            if not reply_content:
                check_reason = f"第 {reply_attempt_count} 次生成回复为空"
                continue
            
            # 2. 检查回复（使用独立的 ReplyChecker）
            self.session.state = ConversationState.CHECKING
            try:
                current_goal_str = (
                    self.session.conversation_info.goal_list[0].get("goal", "")
                    if self.session.conversation_info.goal_list else ""
                )
                
                # 使用 ReplyChecker 进行检查
                is_suitable, check_reason, need_replan = await checker.check(
                    reply=reply_content,
                    goal=current_goal_str,
                    chat_history=self.session.observation_info.chat_history,
                    chat_history_str=self.session.observation_info.chat_history_str,
                    retry_count=reply_attempt_count - 1,
                )
                logger.info(
                    f"[PFC][{self.user_name}] 第 {reply_attempt_count} 次检查结果: "
                    f"合适={is_suitable}, 原因='{check_reason}', 需重新规划={need_replan}"
                )
                if is_suitable:
                    final_reply_to_send = reply_content
                    break
                elif need_replan:
                    logger.warning(
                        f"[PFC][{self.user_name}] 第 {reply_attempt_count} 次检查建议重新规划，停止尝试"
                    )
                    break
            except Exception as check_err:
                logger.error(
                    f"[PFC][{self.user_name}] 第 {reply_attempt_count} 次检查出错: {check_err}"
                )
                check_reason = f"第 {reply_attempt_count} 次检查过程出错: {check_err}"
                break
        
        # 处理最终结果
        if is_suitable:
            # 检查是否有新消息
            if self._check_new_messages_after_planning():
                logger.info(f"[PFC][{self.user_name}] 生成回复期间收到新消息，取消发送，重新规划")
                self.session.conversation_info.done_action[action_index].update({
                    "status": "recall",
                    "final_reason": f"有新消息，取消发送: {final_reply_to_send[:30]}..."
                })
                return False
            
            # 发送回复
            self.session.generated_reply = final_reply_to_send
            await self._send_reply()
            
            # 更新状态
            self.session.conversation_info.last_successful_reply_action = action_type
            self.session.conversation_info.done_action[action_index].update({
                "status": "done",
                "final_reason": f"成功发送: {final_reply_to_send[:30]}..."
            })
            return True
        
        elif need_replan:
            logger.warning(
                f"[PFC][{self.user_name}] 经过 {reply_attempt_count} 次尝试，决定打回动作决策"
            )
            self.session.conversation_info.done_action[action_index].update({
                "status": "recall",
                "final_reason": f"尝试{reply_attempt_count}次后打回: {check_reason}"
            })
            self.session.conversation_info.last_successful_reply_action = None
            return False
        
        else:
            logger.warning(
                f"[PFC][{self.user_name}] 经过 {reply_attempt_count} 次尝试，未能生成合适回复"
            )
            self.session.conversation_info.done_action[action_index].update({
                "status": "recall",
                "final_reason": f"尝试{reply_attempt_count}次后失败: {check_reason}"
            })
            self.session.conversation_info.last_successful_reply_action = None
            
            # 执行等待
            logger.info(f"[PFC][{self.user_name}] 由于无法生成合适回复，执行 'wait' 操作...")
            self.session.state = ConversationState.WAITING
            await self._do_wait()
            
            wait_action_record = {
                "action": "wait",
                "plan_reason": f"因 {action_type} 多次尝试失败而执行的后备等待",
                "status": "done",
                "time": datetime.datetime.now().strftime("%H:%M:%S"),
                "final_reason": None,
            }
            self.session.conversation_info.done_action.append(wait_action_record)
            return False
    
    async def _send_reply(self):
        """发送回复（支持多行拆分发送）"""
        from src.plugin_system.apis import send_api
        
        reply_content = self.session.generated_reply
        if not reply_content:
            return
        
        try:
            # 将多行回复拆分成多条消息
            lines = [line.strip() for line in reply_content.split('\n') if line.strip()]
            
            if not lines:
                return
            
            for i, line in enumerate(lines):
                # 发送消息
                await send_api.text_to_stream(
                    text=line,
                    stream_id=self.session.stream_id,
                )
                
                # 记录到历史
                self.session.add_bot_message(line)
                
                # 多条消息之间稍微间隔，模拟真人打字
                if i < len(lines) - 1:
                    await asyncio.sleep(0.5)
            
            logger.info(f"[PFC][{self.user_name}] 成功发送 {len(lines)} 条回复")
            
        except Exception as e:
            logger.error(f"[PFC][{self.user_name}] 发送回复失败: {e}")
    
    async def _handle_fetch_knowledge(self, query: str, action_index: int) -> bool:
        """
        处理获取知识
        
        调用 KnowledgeFetcher 从记忆系统和知识库中获取相关知识，
        并将结果存储到 conversation_info.knowledge_list 中。
        """
        self.session.state = ConversationState.FETCHING
        
        try:
            from .knowledge_fetcher import KnowledgeFetcher
            
            logger.info(f"[PFC][{self.user_name}] 开始获取知识: {query[:100]}...")
            
            # 创建知识获取器
            fetcher = KnowledgeFetcher(self.user_name, self.config)
            
            # 获取知识
            knowledge_text, sources_text = await fetcher.fetch(
                query=query,
                chat_history=self.session.observation_info.chat_history
            )
            
            # 将获取的知识添加到 knowledge_list
            if knowledge_text and knowledge_text != "未找到相关知识":
                knowledge_item = {
                    "query": query[:200],  # 截断过长的查询
                    "knowledge": knowledge_text,
                    "source": sources_text,
                    "time": time.time(),
                }
                
                # 初始化 knowledge_list（如果不存在）
                if not hasattr(self.session.conversation_info, 'knowledge_list') or \
                   self.session.conversation_info.knowledge_list is None:
                    self.session.conversation_info.knowledge_list = []
                
                self.session.conversation_info.knowledge_list.append(knowledge_item)
                
                # 限制知识列表长度（最多保留10条）
                if len(self.session.conversation_info.knowledge_list) > 10:
                    self.session.conversation_info.knowledge_list = \
                        self.session.conversation_info.knowledge_list[-10:]
                
                logger.info(
                    f"[PFC][{self.user_name}] 成功获取知识: "
                    f"{knowledge_text[:100]}... (来源: {sources_text})"
                )
            else:
                logger.info(f"[PFC][{self.user_name}] 未找到相关知识")
            
            return True
            
        except Exception as e:
            logger.error(f"[PFC][{self.user_name}] 获取知识失败: {e}")
            import traceback
            traceback.print_exc()
            self.session.conversation_info.done_action[action_index].update({
                "status": "recall",
                "final_reason": f"获取知识失败: {e}"
            })
            return False
    
    async def _handle_rethink_goal(self, action_index: int) -> bool:
        """处理重新思考目标"""
        self.session.state = ConversationState.RETHINKING
        
        try:
            from .goal_analyzer import GoalAnalyzer
            analyzer = GoalAnalyzer(self.session)
            await analyzer.analyze_goal()
            return True
        except Exception as e:
            logger.error(f"[PFC][{self.user_name}] 重新思考目标失败: {e}")
            self.session.conversation_info.done_action[action_index].update({
                "status": "recall",
                "final_reason": f"重新思考目标失败: {e}"
            })
            return False
    
    async def _handle_listening(self, action_index: int) -> bool:
        """处理倾听"""
        self.session.state = ConversationState.LISTENING
        
        # 使用 waiter 进行真正的倾听等待（等待新消息或超时）
        await self._do_wait_listening()
        return True
    
    async def _do_wait_listening(self):
        """执行倾听等待"""
        from .waiter import Waiter
        from .plugin import get_config
        
        config = get_config()
        
        async def check_new_message(since_time: float) -> bool:
            """检查是否有新消息"""
            return self.session.observation_info.new_messages_count > 0
        
        waiter = Waiter(
            self.session.stream_id,
            self.user_name,
            config,
            new_message_checker=check_new_message
        )
        await waiter.wait_listening(self.session.conversation_info)
    
    async def _handle_wait(self, action_index: int) -> bool:
        """处理等待"""
        self.session.state = ConversationState.WAITING
        await self._do_wait()
        return True
    
    async def _do_wait(self):
        """执行等待"""
        from .waiter import Waiter
        from .plugin import get_config
        
        config = get_config()
        
        async def check_new_message(since_time: float) -> bool:
            """检查是否有新消息"""
            return self.session.observation_info.new_messages_count > 0
        
        waiter = Waiter(
            self.session.stream_id,
            self.user_name,
            config,
            new_message_checker=check_new_message
        )
        await waiter.wait(self.session.conversation_info)
    
    async def _handle_say_goodbye(self, action_index: int) -> bool:
        """处理告别"""
        from .replyer import ReplyGenerator
        
        self.session.state = ConversationState.GENERATING
        
        replyer = ReplyGenerator(self.session, self.user_name)
        reply_content = await replyer.generate(action_type="say_goodbye")
        
        if reply_content:
            self.session.generated_reply = reply_content
            await self._send_reply()
        
        self.session.should_continue = False
        return True
    
    async def _handle_end_conversation(self, action_index: int) -> bool:
        """处理结束对话"""
        self.session.should_continue = False
        logger.info(f"[PFC][{self.user_name}] 对话结束")
        return True
    
    async def _handle_block_and_ignore(self, action_index: int) -> bool:
        """处理屏蔽和忽略"""
        # 从配置获取屏蔽忽略时间
        block_seconds = self.config.waiting.block_ignore_seconds
        self.session.ignore_until_timestamp = time.time() + block_seconds
        self.session.should_continue = False
        logger.info(f"[PFC][{self.user_name}] 已屏蔽，{block_seconds // 60}分钟内忽略")
        return True


# 全局循环管理器
class ConversationLoopManager:
    """会话循环管理器"""
    
    _instance: Optional["ConversationLoopManager"] = None
    
    def __init__(self):
        self._loops: Dict[str, ConversationLoop] = {}
        self._lock = asyncio.Lock()
    
    @classmethod
    def get_instance(cls) -> "ConversationLoopManager":
        if cls._instance is None:
            cls._instance = ConversationLoopManager()
        return cls._instance
    
    async def get_or_create_loop(
        self,
        session: PFCSession,
        user_name: str,
    ) -> ConversationLoop:
        """获取或创建会话循环"""
        async with self._lock:
            user_id = session.user_id
            
            logger.debug(f"[PFC][{user_name}] get_or_create_loop: user_id={user_id}, session.should_continue={session.should_continue}")
            
            if user_id in self._loops:
                loop = self._loops[user_id]
                logger.debug(f"[PFC][{user_name}] 找到现有循环: _running={loop._running}, task={loop._task}")
                
                if loop._running:
                    # 循环正在运行，直接返回
                    logger.debug(f"[PFC][{user_name}] 复用现有运行中的循环")
                    return loop
                else:
                    # 循环已停止，需要清理并创建新循环
                    logger.debug(f"[PFC][{user_name}] 旧循环已停止，创建新循环")
                    del self._loops[user_id]
            
            # 创建新循环
            loop = ConversationLoop(session, user_name)
            self._loops[user_id] = loop
            await loop.start()
            
            logger.debug(f"[PFC][{user_name}] 新会话循环已创建并启动")
            return loop
    
    async def stop_loop(self, user_id: str):
        """停止会话循环"""
        async with self._lock:
            if user_id in self._loops:
                await self._loops[user_id].stop()
                del self._loops[user_id]
    
    async def stop_all(self):
        """停止所有循环"""
        async with self._lock:
            for loop in self._loops.values():
                await loop.stop()
            self._loops.clear()


def get_loop_manager() -> ConversationLoopManager:
    """获取循环管理器单例"""
    return ConversationLoopManager.get_instance()