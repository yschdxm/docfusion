"""SQL 查询服务 — 针对 xlsx 入 PostgreSQL 的数据执行精确查询"""
import logging
from typing import List, Dict, Any
from app.services.llm_service import llm_service
from app.db.postgres import engine
from sqlalchemy import text

logger = logging.getLogger(__name__)


class SQLQueryService:

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

    async def generate_and_execute(
        self,
        question: str,
        schema_info: str,
        max_retries: int = 5,
    ) -> List[Dict[str, Any]]:
        """根据自然语言问题生成 SQL 并执行，失败或结果不满意时反馈给 LLM 重试。

        Returns:
            [{"column": value, ...}, ...] 查询结果
        """
        if not schema_info:
            return []

        # 先查询表的实际列名，作为 schema_info 的补充
        actual_columns = await self._get_actual_columns(schema_info)
        col_hint = ""
        if actual_columns:
            col_hint = "\n数据库实际列名和采样数据（必须用这些列名，用双引号包裹）：\n" + "\n".join(actual_columns)

        messages = [
            {"role": "system", "content": f"你是 SQL 专家。可用表和列信息：\n{schema_info}{col_hint}\n\n要求：\n1. 所有列名和表名必须用双引号包裹\n2. schema_info 中「模板表头」是用户期望的列名，可能与数据库列名有差异（如点号→下划线），请以数据库实际列名为准"},
        ]

        for attempt in range(max_retries):
            if attempt == 0:
                prompt = f"{question}\n\n请生成 SQL 查询。只返回 JSON: {{\"sql\": \"SELECT ...\", \"explanation\": \"...\"}}"
            else:
                prompt = '查询结果不满意或执行出错，请修改 SQL 查询。\n\n只返回 JSON: {"sql": "SELECT ...", "explanation": "..."}'

            messages.append({"role": "user", "content": prompt})

            try:
                response = await llm_service.chat_completion(messages, temperature=0.3, max_tokens=2000)
                sql_result = llm_service._extract_json(response)
                sql = sql_result.get("sql", "")
            except Exception as e:
                logger.warning("[SQL] LLM 生成 SQL 失败: %s", e)
                messages.append({"role": "assistant", "content": response or ""})
                messages.append({"role": "user", "content": "JSON 解析失败，请重新生成 SQL。只返回 JSON: {\"sql\": \"SELECT ...\", \"explanation\": \"...\"}"})
                continue

            if not sql:
                continue

            # 安全检查
            sql_stripped = sql.strip().upper()
            if not sql_stripped.startswith("SELECT"):
                logger.warning("[SQL] 拒绝非 SELECT SQL: %s", sql[:100])
                continue

            forbidden_found = False
            for forbidden in ["DROP", "DELETE", "UPDATE", "INSERT", "ALTER", "CREATE", "TRUNCATE"]:
                if forbidden in sql_stripped:
                    logger.warning("[SQL] 拒绝包含危险关键字的 SQL: %s", sql[:100])
                    forbidden_found = True
                    break
            if forbidden_found:
                continue

            if "LIMIT" not in sql_stripped:
                sql = sql.rstrip(";") + " LIMIT 100"

            try:
                async with engine.connect() as conn:
                    result = await conn.execute(text(sql))
                    columns = list(result.keys())
                    rows = result.fetchall()
                    row_dicts = [dict(zip(columns, row)) for row in rows]

                    logger.info("[SQL] 执行成功: %d 条记录, 列: %s (第%d次尝试)", len(rows), columns, attempt + 1)

                    if row_dicts:
                        # 代码级检查：哪些列全是 None
                        all_null_cols = []
                        for col in columns:
                            if all(r.get(col) is None for r in row_dicts):
                                all_null_cols.append(col)

                        if all_null_cols:
                            # 有全空列，告诉 AI 这些列可能映射错误
                            null_info = f"以下列的值全是空的：{all_null_cols}，可能是模板表头和数据库列名不匹配。请检查是否需要调整 SELECT 中的列名。"
                            preview = "\n".join([str(r) for r in row_dicts[:2]])
                            messages.append({"role": "assistant", "content": response})
                            messages.append({"role": "user", "content": f"查询返回 {len(row_dicts)} 条记录，但 {null_info}\n前2条预览：\n{preview}\n\n如果确认数据正确，回复 {{\"satisfied\": true}}。如果需要调整，回复 {{\"satisfied\": false, \"reason\": \"原因\", \"sql\": \"新的SQL\"}}"})
                            try:
                                judge_resp = await llm_service.chat_completion(messages, temperature=0.3, max_tokens=2000)
                                judge = llm_service._extract_json(judge_resp)
                                if judge.get("satisfied"):
                                    logger.info("[SQL] AI 判定结果满意，返回 %d 条记录", len(row_dicts))
                                    return row_dicts
                                else:
                                    new_sql = judge.get("sql", "")
                                    if new_sql:
                                        logger.info("[SQL] AI 不满意，重新查询")
                                        messages.append({"role": "user", "content": f"请使用以下 SQL 查询：\n{new_sql}\n\n只返回 JSON: {{\"sql\": \"SELECT ...\", \"explanation\": \"...\"}}"})
                                        continue
                            except Exception:
                                pass
                            return row_dicts
                        else:
                            # 所有列都有数据，直接返回
                            logger.info("[SQL] 所有列都有数据，直接返回 %d 条记录", len(row_dicts))
                            return row_dicts
                    else:
                        # 0 条记录，让 AI 调整
                        messages.append({"role": "assistant", "content": response})
                        messages.append({"role": "user", "content": "查询返回 0 条记录。可能是时间格式不匹配（数据库中格式为 '2025-11-25 09:00:00.0'）或其他条件不对，请调整 SQL 重新查询。只返回 JSON: {\"sql\": \"SELECT ...\", \"explanation\": \"...\"}"})
                        continue

            except Exception as e:
                error_msg = str(e)
                logger.warning("[SQL] 执行失败 (第%d次): sql=%s, error=%s", attempt + 1, sql[:200], error_msg[:200])
                messages.append({"role": "assistant", "content": response})
                messages.append({"role": "user", "content": f"SQL 执行出错：{error_msg[:500]}\n请修正 SQL 后重新生成。只返回 JSON: {{\"sql\": \"SELECT ...\", \"explanation\": \"...\"}}"})

        logger.error("[SQL] %d 次重试全部失败", max_retries)
        return []

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

        rows = await self.generate_and_execute(question, schema_text)

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


sql_query_service = SQLQueryService()
