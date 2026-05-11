#!/usr/bin/env python3
"""DeepSeek AI 调用：标题、正文生成、反思修正、学科识别、修订"""
import sys
import openai
from utils import DEFAULT_MAX_CHARS, brace_balanced, postprocess_latex, console, create_progress, print_status, print_warning, print_error
from config_manager import load_config, get_recent_feedback

def identify_subject(text: str, api_key: str) -> str:
    if not api_key:
        return "未知"
    client = openai.OpenAI(api_key=api_key, base_url="https://api.deepseek.com")
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

def generate_title(text: str, api_key: str) -> str:
    if not api_key:
        return "未命名笔记"
    client = openai.OpenAI(api_key=api_key, base_url="https://api.deepseek.com")
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

def generate_latex_content(text: str, api_key: str, max_chars: int = DEFAULT_MAX_CHARS, content_type: str = None) -> str:
    if not api_key:
        print_error("未找到 DEEPSEEK_API_KEY，请检查 .env 文件")
        return ""

    client = openai.OpenAI(api_key=api_key, base_url="https://api.deepseek.com")
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
        feedback_text = "\n用户历史反馈：\n" + "\n".join(feedback_lines)

    base_system = (
        "你是一位严谨的学术笔记整理专家。你的任务不是转录，而是将原始材料转化为一份"
        "结构清晰、逻辑连贯、有自身语言风格的课程笔记。"
        "\n请遵循以下要求："
        "\n1. **开头必须包含一个引言段落**（使用 \\section*{引言} 或 \\subsection*{引言}），"
        "在其中用自然语言概括本笔记涵盖的主要知识点、学习目标或核心问题，让读者知道将要学到什么。"
        "\n2. **正文整理**："
        "\n   - 用你自己的话重新组织和解释概念，不要直接复制原文长句，但要确保信息准确。"
        "\n   - 使用 \\section、\\subsection 构建层级，用 \\textbf{概念}、\\textit{强调}、itemize/enumerate 列举。"
        "\n   - 适当使用 \\begin{quote} 引用原文关键句或法条，用 \\begin{table} 呈现对比数据，"
        "用 \\begin{description} 定义术语。"
        "\n   - 添加过渡句和逻辑连接词，使笔记读起来像一篇完整的文章，而非要点拼接。"
        "\n3. **结尾必须包含一个总结段落**（使用 \\section*{总结} 或 \\subsection*{总结}），"
        "在其中梳理各知识点的层次关系（例如：核心概念→分支→应用），提炼最重要的几个要点，"
        "并可以指出它们之间的内在联系。总结应体现学术性，避免口语化。"
        "\n4. 所有 LaTeX 环境必须正确配对，表格列数与数据一致，特殊字符转义。"
        "\n5. 只输出正文内容（不含 documentclass、usepackage、begin{document} 等），直接以 \\section 开头。"
    )

    if content_type:
        type_map = {
            "1": "本次材料偏向理论阐述，请在引言中明确列出关键概念和定义，在总结中构建概念图。",
            "2": "本次材料包含案例，请在正文中设置“案例背景”“法律分析”“结论”等子节，引言点明案例问题，总结归纳法理原则。",
            "3": "本次材料是实验性内容，请按“实验目的”“方法”“结果”“讨论”组织笔记，引言说明实验目标，总结得出结论与局限性。",
            "4": "本次材料以数据为主，请大量使用表格呈现，引言列出数据来源与变量，总结归纳数据规律。"
        }
        base_system += "\n" + type_map.get(content_type, "")

    if feedback_text:
        base_system += "\n" + feedback_text

    print_status("正在调用 AI 整理文本...", style="magenta", icon="🤖")
    try:
        resp = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": base_system},
                {"role": "user", "content": processed}
            ],
            temperature=0.3,
        )
        latex_body = resp.choices[0].message.content
        latex_body = postprocess_latex(latex_body)
        print_status("AI 整理完成。", style="green")
        return latex_body
    except Exception as e:
        print_error(f"调用 DeepSeek API 失败：{e}")
        return ""

def self_correct_latex(latex_body: str, api_key: str) -> str:
    if not api_key:
        return latex_body

    client = openai.OpenAI(api_key=api_key, base_url="https://api.deepseek.com")
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
            )
            return resp.choices[0].message.content
        except Exception as e:
            print_error(f"反思修正 API 调用失败：{e}")
            return code

    print_status("正在反思修正语法错误...", style="magenta", icon="🔧")
    corrected = _call_correction(latex_body)

    if corrected == latex_body or not brace_balanced(corrected):
        print_warning("第一次修正未完全解决问题，尝试第二次修正...")
        corrected2 = _call_correction(corrected)
        if corrected2 == corrected or not brace_balanced(corrected2):
            print_warning("反思修正未能完全消除语法错误，将保留第一次修正结果。")
            return corrected
        else:
            corrected = corrected2

    print_status("反思修正完成。", style="green")
    return corrected

def revise_content(current_latex: str, user_comment: str, api_key: str) -> str:
    if not api_key:
        return current_latex
    client = openai.OpenAI(api_key=api_key, base_url="https://api.deepseek.com")
    system_prompt = (
        "你是一个 LaTeX 笔记修订专家。请根据用户给出的修改意见，对提供的 LaTeX 正文进行修改。"
        "要求：只输出修改后的完整正文，保持原有的章节结构和格式，仅修改用户要求的部分。"
        "不要添加任何解释。确保 LaTeX 语法正确、特殊字符转义、环境配对。"
    )
    print_status("正在修订笔记...", style="magenta", icon="✏️")
    try:
        resp = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"修改意见：{user_comment}\n\n原内容：\n{current_latex}"}
            ],
            temperature=0.3,
        )
        revised = resp.choices[0].message.content
        revised = postprocess_latex(revised)
        print_status("修订完成。", style="green")
        return revised
    except Exception as e:
        print_error(f"修订失败：{e}")
        return current_latex