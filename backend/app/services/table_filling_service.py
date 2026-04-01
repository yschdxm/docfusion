from typing import List, Dict, Any, Optional
from uuid import UUID, uuid4
import os
import logging
from app.services.llm_service import llm_service
from app.services.document_processor import DocxParser, XlsxParser, MdParser, TxtParser
from app.services.rag_service import rag_service
from app.db.neo4j_db import run_cypher
from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


class TableFillingService:
    def __init__(self):
        self.parsers = {
            "docx": DocxParser(),
            "xlsx": XlsxParser(),
            "md": MdParser(),
            "txt": TxtParser()
        }
    
    async def get_entities_from_neo4j(
        self,
        document_ids: List[str],
        entity_types: Optional[List[str]] = None
    ) -> List[Dict[str, Any]]:
        """从Neo4j获取指定文档的实体数据"""
        if not document_ids:
            return []
        
        if entity_types:
            result = await run_cypher(
                """
                MATCH (d:Document)-[:HAS_ENTITY]->(e:Entity)
                WHERE d.id IN $doc_ids AND e.type IN $entity_types
                RETURN e.name AS name, e.type AS type, e.value AS value, e.context AS context
                """,
                {"doc_ids": document_ids, "entity_types": entity_types}
            )
        else:
            result = await run_cypher(
                """
                MATCH (d:Document)-[:HAS_ENTITY]->(e:Entity)
                WHERE d.id IN $doc_ids
                RETURN e.name AS name, e.type AS type, e.value AS value, e.context AS context
                """,
                {"doc_ids": document_ids}
            )
        
        return [
            {
                "entity_name": r["name"],
                "entity_type": r["type"],
                "entity_value": r.get("value", ""),
                "context": r.get("context", "")
            }
            for r in result
        ]
    
    async def fill_table_from_entities(
        self,
        document_ids: List[str],
        template_file: Dict[str, str],
        user_instruction: str,
        entity_types: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """使用Neo4j中的实体数据填写表格"""
        # 从Neo4j获取实体数据
        entities = await self.get_entities_from_neo4j(document_ids, entity_types)
        
        if not entities:
            raise ValueError("未找到实体数据，请先进行信息提取")
        
        # 构建实体数据文本
        entities_text = "\n".join([
            f"- {e['entity_type']}: {e['entity_name']} = {e['entity_value']} (上下文: {e['context'][:100]})"
            for e in entities
        ])
        
        # 解析模板
        template_parser = self.parsers.get(template_file.get("file_type"))
        if not template_parser:
            raise ValueError("Unsupported template file type")
        
        template_data = template_parser.parse(template_file.get("file_path"))
        
        # 使用LLM提取表格数据
        filled_data = await llm_service.extract_table_data(
            source_text=entities_text,
            template_structure=template_data,
            user_instruction=user_instruction
        )
        
        # 生成输出文件
        output_filename = f"filled_{uuid4().hex}.xlsx"
        output_path = os.path.join(settings.UPLOAD_DIR, "output", output_filename)
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        
        XlsxParser.write_from_dict(filled_data, output_path)
        
        return {
            "filled_data": filled_data,
            "output_path": output_path,
            "output_filename": output_filename,
            "entities_used": len(entities)
        }
    
    async def fill_table(
        self,
        source_files: List[Dict[str, str]],
        template_file: Dict[str, str],
        user_instruction: str
    ) -> Dict[str, Any]:
        """
        填写Excel表格模板

        根据源文档类型采用不同策略：
        1. Word/md/txt源文档：完全读取原文档，分块处理（256k上下文）
        2. Excel源文档：使用Neo4j中的结构化数据，不读取原文档
        """
        # 检查源文档类型
        has_excel_source = any(s.get("file_type") == "xlsx" for s in source_files)
        has_text_source = any(s.get("file_type") in ["docx", "md", "txt"] for s in source_files)

        source_text = ""
        entities_used = 0

        if has_excel_source and not has_text_source:
            # 只有Excel源文档：使用Neo4j中的结构化数据
            logger.info("源文档为Excel，使用Neo4j中的结构化数据")

            # 获取文档ID
            from app.db.postgres import engine
            from app.models.document import Document
            from sqlalchemy import select
            from sqlalchemy.ext.asyncio import async_sessionmaker

            AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)
            document_ids = []

            async with AsyncSessionLocal() as db:
                for source in source_files:
                    if source.get("file_type") == "xlsx":
                        # 通过文件路径查找文档ID
                        result = await db.execute(
                            select(Document.id).where(Document.file_path == source.get("file_path"))
                        )
                        doc_id = result.scalar_one_or_none()
                        if doc_id:
                            document_ids.append(str(doc_id))

            if document_ids:
                entities = await self.get_entities_from_neo4j(document_ids)
                if entities:
                    # 构建实体数据文本
                    source_text = "\n".join([
                        f"- {e['entity_type']}: {e['entity_name']} = {e['entity_value']} (上下文: {e['context'][:100]})"
                        for e in entities
                    ])
                    entities_used = len(entities)
                    logger.info(f"从Neo4j获取到 {entities_used} 个实体")
                else:
                    logger.warning("Neo4j中未找到实体数据，将读取Excel文件内容")
                    source_text = self._read_source_files(source_files)
            else:
                logger.warning("无法找到文档ID，将读取Excel文件内容")
                source_text = self._read_source_files(source_files)
        else:
            # Word/md/txt源文档或混合类型：读取原文档内容
            logger.info("源文档为Word/md/txt或混合类型，读取原文档内容")
            source_text = self._read_source_files(source_files)

        # 解析模板
        template_parser = self.parsers.get(template_file.get("file_type"))
        if not template_parser:
            raise ValueError("Unsupported template file type")

        template_data = template_parser.parse(template_file.get("file_path"))

        # 使用LLM提取表格数据
        filled_data = await llm_service.extract_table_data(
            source_text=source_text,
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
            "output_filename": output_filename,
            "entities_used": entities_used
        }

    def _read_source_files(self, source_files: List[Dict[str, str]]) -> str:
        """读取源文件内容"""
        all_source_text = []
        for source in source_files:
            file_type = source.get("file_type")
            file_path = source.get("file_path")

            parser = self.parsers.get(file_type)
            if parser:
                try:
                    parsed = parser.parse(file_path)
                    all_source_text.append(parsed.get("full_text", ""))
                except Exception as e:
                    logger.warning(f"解析文件失败 {file_path}: {e}")

        return "\n\n---\n\n".join(all_source_text)
    
    async def fill_word_template(
        self,
        source_files: List[Dict[str, str]],
        template_file: Dict[str, str],
        user_instruction: str
    ) -> Dict[str, Any]:
        """
        填写Word模板

        根据源文档类型采用不同策略：
        1. Word/md/txt源文档：完全读取原文档，分块处理（256k上下文）
        2. Excel源文档：使用Neo4j中的结构化数据，不读取原文档
        """
        # 检查源文档类型
        has_excel_source = any(s.get("file_type") == "xlsx" for s in source_files)
        has_text_source = any(s.get("file_type") in ["docx", "md", "txt"] for s in source_files)

        source_text = ""
        entities_used = 0

        if has_excel_source and not has_text_source:
            # 只有Excel源文档：使用Neo4j中的结构化数据
            logger.info("源文档为Excel，使用Neo4j中的结构化数据")

            # 获取文档ID
            from app.db.postgres import engine
            from app.models.document import Document
            from sqlalchemy import select
            from sqlalchemy.ext.asyncio import async_sessionmaker

            AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)
            document_ids = []

            async with AsyncSessionLocal() as db:
                for source in source_files:
                    if source.get("file_type") == "xlsx":
                        # 通过文件路径查找文档ID
                        result = await db.execute(
                            select(Document.id).where(Document.file_path == source.get("file_path"))
                        )
                        doc_id = result.scalar_one_or_none()
                        if doc_id:
                            document_ids.append(str(doc_id))

            if document_ids:
                entities = await self.get_entities_from_neo4j(document_ids)
                if entities:
                    # 构建实体数据文本
                    source_text = "\n".join([
                        f"- {e['entity_type']}: {e['entity_name']} = {e['entity_value']} (上下文: {e['context'][:100]})"
                        for e in entities
                    ])
                    entities_used = len(entities)
                    logger.info(f"从Neo4j获取到 {entities_used} 个实体")
                else:
                    logger.warning("Neo4j中未找到实体数据，将读取Excel文件内容")
                    source_text = self._read_source_files(source_files)
            else:
                logger.warning("无法找到文档ID，将读取Excel文件内容")
                source_text = self._read_source_files(source_files)
        else:
            # Word/md/txt源文档或混合类型：读取原文档内容
            logger.info("源文档为Word/md/txt或混合类型，读取原文档内容")
            source_text = self._read_source_files(source_files)

        # 解析模板
        template_parser = DocxParser()
        template_data = template_parser.parse(template_file.get("file_path"))

        # MiMo-V2-Flash 支持 256K 上下文
        # 分块处理：每块 200K 字符，重叠 10K 字符
        CHUNK_SIZE = 200000
        OVERLAP_SIZE = 10000

        if len(source_text) <= CHUNK_SIZE:
            # 文本较短，直接处理
            prompt = f"""根据源文档内容，填写Word模板。

用户指令：
{user_instruction}

模板内容：
{template_data.get("full_text", "")[:50000]}

源文档内容：
{source_text}

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
        else:
            # 文本较长，分块处理
            logger.info(f"源文档较长 ({len(source_text)} 字符)，分块处理")
            chunks = []
            start = 0
            while start < len(source_text):
                end = min(start + CHUNK_SIZE, len(source_text))
                chunks.append(source_text[start:end])
                if end >= len(source_text):
                    break
                start = end - OVERLAP_SIZE
                if start < 0:
                    start = 0

            logger.info(f"分成 {len(chunks)} 块处理")

            # 逐块处理并汇总结果
            all_sections = []
            for idx, chunk in enumerate(chunks):
                logger.info(f"处理第 {idx + 1}/{len(chunks)} 块...")
                prompt = f"""根据源文档内容，填写Word模板。

