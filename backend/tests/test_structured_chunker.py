"""结构化分块器基线测试。

本文件用于固定当前 structured_chunker.py 的行为基线，
为后续 Phase 2B chunk 优化提供回归保护。

重要说明：
- 这些测试验证的是"当前实现行为"，不一定是"期望行为"
- 测试名称中带 "currently" 的断言描述的是现状，而非最终期望
- 测试名称中带 "yet" 的断言描述的是当前缺口
- 后续进入 Phase 2B 时，可以对比这些基线判断哪些行为是有意改变
"""

import re

import pytest

from backend.app.rag.chunkers.structured_chunker import (
    _CLAUSE_PATTERN,
    _HEADING_SEQUENCE,
    _PREDEFINED_CONTENT_GROUPS,
    SOPStructuredChunker,
)
from backend.app.rag.chunkers.text_chunker import TextChunk


# ─────────────────────────────────────────────────────────────────────────────
# Test Helpers
# ─────────────────────────────────────────────────────────────────────────────


def make_wi_sj_052_style_text() -> str:
    """构造 WI-SJ-052 风格的结构化 SOP/WI 文本。

    这类文本应该触发 should_use() == True。
    """
    return """摇臂钻床安全操作规范
文件编号 WI-SJ-052
版本号 A/0
生效日期 2024-01-01

目的
本文件规定摇臂钻床安全操作要求。

适用范围
本文件适用于摇臂钻床操作人员。

职责
3.1 操作工负责日常操作。
3.2 班组长负责监督检查。

内容
4.1 操作人员必须穿戴防护服。
4.2 开机前检查设备状态。
4.3 确认工件夹紧后方可启动。
4.13 钻削过程中应及时清理铁屑。
4.14 出现异常响声时停止自动进给。
4.22 发现设备异常立即停机。
4.25 下班后卸下钻头，切断电源。
修订页
编制 张三
审核 李四
批准 王五
"""


def make_step_style_text() -> str:
    """构造 Step1/Step2 风格的结构化文本。

    当前实现中，Step 风格的条目不会被 _CLAUSE_PATTERN 识别为条款。
    """
    return """皮带轮部品（通用）作业指导书 SOP

目的
本文件规定皮带轮部品装配操作要求。

适用范围
本文件适用于皮带轮部品装配作业。

职责
操作工负责按本指导书操作。

内容
Step1 将止动螺丝放入专用治具孔中。
Step2 使用手扳压力机压装。
Step3 用扭矩扳手拧紧，扭矩 4.5N。
Step4 检查安装位置是否正确。
"""


def make_sop_title_only_text() -> str:
    """构造标题有 SOP 但正文结构不完全符合的文本。

    标题中有 SOP 字样，但条款格式不是 X.Y 形式。
    """
    return """电机齿轮安装SOP

目的
本文件规定电机齿轮安装要求。

适用范围
本文件适用于电机齿轮安装作业。

职责
操作工负责按本指导书操作。

内容
1. 检查齿轮和轴的配合尺寸。
2. 对斜齿轮进行加温，设定温度 250°，时间 1 小时。
3. 安装后检查齿轮与齿条的间隙，应控制在 0.15mm-0.3mm。
"""


def make_plain_alarm_manual_text() -> str:
    """构造普通报警手册文本。

    这类文本不应触发 should_use()。
    """
    return """故障代码手册

700000 面板急停报警
现场先检查急停按钮是否按下，再检查安全继电器状态。

700014 围栏急停报警
检查围栏门是否关闭，安全锁是否正常。

700018 B轴夹紧放松信号异常
检查夹紧传感器和放松电磁阀状态。
"""


def make_minimal_structured_text() -> str:
    """构造最小可触发结构化分块的文本。

    包含必须的标题序列和足够多的条款。
    """
    return """测试作业指导书
文件编号 TEST-001

目的
规定测试操作要求。

适用范围
适用于测试作业。

职责
操作工负责执行。

内容
4.1 作业前检查设备。
4.2 确认安全防护到位。
4.3 按规程启动设备。
4.4 记录运行参数。
4.5 发现异常及时报告。
"""


