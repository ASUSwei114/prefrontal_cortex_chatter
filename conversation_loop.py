"""PFC 会话循环管理器 - 复刻原版PFC的持续循环行为 (GPL-3.0)"""

from __future__ import annotations
import asyncio
import datetime
import time
from typing import Callable, Awaitable, Dict, Optional, TYPE_CHECKING

from src.common.logger import get_logger
from src.config.config import global_config
from .models import ConversationState, ConversationInfo
from .session import PFCSession

if TYPE_CHECKING:
    from .plugin import PFCConfig

logger = get_logger("pfc_loop")


# ============================================================================
# 等待器类 (原 waiter.py)
# ============================================================================

class Waiter:
    """等待处理类"""

    def __init__(self, stream_id: str, private_name: str, config: "PFCConfig",
                 new_message_checker: Optional[Callable[[float], Awaitable[bool]]] = None):
        self.stream_id = stream_id
        self.private_name = private_name
        self.config = config
        self.bot_name = global_config.bot.nickname if global_config else "Bot"
        self._new_message_checker = new_message_checker
        self.timeout_seconds = config.waiting.wait_timeout_seconds
        self.check_interval = 5

    def set_message_checker(self, checker: Callable[[float], Awaitable[bool]]):
        self._new_message_checker = checker

    async def wait(self, conversation_info: ConversationInfo) -> bool:
        """等待用户新消息或超时，返回True表示超时"""
        wait_start_time = time.time()
        logger.info(f"[私聊][{self.private_name}]进入常规等待状态 (超时: {self.timeout_seconds} 秒, 检查间隔: {self.check_interval} 秒)...")

        while True:
            if await self._check_new_message(wait_start_time):
                elapsed_time = time.time() - wait_start_time
                logger.info(f"[私聊][{self.private_name}]等待结束，收到新消息 (已等待 {elapsed_time:.1f} 秒)")
                return False

            elapsed_time = time.time() - wait_start_time
            if elapsed_time > self.timeout_seconds:
                logger.info(f"[私聊][{self.private_name}]等待超时 (已等待 {elapsed_time:.1f} 秒，超时阈值 {self.timeout_seconds} 秒)...添加思考目标。")
                conversation_info.goal_list.append({
                    "goal": f"你等待了{elapsed_time / 60:.1f}分钟，注意可能在对方看来聊天已经结束，思考接下来要做什么",
                    "reasoning": "对方很久没有回复你的消息了",
                })
                return True

            await asyncio.sleep(self.check_interval)

    async def wait_listening(self, conversation_info: ConversationInfo) -> bool:
        """倾听用户发言或超时，返回True表示超时"""
        wait_start_time = time.time()
        logger.info(f"[私聊][{self.private_name}]进入倾听等待状态 (超时: {self.timeout_seconds} 秒, 检查间隔: {self.check_interval} 秒)...")

        while True:
            if await self._check_new_message(wait_start_time):
                elapsed_time = time.time() - wait_start_time
                logger.info(f"[私聊][{self.private_name}]倾听等待结束，收到新消息 (已等待 {elapsed_time:.1f} 秒)")
                return False

            elapsed_time = time.time() - wait_start_time
            if elapsed_time > self.timeout_seconds:
                logger.info(f"[私聊][{self.private_name}]倾听等待超时 (已等待 {elapsed_time:.1f} 秒，超时阈值 {self.timeout_seconds} 秒)...添加思考目标。")
                conversation_info.goal_list.append({
                    "goal": f"你等待了{elapsed_time / 60:.1f}分钟，对方似乎话说一半突然消失了，思考接下来要做什么",
                    "reasoning": "对方话说一半消失了，很久没有回复",
                })
                return True

            await asyncio.sleep(self.check_interval)

    async def wait_short(self, seconds: float = 10.0) -> bool:
        """短暂等待"""
        await asyncio.sleep(seconds)
        return False

    async def _check_new_message(self, since_time: float) -> bool:
        if self._new_message_checker:
            try:
                return await self._new_message_checker(since_time)
            except Exception as e:
                logger.error(f"[私聊][{self.private_name}]检查新消息时出错: {e}")
        return False


# ============================================================================
# 会话循环类
# ============================================================================


