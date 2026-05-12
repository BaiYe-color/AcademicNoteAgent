#!/usr/bin/env python3
"""PDF/PPTX → LaTeX / Markdown 学术笔记 Agent（支持 DeepSeek-OCR 分级扫描）"""
import sys
import os
import argparse
import signal
from pathlib import Path

from dotenv import load_dotenv

from utils import (
    ensure_directories, get_next_article_dir, brace_balanced,
    TEMPLATE_DIR, SOURCE_DIR, create_draft_dir, clear_drafts,
    console, print_status, print_warning, print_error, print_panel
)
from text_extractor import extract_text, extract_text_from_pptx
from ui_prompts import get_user_config
from ai_client import (
    generate_title, generate_latex_content, generate_markdown_content,
    self_correct_latex, identify_subject, revise_content
)
from template_filler import fill_template
from config_manager import (
    load_config, save_config, update_subject_stats, add_feedback,
    save_session_state, load_session_state, clear_session_state
)

load_dotenv()
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")

MAX_REVISION_ROUNDS = 5

# ---------- 文件扫描 ----------
def list_source_files() -> list:
    if not SOURCE_DIR.exists():
        return []
    files = list(SOURCE_DIR.glob("*.pdf")) + list(SOURCE_DIR.glob("*.pptx"))
    files.sort(key=lambda f: f.stat().st_ctime, reverse=True)
    return files

def scan_source():
    files = list_source_files()
    return files[0] if files else None

def resolve_file_path(args):
    if args.file:
        return Path(args.file).expanduser().resolve()
    files = list_source_files()
    if not files:
        print_error("Source 文件夹中无待处理文件，请通过 --file 指定路径。")
        sys.exit(1)
    if len(files) == 1:
        target = files[0]
        console.print(f"检测到唯一文件 [bold cyan]{target.name}[/bold cyan]，是否处理？(回车确认，输入 no 则跳过)")
        choice = input().strip().lower()
        if choice == "no":
            console.print("已跳过。请使用 --file 手动指定文件路径。", style="yellow")
            sys.exit(0)
        return target
    else:
        console.print("[bold]Source/ 目录下有以下文件：[/bold]")
        for idx, f in enumerate(files, start=1):
            size_kb = f.stat().st_size / 1024
            ctime = f.stat().st_ctime
            from datetime import datetime
            time_str = datetime.fromtimestamp(ctime).strftime("%Y-%m-%d %H:%M")
            console.print(f"  {idx}. [cyan]{f.name}[/cyan]  ({size_kb:.1f} KB, 创建于 {time_str})")
        while True:
            choice = input("请输入序号选择文件 (输入 0 退出): ").strip()
            if choice == "0":
                print("已退出。")
                sys.exit(0)
            try:
                idx = int(choice)
                if 1 <= idx <= len(files):
                    return files[idx - 1]
                else:
                    console.print("[yellow]序号超出范围，请重新输入。[/yellow]")
            except ValueError:
                console.print("[yellow]请输入有效数字。[/yellow]")

