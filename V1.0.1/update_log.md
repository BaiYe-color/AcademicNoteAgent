
---

## 更新日志

### 版本 V1.0.1 (2026-05-15)

#### ✨ 新增功能
- **长文档自动化去重体系**：针对分段生成长文档时可能出现的跨片段内容重叠问题，引入三层协同去重机制，无需用户手动干预：
  - **B. 分块主题清单（预防层）**：逐段生成时动态维护 `covered_topics` 已覆盖主题列表，通过 prompt 约束后续 chunk "只补充新信息，不要重复展开已有内容"，从源头减少结构性重复。
  - **C. 段落级语义去重（处理层）**：合并全文后，基于字符 2-gram Jaccard 相似度对相邻段落进行滑动窗口比对（默认阈值 0.72，窗口 8），自动删除高度相似的重复段落。自动跳过标题、环境边界和表格，避免误伤格式。
  - **A变体. 跨片段 LLM 查重 + 本地执行（治理层）**：所有 chunk 生成完毕后，将各片段的标题列表与首尾摘要发给 LLM，由 AI 判断是否存在跨片段的内容冗余；本地根据返回的 JSON 建议执行 `merge`（严格去重后合并）或 `delete`（直接删除空壳片段）。

#### 🔧 功能增强
- `utils.py` 新增 `extract_headings()`：支持从 LaTeX（`\section` / `\subsection`）和 Markdown（`##` / `###`）中提取章节标题。
- `utils.py` 新增 `deduplicate_paragraphs()`：通用的段落级语义去重引擎，支持 `latex` 和 `markdown` 两种格式模式。
- `ai_client.py` 的 `generate_chunk_latex()` / `generate_chunk_markdown()` 新增 `covered_topics` 参数，支持接收前序 chunk 的主题清单并注入 system prompt。
- `ai_client.py` 新增 `detect_cross_chunk_duplicates()`：轻量 LLM 调用，基于摘要检测跨片段结构性重复，只输出 JSON、不解释。
- `ai_client.py` 新增 `_apply_duplicate_suggestions()`：本地解析查重报告，执行片段级合并或删除，避免 LLM 直接重写全文导致格式破坏。
- `generate_latex_content()` 与 `generate_markdown_content()` 的长文档分支已完整整合三层去重逻辑，处理流程自动触发，无需额外配置。

---