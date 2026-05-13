#!/usr/bin/env python3
"""工具函数：路径、检查、LaTeX后处理、草稿管理、控制台输出"""
import re
import shutil
from pathlib import Path

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn
from rich.panel import Panel
from rich.table import Table

# ---------- 常量 ----------
BASE_DIR = Path(__file__).resolve().parent
SOURCE_DIR = BASE_DIR / "Source"
TEMPLATE_DIR = BASE_DIR / "Template"
RESULT_DIR = BASE_DIR / "Result"
DEFAULT_MAX_CHARS = 30000

console = Console()

def print_status(message: str, style: str = "green", icon: str = "✔"):
    """打印带颜色的状态信息"""
    console.print(f"[{style}]{icon} {message}[/{style}]")

def print_warning(message: str):
    console.print(f"[yellow]⚠ {message}[/yellow]")

def print_error(message: str):
    console.print(f"[red]✘ {message}[/red]")

def print_panel(title: str, content: str):
    console.print(Panel(content, title=title, border_style="green"))

def print_table(header: list, rows: list):
    table = Table(show_header=True, header_style="bold blue")
    for h in header:
        table.add_column(h, style="cyan")
    for row in rows:
        table.add_row(*[str(r) for r in row])
    console.print(table)

def create_progress():
    """创建一个带 spinner 的进度条"""
    return Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        console=console,
        transient=False,
    )

def brace_balanced(s: str) -> bool:
    stack = []
    for ch in s:
        if ch == '{':
            stack.append(ch)
        elif ch == '}':
            if not stack:
                return False
            stack.pop()
    return len(stack) == 0

def get_next_article_dir() -> Path:
    RESULT_DIR.mkdir(parents=True, exist_ok=True)
    existing = []
    pattern = re.compile(r"^Article_(\d+)$")
    for item in RESULT_DIR.iterdir():
        if item.is_dir():
            match = pattern.match(item.name)
            if match:
                existing.append(int(match.group(1)))
    next_num = max(existing) + 1 if existing else 1
    article_dir = RESULT_DIR / f"Article_{next_num}"
    article_dir.mkdir(parents=True, exist_ok=True)
    return article_dir

def ensure_directories():
    for d in (SOURCE_DIR, TEMPLATE_DIR, RESULT_DIR):
        d.mkdir(parents=True, exist_ok=True)

def postprocess_latex(latex: str) -> str:
    """本地修复 AI 常见的表格列数不匹配、空环境、缺少花括号等问题"""
    def fix_tabular(match):
        cols_def = match.group(1)
        body = match.group(2)
        first_data_line = ""
        for line in body.splitlines():
            line = line.strip()
            if line and not line.startswith('%') and '&' in line:
                first_data_line = line
                break
        if not first_data_line:
            return match.group(0)
        n_cols = len(first_data_line.split('&'))
        col_letters = re.findall(r'[lcrp]', cols_def)
        if len(col_letters) != n_cols:
            new_cols = 'l' * n_cols
            fixed = match.group(0).replace(cols_def, new_cols, 1)
            return fixed
        return match.group(0)

    latex = re.sub(r'\\begin\{tabular\}(\{[^}]*\})(.*?)\\end\{tabular\}', fix_tabular, latex, flags=re.DOTALL)
    latex = re.sub(r'\\begin\{lstlisting\}\s*\\end\{lstlisting\}', '', latex)
    latex = re.sub(r'\\begin\{tabular\}([^{])', r'\\begin{tabular}{\1}', latex)
    return latex

# ---------- 草稿管理 ----------
def clear_drafts(article_dir: Path):
    for d in article_dir.iterdir():
        if d.is_dir() and d.name.startswith("draft_"):
            shutil.rmtree(d)