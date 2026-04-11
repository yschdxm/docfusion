# Agent系统重构指南

## 重构完成总结

### 1. 新增架构组件

#### Agent核心模块 (`backend/app/agent/`)
```
agent/
├── __init__.py                 # 模块入口
├── base/                       # 基础组件
│   ├── __init__.py
│   └── tool.py                 # 工具基类、上下文、结果定义
├── core/                       # 核心运行时
│   ├── __init__.py
│   ├── runtime.py              # AgentRuntime - Agent主循环
│   ├── registry.py             # ToolRegistry - 工具注册表
│   ├── executor.py             # ToolExecutor - 工具执行器
│   ├── stream.py               # StreamManager - 流式输出管理
│   └── tracker.py              # StepTracker - 步骤追踪
├── tools/                      # 工具实现
│   ├── __init__.py
│   ├── rag_tool.py             # RAG检索工具
│   ├── doc_reader_tool.py      # 文档阅读工具
│   ├── pg_query_tool.py        # PostgreSQL查询工具
│   ├── neo4j_query_tool.py     # Neo4j查询工具
│   ├── list_docs_tool.py       # 文档列表工具
│   ├── fill_table_tool.py      # 表格填写工具
│   ├── get_table_structure_tool.py  # 获取表格结构工具
│   └── extract_from_docs_tool.py    # 文档提取工具
└── agents/                     # Agent实现
    ├── __init__.py
    └── fill_table_agent.py     # 填表专用Agent
```

#### 新增API端点
- `POST /api/v1/agent/stream` - 流式Agent对话接口
- `POST /api/v1/agent/stream/fill-table` - 填表专用流式接口

#### 新增Schema
- `backend/app/schemas/agent_stream.py` - 流式事件schema

### 2. 关键设计特点

#### 类OpenClaw架构
1. **工具系统**：每个工具实现`BaseTool`接口，定义name/description/parameters/execute
2. **工具注册表**：统一管理工具，支持权限控制(allow/deny lists)
3. **AgentRuntime**：协调LLM调用和工具执行的主循环
4. **流式输出**：SSE格式实时推送Agent思考过程、工具调用、结果

#### 数据查找优先级（严格遵循）
```python
1. PostgreSQL (query_pg_database)  - 结构化数据，最准确
2. Neo4j知识图谱 (query_knowledge_graph) - 实体关系数据
3. RAG向量检索 (rag_search) - 非结构化文本
4. 文档提取 (extract_from_documents) - 最后手段
```

#### 流式事件类型
- `thinking_start/chunk/end` - 思考过程
- `tool_call/result/error` - 工具调用
- `step_start/progress/end` - 步骤执行
- `data_retrieval_start/progress/end` - 数据检索
- `fill_table_start/progress/end` - 填表进度
- `completed/failed` - 任务完成/失败

### 3. API使用示例

#### 流式填表请求
```http
POST /api/v1/agent/stream
Content-Type: application/json
Accept: text/event-stream

{
  "message": "请帮我填写汇总表",
  "file_ids": ["uuid-1", "uuid-2"],
  "template_id": "uuid-template",
  "task_type": "fill_table"
}
```

#### SSE响应示例
```
event: step_start
data: {"event_type": "step_start", "step_id": "step_1", "data": {"step_name": "分析表格结构", ...}}

event: step_progress
data: {"event_type": "step_progress", "step_id": "step_1", "data": {"progress": 100, "message": "表格有3列..."}}

event: step_end
data: {"event_type": "step_end", "step_id": "step_1", "data": {"result_summary": "表格结构分析完成"}}

event: data_retrieval_start
data: {"event_type": "data_retrieval_start", "data": {"source": "postgresql", "query": "..."}}
...
event: completed
data: {"event_type": "completed", "data": {"message": "填表完成", "download_url": "..."}}
```

### 4. 前端适配建议

