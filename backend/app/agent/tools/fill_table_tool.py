"""
表格填写工具 - 使用数据填写表格模板

功能：
- 将数据填写到Excel模板
- 将数据填写到Word模板
- 支持追加或覆盖模式
"""

from typing import Any, Dict, List
import os

from app.agent.base.tool import BaseTool, ToolContext, ToolResult, ToolCategory, PermissionLevel
from app.db.postgres import async_session
from app.models.document import Document
from sqlalchemy import select


class FillTableTool(BaseTool):
    """表格填写工具

    使用提供的数据填写表格模板，支持Excel和Word格式。
    这是填表流程的最后一步。
    """

    # 类级别的查询缓存（应对 context 重置的情况）
    _query_cache: Dict[str, Dict] = {}
    _CACHE_TTL_SECONDS = 300  # 缓存有效期5分钟

    @classmethod
    def _get_cached_data(cls, cache_key: str, query: str):
        """获取缓存数据，带TTL检查"""
        cached = cls._query_cache.get(cache_key)
        if not cached:
            return None

        from datetime import datetime
        timestamp = datetime.fromisoformat(cached.get("timestamp", "2000-01-01"))
        if (datetime.utcnow() - timestamp).total_seconds() > cls._CACHE_TTL_SECONDS:
            del cls._query_cache[cache_key]
            return None

        if cached.get("query") != query:
            return None

        return cached.get("records")

    @classmethod
    def _set_cached_data(cls, cache_key: str, query: str, records: List[Dict],
                         template_headers: List[str], doc_ids: List[str]):
        """设置缓存数据"""
        from datetime import datetime
        cls._query_cache[cache_key] = {
            "records": records,
            "template_headers": template_headers,
            "query": query,
            "doc_ids": doc_ids,
            "timestamp": datetime.utcnow().isoformat()
        }
        cls._cleanup_expired_cache()

    @classmethod
    def _cleanup_expired_cache(cls):
        """清理过期缓存"""
        from datetime import datetime
        now = datetime.utcnow()
        expired_keys = [
            key for key, value in list(cls._query_cache.items())
            if (now - datetime.fromisoformat(value.get("timestamp", "2000-01-01"))).total_seconds()
               > cls._CACHE_TTL_SECONDS
        ]
        for key in expired_keys:
            del cls._query_cache[key]

    @property
    def category(self) -> ToolCategory:
        return ToolCategory.DATA_FILL

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.SENSITIVE

    @property
    def timeout_ms(self) -> int:
        return 60000  # 60秒

    @property
    def cacheable(self) -> bool:
        return True

    @property
    def cache_ttl_seconds(self) -> int:
        return 600  # 10分钟

    @property
    def name(self) -> str:
        return "fill_table"

    @property
    def description(self) -> str:
        return """在当前打开的文档上填写表格数据。支持增量填表和多表格文档。

使用场景：
- 在当前打开的文档上填写表格
- 增量追加数据到当前文档
- 将提取的数据填入当前文档（支持多表格Word文档）

重要规则：
- 所有填表操作都在当前打开的文档上进行，不创建新文件
- 必须提供 current_doc_id 参数
- 如果 current_doc_id 未提供，填表会失败

支持格式：
- Excel (.xlsx)
- Word (.docx)

填写模式：
- overwrite: 覆盖现有内容（保留表头），首次填写使用
- append: 追加到现有内容后面，增量填表使用

多表格文档填写（重要）：
- Word文档中有多个表格时，**必须**使用 target_table_index 指定填写哪个表格
- 表格索引从0开始，按文档中出现的顺序
- **关键**：多表格文档中，每个表格通常有特定用途，需按用途过滤数据
  - 先通过 get_table_structure 了解每个表格的用途和当前状态（是否为空/有占位行）
  - 根据用途筛选数据，不要将所有数据填入每个表格

fill_mode 详解（针对指定表格的操作）：
- **overwrite**: 清空【target_table_index 指定的表格】，然后填入新数据
  - 用于：表格为空、只有表头、有占位空行、或需要替换旧数据
  - 效果：该表格的所有现有数据行被删除，只保留表头，然后填入新数据

- **append**: 在【target_table_index 指定的表格】现有内容后面添加新行
  - 用于：该表格已有有效数据，需要继续添加更多数据时
  - 效果：新行添加到该表格的末尾，原有数据保留

重要概念：fill_mode 是针对单个表格的操作，不是文档级别的操作。
- 填写表格2时，即使表格1已经填好，也不要用 append 来"跳到"表格2
- 填写每个表格时，根据该表格当前是否为空/有占位行来选择 fill_mode

多表格填写流程：
1. 获取表格结构，分析每个表格的用途和当前状态（row_count 是否大于1，sample_data 是否为空）
2. 查询所需数据
3. 填写表格0：
   - fill_mode="overwrite"（因为表格通常只有表头或空行）
   - target_table_index=0
4. 填写表格1：
   - 检查表格1状态：如果只有表头/空行 → 用 overwrite；如果已有有效数据 → 用 append
   - target_table_index=1（指定填写第二个表格）
5. 后续表格同理，每个独立判断 fill_mode

注意：
- 数据格式必须是数组，每个元素是一行的数据
- 字段名必须与表头匹配
- 本工具只会填写文档中已有的表格，不会创建新表格
- **多表格文档必须指定target_table_index，否则数据会填错位**"""

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "current_doc_id": {
                    "type": "string",
                    "description": "当前在OnlyOffice中打开的文档ID（必需）"
                },
                "data": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "description": "一行数据，字段名对应表头"
                    },
                    "description": "填表数据，数组形式，每个元素是一行的数据。数据量大时建议使用 source_query 代替"
                },
                "source_query": {
                    "type": "object",
                    "properties": {
                        "doc_ids": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "源文档ID列表"
                        },
                        "query": {
                            "type": "string",
                            "description": "自然语言查询描述"
                        },
                        "max_rows": {
                            "type": "integer",
                            "default": 500,
                            "description": "最大查询行数，默认500。如需获取全部数据，请使用 fetch_all=true"
                        },
                        "fetch_all": {
                            "type": "boolean",
                            "default": False,
                            "description": "是否获取全部数据。设为true时，工具会自动分批获取所有数据，忽略max_rows限制"
                        },
                        "data_confirmed": {
                            "type": "boolean",
                            "description": "是否已确认数据摘要。首次调用时不传或传false，工具返回数据预览；确认无误后再次调用时传true执行实际填充"
                        }
                    },
                    "description": "自动数据源模式。首次调用返回数据预览，确认后再次调用并设置data_confirmed=true执行填充"
                },
                "fill_mode": {
                    "type": "string",
                    "enum": ["append", "overwrite"],
                    "default": "overwrite",
                    "description": """填写模式:
- overwrite: 覆盖现有内容（保留表头），首次填写使用
- append: 追加到现有内容后面，增量填表使用"""
                },
                "target_table_index": {
                    "type": "integer",
                    "description": "目标表格索引（从0开始），用于多表格文档。如果不指定，自动选择第一个合适的表格"
                }
            },
            "required": ["current_doc_id"]
        }

    async def execute(self, params: Dict[str, Any], context: ToolContext) -> ToolResult:
        """执行表格填写"""
        import logging
        logger = logging.getLogger(__name__)

        try:
            current_doc_id = params.get("current_doc_id", "") or (context.metadata.get("current_doc_id", "") if context.metadata else "")
            data = params.get("data", [])
            source_query = params.get("source_query")
            fill_mode = params.get("fill_mode", "overwrite")
            target_table_index = params.get("target_table_index")

            # UUID校验
            if current_doc_id:
                uuid_error = BaseTool.validate_uuid(current_doc_id, "current_doc_id")
                if uuid_error:
                    return ToolResult(success=False, error=uuid_error)

            # 必须提供 current_doc_id
            if not current_doc_id:
                return ToolResult(
                    success=False,
                    error="必须提供 current_doc_id，所有填表操作必须在当前打开的文档上进行"
                )

            # source_query 模式：自动查询数据并填充
            if source_query and not data:
                # 检查是否已确认（LLM 已审核过数据摘要）
                if source_query.get("data_confirmed"):
                    return await self._execute_confirmed_source_query(
                        source_query, current_doc_id,
                        fill_mode, target_table_index, context, logger
                    )
                else:
                    return await self._execute_with_source_query(
                        source_query, current_doc_id,
                        fill_mode, target_table_index, context, logger
                    )

            if not data:
                return ToolResult(
                    success=False,
                    error="填表数据不能为空"
                )

            # 直接修改当前打开的文档
            async with async_session() as db:
                return await self._fill_current_document(
                    db, current_doc_id, data, fill_mode, target_table_index, logger, context
                )

        except Exception as e:
            logger.exception(f"表格填写失败: {e}")
            return ToolResult(
                success=False,
                error=f"表格填写失败: {str(e)}"
            )

    async def _execute_with_source_query(
        self, source_query: Dict, current_doc_id: str,
        fill_mode: str, target_table_index: int, context: ToolContext, logger
    ) -> ToolResult:
        """source_query 模式：自动查询源数据并填入当前文档。

        LLM 不需要搬运数据，只需传查询描述。
        工具内部自动完成：查询 → 列名匹配 → 填充。
        """
        sq_doc_ids = source_query.get("doc_ids", context.file_ids)
        sq_query = source_query.get("query", "")
        sq_max_rows = source_query.get("max_rows", 500)
        fetch_all = source_query.get("fetch_all", False)

        if not sq_query:
            return ToolResult(success=False, error="source_query.query 不能为空")
        if not current_doc_id:
            return ToolResult(success=False, error="source_query 模式下必须提供 current_doc_id")

        # 检查源文档类型：source_query 自动模式仅适用于 xlsx 源文档
        if sq_doc_ids:
            async with async_session() as db:
                source_result = await db.execute(
                    select(Document.file_type).where(Document.id.in_(sq_doc_ids))
                )
                source_types = {row[0] for row in source_result.fetchall()}
                non_xlsx = source_types - {"xlsx"}
                if non_xlsx:
                    return ToolResult(
                        success=False,
                        error=(
                            f"source_query 自动模式仅适用于xlsx源文档。"
                            f"当前源文档包含非xlsx格式: {', '.join(non_xlsx)}。"
                            f"对于非xlsx文档，请先使用 read_file 或 rag_search 提取数据，"
                            f"再通过 data 参数传入 fill_table。"
                        )
                    )

        # 1. 获取模板表头（使用当前打开的文档）
        async with async_session() as db:
            result = await db.execute(
                select(Document).where(Document.id == current_doc_id)
            )
            template_doc = result.scalar_one_or_none()

        if not template_doc:
            return ToolResult(success=False, error=f"当前文档不存在: {current_doc_id}")

        # 获取模板表头
        template_headers = self._get_template_headers(template_doc.file_path, template_doc.file_type, target_table_index)
        if not template_headers:
            return ToolResult(success=False, error="无法获取模板表头")

        logger.info(f"[FillTableTool][source_query] 模板表头: {template_headers}, fetch_all={fetch_all}")

        # 2. 查询源数据，根据 fetch_all 参数决定查询策略
        from app.services.sql_query_service import sql_query_service as sql_service

        if fetch_all:
            # 获取全部数据（自动分批）
            headers_str = "，".join(template_headers)
            augmented_query = (
                f"{sq_query}\n\n"
                f"模板表头（可能与数据库列名有差异）：{headers_str}\n"
                f"请使用 AS 将列名重命名为与模板表头一致。"
                f"请返回所有匹配的数据，不要限制行数。"
            )
            source_records = await self._fetch_all_data(
                sql_service, augmented_query, sq_doc_ids, template_headers, logger
            )
        else:
            # 限制查询行数
            headers_str = "，".join(template_headers)
            augmented_query = (
                f"{sq_query}\n\n"
                f"模板表头（可能与数据库列名有差异）：{headers_str}\n"
                f"请使用 AS 将列名重命名为与模板表头一致。"
                f"请确保返回不超过 {sq_max_rows} 行数据。"
            )
            query_result = await sql_service.generate_and_execute(
                question=augmented_query,
                doc_ids=sq_doc_ids,
                max_retries=3
            )
            if query_result.get("error"):
                return ToolResult(
                    success=False,
                    error=f"源数据查询失败: {query_result['error']}"
                )
            source_records = query_result.get("records", [])

        if not source_records:
            return ToolResult(
                success=True,
                data={"filled_rows": 0, "total_rows": 0, "message": "查询未返回数据"},
                metadata={"source_query": sq_query}
            )

        # 2.5 用 AI 建立模板表头到源数据列名的映射（参照旧架构 table_filling_service.py）
        if source_records:
            source_columns = list(source_records[0].keys())
            from app.services.llm_service import llm_service
            header_mapping = await llm_service.map_columns(template_headers, source_columns)
            if header_mapping:
                logger.info(f"[FillTableTool] AI列名映射: {header_mapping}")
                source_records = [
                    {header_mapping.get(k, k): v for k, v in record.items()}
                    for record in source_records
                ]

        # 3. 缓存数据供确认阶段使用
        cache_key = f"fill_table_cache_{current_doc_id}_{hash(sq_query)}_{target_table_index or 0}"
        self._set_cached_data(cache_key, sq_query, source_records, template_headers, sq_doc_ids)
        # 同时存入 context.metadata（如果 context 可用）
        if context:
            context.metadata[cache_key] = self._query_cache[cache_key]
        logger.info(f"[FillTableTool] 已缓存查询结果: {len(source_records)} 行数据, cache_key={cache_key}")

        # 4. 生成数据摘要，返回给 LLM 审核
        summary = self._build_data_summary(source_records, template_headers)
        return ToolResult(
            success=True,
            data={
                "data_preview": summary,
                "total_records": len(source_records),
                "source_columns": list(source_records[0].keys()) if source_records else [],
                "template_headers": template_headers,
                "action_required": "请确认以上数据是否正确，然后调用 fill_table 时将 source_query.data_confirmed 设为 true 来执行实际填入。"
            },
            metadata={"source_query": sq_query, "stage": "preview"}
        )

    async def _execute_confirmed_source_query(
        self, source_query: Dict, current_doc_id: str,
        fill_mode: str, target_table_index: int, context: ToolContext, logger
    ) -> ToolResult:
        """source_query 确认模式：LLM 已审核过数据摘要，执行实际填入。"""
        sq_doc_ids = source_query.get("doc_ids", context.file_ids)
        sq_query = source_query.get("query", "")
        sq_max_rows = source_query.get("max_rows", 500)
        fetch_all = source_query.get("fetch_all", False)

        if not sq_query:
            return ToolResult(success=False, error="source_query.query 不能为空")

        # 1. 获取模板表头（使用当前打开的文档）
        async with async_session() as db:
            result = await db.execute(select(Document).where(Document.id == current_doc_id))
            template_doc = result.scalar_one_or_none()

        if not template_doc:
            return ToolResult(success=False, error=f"当前文档不存在: {current_doc_id}")

        template_headers = self._get_template_headers(template_doc.file_path, template_doc.file_type, target_table_index)
        if not template_headers:
            return ToolResult(success=False, error="无法获取模板表头")

        # 2. 尝试从缓存获取数据（优先使用缓存，避免重复查询）
        cache_key = f"fill_table_cache_{current_doc_id}_{hash(sq_query)}_{target_table_index or 0}"

        # 首先尝试从 context.metadata 获取（同一会话）
        cached = context.metadata.get(cache_key) if context else None
        if cached and cached.get("query") == sq_query:
            source_records = cached["records"]
            template_headers = cached.get("template_headers", template_headers)
            logger.info(f"[FillTableTool][source_query-confirmed] 从 context 缓存获取 {len(source_records)} 行数据")
        else:
            # 其次从类缓存获取（跨会话，检查TTL）
            cached_records = self._get_cached_data(cache_key, sq_query)
            if cached_records:
                source_records = cached_records
                logger.info(f"[FillTableTool][source_query-confirmed] 从类缓存获取 {len(source_records)} 行数据")
            else:
                # 缓存未命中，重新查询
                logger.warning("[FillTableTool][source_query-confirmed] 缓存未命中，重新查询数据")
                from app.services.sql_query_service import sql_query_service as sql_service

                if fetch_all:
                    # 获取全部数据
                    headers_str = "，".join(template_headers)
                    augmented_query = (
                        f"{sq_query}\n\n"
                        f"模板表头（可能与数据库列名有差异）：{headers_str}\n"
                        f"请使用 AS 将列名重命名为与模板表头一致。"
                        f"请返回所有匹配的数据，不要限制行数。"
                    )
                    source_records = await self._fetch_all_data(
                        sql_service, augmented_query, sq_doc_ids, template_headers, logger
                    )
                else:
                    # 限制查询行数
                    headers_str = "，".join(template_headers)
                    augmented_query = (
                        f"{sq_query}\n\n"
                        f"模板表头（可能与数据库列名有差异）：{headers_str}\n"
                        f"请使用 AS 将列名重命名为与模板表头一致。"
                        f"请确保返回不超过 {sq_max_rows} 行数据。"
                    )
                    query_result = await sql_service.generate_and_execute(
                        question=augmented_query,
                        doc_ids=sq_doc_ids,
                        max_retries=3
                    )
                    if query_result.get("error"):
                        return ToolResult(success=False, error=f"源数据查询失败: {query_result['error']}")
                    source_records = query_result.get("records", [])

        if not source_records:
            return ToolResult(success=True, data={"filled_rows": 0, "total_rows": 0, "message": "查询未返回数据"})

        # 2.5 用 AI 建立模板表头到源数据列名的映射（参照旧架构 table_filling_service.py）
        if source_records:
            source_columns = list(source_records[0].keys())
            from app.services.llm_service import llm_service
            header_mapping = await llm_service.map_columns(template_headers, source_columns)
            if header_mapping:
                logger.info(f"[FillTableTool][confirmed] AI列名映射: {header_mapping}")
                source_records = [
                    {header_mapping.get(k, k): v for k, v in record.items()}
                    for record in source_records
                ]

        # 3. 填入（直接修改当前文档）
        if fetch_all:
            data = source_records  # fetch_all 模式不截断
        else:
            data = source_records[:sq_max_rows]
        logger.info(f"[FillTableTool][source_query-confirmed] 填入 {len(data)} 行数据 (fetch_all={fetch_all}, total={len(source_records)})")

        async with async_session() as db:
            return await self._fill_current_document(
                db, current_doc_id, data, fill_mode, target_table_index, logger, context
            )

    def _build_data_summary(self, records: List[Dict], template_headers: List[str]) -> str:
        """构建数据摘要：前5行 + 中间3行 + 末尾2行 + 列名 + 行数 + 数据质量统计"""
        import json

        total = len(records)
        columns = list(records[0].keys()) if records else []

        # 数据质量统计
        null_counts = {col: 0 for col in columns}
        unique_counts = {col: set() for col in columns}
        for record in records:
            for col in columns:
                val = record.get(col)
                if val is None or str(val).strip() == "" or str(val) == "None":
                    null_counts[col] += 1
                else:
                    unique_counts[col].add(str(val))

        unique_counts = {col: len(vals) for col, vals in unique_counts.items()}

        lines = [f"共 {total} 行数据，{len(columns)} 列"]
        lines.append(f"源数据列名: {columns}")
        lines.append(f"模板表头:   {template_headers}")
        lines.append("")

        # 列信息摘要
        lines.append("=== 列信息摘要 ===")
        for col in columns:
            null_pct = null_counts[col] / total * 100 if total > 0 else 0
            lines.append(f"  {col}: 唯一值 {unique_counts[col]}，空值 {null_counts[col]} ({null_pct:.1f}%)")
        lines.append("")

        # 前10行
        head_count = min(10, total)
        lines.append(f"=== 前 {head_count} 行 ===")
        for i, record in enumerate(records[:head_count]):
            lines.append(f"行{i+1}: {json.dumps(record, ensure_ascii=False)}")

        # 中间5行（如果数据够多）
        if total > 20:
            mid_start = total // 2 - 2
            lines.append(f"\n=== 中间第 {mid_start+1}-{mid_start+5} 行 ===")
            for i, record in enumerate(records[mid_start:mid_start+5]):
                lines.append(f"行{mid_start+i+1}: {json.dumps(record, ensure_ascii=False)}")

        # 末尾5行
        if total > 10:
            lines.append("\n=== 末尾 5 行 ===")
            for i, record in enumerate(records[-5:], start=total-4):
                lines.append(f"行{i+1}: {json.dumps(record, ensure_ascii=False)}")

        return "\n".join(lines)

    async def _fetch_all_data(
        self,
        sql_service,
        augmented_query: str,
        sq_doc_ids: List[str],
        template_headers: List[str],
        logger
    ) -> List[Dict]:
        """分批获取全部数据

        策略：
        1. 首次查询获取数据
        2. 如果达到LIMIT上限(10000条)，尝试分批获取更多
        3. 最多获取50000条，防止无限循环
        """
        # 第一次查询
        query_result = await sql_service.generate_and_execute(
            question=augmented_query,
            doc_ids=sq_doc_ids,
            max_retries=3
        )

        records = query_result.get("records", [])
        total_fetched = len(records)

        # 如果达到LIMIT上限，尝试分批获取更多
        if total_fetched >= 10000:
            logger.info(f"[FillTableTool] 首次查询返回{total_fetched}条，可能还有更多数据，尝试分批获取")

            offset = total_fetched
            batch_size = 5000
            max_total = 50000  # 最多获取5万行，防止无限循环

            while total_fetched < max_total:
                batch_query = (
                    f"{augmented_query}\n\n"
                    f"请使用 OFFSET {offset} LIMIT {batch_size} 获取下一批数据"
                )

                batch_result = await sql_service.generate_and_execute(
                    question=batch_query,
                    doc_ids=sq_doc_ids,
                    max_retries=2
                )

                batch_records = batch_result.get("records", [])
                if not batch_records:
                    break

                records.extend(batch_records)
                total_fetched += len(batch_records)
                offset += len(batch_records)

                logger.info(f"[FillTableTool] 分批获取: 已获取 {total_fetched} 行")

                # 如果这批数据不足batch_size，说明已经获取完毕
                if len(batch_records) < batch_size:
                    break

        # 去重
        seen = set()
        unique_records = []
        for record in records:
            key = tuple(sorted([(k, str(v)) for k, v in record.items()]))
            if key not in seen:
                seen.add(key)
                unique_records.append(record)

        logger.info(f"[FillTableTool] 最终获取: {len(unique_records)} 条唯一记录（原始 {len(records)} 条）")
        return unique_records

    def _get_template_headers(self, file_path: str, file_type: str, target_table_index: int = None) -> List[str]:
        """获取模板文件的表头"""
        if file_type == "xlsx":
            from openpyxl import load_workbook
            wb = load_workbook(file_path, read_only=True)
            ws = wb.active
            headers = [str(cell.value) if cell.value else f"Column_{i+1}"
                       for i, cell in enumerate(next(ws.iter_rows(min_row=1, max_row=1)))]
            wb.close()
            return headers
        elif file_type == "docx":
            from docx import Document as DocxDocument
            doc = DocxDocument(file_path)
            if not doc.tables:
                return []
            table_idx = target_table_index if target_table_index is not None else 0
            table = doc.tables[min(table_idx, len(doc.tables) - 1)]
            if table.rows:
                return [cell.text.strip() if cell.text.strip() else f"Column_{i+1}"
                        for i, cell in enumerate(table.rows[0].cells)]
        return []

    async def _fill_current_document(
        self, db, current_doc_id: str, data: List[Dict], fill_mode: str, target_table_index: int, logger, context: ToolContext = None
    ) -> ToolResult:
        """返回填表数据，由前端通过 OnlyOffice 插件实时写入编辑器（不修改文件）

        Args:
            db: 数据库会话
            current_doc_id: 当前打开的文档 ID
            data: 填表数据
            fill_mode: 填写模式（overwrite/append）
            target_table_index: 目标表格索引
            logger: 日志记录器
            context: 工具上下文

        Returns:
            ToolResult
        """
        # 查询文档
        result = await db.execute(
            select(Document).where(Document.id == current_doc_id)
        )
        doc = result.scalar_one_or_none()

        if not doc:
            return ToolResult(
                success=False,
                error=f"文档不存在: {current_doc_id}"
            )

        # 获取表头
        template_headers = self._get_template_headers(doc.file_path, doc.file_type, target_table_index)
        if not template_headers:
            return ToolResult(
                success=False,
                error="无法获取表头"
            )

        logger.info(f"[FillTableTool] 返回填表数据供插件调用: {current_doc_id}, {len(data)}行, {doc.file_type}")

        return ToolResult(
            success=True,
            data={
                "action": "fill_table_via_plugin",
                "filled_rows": len(data),
                "total_rows": len(data),
                "current_doc_id": current_doc_id,
                "file_type": doc.file_type,
                "headers": template_headers,
                "data": data,
                "fill_mode": fill_mode,
                "target_table_index": target_table_index or 0,
                "message": f"✅ 已完成填表，共填写 {len(data)} 行数据。",
            },
            metadata={
                "fill_mode": fill_mode,
                "is_current_doc_update": True,
            }
        )

    async def _fill_excel(self, file_path: str, data: List[Dict], fill_mode: str) -> bool:
        """填写Excel文件"""
        try:
            from openpyxl import load_workbook

            wb = load_workbook(file_path)
            ws = wb.active

            # 获取表头
            headers = []
            first_row = next(ws.iter_rows(min_row=1, max_row=1, values_only=True), None)
            if first_row:
                headers = [str(cell) if cell else f"Column_{i+1}" for i, cell in enumerate(first_row)]

            # 处理填写模式
            if fill_mode == "overwrite":
                # 清空数据行，保留表头
                # 删除现有数据行
                for row in range(ws.max_row, 1, -1):
                    ws.delete_rows(row)

            # 填写数据
            for row_data in data:
                row_values = []
                for header in headers:
                    value = self._get_value_for_header(row_data, header)
                    row_values.append(value)
                ws.append(row_values)

            wb.save(file_path)
            wb.close()

            return True

        except Exception as e:
            print(f"填写Excel失败: {e}")
            return False

    def _get_value_for_header(self, row_data: Dict, header: str) -> str:
        """智能列名匹配：精确匹配 → 大小写不敏感匹配 → 包含匹配"""
        # 1. 精确匹配
        if header in row_data and row_data[header] is not None:
            return str(row_data[header])
        # 2. 去空格+大小写不敏感匹配
        header_lower = header.strip().lower()
        for key, value in row_data.items():
            if value is not None and key.strip().lower() == header_lower:
                return str(value)
        # 3. 包含匹配（header 包含 key 或 key 包含 header）
        for key, value in row_data.items():
            if value is not None:
                key_clean = key.strip().lower()
                if header_lower in key_clean or key_clean in header_lower:
                    return str(value)
        return ""

    def _is_empty_row(self, row) -> bool:
        """检查表格行是否为空（所有单元格都为空或只有空白字符）"""
        if not row.cells:
            return True

        for cell in row.cells:
            text = cell.text.strip()
            if text:
                return False
        return True

    async def _fill_word(self, file_path: str, data: List[Dict], fill_mode: str, target_table_index: int = None) -> bool:
        """填写Word文件 - 支持多表格智能填写和空行优先填写"""
        import logging
        logger = logging.getLogger(__name__)

        try:
            from docx import Document

            logger.info(f"[FillTableTool] 开始填写Word文件: {file_path}, 数据行数: {len(data)}")

            doc = Document(file_path)

            if not doc.tables:
                logger.error("[FillTableTool] 文档中没有表格")
                return False

            logger.info(f"[FillTableTool] 文档中共有 {len(doc.tables)} 个表格")

            # 获取第一个表格的表头作为参考
            first_table = doc.tables[0]
            headers = []
            if first_table.rows:
                first_row = first_table.rows[0]
                headers = [cell.text.strip() if cell.text.strip() else f"Column_{i+1}"
                          for i, cell in enumerate(first_row.cells)]
                logger.info(f"[FillTableTool] 表头: {headers}")

            # 确定目标表格
            target_table = None
            if target_table_index is not None and target_table_index < len(doc.tables):
                # 使用指定的表格索引
                target_table = doc.tables[target_table_index]
                logger.info(f"[FillTableTool] 使用指定的表格 {target_table_index} 作为填写目标")
            else:
                # 找到第一个非空表格（已有数据或只有表头）进行覆盖
                for i, table in enumerate(doc.tables):
                    logger.info(f"[FillTableTool] 检查表格 {i}: {len(table.rows)} 行")
                    if len(table.rows) >= 1:  # 至少要有表头
                        target_table = table
                        logger.info(f"[FillTableTool] 选择表格 {i} 作为填写目标")
                        break

            if not target_table:
                logger.error("[FillTableTool] 没有找到有效的表格")
                return False

            # 检测空行（从第二行开始，第一行是表头）
            empty_rows = []
            for i, row in enumerate(target_table.rows[1:], start=2):  # 从第2行开始（索引1）
                if self._is_empty_row(row):
                    empty_rows.append((i - 1, row))  # 存储行索引（从0开始）和行对象

            logger.info(f"[FillTableTool] 检测到 {len(empty_rows)} 个空行")

            # 根据fill_mode处理
            if fill_mode == "overwrite":
                # 优先填写空行
                filled_count = 0
                data_index = 0

                # 先填写空行
                for row_index, row in empty_rows:
                    if data_index < len(data):
                        row_data = data[data_index]
                        for i, header in enumerate(headers):
                            if i < len(row.cells):
                                value = self._get_value_for_header(row_data, header)
                                if value is None:
                                    value = ""
                                row.cells[i].text = str(value)
                        filled_count += 1
                        data_index += 1
                        logger.info(f"[FillTableTool] 填写空行 {row_index}")

                # 如果还有数据需要填写，删除剩余空行并添加新行
                if data_index < len(data):
                    # 删除未使用的空行
                    for _, row in empty_rows[data_index:]:
                        target_table._tbl.remove(row._tr)
                    logger.info(f"[FillTableTool] 删除未使用的空行: {len(empty_rows) - data_index} 行")

                    # 添加新行
                    for row_data in data[data_index:]:
                        row = target_table.add_row()
                        for i, header in enumerate(headers):
                            if i < len(row.cells):
                                value = self._get_value_for_header(row_data, header)
                                if value is None:
                                    value = ""
                                row.cells[i].text = str(value)
                        filled_count += 1
                        logger.info("[FillTableTool] 添加新行")

                # 如果空行多于数据行，删除多余的空行
                if len(empty_rows) > len(data):
                    rows_to_remove = len(empty_rows) - len(data)
                    for _, row in empty_rows[len(data):]:
                        target_table._tbl.remove(row._tr)
                    logger.info(f"[FillTableTool] 删除多余的空行: {rows_to_remove} 行")

                logger.info(f"[FillTableTool] 填写完成, 总共填写 {filled_count} 行")

            else:  # append模式
                # 优先填写空行，然后追加
                filled_count = 0
                data_index = 0

                # 先填写空行
                for row_index, row in empty_rows:
                    if data_index < len(data):
                        row_data = data[data_index]
                        for i, header in enumerate(headers):
                            if i < len(row.cells):
                                value = self._get_value_for_header(row_data, header)
                                if value is None:
                                    value = ""
                                row.cells[i].text = str(value)
                        filled_count += 1
                        data_index += 1
                        logger.info(f"[FillTableTool] 填写空行 {row_index}")

                # 如果还有数据需要填写，追加新行
                if data_index < len(data):
                    for row_data in data[data_index:]:
                        row = target_table.add_row()
                        for i, header in enumerate(headers):
                            if i < len(row.cells):
                                value = self._get_value_for_header(row_data, header)
                                if value is None:
                                    value = ""
                                row.cells[i].text = str(value)
                        filled_count += 1
                        logger.info("[FillTableTool] 追加新行")

                logger.info(f"[FillTableTool] 追加完成, 总共填写 {filled_count} 行")

            doc.save(file_path)
            logger.info(f"[FillTableTool] 文档已保存: {file_path}")

            return True

        except Exception as e:
            logger.exception(f"[FillTableTool] 填写Word失败: {e}")
            return False


