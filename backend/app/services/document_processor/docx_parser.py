import shutil
import tempfile
import zipfile
from copy import deepcopy
from typing import Any, Dict, List

from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Pt
from docx.text.paragraph import Paragraph


class DocxParser:
    @staticmethod
    def parse(file_path: str) -> Dict[str, Any]:
        try:
            if not zipfile.is_zipfile(file_path):
                raise ValueError("文件不是有效的 docx 格式")
            try:
                doc = Document(file_path)
            except KeyError as exc:
                error_msg = str(exc)
                if "footnotes" in error_msg.lower() or "endnotes" in error_msg.lower():
                    doc = DocxParser._parse_with_missing_parts(file_path)
                else:
                    raise ValueError(f"docx 文件结构不完整: {error_msg}")
        except zipfile.BadZipFile:
            raise ValueError("文件损坏，不是有效的 docx 文件")
        except Exception as exc:
            if "docx" in str(exc) or "文件" in str(exc):
                raise
            raise ValueError(f"文件解析失败: {str(exc)}")

        content = []
        tables = []
        headings = []

        try:
            for source_index, para in enumerate(doc.paragraphs):
                if para.text.strip():
                    style_name = para.style.name if para.style else "Normal"
                    content.append({"text": para.text, "style": style_name, "source_index": source_index})
                    if style_name.startswith("Heading"):
                        level = int(style_name[-1]) if style_name[-1].isdigit() else 1
                        headings.append({"level": level, "text": para.text})
        except Exception:
            if not content:
                content = DocxParser._extract_text_from_zip(file_path)

        try:
            for table in doc.tables:
                table_data = []
                for row in table.rows:
                    table_data.append([cell.text for cell in row.cells])
                tables.append(table_data)
        except Exception:
            pass

        full_text = "\n".join([paragraph["text"] for paragraph in content])
        return {
            "full_text": full_text,
            "paragraphs": content,
            "headings": headings,
            "tables": tables,
        }

    @staticmethod
    def _parse_with_missing_parts(file_path: str) -> Document:
        temp_dir = tempfile.mkdtemp()
        temp_file = f"{temp_dir}/temp.docx"
        try:
            with zipfile.ZipFile(file_path, "r") as source_zip:
                with zipfile.ZipFile(temp_file, "w") as target_zip:
                    for item in source_zip.infolist():
                        target_zip.writestr(item, source_zip.read(item.filename))
                    if "word/footnotes.xml" not in source_zip.namelist():
                        target_zip.writestr(
                            "word/footnotes.xml",
                            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:footnotes xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"/>',
                        )
                    if "word/endnotes.xml" not in source_zip.namelist():
                        target_zip.writestr(
                            "word/endnotes.xml",
                            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:endnotes xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"/>',
                        )
            return Document(temp_file)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    @staticmethod
    def _extract_text_from_zip(file_path: str) -> List[Dict[str, Any]]:
        content = []
        try:
            with zipfile.ZipFile(file_path, "r") as zip_file:
                if "word/document.xml" not in zip_file.namelist():
                    return content
                import xml.etree.ElementTree as ET

                root = ET.fromstring(zip_file.read("word/document.xml"))
                ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
                for para in root.findall(".//w:p", ns):
                    texts = []
                    for text_elem in para.findall(".//w:t", ns):
                        if text_elem.text:
                            texts.append(text_elem.text)
                    if texts:
                        content.append({"text": "".join(texts), "style": "Normal"})
        except Exception:
            pass
        return content

    @staticmethod
    def write(content: str, output_path: str, format_info: Dict[str, Any] = None):
        doc = Document()

        paragraph_specs = (format_info or {}).get("paragraphs", [])
        if paragraph_specs:
            for paragraph in paragraph_specs:
                text = (paragraph.get("text") or "").strip()
                if not text:
                    continue
                style = paragraph.get("style") or "Normal"
                if style.startswith("Heading "):
                    level = 1
                    try:
                        level = max(1, min(6, int(style.split()[-1])))
                    except Exception:
                        level = 1
                    doc.add_heading(text, level=level)
                else:
                    para = doc.add_paragraph(text)
                    if style in {"List Bullet", "List Number"}:
                        para.style = style
        else:
            for para_text in content.split("\n"):
                if para_text.strip():
                    doc.add_paragraph(para_text)

        if format_info and "tables" in format_info:
            for table_data in format_info["tables"]:
                if not table_data:
                    continue
                rows_count = len(table_data)
                cols_count = len(table_data[0]) if table_data else 0
                if rows_count <= 0 or cols_count <= 0:
                    continue
                table = doc.add_table(rows=rows_count, cols=cols_count)
                for row_index, row_data in enumerate(table_data):
                    for col_index, cell_text in enumerate(row_data):
                        if col_index < len(table.rows[row_index].cells):
                            table.rows[row_index].cells[col_index].text = str(cell_text) if cell_text else ""

        doc.save(output_path)

    @staticmethod
    def load_document(file_path: str) -> Document:
        return Document(file_path)

    @staticmethod
    def get_content_paragraphs(doc: Document) -> List[Paragraph]:
        return [paragraph for paragraph in doc.paragraphs if paragraph.text.strip()]

    @staticmethod
    def replace_text_in_paragraph(paragraph: Paragraph, old_text: str, new_text: str) -> str:
        before = paragraph.text
        if not old_text:
            DocxParser._rewrite_paragraph_text(paragraph, new_text)
            return before

        for run in paragraph.runs:
            if old_text in run.text:
                run.text = run.text.replace(old_text, new_text)
                return before

        if old_text in before:
            DocxParser._rewrite_paragraph_text(paragraph, before.replace(old_text, new_text))
        return before

    @staticmethod
    def rewrite_paragraph(paragraph: Paragraph, new_text: str) -> str:
        before = paragraph.text
        DocxParser._rewrite_paragraph_text(paragraph, new_text)
        return before

    @staticmethod
    def insert_paragraph_after(paragraph: Paragraph, text: str, style_name: str = None) -> Paragraph:
        new_p = OxmlElement("w:p")
        paragraph._p.addnext(new_p)
        new_paragraph = Paragraph(new_p, paragraph._parent)

        if paragraph._p.pPr is not None:
            new_paragraph._p.append(deepcopy(paragraph._p.pPr))

        target_style = style_name or (paragraph.style.name if paragraph.style else None)
        if target_style:
            try:
                new_paragraph.style = target_style
            except Exception:
                pass

        run = new_paragraph.add_run(text)
        if paragraph.runs:
            DocxParser._copy_run_format(paragraph.runs[0], run)
        return new_paragraph

    @staticmethod
    def promote_heading(paragraph: Paragraph, level: int) -> str:
        before = paragraph.text
        paragraph.style = f"Heading {max(1, min(6, level))}"
        return before

    @staticmethod
    def save_document(doc: Document, output_path: str) -> None:
        doc.save(output_path)

    @staticmethod
    def _rewrite_paragraph_text(paragraph: Paragraph, new_text: str) -> None:
        if paragraph.runs:
            first_run = paragraph.runs[0]
            first_run.text = new_text
            for run in paragraph.runs[1:]:
                if run.text:
                    run.text = ""
            return

        paragraph.add_run(new_text)

    @staticmethod
    def _copy_run_format(source_run, target_run) -> None:
        target_run.bold = source_run.bold
        target_run.italic = source_run.italic
        target_run.underline = source_run.underline
        target_run.font.name = source_run.font.name
        target_run.font.size = source_run.font.size
        target_run.font.color.rgb = source_run.font.color.rgb
        target_run.font.highlight_color = source_run.font.highlight_color

    @staticmethod
    def set_paragraph_font(paragraph: Paragraph, font_name: str = "", font_size_pt: float = None) -> None:
        for run in paragraph.runs:
            if font_name:
                run.font.name = font_name
                r_pr = run._element.get_or_add_rPr()
                r_fonts = r_pr.rFonts
                if r_fonts is None:
                    r_fonts = OxmlElement("w:rFonts")
                    r_pr.append(r_fonts)
                r_fonts.set(qn("w:ascii"), font_name)
                r_fonts.set(qn("w:hAnsi"), font_name)
                r_fonts.set(qn("w:eastAsia"), font_name)
                r_fonts.set(qn("w:cs"), font_name)
            if font_size_pt is not None:
                run.font.size = Pt(float(font_size_pt))