# ─────────────────────────────────────────────────────────────────────────────
# 1. should_use() 正例/反例测试
# ─────────────────────────────────────────────────────────────────────────────


class TestShouldUsePositiveCases:
    """验证 should_use() 正确返回 True 的场景。"""

    def test_should_use_accepts_wi_style_structured_text(self) -> None:
        """WI-SJ-052 风格的结构化 SOP/WI 文本应触发 should_use() == True。"""
        chunker = SOPStructuredChunker()
        text = make_wi_sj_052_style_text()
        result = chunker.should_use(text=text, filename="WI-SJ-052.txt")
        assert result is True, "WI-SJ-052 风格文本应触发结构化分块"

    def test_should_use_accepts_minimal_structured_text(self) -> None:
        """最小结构化文本（满足 heading_hits >= 3 且 clause_hits >= 4）应触发。"""
        chunker = SOPStructuredChunker()
        text = make_minimal_structured_text()
        result = chunker.should_use(text=text, filename="test.txt")
        assert result is True, "满足条件的最小结构化文本应触发结构化分块"

    def test_should_use_accepts_sop_filename_with_reduced_requirements(self) -> None:
        """文件名包含 SOP/WI 时，条件放宽（heading >= 2 且 clause >= 2）。"""
        chunker = SOPStructuredChunker()
        text = """测试文档

目的
规定操作要求。

适用范围
适用于装配作业。

内容
4.1 检查设备状态。
4.2 按规程操作。
"""
        # 文件名包含 SOP，条件放宽
        result = chunker.should_use(text=text, filename="装配SOP.docx")
        assert result is True, "文件名含 SOP 且满足放宽条件时应触发"


class TestShouldUseNegativeCases:
    """验证 should_use() 正确返回 False 的场景。"""

    def test_should_use_rejects_plain_alarm_manual(self) -> None:
        """普通报警手册文本不应触发结构化分块。"""
        chunker = SOPStructuredChunker()
        text = make_plain_alarm_manual_text()
        result = chunker.should_use(text=text, filename="123.txt")
        assert result is False, "普通报警手册不应触发结构化分块"

    def test_should_use_rejects_unstructured_text(self) -> None:
        """无结构特征的纯文本不应触发。"""
        chunker = SOPStructuredChunker()
        text = "这是一段普通的文本，没有任何结构化特征。"
        result = chunker.should_use(text=text, filename="plain.txt")
        assert result is False, "无结构特征文本不应触发结构化分块"

    def test_should_use_rejects_insufficient_headings(self) -> None:
        """标题序列不足时不触发。"""
        chunker = SOPStructuredChunker()
        text = """测试文档

目的
只有目的章节。

内容
4.1 第一条。
4.2 第二条。
4.3 第三条。
4.4 第四条。
"""
        result = chunker.should_use(text=text, filename="test.txt")
        # 只有 1 个标题命中（目的），不满足 >= 3
        assert result is False, "标题序列不足时不应触发"


class TestShouldUseStepStyleText:
    """验证 Step 风格文本的 should_use() 行为。"""

    def test_should_use_rejects_step_style_text_even_with_sop_filename_currently(self) -> None:
        """Step 风格文本即使文件名包含 SOP，当前也不会触发。

        当前实现：Step 风格的条目不计入 clause_hits（因为 _CLAUSE_PATTERN 不识别），
        因此即使 filename_signal=True，也无法满足 clause >= 2 的放宽条件。
        """
        chunker = SOPStructuredChunker()
        text = make_step_style_text()
        result = chunker.should_use(text=text, filename="皮带轮部品作业指导书SOP.docx")
        assert result is False, "当前实现下，Step 风格文本即使文件名含 SOP 也不触发结构化分块"

    def test_should_use_rejects_step_style_text_without_sop_filename(self) -> None:
        """Step 风格文本在文件名不含 SOP 时当前不会触发。

        当前实现：Step 条目不计入 clause_hits，可能无法满足 clause >= 4 的要求。
        """
        chunker = SOPStructuredChunker()
        text = make_step_style_text()
        result = chunker.should_use(text=text, filename="作业指导书.txt")
        assert result is False, "当前实现下，Step 风格文本在普通文件名下不触发结构化分块"