# ---------- 主流程 ----------
def process_pdf(file_path, config, skip_reflect=False, skip_revise=False, resume_state=None):
    if resume_state:
        article_dir = Path(resume_state["article_dir"])
        draft_number = resume_state["draft_number"]
        main_tex_content = resume_state.get("main_tex_content", "")
        header_tex_content = resume_state.get("header_tex_content", "")
        content = resume_state["content_tex"]
        config = resume_state["config"]
        output_format = config.get("output_format", "latex")
        skip_reflect = resume_state["skip_reflect"]
        skip_revise = resume_state["skip_revise"]
        print_status(f"从断点恢复，当前位于 {article_dir}，draft_{draft_number:02d}", style="cyan")
    else:
        article_dir = get_next_article_dir()
        print_status(f"输出项目目录：{article_dir}", style="cyan")

        ext = file_path.suffix.lower()
        if ext == '.pdf':
            full_text = extract_text(str(file_path), ocr_mode=config.get("ocr_mode", "1"))
        elif ext == '.pptx':
            full_text = extract_text_from_pptx(str(file_path))
        else:
            print_error(f"不支持的文件类型 '{ext}'")
            sys.exit(1)

        output_format = config.get("output_format", "latex")
        source_tracing = config.get("source_tracing", False)
        ocr_mode = config.get("ocr_mode", "1")

        # 学科识别
        if config.get("subject_recognition") and DEEPSEEK_API_KEY:
            subject = identify_subject(full_text, DEEPSEEK_API_KEY)
            config_data = load_config()
            update_subject_stats(config_data, subject)
            save_config(config_data)

        title = config.get("cover_title", None)
        if config.get("cover") and title is None:
            title = generate_title(full_text, DEEPSEEK_API_KEY)
            print_panel("笔记标题", title)

        # 生成内容
        if output_format == "markdown":
            content = generate_markdown_content(
                full_text, DEEPSEEK_API_KEY,
                content_type=config.get("content_type"),
                source_tracing=source_tracing,
                ocr_mode=ocr_mode
            )
        else:
            content = generate_latex_content(
                full_text, DEEPSEEK_API_KEY,
                content_type=config.get("content_type"),
                source_tracing=source_tracing,
                ocr_mode=ocr_mode
            )
        if not content:
            print_error("未能生成内容，程序终止。")
            sys.exit(1)

        # LaTeX 自我修正
        if output_format == "latex" and not skip_reflect and DEEPSEEK_API_KEY:
            content = self_correct_latex(content, DEEPSEEK_API_KEY)
        elif output_format == "latex" and skip_reflect:
            print_status("已跳过反思修正步骤。")

        if output_format == "latex" and not brace_balanced(content):
            print_warning("初稿可能存在括号错误，请编译时检查。")

        # 准备模板（仅 LaTeX）
        main_tex_content = ""
        header_tex_content = ""
        if output_format == "latex":
            main_replacements = {
                "<<FONT_SIZE>>": str(config["font_size"]),
                "<<CJK_MAIN_FONT>>": config["cjk_serif"],
                "<<CJK_SANS_FONT>>": config["cjk_sans"],
                "<<CJK_MONO_FONT>>": config["cjk_mono"],
                "<<EN_MAIN_FONT>>": config["en_serif"],
                "<<EN_SANS_FONT>>": config["en_sans"],
                "<<EN_MONO_FONT>>": config["en_mono"],
                "<<DOC_TITLE>>": title if config.get("cover") else "",
                "<<DOC_AUTHOR>>": config.get("cover_author", ""),
                "<<DOC_DATE>>": config.get("cover_date", ""),
            }
            if config.get("cover"):
                main_replacements["<<COVER_COMMAND>>"] = "\\maketitle\n\\thispagestyle{fancy}"
            else:
                main_replacements["<<COVER_COMMAND>>"] = "\\thispagestyle{fancy}"

            if config.get("header_enabled"):
                hl = config.get("header_left", "")
                hc = config.get("header_center", "")
                hr = config.get("header_right", "")
                headrule = "0.4pt"
            else:
                hl = hc = hr = ""
                headrule = "0pt"
            header_replacements = {
                "<<HEADER_LEFT>>": hl,
                "<<HEADER_CENTER>>": hc,
                "<<HEADER_RIGHT>>": hr,
                "<<FOOTER_LEFT>>": "",
                "<<FOOTER_RIGHT>>": "",
                "<<HEADRULE_WIDTH>>": headrule,
            }

            main_tex_tpl = (TEMPLATE_DIR / "0_main.tex").read_text(encoding="utf-8")
            for ph, val in main_replacements.items():
                main_tex_tpl = main_tex_tpl.replace(ph, str(val))
            main_tex_content = main_tex_tpl

            header_tex_tpl = (TEMPLATE_DIR / "headerfooter.tex").read_text(encoding="utf-8")
            for ph, val in header_replacements.items():
                header_tex_tpl = header_tex_tpl.replace(ph, str(val))
            header_tex_content = header_tex_tpl

        # 保存初稿
        draft_number = 1
        draft_dir = create_draft_dir(article_dir, draft_number)
        if output_format == "latex":
            (draft_dir / "main.tex").write_text(main_tex_content, encoding="utf-8")
            (draft_dir / "headerfooter.tex").write_text(header_tex_content, encoding="utf-8")
            (draft_dir / "content.tex").write_text(content, encoding="utf-8")
        else:
            (draft_dir / "content.md").write_text(content, encoding="utf-8")
        print_status(f"笔记初稿已保存到 draft_{draft_number:02d}。")

        # 保存会话状态（支持断点续传）
        initial_state = {
            "article_dir": str(article_dir),
            "draft_number": draft_number,
            "main_tex_content": main_tex_content,
            "header_tex_content": header_tex_content,
            "content_tex": content,
            "config": config,
            "skip_reflect": skip_reflect,
            "skip_revise": skip_revise,
            "file_path": str(file_path)
        }
        save_session_state(initial_state)

    # ---- 修订循环 ----
    if skip_revise and not resume_state:
        print_status("已跳过交互修订。")
        final_content = content
    else:
        current_content = content
        while draft_number <= MAX_REVISION_ROUNDS:
            console.print("\n是否需要继续修改？输入 [bold]1[/bold] 进入修改，输入 [bold]0[/bold] 结束并生成最终稿。")
            choice = input().strip()
            if choice == "0":
                break
            elif choice == "1":
                user_comment = input("请输入修改意见：\n").strip()
                if not user_comment:
                    console.print("修改意见为空，跳过修订。", style="yellow")
                    continue
                new_content = revise_content(
                    current_content, user_comment, DEEPSEEK_API_KEY,
                    format=output_format,
                    source_tracing=config.get("source_tracing", False)
                )
                if output_format == "latex" and not brace_balanced(new_content):
                    print_warning("修订后可能存在括号错误，请编译时检查。")
                current_content = new_content
                draft_number += 1
                draft_dir = create_draft_dir(article_dir, draft_number)
                if output_format == "latex":
                    (draft_dir / "main.tex").write_text(main_tex_content, encoding="utf-8")
                    (draft_dir / "headerfooter.tex").write_text(header_tex_content, encoding="utf-8")
                    (draft_dir / "content.tex").write_text(current_content, encoding="utf-8")
                else:
                    (draft_dir / "content.md").write_text(current_content, encoding="utf-8")
                print_status(f"修订版本已保存到 draft_{draft_number:02d}。")
                state = {
                    "article_dir": str(article_dir),
                    "draft_number": draft_number,
                    "main_tex_content": main_tex_content,
                    "header_tex_content": header_tex_content,
                    "content_tex": current_content,
                    "config": config,
                    "skip_reflect": skip_reflect,
                    "skip_revise": skip_revise,
                    "file_path": str(file_path) if not resume_state else resume_state.get("file_path", "")
                }
                save_session_state(state)
            else:
                console.print("无效输入，请输入 1 或 0。", style="yellow")
        final_content = current_content

    # 生成最终稿
    if output_format == "latex":
        (article_dir / "main.tex").write_text(main_tex_content, encoding="utf-8")
        (article_dir / "headerfooter.tex").write_text(header_tex_content, encoding="utf-8")
        (article_dir / "content.tex").write_text(final_content, encoding="utf-8")
    else:
        (article_dir / "content.md").write_text(final_content, encoding="utf-8")
    clear_drafts(article_dir)
    clear_session_state()

    console.print("\n[green]✅ 最终笔记已生成到 Article_X/ 目录。[/green]")
    if output_format == "latex":
        for f in ["main.tex", "headerfooter.tex", "content.tex"]:
            console.print(f"   [cyan]{article_dir / f}[/cyan]")
    else:
        console.print(f"   [cyan]{article_dir / 'content.md'}[/cyan]")

    # 满意度反馈
    console.print("\n您对本次笔记满意吗？请打分（1-5）并附修改意见（直接回车跳过）")
    try:
        score_str = input("打分：").strip()
        if score_str:
            score = int(score_str)
            if 1 <= score <= 5:
                comment = input("修改意见：").strip()
                config_data = load_config()
                add_feedback(config_data, score, comment)
                save_config(config_data)
                console.print("[green]感谢您的反馈！[/green]")
            else:
                console.print("[yellow]分数超出范围，跳过反馈。[/yellow]")
    except:
        pass

