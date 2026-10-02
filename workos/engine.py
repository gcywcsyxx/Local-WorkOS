"""Deterministic, local-only WorkOS domain logic (Python 3.11+).

No network, model calls, filesystem reads, or document macro execution occur here.
Rates are decimal fractions, money is RMB millions, chunk ordinals are 1-based.
PDF page numbers are physical 1-based pages; unpaginated sources use ``None``.
"""
from __future__ import annotations

from datetime import date
import hashlib
from io import BytesIO
import math
from pathlib import PurePosixPath
import re
import stat
import unicodedata
from xml.etree import ElementTree
import zipfile

MAX_UPLOAD_BYTES = 20 * 1024 * 1024
MAX_OFFICE_ENTRIES = 5000
MAX_OFFICE_EXPANDED_BYTES = 128 * 1024 * 1024
MAX_OFFICE_MEMBER_BYTES = 32 * 1024 * 1024
MAX_XLSX_CELLS = 100_000
MAX_PPTX_SLIDES = 500
MAX_TEXT_CHARS = 2_000_000
MAX_DOCX_EXPANDED_BYTES = 32 * 1024 * 1024
MAX_DOCX_MEMBER_BYTES = 12 * 1024 * 1024
MAX_PDF_PAGES = 500
_CHUNK_SIZE = 900
_CHUNK_OVERLAP = 100
_WORD_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def _text(value: object, label: str, *, maximum: int = MAX_TEXT_CHARS) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{label}必须是文本。")
    if len(value) > maximum:
        raise ValueError(f"{label}过长，最多允许 {maximum} 个字符。")
    return value.replace("\r\n", "\n").replace("\r", "\n")


def _unpaginated(content: str, warnings: list[str]) -> dict:
    content = content.strip()
    if not content:
        raise ValueError("文件没有可读取的正文文字。")
    if len(content) > MAX_TEXT_CHARS:
        raise ValueError("文件提取后的文字超过安全大小限制。")
    return {"content": content, "page_count": 1,
            "pages": [{"page": None, "text": content}], "warnings": warnings}


def _parse_docx(data: bytes) -> dict:
    warnings = ["DOCX 仅提取正文和表格文字，无法确定排版页码；引用使用段落定位。",
                "不会执行宏、嵌入对象或加载外部链接；页眉、图片和批注未提取。"]
    try:
        with zipfile.ZipFile(BytesIO(data)) as archive:
            members = archive.infolist()
            if len(members) > 2048:
                raise ValueError("DOCX 包含过多压缩条目。")
            total = 0
            names: set[str] = set()
            for member in members:
                name = member.filename.replace("\\", "/")
                parts = PurePosixPath(name).parts
                if (not name or name.startswith("/") or "\x00" in name or ":" in name
                        or ".." in parts or stat.S_ISLNK(member.external_attr >> 16)):
                    raise ValueError("DOCX 包含不安全的压缩路径或符号链接。")
                if name in names:
                    raise ValueError("DOCX 包含重复的压缩路径。")
                names.add(name)
                if member.flag_bits & 1:
                    raise ValueError("不支持加密的 DOCX 文件。")
                if member.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
                    raise ValueError("DOCX 使用了不支持的压缩格式。")
                total += member.file_size
                if (member.file_size > MAX_DOCX_MEMBER_BYTES
                        or total > MAX_DOCX_EXPANDED_BYTES
                        or (member.file_size > 1024 * 1024
                            and member.file_size > max(member.compress_size, 1) * 1000)):
                    raise ValueError("DOCX 解压量或压缩比超过安全限制。")
            if "word/document.xml" not in names:
                raise ValueError("DOCX 缺少正文 word/document.xml。")
            with archive.open("word/document.xml") as stream:
                xml = stream.read(MAX_DOCX_MEMBER_BYTES + 1)
            if len(xml) > MAX_DOCX_MEMBER_BYTES:
                raise ValueError("DOCX 正文解压量超过安全限制。")
        # Reject DTD/entity definitions even for UTF-16 encoded XML.
        xml_probe = xml.replace(b"\x00", b"").upper()
        if b"<!DOCTYPE" in xml_probe or b"<!ENTITY" in xml_probe:
            raise ValueError("DOCX 正文包含不允许的 XML 实体或文档类型声明。")
        root = ElementTree.fromstring(xml)
        if root.tag != _WORD_NS + "document":
            raise ValueError("DOCX 正文 XML 格式不受支持。")
        paragraphs = []
        for paragraph in root.iter(_WORD_NS + "p"):
            pieces = []
            for node in paragraph.iter():
                if node.tag == _WORD_NS + "t":
                    pieces.append(node.text or "")
                elif node.tag == _WORD_NS + "tab":
                    pieces.append("\t")
                elif node.tag in (_WORD_NS + "br", _WORD_NS + "cr"):
                    pieces.append("\n")
            text = "".join(pieces).strip()
            if text:
                paragraphs.append(text)
        return _unpaginated("\n".join(paragraphs), warnings)
    except Exception as exc:
        if isinstance(exc, ValueError) and re.search(r"[\u3400-\u9fff]", str(exc)):
            raise  # Preserve the Chinese validation messages above.
        raise ValueError("DOCX 文件损坏或正文无法解析。") from exc