class ConversationLoop:
    """单个会话的持续循环"""

    def __init__(self, session: PFCSession, user_name: str):
        self.session = session
        self.user_name = user_name
        from .plugin import get_config
        self.config = get_config()
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._interrupt_event = asyncio.Event()  # 新消息中断事件
        self._planning_task: Optional[asyncio.Task] = None  # 当前规划任务

    async def start(self):
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop())
        logger.info(f"[PFC][{self.user_name}] 会话循环已启动")

    async def stop(self):
        self._running = False
        self._interrupt_event.set()  # 触发中断事件
        if self._planning_task and not self._planning_task.done():
            self._planning_task.cancel()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info(f"[PFC][{self.user_name}] 会话循环已停止")

    def notify_new_message(self):
        """通知循环有新消息到达，触发中断"""
        self._interrupt_event.set()
        logger.debug(f"[PFC][{self.user_name}] 收到新消息通知，触发中断事件")

    async def _loop(self):
        """PFC核心循环"""
        while self._running and self.session.should_continue:
            # 忽略逻辑
            if self.session.ignore_until_timestamp:
                if time.time() < self.session.ignore_until_timestamp:
                    await asyncio.sleep(30)
                    continue
                logger.info(f"[PFC][{self.user_name}] 忽略时间已到，清除忽略状态")
                self.session.ignore_until_timestamp = None
                if self.session.observation_info.new_messages_count == 0:
                    self.session.should_continue = False
                continue

            try:
                # 清除中断事件，准备新一轮规划
                self._interrupt_event.clear()
                initial_new_message_count = self.session.observation_info.new_messages_count + 1

                from .planner import ActionPlanner
                planner = ActionPlanner(self.session, self.user_name)
                
                # 使用可中断的方式执行规划
                self._planning_task = asyncio.create_task(planner.plan())
                try:
                    # 等待规划完成或被中断
                    done, pending = await asyncio.wait(
                        [self._planning_task, asyncio.create_task(self._interrupt_event.wait())],
                        return_when=asyncio.FIRST_COMPLETED
                    )
                    
                    # 检查是否被中断
                    if self._interrupt_event.is_set():
                        # 取消规划任务
                        if not self._planning_task.done():
                            self._planning_task.cancel()
                            try:
                                await self._planning_task
                            except asyncio.CancelledError:
                                pass
                        logger.info(f"[PFC][{self.user_name}] 规划被新消息中断，重新规划")
                        self.session.conversation_info.last_successful_reply_action = None
                        # 取消等待任务
                        for task in pending:
                            task.cancel()
                            try:
                                await task
                            except asyncio.CancelledError:
                                pass
                        await asyncio.sleep(0.1)
                        continue
                    
                    # 获取规划结果
                    action, reason = self._planning_task.result()
                    # 取消等待任务
                    for task in pending:
                        task.cancel()
                        try:
                            await task
                        except asyncio.CancelledError:
                            pass
                finally:
                    self._planning_task = None

                current_new_message_count = self.session.observation_info.new_messages_count
                # 降低阈值：只要有新消息就重新规划
                if current_new_message_count > initial_new_message_count:
                    logger.info(f"[PFC][{self.user_name}] 规划期间发现新增消息 ({initial_new_message_count} -> {current_new_message_count})，重新规划")
                    self.session.conversation_info.last_successful_reply_action = None
                    await asyncio.sleep(0.1)
                    continue

                if initial_new_message_count > 0 and action in ["direct_reply", "send_new_message"]:
                    await self.session.clear_unprocessed_messages()
                    self.session.observation_info.new_messages_count = 0

                await self._handle_action(action, reason)

                # 检查结束对话目标
                for goal_item in (self.session.conversation_info.goal_list or []):
                    if isinstance(goal_item, dict) and goal_item.get("goal") == "结束对话":
                        self.session.should_continue = False
                        logger.info(f"[PFC][{self.user_name}] 检测到'结束对话'目标，停止循环")
                        break

            except Exception as e:
                logger.error(f"[PFC][{self.user_name}] PFC主循环出错: {e}")
                await asyncio.sleep(1)

            if self.session.should_continue:
                await asyncio.sleep(0.1)

        self._running = False
        logger.info(f"[PFC][{self.user_name}] PFC循环结束")

    def _check_new_messages_after_planning(self) -> bool:
        if self.session.observation_info.new_messages_count > 2:
            logger.info(f"[PFC][{self.user_name}] 生成期间收到新消息，取消当前动作")
            self.session.conversation_info.last_successful_reply_action = None
            return True
        return False

    async def _handle_action(self, action: str, reason: str):
        """处理规划的行动"""
        current_action_record = {
            "action": action, "plan_reason": reason, "status": "start",
            "time": datetime.datetime.now().strftime("%H:%M:%S"), "final_reason": None,
        }
        self.session.conversation_info.done_action.append(current_action_record)
        action_index = len(self.session.conversation_info.done_action) - 1

        handlers = {
            "direct_reply": lambda: self._handle_reply_action("direct_reply", action_index),
            "send_new_message": lambda: self._handle_reply_action("send_new_message", action_index),
            "fetch_knowledge": lambda: self._handle_fetch_knowledge(reason, action_index),
            "rethink_goal": lambda: self._handle_rethink_goal(action_index),
            "listening": lambda: self._handle_listening(action_index),
            "wait": lambda: self._handle_wait(action_index),
            "say_goodbye": lambda: self._handle_say_goodbye(action_index),
            "end_conversation": lambda: self._handle_end_conversation(action_index),
            "block_and_ignore": lambda: self._handle_block_and_ignore(action_index),
            "use_tool": lambda: self._handle_use_tool(reason, action_index),
        }

        handler = handlers.get(action)
        action_successful = await handler() if handler else False

        if action_successful:
            self.session.conversation_info.done_action[action_index].update({
                "status": "done", "time": datetime.datetime.now().strftime("%H:%M:%S"),
            })
            if action not in ["direct_reply", "send_new_message"]:
                self.session.conversation_info.last_successful_reply_action = None

    async def _handle_reply_action(self, action_type: str, action_index: int) -> bool:
        """处理回复类行动（支持中断）"""
        from .replyer import ReplyGenerator, ReplyChecker

        max_attempts = self.config.reply_checker.max_retries
        attempt, is_suitable, need_replan, check_reason, final_reply = 0, False, False, "未进行尝试", ""

        replyer = ReplyGenerator(self.session, self.user_name)
        checker = ReplyChecker(self.session.stream_id, self.user_name, self.config)

        while attempt < max_attempts and not is_suitable:
            # 检查是否被中断
            if self._interrupt_event.is_set():
                logger.info(f"[PFC][{self.user_name}] 回复生成被新消息中断")
                self.session.conversation_info.done_action[action_index].update({
                    "status": "recall", "final_reason": "被新消息中断"})
                return False
            
            attempt += 1
            self.session.state = ConversationState.GENERATING
            
            # 使用可中断的方式生成回复
            generate_task = asyncio.create_task(replyer.generate(action_type=action_type))
            interrupt_task = asyncio.create_task(self._interrupt_event.wait())
            
            try:
                done, pending = await asyncio.wait(
                    [generate_task, interrupt_task],
                    return_when=asyncio.FIRST_COMPLETED
                )
                
                # 检查是否被中断
                if self._interrupt_event.is_set():
                    if not generate_task.done():
                        generate_task.cancel()
                        try:
                            await generate_task
                        except asyncio.CancelledError:
                            pass
                    for task in pending:
                        task.cancel()
                        try:
                            await task
                        except asyncio.CancelledError:
                            pass
                    logger.info(f"[PFC][{self.user_name}] 回复生成被新消息中断")
                    self.session.conversation_info.done_action[action_index].update({
                        "status": "recall", "final_reason": "被新消息中断"})
                    return False
                
                reply_content = generate_task.result()
                # 取消等待任务
                for task in pending:
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass
            except Exception as e:
                logger.error(f"[PFC][{self.user_name}] 生成回复时出错: {e}")
                check_reason = f"第 {attempt} 次生成出错: {e}"
                continue

            if not reply_content:
                check_reason = f"第 {attempt} 次生成回复为空"
                continue

            self.session.state = ConversationState.CHECKING
            try:
                current_goal = (self.session.conversation_info.goal_list[0].get("goal", "")
                               if self.session.conversation_info.goal_list else "")
                is_suitable, check_reason, need_replan = await checker.check(
                    reply=reply_content, goal=current_goal,
                    chat_history=self.session.observation_info.chat_history,
                    chat_history_str=self.session.observation_info.chat_history_str,
                    retry_count=attempt - 1)
                if is_suitable:
                    final_reply = reply_content
                    break
                elif need_replan:
                    break
            except Exception as e:
                check_reason = f"第 {attempt} 次检查出错: {e}"
                break

        if is_suitable:
            # 发送前再次检查是否有新消息
            if self._interrupt_event.is_set() or self._check_new_messages_after_planning():
                self.session.conversation_info.done_action[action_index].update({
                    "status": "recall", "final_reason": f"有新消息，取消发送"})
                return False
            self.session.generated_reply = final_reply
            await self._send_reply()
            self.session.conversation_info.last_successful_reply_action = action_type
            self.session.conversation_info.done_action[action_index].update({
                "status": "done", "final_reason": f"成功发送: {final_reply[:30]}..."})
            return True

        self.session.conversation_info.done_action[action_index].update({
            "status": "recall", "final_reason": f"尝试{attempt}次后失败: {check_reason}"})
        self.session.conversation_info.last_successful_reply_action = None

        if not need_replan:
            self.session.state = ConversationState.WAITING
            await self._do_wait()
            self.session.conversation_info.done_action.append({
                "action": "wait", "plan_reason": f"因 {action_type} 多次尝试失败而执行的后备等待",
                "status": "done", "time": datetime.datetime.now().strftime("%H:%M:%S"), "final_reason": None})
        return False

    async def _send_reply(self):
        """发送回复（支持多行拆分）"""
        from src.plugin_system.apis import send_api
        reply_content = self.session.generated_reply
        if not reply_content:
            return

        try:
            lines = [line.strip() for line in reply_content.split('\n') if line.strip()]
            for i, line in enumerate(lines):
                await send_api.text_to_stream(text=line, stream_id=self.session.stream_id)
                self.session.add_bot_message(line)
                if i < len(lines) - 1:
                    await asyncio.sleep(0.5)
            logger.info(f"[PFC][{self.user_name}] 成功发送 {len(lines)} 条回复")
        except Exception as e:
            logger.error(f"[PFC][{self.user_name}] 发送回复失败: {e}")

    async def _handle_fetch_knowledge(self, query: str, action_index: int) -> bool:
        """处理获取知识"""
        self.session.state = ConversationState.FETCHING
        try:
            from .knowledge_fetcher import KnowledgeFetcher
            fetcher = KnowledgeFetcher(self.user_name, self.config)
            knowledge_text, sources_text = await fetcher.fetch(
                query=query, chat_history=self.session.observation_info.chat_history)

            if knowledge_text and knowledge_text != "未找到相关知识":
                if not hasattr(self.session.conversation_info, 'knowledge_list') or \
                   self.session.conversation_info.knowledge_list is None:
                    self.session.conversation_info.knowledge_list = []
                self.session.conversation_info.knowledge_list.append({
                    "query": query[:200], "knowledge": knowledge_text,
                    "source": sources_text, "time": time.time()})
                if len(self.session.conversation_info.knowledge_list) > 10:
                    self.session.conversation_info.knowledge_list = \
                        self.session.conversation_info.knowledge_list[-10:]
            return True
        except Exception as e:
            logger.error(f"[PFC][{self.user_name}] 获取知识失败: {e}")
            self.session.conversation_info.done_action[action_index].update({
                "status": "recall", "final_reason": f"获取知识失败: {e}"})
            return False

    async def _handle_rethink_goal(self, action_index: int) -> bool:
        self.session.state = ConversationState.RETHINKING
        try:
            from .goal_analyzer import GoalAnalyzer
            await GoalAnalyzer(self.session).analyze_goal()
            return True
        except Exception as e:
            logger.error(f"[PFC][{self.user_name}] 重新思考目标失败: {e}")
            self.session.conversation_info.done_action[action_index].update({
                "status": "recall", "final_reason": f"重新思考目标失败: {e}"})
            return False

    async def _handle_listening(self, action_index: int) -> bool:
        self.session.state = ConversationState.LISTENING
        await self._do_wait_listening()
        return True

    async def _do_wait_listening(self):
        initial_count = self.session.observation_info.new_messages_count

        async def check_new_message(since_time: float) -> bool:
            # 检查是否有新消息或被中断
            if self._interrupt_event.is_set():
                return True
            return self.session.observation_info.new_messages_count > initial_count

        waiter = Waiter(self.session.stream_id, self.user_name, self.config, new_message_checker=check_new_message)
        await waiter.wait_listening(self.session.conversation_info)

    async def _handle_wait(self, action_index: int) -> bool:
        self.session.state = ConversationState.WAITING
        await self._do_wait()
        return True

    async def _do_wait(self):
        initial_count = self.session.observation_info.new_messages_count

        async def check_new_message(since_time: float) -> bool:
            # 检查是否有新消息或被中断
            if self._interrupt_event.is_set():
                return True
            return self.session.observation_info.new_messages_count > initial_count

        waiter = Waiter(self.session.stream_id, self.user_name, self.config, new_message_checker=check_new_message)
        await waiter.wait(self.session.conversation_info)

    async def _handle_say_goodbye(self, action_index: int) -> bool:
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
        self.session.should_continue = False
        logger.info(f"[PFC][{self.user_name}] 对话结束")
        return True

    async def _handle_block_and_ignore(self, action_index: int) -> bool:
        block_seconds = self.config.waiting.block_ignore_seconds
        self.session.ignore_until_timestamp = time.time() + block_seconds
        self.session.should_continue = False
        logger.info(f"[PFC][{self.user_name}] 已屏蔽，{block_seconds // 60}分钟内忽略")
        return True

    async def _handle_use_tool(self, reason: str, action_index: int) -> bool:
        """处理使用工具行动 - 由 PFC 决策后执行工具"""
        self.session.state = ConversationState.FETCHING
        try:
            from .context_builder import PFCContextBuilder
            from .shared import format_chat_history
            
            builder = PFCContextBuilder(self.session.stream_id, self.config)
            
            # 从 reason 中提取工具名称（如果有的话）
            tool_name = self._extract_tool_name_from_reason(reason)
            
            # 构建聊天历史
            from .shared import PersonalityHelper
            personality_helper = PersonalityHelper(self.user_name)
            chat_history_text = format_chat_history(
                self.session.observation_info.chat_history,
                personality_helper.bot_name,
                self.user_name,
                10
            )
            
            # 获取目标消息
            target_message = ""
            if self.session.observation_info.chat_history:
                target_message = self.session.observation_info.chat_history[-1].get("content", "")
            
            # 执行工具决策
            result = await builder.execute_tool_decision(
                tool_name=tool_name or "",
                tool_args=None,  # 让 LLM 自动推断参数
                chat_history=chat_history_text,
                sender_name=self.user_name,
                target_message=target_message
            )
            
            if result.get("success"):
                used_tools = result.get("used_tools", [])
                tool_results = result.get("results", [result.get("result")])
                
                # 记录工具执行结果到会话
                if not hasattr(self.session.conversation_info, 'tool_results') or \
                   self.session.conversation_info.tool_results is None:
                    self.session.conversation_info.tool_results = []
                
                for tool_result in tool_results:
                    if tool_result:
                        self.session.conversation_info.tool_results.append({
                            "tool_name": tool_result.get("tool_name", "unknown"),
                            "content": tool_result.get("content", ""),
                            "time": time.time()
                        })
                
                # 保留最近10条工具结果
                if len(self.session.conversation_info.tool_results) > 10:
                    self.session.conversation_info.tool_results = \
                        self.session.conversation_info.tool_results[-10:]
                
                logger.info(f"[PFC][{self.user_name}] 工具执行成功: {used_tools}")
                self.session.conversation_info.done_action[action_index].update({
                    "status": "done",
                    "final_reason": f"成功执行工具: {', '.join(used_tools) if used_tools else tool_name}"
                })
                return True
            else:
                error_msg = result.get("error", "未知错误")
                logger.warning(f"[PFC][{self.user_name}] 工具执行失败: {error_msg}")
                self.session.conversation_info.done_action[action_index].update({
                    "status": "recall",
                    "final_reason": f"工具执行失败: {error_msg}"
                })
                return False
                
        except Exception as e:
            logger.error(f"[PFC][{self.user_name}] 使用工具失败: {e}")
            self.session.conversation_info.done_action[action_index].update({
                "status": "recall",
                "final_reason": f"使用工具失败: {e}"
            })
            return False

    def _extract_tool_name_from_reason(self, reason: str) -> str:
        """从 reason 中提取工具名称"""
        import re
        
        # 尝试匹配常见的工具名称模式
        patterns = [
            r'使用\s*[「"\'`]?(\w+)[」"\'`]?\s*工具',
            r'调用\s*[「"\'`]?(\w+)[」"\'`]?',
            r'工具[：:]\s*[「"\'`]?(\w+)[」"\'`]?',
            r'tool[：:]\s*[「"\'`]?(\w+)[」"\'`]?',
            r'(\w+_\w+)',  # 匹配下划线分隔的工具名
        ]
        
        for pattern in patterns:
            match = re.search(pattern, reason, re.IGNORECASE)
            if match:
                return match.group(1)
        
        return ""


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

    async def get_or_create_loop(self, session: PFCSession, user_name: str) -> ConversationLoop:
        async with self._lock:
            user_id = session.user_id
            if user_id in self._loops:
                loop = self._loops[user_id]
                if loop._running:
                    # 更新 user_name（可能从临时会话变为有昵称的会话）
                    if user_name and user_name != user_id:
                        loop.user_name = user_name
                    return loop
                del self._loops[user_id]

            loop = ConversationLoop(session, user_name)
            self._loops[user_id] = loop
            await loop.start()
            return loop

    async def stop_loop(self, user_id: str):
        async with self._lock:
            if user_id in self._loops:
                await self._loops[user_id].stop()
                del self._loops[user_id]

    async def stop_all(self):
        async with self._lock:
            for loop in self._loops.values():
                await loop.stop()
            self._loops.clear()


def get_loop_manager() -> ConversationLoopManager:
    return ConversationLoopManager.get_instance()