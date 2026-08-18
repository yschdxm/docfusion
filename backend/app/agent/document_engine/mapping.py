"""
映射与 dry_run 报告的数据模型

LLM 的产出是"映射"（纯数据、可 pydantic 校验），而不是不透明的参数 blob：
- TableFillPlan: 统计表填写 —— LLM 做列对齐判断（column_map），行物化由引擎确定性执行
- CellFill: 逐格填写 —— 用于表单字段、交叉表单元格、用户指定位置
- DryRunReport: 引擎对映射做纯确定性校验（不写盘），逐条报告状态
"""

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

from app.agent.document_engine.address import (
    Address,
    DocxTableAddr,
    XlsxSheetAddr,
)


# ──────────────────────────── 填表映射 ────────────────────────────

class TableFillPlan(BaseModel):
    """统计表（行重复结构）填写计划

    LLM 只产出列对齐映射；data 为记录数组（key 为源数据列名）。
    引擎按 column_map 把每条记录物化为表的一行。
    """
    target: DocxTableAddr | XlsxSheetAddr = Field(..., description="目标表格")
    fill_mode: Literal["overwrite", "append"] = Field(
        "overwrite", description="overwrite=清空表头以下数据行后填入；append=追加到末尾"
    )
    column_map: Dict[str, str] = Field(
        default_factory=dict,
        description="模板表头 → 源数据列名。未列入的表头由引擎自动匹配兜底（精确→大小写→包含）"
    )
    data: List[Dict[str, Any]] = Field(default_factory=list, description="记录数组（key 为源数据列名）")


class CellFill(BaseModel):
    """逐格填写项（表单字段 / 交叉表单元格 / 指定位置）"""
    target: Address = Field(..., description="目标地址")
    value: Any = Field(None, description="要写入的值，null 表示清空")
    source: Optional[str] = Field(None, description="值来源说明（如 '文档A 第2段'），可选")
    rationale: Optional[str] = Field(None, description="填值理由，可选")


# ──────────────────────────── dry_run 报告 ────────────────────────────

DryRunStatus = Literal["ok", "type_mismatch", "ambiguous", "not_found", "empty_value"]


class DryRunItem(BaseModel):
    """单条映射的校验结果"""
    subject: str = Field(..., description="校验对象描述（地址或列名）")
    status: DryRunStatus
    detail: str = Field("", description="状态说明（当前值、期望值、候选等）")


class DryRunReport(BaseModel):
    """dry_run 校验报告（纯确定性产出，不写盘）"""
    items: List[DryRunItem] = Field(default_factory=list)
    total: int = 0
    ok_count: int = 0

    def add(self, subject: str, status: DryRunStatus, detail: str = "") -> None:
        self.items.append(DryRunItem(subject=subject, status=status, detail=detail))
        self.total += 1
        if status == "ok":
            self.ok_count += 1

    @property
    def all_ok(self) -> bool:
        return self.total > 0 and self.ok_count == self.total

    @property
    def problem_items(self) -> List[DryRunItem]:
        return [i for i in self.items if i.status != "ok"]

    def summary(self) -> str:
        if not self.items:
            return "没有可校验的映射项"
        problems = self.problem_items
        if not problems:
            return f"全部 {self.total} 项校验通过"
        lines = [f"共 {self.total} 项，{self.ok_count} 项通过，{len(problems)} 项需处理："]
        for item in problems[:20]:
            lines.append(f"  [{item.status}] {item.subject}: {item.detail}")
        if len(problems) > 20:
            lines.append(f"  ... 其余 {len(problems) - 20} 项略")
        return "\n".join(lines)
