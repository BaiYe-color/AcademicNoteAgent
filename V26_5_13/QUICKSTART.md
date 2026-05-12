# 快速上手指南

欢迎使用 AcademicNoteAgent！本指南将帮助你快速完成环境配置，并运行程序将 PDF 或 PPT 文件整理为学术笔记。

---

## 1. 配置环境

### 1.1 安装 Python 依赖

打开终端（或命令提示符），进入项目根目录，运行以下命令安装所需的 Python 库：

```bash
pip install -r requirements.txt
```

如果下载速度较慢，可以使用清华镜像：

```bash
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```

### 1.2 配置 API 密钥

在项目根目录找到 `.env.example` 文件，将其复制并重命名为 `.env`。用文本编辑器打开 `.env`，填入你的 API 密钥：

```
DEEPSEEK_API_KEY=你的DeepSeek_API_Key
QIANFAN_API_KEY=你的千帆_API_Key
```

- **DeepSeek API Key**：从 [DeepSeek 开放平台](https://platform.deepseek.com/) 获取。
- **千帆 API Key**：从 [百度智能云千帆平台](https://console.bce.baidu.com/qianfan/overview) 获取，用于调用 OCR 或视觉描述功能。

> 如果暂时不需要 OCR 功能，可以跳过千帆密钥的填写，程序将自动回退到本地 Tesseract（需额外安装）。

### 1.3 安装系统依赖（可选，仅当需要 OCR 扫描功能时）

如果你要处理的文件包含**图表、无法直接选中的文字、手写笔迹或扫描图片**，需要安装以下两个软件，以便程序能够将 PDF 页面转换为图片并进行识别。

#### 安装 Tesseract OCR

- **Windows**：从 [GitHub 官方发布页](https://github.com/UB-Mannheim/tesseract/wiki) 下载安装包。
  - 安装时务必勾选 **中文简体语言包**（`Chinese (Simplified)`）。
  - 记下安装路径（例如 `C:\Program Files\Tesseract-OCR`）。
- **macOS**：使用 Homebrew 安装：
  ```bash
  brew install tesseract
  brew install tesseract-lang  # 安装所有语言包，或 brew install tesseract-lang-chi-sim
  ```
- **Linux**：使用包管理器安装：
  ```bash
  sudo apt install tesseract-ocr tesseract-ocr-chi-sim   # Debian/Ubuntu
  ```

安装完成后，请确保 `tesseract` 命令可在终端中直接调用。如果不行，可以在 `.env` 文件中指定完整路径：

```
TESSERACT_CMD=C:\Program Files\Tesseract-OCR\tesseract.exe
```

#### 安装 Poppler

Poppler 用于将 PDF 页面渲染为图片，供 OCR 使用。

- **Windows**：
  - 下载预编译包：[poppler-windows](https://github.com/oschwartz10612/poppler-windows/releases)
  - 解压到任意目录（例如 `C:\poppler`），将 `bin` 子目录添加到系统环境变量 `PATH` 中。
  - 或者在 `.env` 文件中设置：
    ```
    POPPLER_PATH=C:\poppler\bin
    ```
- **macOS**：使用 Homebrew 安装：
  ```bash
  brew install poppler
  ```
- **Linux**：
  ```bash
  sudo apt install poppler-utils   # Debian/Ubuntu
  ```

### 1.4 安装 LaTeX 环境（可选，仅当需要编译 .tex 文件为 PDF 时）

程序生成的 `.tex` 文件不会自动编译为 PDF。如果你希望得到最终的 PDF 文档，需要自行安装 LaTeX 发行版。

- **Windows**：推荐安装 [MiKTeX](https://miktex.org/download) 或 [TeX Live](https://tug.org/texlive/)。
- **macOS**：推荐安装 [MacTeX](https://tug.org/mactex/)。
- **Linux**：使用包管理器安装 TeX Live（例如 `sudo apt install texlive-full`）。

安装完成后，确保 `xelatex` 命令可用。

---

## 2. 运行程序

### 2.1 首次启动

将你需要处理的 **PDF** 或 **PPTX** 文件放入项目目录下的 `Source` 文件夹中。

在终端中运行：

```bash
python main.py
```

程序会自动扫描 `Source` 文件夹内的所有支持文件，并列出供你选择。

如果你希望直接指定某个文件，可以使用：

```bash
python main.py --file "Source/你的课件.pdf"
```

### 2.2 交互配置

启动后，程序会引导你进行一系列选项设置。如果你不确定如何选择，直接按 **回车** 即可使用默认值。

主要配置项包括：

- **输出格式**：选择 LaTeX（可编译为 PDF）或 Markdown（通用笔记）。
- **字体与字号**：选择中英文字体，设置正文字号。
- **封面与页眉**（仅 LaTeX）：是否生成封面，自定义页眉文字。
- **OCR 模式**：
  - `1`：仅对空白页启用 OCR（推荐用于普通 PDF）。
  - `2`：对所有页面启用 OCR 或视觉描述（适合扫描件、手写笔记）。
  - 直接回车：关闭 OCR。
- **内容类型**：可选理论笔记、案例分析等，帮助 AI 采用合适的结构。
- **原文页码追溯**：可在笔记中标注原始页码，方便对照。

多次使用后，程序会记住你的偏好，并提供“快速通道”直接采用常用配置。

### 2.3 生成与修订

程序将自动：

1. 提取文本（必要时调用 OCR 或视觉描述，需要注意的是.PPTX 文件无法进行 OCR 识别）。
2. 调用 DeepSeek 生成结构化笔记。
3. 对 LaTeX 进行自我修正（可跳过）。
4. 保存初稿到 `draft_01`。

此时，你可以选择：

- **输入 `1`**：提出修改意见，AI 会根据意见重新生成并保存到新的草稿（`draft_02`、`draft_03`...）。
- **输入 `0`**：结束修订，生成最终稿。

最终稿会放在 `Result/Article_X/` 目录下，之前的所有临时草稿会被自动清理。

### 2.4 编译 LaTeX（若选择了 LaTeX 输出）

进入对应输出目录，执行：

```bash
cd Result/Article_1
xelatex main.tex
```

即可得到最终的 PDF 文件。

---

## 3. 常见问题

**Q: 运行时提示“pdf2image 或 Poppler 未安装”怎么办？**  
A: 按照第 1.3 节安装 Poppler，并确保已安装 `pdf2image`（已在 requirements.txt 中）。Windows 用户必须设置 `POPPLER_PATH` 环境变量或在 `.env` 中指定。

**Q: 为什么我选择了 OCR 模式 2，终端却没有 OCR 相关输出？**  
A: 可能是处理的是 PPTX 文件（PPTX 暂不支持 OCR），请确认处理的是 PDF。或者 Poppler 未正确配置导致 pdf2image 无法导入。

**Q: 生成的笔记和我提供的文件内容完全无关？**  
A: 通常是因为 OCR 或视觉描述未能提取到有效文字，AI 收到了空白或无效信息而产生了“幻觉”。请确保文件质量、正确安装 OCR 工具，并使用 OCR 模式 2。

**Q: 编译 LaTeX 时提示缺少字体？**  
A: 请确保你的系统安装了程序选择的字体（如 SimSun、SimHei 等）。也可以在交互配置中选择你系统已有的字体。

**Q: 如何中断并恢复工作？**  
A: 在多轮修订阶段，按 `Ctrl+C` 可安全退出，已保存的草稿会被记录。下次运行 `python main.py` 时会询问是否从断点继续，回车即可恢复。

---

现在，你可以开始使用 AcademicNoteAgent 将你的学习资料整理成高质量的笔记了！