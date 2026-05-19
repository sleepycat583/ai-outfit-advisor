# 👗 AI 智能穿搭顾问 · 小衣 (AI Outfit Advisor)

> **V1.2** — 基于 LangChain Agent + RAG 双引擎的个性化穿搭推荐系统

一个面向大学生群体的智能穿搭决策助手。融合**大语言模型 (Qwen3-max)**、**RAG 本地知识库 (Chroma)** 与 **Agent 联网搜索 (DuckDuckGo)**，以"顶尖私人穿搭主理人"人设，为不同性别、风格、体型的用户提供面试、约会、早八等高频场景的 OOTD 解决方案。



<img width="2508" height="1190" alt="image" src="https://github.com/user-attachments/assets/162b3e81-deb7-4da5-9787-d9fcf0fd3fa3" />


---

## ✨ 核心亮点

| 引擎 | 能力 |
|------|------|
| 🧠 **Agent 联网决策** | 自主调用 DuckDuckGo 实时搜索天气、流行趋势，结合 LangChain 全生命周期 Callback 系统实现终端透明日志 |
| 📚 **RAG 本地知识库** | 基于 Chroma 向量数据库，覆盖洗护养护、尺码推荐、颜色搭配三大领域，支持 `.txt` 文档一键上传与 MD5 去重 |
| 🎯 **千人千面画像** | 侧边栏"穿搭档案"支持性别、偏好风格、身高体重动态注入 System Prompt，实现真正的个性化生成 |
| 💬 **专业人设** | "小衣"以时尚主理人口吻输出：场景破冰 → OOTD 推荐 → 私藏贴士 → 专属签名，排版清晰有呼吸感 |

---

## 🚀 最新优化与亮点

- **模块化检索层**：提取 `vector_store_service.py` 统一封装 Chroma 初始化与 Retriever 构建，`rag.py` 聚焦 Agent 逻辑。
- **配置分层与自动加载**：`config_data.py` 集中管理模型名、切分参数、向量库路径等，同时支持 `.env` 自动读取。
- **RAG 检索链路强化**：Retriever Tool 直连知识库，检索返回数量通过 `similarity_threshold` 控制。
- **会话可靠性提升**：文件型历史记录引入锁与原子写入，避免并发写入导致的损坏。

---

## 🏗️ 系统架构

```
┌─────────────────────────────────────────────────┐
│                  Streamlit UI                     │
│  ┌──────────┐  ┌──────────┐  ┌───────────────┐  │
│  │ 侧边栏    │  │ 快捷提问 │  │ 打字机流式输出 │  │
│  │ 穿搭档案  │  │ 一键发送 │  │ typewriter    │  │
│  └──────────┘  └──────────┘  └───────────────┘  │
├─────────────────────────────────────────────────┤
│              LangChain Pipeline                   │
│  ┌─────────────────────────────────────────────┐ │
│  │  RunnableWithMessageHistory                  │ │
│  │  ┌───────────────────────────────────────┐  │ │
│  │  │  AgentExecutor                         │  │ │
│  │  │  ┌─────────────┐  ┌────────────────┐  │  │ │
│  │  │  │ DuckDuckGo  │  │ Retriever Tool │  │  │ │
│  │  │  │ (联网搜索)   │  │ (知识库检索)   │  │  │ │
│  │  │  └─────────────┘  └────────────────┘  │  │ │
│  │  └───────────────────────────────────────┘  │ │
│  │  → RunnableLambda (output extraction)       │ │
│  └─────────────────────────────────────────────┘ │
├─────────────────────────────────────────────────┤
│               Data Layer                          │
│  ┌──────────┐  ┌──────────┐  ┌───────────────┐  │
│  │ Chroma   │  │ File     │  │ DashScope API │  │
│  │ 向量库   │  │ Chat     │  │ Qwen3-max     │  │
│  │          │  │ History  │  │ text-embed-v4 │  │
│  └──────────┘  └──────────┘  └───────────────┘  │
└─────────────────────────────────────────────────┘
```

**RAG 检索流程补充**
1. `app_qa.py` 收集用户画像（性别/风格/体型）与问题。
2. `RagService` 组装 Prompt + Tool Calling Agent。
3. Agent 根据问题决定调用 **知识库检索** 或 **联网搜索**。
4. 知识库检索通过 `VectorStoreService → Chroma` 返回相关片段。
5. 最终由 `ChatTongyi (Qwen3-max)` 统一生成回答，Streamlit 端打字机式流式输出。

