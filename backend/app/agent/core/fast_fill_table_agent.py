"""
快速填表Agent - 为90秒约束深度优化

负责：
- 快速填表流程
- 并行执行
- 进度报告
"""

from typing import Dict, Any, List
import asyncio
import logging
from datetime import datetime

from app.agent.core.fast_mode_detector import FastModeDecision
from app.agent.core.fast_intent_classifier import fast_intent_classifier, IntentResult
from app.agent.core.query_template_engine import query_template_engine, QueryIntent
from app.agent.core.parallel_data_fetcher import parallel_data_fetcher, DataQuery
from app.agent.core.streaming_file_generator import streaming_file_generator
from app.agent.core.stream import StreamManager, AgentEventType
from app.agent.base.tool import ToolContext

logger = logging.getLogger(__name__)


class FastFillTableAgent:
    """快速填表Agent

    为90秒约束深度优化，采用单次LLM调用 + 并行工具执行。
    """

    SYSTEM_PROMPT = """你是一个快速填表助手。

## 工作流程
1. 获取表格结构
2. 查询数据
3. 列映射
4. 填写表格
5. 生成摘要

## 规则
- 只使用提供的工具
- 不要重复查询
- 不要询问用户确认
- 直接执行操作

## 可用工具
- get_table_structure: 获取表格结构
- query_pg_database: 查询PostgreSQL
- query_knowledge_graph: 查询Neo4j
- fill_table: 填写表格
"""

    async def execute(
        self,
        user_message: str,
        file_ids: List[str],
        template_id: str,
        context: ToolContext,
        stream_manager: StreamManager,
        decision: FastModeDecision
    ) -> Dict[str, Any]:
        """执行快速填表

        Args:
            user_message: 用户消息
            file_ids: 源文件ID列表
            template_id: 模板ID
            context: 工具上下文
            stream_manager: 流管理器
            decision: 快速模式决策

        Returns:
            执行结果
        """
        logger.info("[FastFillTableAgent] 开始快速填表")
        start_time = datetime.utcnow()

        try:
            # 步骤1: 并行获取结构 + 解析意图
            await stream_manager.emit_progress(0.1, "获取表格结构和解析意图...")
            structure, intent = await asyncio.gather(
                self._get_table_structure(template_id),
                fast_intent_classifier.classify(user_message)
            )

            # 步骤2: 并行查询数据
            await stream_manager.emit_progress(0.3, "查询数据...")
            queries = self._build_queries(intent, file_ids, structure)
            data_results = await parallel_data_fetcher.fetch_all(queries)

            # 步骤3: 列映射
            await stream_manager.emit_progress(0.6, "列映射...")
            mapping = await self._map_columns(structure, data_results)

            # 步骤4: 合并数据
            merged_data = self._merge_data(data_results)

            # 步骤5: 填写表格
            await stream_manager.emit_progress(0.8, "填写表格...")
            file_info = await streaming_file_generator.generate_and_stream(
                template_id=template_id,
                data=merged_data,
                mapping=mapping,
                stream_bus=stream_manager,
                task_id=context.session_id
            )

            # 步骤6: 生成摘要
            await stream_manager.emit_progress(1.0, "完成")
            summary = self._generate_summary(merged_data, file_info)

            # 计算耗时
            duration_ms = int((datetime.utcnow() - start_time).total_seconds() * 1000)

            logger.info(f"[FastFillTableAgent] 快速填表完成 | 耗时: {duration_ms}ms")

            return {
                "success": True,
                "final_content": summary,
                "artifacts": [file_info],
                "duration_ms": duration_ms,
                "iterations": 1,
                "tokens_used": 0  # 快速模式不统计token
            }

        except Exception as e:
            logger.exception(f"[FastFillTableAgent] 快速填表失败: {e}")
            duration_ms = int((datetime.utcnow() - start_time).total_seconds() * 1000)

            return {
                "success": False,
                "final_content": f"快速填表失败: {str(e)}",
                "artifacts": [],
                "duration_ms": duration_ms,
                "iterations": 1,
                "tokens_used": 0
            }

    async def _get_table_structure(self, template_id: str) -> Dict[str, Any]:
        """获取表格结构"""
        from app.agent.tools.get_table_structure_tool import GetTableStructureTool

        tool = GetTableStructureTool()
        result = await tool.execute(
            {"file_id": template_id},
            ToolContext(session_id="fast", file_ids=[template_id])
        )

        if not result.success:
            raise ValueError(f"获取表格结构失败: {result.error}")

        return result.data

    def _build_queries(
        self,
        intent: IntentResult,
        file_ids: List[str],
        structure: Dict[str, Any]
    ) -> List[DataQuery]:
        """构建查询列表"""
        queries = []

        # 根据意图构建查询
        if intent.data_source in ["pg", "auto"]:
            for file_id in file_ids:
                queries.append(DataQuery(
                    source_type="postgresql",
                    query=f"SELECT * FROM data WHERE doc_id = '{file_id}'",
                    params={"file_id": file_id}
                ))

        if intent.data_source in ["neo4j", "auto"]:
            for file_id in file_ids:
                queries.append(DataQuery(
                    source_type="neo4j",
                    query=f"MATCH (n) WHERE n.document_id = '{file_id}' RETURN n",
                    params={"file_id": file_id}
                ))

        if intent.data_source in ["rag", "auto"]:
            queries.append(DataQuery(
                source_type="rag",
                query=intent.extracted_entities.get("data_hint", ""),
                params={"top_k": 10}
            ))

        return queries

    async def _map_columns(
        self,
        structure: Dict[str, Any],
        data_results: List[Dict[str, Any]]
    ) -> Dict[str, str]:
        """列映射"""
        from app.services.llm_service import llm_service

        # 获取表头
        headers = structure.get("headers", [])

        # 合并所有数据列名
        all_columns = set()
        for result in data_results:
            if "columns" in result:
                all_columns.update(result["columns"])
            elif "data" in result and result["data"]:
                if isinstance(result["data"][0], dict):
                    all_columns.update(result["data"][0].keys())

        # 调用LLM进行列映射
        mapping = await llm_service.map_columns(
            target_columns=headers,
            source_columns=list(all_columns)
        )

        return mapping

    def _merge_data(self, data_results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """合并数据"""
        merged = []

        for result in data_results:
            if "data" in result:
                data = result["data"]
                if isinstance(data, list) and data:
                    if isinstance(data[0], dict):
                        merged.extend(data)
                    else:
                        # 转换为字典格式
                        for item in data:
                            if isinstance(item, dict):
                                merged.append(item)

        # 去重
        seen = set()
        unique_data = []
        for row in merged:
            row_key = str(sorted(row.items()))
            if row_key not in seen:
                seen.add(row_key)
                unique_data.append(row)

        return unique_data

    def _generate_summary(
        self,
        data: List[Dict[str, Any]],
        file_info: Dict[str, Any]
    ) -> str:
        """生成摘要"""
        return f"""填表完成！

- 填写行数: {len(data)}
- 输出文件: {file_info.get('filename', '未知')}
- 下载链接: {file_info.get('download_url', '未知')}"""


# 全局快速填表Agent实例
fast_fill_table_agent = FastFillTableAgent()
