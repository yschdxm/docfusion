from typing import Dict, Any, Optional, List
from app.services.llm_service import llm_service
from app.services.table_filling_service import table_filling_service
from app.services.document_processor import DocxParser, XlsxParser, MdParser, TxtParser
import logging

logger = logging.getLogger(__name__)


class DocumentAgent:
    def __init__(self):
        self.parsers = {
            "docx": DocxParser(),
            "xlsx": XlsxParser(),
            "md": MdParser(),
            "txt": TxtParser()
        }

    async def process_instruction(
        self,
        intent: str,
        documents_content: List[Dict[str, Any]],
        template_content: Optional[Dict[str, Any]] = None,
        instruction: str = "",
        action_id: Optional[str] = None
    ) -> Dict[str, Any]:
        logger.debug("[AGENT] process_instruction: intent=%s, action_id=%s, docs=%d, template=%s",
                      intent, action_id, len(documents_content), bool(template_content))
        try:
            if action_id and action_id.startswith("fill-"):
                return await self._execute_table_fill(documents_content, template_content)

            if intent == "fill_table":
                return await self._execute_table_fill(documents_content, template_content, instruction)
            elif intent == "operation":
                return await self._execute_document_operation(documents_content, instruction)
            else:
                return {"success": False, "message": "未知操作类型"}
        except Exception as e:
            logger.error(f"指令处理失败: intent={intent}, error={e}")
            return {"success": False, "message": f"操作失败: {str(e)}"}

    async def _execute_table_fill(
        self,
        documents_content: List[Dict[str, Any]],
        template_content: Optional[Dict[str, Any]],
        instruction: str = "智能填写表格"
    ) -> Dict[str, Any]:
        logger.debug("[AGENT] _execute_table_fill: docs=%d, template=%s, template_type=%s",
                      len(documents_content),
                      template_content.get("filename", "") if template_content else "",
                      template_content.get("file_type", "") if template_content else "")
        try:
            if not template_content:
                return {"success": False, "message": "缺少模板文件。"}

            template_file = {
                "file_type": template_content["file_type"],
                "file_path": template_content.get("file_path", ""),
            }

            # 提取 doc_ids
            doc_ids = [d["id"] for d in documents_content if "id" in d]

            if not documents_content:
                fill_result = await table_filling_service.auto_fill_table(
                    template_file=template_file,
                    user_instruction=instruction,
                )
            else:
                source_files = [
                    {"file_type": d["file_type"], "file_path": d.get("file_path", "")}
                    for d in documents_content
                ]

                if template_content["file_type"] == "xlsx":
                    fill_result = await table_filling_service.fill_table(
                        source_files=source_files,
                        template_file=template_file,
                        user_instruction=instruction,
                        doc_ids=doc_ids,
                    )
                else:
                    fill_result = await table_filling_service.fill_word_template(
                        source_files=source_files,
                        template_file=template_file,
                        user_instruction=instruction,
                        doc_ids=doc_ids,
                    )

            return {
                "success": True,
                "message": "表格填写完成！您可以下载填写后的文件。",
                "action": {
                    "action_id": "",
                    "action_type": "completed",
                    "title": "表格填写完成",
                    "description": f"已成功填写模板 {template_content.get('filename', '')}",
                    "progress": 100,
                    "result": {
                        "output_path": fill_result.get("output_path", ""),
                        "output_filename": fill_result.get("output_filename", ""),
                        "filled_file_url": f"/api/v1/table-fill/download-file/{fill_result.get('output_filename', '')}",
                    }
                }
            }
        except Exception as e:
            logger.error(f"表格填写失败: error={e}")
            return {
                "success": False,
                "message": f"表格填写失败：{str(e)}",
                "action": {
                    "action_id": "",
                    "action_type": "failed",
                    "title": "表格填写失败",
                    "description": str(e)
                }
            }

    async def _execute_document_operation(
        self,
        documents_content: List[Dict[str, Any]],
        instruction: str
    ) -> Dict[str, Any]:
        try:
            if not documents_content:
                return {"success": False, "message": "请先选择要操作的文档。"}

            doc = documents_content[0]
            file_path = doc.get("file_path", "")
            file_type = doc.get("file_type", "")

            parser = self.parsers.get(file_type)
            if not parser:
                return {"success": False, "message": f"不支持的文件类型: {file_type}"}

            parsed_data = parser.parse(file_path)

            operation_result = await llm_service.document_operation(
                document_content=parsed_data.get("full_text", ""),
                instruction=instruction,
                document_type=file_type
            )

            return {
                "success": True,
                "message": operation_result.get("message", "操作完成"),
                "result": operation_result.get("result", ""),
            }
        except Exception as e:
            logger.error(f"文档操作失败: error={e}")
            return {"success": False, "message": f"文档操作失败：{str(e)}"}


document_agent = DocumentAgent()
