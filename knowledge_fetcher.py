"""
PFC知识获取器模块

负责从记忆系统和知识库中获取相关知识
"""

from typing import List, Tuple, Dict, Any, Optional
from src.common.logger import get_logger
from src.plugin_system.apis import llm_api

from .config import PFCConfig

logger = get_logger("PFC-KnowledgeFetcher")


class KnowledgeFetcher:
    """
    知识获取器
    
    负责从记忆系统和知识库中获取与查询相关的知识
    """
    
    def __init__(
        self,
        private_name: str,
        config: PFCConfig
    ):
        """
        初始化知识获取器
        
        Args:
            private_name: 私聊对象名称
            config: PFC配置
        """
        self.private_name = private_name
        self.config = config
        
        # 记忆管理器（延迟初始化）
        self._hippocampus_manager = None
        self._qa_manager = None
        
        logger.debug(f"[私聊][{private_name}]知识获取器初始化完成")
    
    @property
    def hippocampus_manager(self):
        """延迟加载记忆管理器"""
        if self._hippocampus_manager is None:
            try:
                from src.plugins.memory_system.Hippocampus import HippocampusManager
                self._hippocampus_manager = HippocampusManager.get_instance()
            except ImportError:
                logger.warning(
                    f"[私聊][{self.private_name}]"
                    "无法导入HippocampusManager，记忆功能不可用"
                )
            except Exception as e:
                logger.error(
                    f"[私聊][{self.private_name}]"
                    f"初始化HippocampusManager失败: {e}"
                )
        return self._hippocampus_manager
    
    @property
    def qa_manager(self):
        """延迟加载QA管理器"""
        if self._qa_manager is None:
            try:
                from src.plugins.knowledge.knowledge_lib import qa_manager
                self._qa_manager = qa_manager
            except ImportError:
                logger.warning(
                    f"[私聊][{self.private_name}]"
                    "无法导入qa_manager，知识库功能不可用"
                )
            except Exception as e:
                logger.error(
                    f"[私聊][{self.private_name}]"
                    f"初始化qa_manager失败: {e}"
                )
        return self._qa_manager
    
    async def fetch(
        self,
        query: str,
        chat_history: List[Dict[str, Any]]
    ) -> Tuple[str, str]:
        """
        获取相关知识
        
        Args:
            query: 查询内容
            chat_history: 聊天历史
            
        Returns:
            (获取的知识, 知识来源) 元组
        """
        logger.debug(f"[私聊][{self.private_name}]开始获取知识: {query[:50]}...")
        
        # 构建查询上下文
        chat_history_text = self._format_chat_history(chat_history)
        
        knowledge_parts = []
        sources = []
        
        # 从记忆系统获取相关知识
        memory_knowledge, memory_sources = await self._fetch_from_memory(
            query,
            chat_history_text
        )
        if memory_knowledge:
            knowledge_parts.append(memory_knowledge)
            sources.extend(memory_sources)
        
        # 从知识库获取相关知识
        kb_knowledge = self._fetch_from_knowledge_base(query)
        if kb_knowledge and kb_knowledge != "未找到匹配的知识":
            knowledge_parts.append(
                f"\n现在有以下**知识**可供参考：\n{kb_knowledge}\n"
                "请记住这些**知识**，并根据**知识**回答问题。\n"
            )
            sources.append("知识库")
        
        # 组合知识
        if knowledge_parts:
            knowledge_text = "\n".join(knowledge_parts)
            sources_text = "，".join(sources) if sources else "无来源"
        else:
            knowledge_text = "未找到相关知识"
            sources_text = "无记忆匹配"
        
        logger.debug(
            f"[私聊][{self.private_name}]获取到知识: "
            f"{knowledge_text[:100]}..., 来源: {sources_text}"
        )
        
        return knowledge_text, sources_text
    
    async def _fetch_from_memory(
        self,
        query: str,
        chat_history_text: str
    ) -> Tuple[str, List[str]]:
        """
        从记忆系统获取相关知识
        
        Args:
            query: 查询内容
            chat_history_text: 聊天历史文本
            
        Returns:
            (知识文本, 来源列表) 元组
        """
        if not self.hippocampus_manager:
            return "", []
        
        try:
            related_memory = await self.hippocampus_manager.get_memory_from_text(
                text=f"{query}\n{chat_history_text}",
                max_memory_num=3,
                max_memory_length=2,
                max_depth=3,
                fast_retrieval=False,
            )
            
            if not related_memory:
                return "", []
            
            knowledge_parts = []
            sources = []
            
            for memory in related_memory:
                memory_id = memory[0]
                memory_content = memory[1]
                knowledge_parts.append(memory_content)
                sources.append(f"记忆片段{memory_id}")
            
            knowledge_text = "\n".join(knowledge_parts)
            return knowledge_text, sources
            
        except Exception as e:
            logger.error(
                f"[私聊][{self.private_name}]从记忆系统获取知识失败: {e}"
            )
            return "", []
    
    def _fetch_from_knowledge_base(self, query: str) -> str:
        """
        从知识库获取相关知识
        
        Args:
            query: 查询内容
            
        Returns:
            知识文本
        """
        if not self.qa_manager:
            return ""
        
        logger.debug(f"[私聊][{self.private_name}]正在从LPMM知识库中获取知识")
        
        try:
            knowledge_info = self.qa_manager.get_knowledge(query)
            logger.debug(
                f"[私聊][{self.private_name}]LPMM知识库查询结果: "
                f"{str(knowledge_info)[:150]}"
            )
            return knowledge_info
        except Exception as e:
            logger.error(
                f"[私聊][{self.private_name}]LPMM知识库搜索工具执行失败: {e}"
            )
            return "未找到匹配的知识"
    
    def _format_chat_history(
        self,
        chat_history: List[Dict[str, Any]]
    ) -> str:
        """
        格式化聊天历史为文本
        
        Args:
            chat_history: 聊天历史列表
            
        Returns:
            格式化的聊天历史文本
        """
        if not chat_history:
            return ""
        
        formatted_lines = []
        for msg in chat_history[-10:]:  # 只取最近10条
            sender = msg.get("sender", {})
            sender_name = sender.get("nickname", "未知用户")
            content = msg.get("processed_plain_text", msg.get("content", ""))
            formatted_lines.append(f"{sender_name}: {content}")
        
        return "\n".join(formatted_lines)
    
    async def fetch_with_context(
        self,
        query: str,
        context: str,
        max_results: int = 5
    ) -> List[Dict[str, Any]]:
        """
        带上下文的知识获取
        
        Args:
            query: 查询内容
            context: 上下文信息
            max_results: 最大结果数
            
        Returns:
            知识结果列表
        """
        results = []
        
        # 从记忆获取
        if self.hippocampus_manager:
            try:
                memories = await self.hippocampus_manager.get_memory_from_text(
                    text=f"{query}\n{context}",
                    max_memory_num=max_results,
                    max_memory_length=2,
                    max_depth=3,
                    fast_retrieval=True,
                )
                
                for memory in memories or []:
                    results.append({
                        "type": "memory",
                        "id": memory[0],
                        "content": memory[1],
                        "source": f"记忆片段{memory[0]}"
                    })
            except Exception as e:
                logger.error(f"[私聊][{self.private_name}]获取记忆失败: {e}")
        
        # 从知识库获取
        if self.qa_manager and len(results) < max_results:
            try:
                kb_result = self.qa_manager.get_knowledge(query)
                if kb_result and kb_result != "未找到匹配的知识":
                    results.append({
                        "type": "knowledge_base",
                        "id": "kb_0",
                        "content": kb_result,
                        "source": "知识库"
                    })
            except Exception as e:
                logger.error(f"[私聊][{self.private_name}]获取知识库失败: {e}")
        
        return results[:max_results]
    
    async def summarize_knowledge(
        self,
        knowledge_list: List[Dict[str, Any]],
        query: str
    ) -> str:
        """
        总结知识内容
        
        使用LLM对获取的知识进行总结
        
        Args:
            knowledge_list: 知识列表
            query: 原始查询
            
        Returns:
            总结后的知识文本
        """
        if not knowledge_list:
            return "未找到相关知识"
        
        # 构建知识文本
        knowledge_text = ""
        for i, item in enumerate(knowledge_list):
            content = item.get("content", "")
            source = item.get("source", "未知来源")
            knowledge_text += f"{i+1}. [{source}] {content}\n\n"
        
        # 如果知识较短，直接返回
        if len(knowledge_text) < 500:
            return knowledge_text
        
        # 使用LLM总结
        prompt = f"""请根据以下知识内容，针对问题"{query}"进行简洁的总结：

{knowledge_text}

请用简洁的语言总结上述知识中与问题相关的要点，不超过200字。"""
        
        try:
            summary = await llm_api.generate_with_model(
                model_name=self.config.llm.chat_model,
                prompt=prompt,
                temperature=0.3,
                max_tokens=300
            )
            return summary
        except Exception as e:
            logger.error(f"[私聊][{self.private_name}]总结知识失败: {e}")
            return knowledge_text[:500] + "..."