#### TypeScript类型定义
```typescript
// Agent事件类型
interface AgentEvent {
  event_type: string;
  step_id?: string;
  timestamp: string;
  data: Record<string, any>;
}

// SSE连接
class AgentStreamService {
  async *streamChat(request: AgentStreamRequest): AsyncGenerator<AgentEvent> {
    const response = await fetch('/api/v1/agent/stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(request)
    });

    const reader = response.body?.getReader();
    const decoder = new TextDecoder();

    while (true) {
      const { done, value } = await reader!.read();
      if (done) break;

      const chunk = decoder.decode(value);
      // 解析SSE格式并yield事件
      for (const event of this.parseSSE(chunk)) {
        yield event;
      }
    }
  }
}
```

#### 组件建议
1. **AgentThinkingPanel** - 展示Agent思考过程
2. **ToolCallCard** - 展示工具调用和结果
3. **ProgressBar** - 展示步骤进度
4. **ActionConfirmCard** - 展示需要确认的操作

### 5. 工具清单

| 工具名 | 描述 | 使用场景 |
|--------|------|---------|
| `list_documents` | 列出所有文档 | 了解可用资源 |
| `get_table_structure` | 获取表格结构 | 填表前分析表头 |
| `query_pg_database` | 查询PostgreSQL | 查找结构化数据 |
| `query_knowledge_graph` | 查询Neo4j | 查找实体关系 |
| `rag_search` | RAG向量检索 | 语义搜索 |
| `extract_from_documents` | 文档提取 | 最后手段提取 |
| `fill_table` | 填写表格 | 执行最终填表 |

### 6. 数据流

```
用户请求
  ↓
AgentRuntime
  ↓
步骤1: 获取表格结构 (get_table_structure)
  ↓
步骤2: 查询PG (query_pg_database)
  ↓
步骤3: 查询Neo4j (query_knowledge_graph) [如需要]
  ↓
步骤4: RAG检索 (rag_search) [如需要]
  ↓
步骤5: 整合数据
  ↓
步骤6: 填写表格 (fill_table)
  ↓
返回结果
```

### 7. 测试建议

#### 后端测试
```python
# 测试工具
from app.agent.tools import RAGTool

tool = RAGTool()
result = await tool.run(
    {"query": "城市GDP", "top_k": 5},
    ToolContext(session_id="test", file_ids=["doc1"])
)
assert result.success

# 测试Agent
from app.agent.agents import FillTableAgent

agent = FillTableAgent()
result = await agent.run(
    user_instruction="填写汇总表",
    file_ids=["doc1"],
    template_id="template1",
    stream=StreamManager(),
    tracker=StepTracker()
)
assert result["success"]
```

#### API测试
```bash
# 测试流式接口
curl -X POST http://localhost:8000/api/v1/agent/stream \
  -H "Content-Type: application/json" \
  -H "Accept: text/event-stream" \
  -d '{
    "message": "请帮我填写汇总表",
    "file_ids": ["doc-id-1"],
    "template_id": "template-id-1"
  }'
```

### 8. 注意事项

1. **向后兼容**：原有的 `/agent/chat` 端点仍然可用
2. **错误处理**：每个工具都有错误处理和重试机制
3. **数据安全**：工具只能查询，不能修改原始数据
4. **性能优化**：数据查找遵循优先级，避免不必要的查询
5. **流式超时**：默认5分钟超时，可在StreamManager中调整

### 9. 后续优化方向

1. **缓存机制**：为工具结果添加缓存，避免重复查询
2. **并行执行**：多个独立查询可以并行执行
3. **智能决策**：LLM自动判断数据完整性，减少不必要的查询
4. **用户确认**：重要操作前要求用户确认
5. **文档编辑工具**：添加文档编辑功能（预留）

### 10. 相关文件修改

- `backend/app/api/v1/api.py` - 添加流式端点路由
- `backend/app/api/v1/endpoints/agent_stream.py` - 新增流式API
- `backend/app/schemas/agent_stream.py` - 新增schema

所有原有功能保持不变，新功能通过新端点提供。