def _validate_office_zip(data: bytes, expected: str, label: str):
    try:
        with zipfile.ZipFile(BytesIO(data)) as archive:
            members = archive.infolist()
            if len(members) > MAX_OFFICE_ENTRIES:
                raise ValueError(f'{label} 包含过多压缩条目。')
            total = 0
            names = set()
            for member in members:
                name = member.filename.replace('\\', '/')
                parts = PurePosixPath(name).parts
                if (not name or name.startswith('/') or '\x00' in name or ':' in name
                        or '..' in parts or stat.S_ISLNK(member.external_attr >> 16)):
                    raise ValueError(f'{label} 包含不安全的压缩路径或符号链接。')
                if name in names:
                    raise ValueError(f'{label} 包含重复的压缩路径。')
                names.add(name)
                if member.flag_bits & 1:
                    raise ValueError(f'不支持加密的 {label} 文件。')
                if member.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
                    raise ValueError(f'{label} 使用了不支持的压缩格式。')
                total += member.file_size
                if (member.file_size > MAX_OFFICE_MEMBER_BYTES or total > MAX_OFFICE_EXPANDED_BYTES
                        or (member.file_size > 1024 * 1024 and member.file_size > max(member.compress_size, 1) * 1000)):
                    raise ValueError(f'{label} 解压量或压缩比超过安全限制。')
            if expected not in names:
                raise ValueError(f'{label} 缺少必要的包结构。')
    except zipfile.BadZipFile as exc:
        raise ValueError(f'{label} 不是有效的 Office 压缩文件。') from exc


def _office_value(value):
    if value is None:
        return ''
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, float):
        return format(value, '.12g')
    return str(value).replace('\r', ' ').replace('\n', ' ').strip()


def _parse_pptx(data: bytes) -> dict:
    _validate_office_zip(data, 'ppt/presentation.xml', 'PPTX')
    try:
        from pptx import Presentation
        presentation = Presentation(BytesIO(data))
        if len(presentation.slides) > MAX_PPTX_SLIDES:
            raise ValueError(f'PPTX 超过 {MAX_PPTX_SLIDES} 页的安全限制。')
        pages = []
        total_chars = 0
        warnings = ['PPTX 提取文本和表格；图片、备注及复杂图表版式可能不完整，公式/图表不在此重算。']
        for index, slide in enumerate(presentation.slides, 1):
            pieces = []
            for shape in slide.shapes:
                if getattr(shape, 'has_text_frame', False):
                    text = shape.text.strip()
                    if text:
                        pieces.append(text)
                if getattr(shape, 'has_table', False):
                    for row in shape.table.rows:
                        line = ' | '.join(cell.text.strip() for cell in row.cells)
                        if line.strip(' |'):
                            pieces.append(line)
                if getattr(shape, 'has_chart', False):
                    chart = shape.chart
                    if chart.has_title:
                        pieces.append('图表标题: ' + chart.chart_title.text_frame.text.strip())
                    for series in chart.series:
                        values = list(series.values)[:100]
                        pieces.append('图表序列 ' + str(series.name) + ': ' + ', '.join(_office_value(value) for value in values))
            text = 'Slide ' + str(index) + '\n' + '\n'.join(pieces)
            total_chars += len(text)
            if total_chars > MAX_TEXT_CHARS:
                raise ValueError('PPTX 提取文字超过安全大小限制。')
            pages.append({'page': index, 'text': text})
        content = '\n\n'.join(page['text'] for page in pages)
        return {'content': content, 'page_count': max(1, len(pages)), 'pages': pages, 'warnings': warnings}
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError('PPTX 文件损坏或文本结构无法解析。') from exc