用户指令：
{user_instruction}

模板内容：
{template_data.get("full_text", "")[:50000]}

源文档内容（第 {idx + 1}/{len(chunks)} 块）：
{chunk}

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

                try:
                    json_str = response.strip()
                    if "```json" in json_str:
                        json_str = json_str.split("```json")[1].split("```")[0].strip()
                    chunk_data = json.loads(json_str)
                    if "sections" in chunk_data:
                        all_sections.extend(chunk_data["sections"])
                except Exception as e:
                    logger.warning(f"解析第 {idx + 1} 块结果失败: {e}")

            fill_data = {"sections": all_sections}

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
            "output_filename": output_filename,
            "entities_used": entities_used
        }
    
    async def auto_fill_table(
        self,
        template_file: Dict[str, str],
        user_instruction: str = "",
        max_docs: int = 5
    ) -> Dict[str, Any]:
        """
        自动选择文档并填写表格

        使用RAG服务找到与模板最相关的文档，然后填写表格
        """
        logger.info(f"开始自动填写表格，模板: {template_file}")

        # 解析模板
        template_parser = self.parsers.get(template_file.get("file_type"))
        if not template_parser:
            raise ValueError("Unsupported template file type")

        template_data = template_parser.parse(template_file.get("file_path"))
        template_content = template_data.get("full_text", "")

        logger.info(f"模板内容长度: {len(template_content)}")

        # 使用RAG服务找到相关文档
        logger.info("调用RAG服务查找相关文档...")
        selected_doc_ids = await rag_service.auto_select_documents(
            template_content=template_content,
            template_structure=template_data,
            max_docs=max_docs
        )

        logger.info(f"RAG返回的文档ID: {selected_doc_ids}")

        if not selected_doc_ids:
            raise ValueError("未找到相关文档，请手动选择源文档")

        # 获取文档内容
        from app.db.postgres import engine
        from app.models.document import Document
        from sqlalchemy import select
        from sqlalchemy.ext.asyncio import async_sessionmaker

        AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)
        source_files = []

        async with AsyncSessionLocal() as db:
            for doc_id in selected_doc_ids:
                try:
                    # 验证UUID格式
                    from uuid import UUID
                    try:
                        doc_uuid = UUID(doc_id)
                    except ValueError:
                        logger.warning(f"无效的文档ID格式: {doc_id}")
                        continue

                    result = await db.execute(select(Document).where(Document.id == doc_uuid))
                    doc = result.scalar_one_or_none()
                    if doc and doc.file_path:
                        source_files.append({
                            "file_type": doc.file_type,
                            "file_path": doc.file_path
                        })
                        logger.info(f"找到文档: {doc.original_filename}")
                except Exception as e:
                    logger.warning(f"获取文档 {doc_id} 失败: {e}")

        if not source_files:
            raise ValueError("无法获取文档内容，请确保已上传源文档")

        logger.info(f"共找到 {len(source_files)} 个源文档")

        # 根据模板文档类型调用对应方法
        # 检查模板是否是Excel文档
        is_excel_template = template_file.get("file_type") == "xlsx"

        if is_excel_template:
            # Excel模板，调用fill_table
            return await self.fill_table(
                source_files=source_files,
                template_file=template_file,
                user_instruction=user_instruction or "根据模板结构填写数据"
            )
        else:
            # Word模板，调用fill_word_template
            return await self.fill_word_template(
                source_files=source_files,
                template_file=template_file,
                user_instruction=user_instruction or "根据模板结构填写数据"
            )


table_filling_service = TableFillingService()
