"""
PFC知识获取器模块

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
        self._memory_manager = None
        self._qa_manager = None
        self._web_search_tool = None
        
        logger.debug(f"[私聊][{private_name}]知识获取器初始化完成")
    
    @property
    def memory_manager(self):
        """延迟加载记忆管理器"""
        if self._memory_manager is None:
            try:
                from src.memory_graph.manager_singleton import get_memory_manager
                self._memory_manager = get_memory_manager()
                if self._memory_manager is None:
                    logger.warning(
                        f"[私聊][{self.private_name}]"
                        "MemoryManager未初始化，记忆功能不可用"
                    )
            except ImportError:
                logger.warning(
                    f"[私聊][{self.private_name}]"
                    "无法导入MemoryManager，记忆功能不可用"
                )
            except Exception as e:
                logger.error(
                    f"[私聊][{self.private_name}]"
                    f"获取MemoryManager失败: {e}"
                )
        return self._memory_manager
    
    @property
    def qa_manager(self):
        """延迟加载QA管理器"""
        if self._qa_manager is None:
            try:
                from src.chat.knowledge.knowledge_lib import qa_manager
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
    
    @property
    def web_search_tool(self):
        """延迟加载联网搜索工具"""
        if self._web_search_tool is None:
            try:
                from src.plugins.built_in.WEB_SEARCH_TOOL.tools.web_search import WebSurfingTool
                self._web_search_tool = WebSurfingTool()
                logger.debug(
                    f"[私聊][{self.private_name}]"
                    "联网搜索工具初始化成功"
                )
            except ImportError:
                logger.warning(
                    f"[私聊][{self.private_name}]"
                    "无法导入WebSurfingTool，联网搜索功能不可用"
                )
            except Exception as e:
                logger.error(
                    f"[私聊][{self.private_name}]"
                    f"初始化WebSurfingTool失败: {e}"
                )
        return self._web_search_tool
    
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
        
        # 从联网搜索获取相关知识（如果启用）
        if self.config.web_search.enabled:
            web_knowledge = await self._fetch_from_web_search(query)
            if web_knowledge:
                knowledge_parts.append(
                    f"\n现在有以下**联网搜索结果**可供参考：\n{web_knowledge}\n"
                    "请参考这些最新信息回答问题。\n"
                )
                sources.append("联网搜索")
        
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
        if not self.memory_manager:
            return "", []
        
        try:
            # 使用 MoFox_Bot 的 MemoryManager.search_memories
            search_query = f"{query}\n{chat_history_text}"
            memories = await self.memory_manager.search_memories(
                query=search_query,
                top_k=3,
                min_importance=0.0,
                include_forgotten=False,
            )
            
            if not memories:
                return "", []
            
            knowledge_parts = []
            sources = []
            
            for memory in memories:
                # Memory 对象有 to_text() 方法
                memory_text = memory.to_text()
                knowledge_parts.append(memory_text)
                sources.append(f"记忆片段{memory.id[:8]}")
            
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
    
    async def _fetch_from_web_search(self, query: str) -> str:
        """
        从联网搜索获取相关知识
        
        Args:
            query: 查询内容
            
        Returns:
            搜索结果文本
        """
        if not self.web_search_tool:
            return ""
        
        logger.debug(f"[私聊][{self.private_name}]正在进行联网搜索: {query[:50]}...")
        
        try:
            # 构建搜索参数
            search_args = {
                "query": query,
                "num_results": self.config.web_search.num_results,
                "time_range": self.config.web_search.time_range,
                "answer_mode": self.config.web_search.answer_mode,
            }
            
            # 执行搜索
            result = await self.web_search_tool.execute(search_args)
            
            if "error" in result:
                logger.warning(
                    f"[私聊][{self.private_name}]联网搜索失败: {result['error']}"
                )
                return ""
            
            # 获取搜索结果内容
            content = result.get("content", "")
            if content:
                logger.debug(
                    f"[私聊][{self.private_name}]联网搜索成功，"
                    f"结果长度: {len(content)}"
                )
                return content
            
            return ""
            
        except Exception as e:
            logger.error(
                f"[私聊][{self.private_name}]联网搜索执行失败: {e}"
            )
            return ""
    
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
        if self.memory_manager:
            try:
                memories = await self.memory_manager.search_memories(
                    query=f"{query}\n{context}",
                    top_k=max_results,
                    min_importance=0.0,
                    include_forgotten=False,
                )
                
                for memory in memories or []:
                    results.append({
                        "type": "memory",
                        "id": memory.id,
                        "content": memory.to_text(),
                        "source": f"记忆片段{memory.id[:8]}"
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
        
        # 从联网搜索获取
        if self.config.web_search.enabled and len(results) < max_results:
            try:
                web_result = await self._fetch_from_web_search(query)
                if web_result:
                    results.append({
                        "type": "web_search",
                        "id": "web_0",
                        "content": web_result,
                        "source": "联网搜索"
                    })
            except Exception as e:
                logger.error(f"[私聊][{self.private_name}]获取联网搜索失败: {e}")
        
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