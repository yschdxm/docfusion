"""SQL 查询服务 — 针对 xlsx 入 PostgreSQL 的数据执行精确查询"""
import logging
from typing import List, Dict, Any
from app.services.llm_service import llm_service
from app.db.postgres import engine
from sqlalchemy import text

logger = logging.getLogger(__name__)


class SQLQueryService:

    async def _get_table_info(self, doc_ids: List[str]) -> List[Dict[str, Any]]:
        """根据doc_ids获取对应的PostgreSQL表信息。

        Returns:
            [{"table_name": str, "columns": [{"name": str, "type": str}], "sample_data": [...]}]
        """
        if not doc_ids:
            logger.warning("[_get_table_info] doc_ids为空")
            return []

        try:
            from app.db.postgres import engine
            from sqlalchemy import text

            # 找到 doc_id 对应的表名（表名以 doc_id 前8位开头）
            table_patterns = [f"{did[:8]}%" for did in doc_ids if len(did) >= 8]
            logger.info(f"[_get_table_info] doc_ids={doc_ids}, 生成的表名模式={table_patterns}")
            if not table_patterns:
                logger.warning("[_get_table_info] 无法生成表名模式，doc_id可能太短")
                return []

            tables_info = []
            async with engine.connect() as conn:
                for pattern in table_patterns:
                    # 查询匹配的表
                    result = await conn.execute(
                        text("SELECT table_name FROM information_schema.tables WHERE table_schema='public' AND table_name LIKE :p"),
                        {"p": pattern}
                    )
                    table_names = [r[0] for r in result.fetchall()]
                    logger.info(f"[_get_table_info] 模式'{pattern}'匹配到的表: {table_names}")

                    for table_name in table_names:
                        # 查询列信息
                        col_result = await conn.execute(
                            text("SELECT column_name, data_type FROM information_schema.columns WHERE table_schema='public' AND table_name=:t ORDER BY ordinal_position"),
                            {"t": table_name}
                        )
                        columns = [{"name": c[0], "type": c[1]} for c in col_result.fetchall()]

                        # 获取采样数据（3行）
                        sample_data = []
                        try:
                            col_names = [f'"{c["name"]}"' for c in columns]
                            sample_result = await conn.execute(
                                text(f"SELECT {', '.join(col_names)} FROM \"{table_name}\" LIMIT 3")
                            )
                            for row in sample_result.fetchall():
                                sample_data.append(dict(zip([c["name"] for c in columns], row)))
                        except Exception as e:
                            logger.warning(f"获取采样数据失败: {table_name}, {e}")

                        tables_info.append({
                            "table_name": table_name,
                            "columns": columns,
                            "sample_data": sample_data
                        })

            return tables_info
        except Exception as e:
            logger.warning("获取表信息失败: %s", e)
            return []

    async def get_schema_for_doc(self, doc_id: str, schema_store: Dict[str, Any] = None) -> str:
        """获取文档对应的表结构信息（用于 LLM 生成 SQL）。

        Args:
            doc_id: 文档 ID
            schema_store: 预处理时存储的 schema 信息 {doc_id: [{table_name, columns, ...}]}
        """
        if not schema_store:
            return ""

        schemas = schema_store.get(doc_id, [])
        if not schemas:
            return ""

        lines = []
        for schema in schemas:
            table_name = schema.get("table_name", "")
            sheet_name = schema.get("sheet_name", "")
            columns = schema.get("columns", [])
            row_count = schema.get("row_count", 0)

            col_lines = []
            for col in columns:
                col_lines.append(f"  - {col['name']} ({col['type']})")

            lines.append(f"表名: {table_name}（来源 Sheet: {sheet_name}，共 {row_count} 行）")
            lines.append("列:")
            lines.extend(col_lines)
            lines.append("")

        return "\n".join(lines)

    async def _get_actual_columns(self, schema_info: str) -> List[str]:
        """从 schema_info 中提取表名，查询 PostgreSQL 实际列名和采样数据。"""
        import re
        table_match = re.search(r'表\s+([\w]+)', schema_info)
        if not table_match:
            return []
        table_name = table_match.group(1)
        try:
            async with engine.connect() as conn:
                result = await conn.execute(
                    text("SELECT column_name, data_type FROM information_schema.columns WHERE table_schema='public' AND table_name=:t ORDER BY ordinal_position"),
                    {"t": table_name}
                )
                cols = result.fetchall()
                col_names = [f'"{c[0]}"' for c in cols]

                # 取1行采样数据，让 AI 知道各列的实际格式
                col_list = ", ".join(col_names)
                try:
                    sample = await conn.execute(text(f'SELECT {col_list} FROM "{table_name}" LIMIT 1'))
                    row = sample.fetchone()
                    if row:
                        col_names.append("-- 采样数据（参考格式）：")
                        for i, col in enumerate(cols):
                            col_names.append(f'--   "{col[0]}" = {repr(row[i])}')
                except Exception:
                    pass

                return col_names
        except Exception:
            return []

    async def generate_and_execute_once(
        self,
        question: str,
        schema_info: str = "",
        doc_ids: List[str] = None,
        previous_error: str = "",
    ) -> Dict[str, Any]:
        """单次生成 SQL 并执行，不重试。用于外层控制重试逻辑。

        Args:
            question: 查询问题
            schema_info: 可选的schema信息（向后兼容）
            doc_ids: 文档ID列表，用于获取准确的表结构
            previous_error: 前次错误信息

        Returns:
            {"sql": str, "records": List[Dict], "error": str|None}
        """
        # 优先使用doc_ids获取准确的表信息
        tables_info = []
        if doc_ids:
            tables_info = await self._get_table_info(doc_ids)

        # 构建详细的schema信息
        if tables_info:
            schema_lines = []
            for table in tables_info:
                table_name = table["table_name"]
                columns = table["columns"]
                sample_data = table.get("sample_data", [])

                col_descs = [f'"{c["name"]}" ({c["type"]})' for c in columns]
                schema_lines.append(f"表名: {table_name}")
                schema_lines.append(f"列: {', '.join(col_descs)}")

                if sample_data:
                    schema_lines.append("采样数据（前3行）:")
                    for i, row in enumerate(sample_data, 1):
                        row_str = ", ".join([f'{k}={repr(v)[:50]}' for k, v in row.items()])
                        schema_lines.append(f"  行{i}: {row_str}")
                schema_lines.append("")

            full_schema = "\n".join(schema_lines)
        elif schema_info:
            full_schema = schema_info
        else:
            return {"sql": "", "records": [], "error": "没有schema信息"}

        messages = [
            {"role": "system", "content": f"""你是 SQL 专家。请根据提供的表结构生成正确的SQL查询。

可用表信息：
{full_schema}

要求：
1. 所有列名和表名必须用双引号包裹（如 "table_name"."column_name"）
2. 表名是 {doc_ids[0][:8] if doc_ids else 'doc_id前8位'}_sheetname 格式
3. 根据采样数据理解实际的数据格式
4. 查询条件要准确匹配数据内容
5. 返回所有相关列，不要遗漏"""},
        ]

        if previous_error:
            prompt = f"前次查询失败或结果不满意：{previous_error}\n\n{question}\n\n请生成 SQL 查询。只返回 JSON: {{\"sql\": \"SELECT ...\", \"explanation\": \"...\"}}"
        else:
            prompt = f"{question}\n\n请生成 SQL 查询。只返回 JSON: {{\"sql\": \"SELECT ...\", \"explanation\": \"...\"}}"

        messages.append({"role": "user", "content": prompt})

        try:
            response = await llm_service.chat_completion(messages, temperature=0.3, max_tokens=2000)
            sql_result = llm_service._extract_json(response)
            sql = sql_result.get("sql", "")
        except Exception as e:
            logger.warning("[SQL-ONCE] LLM 生成 SQL 失败: %s", e)
            return {"sql": "", "records": [], "error": f"LLM生成失败: {e}"}

        if not sql:
            return {"sql": "", "records": [], "error": "未生成SQL"}

        # 安全检查
        sql_stripped = sql.strip().upper()
        if not sql_stripped.startswith("SELECT"):
            return {"sql": sql, "records": [], "error": "非SELECT查询被拒绝"}

        for forbidden in ["DROP", "DELETE", "UPDATE", "INSERT", "ALTER", "CREATE", "TRUNCATE"]:
            if forbidden in sql_stripped:
                return {"sql": sql, "records": [], "error": f"包含危险关键字: {forbidden}"}

        if "LIMIT" not in sql_stripped:
            sql = sql.rstrip(";") + " LIMIT 200"

        try:
            async with engine.connect() as conn:
                result = await conn.execute(text(sql))
                columns = list(result.keys())
                rows = result.fetchall()
                row_dicts = [dict(zip(columns, row)) for row in rows]

                logger.info("[SQL-ONCE] 执行成功: %d 条记录, 列: %s", len(rows), columns)
                return {"sql": sql, "records": row_dicts, "error": None, "columns": columns}

        except Exception as e:
            error_msg = str(e)
            logger.warning("[SQL-ONCE] 执行失败: sql=%s, error=%s", sql[:200], error_msg[:200])
            return {"sql": sql, "records": [], "error": error_msg}

    async def query_for_field(
        self,
        field_name: str,
        row_context: str = "",
        schema_store: Dict[str, Any] = None,
        doc_ids: List[str] = None,
    ) -> List[Dict[str, Any]]:
        """为填表字段执行 SQL 查询。

        Args:
            field_name: 待填字段名
            row_context: 同行上下文
            schema_store: schema 信息
            doc_ids: 限制查询的文档 ID

        Returns:
            [{"content": str, "source": "sql"}, ...]
        """
        if not schema_store:
            return []

        # 收集相关表的 schema
        relevant_schemas = []
        if doc_ids:
            for doc_id in doc_ids:
                if doc_id in schema_store:
                    relevant_schemas.extend(schema_store[doc_id])
        else:
            for schemas in schema_store.values():
                relevant_schemas.extend(schemas)

        if not relevant_schemas:
            return []

        # 构建 schema 文本
        schema_text = ""
        for s in relevant_schemas:
            table_name = s.get("table_name", "")
            columns = s.get("columns", [])
            col_descs = [f"{c['name']}({c['type']})" for c in columns]
            schema_text += f"表 {table_name}: {', '.join(col_descs)}\n"

        # 构建查询问题
        question = f"查找「{field_name}」的值"
        if row_context:
            question += f"，相关上下文：{row_context}"

        result = await self.generate_and_execute_once(question, schema_text)
        rows = result.get("records", [])

        results = []
        for row in rows[:20]:
            # 将结果转为可读文本
            parts = [f"{k}={v}" for k, v in row.items() if v is not None]
            results.append({
                "content": f"SQL查询结果：{'，'.join(parts)}",
                "source": "sql",
                "raw_data": row,
            })

        return results


    async def generate_and_execute(
        self,
        question: str,
        schema_info: str = "",
        doc_ids: List[str] = None,
        max_retries: int = 3,
    ) -> Dict[str, Any]:
        """生成并执行SQL，带重试机制。

        当查询失败或结果很少时，自动放宽查询条件重试。

        Args:
            question: 查询问题
            schema_info: 可选的schema信息
            doc_ids: 文档ID列表
            max_retries: 最大重试次数

        Returns:
            {"sql": str, "records": List[Dict], "error": str|None}
        """
        last_error = ""
        all_records = []
        last_sql = ""

        for attempt in range(max_retries):
            # 构建带重试提示的问题
            retry_question = question
            if attempt > 0:
                # 添加重试指导
                if attempt == 1:
                    retry_question = f"{question}\n\n（前次查询未返回足够数据，请尝试：1) 使用更宽泛的匹配条件如LIKE 2) 检查列名是否正确 3) 扩大查询范围）"
                elif attempt == 2:
                    retry_question = f"{question}\n\n（前两次查询均未返回足够数据，请尝试：1) 使用ILIKE进行大小写不敏感匹配 2) 使用OR连接多个可能条件 3) 减少WHERE限制）"

            result = await self.generate_and_execute_once(
                question=retry_question,
                schema_info=schema_info,
                doc_ids=doc_ids,
                previous_error=last_error if attempt > 0 else ""
            )

            last_sql = result.get("sql", "")

            if result.get("error") is None:
                records = result.get("records", [])
                all_records.extend(records)

                # 如果获取到足够数据，提前返回
                if len(all_records) >= 10:
                    logger.info("[SQL-RETRY] 第%d次尝试成功，获取%d条记录", attempt + 1, len(all_records))
                    break
                else:
                    logger.info("[SQL-RETRY] 第%d次尝试获取%d条记录，数据不足，继续重试", attempt + 1, len(records))
                    last_error = f"仅返回{len(records)}条记录，数据不够充分"
            else:
                last_error = result.get("error", "")
                logger.warning("[SQL-RETRY] 第%d次尝试失败: %s", attempt + 1, last_error[:100])

        # 去重（基于所有字段）
        seen = set()
        unique_records = []
        for record in all_records:
            # 使用所有字段值作为去重键
            key = tuple(sorted([(k, str(v)) for k, v in record.items()]))
            if key not in seen:
                seen.add(key)
                unique_records.append(record)

        logger.info("[SQL-RETRY] 最终返回: %d条唯一记录（原始%d条）", len(unique_records), len(all_records))

        return {
            "sql": last_sql,
            "records": unique_records,
            "error": None if unique_records else last_error,
            "columns": list(unique_records[0].keys()) if unique_records else []
        }


sql_query_service = SQLQueryService()
