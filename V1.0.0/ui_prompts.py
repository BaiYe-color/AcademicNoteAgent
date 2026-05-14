#!/usr/bin/env python3
"""交互式配置（优化：预设后可快速修改OCR/输出格式/追溯）"""
from datetime import date
import sys
from config_manager import load_config, save_config, update_usage_stats, get_personalized_preset

# ---------- 字体映射 ----------
CJK_SERIF_MAP = {
    "0": "SimSun",
    "1": "Source Han Serif SC",
    "2": "STSong",
    "3": "FangSong",
}
CJK_SANS_MAP = {
    "0": "SimHei",
    "1": "Source Han Sans SC",
    "2": "Microsoft YaHei",
}
EN_SERIF_MAP = {
    "0": "Times New Roman",
    "1": "Cambria",
    "2": "Georgia",
}
EN_SANS_MAP = {
    "0": "Arial",
    "1": "Helvetica",
    "2": "Calibri",
    "3": "Roboto",
}
EN_MONO_MAP = {
    "0": "Consolas",
    "1": "JetBrains Mono",
}

def _print_config_table(config, template_choice=None, title="当前配置"):
    """用 rich 表格打印当前配置，供用户确认。"""
    from rich.table import Table
    from rich.panel import Panel
    from utils import console

    table = Table(show_header=True, header_style="bold blue", border_style="dim")
    table.add_column("配置项", style="cyan", width=14)
    table.add_column("当前值", style="green")

    fmt = "LaTeX" if config.get("output_format") == "latex" else "Markdown"
    table.add_row("输出格式", fmt)

    style_map = {"narrative": "论述型", "structured": "结构化型", "minimal": "极简型"}
    style_display = style_map.get(config.get("note_style", "narrative"), "论述型")
    custom_name = config.get("custom_style_name")
    if custom_name:
        style_display = f"自定义({custom_name})"
    table.add_row("笔记风格", style_display)

    ocr_map = {"0": "关闭", "1": "仅空白页", "2": "全部页面"}
    table.add_row("OCR 模式", ocr_map.get(config.get("ocr_mode", "1"), "未知"))

    trace = "开启" if config.get("source_tracing") else "关闭"
    table.add_row("原文追溯", trace)

    if template_choice:
        main_tpl = "自定义" if template_choice.get("main_is_custom") else "系统默认"
        header_tpl = "自定义" if template_choice.get("header_is_custom") else "系统默认"
        table.add_row("主模板", main_tpl)
        table.add_row("页眉模板", header_tpl)
    else:
        table.add_row("模板", "系统默认")

    if config.get("output_format") == "latex":
        if not (template_choice and template_choice.get("main_is_custom")):
            table.add_row("中文字体", f"{config.get('cjk_serif', 'SimSun')} / {config.get('cjk_sans', 'SimHei')}")
            table.add_row("正文字号", f"{config.get('font_size', 12)}pt")

        cover = "有" if config.get("cover") else "无"
        table.add_row("封面", cover)

        header = "有" if config.get("header_enabled") else "无"
        table.add_row("页眉", header)

    panel = Panel(table, title=title, border_style="blue", padding=(0, 1))
    console.print()
    console.print(panel)
    console.print()


def _handle_custom_style(config_data, config):
    """
    处理自定义风格的选择、创建和加载。
    返回 (note_style, custom_addons, custom_style_name)
    """
    custom_styles = config_data.get("custom_styles", {})

    print("\n自定义风格选项：")
    print("[1] 基于论述型追加要求")
    print("[2] 基于结构化型追加要求")
    print("[3] 基于极简型追加要求")
    if custom_styles:
        print("[4] 使用已保存的自定义风格")
    print("[0] 返回上级")

    choice = input().strip()

    if choice == "0":
        return None, [], None

    if choice == "4" and custom_styles:
        print("\n已保存的自定义风格：")
        names = list(custom_styles.keys())
        for i, name in enumerate(names, 1):
            base = custom_styles[name].get("base_style", "narrative")
            base_display = {"narrative": "论述型", "structured": "结构化型", "minimal": "极简型"}.get(base, base)
            print(f"  [{i}] {name}（基于 {base_display}）")
        print("  [0] 返回")

        while True:
            c = input("请选择：").strip()
            if c == "0":
                return _handle_custom_style(config_data, config)
            try:
                idx = int(c)
                if 1 <= idx <= len(names):
                    selected = names[idx - 1]
                    style_data = custom_styles[selected]
                    return style_data["base_style"], style_data["addons"], selected
            except:
                pass
            print("无效输入，请重新选择。")

    base_map = {"1": "narrative", "2": "structured", "3": "minimal"}
    if choice not in base_map:
        print("无效输入，使用论述型作为基础。")
        base_style = "narrative"
    else:
        base_style = base_map[choice]

    print("\n请输入你的追加要求，每行一条，直接回车结束：")
    addons = []
    while True:
        line = input("> ").strip()
        if not line:
            break
        addons.append(line)

    if not addons:
        print("未输入追加要求，将使用基础风格。")
        return base_style, [], None

    print("\n是否保存此自定义风格供下次使用？")
    print("回车跳过，输入名称保存")
    name_input = input().strip()
    if name_input:
        config_data.setdefault("custom_styles", {})[name_input] = {
            "base_style": base_style,
            "addons": addons
        }
        from config_manager import save_config
        save_config(config_data)
        print(f"已保存自定义风格：{name_input}")
        return base_style, addons, name_input

    return base_style, addons, None