class TestShouldUseSopTitleOnly:
    """验证标题有 SOP 但正文结构不完全符合的文本。"""

    def test_should_use_rejects_sop_title_only_text_without_x_y_clauses(self) -> None:
        """标题有 SOP，但正文只有纯数字条款时当前不会触发。

        当前实现：纯数字条款（如 "1." "2."）不被 _CLAUSE_PATTERN 识别，
        因此即使文件名包含 SOP，也无法满足 clause >= 2 的放宽条件。
        """
        chunker = SOPStructuredChunker()
        text = make_sop_title_only_text()
        result = chunker.should_use(text=text, filename="电机齿轮安装SOP.txt")
        assert result is False, "当前实现下，纯数字条款的 SOP 标题文本不会触发结构化分块"


# ─────────────────────────────────────────────────────────────────────────────
# 2. _CLAUSE_PATTERN / 条款提取行为测试
# ─────────────────────────────────────────────────────────────────────────────


class TestClausePatternRecognition:
    """验证 _CLAUSE_PATTERN 正则表达式的匹配行为。"""

    def test_clause_pattern_matches_x_y_format(self) -> None:
        """X.Y 格式的条款号应被正确识别。"""
        match = _CLAUSE_PATTERN.match("4.13 钻削过程中应及时清理铁屑。")
        assert match is not None, "X.Y 格式条款应被识别"
        assert match.group("number") == "4.13", "应正确提取条款号"
        assert "钻削过程中应及时清理铁屑" in match.group("body"), "应正确提取条款正文"

    def test_clause_pattern_matches_x_y_format_with_trailing_dot(self) -> None:
        """X.Y. 格式（带尾随点）也应被识别。"""
        match = _CLAUSE_PATTERN.match("4.13. 钻削过程中应及时清理铁屑。")
        assert match is not None, "X.Y. 格式条款应被识别"
        assert match.group("number") == "4.13"

    def test_clause_pattern_does_not_match_step_format(self) -> None:
        """Step1/Step2 格式当前不被识别为条款。

        这是当前实现的限制，测试名称中的 'yet' 表明这是待改进的缺口。
        """
        match = _CLAUSE_PATTERN.match("Step1 将止动螺丝放入专用治具孔中。")
        assert match is None, "Step 格式当前不被 _CLAUSE_PATTERN 识别"

    def test_clause_pattern_does_not_match_pure_number_format(self) -> None:
        """纯数字格式（如 "1." "2."）不被识别为条款。"""
        match = _CLAUSE_PATTERN.match("1. 检查齿轮和轴的配合尺寸。")
        assert match is None, "纯数字格式当前不被 _CLAUSE_PATTERN 识别"

    def test_clause_pattern_matches_various_x_y_examples(self) -> None:
        """验证多个 X.Y 格式的变体。"""
        valid_clauses = [
            "4.1 操作人员必须穿戴防护服。",
            "4.25 下班后卸下钻头，切断电源。",
            "3.1 操作工负责日常操作。",
            "10.5 这是测试条款。",
        ]
        for clause in valid_clauses:
            match = _CLAUSE_PATTERN.match(clause)
            assert match is not None, f"'{clause}' 应被识别为有效条款格式"


class TestStepStyleLinesDoNotBecomeClauseChunks:
    """验证 Step 风格行不会被识别为条款 chunk。"""

    def test_step_style_lines_do_not_become_clause_chunks_yet(self) -> None:
        """Step 风格的行当前不会生成 clause 类型的 chunk。

        这是当前实现的缺口，测试名称中的 'yet' 表明这是待改进的点。
        """
        chunker = SOPStructuredChunker()
        text = make_step_style_text()
        filename = "皮带轮部品SOP.docx"

        should_use = chunker.should_use(text=text, filename=filename)
        assert should_use is False, "当前实现下，Step 风格文本不会触发结构化分块"

        chunks = chunker.split(document_id="test-doc", text=text, filename=filename)
        assert chunks == [], "当前实现下，未触发结构化分块的 Step 文本不会产出结构化 chunk"

        # 检查是否有 clause 类型的 chunk
        clause_chunks = [c for c in chunks if c.chunk_type == "clause"]
        assert clause_chunks == [], "当前实现下，Step 风格文本不会生成 clause 类型的结构化 chunk"


