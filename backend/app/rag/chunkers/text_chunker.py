"""文本分块器，按固定字符大小切分文档。

支持可配置的 chunk 大小、重叠长度和最小有效长度，
并尽量在自然边界（段落、句子、标点）处切分，保持语义完整性。
"""
from dataclasses import dataclass  # 导入 dataclass，用于定义轻量级 chunk 数据结构。
from dataclasses import field


@dataclass(slots=True)  # 用 dataclass 定义 chunk 结构，并启用 slots 节省内存。
class TextChunk:  # 表示切分后的一个文本片段。
    chunk_id: str  # chunk 唯一标识。
    document_id: str  # chunk 所属文档 ID。
    chunk_index: int  # chunk 在文档中的顺序编号。
    text: str  # chunk 里的文本内容。
    char_start: int  # chunk 在原文中的起始字符位置。
    char_end: int  # chunk 在原文中的结束字符位置。
    ocr_used: bool = False  # 当前 chunk 是否来自 OCR 参与的解析链路。
    parser_name: str | None = None  # 生成当前 chunk 的解析器名称，便于后续追踪来源。
    page_no: int | None = None  # OCR 可可靠定位时返回页码；普通文本和无法映射时为空。
    ocr_confidence: float | None = None  # OCR 置信度摘要，供后续排序和质量评估复用。
    quality_score: float | None = None  # 通用质量分，当前优先复用 OCR 置信度，为后续排序增强预留统一字段。
    chunk_type: str = "text"  # chunk 语义类型，普通文档默认为 text；结构化文档可落 doc_summary/section_summary/clause/metadata。
    parent_id: str | None = None  # 当前 chunk 的父级 chunk id，结构化文档做章节回溯时复用。
    doc_title: str | None = None  # 文档标题，供结构化检索增强使用。
    document_code: str | None = None  # 文档业务编号，如 WI-SJ-052；与内部 document_id 区分。
    section: str | None = None  # 章节号或章节范围，如 4.13 / 4.1-4.4 / ALL。
    section_label: str | None = None  # 章节语义标签，如 清屑要求 / 作业前准备。
    keywords: list[str] = field(default_factory=list)  # 结构化关键词，用于 embedding / lexical 增强。
    retrieval_text: str | None = None  # 用于 embedding / lexical 的增强文本，缺失时回退到 text。
    display_text: str | None = None  # 用于展示与引用的文本，缺失时回退到 text。
    summary_text: str | None = None  # 可选短摘要，供前端展示和后续 rerank 扩展复用。
    section_path: list[str] = field(default_factory=list)  # 结构化章节路径，如 ["内容", "4.13"]。
    clause_no: str | None = None  # 原始条款号。
    clause_no_normalized: str | None = None  # 归一化条款号，便于精确检索 4.17 / 第4.17条 等问法。
    source_file_name: str | None = None  # 原始文件名，给索引层和追溯层统一留存。
    version: str | None = None  # 文档版本号，如 A/0。
    effective_date: str | None = None  # 生效日期，统一保留成字符串，避免早期 schema 被日期格式约束住。
    risk_level: str | None = None  # 风险等级，安全类规范可复用。
    is_generated_summary: bool = False  # 当前 chunk 是否为规则/LLM 生成的摘要块。

    def embedding_text(self) -> str:  # 统一返回用于 embedding 的文本，优先使用 retrieval_text。
        return (self.retrieval_text or self.text).strip()

    def payload_text(self) -> str:  # 统一返回写入 payload 的展示文本，优先使用 display_text。
        return (self.display_text or self.text).strip()


