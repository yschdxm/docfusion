from typing import Dict, Any, Optional
from uuid import UUID
from app.services.llm_service import llm_service
from app.services.document_processor import DocxParser, XlsxParser, MdParser, TxtParser
from app.core.config import get_settings
import os

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
        file_path: str,
        file_type: str,
        instruction: str,
        output_format: Optional[str] = None
    ) -> Dict[str, Any]:
        parser = self.parsers.get(file_type)
        if not parser:
            raise ValueError(f"Unsupported file type: {file_type}")
        
        parsed_data = parser.parse(file_path)
        full_text = parsed_data.get("full_text", "")
        
        operation_result = await llm_service.document_operation(
            document_content=full_text,
            instruction=instruction,
            document_type=file_type
        )
        
        result = operation_result.get("result", "")
        operation_type = operation_result.get("operation_type", "query")
        
        output_file = None
        if operation_type in ["format", "convert", "edit"] and output_format:
            output_file = await self._generate_output(
                result, output_format, parsed_data
            )
        
        return {
            "operation_type": operation_type,
            "result": result,
            "success": operation_result.get("success", True),
            "message": operation_result.get("message", "操作完成"),
            "output_file": output_file
        }
    
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
                XlsxParser.write(original_data["tables"][0], output_path)
        
        return output_path
    
    async def convert_document(
        self,
        file_path: str,
        source_format: str,
        target_format: str
    ) -> str:
        parser = self.parsers.get(source_format)
        if not parser:
            raise ValueError(f"Unsupported source format: {source_format}")
        
        parsed_data = parser.parse(file_path)
        content = parsed_data.get("full_text", "")
        
        import uuid
        output_filename = f"converted_{uuid.uuid4().hex}.{target_format}"
        output_path = os.path.join(settings.UPLOAD_DIR, "output", output_filename)
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        
        target_parser = self.parsers.get(target_format)
        if target_format == "docx":
            DocxParser.write(content, output_path, parsed_data)
        elif target_format == "md":
            MdParser.write(content, output_path)
        elif target_format == "txt":
            TxtParser.write(content, output_path)
        
        return output_path


document_agent = DocumentAgent()