# ---------- 信号处理 ----------
def signal_handler(sig, frame):
    console.print("\n[yellow]用户中断，进度已保存，下次运行可从断点继续。[/yellow]")
    sys.exit(1)

# ---------- 入口 ----------
def main():
    parser = argparse.ArgumentParser(description="PDF/PPTX → LaTeX / Markdown 学术笔记 Agent")
    parser.add_argument("--file", required=False)
    parser.add_argument("--no-reflect", action="store_true")
    parser.add_argument("--no-revise", action="store_true")
    parser.add_argument("--reset-config", action="store_true")
    parser.add_argument("--format", choices=["latex", "md"], help="输出格式：latex 或 md")
    parser.add_argument("--trace", action="store_true", help="启用原文页码追溯")
    args = parser.parse_args()

    if args.reset_config:
        from config_manager import CONFIG_PATH
        if CONFIG_PATH.exists():
            CONFIG_PATH.unlink()
        load_config()
        console.print("[green]配置文件已重置。[/green]")
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    ensure_directories()

    # 检查中断会话
    state = load_session_state()
    if state and not args.no_revise:
        console.print("[cyan]检测到上次未完成的笔记任务。[/cyan]")
        console.print(f"原文件路径：{state.get('file_path', '未知')}")
        console.print("是否从上次中断处继续？(回车确认，输入 no 则重新开始)")
        choice = input().strip().lower()
        if choice == "no":
            clear_session_state()
            state = None
        else:
            try:
                process_pdf(None, None, resume_state=state)
            except Exception as e:
                print_error(f"恢复处理发生错误：{e}")
                sys.exit(1)
            return

    # 准备命令行覆盖
    overrides = {}
    if args.format:
        overrides["output_format"] = args.format
    if args.trace:
        overrides["source_tracing"] = True

    file_path = resolve_file_path(args)
    try:
        config = get_user_config(overrides if overrides else None)
        process_pdf(file_path, config, skip_reflect=args.no_reflect, skip_revise=args.no_revise)
    except Exception as e:
        print_error(f"处理过程发生错误：{e}")
        sys.exit(1)

if __name__ == "__main__":
    main()