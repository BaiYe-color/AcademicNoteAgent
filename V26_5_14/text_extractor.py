#!/usr/bin/env python3
"""PDF 和 PPTX 文本提取（DeepSeek 视觉描述 + OCR 回退 + 图片 OCR + 页码标记）"""
import sys
import os
import base64
import tempfile
import io
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
DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY")        # 百炼视觉 API
TESSERACT_CMD = os.getenv("TESSERACT_CMD")                # 可选: Tesseract 路径
POPPLER_PATH = os.getenv("POPPLER_PATH")                  # 可选: Poppler 路径

# 百炼 client（视觉专用）
_dashscope_client = None

def _ensure_dashscope_client():
    global _dashscope_client
    if _dashscope_client is None:
        if not DASHSCOPE_API_KEY:
            print_error("未找到 DASHSCOPE_API_KEY，请检查 .env 文件")
            raise RuntimeError("DASHSCOPE_API_KEY not configured")
        from openai import OpenAI
        _dashscope_client = OpenAI(
            api_key=DASHSCOPE_API_KEY,
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1"
        )
    return _dashscope_client

if TESSERACT_CMD and pytesseract:
    pytesseract.pytesseract.tesseract_cmd = TESSERACT_CMD


# ---------- 工具函数 ----------
def _get_image_data_url(image_path: str) -> str:
    """根据文件扩展名生成正确的 base64 data URL，避免 MIME 类型与实际格式不符。"""
    ext = Path(image_path).suffix.lower()
    mime_map = {
        '.png': 'image/png',
        '.jpg': 'image/jpeg',
        '.jpeg': 'image/jpeg',
        '.gif': 'image/gif',
        '.webp': 'image/webp',
        '.bmp': 'image/bmp',
    }
    mime_type = mime_map.get(ext, 'image/png')
    with open(image_path, "rb") as f:
        img_b64 = base64.b64encode(f.read()).decode("utf-8")
    return f"data:{mime_type};base64,{img_b64}"


# ---------- 百炼 Qwen2-VL 视觉描述 ----------
def describe_page_with_qvl(image_path: str) -> str | None:
    """通过百炼 Qwen2-VL 对页面图片进行详细的内容描述"""
    if not DASHSCOPE_API_KEY:
        return None
    try:
        client = _ensure_dashscope_client()
        image_url = _get_image_data_url(image_path)
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
                    {"type": "image_url", "image_url": {"url": image_url}}
                ]
            }
        ]
        response = client.chat.completions.create(
            model="qwen-vl-max",
            messages=messages,
            max_tokens=4096
        )
        return response.choices[0].message.content
    except Exception as e:
        print_warning(f"Qwen2-VL 视觉描述失败：{e}")
        return None

# ---------- 百炼 Qwen2-VL 纯文字 OCR ----------
def ocr_page_with_qvl(image_path: str) -> str | None:
    """通过百炼 Qwen2-VL 进行纯文字提取（OCR）"""
    if not DASHSCOPE_API_KEY:
        return None
    try:
        client = _ensure_dashscope_client()
        image_url = _get_image_data_url(image_path)
        messages = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": "请提取这张图片中的所有文字内容，保持原有的排版结构。只输出文字，不要添加任何解释或描述。"
                    },
                    {"type": "image_url", "image_url": {"url": image_url}}
                ]
            }
        ]
        response = client.chat.completions.create(
            model="qwen-vl-max",
            messages=messages,
            max_tokens=4096
        )
        return response.choices[0].message.content
    except Exception as e:
        print_warning(f"Qwen2-VL OCR 失败：{e}")
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

# ---------- 统一 OCR 入口 ----------
def ocr_page(image_path: str) -> str:
    """优先百炼 Qwen2-VL，失败回退到 Tesseract"""
    text = ocr_page_with_qvl(image_path)
    if text is not None:
        print_status("OCR 识别成功（百炼 Qwen2-VL）", style="magenta", icon="☁️")
        return text
    print_status("尝试本地 Tesseract OCR…", style="magenta", icon="🔤")
    return ocr_page_with_tesseract(image_path)

# ---------- 检查视觉描述是否包含有效内容 ----------
def is_valid_description(desc: str) -> bool:
    """判断视觉描述是否包含实质内容。Qwen2-VL 质量较高，条件放宽。"""
    if not desc or not desc.strip():
        return False
    return len(desc.strip()) >= 10