class FillCellTool(BaseTool):
    """填写单个单元格工具"""

    @property
    def name(self) -> str:
        return "fill_cell"

    @property
    def description(self) -> str:
        return """填写Excel单个单元格。

使用场景：
- 当需要修改单个单元格的内容时
- 当需要精确填写某个特定位置的数据时

注意事项：
- 行和列索引从0开始
- 如果单元格已有内容，会被覆盖"""

    @property
    def category(self) -> ToolCategory:
        return ToolCategory.DATA_FILL

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.SENSITIVE

    @property
    def timeout_ms(self) -> int:
        return 5000  # 5秒

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "file_id": {
                    "type": "string",
                    "description": "文档ID"
                },
                "sheet_name": {
                    "type": "string",
                    "description": "工作表名称（可选，默认第一个）"
                },
                "row": {
                    "type": "integer",
                    "description": "行号（从0开始）"
                },
                "col": {
                    "type": "integer",
                    "description": "列号（从0开始）"
                },
                "value": {
                    "description": "要填写的值"
                }
            },
            "required": ["file_id", "row", "col", "value"]
        }

    async def execute(self, params: Dict[str, Any], context: ToolContext) -> ToolResult:
        """填写单个单元格"""
        try:
            file_id = params.get("file_id", "")
            sheet_name = params.get("sheet_name")
            row = params.get("row")
            col = params.get("col")
            value = params.get("value")

            if not file_id:
                return ToolResult(success=False, error="文档ID不能为空")

            if row is None or col is None:
                return ToolResult(success=False, error="行号和列号不能为空")

            # 验证UUID格式
            uuid_error = BaseTool.validate_uuid(file_id, "file_id")
            if uuid_error:
                return ToolResult(success=False, error=uuid_error)

            # 查询文档信息
            async with async_session() as db:
                result = await db.execute(
                    select(Document).where(Document.id == file_id)
                )
                doc = result.scalar_one_or_none()

                if not doc:
                    return ToolResult(success=False, error=f"文档不存在: {file_id}")

                if doc.file_type != "xlsx":
                    return ToolResult(success=False, error=f"不支持的文件类型: {doc.file_type}，仅支持xlsx")

                if not os.path.exists(doc.file_path):
                    return ToolResult(success=False, error=f"文件不存在: {doc.file_path}")

                # 使用openpyxl填写单元格
                try:
                    from openpyxl import load_workbook
                    wb = load_workbook(doc.file_path)

                    # 获取工作表
                    if sheet_name:
                        if sheet_name not in wb.sheetnames:
                            return ToolResult(
                                success=False,
                                error=f"工作表不存在: {sheet_name}，可用工作表: {wb.sheetnames}"
                            )
                        ws = wb[sheet_name]
                    else:
                        ws = wb.active

                    # 填写单元格（openpyxl从1开始）
                    ws.cell(row=row + 1, column=col + 1, value=value)

                    # 保存文件
                    wb.save(doc.file_path)
                    wb.close()

                    return ToolResult(
                        success=True,
                        data={
                            "file_id": file_id,
                            "sheet_name": ws.title,
                            "row": row,
                            "col": col,
                            "value": value,
                            "message": f"已填写单元格 ({row}, {col})"
                        }
                    )

                except ImportError:
                    return ToolResult(success=False, error="openpyxl未安装，无法填写Excel")
                except Exception as e:
                    return ToolResult(success=False, error=f"填写单元格失败: {str(e)}")

        except Exception as e:
            logger.exception(f"填写单元格失败: {e}")
            return ToolResult(success=False, error=f"填写单元格失败: {str(e)}")