def _parse_xlsx(data: bytes, *, macro_enabled=False) -> dict:
    _validate_office_zip(data, 'xl/workbook.xml', 'Excel')
    try:
        from openpyxl import load_workbook
        formula_book = load_workbook(BytesIO(data), read_only=True, data_only=False, keep_links=False, keep_vba=False)
        value_book = load_workbook(BytesIO(data), read_only=True, data_only=True, keep_links=False, keep_vba=False)
        try:
            if len(formula_book.worksheets) > MAX_OFFICE_ENTRIES:
                raise ValueError('Excel 工作表数量超过安全限制。')
            pages = []
            warnings = ['公式未重算；缓存值可能过期。不会执行宏、刷新外部链接或修改原工作簿。']
            if macro_enabled:
                warnings.append('XLSM 按只读方式提取单元格；VBA 宏不会执行或写回。')
            cell_count = 0
            total_chars = 0
            for sheet_index, formula_sheet in enumerate(formula_book.worksheets, 1):
                value_sheet = value_book[formula_sheet.title]
                label = 'Sheet ' + str(sheet_index) + ': ' + formula_sheet.title
                if formula_sheet.sheet_state != 'visible':
                    label += ' [hidden]'
                lines = [label]
                formula_rows = formula_sheet.iter_rows(values_only=False)
                value_rows = value_sheet.iter_rows(values_only=True)
                truncated = False
                for row_number, pair in enumerate(zip(formula_rows, value_rows), 1):
                    formula_row, cached_row = pair
                    entries = []
                    for column_index, cell in enumerate(formula_row, 1):
                        cell_count += 1
                        if cell_count > MAX_XLSX_CELLS:
                            truncated = True
                            break
                        formula_value = cell.value
                        cached_value = cached_row[column_index - 1] if column_index - 1 < len(cached_row) else None
                        if formula_value is None:
                            continue
                        address = cell.coordinate
                        if cell.data_type == 'f' or (isinstance(formula_value, str) and formula_value.startswith('=')):
                            text = address + ': formula=' + _office_value(formula_value) + '; cached=' + (_office_value(cached_value) or '[blank]')
                        else:
                            text = address + ': ' + _office_value(formula_value)
                        entries.append(text)
                    if entries:
                        lines.append(' | '.join(entries))
                    if truncated:
                        break
                text = '\n'.join(lines)
                total_chars += len(text)
                if total_chars > MAX_TEXT_CHARS:
                    raise ValueError('Excel 提取文字超过安全大小限制。')
                pages.append({'page': sheet_index, 'text': text})
                if truncated:
                    warnings.append(f'单元格提取达到 {MAX_XLSX_CELLS} 个上限，后续内容未解析。')
                    break
            content = '\n\n'.join(page['text'] for page in pages)
            return {'content': content, 'page_count': max(1, len(pages)), 'pages': pages, 'warnings': warnings}
        finally:
            formula_book.close(); value_book.close()
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError('Excel 文件损坏或单元格结构无法解析。') from exc


def _parse_pdf(data: bytes) -> dict:
    try:
        from pypdf import PdfReader  # Optional pure-Python dependency.
    except ImportError as exc:
        raise ValueError("PDF 解析需要可选依赖 pypdf；请安装后重试，或导入 TXT/MD/DOCX。") from exc
    try:
        reader = PdfReader(BytesIO(data), strict=False)
        if reader.is_encrypted:
            raise ValueError("不支持加密 PDF，请先提供未加密副本。")
        count = len(reader.pages)
        if count > MAX_PDF_PAGES:
            raise ValueError(f"PDF 超过 {MAX_PDF_PAGES} 页的安全限制。")
        pages = []
        total = 0
        for index, page in enumerate(reader.pages, 1):
            text = (page.extract_text() or "").replace("\r\n", "\n").replace("\r", "\n").strip()
            total += len(text)
            if total > MAX_TEXT_CHARS:
                raise ValueError("PDF 提取文字超过安全大小限制。")
            pages.append({"page": index, "text": text})
        warnings = ["PDF 文字提取可能改变表格和多栏阅读顺序，请对照原文件核实。"]
        empty = sum(not page["text"] for page in pages)
        if empty or not pages:
            warnings.append(f"有 {empty or count} 页未提取到文字；可能为扫描件。本工具不支持自动 OCR。")
        return {"content": "\n\n".join(page["text"] for page in pages),
                "page_count": count, "pages": pages, "warnings": warnings}
    except Exception as exc:
        if isinstance(exc, ValueError) and re.search(r"[\u3400-\u9fff]", str(exc)):
            raise
        raise ValueError("PDF 文件损坏或无法提取文字，请检查格式和加密状态。") from exc


