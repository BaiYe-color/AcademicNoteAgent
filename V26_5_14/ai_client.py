#!/usr/bin/env python3
"""DeepSeek API 调用：文本生成、修正、修订、学科识别、大纲生成"""
import os
import re
import openai

from dotenv import load_dotenv
load_dotenv()

from utils import DEFAULT_MAX_CHARS, brace_balanced, postprocess_latex, console, print_status, print_warning, print_error
from config_manager import load_config, get_recent_feedback

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
_client = None

# ---------- 笔记风格配置 ----------
NOTE_STYLE_CONFIG = {
    "narrative": {
        "name": "论述型",
        "description": "保留原文论证脉络，像一篇连贯的学术综述"
    },
    "structured": {
        "name": "结构化型",
        "description": "模块化整理，强调概念层次与关联"
    },
    "minimal": {
        "name": "极简型",
        "description": "提取核心要点，简洁 bullet points"
    }
}


def _ensure_client():
    """懒加载 DeepSeek client"""
    global _client
    if _client is None:
        if not DEEPSEEK_API_KEY:
            print_error("未找到 DEEPSEEK_API_KEY，请检查 .env 文件")
            raise RuntimeError("DEEPSEEK_API_KEY not configured")
        _client = openai.OpenAI(
            api_key=DEEPSEEK_API_KEY,
            base_url="https://api.deepseek.com"
        )
    return _client


def extract_latex_body(raw: str) -> str:
    """
    从 AI 返回的包装内容中提取纯 LaTeX / Markdown 代码正文。
    处理 markdown 代码块、AI 说明文字等包装。
    """
    # 提取 ```latex ... ``` 代码块
    match = re.search(r'```latex\s*\n(.*?)```', raw, re.DOTALL)
    if match:
        return match.group(1).strip()

    # 提取 ``` ... ``` 代码块（无 latex 标记）
    match = re.search(r'```\s*\n(.*?)```', raw, re.DOTALL)
    if match:
        return match.group(1).strip()

    # 内容已以 \section / \subsection / # 开头，直接返回
    stripped = raw.strip()
    if stripped.startswith('\\') or stripped.startswith('#'):
        return stripped

    # 找到第一个以 \section 或 # 开头的位置，截断前面的说明文字
    idx_sec = stripped.find('\\section')
    idx_hash = stripped.find('# ')
    candidates = [x for x in [idx_sec, idx_hash] if x != -1]
    if candidates:
        return stripped[min(candidates):]

    # 兜底：返回原始内容
    return stripped


