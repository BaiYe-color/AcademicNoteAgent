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
    """本地修复 AI 常见的表格列数不匹配、空环境、缺少花括号、\hline 位置错误、重复段落、（续）标记等问题"""
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

    # 1. 修复 tabular 列数不匹配
    latex = re.sub(r'\\begin\{tabular\}(\{[^}]*\})(.*?)\\end\{tabular\}', fix_tabular, latex, flags=re.DOTALL)
    # 2. 删除空 lstlisting 环境
    latex = re.sub(r'\\begin\{lstlisting\}\s*\\end\{lstlisting\}', '', latex)
    # 3. 修复缺少列定义的 tabular
    latex = re.sub(r'\\begin\{tabular\}([^{])', r'\\begin{tabular}{\1}', latex)

    # 4. 删除 tabular 环境外的孤立 \hline
    # 策略：先保护 tabular 内部的 \hline，删除外部的
    def protect_hline(match):
        inner = match.group(1)
        # 把内部的 \hline 临时替换为占位符
        inner_protected = inner.replace('\\hline', '\\__HLINE__')
        return match.group(0).replace(inner, inner_protected)

    latex = re.sub(r'(\\begin\{tabular\}.*?\\end\{tabular\})', protect_hline, latex, flags=re.DOTALL)
    # 删除所有剩余的 \hline（这些在 tabular 外）
    latex = re.sub(r'\n\s*\\hline\s*\n', '\n', latex)
    # 恢复 tabular 内部的 \hline
    latex = latex.replace('\\__HLINE__', '\\hline')

    # 5. 过滤标题中的"（续）"标记
    latex = re.sub(r'(\\(?:sub)?section\{[^}]+)（续）', r'\1', latex)
    latex = re.sub(r'(\\(?:sub)?section\{[^}]+)\(续\)', r'\1', latex)

    # 6. 删除相邻的重复段落（简单的行级去重，允许微小差异）
    lines = latex.split('\n')
    deduped = []
    prev_norm = ""
    for line in lines:
        # 对当前行做归一化：去空格、去标点，用于比较
        norm = re.sub(r'\s+', '', line)
        norm = re.sub(r'[。，、；：！？""''（）]', '', norm)
        # 如果归一化后与上一行高度相似（>90% 字符相同）且长度>20，认为是重复
        if len(norm) > 20 and len(prev_norm) > 20:
            # 计算最长公共子串比例
            common = sum(1 for a, b in zip(norm, prev_norm) if a == b)
            ratio = common / max(len(norm), len(prev_norm))
            if ratio > 0.9:
                continue  # 跳过重复行
        deduped.append(line)
        prev_norm = norm
    latex = '\n'.join(deduped)

    return latex

# ---------- 长文档分块 ----------
def split_text_into_chunks(text: str, target_chunk_size: int = 15000, overlap: int = 1000) -> list[str]:
    """
    将文本按段落切分为多个 chunk，相邻 chunk 之间有重叠缓冲区。
    保证不在段落中间切断。
    
    Args:
        text: 原文
        target_chunk_size: 每个 chunk 的目标字符数
        overlap: 相邻 chunk 之间的重叠字符数
    
    Returns:
        chunk 文本列表
    """
    paragraphs = [p for p in text.split('\n') if p.strip()]
    if not paragraphs:
        return []
    if len(text) <= target_chunk_size:
        return [text]
    
    chunks = []
    current_chunk = []
    current_size = 0
    
    for para in paragraphs:
        para_size = len(para) + 1
        if current_size + para_size > target_chunk_size and current_chunk:
            chunk_text = '\n'.join(current_chunk)
            chunks.append(chunk_text)
            
            # 重叠：取当前 chunk 末尾段落作为下一 chunk 开头
            overlap_size = 0
            overlap_paras = []
            for p in reversed(current_chunk):
                overlap_size += len(p) + 1
                overlap_paras.insert(0, p)
                if overlap_size >= overlap:
                    break
            current_chunk = overlap_paras
            current_size = sum(len(p) + 1 for p in current_chunk)
        
        current_chunk.append(para)
        current_size += para_size
    
    if current_chunk:
        chunks.append('\n'.join(current_chunk))
    
    return chunks

