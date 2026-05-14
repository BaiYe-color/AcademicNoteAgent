#!/usr/bin/env python3
"""PDF/PPTX → LaTeX / Markdown 学术笔记 Agent"""
import sys
import os
import argparse
import signal
from pathlib import Path

from dotenv import load_dotenv

from utils import (
    ensure_directories, get_next_article_dir, brace_balanced,
    TEMPLATE_DIR, SOURCE_DIR, clear_drafts,
    console, print_status, print_warning, print_error, print_panel
)
from text_extractor import extract_text, extract_text_from_pptx
from ui_prompts import get_user_config
from ai_client import (
    generate_title, generate_latex_content, generate_markdown_content,
    self_correct_latex, identify_subject, revise_content,
    generate_outline, NOTE_STYLE_CONFIG, strip_fence_wrappers,
    DEEPSEEK_API_KEY
)
from template_filler import fill_latex_templates, save_note_output, save_draft, extract_packages_from_tex
from config_manager import (
    load_config, save_config, update_subject_stats, add_feedback,
    save_session_state, load_session_state, clear_session_state
)

load_dotenv()

MAX_REVISION_ROUNDS = 5
OUTLINE_LENGTH_THRESHOLD = 6000  # 文本超过此长度时启用大纲先行

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

def _print_file_list(files):
    """打印 Source/ 目录下的文件列表"""
    console.print("[bold]Source/ 目录下有以下文件：[/bold]")
    for idx, f in enumerate(files, start=1):
        size_kb = f.stat().st_size / 1024
        ctime = f.stat().st_ctime
        from datetime import datetime
        time_str = datetime.fromtimestamp(ctime).strftime("%Y-%m-%d %H:%M")
        console.print(f"  {idx}. [cyan]{f.name}[/cyan]  ({size_kb:.1f} KB, 创建于 {time_str})")


def select_files_interactive(files):
    """
    交互式选择文件和处理模式。
    返回: (selected_files: list[Path], is_batch: bool)
    """
    if not files:
        print_error("Source 文件夹中无待处理文件，请通过 --file 指定路径。")
        sys.exit(1)

    # 只有一个文件时的快捷处理
    if len(files) == 1:
        target = files[0]
        console.print(f"检测到唯一文件 [bold cyan]{target.name}[/bold cyan]")
        console.print("请选择模式：回车=单文件处理，输入 b=批量处理，输入 no=跳过")
        choice = input().strip().lower()
        if choice == "no":
            console.print("已跳过。请使用 --file 手动指定文件路径。", style="yellow")
            sys.exit(0)
        elif choice == "b":
            return [target], True
        else:
            return [target], False

    # 多个文件：先展示列表，再问模式
    _print_file_list(files)

    console.print("\n请选择处理模式：")
    console.print("  [1] 单文件处理（支持多轮修订、满意度打分）")
    console.print("  [2] 批量处理（统一配置，分别输出，跳过修订与打分）")
    console.print("  [0] 退出")

    while True:
        mode = input("请输入选项 (0/1/2): ").strip()
        if mode == "0":
            print("已退出。")
            sys.exit(0)
        elif mode == "1":
            while True:
                choice = input("请输入序号选择文件: ").strip()
                try:
                    idx = int(choice)
                    if 1 <= idx <= len(files):
                        return [files[idx - 1]], False
                    else:
                        console.print("[yellow]序号超出范围，请重新输入。[/yellow]")
                except ValueError:
                    console.print("[yellow]请输入有效数字。[/yellow]")
        elif mode == "2":
            console.print("\n请输入需要批量处理的文件序号，用空格或逗号分隔（如：1 3 5）：")
            while True:
                choice = input().strip()
                indices = []
                valid = True
                for part in choice.replace(',', ' ').split():
                    try:
                        idx = int(part)
                        if 1 <= idx <= len(files):
                            indices.append(idx - 1)
                        else:
                            console.print(f"[yellow]序号 {idx} 超出范围，请重新输入。[/yellow]")
                            valid = False
                            break
                    except ValueError:
                        console.print(f"[yellow]'{part}' 不是有效数字，请重新输入。[/yellow]")
                        valid = False
                        break

                if valid and indices:
                    selected = [files[i] for i in sorted(set(indices))]
                    console.print(f"[green]已选择 {len(selected)} 个文件：{', '.join(f.name for f in selected)}[/green]")
                    return selected, True
                elif valid:
                    console.print("[yellow]未选择任何文件，请重新输入。[/yellow]")
        else:
            console.print("[yellow]无效输入，请输入 0、1 或 2。[/yellow]")