**LLM 调用逻辑补充**
- 使用 DashScope 的 `qwen3-max` 作为主模型。
- Agent 模式下允许工具调用，但对用户侧隐藏工具细节。
- `ConsoleLoggingHandler` 与 Streamlit `status` 同步输出推理/检索状态。

---

## 🛠️ 技术栈

| 层级 | 技术选型 |
|------|----------|
| 前端交互 | Streamlit |
| AI 编排 | LangChain (Core + Community + Classic Agents) |
| 大语言模型 | 阿里云 DashScope — Qwen3-max |
| 向量嵌入 | DashScope — text-embedding-v4 |
| 向量数据库 | Chroma (本地持久化) |
| 联网搜索 | DuckDuckGo Search (Agent Tool) |
| 会话管理 | File-based Chat History (JSON 持久化) |
| 文本分割 | LangChain RecursiveCharacterTextSplitter |

---

## 📦 快速开始

### 环境要求

- Python 3.10+
- 阿里云 DashScope API Key

### 安装

```bash
git clone https://github.com/sleepycat583/ai-outfit-advisor.git
cd ai-outfit-advisor
pip install -r requirements.txt
```

### 配置

在代码或环境变量中配置 DashScope API Key：

```bash
export DASHSCOPE_API_KEY="your-api-key"
```

> 如遇本地代理拦截 DashScope 请求（ProxyError），代码已在入口处设置 `NO_PROXY=dashscope.aliyuncs.com` 白名单绕过。

**补充：支持 `.env` 自动加载（推荐）**

```bash
# .env
DASHSCOPE_API_KEY=your-api-key
# 可选：本地代理环境下为 DashScope 绕过代理
NO_PROXY=dashscope.aliyuncs.com
```

### 启动

```bash
# 主应用 — AI 穿搭顾问问答
streamlit run app_qa.py

# 知识库管理 — 上传 .txt 素材
streamlit run app_file_uploader.py
```

**运行逻辑补充**
- `app_file_uploader.py` 负责入库与去重，建议先导入资料再启动问答端。
- `app_qa.py` 通过 `RagService` 调用 Agent，回答支持流式打字机效果与状态提示。

---

## 📂 项目结构

```
ai-outfit-advisor/
├── app_qa.py                   # 主入口：AI 穿搭问答（Streamlit UI）
├── app_file_uploader.py        # 知识库管理：.txt 文档上传与向量化
├── rag.py                      # RAG 核心：Agent + Prompt + 链构建
├── history.py                  # 会话历史：文件持久化读写
├── vector_store_service.py     # 向量检索服务封装
├── knowledge_base.py           # 知识库引擎：Chroma + MD5 去重
├── config_data.py              # 集中配置：模型、切分参数、路径
├── requirements.txt            # Python 依赖清单
├── chat_history/               # 用户会话历史（JSON）
├── data/chroma/                # Chroma 向量库持久化目录
├── 洗涤养护.txt                # 知识库素材
├── 尺码推荐.txt
├── 颜色选择.txt
├── 2026春夏色彩搭配与流行趋势.txt
├── 体型扬长避短穿搭法则.txt
└── 大厂面试穿搭指南.txt
```

---

## 📝 Changelog

### V1.2 (当前版本)

- **全新 Prompt 人设** — "小衣"升级为顶尖私人穿搭主理人，三板块排版美学（场景感知 / OOTD 灵感 / 私藏贴士）+ 专属签名
- **Agent 联网搜索** — 集成 DuckDuckGo Tool，AI 可自主决定联网获取实时天气与流行趋势
- **Callback 架构升级** — `ConsoleLoggingHandler` 从 AgentExecutor 内部迁移至 `chain.stream` 根节点 config 注入，确保终端日志稳定输出
- **DashScope 代理绕过** — 入口处设置 `NO_PROXY` 环境变量，解决本地代理导致的连接失败
- **快捷提问按钮** — 主界面新增面试、洗护、尺码三个一键发送场景
- **流式打字机效果** — 回答逐字渲染，提升交互体验

### V1.0

- 基于 LangChain + Chroma + DashScope 的 RAG 问答框架
- Streamlit 统一交互界面，侧边栏用户画像
- UUID 会话隔离，FileChatMessageHistory 持久化
- 知识库 .txt 上传、文本分割、向量化存储与 MD5 去重

---

## 👤 作者

**sleepycat583** · [GitHub](https://github.com/sleepycat583)

---

*Made with LangChain + Streamlit + ❤️*