# ---------- 风格化 System Prompt 构建 ----------
def _build_latex_system_prompt(note_style: str, content_type: str = None,
                                source_tracing: bool = False, ocr_mode: str = "1",
                                available_packages: list = None,
                                feedback_text: str = "",
                                outline: str = None) -> str:
    """根据笔记风格构建 LaTeX system prompt。"""

    # 通用基础约束
    base_constraints = (
        "\n【通用要求】"
        "\n1. 所有 LaTeX 环境必须正确配对，表格列数与数据一致，特殊字符转义。"
        "\n2. 只输出正文内容（不含 documentclass、usepackage、begin{document} 等），直接以 \\section 开头。"
        "\n3. 不要输出任何解释、说明、markdown 代码块标记或其他非 LaTeX 内容。"
    )

    # 根据风格构建核心 prompt
    if note_style == "narrative":
        core = (
            "你是一位擅长学术写作的研究者。请基于原文的论述逻辑，将材料重构为一篇连贯的学术综述。"
            "\n\n【核心要求】"
            "\n1. 保留作者论证的完整因果链条，不要拆成孤立知识点。"
            "\n2. 使用过渡句和衔接词展现段落间的逻辑关系（如'因此''然而''这意味着''前文指出...由此可得'）。"
            "\n3. 核心论点用精练语言概括，论证过程保留关键细节。"
            "\n4. 适当补充解释性内容，帮助读者理解'为什么'和'意味着什么'。"
            "\n5. 用自己的话重新组织和解释概念，不要直接复制原文长句，但要确保信息准确。"
            "\n6. 适当使用 \\textbf{概念}、\\textit{强调}、itemize/enumerate 列举、\\begin{quote} 引用原文关键句。"
            "\n\n【强制输出结构】"
            "\n直接以 \\section*{核心论点总览} 开头，用 1-2 段话概括全文主旨、核心问题和主要结论。"
            "\n\n\\section*{章节脉络}"
            "\n说明原文各章节/部分如何层层递进地支撑主论点，展现整体论证框架（2-4 段）。"
            "\n\n\\section{分节标题}"
            "\n按原文结构分节，每节内部按'核心观点 → 论证展开 → 意义总结'组织："
            "\n- 先提出该节的核心观点或立场"
            "\n- 然后用自然段落展开论证/推导/分析，保留关键细节"
            "\n- 最后总结该观点在整体论述中的位置和意义"
            "\n\n\\section*{跨节关联总结}"
            "\n梳理各节核心观点之间的层次、依赖、递进或对比关系，帮助读者建立完整的知识网络。"
        )
    elif note_style == "structured":
        core = (
            "你是一位擅长知识整理的学术助教。请将材料整理为结构清晰、层次分明的学习笔记。"
            "\n\n【核心要求】"
            "\n1. 按主题分块，每块内部有明确的'核心概念 → 展开说明 → 与其他概念的关系'。"
            "\n2. 使用标题层级体现知识的层次结构（大主题 → 子主题 → 细节）。"
            "\n3. 保留关键推导步骤和论证逻辑，但不要过于冗长。"
            "\n4. 在模块末尾简要说明该模块与整体知识体系的联系。"
            "\n5. 用自己的话重新组织和解释概念，不要直接复制原文长句，但要确保信息准确。"
            "\n6. 适当使用 \\textbf{概念}、\\textit{强调}、itemize/enumerate 列举、\\begin{description} 定义术语。"
            "\n\n【强制输出结构】"
            "\n直接以 \\section*{知识框架概览} 开头，用一段话概括材料涉及的知识领域、核心主题和整体结构。"
            "\n\n\\section*{章节脉络}"
            "\n列出材料的主要模块/章节及其逻辑关系（可用 itemize 简要罗列）。"
            "\n\n\\section{模块标题}"
            "\n按主题分模块，每模块内部组织为："
            "\n- 核心概念：精确定义或概括该模块的核心概念"
            "\n- 详细展开：用自然段落或列表展开说明、推导、案例"
            "\n- 关联提示：指出本模块与其他模块概念的关系（如'这是...的基础''与...形成对比'）"
            "\n\n\\section*{体系化总结}"
            "\n从更高视角梳理所有模块之间的层次关系，指出哪些是先决知识、哪些是延伸应用。"
        )
    else:  # minimal
        core = (
            "你是一位高效的学术笔记整理专家。请将材料的核心要点提取出来，整理为简洁、易读的笔记。"
            "\n\n【核心要求】"
            "\n1. 提取关键概念、定义、结论，去除冗余描述和重复内容。"
            "\n2. 使用 bullet points 和简短段落，信息密度高但不过度碎片化。"
            "\n3. 保留必要的推导步骤和逻辑关系，用 1-2 句话说明'为什么'。"
            "\n4. 适当使用 \\textbf{加粗}、itemize/enumerate 列表、\\begin{table} 表格等格式提高可读性。"
            "\n5. 用自己的话重新组织和解释概念，不要直接复制原文长句，但要确保信息准确。"
            "\n\n【强制输出结构】"
            "\n直接以 \\section*{核心要点概览} 开头，用 3-5 个 bullet points 概括全文最核心内容。"
            "\n\n\\section{主题标题}"
            "\n按主题分节，每节用 bullet points 或简短段落呈现要点："
            "\n- 概念/定义：一句话概括"
            "\n- 关键结论：核心结果"
            "\n- 重要公式/关系：如有，简要呈现"
            "\n- 与其他要点的关联：一句话说明"
            "\n\n\\section*{总结}"
            "\n用 3-5 个 bullet points 总结最重要的 takeaway。"
        )

    # 内容类型附加说明
    type_addon = ""
    if content_type:
        type_map = {
            "1": "本次材料偏向理论阐述。请在整理中突出关键概念的定义、定理的陈述与证明思路。",
            "2": "本次材料包含案例。请在整理中设置'案例背景''分析过程''结论/启示'等子节。",
            "3": "本次材料是实验性内容。请按'实验目的''方法''关键结果''结论'组织。",
            "4": "本次材料以数据为主。请大量使用表格呈现数据规律，总结关键趋势。"
        }
        type_addon = "\n\n【内容类型说明】" + type_map.get(content_type, "")

    # 原文追溯
    trace_addon = ""
    if source_tracing:
        trace_addon = (
            "\n\n用户启用了原文追溯功能。请在笔记中对关键论点、直接引用或重要数据，"
            "以 \\marginpar{原文第X页} 的方式注明原始页码（如果原文是 PPT，则用 \\marginpar{Slide X}）。"
            "不要每句都加，只在核心内容处添加。"
        )

    # OCR 模式说明
    ocr_addon = ""
    if ocr_mode == "2":
        ocr_addon = (
            "\n\n注意：部分页面的文字中包含'[视觉描述]''[OCR 文字]'或'[OCR 补充提取]'标记，"
            "表示该部分内容是从图片、图表或幻灯片内嵌图片中识别/描述出的补充文本。"
            "请将其合理融入正文，不要直接显示这些标记。"
            "如果内容中包含视觉描述，请特别重视其中对图表结构、流程、状态转移等信息的说明。"
        )

    # 大纲指导
    outline_addon = ""
    if outline:
        outline_addon = (
            f"\n\n【已确认的内容大纲】以下是经用户确认的内容大纲，请严格按照此大纲的结构和重点生成笔记正文："
            f"\n{outline}\n\n"
            "注意：大纲中的标题仅供参考，你可以根据实际内容调整措辞，但必须保持相同的逻辑结构和主题分布。"
        )

    # 反馈
    feedback_addon = ""
    if feedback_text:
        feedback_addon = "\n\n【用户历史反馈】" + feedback_text

    # 宏包
    pkg_addon = ""
    if available_packages:
        pkg_list = ", ".join(available_packages)
        pkg_addon = (
            f"\n\n【模板已加载的宏包】以下宏包已在导言区加载，你可以自由使用它们的功能：{pkg_list}。"
            f"请勿使用未在此列表中的宏包，否则可能导致编译失败。"
        )

    return core + base_constraints + type_addon + trace_addon + ocr_addon + outline_addon + feedback_addon + pkg_addon


