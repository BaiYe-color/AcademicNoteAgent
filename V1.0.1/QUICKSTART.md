# 快速上手指南

欢迎使用 AcademicNoteAgent！本指南将帮助你从 0 到 1 完成环境配置，并生成第一份学术笔记。

---

## 1. 配置环境

### 1.1 安装 Python 依赖

```bash
pip install -r requirements.txt
```

如果下载慢，可用清华镜像：
```bash
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```

### 1.2 配置 API 密钥

项目根目录有 `.env.example`，复制为 `.env` 并填入密钥：

```bash
cp .env.example .env
```

`.env` 内容示例：
```
DEEPSEEK_API_KEY=你的DeepSeek_API_Key
DASHSCOPE_API_KEY=你的百炼_API_Key

# 以下可选（Windows 本地 OCR 必需）：
TESSERACT_CMD=C:\Program Files\Tesseract-OCR\tesseract.exe
POPPLER_PATH=C:\poppler\bin
```

- **DeepSeek API Key**：从 [DeepSeek 开放平台](https://platform.deepseek.com/) 获取，负责笔记生成、语法修正、修订。
- **百炼 API Key**：从 [阿里云百炼平台](https://bailian.console.aliyun.com/) 获取，负责视觉描述和 OCR。如果暂时不需要 OCR，可跳过，程序会回退到本地 Tesseract（需额外安装）。

### 1.3 安装系统依赖（可选，仅 OCR 需要）

如果你要处理扫描件、手写笔记、图片中的文字：

**Tesseract OCR**
- **Windows**：从 [GitHub](https://github.com/UB-Mannheim/tesseract/wiki) 下载，安装时勾选 **中文简体语言包**。
- **macOS**：`brew install tesseract tesseract-lang`
- **Linux**：`sudo apt install tesseract-ocr tesseract-ocr-chi-sim`

**Poppler**（PDF 转图片用）
- **Windows**：下载 [poppler-windows](https://github.com/oschwartz10612/poppler-windows/releases)，解压后将 `bin` 加入 PATH，或在 `.env` 中设置 `POPPLER_PATH`。
- **macOS**：`brew install poppler`
- **Linux**：`sudo apt install poppler-utils`

### 1.4 安装 LaTeX 环境（可选，仅编译 PDF 需要）

- **Windows**：[MiKTeX](https://miktex.org/download) 或 [TeX Live](https://tug.org/texlive/)
- **macOS**：[MacTeX](https://tug.org/mactex/)
- **Linux**：`sudo apt install texlive-full`

确保 `xelatex` 命令可用。

---

## 2. 运行程序

### 2.1 首次启动

将 PDF 或 PPTX 文件放入 `Source/` 文件夹，然后运行：

```bash
python main.py
```

程序会自动扫描 `Source/` 中的文件并列出供选择。

常用快捷方式：
```bash
python main.py --file "Source/课件.pdf"          # 直接指定文件
python main.py --batch                           # 批量处理多个文件
python main.py --file "Source/课件.pdf" --format md --trace   # 指定格式+追溯
```

### 2.2 交互配置

启动后按提示配置。如果你不确定，**直接回车**即可使用默认值。

**关键设置**（在"快速通道"中可直接修改）：

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| 输出格式 | LaTeX（可编译 PDF）或 Markdown | LaTeX |
| 笔记风格 | 论述型 / 结构化型 / 极简型 / 自定义风格 | 论述型 |
| OCR 模式 | 0-关闭 / 1-仅空白页 / 2-全部页面 | 仅空白页 |
| 原文追溯 | 在关键论点旁标注原始页码 | 关闭 |

**完整配置**还包括：
- **模板选择**（仅 LaTeX）：默认模板或 `Template/custom/` 中的自定义模板
- **字体与字号**（仅默认模板）：中英文字体、正文字号
- **封面与页眉**（仅默认模板 LaTeX）：是否生成封面、页眉文字
- **内容类型**：理论笔记 / 案例分析 / 实验报告 / 数据手册
- **学科识别**：AI 自动识别材料所属学科

> **关于笔记风格的选择建议**：
> - **论述型**（默认）：适合理论性强的课程，输出像一篇连贯综述，保留完整论证脉络。
> - **结构化型**：适合系统学习（如数学、法律），模块化整理，强调概念层次与关联。
> - **极简型**：适合考前快速复习，高密度 bullet points，聚焦核心结论。
> - **自定义风格**：基于上述三种风格追加你自己的要求，例如"每节开头加表格""突出数学公式推导""用中文术语替换英文"等。支持保存到配置中，下次一键调用。

### 2.3 生成与修订

程序自动执行以下步骤：

1. **提取文本**：pdfplumber / python-pptx 提取文字，必要时调用 Qwen-VL 视觉描述或 OCR。
2. **大纲先行**（长文档 >6000 字符）：展示 AI 生成的大纲，你可确认、修改（最多 2 轮）或输入 `skip` 跳过。
3. **生成笔记**：DeepSeek 按选定的笔记风格输出结构化内容，自动感知模板已加载的宏包。
4. **语法修正**（LaTeX）：自动检查并修复括号配对、环境闭合、特殊字符转义等。
5. **保存初稿**：输出到 `Result/Article_X/draft_01`。

**修订环节**：

```
--- 第 1 轮修订 ---
请选择操作：
  [1] 提出具体修改意见
  [2] 结构级调整（整体结构问题）
  [0] 确认完成，生成终稿
```

- **输入 `1`**：写具体修改意见，如"第三章补充一个反例"。
- **输入 `2`**：菜单式选择结构问题，AI 自动调整：
  - `1` 太碎片化了，需要加强连贯性
  - `2` 缺少概念之间的关联说明
  - `3` 各节篇幅不均衡
  - `4` 太冗长了，需要精简
  - `5` 太浅显了，需要加深分析
- **输入 `0`**：结束修订，生成最终稿。

最终稿位于 `Result/Article_X/`，临时草稿自动清理。

> 批量模式会自动跳过大纲确认、多轮修订与打分。

### 2.4 编译 LaTeX（若选了 LaTeX 输出）

```bash
cd Result/Article_1
xelatex main.tex
```

---

## 3. 自定义模板

将自有模板放入 `Template/custom/`，命名格式：
- `0_main_<名称>.tex` —— 主文档模板
- `headerfooter_<名称>.tex` —— 页眉页脚模板

选择自定义模板后，程序会自动跳过冲突配置（字体、字号、封面、页眉等）。自定义模板中不需要占位符，程序不会替换它们。

---

## 4. 常见问题

**Q: 长文档为什么先生成大纲？可以跳过吗？**  
A: 长文档容易因 AI 上下文限制而碎片化。大纲先行让 AI 先建立全局结构。随时输入 `skip` 即可跳过。

**Q: 笔记风格有什么区别？可以自定义吗？**  
A: **论述型**像学术综述，保留论证脉络；**结构化型**像模块化教材，强调概念关联；**极简型**像考前速记，高密度 bullet points。**自定义风格**允许你在任意内置风格上追加自己的要求（如"每节加表格""突出公式"），支持保存和记忆。

**Q: 结构级修订是什么？什么时候用？**  
A: 当你觉得笔记整体结构有问题但不知道具体怎么改时使用。选择对应选项后 AI 自动调整，无需写详细指令。

**Q: OCR 不工作怎么办？**  
A: 确认 `DASHSCOPE_API_KEY` 已填写（百炼 OCR），或已安装 Tesseract+Poppler（本地 OCR）。Windows 必须在 `.env` 中设置 `POPPLER_PATH`。

**Q: 编译 LaTeX 时提示缺少宏包/字体？**  
A: 程序会自动提取模板宏包告知 AI，但偶尔仍可能出错。可手动在模板中添加宏包，或在交互配置中选择系统已有的字体，或使用自定义模板规避。

**Q: 如何中断并恢复？**  
A: 修订阶段按 `Ctrl+C` 退出，草稿会被记录。下次运行 `python main.py` 自动询问是否继续。

**Q: 批量处理时某个文件失败会影响其他文件吗？**  
A: 不会。批量模式下每个文件独立处理，失败会打印错误并继续下一个。

---

现在，你可以开始使用 AcademicNoteAgent 将学习资料整理成高质量的笔记了！
