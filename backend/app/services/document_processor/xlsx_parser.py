import openpyxl
from typing import Dict, List, Any, Optional
import pandas as pd
import re
import logging
import shutil
from datetime import datetime

logger = logging.getLogger(__name__)


class XlsxParser:
    @staticmethod
    def load_workbook_once(file_path: str) -> openpyxl.Workbook:
        """只加载一次工作簿，返回 workbook 对象供后续复用。

        调用方负责在使用完毕后调用 workbook.close() 释放资源。
        """
        return openpyxl.load_workbook(file_path, data_only=True)

    @staticmethod
    def parse(file_path: str = None, workbook: Optional[openpyxl.Workbook] = None) -> Dict[str, Any]:
        """解析 xlsx 文件，支持传入已加载的 workbook 避免重复加载。"""
        should_close = False
        if workbook is None:
            if file_path is None:
                raise ValueError("file_path 和 workbook 不能同时为空")
            workbook = openpyxl.load_workbook(file_path, data_only=True)
            should_close = True

        try:
            sheets = []
            all_text = []

            for sheet_name in workbook.sheetnames:
                sheet = workbook[sheet_name]
                rows = []

                for row in sheet.iter_rows(values_only=True):
                    row_data = [str(cell) if cell is not None else "" for cell in row]
                    rows.append(row_data)
                    all_text.extend([cell for cell in row_data if cell])

                sheets.append({
                    "name": sheet_name,
                    "data": rows,
                    "rows": len(rows),
                    "cols": len(rows[0]) if rows else 0
                })

            full_text = "\n".join(all_text)

            return {
                "full_text": full_text,
                "sheets": sheets,
                "sheet_count": len(sheets)
            }
        finally:
            if should_close:
                workbook.close()

    @staticmethod
    def generate_metadata_summary(
        file_path: str = None,
        doc_id: str = "",
        workbook: Optional[openpyxl.Workbook] = None,
    ) -> List[Dict[str, Any]]:
        """Track 1: 生成元数据摘要 chunks（进向量库和图谱）。

        对每个 sheet 提取：
        - 列级摘要（列名、类型推断、值域）
        - 前 20 行样本数据
        - 枚举值（唯一值较少的列）

        支持传入已加载的 workbook 避免重复加载。
        """
        should_close = False
        if workbook is None:
            if file_path is None:
                raise ValueError("file_path 和 workbook 不能同时为空")
            workbook = openpyxl.load_workbook(file_path, data_only=True)
            should_close = True

        try:
            chunks = []
            chunk_index = 0

            for sheet_name in workbook.sheetnames:
                sheet = workbook[sheet_name]
                rows = []
                for row in sheet.iter_rows(values_only=True):
                    row_data = [str(cell) if cell is not None else "" for cell in row]
                    rows.append(row_data)

                if len(rows) < 2:
                    continue

                headers = rows[0]
                data_rows = rows[1:]
                valid_headers = [str(h) for h in headers if h and str(h).strip()]

                # 推断每列数据类型
                col_types = []
                col_stats = []
                for col_idx in range(len(headers)):
                    col_values = []
                    for row in data_rows:
                        if col_idx < len(row) and row[col_idx] and row[col_idx].strip():
                            col_values.append(row[col_idx].strip())

                    col_type, type_desc = _infer_column_type(col_values)
                    col_types.append(col_type)

                    # 统计信息
                    stats = {}
                    if col_type in ("int", "float"):
                        nums = []
                        for v in col_values:
                            try:
                                nums.append(float(v.replace(",", "").replace(" ", "")))
                            except ValueError:
                                pass
                        if nums:
                            stats = {
                                "min": min(nums),
                                "max": max(nums),
                                "avg": sum(nums) / len(nums),
                                "count": len(nums),
                            }
                    elif col_type == "string":
                        unique_vals = list(set(col_values))
                        if len(unique_vals) <= 50:
                            stats = {"enum_values": unique_vals[:50]}
                    col_stats.append(stats)

                # 生成列级摘要文本
                col_descs = []
                for i, header in enumerate(headers):
                    if header and str(header).strip():
                        h = str(header).strip()
                        t = col_types[i] if i < len(col_types) else "string"
                        s = col_stats[i] if i < len(col_stats) else {}
                        desc = f"{h}({t}"
                        if "min" in s:
                            desc += f",范围{int(s['min'])}-{int(s['max'])}"
                        elif "enum_values" in s:
                            desc += f",枚举值:{','.join(s['enum_values'][:10])}"
                        desc += ")"
                        col_descs.append(desc)

                summary_text = f"文件{doc_id}，Sheet「{sheet_name}」，共{len(data_rows)}行数据，包含列：" + "、".join(col_descs)
                chunks.append({
                    "content": summary_text,
                    "chunk_index": chunk_index,
                    "chunk_type": "column_summary",
                    "section_path": sheet_name,
                })
                chunk_index += 1

                # 前 20 行样本数据转文本
                sample_rows = data_rows[:20]
                if sample_rows:
                    sample_lines = ["| " + " | ".join(valid_headers) + " |"]
                    sample_lines.append("| " + " | ".join(["---"] * len(valid_headers)) + " |")
                    for row in sample_rows:
                        row_cells = [str(cell) if cell else "" for cell in row[:len(headers)]]
                        sample_lines.append("| " + " | ".join(row_cells) + " |")
                    sample_text = f"Sheet「{sheet_name}」数据样本（前{len(sample_rows)}行）：\n" + "\n".join(sample_lines)
                    chunks.append({
                        "content": sample_text,
                        "chunk_index": chunk_index,
                        "chunk_type": "sample_data",
                        "section_path": sheet_name,
                    })
                    chunk_index += 1

                # 枚举值列单独提取
                for i, header in enumerate(headers):
                    if header and str(header).strip() and i < len(col_stats):
                        s = col_stats[i]
                        if "enum_values" in s and len(s["enum_values"]) <= 20:
                            enum_text = f"Sheet「{sheet_name}」列「{str(header).strip()}」的所有取值：" + "、".join(s["enum_values"])
                            chunks.append({
                                "content": enum_text,
                                "chunk_index": chunk_index,
                                "chunk_type": "column_summary",
                                "section_path": sheet_name,
                            })
                            chunk_index += 1

            return chunks
        finally:
            if should_close:
                workbook.close()

    @staticmethod
    async def load_to_postgres(
        file_path: str = None,
        doc_id: str = "",
        db_execute=None,
        db_execute_many=None,
        workbook: Optional[openpyxl.Workbook] = None,
        conn=None,
    ) -> List[Dict[str, Any]]:
        """Track 2: 将 xlsx 原始数据批量写入 PostgreSQL。

        优化特性：
        - 支持传入已加载的 workbook 避免重复加载
        - 流式读取 + 分批处理，内存占用 O(BATCH_SIZE) 而非 O(N)
        - 支持传入 conn 复用数据库连接，单事务提交
        - 索引延迟到最后统一创建

        Args:
            file_path: xlsx 文件路径
            doc_id: 文档 ID
            db_execute: 异步 SQL 执行函数（当 conn 未提供时使用）
            db_execute_many: 异步批量 SQL 执行函数（当 conn 未提供时使用）
            workbook: 已加载的 workbook 对象（可选，避免重复加载）
            conn: 已有的数据库连接（可选，复用连接）

        Returns:
            schema_info: [{"table_name": str, "columns": [{"name": str, "type": str}]}]
        """
        if db_execute is None and conn is None:
            logger.warning("db_execute 和 conn 均未提供，跳过 PostgreSQL 入库")
            return []

        should_close_workbook = False
        if workbook is None:
            if file_path is None:
                raise ValueError("file_path 和 workbook 不能同时为空")
            workbook = openpyxl.load_workbook(file_path, data_only=True)
            should_close_workbook = True

        try:
            schema_info = []
            BATCH_SIZE = 500

            for sheet_name in workbook.sheetnames:
                sheet = workbook[sheet_name]

                # 先读取第一行（表头）和前几行用于推断类型
                first_rows = []
                for i, row in enumerate(sheet.iter_rows(values_only=True)):
                    first_rows.append(row)
                    if i >= 100:  # 读取前 101 行用于类型推断
                        break

                if len(first_rows) < 2:
                    continue

                headers = first_rows[0]
                sample_rows = first_rows[1:]

                # 清理表头作为列名
                col_names = []
                for i, h in enumerate(headers):
                    name = str(h).strip() if h and str(h).strip() else f"col_{i}"
                    name = re.sub(r"[^\w一-鿿]", "_", name)
                    col_names.append(name)

                # 清理 sheet 名作为表名
                safe_sheet = re.sub(r"[^\w一-鿿]", "_", sheet_name)
                table_name = f"{doc_id[:8]}_{safe_sheet}".lower()

                # 基于样本数据推断列类型
                col_types = []
                for col_idx in range(len(headers)):
                    values = [
                        str(r[col_idx]).strip()
                        for r in sample_rows
                        if col_idx < len(r) and r[col_idx] is not None and str(r[col_idx]).strip()
                    ]
                    col_type, _ = _infer_column_type(values)
                    col_types.append(col_type)

                # 创建表
                col_defs = []
                for j, cn in enumerate(col_names):
                    pg_type = "TEXT"
                    if j < len(col_types):
                        if col_types[j] == "int":
                            pg_type = "BIGINT"
                        elif col_types[j] == "float":
                            pg_type = "DOUBLE PRECISION"
                        elif col_types[j] == "date":
                            pg_type = "DATE"
                    col_defs.append(f'"{cn}" {pg_type}')

                try:
                    # 执行建表语句
                    create_sql = f'CREATE TABLE IF NOT EXISTS "{table_name}" ({", ".join(col_defs)})'
                    if conn:
                        from sqlalchemy import text as sa_text
                        await conn.execute(sa_text(create_sql))
                    else:
                        await db_execute(create_sql)

                    # 建表成功后立即记录 schema（即使数据插入失败，删除时也能找到表名）
                    schema_info.append({
                        "table_name": table_name,
                        "sheet_name": sheet_name,
                        "columns": [
                            {"name": col_names[j], "type": col_types[j] if j < len(col_types) else "string"}
                            for j in range(len(col_names))
                        ],
                        "row_count": 0,
                    })

                    # 准备插入 SQL
                    col_list = ", ".join([f'"{cn}"' for cn in col_names])
                    param_list = ", ".join([f":{cn}" for cn in col_names])
                    insert_sql = f'INSERT INTO "{table_name}" ({col_list}) VALUES ({param_list})'

                    # 流式读取 + 分批插入（使用类型转换）
                    total_rows = 0
                    batch = []

                    def _build_row_dict(row):
                        row_dict = {}
                        for col_idx in range(len(col_names)):
                            val = row[col_idx] if col_idx < len(row) else None
                            row_dict[col_names[col_idx]] = _convert_value(val, col_types[col_idx] if col_idx < len(col_types) else "string")
                        return row_dict

                    # 先处理已读取的 sample_rows（跳过第 0 行表头）
                    for row in sample_rows:
                        batch.append(_build_row_dict(row))
                        total_rows += 1

                        if len(batch) >= BATCH_SIZE:
                            if conn:
                                from sqlalchemy import text as sa_text
                                await conn.execute(sa_text(insert_sql), batch)
                            else:
                                await db_execute_many(insert_sql, batch)
                            batch = []

                    # 继续读取剩余行（从 first_rows 之后开始）
                    row_iter = sheet.iter_rows(min_row=len(first_rows) + 1, values_only=True)
                    for row in row_iter:
                        batch.append(_build_row_dict(row))
                        total_rows += 1

                        if len(batch) >= BATCH_SIZE:
                            if conn:
                                from sqlalchemy import text as sa_text
                                await conn.execute(sa_text(insert_sql), batch)
                            else:
                                await db_execute_many(insert_sql, batch)
                            batch = []

                    # 处理最后一批
                    if batch:
                        if conn:
                            from sqlalchemy import text as sa_text
                            await conn.execute(sa_text(insert_sql), batch)
                        else:
                            await db_execute_many(insert_sql, batch)

                    # 收集需要创建索引的列（延迟创建）
                    index_columns = []
                    for j, cn in enumerate(col_names):
                        if any(kw in cn.lower() for kw in ["id", "编号", "工号", "code", "no"]):
                            index_columns.append(cn)

                    # 创建索引（在同一连接中批量执行）
                    for cn in index_columns:
                        try:
                            idx_sql = f'CREATE INDEX IF NOT EXISTS "idx_{table_name}_{cn}" ON "{table_name}" ("{cn}")'
                            if conn:
                                from sqlalchemy import text as sa_text
                                await conn.execute(sa_text(idx_sql))
                            else:
                                await db_execute(idx_sql)
                        except Exception:
                            pass

                    # 更新行数
                    schema_info[-1]["row_count"] = total_rows
                    logger.info(f"已将 sheet「{sheet_name}」写入 PostgreSQL 表 {table_name}，共 {total_rows} 行")
                except Exception as e:
                    logger.error(f"写入 PostgreSQL 失败: sheet={sheet_name}, error={e}")

            return schema_info
        finally:
            if should_close_workbook:
                workbook.close()

    @staticmethod
    def parse_with_pandas(file_path: str) -> Dict[str, Any]:
        sheets = {}
        excel_file = pd.ExcelFile(file_path)

        for sheet_name in excel_file.sheet_names:
            df = pd.read_excel(file_path, sheet_name=sheet_name)
            sheets[sheet_name] = {
                "columns": df.columns.tolist(),
                "data": df.to_dict(orient="records"),
                "shape": df.shape
            }

        return sheets

    @staticmethod
    def write(data: List[List[Any]], output_path: str, sheet_name: str = "Sheet1"):
        workbook = openpyxl.Workbook()
        sheet = workbook.active
        sheet.title = sheet_name

        for row_data in data:
            sheet.append(row_data)

        workbook.save(output_path)

    @staticmethod
    def write_from_dict(data: Dict[str, Any], output_path: str):
        workbook = openpyxl.Workbook()

        first_sheet = True
        for sheet_name, sheet_data in data.items():
            if first_sheet:
                sheet = workbook.active
                sheet.title = sheet_name
                first_sheet = False
            else:
                sheet = workbook.create_sheet(sheet_name)

            if "data" in sheet_data and isinstance(sheet_data["data"], list):
                for row_data in sheet_data["data"]:
                    if isinstance(row_data, list):
                        sheet.append(row_data)
            elif "columns" in sheet_data:
                sheet.append(sheet_data["columns"])
                for row_data in sheet_data.get("data", []):
                    if isinstance(row_data, dict):
                        sheet.append(list(row_data.values()))
                    elif isinstance(row_data, list):
                        sheet.append(row_data)

        workbook.save(output_path)

    @staticmethod
    def write_from_dict_on_template(data: Dict[str, Any], template_path: str, output_path: str):
        """在模板基础上填充数据，保留原有格式（合并单元格、列宽、样式等）。"""
        shutil.copy2(template_path, output_path)
        workbook = openpyxl.load_workbook(output_path)

        for sheet_name, sheet_data in data.items():
            if sheet_name in workbook.sheetnames:
                sheet = workbook[sheet_name]
            elif workbook.active.title not in data:
                sheet = workbook.active
                sheet.title = sheet_name
            else:
                sheet = workbook.create_sheet(sheet_name)

            if "data" in sheet_data and isinstance(sheet_data["data"], list):
                for row_idx, row_data in enumerate(sheet_data["data"], start=1):
                    if isinstance(row_data, list):
                        for col_idx, cell_value in enumerate(row_data, start=1):
                            sheet.cell(row=row_idx, column=col_idx, value=cell_value)

        workbook.save(output_path)