def parse_upload(name: str, data: bytes) -> dict:
    """Parse TXT/MD/PDF/DOCX bytes without extracting ZIP entries to disk."""
    if not isinstance(name, str) or not name.strip() or len(name) > 512 or "\x00" in name:
        raise ValueError("文件名不能为空、过长或包含空字符。")
    if not isinstance(data, bytes):
        raise ValueError("文件内容必须是 bytes 字节数据。")
    if not data:
        raise ValueError("上传文件不能为空。")
    if len(data) > MAX_UPLOAD_BYTES:
        raise ValueError("上传文件不能超过 20MB。")
    extension = PurePosixPath(name.replace("\\", "/")).suffix.lower()
    if extension not in (".txt", ".md", ".pdf", ".docx", ".pptx", ".xlsx", ".xlsm"):
        raise ValueError("仅支持 TXT、MD、PDF、DOCX、PPTX、XLSX 和 XLSM 文件。")
    if extension == ".pptx":
        return _parse_pptx(data)
    if extension in (".xlsx", ".xlsm"):
        return _parse_xlsx(data, macro_enabled=extension == ".xlsm")
    if extension == ".pdf":
        return _parse_pdf(data)
    if extension == ".docx":
        return _parse_docx(data)
    warnings = ["纯文本没有可靠排版页码；引用使用段落定位。"]
    try:
        if data.startswith((b"\xff\xfe", b"\xfe\xff")):
            content = data.decode("utf-16")
        else:
            try:
                content = data.decode("utf-8-sig")
            except UnicodeDecodeError:
                content = data.decode("gb18030")
                warnings.append("文件已按 GB18030 编码解码，请检查文字是否正确。")
    except UnicodeError as exc:
        raise ValueError("文本编码无法识别，请另存为 UTF-8 后重试。") from exc
    if "\x00" in content or any(ord(ch) < 32 and ch not in "\n\r\t" for ch in content):
        raise ValueError("文件包含非文本控制字符，不能作为文本导入。")
    return _unpaginated(_text(content, "文件正文"), warnings)


def _segments(text: str):
    start = 0
    while start < len(text):
        end = min(start + _CHUNK_SIZE, len(text))
        if end < len(text):
            lower = start + _CHUNK_SIZE // 2
            boundaries = [text.rfind(separator, lower, end) + len(separator)
                          for separator in ("\n\n", "\n", "。", "！", "？", ". ", "; ")]
            possible = [boundary for boundary in boundaries if boundary > lower]
            if possible:
                end = max(possible)
        segment = text[start:end].strip()
        if segment:
            yield segment
        if end >= len(text):
            break
        start = max(start + 1, end - _CHUNK_OVERLAP)


def chunk_text(text: str, pages: list | None = None) -> list:
    """Return stable bounded overlapping excerpts, keeping physical PDF pages."""
    text = _text(text, "分段正文")
    if pages is not None and not isinstance(pages, list):
        raise ValueError("页列表必须是列表或空值。")
    sources = pages if pages else [{"page": None, "text": text}]
    chunks = []
    total = 0
    for source in sources:
        if not isinstance(source, dict):
            raise ValueError("每一页必须包含 page 和 text 字段。")
        page = source.get("page")
        if page is not None and (type(page) is not int or page < 1):
            raise ValueError("页码必须是从 1 开始的整数或空值。")
        body = _text(source.get("text", ""), "页面正文")
        total += len(body)
        if total > MAX_TEXT_CHARS:
            raise ValueError("页面正文合计超过安全大小限制。")
        for segment in _segments(body.strip()):
            ordinal = len(chunks) + 1
            digest = hashlib.sha256(f"{page}|{ordinal}|{segment}".encode("utf-8")).hexdigest()[:24]
            chunks.append({"id": "chunk-" + digest, "ordinal": ordinal,
                           "page": page, "text": segment})
    return chunks


_EN_STOP = set("a an the and or but of to in on for by with is are was were be been being do does did "
               "what which when where why how who whom can could would should will shall may might "
               "please tell me about explain summarize summary compare show find give document documents source sources "
               "it its this that these those we our you your have has had any much many as at from".split())
_ZH_STOP = ("请帮我", "请问", "帮我", "告诉我", "请提供", "根据资料", "根据文档", "根据", "关于",
            "怎么样", "怎么", "为什么", "为何", "如何", "是否", "有哪些", "有什么", "是什么",
            "是多少", "多少", "什么", "哪些", "情况", "介绍", "总结", "分析", "比较", "对比",
            "说明", "解释", "研究", "评估", "一下", "目前", "以及", "还有", "中的", "请", "的", "吗", "呢", "与", "和", "及")
_GENERIC_TOPICS = set("收入 营收 增长 利润 毛利率 EBITDA 净利润 估值 投资 融资 风险 财务 成本 客户 "
                      "计划 订单 现金流 产能 进展 状态 数据 revenue growth profit margin ebitda valuation "
                      "investment funding risk risks financial costs customers plan orders cash capacity status data".lower().split())