def get_user_config(overrides=None, template_dir=None):
    """
    交互式获取用户配置。
    template_dir: Template/ 目录路径，用于扫描和选择自定义 LaTeX 模板。
    返回: (config_dict, template_choice_dict)
    """
    config_data = load_config()
    preset = get_personalized_preset(config_data)

    # 模板选择结果，将在输出格式确定后填充
    template_choice = None

    # ========== 1. 尝试个性化预设 ==========
    if preset:
        # 仅当没有使用自定义模板时才使用预设（预设包含字体/页眉等）
        fmt_str = "LaTeX" if preset.get("output_format", "latex") == "latex" else "Markdown"
        trace_str = "开启" if preset.get("source_tracing", False) else "关闭"
        ocr_str = {"0": "关闭", "1": "仅空白页", "2": "全部页面"}.get(preset.get("ocr_mode", "1"), "未知")
        style_str = {"narrative": "论述型", "structured": "结构化型", "minimal": "极简型"}.get(preset.get("note_style", "narrative"), "论述型")
        custom_style_name = preset.get("custom_style_name")
        if custom_style_name:
            style_str = f"自定义({custom_style_name})"
        preset_str = (f"{preset.get('cjk_serif', '')}、{preset.get('font_size', 12)}pt、"
                     f"{'有' if preset.get('cover') else '无'}封面、{fmt_str}、OCR {ocr_str}、追溯{trace_str}、{style_str}")
        print(f"检测到您的常用配置：{preset_str}。是否直接使用？(回车确认，输入任意键进入完整配置)")
        if input().strip() == "":
            config = preset
            # 补充非统计字段的默认值
            config["cjk_mono"] = "SimSun"
            config["content_type"] = None
            config["cover_title"] = None
            config["cover_author"] = ""
            config["cover_date"] = ""
            config["header_left"] = ""
            config["header_center"] = ""
            config["header_right"] = ""
            config["subject_recognition"] = False
            config.setdefault("ocr_mode", "1")
            config.setdefault("output_format", "latex")
            config.setdefault("source_tracing", False)
            config.setdefault("note_style", "narrative")

            # 快速调整关键选项
            style_str = {"narrative": "论述型", "structured": "结构化型", "minimal": "极简型"}.get(config.get('note_style', 'narrative'), "论述型")
            custom_name = config.get('custom_style_name')
            if custom_name:
                style_str = f"自定义({custom_name})"
            print(f"\n当前关键设置：输出格式={fmt_str}，OCR模式={ocr_str}，追溯={trace_str}，笔记风格={style_str}")
            print("是否需要修改这些选项？输入 y 进入快速修改，直接回车确认并继续：")
            adjust = input().strip().lower()
            if adjust == 'y':
                # 输出格式
                print("请选择输出格式：LaTeX 输入 1，Markdown 输入 2，直接回车保持不变")
                fmt_choice = input().strip()
                if fmt_choice == '2':
                    config['output_format'] = 'markdown'
                elif fmt_choice == '1':
                    config['output_format'] = 'latex'

                # OCR 模式
                print("请选择 OCR 模式（0-关闭, 1-仅空白页, 2-全部页面），直接回车保持不变：")
                ocr_input = input().strip()
                if ocr_input in ['0', '1', '2']:
                    config['ocr_mode'] = ocr_input

                # 原文追溯
                print("是否启用原文页码追溯？(输入 y 开启，输入 n 关闭，直接回车保持不变)")
                trace_input = input().strip().lower()
                if trace_input == 'y':
                    config['source_tracing'] = True
                elif trace_input == 'n':
                    config['source_tracing'] = False

                # 笔记风格
                cur_style_name = {"narrative": "论述型", "structured": "结构化型", "minimal": "极简型"}.get(config.get('note_style', 'narrative'), "论述型")
                cur_custom = config.get('custom_style_name')
                if cur_custom:
                    cur_style_name = f"自定义({cur_custom})"
                print(f"请选择笔记风格（当前：{cur_style_name}）：")
                print("  1-论述型 2-结构化型 3-极简型 4-自定义风格，直接回车保持不变")
                style_input = input().strip()
                if style_input == '1':
                    config['note_style'] = 'narrative'
                    config['custom_addons'] = []
                    config['custom_style_name'] = None
                elif style_input == '2':
                    config['note_style'] = 'structured'
                    config['custom_addons'] = []
                    config['custom_style_name'] = None
                elif style_input == '3':
                    config['note_style'] = 'minimal'
                    config['custom_addons'] = []
                    config['custom_style_name'] = None
                elif style_input == '4':
                    note_style, custom_addons, custom_name = _handle_custom_style(config_data, config)
                    if note_style is not None:
                        config['note_style'] = note_style
                        config['custom_addons'] = custom_addons
                        config['custom_style_name'] = custom_name

                # 更新统计
                update_usage_stats(config_data, config)
                save_config(config_data)

            _print_config_table(config, None, "快速通道配置确认")
            return config, None

    # ========== 2. 完整手动配置 ==========
    config = {}

    # --- 输出格式 ---
    if overrides and overrides.get("output_format"):
        config["output_format"] = overrides["output_format"]
    else:
        print("\n请选择输出格式：LaTeX 输入 1，Markdown 输入 2，直接回车默认为 LaTeX")
        fmt_choice = input().strip()
        config["output_format"] = "markdown" if fmt_choice == "2" else "latex"

    # --- 原文追溯 ---
    if overrides and overrides.get("source_tracing") is not None:
        config["source_tracing"] = overrides["source_tracing"]
    else:
        print("\n是否启用原文页码追溯？(输入 y 启用，直接回车跳过，默认关闭)")
        trace_choice = input().strip().lower()
        config["source_tracing"] = trace_choice in ("y", "yes")

    # --- 笔记风格 ---
    print("\n" + "=" * 50)
    print("【笔记风格选择提示】")
    print("-" * 50)
    print("论述型：像学术综述，保留因果链条和过渡句，适合理论讲义/论文")
    print("结构化型：模块化分块，强调概念层次与关联，适合系统学习（数学/法律等）")
    print("极简型  ：高密度 bullet points，去冗余，适合考前快速复习")
    print("=" * 50)
    print("\n请选择笔记整理风格：")
    print("1 - 论述型（默认）：保留原文论证脉络，像一篇连贯的学术综述")
    print("2 - 结构化型：模块化整理，强调概念层次与关联，适合系统学习")
    print("3 - 极简型：提取核心要点，简洁 bullet points，适合快速复习")
    print("4 - 自定义风格：基于内置风格追加你的个性化要求")
    print("直接回车使用默认（论述型）")
    style_choice = input().strip()
    if style_choice == "4":
        note_style, custom_addons, custom_name = _handle_custom_style(config_data, config)
        if note_style is None:
            note_style = "narrative"
            custom_addons = []
            custom_name = None
        config["note_style"] = note_style
        config["custom_addons"] = custom_addons
        config["custom_style_name"] = custom_name
    elif style_choice == "2":
        config["note_style"] = "structured"
        config["custom_addons"] = []
        config["custom_style_name"] = None
    elif style_choice == "3":
        config["note_style"] = "minimal"
        config["custom_addons"] = []
        config["custom_style_name"] = None
    else:
        config["note_style"] = "narrative"
        config["custom_addons"] = []
        config["custom_style_name"] = None

    # --- OCR 模式 ---
    print("\n请选择 OCR 模式（对 PDF 全页识别，对 PPTX 识别内嵌图片）：")
    print("1 - 仅对空白页/无文字幻灯片启用 OCR（默认，速度较快）")
    print("2 - 对所有页/幻灯片启用补充 OCR（可提取图表中的文字）")
    print("   ⚠ 注意：全页 OCR 需要逐页调用视觉模型，运行时间可能增加数倍")
    print("直接回车则完全关闭 OCR")
    ocr_choice = input().strip()
    if ocr_choice == "2":
        config["ocr_mode"] = "2"
    elif ocr_choice == "1":
        config["ocr_mode"] = "1"
    else:
        config["ocr_mode"] = "0"

    # --- 模板选择（仅 LaTeX） ---
    if config.get("output_format") == "latex" and template_dir:
        from template_filler import select_templates_interactive
        template_choice = select_templates_interactive(template_dir)
    else:
        template_choice = None

    main_is_custom = template_choice and template_choice.get("main_is_custom")
    header_is_custom = template_choice and template_choice.get("header_is_custom")

    # --- 字体选择（仅当使用系统默认 0_main 模板时询问） ---
    if not main_is_custom:
        print("\n--- 字体设置（直接回车使用默认） ---")
        print("【中文衬线字体】宋体输入0 | 思源宋体输入1 | 华文宋体输入2 | 仿宋输入3 (默认宋体)")
        choice = input().strip()
        config["cjk_serif"] = CJK_SERIF_MAP.get(choice, "SimSun")

        print("【中文无衬线字体】黑体输入0 | 思源黑体输入1 | 微软雅黑输入2 (默认黑体)")
        choice = input().strip()
        config["cjk_sans"] = CJK_SANS_MAP.get(choice, "SimHei")

        config["cjk_mono"] = "SimSun"

        print("【西文衬线字体】Times New Roman输入0 | Cambria输入1 | Georgia输入2 (默认Times New Roman)")
        choice = input().strip()
        config["en_serif"] = EN_SERIF_MAP.get(choice, "Times New Roman")

        print("【西文无衬线字体】Arial输入0 | Helvetica输入1 | Calibri输入2 | Roboto输入3 (默认Arial)")
        choice = input().strip()
        config["en_sans"] = EN_SANS_MAP.get(choice, "Arial")

        print("【西文等宽字体】Consolas输入0 | JetBrains Mono输入1 (默认Consolas)")
        choice = input().strip()
        config["en_mono"] = EN_MONO_MAP.get(choice, "Consolas")

        # --- 字号 ---
        print("\n请设置正文字体大小，直接回车使用默认小四号（12pt）")
        while True:
            size_input = input().strip()
            if size_input == "":
                config["font_size"] = 12
                break
            try:
                size = int(size_input)
                if 8 <= size <= 20:
                    config["font_size"] = size
                    break
                else:
                    print("字号必须在 8～20 之间，请重新输入：")
            except ValueError:
                print("请输入有效数字，或直接回车使用默认值：")
    else:
        # 使用自定义 0_main 模板，使用占位符默认值（实际不会被替换）
        config["cjk_serif"] = "SimSun"
        config["cjk_sans"] = "SimHei"
        config["cjk_mono"] = "SimSun"
        config["en_serif"] = "Times New Roman"
        config["en_sans"] = "Arial"
        config["en_mono"] = "Consolas"
        config["font_size"] = 12
        print("\n[dim]已使用自定义 0_main 模板，跳过字体和字号设置。[/dim]")

    # --- 封面和页眉（仅 LaTeX） ---
    if config.get("output_format") == "latex":
        # 封面（仅当使用系统默认 0_main 模板时询问）
        if not main_is_custom:
            print("\n是否生成封面？(回车跳过，输入任意键进入封面设置)")
            cover_choice = input().strip()
            if cover_choice == "":
                config["cover"] = False
            else:
                config["cover"] = True
                print("请设置封面标题，直接回车则自动生成")
                title_input = input().strip()
                config["cover_title"] = None if title_input == "" else title_input
                print("请设置作者，直接回车留空")
                author_input = input().strip()
                config["cover_author"] = author_input if author_input else ""
                print("请设置创作时间，直接回车使用当前年份")
                date_input = input().strip()
                config["cover_date"] = date_input if date_input else str(date.today().year)
        else:
            config["cover"] = False
            config["cover_title"] = None
            config["cover_author"] = ""
            config["cover_date"] = ""
            print("\n[dim]已使用自定义 0_main 模板，跳过封面设置。[/dim]")

        # 页眉（仅当使用系统默认 headerfooter 模板时询问）
        if not header_is_custom:
            print("\n是否生成页眉？(回车跳过，输入任意键进入页眉设置)")
            header_choice = input().strip()
            if header_choice == "":
                config["header_enabled"] = False
            else:
                config["header_enabled"] = True
                print("请输入左页眉，直接回车留空")
                config["header_left"] = input().strip()
                print("请输入中页眉，直接回车留空")
                config["header_center"] = input().strip()
                print("请输入右页眉，直接回车留空")
                config["header_right"] = input().strip()
        else:
            config["header_enabled"] = False
            config["header_left"] = ""
            config["header_center"] = ""
            config["header_right"] = ""
            print("\n[dim]已使用自定义 headerfooter 模板，跳过页眉设置。[/dim]")
    else:
        # Markdown 无封面页眉
        config["cover"] = False
        config["header_enabled"] = False
        config["cover_title"] = None
        config["cover_author"] = ""
        config["cover_date"] = ""
        config["header_left"] = ""
        config["header_center"] = ""
        config["header_right"] = ""

    # --- 内容类型 ---
    print("\n请输入内容类型（直接回车则自动识别）：")
    print("1-理论笔记  2-案例分析  3-实验报告  4-数据手册")
    type_choice = input().strip()
    config["content_type"] = type_choice if type_choice in ["1","2","3","4"] else None

    # --- 学科识别 ---
    print("\n是否需要AI识别学科类型？(回车确认/输入no跳过，默认跳过)")
    recog_choice = input().strip().lower()
    config["subject_recognition"] = recog_choice != "no"

    # 更新统计并保存
    update_usage_stats(config_data, config)
    save_config(config_data)
    _print_config_table(config, template_choice, "最终配置确认")
    return config, template_choice