# ---------- 概念图谱转换 ----------
def mermaid_to_latex_items(mermaid: str) -> str:
    """将 Mermaid graph 语法转换为 LaTeX 层级描述列表。
    按源节点分组，减少重复，提升可读性。"""
    if not mermaid or not mermaid.strip().startswith('graph'):
        return ""

    lines = mermaid.strip().split('\n')
    node_map = {}
    node_patterns = [
        r'(\w+)\s*\[([^\]]+)\]',
        r'(\w+)\s*\(([^)]+)\)',
        r'(\w+)\s*\{([^}]+)\}'
    ]

    # 第一轮：提取所有节点定义
    for line in lines:
        for pattern in node_patterns:
            for match in re.finditer(pattern, line):
                node_id, label = match.groups()
                node_map[node_id] = label.strip()

    # 第二轮：提取边，按源节点分组
    edges_by_src: dict[str, list[tuple[str, str]]] = {}
    all_dst_ids = set()
    for line in lines:
        line = line.strip()
        if not line or line.startswith('graph') or line.startswith('%'):
            continue

        line_clean = re.sub(r'(\w+)\s*\[.*?\]', r'\1', line)
        line_clean = re.sub(r'(\w+)\s*\(.*?\)', r'\1', line_clean)
        line_clean = re.sub(r'(\w+)\s*\{.*?\}', r'\1', line_clean)

        edge_match = re.search(r'(\w+)\s*--[->]+\s*\|([^|]+)\|\s*(\w+)', line_clean)
        if not edge_match:
            edge_match = re.search(r'(\w+)\s*--[->]+\s*(\w+)', line_clean)
            if not edge_match:
                edge_match = re.search(r'(\w+)\s*---\s*(\w+)', line_clean)

        if edge_match:
            groups = edge_match.groups()
            if len(groups) == 3:
                src_id, label, dst_id = groups
                label = label.strip()
                if label in ("关联", "相关", "涉及", ""):
                    label = "→"
            else:
                src_id, dst_id = groups
                label = "→"
            all_dst_ids.add(dst_id)
            src_name = node_map.get(src_id, src_id)
            dst_name = node_map.get(dst_id, dst_id)
            edges_by_src.setdefault(src_name, []).append((label, dst_name))

    if not edges_by_src:
        return ""

    # 构建 LaTeX：按源节点分组，每个源节点一个 description item
    sections = []
    for src_name, rels in edges_by_src.items():
        sub_items = []
        for label, dst_name in rels:
            if label == "→":
                sub_items.append(f"\\item \\textbf{{{dst_name}}}")
            else:
                sub_items.append(f"\\item {label}：\\textbf{{{dst_name}}}")
        sub_list = "\n".join(sub_items)
        sections.append(
            f"\\item[\\textbf{{{src_name}}}]"
            f"\n\\begin{{itemize}}\n{sub_list}\n\\end{{itemize}}"
        )

    return (
        "\\begin{description}\n"
        + "\n\n".join(sections)
        + "\n\\end{description}"
    )


# ---------- 标题提取 ----------
def extract_headings(text: str, fmt: str = "latex") -> list[str]:
    """从 LaTeX 或 Markdown 文本中提取章节标题列表"""
    headings = []
    if fmt == "latex":
        pattern = re.compile(r'\\(?:sub)?section\*?\{([^}]+)\}')
        for match in pattern.finditer(text):
            headings.append(match.group(1).strip())
    else:  # markdown
        pattern = re.compile(r'^#{2,3}\s+(.+)$', re.MULTILINE)
        for match in pattern.finditer(text):
            headings.append(match.group(1).strip())
    return headings


# ---------- 段落级语义去重 ----------
def _normalize_paragraph(para: str, fmt: str) -> str:
    """提取段落的纯文本指纹，用于相似度比较"""
    # 去除 LaTeX 命令
    text = re.sub(r'\\[a-zA-Z]+\*?(?:\{[^}]*\})*(?:\[[^\]]*\])*', '', para)
    # 去除 Markdown 标记
    text = re.sub(r'[#*`~\[\]!\(\)_>\-|]', '', text)
    # 去除花括号
    text = text.replace('{', '').replace('}', '')
    # 去除标点和空格
    text = re.sub(r'[。，、；：！？”“''（）\s]', '', text)
    return text.lower()


def _jaccard_similarity(a: str, b: str) -> float:
    """计算两个字符串的字符 2-gram Jaccard 相似度"""
    if not a or not b:
        return 0.0
    def get_bigrams(s):
        return set(s[i:i + 2] for i in range(len(s) - 1))
    bg_a = get_bigrams(a)
    bg_b = get_bigrams(b)
    if not bg_a or not bg_b:
        return 0.0
    return len(bg_a & bg_b) / len(bg_a | bg_b)


def deduplicate_paragraphs(text: str, fmt: str = "latex", threshold: float = 0.72, window: int = 8) -> str:
    """
    对文本进行段落级语义去重。

    Args:
        text: 原始文本
        fmt: "latex" 或 "markdown"
        threshold: Jaccard 相似度阈值，超过则认为重复
        window: 只与前面已保留的 N 个普通段落比较

    Returns:
        去重后的文本
    """
    paragraphs = text.split('\n\n')
    kept = []
    kept_norms = []

    for para in paragraphs:
        para_stripped = para.strip()
        if not para_stripped:
            kept.append(para)
            continue

        # 跳过格式边界、环境声明和标题行
        if fmt == "latex":
            if para_stripped.startswith('\\begin') or para_stripped.startswith('\\end'):
                kept.append(para)
                kept_norms.append("")
                continue
            if re.match(r'\\(?:sub)?section', para_stripped):
                kept.append(para)
                kept_norms.append("")
                continue
        else:  # markdown
            if para_stripped.startswith('#'):
                kept.append(para)
                kept_norms.append("")
                continue
            if para_stripped.startswith('```') or para_stripped.startswith('|'):
                kept.append(para)
                kept_norms.append("")
                continue

        norm = _normalize_paragraph(para_stripped, fmt)
        if len(norm) < 12:
            kept.append(para)
            kept_norms.append(norm)
            continue

        # 与前面 window 个已保留的普通段落比较
        is_duplicate = False
        for prev_norm in kept_norms[-window:]:
            if not prev_norm or len(prev_norm) < 12:
                continue
            sim = _jaccard_similarity(norm, prev_norm)
            if sim > threshold:
                is_duplicate = True
                break

        if not is_duplicate:
            kept.append(para)
            kept_norms.append(norm)

    return '\n\n'.join(kept)


# ---------- 草稿管理 ----------
def clear_drafts(article_dir: Path):
    for d in article_dir.iterdir():
        if d.is_dir() and d.name.startswith("draft_"):
            shutil.rmtree(d)