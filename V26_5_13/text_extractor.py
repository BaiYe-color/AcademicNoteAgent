#!/usr/bin/env python3
"""PDF 和 PPTX 文本提取（DeepSeek 视觉描述 + OCR 回退 + 有效性校验）"""
import sys
import os
import base64
import tempfile
from pathlib import Path

import pdfplumber
from pptx import Presentation
from PIL import Image

# OCR 相关
try:
    import pytesseract
except ImportError:
    pytesseract = None

try:
    from pdf2image import convert_from_path
except ImportError:
    convert_from_path = None

from dotenv import load_dotenv
from utils import console, create_progress, print_status, print_warning, print_error

load_dotenv()

# ---------- 环境变量 ----------
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")          # 保留（其他函数可能用）
QIANFAN_API_KEY = os.getenv("QIANFAN_API_KEY")            # 千帆 DeepSeek-OCR（视觉模型）
TESSERACT_CMD = os.getenv("TESSERACT_CMD")                # 可选: Tesseract 路径
POPPLER_PATH = os.getenv("POPPLER_PATH")                  # 可选: Poppler 路径

if TESSERACT_CMD and pytesseract:
    pytesseract.pytesseract.tesseract_cmd = TESSERACT_CMD

# ---------- DeepSeek 视觉描述（直接理解图片内容） ----------
def describe_page_with_deepseek(image_path: str) -> str | None:
    """通过千帆 DeepSeek 视觉模型，对页面图片进行详细的内容描述，而非简单文字提取"""
    if not QIANFAN_API_KEY:
        return None
    try:
        from openai import OpenAI

        with open(image_path, "rb") as f:
            img_b64 = base64.b64encode(f.read()).decode("utf-8")
        image_url = f"data:image/png;base64,{img_b64}"

        client = OpenAI(
            api_key=QIANFAN_API_KEY,
            base_url="https://qianfan.baidubce.com/v2"
        )

        messages = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": (
                            "请详细描述这张图片中的内容，包括所有文字、图表、公式、手写笔记的结构。"
                            "尽可能完整地转述，不要添加任何不属于图片的信息。"
                        )
                    },
                    {
                        "type": "image_url",
                        "image_url": {"url": image_url}
                    }
                ]
            }
        ]

        response = client.chat.completions.create(
            model="deepseek-ocr",      # 使用千帆 DeepSeek OCR 模型（支持视觉理解）
            messages=messages,
            max_tokens=4096
        )
        return response.choices[0].message.content
    except Exception as e:
        print_warning(f"DeepSeek 视觉描述失败：{e}")
        return None

# ---------- DeepSeek 纯文字 OCR（千帆） ----------
def ocr_page_with_deepseek(image_path: str) -> str | None:
    """通过千帆调用 DeepSeek-OCR 进行传统文字提取（OCR）"""
    if not QIANFAN_API_KEY:
        return None
    try:
        from openai import OpenAI

        with open(image_path, "rb") as f:
            img_b64 = base64.b64encode(f.read()).decode("utf-8")
        image_url = f"data:image/png;base64,{img_b64}"

        client = OpenAI(
            api_key=QIANFAN_API_KEY,
            base_url="https://qianfan.baidubce.com/v2"
        )

        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "OCR"},
                    {
                        "type": "image_url",
                        "image_url": {"url": image_url}
                    }
                ]
            }
        ]

        response = client.chat.completions.create(
            model="deepseek-ocr",
            messages=messages,
            max_tokens=4096
        )
        return response.choices[0].message.content
    except Exception as e:
        print_warning(f"DeepSeek-OCR 调用失败：{e}")
        return None

# ---------- Tesseract 回退 ----------
def ocr_page_with_tesseract(image_path: str) -> str:
    if pytesseract is None:
        print_warning("pytesseract 未安装")
        return ""
    try:
        text = pytesseract.image_to_string(Image.open(image_path), lang="chi_sim+eng")
        return text.strip()
    except Exception as e:
        print_warning(f"Tesseract OCR 错误: {e}")
        return ""

# ---------- 统一 OCR 入口（纯文字提取，用于后备）----------
def ocr_page(image_path: str) -> str:
    """优先千帆 OCR（文字提取），失败回退到 Tesseract"""
    text = ocr_page_with_deepseek(image_path)
    if text is not None:
        print_status("OCR 识别成功（千帆 DeepSeek-OCR）", style="magenta", icon="☁️")
        return text
    print_status("尝试本地 Tesseract OCR…", style="magenta", icon="🔤")
    return ocr_page_with_tesseract(image_path)

# ---------- 检查视觉描述是否包含有效内容 ----------
def is_valid_description(desc: str) -> bool:
    """判断视觉描述是否包含实质内容（非空、长度足够、非纯警告）"""
    if not desc or not desc.strip():
        return False
    # 如果描述过短（少于20个字符），或者只包含警告类文字，视为无效
    desc_stripped = desc.strip()
    if len(desc_stripped) < 20:
        return False
    if desc_stripped.startswith("[警告]") or desc_stripped.startswith("警告："):
        return False
    # 额外防呆：如果描述中只包含“无可提取文本”、“扫描图片”等短语，也无效
    invalid_phrases = ["无可提取文本", "扫描图片", "可能为扫描", "无法识别"]
    if all(phrase in desc_stripped for phrase in invalid_phrases[:1]):  # 至少包含其中一些
        if len(desc_stripped) < 40:  # 且长度仍短，大概率无效
            return False
    return True

