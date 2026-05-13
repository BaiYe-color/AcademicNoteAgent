#!/usr/bin/env python3
"""模板填充与输出管理工具"""
from pathlib import Path
from typing import Tuple

from utils import console, print_status, print_warning


def fill_template(template_path: str | Path, replacements: dict) -> str:
    """读取模板并执行占位符替换，返回填充后的文本（不写入文件）。"""
    tpl = Path(template_path).expanduser().resolve()
    if not tpl.is_file():
        raise FileNotFoundError(f"模板文件不存在：{tpl}")

    content = tpl.read_text(encoding="utf-8")
    for ph, val in replacements.items():
        content = content.replace(ph, str(val))
    return content


def scan_custom_templates(template_dir: Path) -> Tuple[list[str], list[str]]:
    """
    扫描 /Template/custom/ 目录下的用户自定义模板。
    命名规则：0_main_<名称>.tex 和 headerfooter_<名称>.tex
    返回: (main_templates, header_templates)
    """
    custom_dir = template_dir / "custom"
    if not custom_dir.exists():
        return [], []

    main_tpls = []
    header_tpls = []
    for f in custom_dir.iterdir():
        if f.is_file() and f.suffix == ".tex":
            if f.name.startswith("0_main_"):
                main_tpls.append(f.name)
            elif f.name.startswith("headerfooter_"):
                header_tpls.append(f.name)

    return sorted(main_tpls), sorted(header_tpls)


def select_templates_interactive(template_dir: Path) -> dict:
    """
    交互式选择 LaTeX 模板。
    返回 template_choice 字典：
    {
        "main_tpl_path": Path,
        "header_tpl_path": Path,
        "main_is_custom": bool,
        "header_is_custom": bool,
    }
    """
    main_custom, header_custom = scan_custom_templates(template_dir)

    result = {
        "main_tpl_path": template_dir / "0_main.tex",
        "header_tpl_path": template_dir / "headerfooter.tex",
        "main_is_custom": False,
        "header_is_custom": False,
    }

    # --- 0_main 模板选择 ---
    if main_custom:
        console.print("\n[bold]检测到以下自定义 0_main 模板：[/bold]")
        console.print("  [0] 系统默认模板")
        for i, name in enumerate(main_custom, 1):
            display = name.replace("0_main_", "").replace(".tex", "")
            console.print(f"  [{i}] {display}")

        while True:
            choice = input("请选择 0_main 模板（输入序号）：").strip()
            try:
                idx = int(choice)
                if idx == 0:
                    result["main_is_custom"] = False
                    print_status("使用系统默认 0_main 模板", style="cyan")
                    break
                elif 1 <= idx <= len(main_custom):
                    result["main_tpl_path"] = template_dir / "custom" / main_custom[idx - 1]
                    result["main_is_custom"] = True
                    print_status(f"使用自定义 0_main 模板：{main_custom[idx - 1]}", style="green")
                    break
                else:
                    print_warning("序号超出范围，请重新输入。")
            except ValueError:
                print_warning("请输入有效数字。")
    else:
        console.print("[dim]未检测到自定义 0_main 模板，使用系统默认。[/dim]")

    # --- headerfooter 模板选择 ---
    if header_custom:
        console.print("\n[bold]检测到以下自定义 headerfooter 模板：[/bold]")
        console.print("  [0] 系统默认模板")
        for i, name in enumerate(header_custom, 1):
            display = name.replace("headerfooter_", "").replace(".tex", "")
            console.print(f"  [{i}] {display}")

        while True:
            choice = input("请选择 headerfooter 模板（输入序号）：").strip()
            try:
                idx = int(choice)
                if idx == 0:
                    result["header_is_custom"] = False
                    print_status("使用系统默认 headerfooter 模板", style="cyan")
                    break
                elif 1 <= idx <= len(header_custom):
                    result["header_tpl_path"] = template_dir / "custom" / header_custom[idx - 1]
                    result["header_is_custom"] = True
                    print_status(f"使用自定义 headerfooter 模板：{header_custom[idx - 1]}", style="green")
                    break
                else:
                    print_warning("序号超出范围，请重新输入。")
            except ValueError:
                print_warning("请输入有效数字。")
    else:
        console.print("[dim]未检测到自定义 headerfooter 模板，使用系统默认。[/dim]")

    # 提示缺失的自定义模板
    if main_custom and not header_custom:
        print_warning("检测到您未上传 headerfooter 模板，将使用系统默认的 headerfooter.tex")
    elif header_custom and not main_custom:
        print_warning("检测到您未上传 0_main 模板，将使用系统默认的 0_main.tex")

    return result