def _convert_value(val, col_type: str):
    """根据列类型转换值，确保类型匹配数据库列定义。"""
    if val is None or (isinstance(val, str) and val.strip() == ""):
        return None
    if isinstance(val, (int, float)):
        if col_type == "int":
            return int(val)
        elif col_type == "float":
            return float(val)
        return val
    s = str(val).strip()
    if not s:
        return None
    if col_type == "int":
        try:
            return int(s.replace(",", "").replace(" ", ""))
        except ValueError:
            return None
    elif col_type == "float":
        try:
            return float(s.replace(",", "").replace(" ", ""))
        except ValueError:
            return None
    return s


def _infer_column_type(values: List[str]) -> tuple:
    """推断列数据类型。

    Returns:
        (type_name, type_description)
    """
    if not values:
        return "string", "字符串"

    int_count = 0
    float_count = 0
    date_count = 0
    total = len(values)

    for v in values[:100]:  # 只检查前 100 个值
        v = v.replace(",", "").replace(" ", "").replace("，", "")
        # 尝试整数
        try:
            int(v)
            int_count += 1
            continue
        except ValueError:
            pass
        # 尝试浮点数
        try:
            float(v)
            float_count += 1
            continue
        except ValueError:
            pass
        # 尝试日期
        for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y年%m月%d日", "%m/%d/%Y", "%d/%m/%Y"):
            try:
                datetime.strptime(v, fmt)
                date_count += 1
                break
            except ValueError:
                pass

    if int_count / total > 0.8:
        return "int", "整数"
    if (int_count + float_count) / total > 0.8:
        return "float", "浮点数"
    if date_count / total > 0.5:
        return "date", "日期"
    return "string", "字符串"
