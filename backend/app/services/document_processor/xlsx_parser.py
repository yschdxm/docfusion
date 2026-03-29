import openpyxl
from typing import Dict, List, Any
import pandas as pd


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
        
        for sheet_name, sheet_data in data.items():
            if workbook.active.title == "Sheet":
                sheet = workbook.active
                sheet.title = sheet_name
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
