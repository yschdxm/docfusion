"""
获取表单结构工具 - 检测Word文档中的可填写表单字段

功能：
- 使用LLM智能分析文档结构，识别所有可填写字段
- 支持段落式表单（下划线、方括号、冒号等）
- 支持表格式表单（空单元格、示例文本等）
- 支持混合式表单
- 支持Word内容控件
"""

import json
import re
from typing import Any, Dict, List, Optional

from app.agent.base.tool import BaseTool, ToolContext, ToolResult
from app.db.postgres import async_session
from app.models.document import Document
from sqlalchemy import select


class GetFormStructureTool(BaseTool):
    """获取表单结构工具

    使用LLM智能分析Word文档，检测并提取所有可填写的表单字段。
    适用于报名表、合同、申请表等各种类型的表单。
    """

    @property
    def name(self) -> str:
        return "get_form_structure"

    @property
    def description(self) -> str:
        return """获取Word文档中的表单结构信息（可填写字段）。

使用场景：
- 填写报名表、合同、申请表等非结构化表单前
- 了解文档中有哪些需要填写的字段
- 确定字段的位置和类型

支持检测的字段类型：
- 下划线占位符：______
- 方括号占位符：【】、[]
- 冒号模式：姓名：（冒号后无内容或有空格）
- 表格中的空单元格
- 表格中的示例/说明文本（应该被覆盖）
- Word内容控件

返回信息：
- 所有检测到的字段列表（含标签、类型、位置）
- 文档表单类型（unstructured/table_form/mixed）
- 字段总数"""

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "template_id": {
                    "type": "string",
                    "description": "模板文档ID"
                }
            },
            "required": ["template_id"]
        }

    async def execute(self, params: Dict[str, Any], context: ToolContext) -> ToolResult:
        """执行表单结构检测"""
        try:
            template_id = params.get("template_id", "")

            # UUID格式校验
            uuid_error = BaseTool.validate_uuid(template_id, "template_id")
            if uuid_error:
                return ToolResult(success=False, error=uuid_error)

            # 查询文档
            async with async_session() as db:
                result = await db.execute(
                    select(Document).where(Document.id == template_id)
                )
                doc = result.scalar_one_or_none()

                if not doc:
                    return ToolResult(
                        success=False,
                        error=f"模板文档不存在: {template_id}"
                    )

                if doc.file_type != "docx":
                    return ToolResult(
                        success=False,
                        error=f"表单检测仅支持docx格式，当前格式: {doc.file_type}"
                    )

                # 解析表单结构
                form_structure = await self._parse_form_structure(doc.file_path)

                return ToolResult(
                    success=True,
                    data={
                        "template_id": template_id,
                        "filename": doc.original_filename,
                        "file_type": doc.file_type,
                        **form_structure
                    }
                )

        except Exception as e:
            return ToolResult(
                success=False,
                error=f"获取表单结构失败: {str(e)}"
            )

    async def _parse_form_structure(self, file_path: str) -> Dict[str, Any]:
        """解析Word文档的表单结构"""
        from docx import Document as DocxDocument

        doc = DocxDocument(file_path)

        # 使用LLM分析整个文档结构
        fields = await self._analyze_document_with_llm(doc)

        # 判断表单类型
        has_paragraph_fields = any(f['location'].get('paragraph_index') is not None for f in fields)
        has_table_fields = any(f['location'].get('table_index') is not None for f in fields)

        if has_paragraph_fields and has_table_fields:
            form_type = "mixed"
        elif has_table_fields:
            form_type = "table_form"
        elif has_paragraph_fields:
            form_type = "unstructured"
        else:
            form_type = "unknown"

        return {
            "form_type": form_type,
            "fields": fields,
            "total_fields": len(fields)
        }

    async def _analyze_document_with_llm(self, doc) -> List[Dict[str, Any]]:
        """使用LLM智能分析整个文档结构"""
        from app.services.llm_service import llm_service

        # 提取文档内容
        doc_content = self._extract_document_content(doc)

        prompt = f"""请分析以下Word文档，识别所有需要填写的字段。

文档内容：
{doc_content}

请以JSON格式返回分析结果，包含：
- fields: 需要填写的字段列表，每个字段包含：
  - type: "paragraph" 或 "table"
  - label: 字段标签（如"姓名"、"实习名称"、"题目"等）
  - location: 位置信息
    - 对于段落：{{"paragraph_index": 段落索引}}
    - 对于表格：{{"table_index": 表格索引, "row_index": 行索引, "cell_index": 列索引}}
  - current_value: 当前内容（如果是示例/说明文本，标记为示例）
  - is_example: 是否是示例/说明文本（应该被覆盖）

判断规则：
1. 段落中的占位符：
   - 下划线（______）后面需要填写
   - 方括号（【】、[]）内需要填写
   - 冒号（：或:）后面没有内容或只有空格，需要填写
   - "请填写"、"请输入"等提示后面需要填写

2. 表格中的字段：
   - 空单元格需要填写
   - 包含示例文本（如"1、xxx 2、xxx"、"如xxx"、"例如xxx"）的单元格需要填写
   - 包含说明性文本（如"数据、算法、算力、人员等可行性"）的单元格需要填写
   - 表头行不需要填写

3. 特殊情况：
   - 如果文档是手册/指南，可能包含多个需要填写的部分
   - 如果文档是审批表，可能包含多个表格
   - 如果文档是申请表，可能包含段落和表格的混合

请只返回JSON，不要有其他内容。"""

        try:
            response = await llm_service.chat_completion(
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
                enable_thinking=False
            )

            # 解析JSON响应
            analysis = None
            if isinstance(response, str):
                json_match = re.search(r'\{[\s\S]*\}', response)
                if json_match:
                    analysis = json.loads(json_match.group())
            elif isinstance(response, dict):
                analysis = response

            if not analysis or not analysis.get("fields"):
                return []

            # 将LLM分析结果转换为字段列表
            fields = []
            for field_info in analysis["fields"]:
                field_type = field_info.get("type", "paragraph")
                label = field_info.get("label", "")
                location = field_info.get("location", {})
                current_value = field_info.get("current_value", "")
                is_example = field_info.get("is_example", False)

                if not label or not location:
                    continue

                # 构建字段对象
                field = {
                    "label": label,
                    "placeholder_type": "table_cell" if field_type == "table" else "llm_detected",
                    "placeholder_text": current_value if is_example else "",
                    "location": location,
                    "current_value": current_value,
                    "detected_type": self._infer_field_type(label)
                }
                fields.append(field)

            return fields

        except Exception as e:
            print(f"LLM分析文档失败: {e}")
            # 回退到基本检测逻辑
            return self._fallback_detection(doc)

    def _extract_document_content(self, doc) -> str:
        """提取文档内容供LLM分析"""
        content_parts = []

        # 提取段落内容
        for para_idx, para in enumerate(doc.paragraphs):
            text = para.text.strip()
            if text:
                content_parts.append(f"[段落{para_idx}] {text}")

        # 提取表格内容
        for table_idx, table in enumerate(doc.tables):
            content_parts.append(f"\n[表格{table_idx}]")
            for row_idx, row in enumerate(table.rows):
                cells = []
                for col_idx, cell in enumerate(row.cells):
                    cell_text = cell.text.strip()
                    cells.append(f"[{col_idx}]{cell_text if cell_text else '(空)'}")
                content_parts.append(f"  行{row_idx}: {' | '.join(cells)}")

        # 限制长度，避免超出LLM上下文
        content = "\n".join(content_parts)
        if len(content) > 10000:
            content = content[:10000] + "\n... (内容已截断)"

        return content

    def _fallback_detection(self, doc) -> List[Dict[str, Any]]:
        """回退检测逻辑（当LLM分析失败时使用）"""
        fields = []

        # 检测段落中的占位符
        for para_idx, para in enumerate(doc.paragraphs):
            text = para.text.strip()
            if not text:
                continue

            # 检测下划线
            if re.search(r'_{3,}', text):
                fields.append({
                    "label": self._extract_label_from_text(text),
                    "placeholder_type": "underline",
                    "placeholder_text": re.search(r'_{3,}', text).group(),
                    "location": {"paragraph_index": para_idx},
                    "current_value": "",
                    "detected_type": "text"
                })

            # 检测方括号
            if re.search(r'【\s*】|\[\s*\]', text):
                fields.append({
                    "label": self._extract_label_from_text(text),
                    "placeholder_type": "bracket",
                    "placeholder_text": re.search(r'【\s*】|\[\s*\]', text).group(),
                    "location": {"paragraph_index": para_idx},
                    "current_value": "",
                    "detected_type": "text"
                })

            # 检测冒号模式（冒号后无内容或只有空格）
            if re.search(r'[：:]\s*$', text):
                label = re.split(r'[：:]', text)[0].strip()
                if label and len(label) <= 20:
                    fields.append({
                        "label": label,
                        "placeholder_type": "colon",
                        "placeholder_text": text,
                        "location": {"paragraph_index": para_idx},
                        "current_value": "",
                        "detected_type": "text"
                    })

        # 检测表格中的空单元格
        for table_idx, table in enumerate(doc.tables):
            for row_idx, row in enumerate(table.rows):
                for col_idx, cell in enumerate(row.cells):
                    cell_text = cell.text.strip()
                    if not cell_text:
                        # 获取行标签（第一列）
                        label = row.cells[0].text.strip() if row.cells else f"字段{col_idx}"
                        fields.append({
                            "label": label,
                            "placeholder_type": "table_cell",
                            "placeholder_text": "",
                            "location": {
                                "table_index": table_idx,
                                "row_index": row_idx,
                                "cell_index": col_idx
                            },
                            "current_value": "",
                            "detected_type": "text"
                        })

        return fields

    def _extract_label_from_text(self, text: str) -> str:
        """从文本中提取标签"""
        # 尝试提取冒号前的文本
        label = re.split(r'[：:]', text)[0].strip()
        if label and len(label) <= 20:
            return label

        # 尝试提取空格前的文本
        label = text.split()[0] if text.split() else text
        return label[:20] if label else "未知字段"

    def _infer_field_type(self, label: str) -> str:
        """根据标签文本推断字段类型"""
        type_keywords = {
            'date': ['日期', '时间', '年', '月', '日', '出生', 'date', 'time'],
            'phone': ['电话', '手机', '联系方式', 'phone', 'tel'],
            'email': ['邮箱', '邮件', 'email'],
            'number': ['编号', '号码', '序号', '数量', '金额', '价格', 'number', 'id'],
            'address': ['地址', '住址', 'address'],
        }

        label_lower = label.lower()
        for field_type, keywords in type_keywords.items():
            for keyword in keywords:
                if keyword in label_lower:
                    return field_type
        return "text"