def _build_markdown_system_prompt(note_style: str, content_type: str = None,
                                   source_tracing: bool = False, ocr_mode: str = "1",
                                   outline: str = None) -> str:
    """根据笔记风格构建 Markdown system prompt。"""

    base_constraints = (
        "\n【通用要求】"
        "\n1. 使用 #、##、### 构建层级标题。"
        "\n2. 正文用自然段落呈现，用自己的话重述概念。"
        "\n3. 适当使用 **粗体**、*斜体*、列表（- 或 1.）、引用（>）等格式。"
        "\n4. 只输出 Markdown 正文，不要包含任何前言或结语。"
    )

    if note_style == "narrative":
        core = (
            "你是一位擅长学术写作的研究者。请将材料重构为一篇连贯的学术综述式 Markdown 笔记。"
            "\n\n【核心要求】"
            "\n1. 保留作者论证的完整因果链条，不要拆成孤立知识点。"
            "\n2. 使用过渡句和衔接词展现段落间的逻辑关系。"
            "\n3. 核心论点用精练语言概括，论证过程保留关键细节。"
            "\n4. 适当补充解释性内容，帮助读者理解'为什么'和'意味着什么'。"
            "\n\n【强制输出结构】"
            "\n## 核心论点总览"
            "\n用 1-2 段话概括全文主旨、核心问题和主要结论。"
            "\n\n## 章节脉络"
            "\n说明原文各章节如何层层递进地支撑主论点。"
            "\n\n## 分节标题"
            "\n按原文结构分节，每节按'核心观点 → 论证展开 → 意义总结'组织。"
            "\n\n## 跨节关联总结"
            "\n梳理各节核心观点之间的层次、依赖、递进或对比关系。"
        )
    elif note_style == "structured":
        core = (
            "你是一位擅长知识整理的学术助教。请将材料整理为结构清晰的 Markdown 学习笔记。"
            "\n\n【核心要求】"
            "\n1. 按主题分块，每块内部有明确的'核心概念 → 展开说明 → 与其他概念的关系'。"
            "\n2. 使用标题层级体现知识的层次结构。"
            "\n3. 在模块末尾简要说明该模块与整体知识体系的联系。"
            "\n\n【强制输出结构】"
            "\n## 知识框架概览"
            "\n概括材料涉及的知识领域、核心主题和整体结构。"
            "\n\n## 章节脉络"
            "\n列出主要模块/章节及其逻辑关系。"
            "\n\n## 模块标题"
            "\n每模块含：核心概念、详细展开、关联提示。"
            "\n\n## 体系化总结"
            "\n梳理所有模块之间的层次关系。"
        )
    else:  # minimal
        core = (
            "你是一位高效的学术笔记整理专家。请将材料的核心要点提取为简洁的 Markdown 笔记。"
            "\n\n【核心要求】"
            "\n1. 提取关键概念、定义、结论，去除冗余描述。"
            "\n2. 使用 bullet points 和简短段落，信息密度高。"
            "\n3. 保留必要的推导步骤和逻辑关系。"
            "\n\n【强制输出结构】"
            "\n## 核心要点概览"
            "\n3-5 个 bullet points 概括最核心内容。"
            "\n\n## 主题标题"
            "\n按主题分节，每节用 bullet points 呈现要点。"
            "\n\n## 总结"
            "\n3-5 个 bullet points 总结最重要的 takeaway。"
        )

    type_addon = ""
    if content_type:
        type_map = {
            "1": "本次材料偏向理论阐述。请突出关键概念的定义与定理。",
            "2": "本次材料包含案例。请设置'案例背景''分析''结论'等子节。",
            "3": "本次材料是实验性内容。请按'实验目的''方法''结果''结论'组织。",
            "4": "本次材料以数据为主。请大量使用表格呈现数据规律。"
        }
        type_addon = "\n\n【内容类型说明】" + type_map.get(content_type, "")

    trace_addon = ""
    if source_tracing:
        trace_addon = "\n\n用户启用了追溯功能。请在关键论点后使用 [原文第X页] 或 [Slide X] 标注原始位置。"

    ocr_addon = ""
    if ocr_mode == "2":
        ocr_addon = (
            "\n\n注意：部分内容包含'[视觉描述]''[OCR 文字]'等标记，"
            "表示从图片中识别/描述出的补充文本。请合理融入正文，不要直接显示这些标记。"
        )

    outline_addon = ""
    if outline:
        outline_addon = (
            f"\n\n【已确认的内容大纲】请严格按照以下大纲生成笔记正文：\n{outline}"
        )

    return core + base_constraints + type_addon + trace_addon + ocr_addon + outline_addon


