from dataclasses import dataclass  # 导入 dataclass，用于定义解析结果结构。
from pathlib import Path  # 导入 Path，方便处理文件路径。

from pypdf import PdfReader  # 导入 PDF 读取器，用于提取 PDF 文本。

SUPPORTED_PARSE_SUFFIXES = {".pdf", ".md", ".markdown", ".txt"}  # 当前系统支持解析的文件扩展名集合。


@dataclass(slots=True)  # 用 dataclass 定义解析结果结构，并开启 slots 节省内存。
class ParsedDocument:  # 表示一份文档被解析后的结果。
    document_id: str  # 文档唯一标识。
    filename: str  # 原始文件名。
    parser_name: str  # 本次使用的解析器名称。
    text: str  # 解析得到的纯文本内容。


class DocumentParser:  # 负责把不同格式的文件统一解析成纯文本。
    def parse(self, source_path: Path, document_id: str, filename: str) -> ParsedDocument:  # 根据文件类型选择对应解析逻辑。
        suffix = source_path.suffix.lower() or Path(filename).suffix.lower()  # 优先用落盘文件后缀，缺失时回退原始文件名后缀。

        if suffix not in SUPPORTED_PARSE_SUFFIXES:  # 如果当前文件类型不在支持范围内。
            supported = ", ".join(sorted(SUPPORTED_PARSE_SUFFIXES))  # 拼出可读的支持格式列表。
            raise ValueError(  # 抛出业务错误，交给上层转换成 HTTP 异常。
                f"Unsupported file type for parsing: {suffix or 'unknown'}. Supported types: {supported}"  # 返回明确错误信息。
            )

        if suffix == ".pdf":  # 如果是 PDF 文件。
            text = self._parse_pdf(source_path)  # 调用 PDF 解析逻辑提取文本。
            parser_name = "pdf_text"  # 记录本次使用的解析器名称。
        elif suffix in {".md", ".markdown"}:  # 如果是 Markdown 文件。
            text = source_path.read_text(encoding="utf-8", errors="ignore")  # 直接按文本方式读取文件内容。
            parser_name = "markdown_text"  # 记录解析器名称。
        else:  # 剩下的就是 txt 纯文本文件。
            text = source_path.read_text(encoding="utf-8", errors="ignore")  # 直接按文本方式读取。
            parser_name = "plain_text"  # 记录解析器名称。

        normalized_text = self._normalize_text(text)  # 对解析出的文本做统一清洗和换行归一化。
        if not normalized_text:  # 如果清洗后仍然没有有效文本。
            raise ValueError(f"No extractable text found in '{filename}'.")  # 抛出业务错误。

        return ParsedDocument(  # 把解析结果封装成 ParsedDocument 返回。
            document_id=document_id,  # 返回文档 ID。
            filename=filename,  # 返回原始文件名。
            parser_name=parser_name,  # 返回解析器名称。
            text=normalized_text,  # 返回清洗后的纯文本。
        )

    @staticmethod  # 这个工具函数不依赖实例状态，因此用静态方法。
    def _parse_pdf(source_path: Path) -> str:  # 从 PDF 文件里提取全文文本。
        reader = PdfReader(str(source_path))  # 创建 PDF 读取器。
        page_texts = [page.extract_text() or "" for page in reader.pages]  # 逐页提取文本，没有文本就用空字符串兜底。
        return "\n\n".join(page_texts)  # 用双换行把各页文本拼接成一整段。

    @staticmethod  # 这个工具函数也不依赖实例状态，因此用静态方法。
    def _normalize_text(text: str) -> str:  # 对文本做换行和空白标准化处理。
        normalized = text.replace("\r\n", "\n").replace("\r", "\n")  # 把不同系统的换行符统一成 \n。
        lines = [line.rstrip() for line in normalized.split("\n")]  # 去掉每一行末尾多余空白。
        collapsed = "\n".join(lines)  # 重新用单个换行把文本拼回去。
        collapsed = "\n\n".join(part.strip() for part in collapsed.split("\n\n"))  # 对段落两侧多余空白再做清理。
        return collapsed.strip()  # 去掉全文首尾空白并返回。
