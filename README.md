# 👗 AI Outfit Advisor · 小衣

> **V1.2+** — LangChain Agent + RAG 的极客风穿搭决策引擎

面向大学生场景的智能穿搭顾问，结合 **Qwen3-max** 大模型、**Chroma** 本地向量库与 **DuckDuckGo** 联网搜索，实现“可检索、可联网、可记忆”的穿搭建议生成。

---

## 🧠 系统架构（RAG + Tool Calling）

```
┌─────────────────────────────────────────────┐
│                  Streamlit UI               │
│  app_qa.py / app_file_uploader.py            │
└─────────────────────────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────────┐
│                  RagService                  │
│  - Prompt + Agent + History                  │
│  - RunnableWithMessageHistory                │
└─────────────────────────────────────────────┘
       │                     │
       │                     ├──────────► DuckDuckGoSearchRun (联网搜索)
       │                     │
       │                     └──────────► Retriever Tool (知识库检索)
       │                                   ▲
       │                                   │
       │                        VectorStoreService
       │                        (Chroma Retriever)
       │
       └──────────► ChatTongyi (Qwen3-max)
                     ▲
                     │
                DashScope API
```

**RAG 检索流程**
1. `app_qa.py` 收集用户画像（性别/风格/体型）与问题。
2. `RagService` 组装 Prompt + Tool Calling Agent。
3. Agent 根据问题决定调用 **知识库检索** 或 **联网搜索**。
4. 知识库检索通过 `VectorStoreService → Chroma` 返回相关片段。
5. 最终由 `ChatTongyi (Qwen3-max)` 统一生成回答，Streamlit 端打字机式流式输出。

**LLM 调用逻辑**
- 使用 DashScope 的 `qwen3-max` 作为主模型。
- Agent 模式下允许工具调用，但对用户侧隐藏工具细节。
- 通过 `ConsoleLoggingHandler` 与 Streamlit `status` 实时输出推理/检索状态。

---

## 🔧 重构说明（模块化优化）

本次更新重点对 **配置层** 与 **检索层** 做了拆分与复用：

- **`config_data.py` 分层配置**
  - 统一模型名、向量库路径、切分参数、会话存储路径等配置。
  - 内置 `.env` 自动加载逻辑，减少显式环境注入成本。

- **`vector_store_service.py` 向量检索服务封装**
  - 将 Chroma 的初始化与 retriever 构建收敛为独立服务。
  - 让 `rag.py` 聚焦于 Agent 逻辑，而非底层检索细节。

- **`knowledge_base.py` 负责知识入库**
  - 文本切分 + MD5 去重 + 元数据落库。
  - 与检索层解耦，便于未来扩展多格式知识源。

---

## ⚙️ 使用指南

### 环境要求
- Python 3.10+
- DashScope API Key（阿里云）

### 安装依赖

```bash
git clone https://github.com/sleepycat583/ai-outfit-advisor.git
cd ai-outfit-advisor
pip install -r requirements.txt
```

### 环境变量配置

**推荐使用 `.env`（自动加载）：**

```bash
# .env
DASHSCOPE_API_KEY=your-api-key
# 可选：本地代理环境下绕过 DashScope
NO_PROXY=dashscope.aliyuncs.com
```

**或使用命令行注入：**

```bash
export DASHSCOPE_API_KEY="your-api-key"
export NO_PROXY="dashscope.aliyuncs.com"   # 可选
```

### 启动服务

```bash
# 主应用：AI 穿搭问答
streamlit run app_qa.py

# 知识库管理：上传 .txt 文档入库
streamlit run app_file_uploader.py
```

---

## 📂 项目结构

```
ai-outfit-advisor/
├── app_qa.py                 # 主界面：聊天 + 个性化档案
├── app_file_uploader.py      # 知识库上传入口
├── rag.py                    # Agent + RAG 组合核心
├── vector_store_service.py   # 向量检索服务封装
├── knowledge_base.py         # 入库、切分、MD5 去重
├── history.py                # 文件型对话历史存储（带锁）
├── config_data.py            # 配置中心（含 .env 读取）
├── requirements.txt
├── data/chroma/              # Chroma 向量库持久化目录
└── chat_history/             # 会话历史 JSON
```

---

## ✅ 未来规划 (TODO)

1. **检索质量优化**：引入 reranker 或混合检索（BM25 + 向量）提升召回精准度。
2. **多格式知识源**：支持 PDF / Markdown / 网页抓取入库，强化知识覆盖面。
3. **用户画像持久化**：将侧边栏档案落库，支持跨会话复用与个性化追踪。

---

## 👤 Author

**sleepycat583** · <https://github.com/sleepycat583>

---

*Built with LangChain + Streamlit + DashScope* 💡
