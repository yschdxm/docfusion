"""
填表专用Agent

封装完整的填表流程：获取表格结构 -> 查询数据 -> 填写表格 -> 验证。
拥有独立的System Prompt，专注于填表任务。
"""

from typing import Any, Dict

from app.agent.core.delegation import DelegateAgentTool
from app.agent.core.registry import ToolRegistry
from app.agent.core.runtime import AgentRuntime
from app.agent.tools import (
    RAGTool,
    PGQueryTool,
    Neo4jQueryTool,
    GetTableStructureTool,
    FillTableTool,
    ExtractFromDocsTool,
)
from app.agent.prompts.shared import (
    WORK_PRINCIPLES,
    DOCUMENT_TYPE_ROUTING,
    QUERY_FAILURE_STRATEGY,
    FILL_TABLE_STEP1_2,
    FILL_TABLE_STEP3_DETAILED,
    FILL_TABLE_STEP4_5,
    RESULT_REPORTING,
    MULTI_TABLE_STRATEGY,
    IMPORTANT_REMINDERS,
)


FILL_TABLE_SYSTEM_PROMPT = f"""你是一个专业的表格填写Agent，专注于根据源文档数据填写表格模板。

{WORK_PRINCIPLES}

{DOCUMENT_TYPE_ROUTING}

## 数据查找策略（根据文档类型选择）

### 对于 xlsx 源文档：
1. **PostgreSQL (query_pg_database)** - xlsx结构化数据，最准确
2. **Neo4j (query_knowledge_graph)** - PG无结果时使用
3. **RAG检索 (rag_search)** - 非结构化文本补充
4. **文档提取 (extract_from_documents)** - 最后手段

### 对于 docx/md/txt 源文档：

**核心原则：批量提取结构化记录时，必须使用 extract_from_documents，禁止用 rag_search 逐条提取！**

**工具选择指南：**
| 场景 | 推荐工具 | 原因 |
|------|----------|------|
| 批量提取表格数据 | **extract_from_documents** | 一次返回多条结构化记录 |
| 查询特定实体信息 | query_knowledge_graph | 精确查询单个实体 |
| 补充少量缺失数据 | rag_search | 搜索文本片段 |

**禁止行为：**
- 禁止反复用 rag_search 重复搜索同一类数据
- 禁止用 query_knowledge_graph 批量查询表格数据（它只返回有限记录）
- 禁止在 extract_from_documents 已返回足够数据后继续搜索

**注意**: docx/md/txt 文档在PG中没有数据，不要尝试PG查询

{QUERY_FAILURE_STRATEGY}

## 填表任务完整流程（重要）

当用户需要填写表格时（消息包含"填表"、"填写"、"fill"或提供了template_id）：

{FILL_TABLE_STEP1_2}

{FILL_TABLE_STEP3_DETAILED}

{FILL_TABLE_STEP4_5}

{RESULT_REPORTING}

{MULTI_TABLE_STRATEGY}

## 增量填表示例流程
```
用户: "填写XXX数据到模板"

↓ 1. get_table_structure(template_id)
   → 获取表头和表格结构

↓ 2. fill_table(source_query={{"doc_ids": [...], "query": "查询XXX数据", "fetch_all": true}}, template_id=模板ID)
   → 工具自动查询并返回数据摘要
   → 审核摘要：数据列名是否匹配，数据是否完整

↓ 3. fill_table(source_query={{..., "data_confirmed": true}}, template_id=模板ID)
   → 确认填入，创建新文件，返回 output_file_id
   → 已填N行

↓ 4. 评估：已填行数 < 预期行数？继续查询追加

↓ 5. fill_table(source_query={{"query": "补充查询更多数据", "fetch_all": true}}, output_doc_id=xxx, fill_mode="append")
   → 确认后追加到已有文件

↓ 6. 报告用户：填写行数、预期行数、完整度、下载链接
```

{IMPORTANT_REMINDERS}
"""


class FillTableAgent(DelegateAgentTool):
    """填表专用Agent

    封装完整的填表流程：获取表格结构 -> 查询数据 -> 填写表格 -> 验证。
    拥有独立的System Prompt，专注于填表任务。
    """

    @property
    def name(self) -> str:
        return "delegate_fill_table"

    @property
    def description(self) -> str:
        return "将填表任务委派给专用的填表Agent。当用户需要填写表格、填充数据到模板时使用此工具。"

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "task_description": {
                    "type": "string",
                    "description": "填表任务描述"
                },
                "file_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "源文档ID列表"
                },
                "template_id": {
                    "type": "string",
                    "description": "模板文档ID"
                },
            },
            "required": ["task_description", "template_id"]
        }

    def _create_agent(self) -> AgentRuntime:
        """创建填表专用Agent，只注册填表相关工具"""
        registry = ToolRegistry()
        registry.register(GetTableStructureTool())
        registry.register(PGQueryTool())
        registry.register(Neo4jQueryTool())
        registry.register(RAGTool())
        registry.register(FillTableTool())
        registry.register(ExtractFromDocsTool())
        # 注意：不注册 list_documents、read_document 等无关工具
        # 注意：不注册任何 DelegateAgentTool，防止嵌套

        return AgentRuntime(
            registry,
            max_iterations=50,  # 复杂填表任务需要较多迭代
            system_prompt=FILL_TABLE_SYSTEM_PROMPT,
        )

    def _extract_result(self, result: Dict[str, Any]) -> Dict[str, Any]:
        """从子Agent结果中提取填表特有信息"""
        return {
            "output_file_id": result.get("output_file_id"),
            "download_url": result.get("download_url"),
            "filled_rows": result.get("filled_rows"),
        }
