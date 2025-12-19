"""
PFC等待器模块

================================================================================
版权声明 (Copyright Notice)
================================================================================

原始代码来源: MaiM-with-u (https://github.com/MaiM-with-u/MaiBot)
原始版本: 0.6.3-fix4
原始代码路径: src/plugins/PFC/
原始许可证: GNU General Public License v3.0

本文件由 ASUSwei114 (https://github.com/ASUSwei114) 于 2024年12月 修改移植至 MoFox_Bot 项目。

本项目遵循 GNU General Public License v3.0 许可证。
详见 LICENSE 文件。

================================================================================

负责处理等待用户消息和超时逻辑
"""

import time
import asyncio
from typing import Optional, Callable, Awaitable
from src.common.logger import get_logger
from src.config.config import global_config

from .models import ConversationInfo
from .config import PFCConfig

logger = get_logger("PFC-Waiter")


class Waiter:
    """
    等待处理类
    
    负责等待用户新消息或处理超时情况
    """
    
    def __init__(
        self,
        stream_id: str,
        private_name: str,
        config: PFCConfig,
        new_message_checker: Optional[Callable[[float], Awaitable[bool]]] = None
    ):
        """
        初始化等待器
        
        Args:
            stream_id: 会话流ID
            private_name: 私聊对象名称
            config: PFC配置
            new_message_checker: 检查新消息的回调函数
        """
        self.stream_id = stream_id
        self.private_name = private_name
        self.config = config
        self.bot_name = global_config.bot.nickname
        
        # 新消息检查器（由外部注入）
        self._new_message_checker = new_message_checker
        
        # 超时配置 - 使用 waiting 配置
        self.timeout_seconds = config.waiting.default_max_wait_seconds
        self.check_interval = 5  # 每5秒检查一次
        
        logger.debug(f"[私聊][{private_name}]等待器初始化完成")
    
    def set_message_checker(
        self,
        checker: Callable[[float], Awaitable[bool]]
    ):
        """
        设置新消息检查器
        
        Args:
            checker: 检查新消息的回调函数，接收时间戳参数，返回是否有新消息
        """
        self._new_message_checker = checker
    
    async def wait(
        self,
        conversation_info: ConversationInfo
    ) -> bool:
        """
        等待用户新消息或超时
        
        Args:
            conversation_info: 对话信息
            
        Returns:
            True表示超时，False表示收到新消息
        """
        wait_start_time = time.time()
        logger.info(
            f"[私聊][{self.private_name}]进入常规等待状态 "
            f"(超时: {self.timeout_seconds} 秒)..."
        )
        
        while True:
            # 检查是否有新消息
            if await self._check_new_message(wait_start_time):
                logger.info(f"[私聊][{self.private_name}]等待结束，收到新消息")
                return False  # 返回 False 表示不是超时
            
            # 检查是否超时
            elapsed_time = time.time() - wait_start_time
            if elapsed_time > self.timeout_seconds:
                logger.info(
                    f"[私聊][{self.private_name}]等待超过 "
                    f"{self.timeout_seconds} 秒...添加思考目标。"
                )
                
                # 添加超时思考目标
                wait_goal = {
                    "goal": (
                        f"你等待了{elapsed_time / 60:.1f}分钟，"
                        "注意可能在对方看来聊天已经结束，思考接下来要做什么"
                    ),
                    "reasoning": "对方很久没有回复你的消息了",
                }
                conversation_info.goal_list.append(wait_goal)
                logger.info(f"[私聊][{self.private_name}]添加目标: {wait_goal}")
                
                return True  # 返回 True 表示超时
            
            await asyncio.sleep(self.check_interval)
            logger.debug(f"[私聊][{self.private_name}]等待中...")
    
    async def wait_listening(
        self,
        conversation_info: ConversationInfo
    ) -> bool:
        """
        倾听用户发言或超时
        
        与普通等待不同，倾听模式下超时后会添加不同的思考目标
        
        Args:
            conversation_info: 对话信息
            
        Returns:
            True表示超时，False表示收到新消息
        """
        wait_start_time = time.time()
        logger.info(
            f"[私聊][{self.private_name}]进入倾听等待状态 "
            f"(超时: {self.timeout_seconds} 秒)..."
        )
        
        while True:
            # 检查是否有新消息
            if await self._check_new_message(wait_start_time):
                logger.info(f"[私聊][{self.private_name}]倾听等待结束，收到新消息")
                return False  # 返回 False 表示不是超时
            
            # 检查是否超时
            elapsed_time = time.time() - wait_start_time
            if elapsed_time > self.timeout_seconds:
                logger.info(
                    f"[私聊][{self.private_name}]倾听等待超过 "
                    f"{self.timeout_seconds} 秒...添加思考目标。"
                )
                
                # 添加倾听超时思考目标
                wait_goal = {
                    "goal": (
                        f"你等待了{elapsed_time / 60:.1f}分钟，"
                        "对方似乎话说一半突然消失了，可能忙去了？"
                        "也可能忘记了回复？要问问吗？还是结束对话？"
                        "或继续等待？思考接下来要做什么"
                    ),
                    "reasoning": "对方话说一半消失了，很久没有回复",
                }
                conversation_info.goal_list.append(wait_goal)
                logger.info(f"[私聊][{self.private_name}]添加目标: {wait_goal}")
                
                return True  # 返回 True 表示超时
            
            await asyncio.sleep(self.check_interval)
            logger.debug(f"[私聊][{self.private_name}]倾听等待中...")
    
    async def wait_short(
        self,
        seconds: float = 10.0
    ) -> bool:
        """
        短暂等待
        
        用于在某些操作之间添加短暂延迟
        
        Args:
            seconds: 等待秒数
            
        Returns:
            始终返回False
        """
        logger.debug(f"[私聊][{self.private_name}]短暂等待 {seconds} 秒...")
        await asyncio.sleep(seconds)
        return False
    
    async def _check_new_message(self, since_time: float) -> bool:
        """
        检查是否有新消息
        
        Args:
            since_time: 检查此时间之后的消息
            
        Returns:
            是否有新消息
        """
        if self._new_message_checker:
            try:
                return await self._new_message_checker(since_time)
            except Exception as e:
                logger.error(
                    f"[私聊][{self.private_name}]检查新消息时出错: {e}"
                )
                return False
        
        # 如果没有设置检查器，默认返回False
        return False