def identify_subject(text: str) -> str:
    if not DEEPSEEK_API_KEY:
        return "未知"
    client = _ensure_client()
    snippet = text[:1000]
    try:
        print_status("识别学科领域...", style="magenta", icon="🔍")
        resp = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": "以下文本属于哪个学科？只需回复一个简短学科名（如计算机科学、法律、医学）。"},
                {"role": "user", "content": snippet}
            ],
            temperature=0.0,
        )
        subject = resp.choices[0].message.content.strip()
        print_status(f"识别结果：{subject}", style="green")
        return subject
    except Exception as e:
        print_error(f"学科识别失败：{e}")
        return "未知"


def generate_title(text: str) -> str:
    if not DEEPSEEK_API_KEY:
        return "未命名笔记"
    client = _ensure_client()
    snippet = text[:2000]
    try:
        print_status("生成笔记标题...", style="magenta", icon="🖋️")
        resp = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": "根据以下文本，生成一个简洁的中文笔记标题，不超过15个字，只返回标题本身。"},
                {"role": "user", "content": snippet}
            ],
            temperature=0.3,
        )
        title = resp.choices[0].message.content.strip()
        print_status(f"标题：{title}", style="green")
        return title
    except Exception as e:
        print_error(f"标题生成失败：{e}")
        return "未命名笔记"


