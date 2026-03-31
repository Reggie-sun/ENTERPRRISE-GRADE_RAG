"""OCR 配置：Provider、PaddleOCR 参数、质量过滤。

本模块定义 OCR（光学字符识别）相关的配置，包括 OCR 提供商选择、
PaddleOCR 引擎参数、以及低质量内容过滤策略。
作为 mixin 被 Settings 多继承组合。
"""

from pydantic import Field
from pydantic_settings import BaseSettings


class _OCRSettings(BaseSettings):
    """OCR settings mixin — 被 Settings 通过多继承组合。

    包含：OCR 开关、语言、PDF 原生文本阈值、PaddleOCR 引擎参数、质量过滤。
    """

    ocr_provider: str = "disabled"                                         # OCR 提供商: disabled / paddle 等
    ocr_language: str = "ch"                                               # OCR 识别语言（ch=中文）
    ocr_pdf_native_text_min_chars: int = Field(default=80, ge=0, le=10_000)  # PDF 原生文本超过此字符数则跳过 OCR
    # ── PaddleOCR 引擎参数 ──────────────────────────────────────────────────
    ocr_paddle_use_angle_cls: bool = False                  # 是否启用文字方向分类
    ocr_paddle_use_doc_orientation_classify: bool = False    # 是否启用文档方向分类
    ocr_paddle_use_doc_unwarping: bool = False              # 是否启用文档畸变矫正
    ocr_paddle_use_textline_orientation: bool = False        # 是否启用文本行方向检测
    ocr_paddle_ocr_version: str = "PP-OCRv5"               # PaddleOCR 版本号
    ocr_paddle_text_detection_model_name: str = "PP-OCRv5_mobile_det"     # 文本检测模型名称
    ocr_paddle_text_recognition_model_name: str = "PP-OCRv5_mobile_rec"   # 文本识别模型名称
    # ── 低质量内容过滤 ──────────────────────────────────────────────────────
    ocr_low_quality_filter_enabled: bool = True             # 是否启用低质量 OCR 结果过滤
    ocr_low_quality_min_score: float = Field(default=0.55, ge=0.0, le=1.0)  # 最低质量分数阈值
