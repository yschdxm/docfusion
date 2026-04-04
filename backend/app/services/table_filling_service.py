"""表格填写服务 — 批量检索+提取管线

流程：
  1. 用表头作为 query 从源文档中批量提取所有记录
  2. 将记录逐行填入模板
  3. 已有数据的行用行上下文定位，逐一补全
"""
import asyncio
import hashlib
import logging
import os
from typing import List, Dict, Any
from uuid import uuid4

from app.services.llm_service import llm_service
from app.services.document_processor import DocxParser, XlsxParser
from app.services.rag_service import rag_service
from app.services.knowledge_graph_service import knowledge_graph_service
from app.services.sql_query_service import sql_query_service
from app.services.preprocessing_service import get_xlsx_schema_store
from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


class TableFillingService:
    PLACEHOLDER_VALUES = {
        "", "待填写", "待填", "n/a", "N/A", "na", "NA", "-", "--", "---",
        "无", "暂无", "未知", "TBD", "tbd", "null", "NULL", "None",
        "/", "不适用", "不涉及", "/ ", " /",
    }

    def __init__(self):
        self.parsers = {
            "docx": DocxParser(),
            "xlsx": XlsxParser()
        }

    # ──────────────────────────── 通用：按表填写 ────────────────────────────

    async def _fill_table_rows(
        self,
        table_data: List[List[Any]],
        doc_ids: List[str] = None,
        table_context: str = "",
    ) -> List[List[Any]]:
        """填写一个表格：优先 SQL 查询，不全则向量检索补充。"""
        if len(table_data) < 2:
            return [list(r) for r in table_data]

        headers = [str(cell).strip() if cell else "" for cell in table_data[0]]
        headers_str = "，".join([h for h in headers if h])

        # 分类行：全空行 vs 有数据的行
        empty_rows = []      # (row_idx, row)
        partial_rows = []    # (row_idx, row, empty_cols, row_context)

        for row_idx, row in enumerate(table_data[1:], start=1):
            empty_cols = []
            context_parts = []
            for col_idx, cell in enumerate(row):
                cell_text = str(cell).strip() if cell is not None else ""
                header = headers[col_idx] if col_idx < len(headers) and headers[col_idx] else f"列{col_idx}"
                if cell is None or cell_text == "" or cell_text in self.PLACEHOLDER_VALUES:
                    empty_cols.append((col_idx, header))
                else:
                    context_parts.append(f"{header}={cell_text}")
            if len(empty_cols) == len(row):
                empty_rows.append((row_idx, row))
            elif empty_cols:
                partial_rows.append((row_idx, row, empty_cols, "，".join(context_parts)))

        logger.debug("[FILL-TABLE] 分类: 全空行=%d, 部分空行=%d, 表头=%s",
                     len(empty_rows), len(partial_rows), headers_str[:80])

        records = []
        top_contexts = []

        if empty_rows:
            # Step 1: 尝试从 PostgreSQL 查询表结构，走 SQL 路径
            schema_text = await self._get_pg_schema(doc_ids or [])
            if schema_text:
                question = f"{table_context}\n需要填写的列：{headers_str}" if table_context else f"查询所有{headers_str}的数据"
                # 把模板表头传给 AI，让它建立表头→数据库列名的映射
                header_mapping = f"\n模板表头（可能与数据库列名有差异，如 PM2.5→PM2_5、二氧化硫→二氧化硫监测值）：{headers_str}"
                sql_rows = await sql_query_service.generate_and_execute(question, schema_text + header_mapping)
                if sql_rows:
                    records = sql_rows
                    logger.debug("[FILL-SQL] SQL 查询返回 %d 条记录", len(records))

            if not records:
                # Step 2: SQL 无结果，回退到向量检索 + LLM 提取
                query = table_context if table_context else headers_str
                all_results = await self._multi_path_retrieve(query=query, doc_ids=doc_ids)
                top_contexts = self._deduplicate(all_results)[:30]
                logger.debug("[FILL-TABLE] 向量检索返回 %d 条上下文", len(top_contexts))
                if top_contexts:
                    records = await llm_service.batch_extract_records(
                        table_headers=headers_str,
                        contexts=top_contexts,
                        table_context=table_context,
                    )
                    logger.debug("[FILL-TABLE] LLM批量提取到 %d 条记录", len(records))

        # Step 3: 填入全空行（从 records 中依次取），记录数超过空行数时自动扩展
        filled_rows = [list(table_data[0])]  # 表头行

        # 用 AI 建立模板表头 → 数据库列名的映射
        header_to_key = {}
        if records:
            db_columns = list(records[0].keys())
            template_headers = [h for h in headers if h]
            mapping_result = await llm_service.map_columns(template_headers, db_columns)
            header_to_key = mapping_result
            logger.debug("[FILL-TABLE] 列名映射: %s", header_to_key)

        # 如果记录数超过模板空行数，扩展空行
        num_cols = len(headers)
        while len(empty_rows) < len(records):
            empty_rows.append((len(table_data) + len(empty_rows), [None] * num_cols))

        record_idx = 0
        for row_idx, row in empty_rows:
            filled_row = list(row)
            if record_idx < len(records):
                record = records[record_idx]
                for col_idx, header in enumerate(headers):
                    key = header_to_key.get(header)
                    if key and key in record and record[key] is not None:
                        filled_row[col_idx] = str(record[key])
                record_idx += 1
            filled_rows.append(filled_row)

        # Step 4: 部分空行用行上下文逐一补全
        for row_idx, row, empty_cols, row_context in partial_rows:
            filled_row = list(row)
            extraction = await llm_service.extract_row_answers(
                table_headers=headers_str,
                row_context=row_context,
                empty_fields="，".join([h for _, h in empty_cols]),
                contexts=top_contexts if top_contexts else [],
            )
            answers = extraction.get("answers", {})
            for col_idx, header in empty_cols:
                value = answers.get(header)
                if value is not None:
                    filled_row[col_idx] = str(value)
            filled_rows.append(filled_row)

        return filled_rows

    # ──────────────────────────── Excel 填表 ────────────────────────────

    async def fill_table(
        self,
        source_files: List[Dict[str, str]],
        template_file: Dict[str, str],
        user_instruction: str,
        doc_ids: List[str] = None,
    ) -> Dict[str, Any]:
        """填写 Excel 表格。"""
        logger.debug("[FILL] fill_table 开始: source_files=%d, template=%s",
                     len(source_files), template_file.get("file_type"))
        template_parser = self.parsers.get(template_file.get("file_type"))
        if not template_parser:
            raise ValueError("Unsupported template file type")

        template_data = template_parser.parse(template_file.get("file_path"))
        sheets = template_data.get("sheets", [])

        if not sheets:
            raise ValueError("模板中没有找到 Sheet 数据")

        filled_data = {}
        for sheet in sheets:
            sheet_name = sheet.get("name", "Sheet1")
            data = sheet.get("data", [])
            if not data:
                continue
            filled_rows = await self._fill_table_rows(data, doc_ids)
            filled_data[sheet_name] = {"data": filled_rows}

        output_filename = f"filled_{uuid4().hex}.xlsx"
        output_path = os.path.join(settings.UPLOAD_DIR, "output", output_filename)
        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        XlsxParser.write_from_dict_on_template(filled_data, template_file.get("file_path"), output_path)

        return {
            "filled_data": filled_data,
            "output_path": output_path,
            "output_filename": output_filename,
        }

    # ──────────────────────────── Word 填表 ────────────────────────────

    async def fill_word_template(
        self,
        source_files: List[Dict[str, str]],
        template_file: Dict[str, str],
        user_instruction: str,
        doc_ids: List[str] = None,
    ) -> Dict[str, Any]:
        """填写 Word 模板中的表格。"""
        logger.debug("[FILL-WORD] fill_word_template 开始: source_files=%d, template=%s",
                      len(source_files), template_file.get("file_type"))

        template_parser = DocxParser()
        template_data = template_parser.parse(template_file.get("file_path"))
        template_tables = template_data.get("tables", [])
        table_contexts = template_data.get("table_contexts", [])
        logger.debug("[FILL-WORD] 模板解析: tables=%d", len(template_tables))

        filled_tables = []
        for table_idx, table in enumerate(template_tables):
            if not table:
                filled_tables.append([])
                continue
            ctx = table_contexts[table_idx] if table_idx < len(table_contexts) else ""
            logger.debug("[FILL-WORD] 表格 %d 上下文: %s", table_idx, ctx[:100])
            filled_rows = await self._fill_table_rows(table, doc_ids, table_context=ctx)
            filled_tables.append(filled_rows)

        logger.debug("[FILL-WORD] 填写完成: %d 个表格", len(filled_tables))

        output_filename = f"filled_{uuid4().hex}.docx"
        output_path = os.path.join(settings.UPLOAD_DIR, "output", output_filename)
        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        DocxParser.write_tables_on_template(filled_tables, template_file.get("file_path"), output_path)

        return {
            "filled_data": {"tables": filled_tables},
            "output_path": output_path,
            "output_filename": output_filename,
        }

    # ──────────────────────────── 检索工具方法 ────────────────────────────

    async def _get_pg_schema(self, doc_ids: List[str]) -> str:
        """直接从 PostgreSQL 查询表结构信息（不依赖 MongoDB）。"""
        if not doc_ids:
            return ""
        try:
            from app.db.postgres import engine
            from sqlalchemy import text

            # 找到 doc_id 对应的表名（表名以 doc_id 前8位开头）
            table_patterns = [f"{did[:8]}%" for did in doc_ids if len(did) >= 8]
            if not table_patterns:
                return ""

            async with engine.connect() as conn:
                # 查询匹配的表
                tables = []
                for pattern in table_patterns:
                    result = await conn.execute(
                        text("SELECT table_name FROM information_schema.tables WHERE table_schema='public' AND table_name LIKE :p"),
                        {"p": pattern}
                    )
                    tables.extend([r[0] for r in result.fetchall()])

                if not tables:
                    return ""

                # 查询每个表的列信息
                schema_lines = []
                for table_name in tables:
                    result = await conn.execute(
                        text("SELECT column_name, data_type FROM information_schema.columns WHERE table_schema='public' AND table_name=:t ORDER BY ordinal_position"),
                        {"t": table_name}
                    )
                    cols = result.fetchall()
                    col_descs = [f"{c[0]}({c[1]})" for c in cols]
                    schema_lines.append(f"表 {table_name}: {', '.join(col_descs)}")

                return "\n".join(schema_lines)
        except Exception as e:
            logger.warning("查询 PG schema 失败: %s", e)
            return ""

    async def _multi_path_retrieve(
        self,
        query: str,
        doc_ids: List[str] = None,
    ) -> List[Dict[str, Any]]:
        """三路并行检索：向量 / 图谱 / SQL。"""
        tasks = [
            self._vector_search(query, doc_ids),
            self._graph_search(query, doc_ids),
        ]

        schema_store = get_xlsx_schema_store()
        if schema_store:
            tasks.append(self._sql_search(query, doc_ids, schema_store))

        results_list = await asyncio.gather(*tasks, return_exceptions=True)

        all_results = []
        for results in results_list:
            if isinstance(results, Exception):
                logger.warning("检索异常: %s", results)
                continue
            if isinstance(results, list):
                all_results.extend(results)

        return all_results

    async def _vector_search(self, query: str, doc_ids: List[str] = None) -> List[Dict[str, Any]]:
        try:
            results = await rag_service.search_for_field(query=query, doc_ids=doc_ids, top_k=30)
            return [{"content": r["content"], "source": "vector", "score": r.get("score", 0)} for r in results]
        except Exception as e:
            logger.warning("向量检索失败: %s", e)
            return []

    async def _graph_search(self, query: str, doc_ids: List[str] = None) -> List[Dict[str, Any]]:
        try:
            entity_names = [w for w in query.split() if len(w) >= 2]
            results = await knowledge_graph_service.query_for_field(
                field_name=query, entity_names=entity_names, doc_ids=doc_ids,
            )
            return [{"content": r["content"], "source": "graph"} for r in results]
        except Exception as e:
            logger.warning("图谱查询失败: %s", e)
            return []

    async def _sql_search(self, query: str, doc_ids: List[str] = None, schema_store: Dict[str, Any] = None) -> List[Dict[str, Any]]:
        try:
            results = await sql_query_service.query_for_field(
                field_name=query, row_context="", schema_store=schema_store, doc_ids=doc_ids,
            )
            return [{"content": r["content"], "source": "sql"} for r in results]
        except Exception as e:
            logger.warning("SQL 查询失败: %s", e)
            return []

    @staticmethod
    def _deduplicate(all_results: List[Dict[str, Any]]) -> List[str]:
        """按 MD5 去重，返回去重后的上下文文本列表。"""
        if not all_results:
            return []
        seen = set()
        unique = []
        for r in all_results:
            content = r.get("content", "")
            if not content:
                continue
            h = hashlib.md5(content.encode()).hexdigest()
            if h not in seen:
                seen.add(h)
                unique.append(content)
        return unique

    # ──────────────────────────── 自动填表（RAG 选文档） ────────────────────────────

    async def auto_fill_table(
        self,
        template_file: Dict[str, str],
        user_instruction: str = "",
        max_docs: int = 5
    ) -> Dict[str, Any]:
        """自动选择文档并填写表格。"""
        logger.debug("[FILL-AUTO] auto_fill_table 开始: template=%s", template_file.get("file_type"))
        template_parser = self.parsers.get(template_file.get("file_type"))
        if not template_parser:
            raise ValueError("Unsupported template file type")

        template_data = template_parser.parse(template_file.get("file_path"))
        template_content = template_data.get("full_text", "")

        selected_doc_ids = await rag_service.auto_select_documents(
            template_content=template_content,
            template_structure=template_data,
            max_docs=max_docs
        )
        logger.debug("[FILL-AUTO] RAG 自动选择文档: %s", selected_doc_ids)

        if not selected_doc_ids:
            raise ValueError("未找到相关文档，请手动选择源文档")

        from app.db.postgres import engine as pg_engine
        from app.models.document import Document
        from sqlalchemy import select
        from sqlalchemy.ext.asyncio import async_sessionmaker

        AsyncSessionLocal = async_sessionmaker(pg_engine, expire_on_commit=False)
        source_files = []

        async with AsyncSessionLocal() as db:
            for doc_id_str in selected_doc_ids:
                try:
                    from uuid import UUID as UuidCls
                    try:
                        doc_uuid = UuidCls(doc_id_str)
                    except ValueError:
                        continue
                    result = await db.execute(select(Document).where(Document.id == doc_uuid))
                    doc = result.scalar_one_or_none()
                    if doc and doc.file_path:
                        source_files.append({"file_type": doc.file_type, "file_path": doc.file_path})
                except Exception:
                    continue

        if not source_files:
            raise ValueError("无法获取文档内容，请确保已上传源文档")

        if template_file.get("file_type") == "xlsx":
            return await self.fill_table(
                source_files=source_files,
                template_file=template_file,
                user_instruction=user_instruction or "根据模板结构填写数据",
                doc_ids=selected_doc_ids,
            )
        else:
            return await self.fill_word_template(
                source_files=source_files,
                template_file=template_file,
                user_instruction=user_instruction or "根据模板结构填写数据",
                doc_ids=selected_doc_ids,
            )


table_filling_service = TableFillingService()
