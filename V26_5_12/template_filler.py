#!/usr/bin/env python3
"""模板填充工具"""
from pathlib import Path

def fill_template(template_path: str, output_path: str, replacements: dict):
    tpl = Path(template_path)
    if not tpl.is_file():
        raise FileNotFoundError(f"模板文件不存在：{tpl}")
    content = tpl.read_text(encoding="utf-8")
    for ph, val in replacements.items():
        content = content.replace(ph, str(val))
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(content, encoding="utf-8")