# ---------- PDF 文本提取（支持分级 OCR、视觉描述及有效性校验）----------
def extract_text(pdf_path: str, ocr_mode: str = "1") -> str:
    """
    从 PDF 文件中逐页提取文本。对于扫描/手写文档，优先使用视觉描述，若无效则回退到 OCR。
    ocr_mode:
        "0" - 关闭 OCR 和视觉描述（只使用 pdfplumber 提取）
        "1" - 仅对无文本的空白页启用 OCR/视觉描述（默认）
        "2" - 对所有页启用视觉描述（处理手写笔记/扫描件首选）
    返回带页码标记的完整文本。
    """
    print_status("正在提取 PDF 文本...", style="cyan", icon="📄")
    path = Path(pdf_path).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"找不到 PDF 文件：{path}")

    # 提前检查 OCR 环境（仅在需要时提示）
    ocr_warned = False
    if ocr_mode in ("1", "2") and convert_from_path is None:
        print_warning("pdf2image 或 Poppler 未安装，无法进行 OCR。请安装 pdf2image 和 Poppler 后重试。")
        ocr_warned = True

    all_pages = []
    with pdfplumber.open(path) as pdf:
        total = len(pdf.pages)
        with create_progress() as progress:
            task = progress.add_task("[cyan]提取 PDF…", total=total)
            for i, page in enumerate(pdf.pages, start=1):
                text = page.extract_text()
                text = text.strip() if text else ""

                ocr_text = None
                need_ocr = (ocr_mode == "2") or (ocr_mode == "1" and not text)

                if need_ocr and convert_from_path:
                    try:
                        images = convert_from_path(
                            pdf_path,
                            first_page=i,
                            last_page=i,
                            poppler_path=POPPLER_PATH if POPPLER_PATH else None
                        )
                    except Exception as e:
                        print_error(f"PDF 转图片失败 (第{i}页): {e}。请检查 Poppler 是否正确安装并配置。")
                        images = []

                    if images:
                        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                            images[0].save(tmp.name)
                            tmp_name = tmp.name
                        try:
                            if ocr_mode == "2":
                                # 优先视觉描述
                                desc = describe_page_with_deepseek(tmp_name)
                                if desc and is_valid_description(desc):
                                    ocr_text = "[视觉描述]\n" + desc
                                    print_status(f"第{i}页 视觉描述有效", style="green")
                                else:
                                    print_warning(f"第{i}页 视觉描述无效 → 回退 OCR 文字提取")
                                    ocr_text = ocr_page(tmp_name)
                                    if ocr_text:
                                        ocr_text = "[OCR]\n" + ocr_text
                                        print_status(f"第{i}页 OCR 文字提取成功", style="green")
                                    else:
                                        print_warning(f"第{i}页 OCR 文字提取失败")
                            else:
                                # 模式 1 或回退后直接 OCR
                                ocr_text = ocr_page(tmp_name)
                                if ocr_text:
                                    ocr_text = "[OCR]\n" + ocr_text
                                    print_status(f"第{i}页 OCR 文字提取成功", style="green")
                                else:
                                    print_warning(f"第{i}页 OCR 文字提取失败")
                        finally:
                            os.unlink(tmp_name)
                elif need_ocr and not convert_from_path:
                    if not ocr_warned:
                        print_warning("pdf2image 未安装，跳过 OCR")
                        ocr_warned = True

                # 组装页面内容
                page_header = f"[原文页码：第{i}页]"
                if text and ocr_text:
                    all_pages.append(f"{page_header}\n{text}\n\n[补充提取]\n{ocr_text}")
                elif ocr_text:
                    all_pages.append(f"{page_header}\n{ocr_text}")
                elif text:
                    all_pages.append(f"{page_header}\n{text}")
                else:
                    all_pages.append(
                        f"{page_header}\n[警告] 第{i}页无可提取文本，可能为扫描图片，请自行处理。"
                    )

                progress.update(task, advance=1)

    print_status(f"文本提取完成，共 {total} 页。", style="green", icon="✔")
    return "\n\n".join(all_pages)

# ---------- PPTX 文本提取（暂不支持 OCR）----------
def extract_text_from_pptx(pptx_path: str) -> str:
    print_status("正在提取 PPT 文本...", style="cyan", icon="📊")
    path = Path(pptx_path).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"找不到 PPT 文件：{path}")

    prs = Presentation(str(path))
    results = []
    slide_count = len(prs.slides)
    with create_progress() as progress:
        task = progress.add_task("[cyan]Extracting PPTX…", total=slide_count)
        for slide_num, slide in enumerate(prs.slides, start=1):
            slide_texts = []
            for shape in slide.shapes:
                if shape.has_text_frame:
                    for para in shape.text_frame.paragraphs:
                        txt = para.text.strip()
                        if txt:
                            slide_texts.append(txt)
                if shape.has_table:
                    table = shape.table
                    for row in table.rows:
                        for cell in row.cells:
                            txt = cell.text.strip()
                            if txt:
                                slide_texts.append(txt)
            if slide_texts:
                slide_content = "\n".join(slide_texts)
                slide_content = f"[原文页码：Slide {slide_num}]\n{slide_content}"
            else:
                slide_content = f"[原文页码：Slide {slide_num}]\n[警告] 第{slide_num}页没有文字"
                print_warning(f"第{slide_num}页没有文字")
            results.append(slide_content)
            progress.update(task, advance=1)
    print_status(f"文本提取完成，共 {slide_count} 页。", style="green", icon="✔")
    return "\n\n".join(results)