def build_latex_replacements(config: dict, title: str | None) -> Tuple[dict, dict]:
    """
    根据用户配置构建 LaTeX 两个模板的替换映射。

    返回: (main_replacements, header_replacements)
    """
    main_replacements = {
        "<<FONT_SIZE>>": str(config.get("font_size", 12)),
        "<<CJK_MAIN_FONT>>": config.get("cjk_serif", "SimSun"),
        "<<CJK_SANS_FONT>>": config.get("cjk_sans", "SimHei"),
        "<<CJK_MONO_FONT>>": config.get("cjk_mono", "SimSun"),
        "<<EN_MAIN_FONT>>": config.get("en_serif", "Times New Roman"),
        "<<EN_SANS_FONT>>": config.get("en_sans", "Arial"),
        "<<EN_MONO_FONT>>": config.get("en_mono", "Consolas"),
        "<<DOC_TITLE>>": title if config.get("cover") and title else "",
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

    return main_replacements, header_replacements


def extract_packages_from_tex(tex_content: str) -> list[str]:
    r"""
    从 LaTeX 模板内容中提取所有 \usepackage{...} 和 \RequirePackage{...} 的宏包名。
    返回去重后的宏包名列表（不含选项，如 'amsmath' 而不是 '[sumlimits]{amsmath}'）。
    """
    packages = set()
    # \usepackage[options]{pkgname} 或 \usepackage{pkgname}
    for match in re.finditer(r'\\(?:usepackage|RequirePackage)(?:\[[^\]]*\])?\{([^}]+)\}', tex_content):
        pkg_str = match.group(1)
        # 可能一个括号里有多个宏包，用逗号分隔：\usepackage{a,b,c}
        for pkg in pkg_str.split(','):
            pkg = pkg.strip()
            if pkg:
                packages.add(pkg)
    return sorted(packages)


def fill_latex_templates(template_dir: Path, config: dict, title: str | None, template_choice: dict = None) -> Tuple[str, str]:
    """
    填充 LaTeX 主模板和页眉页脚模板。
    支持使用用户自定义模板（无占位符或兼容占位符）。

    参数:
        template_dir: Template/ 目录路径
        config: 用户配置
        title: 笔记标题
        template_choice: 模板选择结果（可选），包含 main_tpl_path, header_tpl_path 等

    返回: (main_tex_content, header_tex_content)
    """
    main_replacements, header_replacements = build_latex_replacements(config, title)

    # 0_main 模板
    if template_choice and template_choice.get("main_is_custom"):
        # 自定义模板：直接读取，如果有占位符也尝试替换（兼容用户部分自定义的情况）
        main_tex = fill_template(template_choice["main_tpl_path"], main_replacements)
    else:
        main_tex = fill_template(template_dir / "0_main.tex", main_replacements)

    # headerfooter 模板
    if template_choice and template_choice.get("header_is_custom"):
        header_tex = fill_template(template_choice["header_tpl_path"], header_replacements)
    else:
        header_tex = fill_template(template_dir / "headerfooter.tex", header_replacements)

    return main_tex, header_tex


def save_note_output(
    output_dir: Path,
    content: str,
    output_format: str,
    main_tex: str = "",
    header_tex: str = ""
) -> None:
    """
    统一保存笔记输出文件。

    参数:
        output_dir: 输出目录
        content: 正文内容
        output_format: "latex" 或 "markdown"
        main_tex: LaTeX 主模板内容（仅 latex 格式需要）
        header_tex: 页眉页脚模板内容（仅 latex 格式需要）
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    if output_format == "latex":
        if main_tex == "" or header_tex == "":
            raise ValueError("LaTeX 输出需要提供 main_tex 和 header_tex")
        (output_dir / "main.tex").write_text(main_tex, encoding="utf-8")
        (output_dir / "headerfooter.tex").write_text(header_tex, encoding="utf-8")
        (output_dir / "content.tex").write_text(content, encoding="utf-8")
    else:
        (output_dir / "content.md").write_text(content, encoding="utf-8")


def save_draft(
    article_dir: Path,
    draft_no: int,
    content: str,
    output_format: str,
    main_tex: str = "",
    header_tex: str = ""
) -> Path:
    """
    保存草稿到 draft_XX 目录，返回草稿目录路径。
    """
    draft_dir = article_dir / f"draft_{draft_no:02d}"
    draft_dir.mkdir(parents=True, exist_ok=True)

    save_note_output(draft_dir, content, output_format, main_tex, header_tex)
    return draft_dir