"""
工具集模块

包含所有可用的Agent工具：
- rag_search: 向量检索
- read_document: 文档阅读（含 xlsx 范围读取）
- get_document_outline: 文档结构大纲（带索引，编辑定位用）
- get_template_structure: 模板结构分析（类型+表头+表单字段，填表前必调）
- query_pg_database: PG数据库查询
- query_knowledge_graph: 知识图谱查询
- list_documents: 文档列表
- fill_table: 表格填写
- fill_form: 表单填写
- edit_xlsx_cells: Excel单元格精确编辑
- edit_docx_cell: Word表格单元格精确编辑
- find_replace_all: 全文查找替换（正文+表格）
- edit_paragraph: 段落内容编辑（replace/rewrite/insert_after/split）
- format_paragraph: 段落格式（heading/list/style）
- convert: 格式转换
- create_word_document: 新建Word文档
- web_search: 联网搜索（非必要不使用，需用户声明）
"""

from .rag_tool import RAGTool
from .doc_reader_tool import DocReaderTool
from .doc_outline_tool import GetDocumentOutlineTool
from .get_template_structure_tool import GetTemplateStructureTool
from .pg_query_tool import PGQueryTool
from .neo4j_query_tool import Neo4jQueryTool
from .list_docs_tool import ListDocumentsTool
from .fill_table_tool import FillTableTool
from .fill_form_tool import FillFormTool
from .edit_cells_tool import EditXlsxCellsTool, EditDocxCellTool, FindReplaceAllTool
from .web_search_tool import WebSearchTool
from .document_edit_tools import (
    CreateWordDocumentTool,
    EditParagraphTool,
    FormatParagraphTool,
    ConvertTool,
)

__all__ = [
    "RAGTool",
    "DocReaderTool",
    "GetDocumentOutlineTool",
    "GetTemplateStructureTool",
    "PGQueryTool",
    "Neo4jQueryTool",
    "ListDocumentsTool",
    "FillTableTool",
    "FillFormTool",
    "EditXlsxCellsTool",
    "EditDocxCellTool",
    "FindReplaceAllTool",
    "WebSearchTool",
    "CreateWordDocumentTool",
    "EditParagraphTool",
    "FormatParagraphTool",
    "ConvertTool",
]