# ---------- 主流程 ----------
def process_pdf(file_path, config, skip_reflect=False, skip_revise=False, resume_state=None, batch_mode=False, template_choice=None):
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
        outline = resume_state.get("outline", None)
        note_style = config.get("note_style", "narrative")
        print_status(f"从断点恢复，当前位于 {article_dir}，draft_{draft_number:02d}", style="cyan")
    else:
        article_dir = get_next_article_dir()
        print_status(f"输出项目目录：{article_dir}", style="cyan")

        ext = file_path.suffix.lower()
        if ext == '.pdf':
            full_text = extract_text(str(file_path), ocr_mode=config.get("ocr_mode", "1"))
        elif ext == '.pptx':
            full_text = extract_text_from_pptx(str(file_path), ocr_mode=config.get("ocr_mode", "1"))
        else:
            raise RuntimeError(f"不支持的文件类型 '{ext}'")

        output_format = config.get("output_format", "latex")
        source_tracing = config.get("source_tracing", False)
        ocr_mode = config.get("ocr_mode", "1")

        # 学科识别
        if config.get("subject_recognition") and DEEPSEEK_API_KEY:
            subject = identify_subject(full_text)
            config_data = load_config()
            update_subject_stats(config_data, subject)
            save_config(config_data)

        title = config.get("cover_title", None)
        if config.get("cover") and title is None:
            title = generate_title(full_text)
            print_panel("笔记标题", title)

        # ---------- 大纲先行（长文档） ----------
        outline = None
        note_style = config.get("note_style", "narrative")
        if len(full_text) > OUTLINE_LENGTH_THRESHOLD and not batch_mode:
            outline = generate_outline(
                full_text,
                note_style=note_style,
                title=title or "未命名笔记",
                content_type=config.get("content_type")
            )
            if outline:
                from rich.markdown import Markdown
                from rich.panel import Panel
                md = Markdown(outline)
                console.print()
                console.print(Panel(md, title="内容大纲", border_style="cyan", padding=(1, 2)))
                console.print("[bold]请确认大纲：[/bold]")
                console.print("  回车 = 确认并继续生成")
                console.print("  输入修改意见 = AI 根据意见调整大纲")
                console.print("  输入 skip = 不使用大纲，直接生成")
                outline_round = 0
                while outline_round < 2:
                    user_input = input().strip()
                    if user_input.lower() == "skip":
                        outline = None
                        print_status("已跳过大纲，直接生成全文。", style="yellow")
                        break
                    elif user_input == "":
                        print_status("大纲已确认，开始生成全文。", style="green")
                        break
                    else:
                        outline_round += 1
                        print_status(f"正在根据意见调整大纲（第 {outline_round} 轮）...", style="magenta")
                        from ai_client import _ensure_client
                        client = _ensure_client()
                        try:
                            resp = client.chat.completions.create(
                                model="deepseek-chat",
                                messages=[
                                    {"role": "system", "content": "你是一位学术内容分析师。请根据用户的修改意见，调整以下内容大纲。只输出修改后的大纲，使用 # 和 ## 层级标题。不要添加任何解释。"},
                                    {"role": "user", "content": f"修改意见：{user_input}\n\n当前大纲：\n{outline}"}
                                ],
                                temperature=0.3,
                                max_tokens=4096,
                            )
                            outline = resp.choices[0].message.content.strip()
                            outline = strip_fence_wrappers(outline)
                            md = Markdown(outline)
                            console.print()
                            console.print(Panel(md, title="调整后的内容大纲", border_style="cyan", padding=(1, 2)))
                            console.print("[bold]请确认大纲：[/bold] 回车=确认，输入修改意见=继续调整，skip=不使用大纲")
                        except Exception as e:
                            print_error(f"大纲调整失败：{e}")
                            break
                if outline_round >= 2 and user_input not in ["", "skip"]:
                    print_warning("大纲调整轮次已达上限，使用当前版本。")
        elif len(full_text) > OUTLINE_LENGTH_THRESHOLD and batch_mode:
            # 批量模式下自动生成大纲但不交互确认
            outline = generate_outline(
                full_text,
                note_style=note_style,
                title=title or "未命名笔记",
                content_type=config.get("content_type")
            )
            if outline:
                print_status("已自动生成内容大纲（批量模式跳过确认）。", style="cyan")

        # 提取模板中已加载的宏包（仅 LaTeX）
        available_packages = []
        if output_format == "latex":
            main_tpl_path = template_choice["main_tpl_path"] if template_choice else TEMPLATE_DIR / "0_main.tex"
            try:
                tpl_content = main_tpl_path.read_text(encoding="utf-8")
                available_packages = extract_packages_from_tex(tpl_content)
                if available_packages:
                    print_status(f"模板已加载宏包：{', '.join(available_packages)}", style="cyan")
            except Exception:
                pass

        # 生成内容
        custom_addons = config.get("custom_addons", [])
        if output_format == "markdown":
            result = generate_markdown_content(
                full_text,
                content_type=config.get("content_type"),
                source_tracing=source_tracing,
                ocr_mode=ocr_mode,
                note_style=note_style,
                outline=outline,
                custom_addons=custom_addons
            )
            content, concept_map = result
        else:
            result = generate_latex_content(
                full_text,
                content_type=config.get("content_type"),
                source_tracing=source_tracing,
                ocr_mode=ocr_mode,
                available_packages=available_packages,
                note_style=note_style,
                outline=outline,
                custom_addons=custom_addons
            )
            content, concept_map = result
        if not content:
            raise RuntimeError("未能生成内容")

        # LaTeX 自我修正
        if output_format == "latex" and not skip_reflect and DEEPSEEK_API_KEY:
            content = self_correct_latex(content)
        elif output_format == "latex" and skip_reflect:
            print_status("已跳过反思修正步骤。")

        if output_format == "latex" and not brace_balanced(content):
            print_warning("初稿可能存在括号错误，请编译时检查。")

        # 准备模板（仅 LaTeX）
        main_tex_content = ""
        header_tex_content = ""
        if output_format == "latex":
            main_tex_content, header_tex_content = fill_latex_templates(TEMPLATE_DIR, config, title, template_choice)

        # 保存初稿
        draft_number = 1
        save_draft(article_dir, draft_number, content, output_format, main_tex_content, header_tex_content)
        print_status(f"笔记初稿已保存到 draft_{draft_number:02d}。")

        # 保存会话状态（支持断点续传，批量模式下不保存）
        if not batch_mode:
            initial_state = {
                "article_dir": str(article_dir),
                "draft_number": draft_number,
                "main_tex_content": main_tex_content,
                "header_tex_content": header_tex_content,
                "content_tex": content,
                "config": config,
                "skip_reflect": skip_reflect,
                "skip_revise": skip_revise,
                "file_path": str(file_path),
                "outline": outline
            }
            save_session_state(initial_state)

    # ---- 修订循环 ----
    if batch_mode:
        print_status("批量模式：跳过多轮修订与打分。", style="cyan")
        final_content = content
    elif skip_revise:
        print_status("已跳过交互修订。")
        final_content = content
    else:
        current_content = content
        while draft_number <= MAX_REVISION_ROUNDS:
            console.print(f"\n[bold]--- 第 {draft_number} 轮修订 ---[/bold]")
            console.print("请选择操作：")
            console.print("  [1] 提出具体修改意见")
            console.print("  [2] 结构级调整（整体结构问题）")
            console.print("  [0] 确认完成，生成终稿")
            choice = input().strip()
            if choice == "0":
                break
            elif choice == "1":
                user_comment = input("请输入具体修改意见：\n").strip()
                if not user_comment:
                    console.print("修改意见为空，跳过修订。", style="yellow")
                    continue
                new_content = revise_content(
                    current_content, user_comment,
                    format=output_format,
                    source_tracing=config.get("source_tracing", False),
                    note_style=note_style,
                    custom_addons=config.get("custom_addons", [])
                )
                if output_format == "latex" and not brace_balanced(new_content):
                    print_warning("修订后可能存在括号错误，请编译时检查。")
                current_content = new_content
                draft_number += 1
                save_draft(article_dir, draft_number, current_content, output_format, main_tex_content, header_tex_content)
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
                    "file_path": str(file_path) if not resume_state else resume_state.get("file_path", ""),
                    "outline": outline
                }
                save_session_state(state)
            elif choice == "2":
                # 结构级调整
                console.print("\n[bold]请选择结构问题类型：[/bold]")
                console.print("  [1] 太碎片化了，需要加强连贯性")
                console.print("  [2] 缺少概念之间的关联说明")
                console.print("  [3] 各节篇幅不均衡")
                console.print("  [4] 太冗长了，需要精简")
                console.print("  [5] 太浅显了，需要加深分析")
                console.print("  [0] 返回上级")
                struct_choice = input().strip()
                structural_issue_map = {
                    "1": "too_fragmented",
                    "2": "lacking_connections",
                    "3": "unbalanced",
                    "4": "too_verbose",
                    "5": "too_shallow",
                }
                if struct_choice == "0":
                    continue
                if struct_choice not in structural_issue_map:
                    console.print("无效输入，返回上级。", style="yellow")
                    continue
                structural_issue = structural_issue_map[struct_choice]
                user_comment = input("请补充具体的修改意见（可选，直接回车则使用默认调整）：\n").strip()
                if not user_comment:
                    user_comment = "请根据上述结构问题类型进行针对性调整。"
                new_content = revise_content(
                    current_content, user_comment,
                    format=output_format,
                    source_tracing=config.get("source_tracing", False),
                    note_style=note_style,
                    structural_issue=structural_issue,
                    custom_addons=config.get("custom_addons", [])
                )
                if output_format == "latex" and not brace_balanced(new_content):
                    print_warning("修订后可能存在括号错误，请编译时检查。")
                current_content = new_content
                draft_number += 1
                save_draft(article_dir, draft_number, current_content, output_format, main_tex_content, header_tex_content)
                print_status(f"结构修订版本已保存到 draft_{draft_number:02d}。")
                state = {
                    "article_dir": str(article_dir),
                    "draft_number": draft_number,
                    "main_tex_content": main_tex_content,
                    "header_tex_content": header_tex_content,
                    "content_tex": current_content,
                    "config": config,
                    "skip_reflect": skip_reflect,
                    "skip_revise": skip_revise,
                    "file_path": str(file_path) if not resume_state else resume_state.get("file_path", ""),
                    "outline": outline
                }
                save_session_state(state)
            else:
                console.print("无效输入，请输入 1、2 或 0。", style="yellow")
        final_content = current_content

    # 生成最终稿
    save_note_output(article_dir, final_content, output_format, main_tex_content, header_tex_content)

    # 保存概念图谱（如生成）
    if concept_map:
        mmd_path = article_dir / "concept_map.mmd"
        with open(mmd_path, "w", encoding="utf-8") as f:
            f.write(concept_map)

    clear_drafts(article_dir)
    clear_session_state()

    console.print("\n[green]✅ 最终笔记已生成到 Article_X/ 目录。[/green]")
    if output_format == "latex":
        for f in ["main.tex", "headerfooter.tex", "content.tex"]:
            console.print(f"   [cyan]{article_dir / f}[/cyan]")
    else:
        console.print(f"   [cyan]{article_dir / 'content.md'}[/cyan]")
    if concept_map:
        console.print(f"   [cyan]{article_dir / 'concept_map.mmd'}[/cyan]")

    # 满意度反馈（批量模式下跳过）
    if not batch_mode:
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

