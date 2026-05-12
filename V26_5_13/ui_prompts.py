#!/usr/bin/env python3
"""交互式配置（支持命令行覆盖、格式、追溯）"""
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

def get_user_config(overrides=None):
    config_data = load_config()
    preset = get_personalized_preset(config_data)

    # 尝试使用个性化预设
    if preset:
        fmt_str = "LaTeX" if preset.get("output_format", "latex") == "latex" else "Markdown"
        trace_str = "开启" if preset.get("source_tracing", False) else "关闭"
        preset_str = f"{preset.get('cjk_serif', '')}、{preset.get('font_size', 12)}pt、" \
                     f"{'有' if preset.get('cover') else '无'}封面、{fmt_str}、追溯{trace_str}"
        print(f"检测到您的常用配置：{preset_str}。是否直接使用？(回车确认，输入任意键进入手动配置)")
        if input().strip() == "":
            config = preset
            # 补充默认字段
            config["cjk_mono"] = "SimSun"
            config["content_type"] = None
            config["cover_title"] = None
            config["cover_author"] = ""
            config["cover_date"] = ""
            config["header_left"] = ""
            config["header_center"] = ""
            config["header_right"] = ""
            config["subject_recognition"] = False
            config["ocr_enabled"] = False
            config.setdefault("output_format", "latex")
            config.setdefault("source_tracing", False)
            update_usage_stats(config_data, config)
            save_config(config_data)
            return config

    # 进入手动配置
    config = {}
    print("输入任意字符进入格式选择，跳过则输入回车，文件将使用默认格式")
    if input().strip() == "":
        config["cjk_serif"] = "SimSun"
        config["cjk_sans"] = "SimHei"
        config["cjk_mono"] = "SimSun"
        config["en_serif"] = "Times New Roman"
        config["en_sans"] = "Arial"
        config["en_mono"] = "Consolas"
        config["font_size"] = 12
        config["cover"] = False
        config["header_enabled"] = False
        config["content_type"] = None
        config["cover_title"] = None
        config["cover_author"] = ""
        config["cover_date"] = ""
        config["header_left"] = ""
        config["header_center"] = ""
        config["header_right"] = ""
        config["subject_recognition"] = False
        config["ocr_enabled"] = False
        config["output_format"] = "latex"
        config["source_tracing"] = False
        update_usage_stats(config_data, config)
        save_config(config_data)
        return config

    # ========== 1. 提前询问输出格式与追溯 ==========
    if overrides and overrides.get("output_format"):
        config["output_format"] = overrides["output_format"]
    else:
        print("\n请选择输出格式：LaTeX 输入 1，Markdown 输入 2，直接回车默认为 LaTeX")
        fmt_choice = input().strip()
        config["output_format"] = "markdown" if fmt_choice == "2" else "latex"

    if overrides and overrides.get("source_tracing") is not None:
        config["source_tracing"] = overrides["source_tracing"]
    else:
        print("\n是否启用原文页码追溯？(输入 y 启用，直接回车跳过，默认关闭)")
        trace_choice = input().strip().lower()
        config["source_tracing"] = trace_choice in ("y", "yes")

    # ========== 2. 字体选择（通用） ==========
    print("\n【中文衬线字体】（正文用）")
    print("宋体输入0 | 思源宋体输入1 | 华文宋体输入2 | 仿宋输入3")
    print("直接回车使用默认：宋体")
    choice = input().strip()
    config["cjk_serif"] = CJK_SERIF_MAP.get(choice, "SimSun")

    print("\n【中文无衬线字体】（标题用）")
    print("黑体输入0 | 思源黑体输入1 | 微软雅黑输入2")
    print("直接回车使用默认：黑体")
    choice = input().strip()
    config["cjk_sans"] = CJK_SANS_MAP.get(choice, "SimHei")

    config["cjk_mono"] = "SimSun"

    print("\n【西文衬线字体】（正文用）")
    print("Times New Roman输入0 | Cambria输入1 | Georgia输入2")
    print("直接回车使用默认：Times New Roman")
    choice = input().strip()
    config["en_serif"] = EN_SERIF_MAP.get(choice, "Times New Roman")

    print("\n【西文无衬线字体】（标题用）")
    print("Arial输入0 | Helvetica输入1 | Calibri输入2 | Roboto输入3")
    print("直接回车使用默认：Arial")
    choice = input().strip()
    config["en_sans"] = EN_SANS_MAP.get(choice, "Arial")

    print("\n【西文等宽字体】（代码用）")
    print("Consolas输入0 | JetBrains Mono输入1")
    print("直接回车使用默认：Consolas")
    choice = input().strip()
    config["en_mono"] = EN_MONO_MAP.get(choice, "Consolas")

    # ========== 3. 字号（通用） ==========
    print("\n请设置正文字体大小，使用默认大小则输入回车，默认小四号（12pt）")
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

    # ========== 4. 封面和页眉（仅 LaTeX） ==========
    if config.get("output_format") == "latex":
        print("\n输入任意字符进入封面设置，跳过则输入回车，LaTeX将不生成封面")
        cover_choice = input().strip()
        if cover_choice == "":
            config["cover"] = False
        else:
            config["cover"] = True
            print("\n请设置封面标题，使用默认标题则输入回车，默认标题由Agent自动生成")
            title_input = input().strip()
            config["cover_title"] = None if title_input == "" else title_input
            print("\n请设置作者，空白则输入回车")
            author_input = input().strip()
            config["cover_author"] = author_input if author_input else ""
            print("\n请设置创作时间，使用默认时间则输入回车，默认时间为当前年份")
            date_input = input().strip()
            config["cover_date"] = date_input if date_input else str(date.today().year)

        print("\n输入任意字符进入页眉设置，跳过则输入回车，LaTeX将不生成页眉")
        header_choice = input().strip()
        if header_choice == "":
            config["header_enabled"] = False
        else:
            config["header_enabled"] = True
            print("\n请输入左页眉，空白则输入回车")
            config["header_left"] = input().strip()
            print("请输入中页眉，空白则输入回车")
            config["header_center"] = input().strip()
            print("请输入右页眉，空白则输入回车")
            config["header_right"] = input().strip()
    else:
        config["cover"] = False
        config["header_enabled"] = False

    # ========== 5. 内容类型、学科识别、OCR（通用） ==========
    print("\n请输入内容类型（直接回车则自动识别）：")
    print("1-理论笔记  2-案例分析  3-实验报告  4-数据手册")
    type_choice = input().strip()
    config["content_type"] = type_choice if type_choice in ["1","2","3","4"] else None

    print("\n是否需要AI识别学科类型？(回车确认/输入no跳过)")
    recog_choice = input().strip().lower()
    config["subject_recognition"] = False if recog_choice == "no" else True

    #OCR选项：
    print("\n请选择 OCR 模式：")
    print("1 - 仅对空白页启用 OCR（默认）")
    print("2 - 对所有页面启用补充 OCR（可提取图表中的文字，速度稍慢）")
    print("直接回车则完全关闭 OCR")
    ocr_choice = input().strip()
    if ocr_choice == "2":
        config["ocr_mode"] = "2"
    elif ocr_choice == "1":
        config["ocr_mode"] = "1"
    else:
        config["ocr_mode"] = "0"   # 0 表示关闭 OCR

    update_usage_stats(config_data, config)
    save_config(config_data)
    return config