"""
文档引擎层：地址模型 / 快照 / 原子操作 / 映射与 dry_run / 表头与数据源 / 文件生命周期

工具层（app.agent.tools）只是薄壳：把 LLM 参数适配为引擎调用。
"""

from app.agent.document_engine import ops
from app.agent.document_engine.address import (
    Address,
    AddressResolver,
    ContentControlAddr,
    DocxParagraphAddr,
    DocxTableAddr,
    DocxTableCellAddr,
    XlsxCellAddr,
    XlsxSheetAddr,
    describe_address,
    list_content_controls,
)
from app.agent.document_engine.fill import (
    commit_cell_fills,
    commit_table_fill,
    dry_run_cell_fills,
    dry_run_table_fill,
)
from app.agent.document_engine.mapping import (
    CellFill,
    DryRunItem,
    DryRunReport,
    TableFillPlan,
)
from app.agent.document_engine.snapshot import DocSnapshot

__all__ = [
    "Address",
    "AddressResolver",
    "CellFill",
    "ContentControlAddr",
    "DocSnapshot",
    "DocxParagraphAddr",
    "DocxTableAddr",
    "DocxTableCellAddr",
    "DryRunItem",
    "DryRunReport",
    "TableFillPlan",
    "XlsxCellAddr",
    "XlsxSheetAddr",
    "commit_cell_fills",
    "commit_table_fill",
    "describe_address",
    "dry_run_cell_fills",
    "dry_run_table_fill",
    "list_content_controls",
    "ops",
]