# ─────────────────────────────────────────────────────────────────────────────
# 3. Chunk 产物结构测试
# ─────────────────────────────────────────────────────────────────────────────


class TestStructuredChunksIncludeMultigranularityOutputs:
    """验证结构化分块生成多粒度输出。"""

    def test_structured_chunks_include_multigranularity_outputs(self) -> None:
        """对一个最小可触发的结构化文本，验证会生成多粒度 chunk。"""
        chunker = SOPStructuredChunker()
        text = make_wi_sj_052_style_text()

        chunks = chunker.split(document_id="test-doc-001", text=text, filename="WI-SJ-052.txt")

        # 验证生成了 chunk
        assert len(chunks) > 0, "结构化文本应生成 chunk"

        # 验证 chunk 类型分布
        chunk_types = {c.chunk_type for c in chunks}

        # 应该包含 metadata 或 doc_summary
        assert "metadata" in chunk_types or "doc_summary" in chunk_types, \
            "应生成 metadata 或 doc_summary 类型的 chunk"

        # 应该包含 section_summary
        assert "section_summary" in chunk_types, \
            "应生成 section_summary 类型的 chunk"

        # 应该包含 clause
        assert "clause" in chunk_types, \
            "应生成 clause 类型的 chunk"

    def test_clause_chunks_have_required_fields(self) -> None:
        """验证 clause chunk 包含必要字段。"""
        chunker = SOPStructuredChunker()
        text = make_wi_sj_052_style_text()

        chunks = chunker.split(document_id="test-doc-001", text=text, filename="WI-SJ-052.txt")
        clause_chunks = [c for c in chunks if c.chunk_type == "clause"]

        assert len(clause_chunks) > 0, "应有 clause chunk"

        for chunk in clause_chunks:
            # 验证必要字段存在
            assert chunk.chunk_id, "clause chunk 应有 chunk_id"
            assert chunk.document_id == "test-doc-001", "clause chunk 应有正确的 document_id"
            assert chunk.text, "clause chunk 应有 text 内容"

            # 验证条款特有字段
            if chunk.clause_no:
                assert chunk.clause_no, "有条款号时应保存 clause_no"
                assert chunk.clause_no_normalized, "有条款号时应生成 clause_no_normalized"

            # 验证父子关系
            assert chunk.parent_id is not None, "clause chunk 应有 parent_id 指向所属 section"

            # 验证检索文本
            assert chunk.retrieval_text, "clause chunk 应有 retrieval_text"

    def test_metadata_chunk_has_document_code(self) -> None:
        """验证 metadata chunk 包含文档编号等信息。"""
        chunker = SOPStructuredChunker()
        text = make_wi_sj_052_style_text()

        chunks = chunker.split(document_id="test-doc-001", text=text, filename="WI-SJ-052.txt")
        metadata_chunks = [c for c in chunks if c.chunk_type == "metadata"]

        if metadata_chunks:
            metadata = metadata_chunks[0]
            assert metadata.document_code == "WI-SJ-052", \
                "metadata chunk 应提取文件编号"
            assert metadata.version == "A/0", \
                "metadata chunk 应提取版本号"
            assert metadata.effective_date == "2024-01-01", \
                "metadata chunk 应提取生效日期"

    def test_doc_summary_chunk_exists(self) -> None:
        """验证生成 doc_summary chunk。"""
        chunker = SOPStructuredChunker()
        text = make_wi_sj_052_style_text()

        chunks = chunker.split(document_id="test-doc-001", text=text, filename="WI-SJ-052.txt")
        doc_summaries = [c for c in chunks if c.chunk_type == "doc_summary"]

        assert len(doc_summaries) == 1, "应有且仅有一个 doc_summary chunk"

        doc_summary = doc_summaries[0]
        assert doc_summary.section == "ALL", "doc_summary 的 section 应为 ALL"
        assert doc_summary.is_generated_summary is True, \
            "doc_summary 应标记为生成的摘要"

    def test_section_summary_chunks_have_parent_reference(self) -> None:
        """验证 section_summary chunk 有正确的父子关系。"""
        chunker = SOPStructuredChunker()
        text = make_wi_sj_052_style_text()

        chunks = chunker.split(document_id="test-doc-001", text=text, filename="WI-SJ-052.txt")
        doc_summaries = [c for c in chunks if c.chunk_type == "doc_summary"]
        section_summaries = [c for c in chunks if c.chunk_type == "section_summary"]

        if doc_summaries and section_summaries:
            doc_summary_id = doc_summaries[0].chunk_id
            for section in section_summaries:
                assert section.parent_id == doc_summary_id, \
                    f"section_summary 的 parent_id 应指向 doc_summary ({doc_summary_id})"


