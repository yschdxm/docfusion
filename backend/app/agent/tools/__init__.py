"""
工具集模块

包含所有可用的Agent工具（共46个）：
- rag_search: 向量检索
- read_document: 文档阅读
- read_cell_range: 读取Excel指定范围
- read_selection: 读取用户选中内容
- get_document_info: 获取文档元数据
- search_in_document: 在文档中搜索文本
- query_pg_database: PG数据库查询
- query_knowledge_graph: 知识图谱查询
- list_documents: 文档列表
- fill_table: 表格填写
- fill_cell: 填写单个单元格
- fill_row: 填写整行
- fill_column: 填写整列
- auto_fill_suggestions: 智能填充建议
- get_table_structure: 获取表格结构
- extract_from_documents: 文档信息提取
- replace_text: 文本替换
- rewrite_paragraph: LLM重写段落
- insert_after: 段落后插入
- heading_promote: 标题级别调整
- list_format: 列表格式化
- paragraph_split: 段落拆分
- set_text_style: 字体样式设置
- convert: 格式转换
- delete_content: 删除内容
- merge_cells: 合并单元格
- split_cell: 拆分单元格
- set_cell_formula: 设置公式
- set_cell_style: 设置样式
- apply_template_style: 应用模板样式
- batch_edit: 批量编辑
- build_knowledge_graph: 构建知识图谱
- find_related_entities: 查找关联实体
- get_entity_details: 获取实体详情
- search_documents: 跨文档搜索
- web_search: 网络搜索
- natural_language_query: 自然语言查询
- aggregate_data: 数据聚合
- ask_user: 向用户提问
- show_notification: 显示通知
- get_current_time: 获取当前时间
- create_task: 创建任务
- get_task_status: 获取任务状态
- cancel_task: 取消任务
- export_document: 导出文档
- generate_preview: 生成预览
"""

# 现有工具
from .rag_tool import RAGTool
from .doc_reader_tool import DocReaderTool, ReadCellRangeTool, ReadSelectionTool, GetDocumentInfoTool, SearchInDocumentTool
from .pg_query_tool import PGQueryTool
from .neo4j_query_tool import Neo4jQueryTool
from .list_docs_tool import ListDocumentsTool
from .fill_table_tool import FillTableTool, FillCellTool, FillRowTool, FillColumnTool, AutoFillSuggestionsTool
from .get_table_structure_tool import GetTableStructureTool
from .extract_from_docs_tool import ExtractFromDocsTool
from .document_edit_tools import (
    ReplaceTextTool,
    RewriteParagraphTool,
    InsertAfterTool,
    HeadingPromoteTool,
    ListFormatTool,
    ParagraphSplitTool,
    SetTextStyleTool,
    ConvertTool,
    DeleteContentTool,
    MergeCellsTool,
    SplitCellTool,
    SetCellFormulaTool,
    SetCellStyleTool,
    ApplyTemplateStyleTool,
)

# 新增工具
from .batch_edit_tool import BatchEditTool
from .knowledge_tools import BuildKnowledgeGraphTool, FindRelatedEntitiesTool, GetEntityDetailsTool
from .search_tools import SearchDocumentsTool, WebSearchTool
from .query_tools import NaturalLanguageQueryTool, AggregateDataTool
from .system_tools import AskUserTool, ShowNotificationTool, GetCurrentTimeTool, CreateTaskTool, GetTaskStatusTool, CancelTaskTool
from .export_tools import ExportDocumentTool, GeneratePreviewTool

__all__ = [
    # 现有工具
    "RAGTool",
    "DocReaderTool",
    "ReadCellRangeTool",
    "ReadSelectionTool",
    "GetDocumentInfoTool",
    "SearchInDocumentTool",
    "PGQueryTool",
    "Neo4jQueryTool",
    "ListDocumentsTool",
    "FillTableTool",
    "FillCellTool",
    "FillRowTool",
    "FillColumnTool",
    "AutoFillSuggestionsTool",
    "GetTableStructureTool",
    "ExtractFromDocsTool",
    "ReplaceTextTool",
    "RewriteParagraphTool",
    "InsertAfterTool",
    "HeadingPromoteTool",
    "ListFormatTool",
    "ParagraphSplitTool",
    "SetTextStyleTool",
    "ConvertTool",
    "DeleteContentTool",
    "MergeCellsTool",
    "SplitCellTool",
    "SetCellFormulaTool",
    "SetCellStyleTool",
    "ApplyTemplateStyleTool",
    # 新增工具
    "BatchEditTool",
    "BuildKnowledgeGraphTool",
    "FindRelatedEntitiesTool",
    "GetEntityDetailsTool",
    "SearchDocumentsTool",
    "WebSearchTool",
    "NaturalLanguageQueryTool",
    "AggregateDataTool",
    "AskUserTool",
    "ShowNotificationTool",
    "GetCurrentTimeTool",
    "CreateTaskTool",
    "GetTaskStatusTool",
    "CancelTaskTool",
    "ExportDocumentTool",
    "GeneratePreviewTool",
]


def get_all_tools():
    """获取所有工具实例"""
    return [
        # 现有工具
        RAGTool(),
        DocReaderTool(),
        ReadCellRangeTool(),
        ReadSelectionTool(),
        GetDocumentInfoTool(),
        SearchInDocumentTool(),
        PGQueryTool(),
        Neo4jQueryTool(),
        ListDocumentsTool(),
        FillTableTool(),
        FillCellTool(),
        FillRowTool(),
        FillColumnTool(),
        AutoFillSuggestionsTool(),
        GetTableStructureTool(),
        ExtractFromDocsTool(),
        ReplaceTextTool(),
        RewriteParagraphTool(),
        InsertAfterTool(),
        HeadingPromoteTool(),
        ListFormatTool(),
        ParagraphSplitTool(),
        SetTextStyleTool(),
        ConvertTool(),
        DeleteContentTool(),
        MergeCellsTool(),
        SplitCellTool(),
        SetCellFormulaTool(),
        SetCellStyleTool(),
        ApplyTemplateStyleTool(),
        # 新增工具
        BatchEditTool(),
        BuildKnowledgeGraphTool(),
        FindRelatedEntitiesTool(),
        GetEntityDetailsTool(),
        SearchDocumentsTool(),
        WebSearchTool(),
        NaturalLanguageQueryTool(),
        AggregateDataTool(),
        AskUserTool(),
        ShowNotificationTool(),
        GetCurrentTimeTool(),
        CreateTaskTool(),
        GetTaskStatusTool(),
        CancelTaskTool(),
        ExportDocumentTool(),
        GeneratePreviewTool(),
    ]
