# AcademicNoteAgent — 面向学术写作的自适应笔记智能体

一个基于大语言模型（DeepSeek）的命令行智能体，能够将 **PDF 讲义** 或 **PPT 演示文稿** 自动整理为结构清晰、包含引言与总结的学术笔记，支持 **LaTeX** 与 **Markdown** 两种输出格式。  
具备自主感知、记忆学习、多轮交互修订、断点续传、OCR（含手写识别）与原文页码追溯等能力，是面向学术场景的笔记助手。

---

## 🧠 Agent 核心特性

| 特性 | 说明 |
|------|------|
| 📡 感知环境 | 自动扫描 `Source/` 目录，列出文件供选择；提取 PDF/PPTX 文本；可选 AI 学科识别 |
| 🧠 决策推荐 | 根据历史统计推荐字体、字号、输出格式、溯源等，一键采用 |
| 🛠️ 自主执行 | 调用 DeepSeek 生成结构化笔记，自动修正 LaTeX 语法错误 |
| 📚 记忆学习 | `config.json` 记录偏好与反馈，高分反馈注入后续 prompt，越用越懂你 |
| 🔄 多轮修订 | 生成初稿后支持连续修改，每轮保存草稿，最多支持 5 轮 |
| ⏸️ 断点续传 | 随时中断，下次启动自动检测未完成任务，从断点继续 |
| 📄 双格式输出 | 支持 LaTeX（可编译为 PDF）和 Markdown（通用、可导入笔记软件） |
| 🔍 原文追溯 | 可选在笔记的关键论点旁标注原始页码或幻灯片编号 |
| 🖼️ OCR 识别 | 内置 DeepSeek-OCR（千帆）和本地 Tesseract，支持印刷/手写文字提取，并提供视觉描述模式 |
| 🎨 彩色终端界面 | 使用 `rich` 库提供进度条、彩色状态提示，交互体验清晰 |

---

## 🚀 主要功能一览

- 📥 输入格式：`.pdf`（通过 pdfplumber + 可选 OCR）、`.pptx`（通过 python-pptx）
- 🤖 AI 笔记生成：支持 LaTeX（含引言、正文、总结）和 Markdown 两种结构化输出
- 🔧 自我修正：自动检查并修复 LaTeX 常见语法错误（表格列数、括号配对、特殊字符等）
- ✍️ 多轮交互修订：每轮修订保存独立草稿 `draft_01`、`draft_02` ……
- 📂 智能文件选择：不指定文件时列出 `Source/` 所有文件（含大小和创建时间）
- 🎨 精细格式定制：中英文字体（衬线/无衬线/等宽）、字号、封面、页眉（仅 LaTeX）
- 🧑‍🔬 学科自动识别：可选 AI 识别材料所属学科，并记录偏好
- 💬 满意度反馈与学习：每次生成后评分留建议，高分反馈融入下次生成
- 📊 个性化预设：统计最常用配置，下次可一键使用
- 📁 自动编号与草稿清理：每次处理创建 `Article_X`，结束后只保留最终文件

---

## 📁 项目结构

```
project/
├── main.py               # 主入口
├── utils.py              # 工具函数、草稿管理、控制台输出
├── text_extractor.py     # PDF/PPTX 文本提取（含 OCR 和视觉描述）
├── ai_client.py          # DeepSeek 调用（生成、修正、修订、学科识别）
├── ui_prompts.py         # 交互式配置
├── config_manager.py     # 配置管理、会话状态（断点续传）
├── template_filler.py    # LaTeX 模板填充
├── requirements.txt      # Python 依赖
├── .env.example          # 环境变量模板
├── config.json           # 自动生成，记录偏好与反馈
├── session_state.json    # 会话状态（断点续传用，完成后自动删除）
├── Source/               # 待处理文件
├── Template/             # LaTeX 模板
└── Result/               # 输出目录
```

---

## 🛠️ 安装与配置

### 1. 环境要求
- Python 3.8+
- 完整 TeX 发行版（如 TeX Live、MiKTeX，仅 LaTeX 输出需要，需支持 XeLaTeX）
- Tesseract OCR（可选，用于本地 OCR 回退）
- Poppler（Windows 下 pdf2image 需要）