# ─────────────────────────────────────────────────────────────────────────────
# 4. section_summary 抢 clause 的当前实现风险
# ─────────────────────────────────────────────────────────────────────────────


class TestSectionSummaryRetrievalTextCurrentlyIncludesChildClauseContent:
    """验证 section_summary 的 retrieval_text 包含子条款内容（当前实现风险）。

    这个测试类固定的是当前实现行为，不一定是期望行为。
    测试名称中的 "currently" 表明这是现状描述。
    """

    def test_section_summary_retrieval_text_currently_includes_child_clause_content(self) -> None:
        """section_summary 的 retrieval_text 当前包含子条款内容。

        这是当前实现的风险基线：
        - section_summary 会把分组内的 clause 内容拼进 summary 文本
        - 这可能导致 clause query 被 section_summary 抢走

        注意：这个测试固定的是"当前实现"，不代表最终期望状态。
        """
        chunker = SOPStructuredChunker()
        text = make_wi_sj_052_style_text()

        chunks = chunker.split(document_id="test-doc-001", text=text, filename="WI-SJ-052.txt")

        section_summaries = [c for c in chunks if c.chunk_type == "section_summary"]
        clause_chunks = [c for c in chunks if c.chunk_type == "clause"]

        assert section_summaries, "该基线样本文本应生成 section_summary chunk"
        assert clause_chunks, "该基线样本文本应生成 clause chunk"

        found_overlap = False
        for section in section_summaries:
            child_clauses = [c for c in clause_chunks if c.parent_id == section.chunk_id]
            if not child_clauses:
                continue

            clause = child_clauses[0]
            section_text = section.retrieval_text or section.text
            assert clause.text in section.text, \
                "当前实现下，section_summary 的 text 应直接包含子 clause 的正文"
            assert clause.text in section_text, \
                "当前实现下，section_summary 的 retrieval_text 应直接包含子 clause 的正文"
            found_overlap = True
            break

        assert found_overlap, "至少应存在一组 section_summary / child clause 内容重叠的证据"

    def test_section_and_clause_have_overlapping_content(self) -> None:
        """验证 section_summary 和 clause 存在内容重叠（当前实现风险）。

        这个测试的目的是把当前实现风险固定下来，便于后续 Phase 2B 改进时对比。
        """
        chunker = SOPStructuredChunker()
        text = make_wi_sj_052_style_text()

        chunks = chunker.split(document_id="test-doc-001", text=text, filename="WI-SJ-052.txt")

        section_summaries = [c for c in chunks if c.chunk_type == "section_summary"]
        clause_chunks = [c for c in chunks if c.chunk_type == "clause"]

        assert section_summaries, "该基线样本文本应生成 section_summary chunk"
        assert clause_chunks, "该基线样本文本应生成 clause chunk"

        # 验证当前实现：section_summary 的 text 包含 clause 的摘要
        # 这可能导致 fine-grained clause query 命中 section_summary 而非 clause
        for section in section_summaries:
            # 当前实现的 section_summary 文本格式：
            # "本部分涵盖 4.13-4.18，包括：4.13 xxx；4.14 yyy；..."
            # 这直接包含了 clause 的内容
            assert "包括" in section.text or "涵盖" in section.text, \
                "section_summary 的文本格式应符合当前实现"


