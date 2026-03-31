"""文档解析器，支持 PDF/DOCX/TXT/Markdown 等格式。

将不同格式的文档统一解析为纯文本输出，
PDF 使用 pypdf 提取、DOCX 通过解压 XML 抽取正文、
TXT/Markdown 直接读取，解析后统一做换行和空白归一化处理。
"""
import csv
import io
import json as json_module
from dataclasses import dataclass  # 导入 dataclass，用于定义解析结果结构。
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath  # 导入 Path，方便处理文件路径。
from xml.etree import ElementTree  # 导入 XML 解析器，用于提取 DOCX 里的正文文本。
from zipfile import BadZipFile, ZipFile  # 导入 zip 工具，用于读取 DOCX 容器内容。

from pypdf import PdfReader  # 导入 PDF 读取器，用于提取 PDF 文本。

SUPPORTED_NATIVE_PARSE_SUFFIXES = {".pdf", ".md", ".markdown", ".txt", ".docx", ".csv", ".html", ".json", ".xlsx", ".pptx", ".xls"}  # 当前系统支持原生解析的文件扩展名集合。
OCR_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}  # 当前计划通过 OCR 进入主链路的图片扩展名集合。
SUPPORTED_PARSE_SUFFIXES = SUPPORTED_NATIVE_PARSE_SUFFIXES | OCR_IMAGE_SUFFIXES  # 系统整体支持的解析扩展名集合，包含 OCR-only 图片。
WORDPROCESSINGML_NAMESPACE = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}  # DOCX 正文 XML 的命名空间。
DOCX_RELATIONSHIP_EMBED_ATTR = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}embed"  # DOCX 图片引用关系字段。
DOCX_IMAGE_RELATIONSHIP_TYPE = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/image"  # DOCX 图片关系类型。


@dataclass(slots=True)  # 用 dataclass 定义解析结果结构，并开启 slots 节省内存。
class ParsedDocument:  # 表示一份文档被解析后的结果。
    document_id: str  # 文档唯一标识。
    filename: str  # 原始文件名。
    parser_name: str  # 本次使用的解析器名称。
    text: str  # 解析得到的纯文本内容。


