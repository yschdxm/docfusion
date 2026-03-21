from typing import List, Dict, Any, Optional
from uuid import UUID, uuid4
import os
from app.services.llm_service import llm_service
from app.services.document_processor import DocxParser, XlsxParser
from app.core.config import get_settings

settings = get_settings()


class TableFillingService:
    def __init__(self):
        self.parsers = {
            "docx": DocxParser(),
            "xlsx": XlsxParser()
        }
    
    async def fill_table(
        self,
        source_files: List[Dict[str, str]],
        template_file: Dict[str, str],
        user_instruction: str
    ) -> Dict[str, Any]:
        all_source_text = []
        for source in source_files:
            file_type = source.get("file_type")
            file_path = source.get("file_path")
            
            parser = self.parsers.get(file_type)
            if parser:
                parsed = parser.parse(file_path)
                all_source_text.append(parsed.get("full_text", ""))
        
        combined_source = "\n\n---\n\n".join(all_source_text)
        
        template_parser = self.parsers.get(template_file.get("file_type"))
        if not template_parser:
            raise ValueError("Unsupported template file type")
        
        template_data = template_parser.parse(template_file.get("file_path"))
        
        filled_data = await llm_service.extract_table_data(
            source_text=combined_source,
            template_structure=template_data,
            user_instruction=user_instruction
        )
        
        output_filename = f"filled_{uuid4().hex}.xlsx"
        output_path = os.path.join(settings.UPLOAD_DIR, "output", output_filename)
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        
        XlsxParser.write_from_dict(filled_data, output_path)
        
        return {
            "filled_data": filled_data,
            "output_path": output_path,
            "output_filename": output_filename
        }
    
    async def fill_word_template(
        self,
        source_files: List[Dict[str, str]],
        template_file: Dict[str, str],
        user_instruction: str
    ) -> Dict[str, Any]:
        all_source_text = []
        for source in source_files:
            file_type = source.get("file_type")
            file_path = source.get("file_path")
            
            if file_type == "xlsx":
                parser = XlsxParser()
                parsed = parser.parse(file_path)
                all_source_text.append(parsed.get("full_text", ""))
            else:
                parser = DocxParser()
                parsed = parser.parse(file_path)
                all_source_text.append(parsed.get("full_text", ""))
        
        combined_source = "\n\n---\n\n".join(all_source_text)
        
        template_parser = DocxParser()
        template_data = template_parser.parse(template_file.get("file_path"))
        
        prompt = f"""根据源文档内容，填写Word模板。

用户指令：
{user_instruction}

模板内容：
{template_data.get("full_text", "")[:3000]}

源文档内容（部分）：
{combined_source[:6000]}

请返回需要填写的内容，格式为JSON：
```json
{{
    "sections": [
        {{
            "title": "章节标题",
            "content": "填写的内容"
        }}
    ]
}}
```

只返回JSON。"""
        
        messages = [{"role": "user", "content": prompt}]
        response = await llm_service.chat_completion(messages, temperature=0.3)
        
        import json
        try:
            json_str = response.strip()
            if "```json" in json_str:
                json_str = json_str.split("```json")[1].split("```")[0].strip()
            fill_data = json.loads(json_str)
        except:
            fill_data = {"sections": [{"title": "Result", "content": response}]}
        
        output_filename = f"filled_{uuid4().hex}.docx"
        output_path = os.path.join(settings.UPLOAD_DIR, "output", output_filename)
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        
        filled_content = "\n\n".join([
            f"{s.get('title', '')}\n{s.get('content', '')}"
            for s in fill_data.get("sections", [])
        ])
        
        DocxParser.write(filled_content, output_path)
        
        return {
            "filled_data": fill_data,
            "output_path": output_path,
            "output_filename": output_filename
        }


table_filling_service = TableFillingService()
