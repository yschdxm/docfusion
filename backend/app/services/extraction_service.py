from typing import List, Dict, Any, Optional
from uuid import UUID
import asyncio
from app.services.llm_service import llm_service
from app.services.document_processor import DocxParser, XlsxParser, MdParser, TxtParser
from app.db.mongodb import get_collection


class ExtractionService:
    def __init__(self):
        self.parsers = {
            "docx": DocxParser(),
            "xlsx": XlsxParser(),
            "md": MdParser(),
            "txt": TxtParser()
        }
    
    async def extract_from_document(
        self,
        file_path: str,
        file_type: str,
        entity_types: Optional[List[str]] = None,
        custom_fields: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        parser = self.parsers.get(file_type)
        if not parser:
            raise ValueError(f"Unsupported file type: {file_type}")
        
        parsed_data = parser.parse(file_path)
        full_text = parsed_data.get("full_text", "")
        
        # 根据 MiMo-V2-Flash 能力（256K上下文，10M TPM）设置更大的块大小
        if len(full_text) > 100000:
            chunks = [full_text[i:i+80000] for i in range(0, len(full_text), 80000)]
            all_entities = []
            
            for chunk in chunks:
                try:
                    entities = await llm_service.extract_entities(chunk, entity_types)
                    all_entities.extend(entities)
                except Exception as e:
                    print(f"Chunk extraction error: {e}")
                    continue
        else:
            all_entities = await llm_service.extract_entities(full_text, entity_types)
        
        if custom_fields:
            custom_entities = await self._extract_custom_fields(full_text[:50000], custom_fields)
            all_entities.extend(custom_entities)
        
        tables = parsed_data.get("tables", [])
        if tables:
            table_entities = self._extract_table_entities(tables)
            all_entities.extend(table_entities)
        
        unique_entities = []
        seen = set()
        for entity in all_entities:
            key = (entity.get("entity_type"), entity.get("entity_name"))
            if key not in seen:
                seen.add(key)
                unique_entities.append(entity)
        
        return {
            "entities": unique_entities,
            "tables": tables,
            "parsed_data": parsed_data
        }
    
    async def _extract_custom_fields(
        self,
        text: str,
        custom_fields: List[str]
    ) -> List[Dict[str, Any]]:
        # MiMo-V2-Flash 支持 256K 上下文
        prompt = f"""从文本中提取以下自定义字段的信息：

自定义字段：
{chr(10).join([f"- {field}" for field in custom_fields])}

文本内容：
{text[:50000]}

请返回JSON格式：
```json
[
    {{
        "entity_type": "CUSTOM",
        "entity_name": "字段名",
        "entity_value": "提取的值",
        "context": "原文上下文"
    }}
]
```

只返回JSON。"""
        
        messages = [{"role": "user", "content": prompt}]
        response = await llm_service.chat_completion(messages, temperature=0.3)
        
        import json
        try:
            json_str = response.strip()
            if "```json" in json_str:
                json_str = json_str.split("```json")[1].split("```")[0].strip()
            return json.loads(json_str)
        except:
            return []
    
    def _extract_table_entities(self, tables: List[List[List[str]]]) -> List[Dict[str, Any]]:
        entities = []
        for i, table in enumerate(tables):
            if not table:
                continue
            
            headers = table[0] if table else []
            for row in table[1:]:
                for j, cell in enumerate(row):
                    if cell and cell.strip():
                        header = headers[j] if j < len(headers) else f"Column_{j}"
                        entities.append({
                            "entity_type": "TABLE_DATA",
                            "entity_name": header,
                            "entity_value": cell,
                            "context": f"Table {i+1}, Row data"
                        })
        return entities
    
    async def save_to_mongodb(
        self,
        document_id: UUID,
        extraction_result: Dict[str, Any]
    ):
        collection = get_collection("extractions")
        await collection.update_one(
            {"document_id": str(document_id)},
            {
                "$set": {
                    "document_id": str(document_id),
                    "entities": extraction_result.get("entities", []),
                    "tables": extraction_result.get("tables", []),
                    "updated_at": asyncio.get_event_loop().time()
                }
            },
            upsert=True
        )


extraction_service = ExtractionService()