# ---------- 欢迎面板 ----------
def print_welcome():
    """打印启动欢迎面板"""
    from rich.panel import Panel
    from rich.text import Text

    welcome_text = Text()
    welcome_text.append("AcademicNoteAgent\n", style="bold cyan")
    welcome_text.append("学术笔记智能整理工具\n\n", style="dim")
    welcome_text.append("核心功能\n", style="bold")
    welcome_text.append("  - 三种笔记风格（论述型 / 结构化型 / 极简型）\n")
    welcome_text.append("  - 长文档大纲先行 + 分段生成\n")
    welcome_text.append("  - 结构级修订 + 断点续传\n")
    welcome_text.append("  - 视觉描述 OCR + 批量处理\n")
    welcome_text.append("\n")
    welcome_text.append("提示：直接回车使用默认配置，输入 y 确认选项", style="dim italic")

    panel = Panel(
        welcome_text,
        title="v2.3.0",
        title_align="right",
        border_style="cyan",
        padding=(1, 2),
    )
    console.print("\n")
    console.print(panel)
    console.print()


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
    parser.add_argument("--batch", action="store_true", help="启用批量处理模式")
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

    # 扫描文件（提前到此处，避免重复扫描）
    files = list_source_files()
    if not files:
        print_error("Source 文件夹中无待处理文件，请通过 --file 指定路径。")
        sys.exit(1)

    # 非自动化模式下显示欢迎面板
    if not args.file and not args.batch:
        print_welcome()

    # 检查中断会话（仅单文件模式）
    if not args.batch:
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

    # 确定处理模式和文件列表
    if args.file and args.batch:
        print_warning("同时指定了 --file 和 --batch，忽略 --batch，按单文件处理。")
        file_paths = [Path(args.file).expanduser().resolve()]
        is_batch = False
    elif args.file:
        file_paths = [Path(args.file).expanduser().resolve()]
        is_batch = False
    elif args.batch:
        file_paths, is_batch = select_files_interactive(files)
        if not file_paths:
            sys.exit(0)
    else:
        file_paths, is_batch = select_files_interactive(files)
        if not file_paths:
            sys.exit(0)

    # 统一配置（批量模式下只配置一次）
    try:
        config, template_choice = get_user_config(overrides if overrides else None, template_dir=TEMPLATE_DIR)
    except Exception as e:
        print_error(f"配置过程发生错误：{e}")
        sys.exit(1)

    if is_batch:
        # 批量处理
        console.print(f"\n[bold cyan]批量处理开始，共 {len(file_paths)} 个文件[/bold cyan]")
        success_count = 0
        for i, fp in enumerate(file_paths, start=1):
            console.print(f"\n[bold]--- 文件 {i}/{len(file_paths)}: {fp.name} ---[/bold]")
            try:
                process_pdf(fp, config, skip_reflect=args.no_reflect, skip_revise=True, batch_mode=True, template_choice=template_choice)
                success_count += 1
            except Exception as e:
                print_error(f"处理 {fp.name} 时发生错误：{e}")
                console.print("[yellow]继续处理下一个文件...[/yellow]")
        console.print(f"\n[green]✅ 批量处理完成，成功 {success_count}/{len(file_paths)} 个文件。[/green]")
    else:
        # 单文件处理
        try:
            process_pdf(file_paths[0], config, skip_reflect=args.no_reflect, skip_revise=args.no_revise, template_choice=template_choice)
        except Exception as e:
            print_error(f"处理过程发生错误：{e}")
            sys.exit(1)

if __name__ == "__main__":
    main()