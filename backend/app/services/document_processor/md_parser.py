import markdown
from bs4 import BeautifulSoup
from typing import Dict, Any
from .chunker import chunk_by_sections, chunk_table


class MdParser:
    @staticmethod
    def parse(file_path: str) -> Dict[str, Any]:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
        
        html = markdown.markdown(content, extensions=["tables", "fenced_code"])
        soup = BeautifulSoup(html, "html.parser")
        
        headings = []
        for level in range(1, 7):
            for h in soup.find_all(f"h{level}"):
                headings.append({
                    "level": level,
                    "text": h.get_text()
                })
        
        tables = []
        for table in soup.find_all("table"):
            table_data = []
            for row in table.find_all("tr"):
                row_data = [cell.get_text().strip() for cell in row.find_all(["td", "th"])]
                table_data.append(row_data)
            tables.append(table_data)
        
        paragraphs = [p.get_text() for p in soup.find_all("p") if p.get_text().strip()]
        
        code_blocks = [code.get_text() for code in soup.find_all("code")]

        # 构建段落列表用于分块
        para_list = []
        for h in headings:
            para_list.append({"text": h["text"], "style": f"Heading {h['level']}"})
        for p in paragraphs:
            para_list.append({"text": p, "style": "Normal"})

        # 生成结构化 chunks
        chunks = chunk_by_sections(para_list, headings)
        chunk_idx = len(chunks)
        for table_data in tables:
            table_chunks = chunk_table(table_data)
            for tc in table_chunks:
                tc["chunk_index"] = chunk_idx
                chunk_idx += 1
            chunks.extend(table_chunks)

        return {
            "full_text": content,
            "html": html,
            "headings": headings,
            "tables": tables,
            "paragraphs": paragraphs,
            "code_blocks": code_blocks,
            "chunks": chunks,
        }
    
    @staticmethod
    def write(content: str, output_path: str, format_info: Dict = None):
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(content)