### 2. 安装 Python 依赖
```bash
git clone <your-repo-url>
cd project
pip install -r requirements.txt
```

### 3. 配置环境变量
复制 `.env.example` 为 `.env` 并填写密钥：
```bash
cp .env.example .env
```
`.env` 文件内容：
```
DEEPSEEK_API_KEY=你的DeepSeek密钥
QIANFAN_API_KEY=你的千帆API Key

# 以下可选：
TESSERACT_CMD=C:\Program Files\Tesseract-OCR\tesseract.exe
POPPLER_PATH=C:\poppler\bin
```

### 4. 安装系统依赖（可选，仅本地 OCR 需要）
- **Tesseract OCR**：从 [GitHub](https://github.com/UB-Mannheim/tesseract/wiki) 下载安装，勾选 `chi_sim` 语言包，将安装目录加入 PATH。
- **Poppler**：Windows 用户从 [这里](https://github.com/oschwartz10612/poppler-windows/releases) 下载，解压后将 `bin` 目录加入 PATH。

### 5. 准备 LaTeX 模板（仅 LaTeX 输出需要）
在 `Template/` 目录下放置 `0_main.tex` 和 `headerfooter.tex`（项目已包含默认模板）。

---

## ⚡ 快速开始

1. 将待处理文件放入 `Source/` 目录。
2. 运行：
   ```bash
   python main.py
   ```
3. 按提示选择文件、输出格式、OCR 模式等。
4. 等待生成，可在多轮修订中反复优化。
5. 最终文件位于 `Result/Article_X/`，LaTeX 文件编译后可得 PDF。

也可直接指定文件并跳过交互：
```bash
python main.py --file "Source/课件.pdf" --format md --trace
```

---

## 📖 使用流程

1. **启动**：程序自动列出 `Source/` 中文件，选择或指定 `--file`。
2. **配置**：可选择个性化预设或手动设置格式、字体、OCR 模式等。
3. **生成**：AI 整理笔记（含引言、总结），自动修正 LaTeX 错误。
4. **修订**：输入修改意见进行多轮打磨，每轮保存草稿。
5. **输出**：生成最终 `.tex` 或 `.md` 文件，编译 LaTeX 得 PDF。
6. **反馈**：打分留言，帮助系统学习你的偏好。

### OCR 使用建议
- 普通文字型 PDF：选择 OCR 模式 **1**（默认），仅对空白页启用。
- 扫描件/手写笔记 PDF：选择 OCR 模式 **2**，程序将对每页进行视觉描述或 OCR 文字提取。
- PPTX 当前暂不支持 OCR。

---

## ⌨️ 命令行参数

| 参数 | 说明 |
|------|------|
| `--file <path>` | 指定文件路径，不提供则交互选择 |
| `--no-reflect` | 跳过 LaTeX 语法自动修正 |
| `--no-revise` | 跳过交互修订，直接使用初稿 |
| `--reset-config` | 重置配置文件为默认 |
| `--format latex` 或 `--format md` | 直接指定输出格式 |
| `--trace` | 启用原文页码追溯 |

---

## 💾 配置文件

`config.json` 自动记录：
- `presets`：常用配置
- `usage_stats`：各选项使用次数（用于个性化推荐）
- `feedback_history`：最近 5 条评分与建议

---

## ❓ 常见问题

**Q: OCR 不工作，日志中没有相关输出？**  
A: 检查 `pdf2image` 和 Poppler 是否正确安装，并在 `.env` 中设置 `POPPLER_PATH`（Windows 必需）。

**Q: 编译 LaTeX 报错？**  
A: 确保系统已安装支持 XeLaTeX 的 TeX 发行版，且模板中指定的中文字体已安装。

**Q: 手写笔记识别效果差？**  
A: 手写体识别仍有局限，可尝试模式 2 的视觉描述，或使用更专业的 OCR 软件转写后再整理。

---

## 📊 适用场景

- 整理课堂讲义、论文笔记
- 会议记录、学术报告归档
- 扫描书籍、手写笔记的数字化与结构化

---

## 🤝 贡献与反馈
欢迎任何形式的贡献，如代码、文档、issue、PR 等。
喜欢不如点个 star 哦 😊