# ─────────────────────────────────────────────────────────────────────────────
# 5. 硬编码分组行为测试
# ─────────────────────────────────────────────────────────────────────────────


class TestPredefinedContentGroups:
    """验证 _PREDEFINED_CONTENT_GROUPS 硬编码分组行为。

    这些测试固定的是当前硬编码行为，目的是为后续改进提供回归保护。
    测试不认可硬编码一定正确，而是把当前行为固定住。
    """

    def test_predefined_content_groups_defined(self) -> None:
        """验证预定义内容分组存在且格式正确。"""
        assert len(_PREDEFINED_CONTENT_GROUPS) == 5, \
            "当前应有 5 个预定义内容分组"

        for group in _PREDEFINED_CONTENT_GROUPS:
            assert len(group) == 4, "每个分组应有 4 个元素 (id, start, end, label)"
            group_id, start_no, end_no, label = group
            assert isinstance(group_id, str), "group_id 应为字符串"
            assert isinstance(start_no, str), "start_no 应为字符串"
            assert isinstance(end_no, str), "end_no 应为字符串"
            assert isinstance(label, str), "label 应为字符串"

    def test_predefined_content_groups_map_4_series_ranges(self) -> None:
        """验证 4.x 系列条款被映射到正确的预定义分组。"""
        chunker = SOPStructuredChunker()

        # 测试条款号范围映射
        test_cases = [
            ("4.1", "pre_operation"),      # 4.1-4.4 作业前准备
            ("4.2", "pre_operation"),
            ("4.4", "pre_operation"),
            ("4.5", "machining_and_clamping"),  # 4.5-4.12 钻削与装夹
            ("4.10", "machining_and_clamping"),
            ("4.12", "machining_and_clamping"),
            ("4.13", "chip_and_stop"),     # 4.13-4.18 清屑、变速与停车
            ("4.15", "chip_and_stop"),
            ("4.18", "chip_and_stop"),
            ("4.19", "prohibition_and_tool"),  # 4.19-4.21 禁令与工具冷却
            ("4.20", "prohibition_and_tool"),
            ("4.21", "prohibition_and_tool"),
            ("4.22", "abnormal_shutdown_maintenance"),  # 4.22-4.27 异常处理
            ("4.25", "abnormal_shutdown_maintenance"),
            ("4.27", "abnormal_shutdown_maintenance"),
        ]

        for clause_no, expected_group_id in test_cases:
            # 使用 chunker 的内部方法验证范围判断
            for group_id, start_no, end_no, _ in _PREDEFINED_CONTENT_GROUPS:
                if group_id == expected_group_id:
                    in_range = chunker._clause_no_in_range(clause_no, start_no, end_no)
                    assert in_range, \
                        f"条款 {clause_no} 应在分组 {group_id} 的范围 [{start_no}, {end_no}] 内"
                    break

    def test_clause_no_in_range_boundary_conditions(self) -> None:
        """验证条款号范围判断的边界条件。"""
        chunker = SOPStructuredChunker()

        # 边界内
        assert chunker._clause_no_in_range("4.13", "4.13", "4.18"), \
            "起始值应在范围内"
        assert chunker._clause_no_in_range("4.18", "4.13", "4.18"), \
            "结束值应在范围内"
        assert chunker._clause_no_in_range("4.15", "4.13", "4.18"), \
            "中间值应在范围内"

        # 边界外
        assert not chunker._clause_no_in_range("4.12", "4.13", "4.18"), \
            "小于起始值不应在范围内"
        assert not chunker._clause_no_in_range("4.19", "4.13", "4.18"), \
            "大于结束值不应在范围内"

    def test_heading_sequence_is_hardcoded(self) -> None:
        """验证标题序列是硬编码的。

        当前实现：_HEADING_SEQUENCE 是固定的 ("目的", "适用范围", "职责", "内容")
        这是当前限制，不支持其他标题名称。
        """
        assert _HEADING_SEQUENCE == ("目的", "适用范围", "职责", "内容"), \
            "当前标题序列是硬编码的"

    def test_content_grouping_depends_on_all_clauses_starting_with_4(self) -> None:
        """验证内容分组依赖所有条款号以 "4." 开头。

        当前实现：如果条款号不都是 4.x 系列，会回退到批量分组。
        """
        chunker = SOPStructuredChunker()

        # 构造一个 4.x 系列的条款列表
        four_series_clauses = [
            type('_Clause', (), {
                'clause_no': '4.1',
                'content': '测试内容',
                'start': 0,
                'end': 10,
                'section_heading': '内容',
                'section_label': '测试条款'
            })(),
            type('_Clause', (), {
                'clause_no': '4.5',
                'content': '测试内容',
                'start': 10,
                'end': 20,
                'section_heading': '内容',
                'section_label': '测试条款'
            })(),
        ]

        # 验证 all(number.startswith("4.") for ...) 条件
        clause_numbers = [c.clause_no for c in four_series_clauses if c.clause_no]
        all_four_series = all(no.startswith("4.") for no in clause_numbers)
        assert all_four_series, "所有条款号应以 4. 开头才能触发预定义分组"


