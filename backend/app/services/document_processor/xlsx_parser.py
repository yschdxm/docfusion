import openpyxl
from typing import Dict, List, Any
import pandas as pd
import re
import logging
import shutil
from datetime import datetime

logger = logging.getLogger(__name__)


class XlsxParser:
    @staticmethod
    def parse(file_path: str) -> Dict[str, Any]:
        workbook = openpyxl.load_workbook(file_path, data_only=True)

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

    @staticmethod
    def generate_metadata_summary(file_path: str, doc_id: str = "") -> List[Dict[str, Any]]:
        """Track 1: 生成元数据摘要 chunks（进向量库和图谱）。

        对每个 sheet 提取：
        - 列级摘要（列名、类型推断、值域）
        - 前 20 行样本数据
        - 枚举值（唯一值较少的列）
        """
        workbook = openpyxl.load_workbook(file_path, data_only=True)
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

    @staticmethod
    async def load_to_postgres(
        file_path: str,
        doc_id: str,
        db_execute=None,
        db_execute_many=None,
    ) -> List[Dict[str, Any]]:
        """Track 2: 将 xlsx 原始数据批量写入 PostgreSQL。

        Args:
            file_path: xlsx 文件路径
            doc_id: 文档 ID
            db_execute: 异步 SQL 执行函数
            db_execute_many: 异步批量 SQL 执行函数

        Returns:
            schema_info: [{"table_name": str, "columns": [{"name": str, "type": str}]}]
        """
        if db_execute is None:
            logger.warning("db_execute 未提供，跳过 PostgreSQL 入库")
            return []

        workbook = openpyxl.load_workbook(file_path, data_only=True)
        schema_info = []

        for sheet_name in workbook.sheetnames:
            sheet = workbook[sheet_name]
            rows = []
            for row in sheet.iter_rows(values_only=True):
                rows.append(row)

            if len(rows) < 2:
                continue

            headers = rows[0]
            data_rows = rows[1:]

            # 清理表头作为列名
            col_names = []
            for i, h in enumerate(headers):
                name = str(h).strip() if h and str(h).strip() else f"col_{i}"
                name = re.sub(r"[^\w\u4e00-\u9fff]", "_", name)
                col_names.append(name)

            # 清理 sheet 名作为表名
            safe_sheet = re.sub(r"[^\w\u4e00-\u9fff]", "_", sheet_name)
            table_name = f"{doc_id[:8]}_{safe_sheet}".lower()

            # 推断列类型
            col_types = []
            for col_idx in range(len(headers)):
                values = [str(r[col_idx]).strip() for r in data_rows if col_idx < len(r) and r[col_idx] is not None and str(r[col_idx]).strip()]
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
                await db_execute(
                    f'CREATE TABLE IF NOT EXISTS "{table_name}" ('
                    + ", ".join(col_defs)
                    + ")"
                )

                # 批量插入
                col_list = ", ".join([f'"{cn}"' for cn in col_names])
                param_list = ", ".join([f":{cn}" for cn in col_names])
                insert_sql = f'INSERT INTO "{table_name}" ({col_list}) VALUES ({param_list})'

                all_row_dicts = []
                for row in data_rows:
                    row_dict = {}
                    for col_idx in range(len(col_names)):
                        val = row[col_idx] if col_idx < len(row) else None
                        if val is None or (isinstance(val, str) and val.strip() == ""):
                            row_dict[col_names[col_idx]] = None
                        else:
                            row_dict[col_names[col_idx]] = str(val).strip()
                    all_row_dicts.append(row_dict)

                if db_execute_many and all_row_dicts:
                    # 分批执行，每批 500 行
                    for batch_start in range(0, len(all_row_dicts), 500):
                        batch = all_row_dicts[batch_start:batch_start + 500]
                        await db_execute_many(insert_sql, batch)
                else:
                    # 回退：逐行执行
                    for row_dict in all_row_dicts:
                        await db_execute(insert_sql, row_dict)

                # 对 ID/编号类列建索引
                for j, cn in enumerate(col_names):
                    if any(kw in cn.lower() for kw in ["id", "编号", "工号", "code", "no"]):
                        try:
                            await db_execute(
                                f'CREATE INDEX IF NOT EXISTS "idx_{table_name}_{cn}" ON "{table_name}" ("{cn}")'
                            )
                        except Exception:
                            pass

                schema_info.append({
                    "table_name": table_name,
                    "sheet_name": sheet_name,
                    "columns": [
                        {"name": col_names[j], "type": col_types[j] if j < len(col_types) else "string"}
                        for j in range(len(col_names))
                    ],
                    "row_count": len(data_rows),
                })
                logger.info(f"已将 sheet「{sheet_name}」写入 PostgreSQL 表 {table_name}，共 {len(data_rows)} 行")
            except Exception as e:
                logger.error(f"写入 PostgreSQL 失败: sheet={sheet_name}, error={e}")

        return schema_info

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