# ---------- 大纲生成 ----------
def generate_outline(text: str, note_style: str = "narrative",
                      max_chars: int = 8000, title: str = "",
                      content_type: str = None) -> str:
    """
    为长文档生成内容大纲，供用户确认后再生成全文。
    返回大纲文本（LaTeX/Markdown 格式）。
    """
    if not DEEPSEEK_API_KEY:
        print_error("未找到 DEEPSEEK_API_KEY")
        return ""

    client = _ensure_client()
    snippet = text[:max_chars]
    if len(text) > max_chars:
        snippet += "\n\n[以上为部分原文，请基于这些内容生成大纲]"

    style_desc = NOTE_STYLE_CONFIG.get(note_style, NOTE_STYLE_CONFIG["narrative"])

    system_prompt = (
        f"你是一位学术内容分析师。请根据以下材料生成一份详细的内容大纲，"
        f"用于指导后续以'{style_desc['name']}'风格撰写笔记。"
        f"\n\n【风格要求】"
        f"\n{style_desc['description']}"
        f"\n\n【大纲要求】"
        f"\n1. 识别材料的核心论点和主要章节结构"
        f"\n2. 为每个章节写出：标题 + 该章节的核心论点/核心概念（2-3句话）"
        f"\n3. 指出章节之间的逻辑关系（递进、并列、对比等）"
        f"\n4. 不要输出正文内容，只输出大纲"
        f"\n5. 输出格式：使用 # 和 ## 层级标题"
    )

    if content_type:
        type_map = {
            "1": "理论阐述类材料，大纲应突出概念定义和定理结构。",
            "2": "案例分析类材料，大纲应包含案例背景、分析框架和结论启示。",
            "3": "实验类材料，大纲应按实验目的、方法、结果、结论组织。",
            "4": "数据类材料，大纲应突出数据来源、变量和规律趋势。"
        }
        system_prompt += "\n\n【内容类型说明】" + type_map.get(content_type, "")

    user_prompt = f"材料标题：{title}\n\n原文内容：\n{snippet}"

    print_status(f"正在生成'{style_desc['name']}'风格的内容大纲...", style="magenta", icon="📋")
    try:
        resp = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.3,
            max_tokens=4096,
        )
        outline = resp.choices[0].message.content.strip()
        outline = extract_latex_body(outline)
        print_status("大纲生成完成。", style="green")
        return outline
    except Exception as e:
        print_error(f"大纲生成失败：{e}")
        return ""