# ---------- PPTX 图片提取 ----------
def extract_slide_images(slide) -> list:
    """递归提取幻灯片（含组合形状 GroupShape）中所有图片的临时文件路径列表"""
    image_paths = []

    def _extract_from_shape(shape):
        if shape.shape_type == 13:  # MSO_SHAPE_TYPE.PICTURE
            try:
                image = shape.image
                image_bytes = image.blob
                content_type = getattr(image, 'content_type', None)
                if content_type:
                    ext = content_type.split('/')[-1]
                    suffix = '.jpg' if ext == 'jpeg' else '.png'
                else:
                    suffix = '.png'
                with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                    tmp.write(image_bytes)
                    image_paths.append(tmp.name)
            except Exception as e:
                print_warning(f"  提取单张图片失败：{e}")
        elif hasattr(shape, 'shapes'):  # GroupShape 递归处理
            for sub_shape in shape.shapes:
                _extract_from_shape(sub_shape)

    for shape in slide.shapes:
        _extract_from_shape(shape)

    return image_paths

# ---------- PDF 文本提取（支持分级 OCR 与视觉描述）----------
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
                                desc = describe_page_with_qvl(tmp_name)
                                if desc and is_valid_description(desc):
                                    ocr_text = "[视觉描述]\n" + desc
                                    print_status(f"第{i}页 视觉描述成功", style="green")
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

# ---------- PPTX 文本提取----------
def extract_text_from_pptx(pptx_path: str, ocr_mode: str = "1") -> str:
    """
    从 PPTX 文件中逐页提取文本，可选对内嵌图片进行 OCR。
    ocr_mode:
        "0" - 关闭 OCR
        "1" - 仅对无文字的幻灯片内嵌图片启用 OCR（默认）
        "2" - 对所有幻灯片内嵌图片启用 OCR
    """
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
            # 提取所有形状内的文字
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

            # 提取图片路径（先提取，用于后续判断和日志）
            image_paths = extract_slide_images(slide)

            # 判断是否需要 OCR
            need_ocr = False
            if ocr_mode == "2":
                need_ocr = True
            elif ocr_mode == "1":
                need_ocr = (not slide_texts) or bool(image_paths)

            ocr_texts = []
            if need_ocr and image_paths:
                print_status(f"Slide {slide_num}: 检测到 {len(image_paths)} 张图片，正在识别...", style="magenta")
                for idx, img_path in enumerate(image_paths, start=1):
                    try:
                        if ocr_mode == "2":
                            desc = describe_page_with_qvl(img_path)
                            if desc and is_valid_description(desc):
                                ocr_texts.append(f"[视觉描述]\n{desc}")
                                print_status(f"  Slide {slide_num} 图片 {idx}/{len(image_paths)} 视觉描述成功", style="green")
                            else:
                                print_warning(f"  Slide {slide_num} 图片 {idx}/{len(image_paths)} 视觉描述无效 → 回退 OCR")
                                ocr_res = ocr_page(img_path)
                                if ocr_res:
                                    ocr_texts.append(f"[OCR 文字]\n{ocr_res}")
                                    print_status(f"  Slide {slide_num} 图片 {idx}/{len(image_paths)} OCR 成功", style="green")
                                else:
                                    print_warning(f"  Slide {slide_num} 图片 {idx}/{len(image_paths)} OCR 未返回文字")
                        else:
                            ocr_res = ocr_page(img_path)
                            if ocr_res:
                                ocr_texts.append(f"[OCR 文字]\n{ocr_res}")
                                print_status(f"  Slide {slide_num} 图片 {idx}/{len(image_paths)} OCR 成功", style="green")
                            else:
                                print_warning(f"  Slide {slide_num} 图片 {idx}/{len(image_paths)} OCR 未返回文字")
                    except Exception as e:
                        print_error(f"  Slide {slide_num} 图片 {idx}/{len(image_paths)} 识别出错：{e}")
                    finally:
                        os.unlink(img_path)
            elif need_ocr and not image_paths:
                if ocr_mode == "2":
                    print_warning(f"Slide {slide_num}: 已启用 OCR 但未检测到可提取图片")

            # 组装本页内容
            slide_content = "\n".join(slide_texts) if slide_texts else ""
            if ocr_texts:
                ocr_block = "\n\n".join(ocr_texts)
                if slide_texts:
                    slide_content += f"\n\n{ocr_block}"
                else:
                    slide_content = ocr_block

            if not slide_content.strip():
                slide_content = f"[警告] 第{slide_num}页没有可提取文字"
                print_warning(f"第{slide_num}页没有可提取文字")

            results.append(f"[原文页码：Slide {slide_num}]\n{slide_content}")
            progress.update(task, advance=1)

    print_status(f"文本提取完成，共 {slide_count} 页。", style="green", icon="✔")
    return "\n\n".join(results)