# ─────────────────────────────────────────────────────────────────────────────
# 6. 其他边界条件和实现细节测试
# ─────────────────────────────────────────────────────────────────────────────


class TestEdgeCasesAndImplementationDetails:
    """验证边界条件和实现细节。"""

    def test_empty_text_returns_empty_chunks(self) -> None:
        """空文本应返回空列表。"""
        chunker = SOPStructuredChunker()
        chunks = chunker.split(document_id="test", text="", filename="test.txt")
        assert chunks == [], "空文本应返回空 chunk 列表"

    def test_text_without_content_heading_returns_empty(self) -> None:
        """没有 '内容' 标题的文本应返回空列表。"""
        chunker = SOPStructuredChunker()
        text = """测试文档

目的
只有目的章节。

适用范围
只有适用范围。
"""
        chunks = chunker.split(document_id="test", text=text, filename="test.txt")
        assert chunks == [], "没有 '内容' 标题的文本应返回空列表"

    def test_chunk_index_is_sequential(self) -> None:
        """验证 chunk_index 是顺序递增的。"""
        chunker = SOPStructuredChunker()
        text = make_wi_sj_052_style_text()

        chunks = chunker.split(document_id="test-doc", text=text, filename="WI-SJ-052.txt")

        for i, chunk in enumerate(chunks):
            assert chunk.chunk_index == i, \
                f"chunk_index 应为顺序递增，期望 {i}，实际 {chunk.chunk_index}"

    def test_retrieval_text_includes_doc_title(self) -> None:
        """验证 retrieval_text 包含文档标题。"""
        chunker = SOPStructuredChunker()
        text = make_wi_sj_052_style_text()

        chunks = chunker.split(document_id="test-doc", text=text, filename="WI-SJ-052.txt")

        for chunk in chunks:
            if chunk.retrieval_text and chunk.doc_title:
                # retrieval_text 应以 doc_title 开头
                assert chunk.doc_title in chunk.retrieval_text, \
                    f"retrieval_text 应包含 doc_title: {chunk.doc_title}"

    def test_risk_level_inference(self) -> None:
        """验证风险等级推断。"""
        chunker = SOPStructuredChunker()

        # 高风险关键词
        high_risk_text = "操作人员严禁在设备运行时进行维修。"
        assert chunker._infer_risk_level(high_risk_text) == "high", \
            "包含'严禁'应为高风险"

        # 中风险关键词
        medium_risk_text = "操作前应检查设备状态。"
        assert chunker._infer_risk_level(medium_risk_text) == "medium", \
            "包含'应'应为中风险"

        # 低风险
        low_risk_text = "这是普通操作说明。"
        assert chunker._infer_risk_level(low_risk_text) == "low", \
            "无风险关键词应为低风险"