class TextChunker:  # 按字符长度切分文本的简单 chunker。
    def __init__(self, chunk_size: int, chunk_overlap: int, chunk_min_chars: int) -> None:  # 初始化 chunker 参数。
        if chunk_size <= 0:  # 如果 chunk_size 非法。
            raise ValueError("chunk_size must be greater than 0.")  # 抛出错误提示调用方。
        if chunk_overlap < 0:  # 如果 overlap 为负数。
            raise ValueError("chunk_overlap must not be negative.")  # 抛出错误。
        if chunk_overlap >= chunk_size:  # 如果 overlap 大于等于 chunk_size。
            raise ValueError("chunk_overlap must be smaller than chunk_size.")  # 抛出错误，避免死循环。

        self.chunk_size = chunk_size  # 保存每个 chunk 的目标长度。
        self.chunk_overlap = chunk_overlap  # 保存相邻 chunk 的重叠长度。
        self.chunk_min_chars = max(1, min(chunk_min_chars, chunk_size))  # 约束最小长度不能小于 1，也不能大于 chunk_size。

    def split(self, document_id: str, text: str) -> list[TextChunk]:  # 把整篇文本切成多个 chunk。
        stripped_text = text.strip()  # 去掉首尾空白，避免生成纯空白 chunk。
        if not stripped_text:  # 如果文本为空。
            return []  # 直接返回空列表。

        chunks: list[TextChunk] = []  # 初始化 chunk 结果列表。
        text_length = len(stripped_text)  # 计算清洗后文本长度。
        start = 0  # 记录当前切分起点。
        chunk_index = 0  # 记录 chunk 序号。

        while start < text_length:  # 只要还没切到文本末尾，就继续循环。
            max_end = min(start + self.chunk_size, text_length)  # 先计算本轮允许的最远结束位置。
            end = self._find_chunk_end(stripped_text, start, max_end)  # 再尽量把结束位置对齐到自然边界。
            chunk_text = stripped_text[start:end].strip()  # 截取当前 chunk 并去掉首尾空白。

            if chunk_text:  # 如果当前 chunk 不是空字符串。
                chunks.append(  # 把当前 chunk 加入结果列表。
                    TextChunk(  # 创建一个 TextChunk 对象。
                        chunk_id=f"{document_id}-chunk-{chunk_index}",  # 用文档 ID 和序号拼出 chunk_id。
                        document_id=document_id,  # 记录所属文档 ID。
                        chunk_index=chunk_index,  # 记录 chunk 顺序。
                        text=chunk_text,  # 保存 chunk 文本。
                        char_start=start,  # 保存起始字符位置。
                        char_end=end,  # 保存结束字符位置。
                    )
                )
                chunk_index += 1  # 当前 chunk 已完成，序号加一。

            if end >= text_length:  # 如果已经切到文本末尾。
                break  # 结束循环。

            next_start = max(end - self.chunk_overlap, start + 1)  # 计算下一轮开始位置，并保留 overlap。
            while next_start < text_length and stripped_text[next_start].isspace():  # 如果下一个起点落在空白字符上。
                next_start += 1  # 往后跳过连续空白。
            start = next_start  # 更新下一轮切分起点。

        return chunks  # 返回最终 chunk 列表。

    def _find_chunk_end(self, text: str, start: int, max_end: int) -> int:  # 尽量为 chunk 找到自然结束边界。
        if max_end >= len(text):  # 如果已经到文本结尾。
            return len(text)  # 直接返回文本长度。

        min_end = min(start + self.chunk_min_chars, max_end)  # 先算出允许搜索边界的最小结束位置。
        boundary = self._find_last_boundary(text, min_end, max_end)  # 在允许范围内搜索最后一个自然边界。
        return boundary if boundary > start else max_end  # 如果找到边界就用边界，否则退回 max_end。

    @staticmethod  # 这个工具函数不依赖实例状态，因此用静态方法。
    def _find_last_boundary(text: str, start: int, end: int) -> int:  # 在给定区间内查找最后一个自然边界。
        boundaries = ("\n\n", "\n", "。", "！", "？", ".", "!", "?", ";", "；", ",", "，", " ")  # 定义优先考虑的边界分隔符。
        best = -1  # 初始化最佳边界位置为未找到。

        for separator in boundaries:  # 依次遍历每种分隔符。
            index = text.rfind(separator, start, end)  # 在指定区间里从右往左查找分隔符。
            if index != -1:  # 如果找到了该分隔符。
                candidate = index + len(separator)  # 把 chunk 结束位置放在分隔符之后。
                if candidate > best:  # 如果这个边界比之前记录的更靠后。
                    best = candidate  # 更新最佳边界。

        return best  # 返回最终找到的最佳边界位置。