class DocumentParser:  # 负责把不同格式的文件统一解析成纯文本。
    def parse(  # 根据文件类型选择对应解析逻辑。
        self,
        source_path: Path,
        document_id: str,
        filename: str,
        *,
        allow_empty: bool = False,
    ) -> ParsedDocument:
        suffix = self.resolve_suffix(source_path=source_path, filename=filename)  # 优先用落盘文件后缀，缺失时回退原始文件名后缀。

        if suffix not in SUPPORTED_PARSE_SUFFIXES:  # 如果当前文件类型不在支持范围内。
            supported = ", ".join(sorted(SUPPORTED_PARSE_SUFFIXES))  # 拼出可读的支持格式列表。
            raise ValueError(  # 抛出业务错误，交给上层转换成 HTTP 异常。
                f"Unsupported file type for parsing: {suffix or 'unknown'}. Supported types: {supported}"  # 返回明确错误信息。
            )
        if suffix in OCR_IMAGE_SUFFIXES:  # 图片文件需要 OCR，不能直接走原生文本解析。
            raise ValueError(f"OCR is required to parse image file type: {suffix}.")

        if suffix == ".pdf":  # 如果是 PDF 文件。
            text = self._parse_pdf(source_path)  # 调用 PDF 解析逻辑提取文本。
            parser_name = "pdf_text"  # 记录本次使用的解析器名称。
        elif suffix == ".docx":  # DOCX 先从 zip 里的 document.xml 抽取正文文本。
            text = self._parse_docx(source_path)
            parser_name = "docx_xml"
        elif suffix == ".csv":
            text = self._parse_csv(source_path)
            parser_name = "csv_text"
        elif suffix == ".html":
            text = self._parse_html(source_path)
            parser_name = "html_text"
        elif suffix == ".json":
            text = self._parse_json(source_path)
            parser_name = "json_flatten"
        elif suffix == ".xlsx":
            text = self._parse_xlsx(source_path)
            parser_name = "xlsx_xml"
        elif suffix == ".pptx":
            text = self._parse_pptx(source_path)
            parser_name = "pptx_xml"
        elif suffix == ".xls":
            text = self._parse_xls(source_path)
            parser_name = "xls_xlrd"
        elif suffix in {".md", ".markdown"}:  # 如果是 Markdown 文件。
            text = source_path.read_text(encoding="utf-8", errors="ignore")  # 直接按文本方式读取文件内容。
            parser_name = "markdown_text"  # 记录解析器名称。
        else:  # 剩下的就是 txt 纯文本文件。
            text = source_path.read_text(encoding="utf-8", errors="ignore")  # 直接按文本方式读取。
            parser_name = "plain_text"  # 记录解析器名称。

        normalized_text = self._normalize_text(text)  # 对解析出的文本做统一清洗和换行归一化。
        if not normalized_text and not allow_empty:  # 如果清洗后仍然没有有效文本。
            raise ValueError(f"No extractable text found in '{filename}'.")  # 抛出业务错误。

        return ParsedDocument(  # 把解析结果封装成 ParsedDocument 返回。
            document_id=document_id,  # 返回文档 ID。
            filename=filename,  # 返回原始文件名。
            parser_name=parser_name,  # 返回解析器名称。
            text=normalized_text,  # 返回清洗后的纯文本。
        )

    @staticmethod
    def resolve_suffix(*, source_path: Path, filename: str) -> str:  # 统一计算当前文档后缀，便于 OCR 和原生解析共用。
        return source_path.suffix.lower() or Path(filename).suffix.lower()

    @staticmethod
    def is_ocr_image_suffix(suffix: str) -> bool:  # 暴露图片扩展名判断，避免外层重复维护后缀集合。
        return suffix.lower() in OCR_IMAGE_SUFFIXES

    @staticmethod
    def should_attempt_pdf_ocr(text: str, *, min_chars: int) -> bool:  # PDF 原生抽取文本不足时触发 OCR fallback。
        return len(DocumentParser._normalize_text(text)) < min_chars

    @staticmethod
    def list_docx_embedded_image_paths(source_path: Path) -> list[str]:  # 提取 DOCX 里按文档顺序出现的嵌图路径，给 OCR 链路复用。
        try:
            with ZipFile(source_path) as archive:
                with archive.open("word/document.xml") as document_xml:
                    root = ElementTree.fromstring(document_xml.read())
                with archive.open("word/_rels/document.xml.rels") as rels_xml:
                    rels_root = ElementTree.fromstring(rels_xml.read())
                archive_names = set(archive.namelist())
        except KeyError:
            return []
        except (BadZipFile, ElementTree.ParseError):
            return []

        relationship_targets: dict[str, str] = {}
        for relationship in rels_root:
            if DocumentParser._local_name(relationship.tag) != "Relationship":
                continue
            relationship_id = relationship.attrib.get("Id")
            relationship_type = relationship.attrib.get("Type")
            target = relationship.attrib.get("Target")
            if not relationship_id or relationship_type != DOCX_IMAGE_RELATIONSHIP_TYPE or not target:
                continue
            normalized_target = DocumentParser._resolve_docx_archive_path(base_path="word/document.xml", target=target)
            if Path(normalized_target).suffix.lower() not in OCR_IMAGE_SUFFIXES:
                continue
            if normalized_target not in archive_names:
                continue
            relationship_targets[relationship_id] = normalized_target

        ordered_paths: list[str] = []
        seen_paths: set[str] = set()
        for node in root.iter():
            if DocumentParser._local_name(node.tag) != "blip":
                continue
            relationship_id = node.attrib.get(DOCX_RELATIONSHIP_EMBED_ATTR)
            if relationship_id is None:
                continue
            target_path = relationship_targets.get(relationship_id)
            if target_path is None or target_path in seen_paths:
                continue
            seen_paths.add(target_path)
            ordered_paths.append(target_path)
        return ordered_paths

    @staticmethod
    def normalize_text(text: str) -> str:  # 暴露公共归一化入口，给 OCR 结果和 fallback 合并复用。
        return DocumentParser._normalize_text(text)

    @staticmethod  # 这个工具函数不依赖实例状态，因此用静态方法。
    def _parse_pdf(source_path: Path) -> str:  # 从 PDF 文件里提取全文文本。
        page_texts = DocumentParser.extract_pdf_page_texts(source_path)  # 逐页提取文本，没有文本就用空字符串兜底。
        return "\n\n".join(page_texts)  # 用双换行把各页文本拼接成一整段。

    @staticmethod
    def extract_pdf_page_texts(source_path: Path) -> list[str]:  # 单独暴露 PDF 分页原生文本，给按页 OCR fallback 复用。
        reader = PdfReader(str(source_path))  # 创建 PDF 读取器。
        return [page.extract_text() or "" for page in reader.pages]  # 逐页提取文本，没有文本就用空字符串兜底。

    @staticmethod
    def _parse_docx(source_path: Path) -> str:  # 从 DOCX 容器里抽取正文文本，输出给统一切块链路。
        try:
            with ZipFile(source_path) as archive:
                with archive.open("word/document.xml") as document_xml:
                    root = ElementTree.fromstring(document_xml.read())
        except KeyError as exc:
            raise ValueError(f"DOCX body XML is missing in '{source_path.name}'.") from exc
        except BadZipFile as exc:
            raise ValueError(f"Invalid DOCX container for '{source_path.name}'.") from exc
        except ElementTree.ParseError as exc:
            raise ValueError(f"DOCX body XML is invalid for '{source_path.name}'.") from exc

        body = root.find("w:body", WORDPROCESSINGML_NAMESPACE)
        if body is None:
            return ""

        blocks: list[str] = []
        for child in body:
            element_name = DocumentParser._local_name(child.tag)
            if element_name == "p":
                paragraph_text = DocumentParser._extract_docx_paragraph(child)
                if paragraph_text:
                    blocks.append(paragraph_text)
                continue
            if element_name == "tbl":
                table_text = DocumentParser._extract_docx_table(child)
                if table_text:
                    blocks.append(table_text)

        return "\n\n".join(blocks)

    @staticmethod
    def _extract_docx_paragraph(paragraph: ElementTree.Element) -> str:  # 提取单个段落里的文本、换行和制表符。
        segments: list[str] = []
        for node in paragraph.iter():
            element_name = DocumentParser._local_name(node.tag)
            if element_name == "t" and node.text:
                segments.append(node.text)
            elif element_name == "tab":
                segments.append("\t")
            elif element_name in {"br", "cr"}:
                segments.append("\n")
        return "".join(segments).strip()

    @staticmethod
    def _extract_docx_table(table: ElementTree.Element) -> str:  # 把表格按“列用 tab、行用换行”展开成可检索文本。
        rows: list[str] = []
        for row in table.findall("w:tr", WORDPROCESSINGML_NAMESPACE):
            cells: list[str] = []
            for cell in row.findall("w:tc", WORDPROCESSINGML_NAMESPACE):
                cell_paragraphs = [
                    text
                    for text in (
                        DocumentParser._extract_docx_paragraph(paragraph)
                        for paragraph in cell.findall("w:p", WORDPROCESSINGML_NAMESPACE)
                    )
                    if text
                ]
                if cell_paragraphs:
                    cells.append("\n".join(cell_paragraphs))
            if cells:
                rows.append("\t".join(cells))
        return "\n".join(rows)

    @staticmethod
    def _local_name(tag: str) -> str:  # 统一去掉 XML namespace，便于按元素名判断结构。
        if "}" in tag:
            return tag.rsplit("}", 1)[-1]
        return tag

    @staticmethod
    def _resolve_docx_archive_path(*, base_path: str, target: str) -> str:  # 把 DOCX relationship target 归一成 zip 内标准路径。
        combined = PurePosixPath(base_path).parent / PurePosixPath(target)
        normalized_parts: list[str] = []
        for part in combined.parts:
            if part in {"", "."}:
                continue
            if part == "..":
                if normalized_parts:
                    normalized_parts.pop()
                continue
            normalized_parts.append(part)
        return PurePosixPath(*normalized_parts).as_posix()

    @staticmethod  # 这个工具函数也不依赖实例状态，因此用静态方法。
    def _normalize_text(text: str) -> str:  # 对文本做换行和空白标准化处理。
        normalized = text.replace("\r\n", "\n").replace("\r", "\n")  # 把不同系统的换行符统一成 \n。
        lines = [line.rstrip() for line in normalized.split("\n")]  # 去掉每一行末尾多余空白。
        collapsed = "\n".join(lines)  # 重新用单个换行把文本拼回去。
        collapsed = "\n\n".join(part.strip() for part in collapsed.split("\n\n"))  # 对段落两侧多余空白再做清理。
        return collapsed.strip()  # 去掉全文首尾空白并返回。

    @staticmethod
    def _parse_csv(source_path: Path) -> str:  # 用标准库 csv 解析，按列用 tab、行用换行输出。
        raw = source_path.read_bytes()
        text = raw.decode("utf-8-sig", errors="ignore")
        reader = csv.reader(io.StringIO(text))
        rows: list[str] = []
        for row in reader:
            rows.append("\t".join(row))
        return "\n".join(rows)

    @staticmethod
    def _parse_html(source_path: Path) -> str:  # 提取 HTML 可见文本，忽略 script 和 style。

        class _VisibleTextExtractor(HTMLParser):
            def __init__(self) -> None:
                super().__init__()
                self._skip_tags: set[str] = set()
                self._segments: list[str] = []

            def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
                if tag.lower() in {"script", "style"}:
                    self._skip_tags.add(tag.lower())

            def handle_endtag(self, tag: str) -> None:
                self._skip_tags.discard(tag.lower())

            def handle_data(self, data: str) -> None:
                if not self._skip_tags:
                    self._segments.append(data)

        raw = source_path.read_text(encoding="utf-8", errors="ignore")
        extractor = _VisibleTextExtractor()
        extractor.feed(raw)
        return "".join(extractor._segments)

    @staticmethod
    def _parse_json(source_path: Path) -> str:  # 递归展开 JSON 成 path: value 格式。
        raw = source_path.read_text(encoding="utf-8", errors="ignore")
        data = json_module.loads(raw)
        lines: list[str] = []
        DocumentParser._flatten_json(data, lines, prefix="")
        return "\n".join(lines)

    @staticmethod
    def _flatten_json(obj: object, lines: list[str], *, prefix: str) -> None:  # 递归展开 JSON 结构。
        if isinstance(obj, dict):
            for key, value in obj.items():
                path = f"{prefix}.{key}" if prefix else str(key)
                DocumentParser._flatten_json(value, lines, prefix=path)
        elif isinstance(obj, list):
            for index, item in enumerate(obj):
                path = f"{prefix}[{index}]"
                DocumentParser._flatten_json(item, lines, prefix=path)
        else:
            lines.append(f"{prefix}: {obj}")

    @staticmethod
    def _parse_xlsx(source_path: Path) -> str:  # 用 zipfile + xml.etree 解析 xlsx，不依赖 openpyxl。
        try:
            with ZipFile(source_path) as archive:
                # 解析 shared strings
                shared_strings: list[str] = []
                if "xl/sharedStrings.xml" in archive.namelist():
                    with archive.open("xl/sharedStrings.xml") as shared_xml:
                        shared_root = ElementTree.fromstring(shared_xml.read())
                    for si in shared_root:
                        t_elem = si.find("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}t")
                        if t_elem is not None and t_elem.text:
                            shared_strings.append(t_elem.text)
                        else:
                            # 多个 <r><t>...</t></r> 片段拼接
                            parts: list[str] = []
                            ns = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
                            for r_elem in si.findall(f"{ns}r"):
                                t_child = r_elem.find(f"{ns}t")
                                if t_child is not None and t_child.text:
                                    parts.append(t_child.text)
                            shared_strings.append("".join(parts))

                # 解析 workbook 获取 sheet 顺序
                sheet_names: list[str] = []
                with archive.open("xl/workbook.xml") as wb_xml:
                    wb_root = ElementTree.fromstring(wb_xml.read())
                ns_wb = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
                for sheet_elem in wb_root.findall(f".//{ns_wb}sheet"):
                    name = sheet_elem.attrib.get("name", "")
                    if name:
                        sheet_names.append(name)

                # 逐 sheet 解析
                blocks: list[str] = []
                ns = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
                for idx, sheet_name in enumerate(sheet_names, start=1):
                    sheet_path = f"xl/worksheets/sheet{idx}.xml"
                    if sheet_path not in archive.namelist():
                        continue
                    with archive.open(sheet_path) as sheet_xml:
                        sheet_root = ElementTree.fromstring(sheet_xml.read())

                    sheet_rows: list[str] = []
                    for row_elem in sheet_root.findall(f".//{ns}row"):
                        cells: list[str] = []
                        for c_elem in row_elem.findall(f"{ns}c"):
                            cell_type = c_elem.attrib.get("t", "")
                            v_elem = c_elem.find(f"{ns}v")
                            if v_elem is not None and v_elem.text:
                                if cell_type == "s":
                                    si = int(v_elem.text)
                                    cells.append(shared_strings[si] if si < len(shared_strings) else "")
                                else:
                                    cells.append(v_elem.text)
                            else:
                                # inline string: <is><t>...</t></is>
                                is_elem = c_elem.find(f"{ns}is")
                                if is_elem is not None:
                                    t_elem = is_elem.find(f"{ns}t")
                                    if t_elem is not None and t_elem.text:
                                        cells.append(t_elem.text)
                                    else:
                                        cells.append("")
                                else:
                                    cells.append("")
                        if cells:
                            sheet_rows.append("\t".join(cells))
                    if sheet_rows:
                        blocks.append(f"[Sheet] {sheet_name}")
                        blocks.append("\n".join(sheet_rows))

                return "\n\n".join(blocks)
        except KeyError as exc:
            raise ValueError(f"XLSX workbook structure is missing in '{source_path.name}'.") from exc
        except BadZipFile as exc:
            raise ValueError(f"Invalid XLSX container for '{source_path.name}'.") from exc
        except ElementTree.ParseError as exc:
            raise ValueError(f"XLSX XML is invalid for '{source_path.name}'.") from exc

    @staticmethod
    def _parse_pptx(source_path: Path) -> str:  # 用 zipfile + xml.etree 按 slide 顺序提取文本。
        try:
            with ZipFile(source_path) as archive:
                # 获取 slide 文件列表并排序
                slide_files = sorted(
                    [name for name in archive.namelist() if name.startswith("ppt/slides/slide") and name.endswith(".xml")],
                    key=lambda name: int("".join(c for c in name if c.isdigit()) or "0"),
                )

                blocks: list[str] = []
                ns_a = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
                for slide_index, slide_path in enumerate(slide_files, start=1):
                    with archive.open(slide_path) as slide_xml:
                        slide_root = ElementTree.fromstring(slide_xml.read())
                    texts: list[str] = []
                    for t_elem in slide_root.iter(f"{ns_a}t"):
                        if t_elem.text:
                            texts.append(t_elem.text)
                    if texts:
                        blocks.append(f"[Slide {slide_index}]")
                        blocks.append("\n".join(texts))

                return "\n\n".join(blocks)
        except BadZipFile as exc:
            raise ValueError(f"Invalid PPTX container for '{source_path.name}'.") from exc
        except ElementTree.ParseError as exc:
            raise ValueError(f"PPTX XML is invalid for '{source_path.name}'.") from exc

    @staticmethod
    def _parse_xls(source_path: Path) -> str:  # 用 xlrd 解析 .xls，按 sheet/row 展开文本。
        try:
            import xlrd
        except ImportError as exc:
            raise ValueError(
                "xlrd is required to parse .xls files but is not installed. "
                "Install it with: pip install xlrd"
            ) from exc
        workbook = xlrd.open_workbook(source_path)
        blocks: list[str] = []
        for sheet in workbook.sheets():
            rows: list[str] = []
            for row_idx in range(sheet.nrows):
                cells = [str(sheet.cell_value(row_idx, col_idx)) for col_idx in range(sheet.ncols)]
                rows.append("\t".join(cells))
            if rows:
                blocks.append(f"[Sheet] {sheet.name}")
                blocks.append("\n".join(rows))
        return "\n\n".join(blocks)
