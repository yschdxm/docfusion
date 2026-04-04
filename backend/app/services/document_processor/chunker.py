"""共享分块工具 — 按章节/段落分块，适配 bge-m3 嵌入模型"""
from typing import List, Dict, Any


# 默认分块参数（bge-m3 支持 8192 token，大文档用较大块减少总块数）
DEFAULT_CHUNK_SIZE = 2500
DEFAULT_OVERLAP = 200
MIN_CHUNK_SIZE = 200


def chunk_by_sections(
    paragraphs: List[Dict[str, Any]],
    headings: List[Dict[str, Any]],
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    overlap: int = DEFAULT_OVERLAP,
) -> List[Dict[str, Any]]:
    """按标题层级分组段落，再在每个 section 内部分块。

    Args:
        paragraphs: [{"text": "...", "style": "Heading 1" | "Normal" | ...}, ...]
        headings: [{"level": 1, "text": "..."}, ...]
        chunk_size: 目标块大小（字符数）
        overlap: 相邻块重叠字符数

    Returns:
        [{"content": str, "chunk_index": int, "chunk_type": "text", "section_path": str}, ...]
    """
    if not paragraphs:
        return []

    # 构建 heading 位置索引：heading_text -> 它在 paragraphs 中的索引
    heading_positions = []
    for i, para in enumerate(paragraphs):
        style = para.get("style", "") or ""
        if "Heading" in style:
            level = int(style[-1]) if style[-1].isdigit() else 1
            heading_positions.append((i, level, para["text"]))

    # 按 heading 切分 sections
    sections = []  # [(section_path, [paragraph_texts])]
    current_path: List[str] = []
    current_texts: List[str] = []
    heading_idx = 0

    for i, para in enumerate(paragraphs):
        # 检查是否是 heading
        is_heading = False
        if heading_idx < len(heading_positions) and heading_positions[heading_idx][0] == i:
            _, level, text = heading_positions[heading_idx]
            heading_idx += 1
            is_heading = True

            # 先保存之前 section 的内容
            if current_texts:
                sections.append((" > ".join(current_path), current_texts))
                current_texts = []

            # 更新路径
            while len(current_path) >= level:
                current_path.pop()
            current_path.append(text)

        if not is_heading and para.get("text", "").strip():
            current_texts.append(para["text"])

    # 最后一个 section
    if current_texts:
        sections.append((" > ".join(current_path), current_texts))

    # 如果没有任何 heading，整个文档作为一个 section
    if not sections:
        all_texts = [p["text"] for p in paragraphs if p.get("text", "").strip()]
        sections.append(("", all_texts))

    # 在每个 section 内部分块
    chunks = []
    chunk_index = 0
    for section_path, texts in sections:
        section_text = "\n".join(texts)
        if not section_text.strip():
            continue

        sub_chunks = _split_text(section_text, chunk_size, overlap)
        for content in sub_chunks:
            chunks.append({
                "content": content,
                "chunk_index": chunk_index,
                "chunk_type": "text",
                "section_path": section_path,
            })
            chunk_index += 1

    return chunks


def chunk_by_paragraphs(
    text: str,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    overlap: int = DEFAULT_OVERLAP,
) -> List[Dict[str, Any]]:
    """按段落分块，适合 md/txt 文件。

    Args:
        text: 完整文本
        chunk_size: 目标块大小
        overlap: 重叠大小

    Returns:
        [{"content": str, "chunk_index": int, "chunk_type": "text", "section_path": ""}, ...]
    """
    if not text.strip():
        return []

    # 按双换行分段
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    if not paragraphs:
        paragraphs = [text.strip()]

    merged_text = "\n".join(paragraphs)
    sub_chunks = _split_text(merged_text, chunk_size, overlap)

    return [
        {
            "content": content,
            "chunk_index": i,
            "chunk_type": "text",
            "section_path": "",
        }
        for i, content in enumerate(sub_chunks)
    ]


def chunk_table(
    table_data: List[List[str]],
    sheet_name: str = "",
    chunk_size: int = DEFAULT_CHUNK_SIZE,
) -> List[Dict[str, Any]]:
    """将表格数据转为文本 chunk。

    Args:
        table_data: 二维列表，第一行为表头
        sheet_name: sheet 名称
        chunk_size: 目标块大小

    Returns:
        [{"content": str, "chunk_index": int, "chunk_type": "table", "section_path": str}, ...]
    """
    if not table_data:
        return []

    headers = table_data[0]
    valid_headers = [str(h) for h in headers if h]
    header_line = "| " + " | ".join(valid_headers) + " |"
    separator = "| " + " | ".join(["---"] * len(valid_headers)) + " |"

    chunks = []
    chunk_index = 0
    current_lines = [header_line, separator]
    current_len = len(header_line) + len(separator)

    for row in table_data[1:]:
        row_cells = [str(cell) if cell else "" for cell in row[:len(headers)]]
        row_line = "| " + " | ".join(row_cells) + " |"

        if current_len + len(row_line) > chunk_size and len(current_lines) > 2:
            # 当前块已满，保存并开始新块
            chunks.append({
                "content": "\n".join(current_lines),
                "chunk_index": chunk_index,
                "chunk_type": "table",
                "section_path": sheet_name,
            })
            chunk_index += 1
            current_lines = [header_line, separator, row_line]
            current_len = len(header_line) + len(separator) + len(row_line)
        else:
            current_lines.append(row_line)
            current_len += len(row_line)

    # 最后一块
    if len(current_lines) > 2:
        chunks.append({
            "content": "\n".join(current_lines),
            "chunk_index": chunk_index,
            "chunk_type": "table",
            "section_path": sheet_name,
        })

    return chunks


def _split_text(
    text: str,
    chunk_size: int,
    overlap: int,
) -> List[str]:
    """将文本按 chunk_size 切分，智能在标点处断开，保留 overlap 重叠。"""
    if len(text) <= chunk_size:
        return [text]

    chunks = []
    start = 0

    while start < len(text):
        end = start + chunk_size

        if end < len(text):
            # 向后查找最近的句号、问号、感叹号、换行
            best_break = end
            search_range = min(end + 200, len(text))
            for i in range(search_range, max(end - 200, start), -1):
                if i < len(text) and text[i - 1] in "。！？\n；":
                    best_break = i
                    break
            end = best_break

        chunk = text[start:end].strip()
        if len(chunk) >= MIN_CHUNK_SIZE or end >= len(text):
            chunks.append(chunk)

        start = end - overlap
        if start >= len(text):
            break

    return chunks