def _normal(text: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", text).casefold())


def _query_groups(question: str) -> list[str]:
    clean = _normal(question)
    for stop in sorted(_ZH_STOP, key=len, reverse=True):
        clean = clean.replace(stop, " ")
    # Separate known metrics from company names: a company match alone must not
    # qualify a question about an absent metric such as cash flow.
    metric_pattern = "|".join(re.escape(term) for term in sorted(_GENERIC_TOPICS, key=len, reverse=True)
                              if not term.isascii())
    clean = re.sub("(" + metric_pattern + ")", r" \1 ", clean)
    groups = []
    for term in re.findall(r"[a-z][a-z0-9_-]*|[\u3400-\u9fff]+", clean):
        if len(term) >= 2 and term not in _EN_STOP and term not in groups:
            groups.append(term)
    return groups


def _query_phrases(question: str) -> list[str]:
    phrases = []
    normalized = _normal(question)
    for sequence in re.findall(r"[a-z][a-z0-9_-]*(?:\s+[a-z][a-z0-9_-]*)+", normalized):
        words = sequence.split()
        for index in range(len(words) - 1):
            if words[index] not in _EN_STOP and words[index + 1] not in _EN_STOP:
                phrases.append(" ".join(words[index:index + 2]))
    phrases.extend(re.findall(r'["“]([^"”]{2,80})["”]', normalized))
    return list(dict.fromkeys(phrases))


def _match(term: str, haystack: str) -> float:
    if term.isascii():
        pattern = r"\s+".join(re.escape(word) for word in term.split())
        return float(bool(re.search(r"(?<![a-z0-9_])" + pattern + r"(?![a-z0-9_])", haystack)))
    if term in haystack:
        return 1.0
    if len(term) < 3:
        return 0.0
    # Adjacent Chinese bigrams avoid treating any shared single character as evidence.
    pairs = [term[index:index + 2] for index in range(len(term) - 1)]
    return sum(pair in haystack for pair in pairs) / len(pairs)


def _coverage(groups: list[str], haystack: str) -> float:
    weights = [min(len(term), 8) if not term.isascii() else 3 for term in groups]
    return sum(weight * _match(term, haystack) for term, weight in zip(groups, weights)) / max(sum(weights), 1)


def _quote(text: str, groups: list[str], maximum: int = 900) -> str:
    if len(text) <= maximum:
        return text.strip()
    folded = text.casefold()
    positions = [0]
    for term in groups:
        position = folded.find(term)
        if position >= 0:
            positions.append(max(0, position - 100))
        elif not term.isascii():
            for index in range(len(term) - 1):
                position = folded.find(term[index:index + 2])
                if position >= 0:
                    positions.append(max(0, position - 100))
    start = max(positions, key=lambda pos: _coverage(groups, _normal(text[pos:pos + maximum])))
    return text[start:start + maximum].strip()


def _question(question: str) -> str:
    question = _text(question, "问题", maximum=3000).strip()
    if not question:
        raise ValueError("问题不能为空。")
    return question


def retrieve(question: str, documents: list, limit: int = 6) -> list:
    """Explainable lexical retrieval, not semantic inference or truth verification.

    English matches whole words; Chinese matches phrases and adjacent bigrams.
    Require >=40% weighted query coverage plus a non-generic topic anchor.
    Title matches help ranking but cannot alone qualify an unrelated body.
    """
    question = _question(question)
    if not isinstance(documents, list):
        raise ValueError("待检索资料必须是列表。")
    if type(limit) is not int or not 0 <= limit <= 50:
        raise ValueError("引用数量必须是 0 到 50 的整数。")
    groups = _query_groups(question)
    phrases = _query_phrases(question)
    if not groups or limit == 0:
        return []
    anchors = [term for term in groups if term not in _GENERIC_TOPICS] or groups
    ranked = []
    for document_index, document in enumerate(documents):
        if not isinstance(document, dict):
            raise ValueError("待检索资料记录必须是对象。")
        document_id = document.get("id")
        if not isinstance(document_id, str) or not document_id:
            continue  # Never manufacture a reference to a document with no identity.
        title = document.get("title") or "未命名资料"
        if not isinstance(title, str):
            raise ValueError("资料标题必须是文本。")
        chunks = document.get("chunks")
        if not chunks:
            chunks = chunk_text(document.get("content", ""))
        if not isinstance(chunks, list):
            raise ValueError("资料分段必须是列表。")
        for chunk_index, chunk in enumerate(chunks):
            if not isinstance(chunk, dict) or not isinstance(chunk.get("text"), str):
                continue
            body = chunk["text"].strip()
            if not body:
                continue
            normalized_body = _normal(body)
            combined = _normal(title) + " " + normalized_body
            coverage = _coverage(groups, combined)
            body_coverage = _coverage(groups, normalized_body)
            if coverage < .40 or body_coverage < .24:
                continue
            if not any(_match(term, combined) >= .5 for term in anchors):
                continue
            # When the query explicitly asks a generic metric, it must occur in the excerpt.
            metrics = [term for term in groups if term in _GENERIC_TOPICS]
            if metrics and not any(_match(term, normalized_body) >= .5 for term in metrics):
                continue
            ordinal = chunk.get("ordinal", chunk_index + 1)
            if type(ordinal) is not int or ordinal < 1:
                ordinal = chunk_index + 1
            page = chunk.get("page")
            if page is not None and (type(page) is not int or page < 1):
                page = None
            chunk_id = chunk.get("id") or f"paragraph-{ordinal}"
            citation = {"id": f"{document_id}:{chunk_id}", "document_id": document_id,
                        "title": title, "page": page, "ordinal": ordinal,
                        "quote": _quote(body, groups)}
            score = (coverage + body_coverage + .20 * _coverage(groups, _normal(title))
                     + .25 * sum(_match(phrase, normalized_body) for phrase in phrases))
            ranked.append((-score, document_index, ordinal, chunk_index, citation))
    ranked.sort(key=lambda entry: entry[:4])
    result = []
    seen = set()
    for *_, citation in ranked:
        key = (citation["document_id"], citation["quote"])
        if key not in seen:
            result.append(citation)
            seen.add(key)
        if len(result) == limit:
            break
    return result


def local_answer(question: str, citations: list) -> dict:
    """Display attributed source quotations, with no invented synthesis."""
    _question(question)
    if not isinstance(citations, list):
        raise ValueError("引用必须是列表。")
    warning = "本地模式仅做关键词检索与原文摘录，未独立核实材料；不同日期或口径不能直接判定为事实冲突。"
    if not citations:
        return {"answer": "在所选材料中未找到与问题足够相关的原文。请补充资料或调整关键词；本地模式不猜测答案。",
                "citations": [], "mode": "local", "warning": warning}
    blocks = ["以下仅为所选材料的原文摘录，不是已验证事实，也不构成推断或投资结论。"]
    copied = []
    for index, citation in enumerate(citations, 1):
        if not isinstance(citation, dict) or not isinstance(citation.get("quote"), str) or not citation["quote"].strip():
            raise ValueError("引用必须包含非空原文 quote。")
        copied.append(dict(citation))
        page = citation.get("page")
        location = f"第 {page} 页，第 {citation.get('ordinal', index)} 段" if page else f"第 {citation.get('ordinal', index)} 段（无原始页码）"
        blocks.append(f"[{index}] {citation.get('title', '未命名资料')} · {location}\n" +
                      "\n".join("> " + line for line in citation["quote"].splitlines()))
    return {"answer": "\n\n".join(blocks), "citations": copied, "mode": "local", "warning": warning}


_ACTION = re.compile(r"待办|下一步|行动项|负责人|负责(?:人)?[：:]?|跟进|\btodo\b|\baction\s*(?:item)?\b|\bowner\s*:", re.I)
_NEGATIVE_ACTION = re.compile(r"(?:无需|不需(?:要)?|不用|不要|取消|暂无|没有)(?:再|任何|新的)?\s*(?:待办|行动|跟进|下一步)|(?:任务|待办|行动项).{0,8}(?:已完成|已取消)")
_DATE_TOKEN = r"(\d{4})\s*[-/年]\s*(\d{1,2})\s*[-/月]\s*(\d{1,2})日?"
_DUE = re.compile(r"(?:截止(?:日期|时间)?|到期(?:日)?|最晚|期限|完成日期|\bdue\b|\bdeadline\b)\s*[：:]?\s*" + _DATE_TOKEN, re.I)


def _action_owner(source: str) -> str:
    patterns = [r"(?:负责人|\bowner)\s*[：:]\s*([^，,；;。\n：:]{1,40})",
                r"由\s*([\u3400-\u9fffA-Za-z·][\u3400-\u9fffA-Za-z· ]{0,20}?)\s*负责",
                r"(?:^|[：:，,；;\s])([\u3400-\u9fffA-Za-z·]{1,12})\s*负责(?!人)"]
    for pattern in patterns:
        match = re.search(pattern, source, flags=re.I)
        if match:
            owner = re.split(r"\s+(?:截止|due|deadline)|截止|到期|最晚", match.group(1), flags=re.I)[0].strip()
            if owner not in ("待定", "未定", "未知", "待确认", "TBD", "tbd", "待补充"):
                return owner
    return ""


def meeting_draft(transcript: str) -> dict:
    """Extract rule-based candidates; never infer an owner, deadline, or consensus."""
    transcript = _text(transcript, "会议逐字稿", maximum=200_000).strip()
    if not transcript:
        raise ValueError("会议逐字稿不能为空。")
    # A sentence/line remains an exact substring of the transcript for traceability.
    sources = [part.strip() for part in re.findall(r"[^\n。！？!?]+[。！？!?]?", transcript) if part.strip()]
    summary_quotes = sources[:8]
    summary = "规则草稿：以下是逐字稿原文摘录，未推断共识、事实或会议结论。\n" + "\n".join(
        f'- "{source[:400]}"' + ("（节选）" if len(source) > 400 else "") for source in summary_quotes)
    actions = []
    seen = set()
    for source in sources:
        if not _ACTION.search(source) or _NEGATIVE_ACTION.search(source):
            continue
        if source in seen:
            continue
        seen.add(source)
        due = ""
        match = _DUE.search(source)
        if match:
            try:
                due = date(*(int(part) for part in match.groups())).isoformat()
            except ValueError:
                pass
        title = re.sub(r"^\s*(?:[-*•]|\d+[.、)])\s*", "", source)
        title = re.sub(r"^(?:待办|下一步|行动项|todo|action\s*item)\s*[：:]\s*", "", title, flags=re.I)
        actions.append({"title": title[:200], "owner": _action_owner(source),
                        "due": due, "source_quote": source})
        if len(actions) == 30:
            break
    return {"summary": summary, "actions": actions, "mode": "rules",
            "warning": "规则草稿，不是模型总结。摘录不等于已核实事实；行动项仅为候选，须逐条确认后生成任务。仅显式负责人及明确截止日期会填入；相对日期和未明确字段留空。最多展示 8 条摘要摘录、30 条候选。"}


_DEFAULT_ASSUMPTIONS = {"revenue": 100.0, "growth": .15, "margin": .20,
                        "entry_multiple": 8.0, "exit_multiple": 8.0,
                        "leverage": .30, "years": 5, "cash_conversion": .70,
                        "interest_rate": .08}
_RANGES = {"revenue": (0.0, 1_000_000_000.0, False, "初始收入"),
           "growth": (-.50, 1.0, True, "年收入增长率"),
           "margin": (.01, 1.0, True, "EBITDA 利润率"),
           "entry_multiple": (0.0, 50.0, False, "进入 EV/EBITDA 倍数"),
           "exit_multiple": (0.0, 50.0, True, "退出 EV/EBITDA 倍数"),
           "leverage": (0.0, .80, True, "初始债务/进入企业价值比例"),
           "cash_conversion": (0.0, 1.0, True, "税前现金转换率"),
           "interest_rate": (0.0, .50, True, "年债务利率")}


def _validate_assumptions(assumptions: dict) -> dict:
    if not isinstance(assumptions, dict):
        raise ValueError("测算假设必须是对象。")
    unknown = set(assumptions) - set(_DEFAULT_ASSUMPTIONS)
    if unknown:
        raise ValueError("包含不支持的测算假设字段：" + "、".join(str(key) for key in sorted(unknown, key=str)))
    result = {**_DEFAULT_ASSUMPTIONS, **assumptions}
    if type(result["years"]) is not int or not 1 <= result["years"] <= 10:
        raise ValueError("持有期 years 必须是 1 到 10 的整数，不能是布尔值。")
    for key, (low, high, inclusive, label) in _RANGES.items():
        value = result[key]
        if type(value) not in (int, float):
            raise ValueError(f"{label}必须是有限数值，不能是布尔值或文本。")
        try:
            number = float(value)
        except (OverflowError, ValueError) as exc:
            raise ValueError(f"{label}必须是有限合理数值。") from exc
        if not math.isfinite(number) or number > high or number < low or (not inclusive and number == low):
            relation = "大于" if not inclusive else "不小于"
            raise ValueError(f"{label}必须{relation} {low:g} 且不大于 {high:g}；比例使用小数，不允许 NaN/Infinity。")
        result[key] = number
    # Avoid effectively zero purchase equity and numerical overflow from tiny denominators.
    entry_ev = result["revenue"] * result["margin"] * result["entry_multiple"]
    if entry_ev * (1 - result["leverage"]) < .000001:
        raise ValueError("进入权益价值过小；请使用合理的收入、利润率和进入倍数。")
    return result


def _scenario(assumptions: dict, *, entry_ev: float, entry_equity: float) -> dict:
    revenue = assumptions["revenue"]
    debt = entry_ev * assumptions["leverage"]
    cash = 0.0
    rows = []
    for year in range(1, assumptions["years"] + 1):
        revenue *= 1 + assumptions["growth"]
        ebitda = revenue * assumptions["margin"]
        opening_debt = debt
        interest = opening_debt * assumptions["interest_rate"]
        operating_cash = ebitda * assumptions["cash_conversion"]
        cash_flow = operating_cash - interest
        repayment = 0.0
        debt_draw = 0.0
        if cash_flow >= 0:
            repayment = min(debt, cash_flow)
            debt -= repayment
            cash += cash_flow - repayment
        else:
            cash_used = min(cash, -cash_flow)
            cash -= cash_used
            debt_draw = -cash_flow - cash_used
            debt += debt_draw
        debt = max(0.0, debt)
        cash = max(0.0, cash)
        rows.append({"year": year, "revenue": revenue, "ebitda": ebitda,
                     "opening_debt": opening_debt, "interest": interest,
                     "operating_cash": operating_cash, "cash_flow": cash_flow,
                     "debt_repayment": repayment, "debt_draw": debt_draw,
                     "debt": debt, "cash": cash, "net_debt": debt - cash})
    exit_ev = rows[-1]["ebitda"] * assumptions["exit_multiple"]
    exit_equity = max(0.0, exit_ev - debt + cash)
    moic = exit_equity / entry_equity
    irr = -1.0 if exit_equity == 0 else moic ** (1.0 / assumptions["years"]) - 1.0
    return {"irr": irr, "moic": moic, "entry_ev": entry_ev, "entry_equity": entry_equity,
            "entry_debt": entry_ev * assumptions["leverage"], "exit_ev": exit_ev,
            "exit_equity": exit_equity, "exit_debt": debt, "exit_cash": cash,
            "net_debt": debt - cash, "rows": rows, "assumptions": dict(assumptions)}


def calculate_model(assumptions: dict) -> dict:
    """Simplified terminal-only equity returns; not a full LBO or valuation opinion.

    The entry price/financing is identical across base, bear, bull and sensitivity.
    Cash is retained, not distributed. Cash deficits use cash then additional debt.
    """
    base_assumptions = _validate_assumptions(assumptions)
    a = base_assumptions
    entry_ev = a["revenue"] * a["margin"] * a["entry_multiple"]
    entry_equity = entry_ev * (1 - a["leverage"])
    bear = {**a, "growth": max(-.5, a["growth"] - .05), "margin": max(.01, a["margin"] - .03),
            "exit_multiple": max(0.0, a["exit_multiple"] - 1.0)}
    bull = {**a, "growth": min(1.0, a["growth"] + .05), "margin": min(1.0, a["margin"] + .03),
            "exit_multiple": min(50.0, a["exit_multiple"] + 1.0)}
    run = lambda scenario: _scenario(scenario, entry_ev=entry_ev, entry_equity=entry_equity)
    growths = sorted({round(max(-.5, min(1.0, a["growth"] + delta)), 10) for delta in (-.10, -.05, 0, .05, .10)})
    multiples = sorted({round(max(0.0, min(50.0, a["exit_multiple"] + delta)), 10) for delta in (-2, -1, 0, 1, 2)})
    values = [[run({**a, "growth": growth, "exit_multiple": multiple})["irr"]
               for multiple in multiples] for growth in growths]
    formulas = {
        "units": "金额：人民币百万元；利率/增长率/利润率/IRR：小数比例；倍数：x。",
        "entry_ev": "进入 EV = 初始收入 × 初始 EBITDA 利润率 × 进入 EV/EBITDA 倍数。",
        "entry_equity": "进入权益 = 进入 EV × (1 − leverage)；leverage 是债务占进入 EV 的比例，不是债务/EBITDA 倍数。",
        "revenue": "第 t 年收入 = 初始收入 × (1 + 年增长率)^t；当年 EBITDA = 当年收入 × EBITDA 利润率。",
        "cash_flow": "期初债务利息 = 期初债务 × 利率；税前经营现金 = EBITDA × 现金转换率；税前可用现金流 = 税前经营现金 − 利息。",
        "debt": "正现金流先偿还债务、余款留存现金；负现金流先使用现金、缺口新增债务。债务和现金均不小于零；净债务 = 债务 − 现金。",
        "exit_equity": "退出 EV = 末年 EBITDA × 退出倍数；退出权益 = max(0, 退出 EV − 期末债务 + 留存现金)。现金流不再单独累加，避免双计。",
        "moic": "MOIC = 退出权益 / 进入权益；中间不分红。",
        "irr": "IRR = MOIC^(1/持有年数) − 1；退出权益为零时 IRR = −1。",
        "scenarios": "相同进入价格/初始债务/初始权益：bear 增长率 −5pct、利润率 −3pct、退出倍数 −1x；bull 分别 +5pct、+3pct、+1x，按输入边界截断。情景利润率仅适用于持有期。",
        "sensitivity": "仅改变年增长率与退出倍数，其余基准假设及进入价格/融资不变；values 单元格为小数 IRR。",
    }
    return {"base": run(a), "bear": run(bear), "bull": run(bull),
            "sensitivity": {"rows": growths, "columns": multiples, "values": values},
            "assumptions": dict(a), "formulas": formulas,
            "warning": "简化税前权益回报演示，非完整 LBO、估值意见或投资建议。未单列税费、交易费用、资本开支/营运资本、折旧及融资约束；现金转换率汇总相关经营现金影响，但不含所得税。假设缺口可新增同利率债务，现金不计息、中间无分红，退出权益最低为零。情景不是概率预测。"}