class FillRowTool(BaseTool):
    """填写整行工具"""

    @property
    def name(self) -> str:
        return "fill_row"

    @property
    def description(self) -> str:
        return """填写Excel整行数据。

使用场景：
- 当需要添加一行新数据时
- 当需要替换某一行的数据时

注意事项：
- 行索引从0开始
- data参数是数组，对应行中的各个单元格"""

    @property
    def category(self) -> ToolCategory:
        return ToolCategory.DATA_FILL

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.SENSITIVE

    @property
    def timeout_ms(self) -> int:
        return 10000  # 10秒

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "file_id": {
                    "type": "string",
                    "description": "文档ID"
                },
                "sheet_name": {
                    "type": "string",
                    "description": "工作表名称（可选，默认第一个）"
                },
                "row": {
                    "type": "integer",
                    "description": "行号（从0开始）"
                },
                "data": {
                    "type": "array",
                    "description": "行数据（数组）"
                }
            },
            "required": ["file_id", "row", "data"]
        }

    async def execute(self, params: Dict[str, Any], context: ToolContext) -> ToolResult:
        """填写整行"""
        try:
            file_id = params.get("file_id", "")
            sheet_name = params.get("sheet_name")
            row = params.get("row")
            data = params.get("data", [])

            if not file_id:
                return ToolResult(success=False, error="文档ID不能为空")

            if row is None:
                return ToolResult(success=False, error="行号不能为空")

            if not data:
                return ToolResult(success=False, error="数据不能为空")

            # 验证UUID格式
            uuid_error = BaseTool.validate_uuid(file_id, "file_id")
            if uuid_error:
                return ToolResult(success=False, error=uuid_error)

            # 查询文档信息
            async with async_session() as db:
                result = await db.execute(
                    select(Document).where(Document.id == file_id)
                )
                doc = result.scalar_one_or_none()

                if not doc:
                    return ToolResult(success=False, error=f"文档不存在: {file_id}")

                if doc.file_type != "xlsx":
                    return ToolResult(success=False, error=f"不支持的文件类型: {doc.file_type}，仅支持xlsx")

                if not os.path.exists(doc.file_path):
                    return ToolResult(success=False, error=f"文件不存在: {doc.file_path}")

                # 使用openpyxl填写整行
                try:
                    from openpyxl import load_workbook
                    wb = load_workbook(doc.file_path)

                    # 获取工作表
                    if sheet_name:
                        if sheet_name not in wb.sheetnames:
                            return ToolResult(
                                success=False,
                                error=f"工作表不存在: {sheet_name}，可用工作表: {wb.sheetnames}"
                            )
                        ws = wb[sheet_name]
                    else:
                        ws = wb.active

                    # 填写整行（openpyxl从1开始）
                    for col_idx, value in enumerate(data):
                        ws.cell(row=row + 1, column=col_idx + 1, value=value)

                    # 保存文件
                    wb.save(doc.file_path)
                    wb.close()

                    return ToolResult(
                        success=True,
                        data={
                            "file_id": file_id,
                            "sheet_name": ws.title,
                            "row": row,
                            "data": data,
                            "columns_count": len(data),
                            "message": f"已填写第 {row} 行，共 {len(data)} 列"
                        }
                    )

                except ImportError:
                    return ToolResult(success=False, error="openpyxl未安装，无法填写Excel")
                except Exception as e:
                    return ToolResult(success=False, error=f"填写整行失败: {str(e)}")

        except Exception as e:
            logger.exception(f"填写整行失败: {e}")
            return ToolResult(success=False, error=f"填写整行失败: {str(e)}")