# ---------- 正文生成 ----------
def generate_latex_content(text: str, max_chars: int = DEFAULT_MAX_CHARS,
                            content_type: str = None, source_tracing: bool = False,
                            ocr_mode: str = "1", available_packages: list = None,
                            note_style: str = "narrative", outline: str = None) -> str:
    if not DEEPSEEK_API_KEY:
        print_error("未找到 DEEPSEEK_API_KEY，请检查 .env 文件")
        return ""

    client = _ensure_client()
    if len(text) > max_chars:
        processed = text[:max_chars] + "\n\n[以下为部分内容，请基于此整理]"
        print_warning(f"文本过长，已截取前 {max_chars} 字符。")
    else:
        processed = text

    config_data = load_config()
    useful_feedback = get_recent_feedback(config_data)
    feedback_text = ""
    if useful_feedback:
        feedback_lines = [f"{i+1}. {c}" for i, c in enumerate(useful_feedback)]
        feedback_text = "\n" + "\n".join(feedback_lines)

    system_prompt = _build_latex_system_prompt(
        note_style=note_style,
        content_type=content_type,
        source_tracing=source_tracing,
        ocr_mode=ocr_mode,
        available_packages=available_packages,
        feedback_text=feedback_text,
        outline=outline
    )

    style_name = NOTE_STYLE_CONFIG.get(note_style, NOTE_STYLE_CONFIG["narrative"])["name"]
    print_status(f"正在调用 AI 整理文本（{style_name} / LaTeX）...", style="magenta", icon="🤖")
    try:
        resp = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": processed}
            ],
            temperature=0.3,
            max_tokens=8192,
        )
        latex_body = resp.choices[0].message.content
        latex_body = extract_latex_body(latex_body)
        latex_body = postprocess_latex(latex_body)
        print_status("AI 整理完成。", style="green")
        return latex_body
    except Exception as e:
        print_error(f"调用 DeepSeek API 失败：{e}")
        return ""


def generate_markdown_content(text: str, max_chars: int = DEFAULT_MAX_CHARS,
                               content_type: str = None, source_tracing: bool = False,
                               ocr_mode: str = "1", note_style: str = "narrative",
                               outline: str = None) -> str:
    if not DEEPSEEK_API_KEY:
        print_error("未找到 DEEPSEEK_API_KEY")
        return ""

    client = _ensure_client()
    if len(text) > max_chars:
        processed = text[:max_chars] + "\n\n[以下为部分内容，请基于此整理]"
        print_warning(f"文本过长，已截取前 {max_chars} 字符。")
    else:
        processed = text

    system_prompt = _build_markdown_system_prompt(
        note_style=note_style,
        content_type=content_type,
        source_tracing=source_tracing,
        ocr_mode=ocr_mode,
        outline=outline
    )

    style_name = NOTE_STYLE_CONFIG.get(note_style, NOTE_STYLE_CONFIG["narrative"])["name"]
    print_status(f"正在调用 AI 生成 Markdown（{style_name}）...", style="magenta", icon="📝")
    try:
        resp = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": processed}
            ],
            temperature=0.3,
            max_tokens=8192,
        )
        md_body = resp.choices[0].message.content
        md_body = extract_latex_body(md_body)
        print_status("Markdown 生成完成。", style="green")
        return md_body
    except Exception as e:
        print_error(f"调用 DeepSeek API 失败：{e}")
        return ""


# ---------- 语法修正 ----------
def self_correct_latex(latex_body: str) -> str:
    if not DEEPSEEK_API_KEY:
        return latex_body
    client = _ensure_client()
    system_prompt = (
        "你是一个 LaTeX 语法专家。请检查用户提供的 LaTeX 正文代码，找出所有语法错误，"
        "并输出修正后的完整代码。规则：\n"
        "1. 检查大括号、方括号是否正确配对。\n"
        "2. 检查 \\begin{...} 和 \\end{...} 是否一一对应。\n"
        "3. 检查 tabular 等环境的列数与数据是否一致，如不一致请修正列定义。\n"
        "4. 修正所有未转义的特殊字符（如 &、%、_、# 在普通文本中）。\n"
        "5. 保持原有的章节、格式、内容不变，只修正语法错误。\n"
        "6. 直接输出修正后的完整正文，不要加任何解释说明。"
    )

    def _call_correction(code: str) -> str:
        try:
            resp = client.chat.completions.create(
                model="deepseek-chat",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": code}
                ],
                temperature=0.0,
                max_tokens=8192,
            )
            return resp.choices[0].message.content
        except Exception as e:
            print_error(f"反思修正 API 调用失败：{e}")
            return code

    print_status("正在反思修正语法错误...", style="magenta", icon="🔧")
    corrected = _call_correction(latex_body)
    corrected = extract_latex_body(corrected)

    if corrected == latex_body or not brace_balanced(corrected):
        print_warning("第一次修正未完全解决问题，尝试第二次修正...")
        corrected2 = _call_correction(corrected)
        corrected2 = extract_latex_body(corrected2)
        if corrected2 == corrected or not brace_balanced(corrected2):
            print_warning("反思修正未能完全消除语法错误，将保留第一次修正结果。")
            return corrected
        else:
            corrected = corrected2

    print_status("反思修正完成。", style="green")
    return corrected


