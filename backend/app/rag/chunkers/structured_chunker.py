"""结构化文档分块器。

面向 SOP / WI / 安全操作规范等强结构化文档，
优先按标题、章节和条款号生成多粒度 chunk；
未命中结构特征时由上层回退到通用 TextChunker。
"""

from dataclasses import dataclass
import re

from .text_chunker import TextChunk

_CLAUSE_PATTERN = re.compile(r"^(?P<number>\d+\.\d+)\.?\s*(?P<body>.*)$")
_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]*|[\u4e00-\u9fff]{2,12}")
_DOCUMENT_CODE_PATTERN = re.compile(r"文件编号\s+([A-Za-z0-9][A-Za-z0-9._/-]*)")
_VERSION_PATTERN = re.compile(r"版\s*本\s*号\s+([A-Za-z0-9][A-Za-z0-9._/-]*)")
_EFFECTIVE_DATE_PATTERN = re.compile(r"生效日期\s+(\d{4}-\d{2}-\d{2})")
_BUSINESS_FILENAME_PATTERN = re.compile(r"(?i)(?:^|[^a-z])(wi|sop)(?:[^a-z]|$)")
_STOPWORD_TOKENS = {
    "本文件",
    "本规程",
    "本部分",
    "规范",
    "内容",
    "要求",
    "规定",
    "负责",
    "进行",
    "以及",
    "用于",
    "适用于",
}
_HIGH_RISK_TERMS = ("严禁", "禁止", "不得", "必须", "立即", "停机", "停车", "切断电源")
_MEDIUM_RISK_TERMS = ("应", "检查", "确认", "注意", "保持", "通知")
_HEADING_SEQUENCE = ("目的", "适用范围", "职责", "内容")
_APPENDIX_PREFIXES = ("修订页", "编制", "审核", "批准")
_PREDEFINED_CONTENT_GROUPS = (
    ("pre_operation", "4.1", "4.4", "作业前准备与防护要求"),
    ("machining_and_clamping", "4.5", "4.12", "钻削与装夹要求"),
    ("chip_and_stop", "4.13", "4.18", "清屑、变速与停车要求"),
    ("prohibition_and_tool", "4.19", "4.21", "禁令与工具冷却要求"),
    ("abnormal_shutdown_maintenance", "4.22", "4.27", "异常处理、停机与保养要求"),
)


@dataclass(slots=True)
class _LineSpan:
    text: str
    start: int
    end: int


@dataclass(slots=True)
class _Clause:
    clause_no: str | None
    content: str
    start: int
    end: int
    section_heading: str
    section_label: str


@dataclass(slots=True)
class _Metadata:
    title: str | None
    document_code: str | None
    version: str | None
    effective_date: str | None
    metadata_start: int
    metadata_end: int


@dataclass(slots=True)
class _SectionGroup:
    group_id: str
    section: str
    label: str
    entries: list[_Clause]


