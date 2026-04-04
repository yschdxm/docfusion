from typing import Dict, Any
from .chunker import chunk_by_paragraphs


class TxtParser:
    @staticmethod
    def parse(file_path: str) -> Dict[str, Any]:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
        
        lines = content.split("\n")
        paragraphs = [line for line in lines if line.strip()]
        
        return {
            "full_text": content,
            "lines": lines,
            "paragraphs": paragraphs,
            "line_count": len(lines),
            "char_count": len(content),
            "chunks": chunk_by_paragraphs(content),
        }
    
    @staticmethod
    def write(content: str, output_path: str):
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(content)