# ---------- 修订 ----------
# 结构级修订问题类型映射
STRUCTURAL_ISSUE_PROMPTS = {
    "too_fragmented": "当前笔记过于碎片化，像孤立知识点的罗列。请加强段落间的过渡和衔接，"
                      "展现概念之间的逻辑关系，使笔记读起来像一篇连贯的论述。",
    "lacking_connections": "当前笔记中各节内容之间缺少关联说明。请在各节末尾或专门的关联总结部分，"
                           "明确指出本节与前后内容的逻辑关系（递进、因果、对比等）。",
    "unbalanced": "当前笔记各节篇幅不均衡，某些部分过详或过略。请重新调整比例，"
                  "确保核心内容得到充分展开，次要内容适当压缩。",
    "too_verbose": "当前笔记过于冗长，包含过多非核心内容。请精简表述，聚焦于最重要的概念、"
                   "结论和推导，去除冗余描述。",
    "too_shallow": "当前笔记过于浅显，缺少深度分析。请在关键论点处补充解释性内容，"
                   "帮助读者理解'为什么'和'这意味着什么'。",
}


def revise_content(current_content: str, user_comment: str, format: str = "latex",
                    source_tracing: bool = False, note_style: str = "narrative",
                    structural_issue: str = None) -> str:
    if not DEEPSEEK_API_KEY:
        return current_content
    client = _ensure_client()
    format_desc = "LaTeX" if format == "latex" else "Markdown"
    style_name = NOTE_STYLE_CONFIG.get(note_style, NOTE_STYLE_CONFIG["narrative"])["name"]

    system_prompt = (
        f"你是一个{format_desc}笔记修订专家。请根据用户给出的修改意见，对提供的{format_desc}正文进行修改。"
        f"\n\n【风格约束】当前笔记风格为'{style_name}'，修订时请保持该风格的一致性："
    )

    if note_style == "narrative":
        system_prompt += "\n- 保持论证的连贯性和学术综述风格\n- 使用过渡句衔接段落\n- 保留因果链条和推导逻辑"
    elif note_style == "structured":
        system_prompt += "\n- 保持模块化和层次结构\n- 强调概念之间的关联\n- 每模块保持'核心概念→展开→关联'的结构"
    else:
        system_prompt += "\n- 保持简洁高效\n- 信息密度高\n- 去除冗余，保留核心"

    system_prompt += (
        "\n\n【通用要求】"
        "\n1. 只输出修改后的完整正文，保持原有的章节结构和格式，仅修改用户要求的部分。"
        "\n2. 不要添加任何解释。"
        "\n3. 确保输出为纯格式文本，且所有现有格式标记（包括原文追溯标记）不得被删除。"
    )

    # 如果是结构级修订，附加结构化指令
    if structural_issue and structural_issue in STRUCTURAL_ISSUE_PROMPTS:
        user_comment = f"【结构问题：{structural_issue}】{STRUCTURAL_ISSUE_PROMPTS[structural_issue]}\n\n用户具体意见：{user_comment}"

    print_status(f"正在修订笔记（{style_name} / {format_desc}）...", style="magenta", icon="✏️")
    try:
        resp = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"修改意见：{user_comment}\n\n原内容：\n{current_content}"}
            ],
            temperature=0.3,
            max_tokens=8192,
        )
        revised = resp.choices[0].message.content
        revised = extract_latex_body(revised)
        if format == "latex":
            revised = postprocess_latex(revised)
        print_status("修订完成。", style="green")
        return revised
    except Exception as e:
        print_error(f"修订失败：{e}")
        return current_content