class FillColumnTool(BaseTool):
    """填写整列工具"""

    @property
    def name(self) -> str:
        return "fill_column"

    @property
    def description(self) -> str:
        return """填写Excel整列数据。

使用场景：
- 当需要添加一列新数据时
- 当需要替换某一列的数据时

注意事项：
- 列索引从0开始
- data参数是数组，对应列中的各个单元格"""

    @property
    def category(self) -> ToolCategory:
        return ToolCategory.DATA_FILL

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.SENSITIVE

    @property
    def timeout_ms(self) -> int:
        return 10000  # 10秒

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "file_id": {
                    "type": "string",
                    "description": "文档ID"
                },
                "sheet_name": {
                    "type": "string",
                    "description": "工作表名称（可选，默认第一个）"
                },
                "col": {
                    "type": "integer",
                    "description": "列号（从0开始）"
                },
                "data": {
                    "type": "array",
                    "description": "列数据（数组）"
                }
            },
            "required": ["file_id", "col", "data"]
        }

    async def execute(self, params: Dict[str, Any], context: ToolContext) -> ToolResult:
        """填写整列"""
        try:
            file_id = params.get("file_id", "")
            sheet_name = params.get("sheet_name")
            col = params.get("col")
            data = params.get("data", [])

            if not file_id:
                return ToolResult(success=False, error="文档ID不能为空")

            if col is None:
                return ToolResult(success=False, error="列号不能为空")

            if not data:
                return ToolResult(success=False, error="数据不能为空")

            # 验证UUID格式
            uuid_error = BaseTool.validate_uuid(file_id, "file_id")
            if uuid_error:
                return ToolResult(success=False, error=uuid_error)

            # 查询文档信息
            async with async_session() as db:
                result = await db.execute(
                    select(Document).where(Document.id == file_id)
                )
                doc = result.scalar_one_or_none()

                if not doc:
                    return ToolResult(success=False, error=f"文档不存在: {file_id}")

                if doc.file_type != "xlsx":
                    return ToolResult(success=False, error=f"不支持的文件类型: {doc.file_type}，仅支持xlsx")

                if not os.path.exists(doc.file_path):
                    return ToolResult(success=False, error=f"文件不存在: {doc.file_path}")

                # 使用openpyxl填写整列
                try:
                    from openpyxl import load_workbook
                    wb = load_workbook(doc.file_path)

                    # 获取工作表
                    if sheet_name:
                        if sheet_name not in wb.sheetnames:
                            return ToolResult(
                                success=False,
                                error=f"工作表不存在: {sheet_name}，可用工作表: {wb.sheetnames}"
                            )
                        ws = wb[sheet_name]
                    else:
                        ws = wb.active

                    # 填写整列（openpyxl从1开始）
                    for row_idx, value in enumerate(data):
                        ws.cell(row=row_idx + 1, column=col + 1, value=value)

                    # 保存文件
                    wb.save(doc.file_path)
                    wb.close()

                    return ToolResult(
                        success=True,
                        data={
                            "file_id": file_id,
                            "sheet_name": ws.title,
                            "col": col,
                            "data": data,
                            "rows_count": len(data),
                            "message": f"已填写第 {col} 列，共 {len(data)} 行"
                        }
                    )

                except ImportError:
                    return ToolResult(success=False, error="openpyxl未安装，无法填写Excel")
                except Exception as e:
                    return ToolResult(success=False, error=f"填写整列失败: {str(e)}")

        except Exception as e:
            logger.exception(f"填写整列失败: {e}")
            return ToolResult(success=False, error=f"填写整列失败: {str(e)}")