class SOPStructuredChunker:
    """面向 SOP / WI 文档的结构化多粒度分块器。"""

    def should_use(self, *, text: str, filename: str) -> bool:
        lines = self._build_line_spans(text)
        if not lines:
            return False
        heading_hits = sum(1 for heading in _HEADING_SEQUENCE if any(line.text == heading for line in lines))
        clause_hits = sum(1 for line in lines if _CLAUSE_PATTERN.match(line.text))
        filename_signal = bool(_BUSINESS_FILENAME_PATTERN.search(filename))
        return (heading_hits >= 3 and clause_hits >= 4) or (filename_signal and heading_hits >= 2 and clause_hits >= 2)

    def split(self, *, document_id: str, text: str, filename: str) -> list[TextChunk]:
        lines = self._build_line_spans(text)
        if not lines:
            return []

        metadata = self._extract_metadata(text=text, lines=lines, filename=filename)
        heading_positions = self._find_heading_positions(lines)
        if "内容" not in heading_positions:
            return []

        purpose_entry = self._build_single_entry(
            lines=lines,
            heading_positions=heading_positions,
            heading="目的",
            section_label="目的",
        )
        scope_entry = self._build_single_entry(
            lines=lines,
            heading_positions=heading_positions,
            heading="适用范围",
            section_label="适用范围",
        )
        duty_entries = self._build_numbered_entries(
            lines=lines,
            start_index=heading_positions.get("职责"),
            end_index=heading_positions.get("内容"),
            section_heading="职责",
            default_label="职责条款",
        )
        content_end_index = self._resolve_content_end_index(lines=lines, start_index=heading_positions["内容"])
        content_entries = self._build_numbered_entries(
            lines=lines,
            start_index=heading_positions["内容"],
            end_index=content_end_index,
            section_heading="内容",
            default_label="操作条款",
        )
        if not content_entries:
            return []

        chunks: list[TextChunk] = []
        doc_title = metadata.title or self._fallback_title(filename)
        base_entries = [entry for entry in (purpose_entry, scope_entry) if entry is not None]
        base_entries.extend(duty_entries)

        section_groups: list[_SectionGroup] = []
        if base_entries:
            section_groups.append(
                _SectionGroup(
                    group_id="basic_info",
                    section=self._build_group_section(base_entries),
                    label="基础信息与职责",
                    entries=base_entries,
                )
            )
        section_groups.extend(self._group_content_entries(content_entries))

        doc_summary_chunk = self._build_doc_summary_chunk(
            document_id=document_id,
            metadata=metadata,
            doc_title=doc_title,
            base_entries=base_entries,
            section_groups=section_groups,
            filename=filename,
        )
        if metadata.document_code or metadata.version or metadata.effective_date:
            chunks.append(
                self._new_chunk(
                    document_id=document_id,
                    chunk_id=f"{document_id}::metadata",
                    text=self._build_metadata_content(metadata, doc_title),
                    char_start=metadata.metadata_start,
                    char_end=metadata.metadata_end,
                    chunk_type="metadata",
                    doc_title=doc_title,
                    document_code=metadata.document_code,
                    section="META",
                    section_label="文档元数据",
                    section_path=["META"],
                    source_file_name=filename,
                    version=metadata.version,
                    effective_date=metadata.effective_date,
                    risk_level="low",
                )
            )
        chunks.append(doc_summary_chunk)

        section_chunk_ids: dict[str, str] = {}
        for group in section_groups:
            chunk_id = f"{document_id}::section_summary::{group.group_id}"
            section_chunk_ids[group.group_id] = chunk_id
            chunks.append(
                self._build_section_summary_chunk(
                    document_id=document_id,
                    metadata=metadata,
                    doc_title=doc_title,
                    filename=filename,
                    group=group,
                    parent_id=doc_summary_chunk.chunk_id,
                )
            )

        if base_entries:
            parent_id = section_chunk_ids.get("basic_info")
            for index, entry in enumerate(base_entries, start=1):
                clause_id = entry.clause_no or f"base-{index}"
                chunks.append(
                    self._build_clause_chunk(
                        document_id=document_id,
                        metadata=metadata,
                        doc_title=doc_title,
                        filename=filename,
                        entry=entry,
                        parent_id=parent_id,
                        chunk_id=f"{document_id}::clause::{clause_id}",
                    )
                )

        for group in section_groups:
            if group.group_id == "basic_info":
                continue
            parent_id = section_chunk_ids[group.group_id]
            for entry in group.entries:
                clause_id = entry.clause_no or group.group_id
                chunks.append(
                    self._build_clause_chunk(
                        document_id=document_id,
                        metadata=metadata,
                        doc_title=doc_title,
                        filename=filename,
                        entry=entry,
                        parent_id=parent_id,
                        chunk_id=f"{document_id}::clause::{clause_id}",
                    )
                )

        for index, chunk in enumerate(chunks):
            chunk.chunk_index = index
        return chunks

    @staticmethod
    def _build_line_spans(text: str) -> list[_LineSpan]:
        lines: list[_LineSpan] = []
        offset = 0
        for raw_line in text.splitlines(keepends=True):
            without_newline = raw_line.rstrip("\n")
            stripped = without_newline.strip()
            if stripped:
                leading_spaces = len(without_newline) - len(without_newline.lstrip())
                start = offset + leading_spaces
                lines.append(_LineSpan(text=stripped, start=start, end=start + len(stripped)))
            offset += len(raw_line)
        if text and not text.endswith(("\n", "\r")):
            trailing = text.splitlines()[-1].strip()
            if trailing and (not lines or lines[-1].text != trailing):
                start = text.rfind(trailing)
                lines.append(_LineSpan(text=trailing, start=start, end=start + len(trailing)))
        return lines

    @staticmethod
    def _fallback_title(filename: str) -> str:
        return re.sub(r"\.[^.]+$", "", filename).strip() or "未命名文档"

    def _extract_metadata(self, *, text: str, lines: list[_LineSpan], filename: str) -> _Metadata:
        title = None
        metadata_start = lines[0].start if lines else 0
        metadata_end = lines[0].end if lines else 0
        heading_start = min((line.start for line in lines if line.text in _HEADING_SEQUENCE), default=metadata_end)

        if lines:
            first_line = lines[0].text
            if "文件编号" in first_line:
                title = first_line.split("文件编号", 1)[0].strip() or None
            elif first_line not in _HEADING_SEQUENCE:
                title = first_line

        date_match = _EFFECTIVE_DATE_PATTERN.search(text)
        document_code_match = _DOCUMENT_CODE_PATTERN.search(text)
        version_match = _VERSION_PATTERN.search(text)

        if heading_start > metadata_start:
            metadata_end = heading_start
        elif lines:
            metadata_end = max(line.end for line in lines[: min(4, len(lines))])

        return _Metadata(
            title=title,
            document_code=document_code_match.group(1) if document_code_match else None,
            version=version_match.group(1) if version_match else None,
            effective_date=date_match.group(1) if date_match else None,
            metadata_start=metadata_start,
            metadata_end=metadata_end,
        )

    @staticmethod
    def _find_heading_positions(lines: list[_LineSpan]) -> dict[str, int]:
        positions: dict[str, int] = {}
        for index, line in enumerate(lines):
            if line.text in _HEADING_SEQUENCE and line.text not in positions:
                positions[line.text] = index
        return positions

    def _build_single_entry(
        self,
        *,
        lines: list[_LineSpan],
        heading_positions: dict[str, int],
        heading: str,
        section_label: str,
    ) -> _Clause | None:
        start_index = heading_positions.get(heading)
        if start_index is None:
            return None
        next_heading_indices = [
            index
            for name, index in heading_positions.items()
            if index > start_index and name in _HEADING_SEQUENCE
        ]
        end_index = min(next_heading_indices) if next_heading_indices else len(lines)
        body_lines = [line for line in lines[start_index + 1 : end_index] if line.text not in _HEADING_SEQUENCE]
        if not body_lines:
            return None
        content = " ".join(line.text for line in body_lines)
        return _Clause(
            clause_no=None,
            content=content,
            start=body_lines[0].start,
            end=body_lines[-1].end,
            section_heading=heading,
            section_label=section_label,
        )

    def _build_numbered_entries(
        self,
        *,
        lines: list[_LineSpan],
        start_index: int | None,
        end_index: int | None,
        section_heading: str,
        default_label: str,
    ) -> list[_Clause]:
        if start_index is None:
            return []
        upper_bound = end_index if end_index is not None else len(lines)
        entries: list[_Clause] = []
        current_no: str | None = None
        current_parts: list[str] = []
        current_start: int | None = None
        current_end: int | None = None

        for line in lines[start_index + 1 : upper_bound]:
            if line.text in _HEADING_SEQUENCE:
                break
            if any(line.text.startswith(prefix) for prefix in _APPENDIX_PREFIXES):
                break
            match = _CLAUSE_PATTERN.match(line.text)
            if match:
                if current_parts and current_start is not None and current_end is not None:
                    entries.append(
                        _Clause(
                            clause_no=current_no,
                            content=" ".join(current_parts).strip(),
                            start=current_start,
                            end=current_end,
                            section_heading=section_heading,
                            section_label=self._infer_clause_label(current_no, current_parts, default_label),
                        )
                    )
                current_no = match.group("number")
                body = (match.group("body") or "").strip()
                current_parts = [body] if body else []
                current_start = line.start
                current_end = line.end
                continue
            if current_parts:
                current_parts.append(line.text)
                current_end = line.end

        if current_parts and current_start is not None and current_end is not None:
            entries.append(
                _Clause(
                    clause_no=current_no,
                    content=" ".join(current_parts).strip(),
                    start=current_start,
                    end=current_end,
                    section_heading=section_heading,
                    section_label=self._infer_clause_label(current_no, current_parts, default_label),
                )
            )
        return entries

    @staticmethod
    def _resolve_content_end_index(*, lines: list[_LineSpan], start_index: int) -> int:
        for index, line in enumerate(lines[start_index + 1 :], start=start_index + 1):
            if any(line.text.startswith(prefix) for prefix in _APPENDIX_PREFIXES):
                return index
        return len(lines)

    def _group_content_entries(self, entries: list[_Clause]) -> list[_SectionGroup]:
        if not entries:
            return []
        clause_numbers = [entry.clause_no for entry in entries if entry.clause_no]
        if clause_numbers and all(number.startswith("4.") for number in clause_numbers):
            groups: list[_SectionGroup] = []
            for group_id, start_no, end_no, label in _PREDEFINED_CONTENT_GROUPS:
                group_entries = [
                    entry
                    for entry in entries
                    if entry.clause_no is not None and self._clause_no_in_range(entry.clause_no, start_no, end_no)
                ]
                if group_entries:
                    groups.append(
                        _SectionGroup(
                            group_id=group_id,
                            section=f"{start_no}-{end_no}",
                            label=label,
                            entries=group_entries,
                        )
                    )
            if groups:
                covered = {entry.clause_no for group in groups for entry in group.entries}
                for entry in entries:
                    if entry.clause_no not in covered:
                        groups.append(
                            _SectionGroup(
                                group_id=f"content_{entry.clause_no or 'other'}",
                                section=entry.clause_no or "内容",
                                label=entry.section_label,
                                entries=[entry],
                            )
                        )
                return groups

        groups = []
        batch_size = 6
        for batch_index in range(0, len(entries), batch_size):
            batch = entries[batch_index : batch_index + batch_size]
            groups.append(
                _SectionGroup(
                    group_id=f"content_group_{batch_index // batch_size + 1}",
                    section=self._build_group_section(batch),
                    label=f"内容分组{batch_index // batch_size + 1}",
                    entries=batch,
                )
            )
        return groups

    @staticmethod
    def _clause_no_in_range(clause_no: str, start_no: str, end_no: str) -> bool:
        value = SOPStructuredChunker._clause_no_key(clause_no)
        return SOPStructuredChunker._clause_no_key(start_no) <= value <= SOPStructuredChunker._clause_no_key(end_no)

    @staticmethod
    def _clause_no_key(clause_no: str) -> tuple[int, ...]:
        return tuple(int(part) for part in clause_no.split(".") if part.isdigit())

    def _build_doc_summary_chunk(
        self,
        *,
        document_id: str,
        metadata: _Metadata,
        doc_title: str,
        base_entries: list[_Clause],
        section_groups: list[_SectionGroup],
        filename: str,
    ) -> TextChunk:
        purpose = next((entry.content for entry in base_entries if entry.section_heading == "目的"), "")
        scope = next((entry.content for entry in base_entries if entry.section_heading == "适用范围"), "")
        duty_entries = [entry for entry in base_entries if entry.section_heading == "职责"]
        section_labels = [group.label for group in section_groups if group.group_id != "basic_info"]
        parts: list[str] = []
        if purpose:
            parts.append(f"本文件用于{purpose}")
        if scope:
            parts.append(f"适用范围为{scope}")
        if duty_entries:
            parts.append(f"职责包括：{'；'.join(self._compact_clause_text(entry) for entry in duty_entries[:4])}")
        if section_labels:
            parts.append(f"内容覆盖{'、'.join(section_labels)}")
        summary = "。".join(part.rstrip("。；") for part in parts if part).strip()
        if summary:
            summary += "。"
        else:
            summary = f"本文件围绕{doc_title}提供结构化操作规范和安全要求。"

        spans = [entry for entry in base_entries]
        spans.extend(entry for group in section_groups for entry in group.entries)
        char_start = min((entry.start for entry in spans), default=metadata.metadata_start)
        char_end = max((entry.end for entry in spans), default=metadata.metadata_end)
        return self._new_chunk(
            document_id=document_id,
            chunk_id=f"{document_id}::doc_summary",
            text=summary,
            char_start=char_start,
            char_end=char_end,
            chunk_type="doc_summary",
            doc_title=doc_title,
            document_code=metadata.document_code,
            section="ALL",
            section_label="整份文档摘要",
            keywords=self._extract_keywords(doc_title, metadata.document_code, *section_labels, summary),
            section_path=["ALL"],
            source_file_name=filename,
            version=metadata.version,
            effective_date=metadata.effective_date,
            risk_level=self._aggregate_risk(spans),
            is_generated_summary=True,
            summary_text=summary,
        )

    def _build_section_summary_chunk(
        self,
        *,
        document_id: str,
        metadata: _Metadata,
        doc_title: str,
        filename: str,
        group: _SectionGroup,
        parent_id: str,
    ) -> TextChunk:
        body = "；".join(self._compact_clause_text(entry) for entry in group.entries)
        content = f"本部分涵盖 {group.section}，包括：{body}。"
        return self._new_chunk(
            document_id=document_id,
            chunk_id=f"{document_id}::section_summary::{group.group_id}",
            text=content,
            char_start=min(entry.start for entry in group.entries),
            char_end=max(entry.end for entry in group.entries),
            chunk_type="section_summary",
            parent_id=parent_id,
            doc_title=doc_title,
            document_code=metadata.document_code,
            section=group.section,
            section_label=group.label,
            keywords=self._extract_keywords(doc_title, group.label, group.section, body),
            section_path=[group.label],
            source_file_name=filename,
            version=metadata.version,
            effective_date=metadata.effective_date,
            risk_level=self._aggregate_risk(group.entries),
            is_generated_summary=True,
            summary_text=content,
        )

    def _build_clause_chunk(
        self,
        *,
        document_id: str,
        metadata: _Metadata,
        doc_title: str,
        filename: str,
        entry: _Clause,
        parent_id: str | None,
        chunk_id: str,
    ) -> TextChunk:
        section = entry.clause_no or entry.section_heading
        section_path = [entry.section_heading]
        if entry.clause_no:
            section_path.append(entry.clause_no)
        return self._new_chunk(
            document_id=document_id,
            chunk_id=chunk_id,
            text=entry.content,
            char_start=entry.start,
            char_end=entry.end,
            chunk_type="clause",
            parent_id=parent_id,
            doc_title=doc_title,
            document_code=metadata.document_code,
            section=section,
            section_label=entry.section_label,
            keywords=self._extract_keywords(doc_title, entry.section_label, entry.clause_no, entry.content),
            section_path=section_path,
            clause_no=entry.clause_no,
            clause_no_normalized=entry.clause_no,
            source_file_name=filename,
            version=metadata.version,
            effective_date=metadata.effective_date,
            risk_level=self._infer_risk_level(entry.content),
        )

    def _new_chunk(
        self,
        *,
        document_id: str,
        chunk_id: str,
        text: str,
        char_start: int,
        char_end: int,
        chunk_type: str,
        doc_title: str,
        document_code: str | None,
        section: str,
        section_label: str,
        source_file_name: str,
        parent_id: str | None = None,
        keywords: list[str] | None = None,
        section_path: list[str] | None = None,
        clause_no: str | None = None,
        clause_no_normalized: str | None = None,
        version: str | None = None,
        effective_date: str | None = None,
        risk_level: str | None = None,
        is_generated_summary: bool = False,
        summary_text: str | None = None,
    ) -> TextChunk:
        display_text = text.strip()
        retrieval_text = self._build_retrieval_text(
            doc_title=doc_title,
            document_code=document_code,
            chunk_type=chunk_type,
            section=section,
            section_label=section_label,
            keywords=keywords or [],
            content=display_text,
        )
        return TextChunk(
            chunk_id=chunk_id,
            document_id=document_id,
            chunk_index=0,
            text=display_text,
            char_start=char_start,
            char_end=char_end,
            chunk_type=chunk_type,
            parent_id=parent_id,
            doc_title=doc_title,
            document_code=document_code,
            section=section,
            section_label=section_label,
            keywords=keywords or [],
            retrieval_text=retrieval_text,
            display_text=display_text,
            summary_text=summary_text,
            section_path=section_path or [],
            clause_no=clause_no,
            clause_no_normalized=clause_no_normalized,
            source_file_name=source_file_name,
            version=version,
            effective_date=effective_date,
            risk_level=risk_level,
            is_generated_summary=is_generated_summary,
        )

    def _build_metadata_content(self, metadata: _Metadata, doc_title: str) -> str:
        parts = [f"文档名称 {doc_title}"]
        if metadata.document_code:
            parts.append(f"文件编号 {metadata.document_code}")
        if metadata.version:
            parts.append(f"版本 {metadata.version}")
        if metadata.effective_date:
            parts.append(f"生效日期 {metadata.effective_date}")
        return "，".join(parts) + "。"

    @staticmethod
    def _build_group_section(entries: list[_Clause]) -> str:
        clause_numbers = [entry.clause_no for entry in entries if entry.clause_no]
        if not clause_numbers:
            headings = {entry.section_heading for entry in entries}
            return "+".join(sorted(headings))
        if len(clause_numbers) == 1:
            return clause_numbers[0]
        return f"{clause_numbers[0]}-{clause_numbers[-1]}"

    def _build_retrieval_text(
        self,
        *,
        doc_title: str,
        document_code: str | None,
        chunk_type: str,
        section: str,
        section_label: str,
        keywords: list[str],
        content: str,
    ) -> str:
        parts = [doc_title]
        if document_code:
            parts.append(document_code)
        parts.extend(part for part in (chunk_type, section, section_label) if part)
        parts.extend(keywords)
        parts.append(content)
        return "\n".join(part for part in parts if part).strip()

    def _extract_keywords(self, *texts: str | None) -> list[str]:
        keywords: list[str] = []
        seen: set[str] = set()
        for text in texts:
            if not text:
                continue
            for token in _TOKEN_PATTERN.findall(text):
                normalized = token.strip()
                if len(normalized) < 2:
                    continue
                if normalized in _STOPWORD_TOKENS:
                    continue
                if normalized in seen:
                    continue
                seen.add(normalized)
                keywords.append(normalized)
                if len(keywords) >= 8:
                    return keywords
        return keywords

    def _infer_clause_label(self, clause_no: str | None, parts: list[str], default_label: str) -> str:
        text = " ".join(parts)
        if clause_no:
            if "铁屑" in text or "长屑" in text:
                return "清屑要求"
            if "装夹" in text or "工件" in text:
                return "工件装夹要求"
            if "停车" in text or "反车" in text:
                return "停车与反车要求"
            if "异常" in text or "事故" in text:
                return "异常与事故处理要求"
            if "冷却液" in text or "冷却" in text:
                return "工具与冷却要求"
            if "防护服" in text or "围巾" in text or "手套" in text:
                return "个人防护要求"
            if "检查" in text or "开机" in text:
                return "作业前检查要求"
            if "记录" in text:
                return "记录要求"
        return default_label

    @staticmethod
    def _compact_clause_text(entry: _Clause) -> str:
        if entry.clause_no:
            return f"{entry.clause_no} {entry.content}"
        return f"{entry.section_label}：{entry.content}"

    def _infer_risk_level(self, text: str) -> str:
        if any(term in text for term in _HIGH_RISK_TERMS):
            return "high"
        if any(term in text for term in _MEDIUM_RISK_TERMS):
            return "medium"
        return "low"

    def _aggregate_risk(self, entries: list[_Clause]) -> str:
        levels = {self._infer_risk_level(entry.content) for entry in entries}
        if "high" in levels:
            return "high"
        if "medium" in levels:
            return "medium"
        return "low"
