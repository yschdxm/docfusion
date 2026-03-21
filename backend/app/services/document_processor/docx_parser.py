from docx import Document
from typing import Dict, List, Any
import io


class DocxParser:
    @staticmethod
    def parse(file_path: str) -> Dict[str, Any]:
        doc = Document(file_path)
        
        content = []
        tables = []
        headings = []
        
        for para in doc.paragraphs:
            if para.text.strip():
                content.append({
                    "text": para.text,
                    "style": para.style.name if para.style else None
                })
                if para.style and "Heading" in para.style.name:
                    headings.append({
                        "level": int(para.style.name[-1]) if para.style.name[-1].isdigit() else 1,
                        "text": para.text
                    })
        
        for table in doc.tables:
            table_data = []
            for row in table.rows:
                row_data = [cell.text for cell in row.cells]
                table_data.append(row_data)
            tables.append(table_data)
        
        full_text = "\n".join([p["text"] for p in content])
        
        return {
            "full_text": full_text,
            "paragraphs": content,
            "headings": headings,
            "tables": tables
        }
    
    @staticmethod
    def write(content: str, output_path: str, format_info: Dict = None):
        doc = Document()
        
        if format_info and "headings" in format_info:
            for heading in format_info["headings"]:
                doc.add_heading(heading["text"], level=heading.get("level", 1))
        
        for para_text in content.split("\n"):
            if para_text.strip():
                doc.add_paragraph(para_text)
        
        doc.save(output_path)
