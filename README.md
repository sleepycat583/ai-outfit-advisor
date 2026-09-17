# 👔 AI Outfit Advisor

> 面向大学生的智能穿搭决策与衣橱管理助手

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE) 
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Streamlit](https://img.shields.io/badge/streamlit-≥1.28.0-FF4B4B.svg)](https://streamlit.io)

[在线 Demo](https://ai-outfit-advisor.streamlit.app/) | [项目结构说明](docs/PROJECT_STRUCTURE.md)

---

## 功能特性

- **多模态智能识衣**：上传照片自动提取品类、颜色、材质、季节属性
- **RAG 知识库问答**：基于 Chroma 向量检索，覆盖色彩搭配、面试穿搭、洗护保养等领域
- **7 天不重样周计划**：结合实时天气与衣橱库存，生成结构化穿搭方案并避免连续重复
- **多租户数据隔离**：每个用户的衣橱、对话历史、知识库向量空间完全隔离
- **云端持久化存储**：基于 Supabase PostgreSQL 与 Storage，彻底解决容器重启数据丢失问题

## 演示

<img width="960" height="502" alt="面试_2x_small" src="https://github.com/user-attachments/assets/7d04c224-532d-4da5-826c-8f43cbb87d90" />

## 技术栈

- **前端框架**：Streamlit ≥1.28.0
- **Python 版本**：3.11+
- **数据库**：Supabase (PostgreSQL + Storage)
- **向量检索**：Chroma 0.4.24 + DashScope Embeddings (text-embedding-v4)
- **大模型**： 
  - 对话：qwen3-max (通义千问)
  - 视觉：qwen-vl-max
- **外部 API**：和风天气 API（7 天预报，可选）
- **LLM 框架**：LangChain + LangGraph
- **关键依赖约束**：
  - `starlette<1.4`（Streamlit gzip middleware 兼容性）
  - `numpy<2`（Chroma 0.4.x 依赖）
  - `chromadb==0.4.24`（版本固定）

## 快速开始

### 环境要求

- Python 3.11+
- Supabase 账号（免费层可用）
- 阿里云百炼 API Key（必需，用于 Qwen 模型）
- 和风天气 API Key（可选，影响 7 天穿搭计划的天气联动）
- LangSmith API Key（可选，用于 Agent 调用链监控）

### 安装步骤

#### 1. 克隆项目

```bash
git clone https://github.com/sleepycat583/ai-outfit-advisor.git
cd ai-outfit-advisor
pip install -r requirements.txt
```

#### 2. 配置 Supabase

在 [Supabase](https://supabase.com) 创建项目后：

**a. 初始化数据库**

进入 SQL Editor，执行以下 SQL 初始化数据库：

```sql
-- 用户表
CREATE TABLE users (
    id TEXT PRIMARY KEY,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    salt TEXT NOT NULL,
    created_at TEXT,
    profile TEXT DEFAULT '{}'
);

-- 聊天记录表
CREATE TABLE chat_messages (
    session_id TEXT PRIMARY KEY,
    messages TEXT NOT NULL,
    updated_at TEXT
);

-- 衣橱单品表
CREATE TABLE wardrobe_items (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    category TEXT NOT NULL,
    sub_category TEXT DEFAULT '',
    color TEXT DEFAULT '',
    material TEXT DEFAULT '',
    season TEXT DEFAULT '',
    image_path TEXT DEFAULT '',
    created_at TEXT
);

-- 知识库记录表（用于防重和恢复）
CREATE TABLE kb_documents (
    id SERIAL PRIMARY KEY,
    user_id TEXT NOT NULL,
    source TEXT NOT NULL,
    content TEXT NOT NULL,
    md5 TEXT NOT NULL,
    created_at TEXT,
    operator TEXT,
    operator_id TEXT,
    operator_name TEXT,
    source_type TEXT DEFAULT 'user'
);
```

**b. 创建存储桶**

进入 Storage 菜单，创建名为 `wardrobe-images` 的 Bucket 并设为 Public。

**c. 旧版本升级（可选）**

⚠️ 仅在从 V2.3 或更早版本升级时需要：先在 SQL Editor 执行 `migrations/001_kb_uploader_attribution.sql`，再部署新代码。全新部署可跳过此步骤。

#### 3. 配置环境变量

复制 `.env.example` 为 `.env`，填入密钥：

```bash
# 必需配置
DASHSCOPE_API_KEY="sk-xxx"
SUPABASE_URL="https://xxx.supabase.co"
SUPABASE_KEY="eyJxxx"  # 使用 anon key，不要用 service role key

# 可选配置（不配置则相关功能不可用）
QWEATHER_API_KEY="xxx"        # 和风天气：7天穿搭计划的天气联动
LANGCHAIN_API_KEY="xxx"       # LangSmith：Agent 调用链追踪
LANGCHAIN_TRACING_V2="true"
LANGCHAIN_PROJECT="ai-outfit-advisor"
LANGCHAIN_ENDPOINT="https://api.smith.langchain.com"
```

#### 4. 启动服务

```bash
streamlit run app.py
```

首次启动时，终端会提示已自动导入系统预置的穿搭知识库，此时即可体验 RAG 问答功能。

## 项目结构

```
ai-outfit-advisor/
├── app.py                  # Streamlit 主入口
├── config/                 # 配置模块
│   ├── base.py             # 基础配置（模型名称、切分参数等）
│   └── supabase.py         # Supabase 客户端单例
├── src/
│   ├── core/               # 核心逻辑
│   │   ├── rag_agent.py    # RAG Agent 构建与工具调度
│   │   └── prompts.py      # Prompt 模板集中管理
│   ├── services/           # 业务服务层
│   │   ├── user.py         # 用户注册、登录、鉴权
│   │   ├── wardrobe.py     # 衣橱管理（VLM 识衣、CRUD）
│   │   ├── knowledge_base.py  # 知识库构建、seeds 自动导入
│   │   ├── vector_store.py    # 用户隔离的向量检索服务
│   │   └── weather.py         # 和风天气 API 封装
│   ├── repositories/       # 数据持久化
│   │   └── chat_history.py # 聊天历史云端存储
│   ├── ui/                 # 界面组件
│   │   └── pages/          # 问答页、知识库管理页
│   └── utils/              # 工具函数（图片缓存等）
├── seeds/                  # 系统预置知识库（启动时自动导入）
│   ├── 大厂面试穿搭指南.txt
│   ├── 2026春夏色彩搭配与流行趋势.txt
│   ├── 洗涤养护.txt
│   └── ...
├── migrations/             # 数据库迁移脚本（仅旧版本升级需要）
└── requirements.txt
```

详细架构说明见 [docs/PROJECT_STRUCTURE.md](docs/PROJECT_STRUCTURE.md)。

## 部署到 Streamlit Cloud

1. 在 Streamlit Cloud 创建应用，关联 GitHub 仓库
2. 在 Settings → Secrets 填入 TOML 格式配置：

```toml
DASHSCOPE_API_KEY = "xxx"
SUPABASE_URL = "https://xxx.supabase.co"
SUPABASE_KEY = "xxx"  # 使用 anon key

# 可选配置
QWEATHER_API_KEY = "xxx"
LANGCHAIN_API_KEY = "xxx"
LANGCHAIN_TRACING_V2 = "true"
LANGCHAIN_PROJECT = "ai-outfit-advisor"
LANGCHAIN_ENDPOINT = "https://api.smith.langchain.com"
```

3. 修改 `requirements.txt` 后，在应用菜单选择 Reboot app

### 安全提示

- `SUPABASE_KEY` 应使用 Project Settings → API 中的 **anon key**（公开安全），不要用 service role key
- `.env` 文件不要提交到 Git
- 和风天气与 LangSmith 为可选配置，不影响核心功能

## License

[MIT](LICENSE) © 2026 Weibin Zhang
