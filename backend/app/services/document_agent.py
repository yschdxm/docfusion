from typing import Dict, Any, Optional, List
from uuid import UUID, uuid4
from app.services.llm_service import llm_service
from app.services.table_filling_service import table_filling_service
from app.services.document_processor import DocxParser, XlsxParser, MdParser, TxtParser
from app.core.config import get_settings
import os
import logging

logger = logging.getLogger(__name__)
settings = get_settings()


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
        """
        统一处理指令入口
        根据intent或action_id调用对应的服务
        """
        try:
            if action_id:
                if action_id.startswith("fill-"):
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
        """执行表格填写（调用table_filling_service）"""
        try:
            if not template_content:
                return {"success": False, "message": "缺少模板文件。"}

            template_file = {"file_type": template_content["file_type"], "file_path": template_content.get("file_path", "")}

            # 如果没有选择文档，使用RAG自动选择
            if not documents_content:
                fill_result = await table_filling_service.auto_fill_table(
                    template_file=template_file,
                    user_instruction=instruction
                )
            else:
                source_files = [{"file_type": d["file_type"], "file_path": d.get("file_path", "")} for d in documents_content]

                # 根据源文档类型判断，而不是模板类型
                # 检查是否有Excel源文档
                has_excel_source = any(s.get("file_type") == "xlsx" for s in source_files)

                if has_excel_source:
                    # 有Excel源文档，调用fill_table
                    fill_result = await table_filling_service.fill_table(
                        source_files=source_files,
                        template_file=template_file,
                        user_instruction=instruction
                    )
                else:
                    # 只有非Excel源文档，调用fill_word_template
                    fill_result = await table_filling_service.fill_word_template(
                        source_files=source_files,
                        template_file=template_file,
                        user_instruction=instruction
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
                        "entities_used": fill_result.get("entities_used", 0)
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
        """执行文档操作（格式转换、编辑等）"""
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
            
            result = operation_result.get("result", "")
            operation_type = operation_result.get("operation_type", "query")
            
            output_file = None
            if operation_type in ["format", "convert", "edit"]:
                output_format = "docx" if file_type == "docx" else file_type
                output_file = await self._generate_output(result, output_format, parsed_data)
            
            return {
                "success": True,
                "message": operation_result.get("message", "操作完成"),
                "result": result,
                "output_file": output_file
            }
        except Exception as e:
            logger.error(f"文档操作失败: error={e}")
            return {"success": False, "message": f"文档操作失败：{str(e)}"}
    
    async def _generate_output(
        self,
        content: str,
        output_format: str,
        original_data: Dict[str, Any]
    ) -> str:
        import uuid
        output_filename = f"output_{uuid.uuid4().hex}.{output_format}"
        output_path = os.path.join(settings.UPLOAD_DIR, "output", output_filename)
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        
        if output_format == "docx":
            DocxParser.write(content, output_path, original_data)
        elif output_format == "md":
            MdParser.write(content, output_path)
        elif output_format == "txt":
            TxtParser.write(content, output_path)
        elif output_format == "xlsx":
            if "tables" in original_data and original_data["tables"]:
                if len(original_data["tables"]) == 1:
                    XlsxParser.write(original_data["tables"][0], output_path)
                else:
                    workbook_data = {}
                    for idx, table in enumerate(original_data["tables"]):
                        sheet_name = f"表格{idx + 1}"
                        workbook_data[sheet_name] = {"data": table}
                    XlsxParser.write_from_dict(workbook_data, output_path)
        
        return output_path


document_agent = DocumentAgent()