class AutoFillSuggestionsTool(BaseTool):
    """智能填充建议工具"""

    @property
    def name(self) -> str:
        return "auto_fill_suggestions"

    @property
    def description(self) -> str:
        return """根据上下文和已有数据为单元格提供填充建议。

使用场景：
- 当不确定某个单元格应该填什么值时
- 当需要根据已有数据推断缺失值时
- 当需要自动填充序列或模式时

注意事项：
- 此工具会分析上下文行的数据，生成建议
- 建议包含置信度和原因
- 可以接受或拒绝建议"""

    @property
    def category(self) -> ToolCategory:
        return ToolCategory.DATA_FILL

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.SAFE

    @property
    def timeout_ms(self) -> int:
        return 30000  # 30秒

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "file_id": {
                    "type": "string",
                    "description": "文档ID"
                },
                "sheet_name": {
                    "type": "string",
                    "description": "工作表名称（可选，默认第一个）"
                },
                "row": {
                    "type": "integer",
                    "description": "目标行号"
                },
                "col": {
                    "type": "integer",
                    "description": "目标列号"
                },
                "context_rows": {
                    "type": "integer",
                    "default": 5,
                    "description": "上下文行数"
                }
            },
            "required": ["file_id", "row", "col"]
        }

    async def execute(self, params: Dict[str, Any], context: ToolContext) -> ToolResult:
        """生成填充建议"""
        try:
            file_id = params.get("file_id", "")
            sheet_name = params.get("sheet_name")
            row = params.get("row")
            col = params.get("col")
            context_rows = params.get("context_rows", 5)

            if not file_id:
                return ToolResult(success=False, error="文档ID不能为空")

            if row is None or col is None:
                return ToolResult(success=False, error="行号和列号不能为空")

            # 验证UUID格式
            uuid_error = BaseTool.validate_uuid(file_id, "file_id")
            if uuid_error:
                return ToolResult(success=False, error=uuid_error)

            # 查询文档信息
            async with async_session() as db:
                result = await db.execute(
                    select(Document).where(Document.id == file_id)
                )
                doc = result.scalar_one_or_none()

                if not doc:
                    return ToolResult(success=False, error=f"文档不存在: {file_id}")

                if doc.file_type != "xlsx":
                    return ToolResult(success=False, error=f"不支持的文件类型: {doc.file_type}，仅支持xlsx")

                if not os.path.exists(doc.file_path):
                    return ToolResult(success=False, error=f"文件不存在: {doc.file_path}")

                # 使用openpyxl读取上下文
                try:
                    from openpyxl import load_workbook
                    wb = load_workbook(doc.file_path, data_only=True)

                    # 获取工作表
                    if sheet_name:
                        if sheet_name not in wb.sheetnames:
                            return ToolResult(
                                success=False,
                                error=f"工作表不存在: {sheet_name}，可用工作表: {wb.sheetnames}"
                            )
                        ws = wb[sheet_name]
                    else:
                        ws = wb.active

                    # 读取上下文数据
                    context_data = []
                    start_row = max(0, row - context_rows)
                    end_row = min(ws.max_row, row + context_rows)

                    for r in range(start_row, end_row + 1):
                        if r == row:
                            continue  # 跳过目标行
                        row_data = []
                        for c in range(max(0, col - 2), min(ws.max_column, col + 3)):
                            cell = ws.cell(row=r + 1, column=c + 1)
                            row_data.append(cell.value)
                        context_data.append({
                            "row": r,
                            "data": row_data
                        })

                    # 读取同列的其他值
                    column_values = []
                    for r in range(max(0, row - 10), min(ws.max_row, row + 10)):
                        if r == row:
                            continue
                        cell_value = ws.cell(row=r + 1, column=col + 1).value
                        if cell_value is not None:
                            column_values.append({"row": r, "value": cell_value})

                    wb.close()

                    # 使用LLM生成建议
                    from app.services.llm_service import llm_service

                    prompt = f"""根据以下上下文数据，为单元格 ({row}, {col}) 生成填充建议。

同列的其他值：
{column_values}

上下文行数据：
{context_data}

请返回JSON格式的建议，包含：
1. suggested_value: 建议的值
2. confidence: 置信度（0-1）
3. reason: 建议原因

只返回JSON，不要其他内容。"""

                    response = await llm_service.generate(
                        prompt=prompt,
                        max_tokens=200,
                        temperature=0
                    )

                    # 解析建议
                    try:
                        import json
                        suggestion = json.loads(response)
                    except:
                        suggestion = {
                            "suggested_value": None,
                            "confidence": 0,
                            "reason": "无法生成建议"
                        }

                    return ToolResult(
                        success=True,
                        data={
                            "file_id": file_id,
                            "sheet_name": ws.title,
                            "row": row,
                            "col": col,
                            "suggestion": suggestion,
                            "context_rows_count": len(context_data)
                        }
                    )

                except ImportError:
                    return ToolResult(success=False, error="openpyxl未安装，无法读取Excel")
                except Exception as e:
                    return ToolResult(success=False, error=f"生成填充建议失败: {str(e)}")

        except Exception as e:
            logger.exception(f"生成填充建议失败: {e}")
            return ToolResult(success=False, error=f"生成填充建议失败: {str(e)}")
