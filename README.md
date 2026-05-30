👔 AI Outfit Advisor (智能穿搭顾问) V2.4

一个面向大学生群体的智能穿搭决策与衣橱管理助手。本项目在最新版本中完成了全面云原生化升级，基于 Supabase 实现了多租户数据隔离与云端持久化。

融合 Qwen-Max 大模型、多模态视觉大模型 (Qwen-VL)、RAG 本地知识库 (Chroma) 与 Agent 联网决策 (DuckDuckGo)，以“顶尖私人穿搭主理人”人设，提供图片识衣、数字衣橱管理、穿搭知识问答，以及基于天气的 7 天不重样周计划的完整 OOTD 解决方案。

✨ V2.4 核心大版本更新（云原生架构演进）

核心模块

升级亮点说明

☁️ 全量数据上云 (Supabase)

彻底解决 Streamlit Cloud 容器重启导致的数据丢失痛点。用户档案、衣橱单品、聊天记录、知识库 MD5 去重记录全面迁移至 Supabase PostgreSQL；图片资产迁移至 Supabase Storage。

🔐 多租户与数据 100% 隔离

完善的注册/登录系统。每个用户的衣橱数据、对话历史、甚至专属的 Chroma 向量检索空间均通过 user_id 严格隔离，真正实现千人千面。

🌱 种子知识自动导入

新增 seeds/ 目录。系统启动时，自动将预置的“大厂面试穿搭、色彩搭配、洗涤养护”等基础知识库写入向量数据库，开箱即用。

📝 文本极速粘贴入库

知识库管理不仅支持 .txt 文件上传，新增“直接粘贴文本”功能，并结合云端 MD5 校验实现防重复导入。

🌟 核心功能矩阵

Agent 联网决策：动态捕获用户所在城市，自主调用 DuckDuckGo 实时搜索未来天气，并结合 LangChain Callback 输出终端透明日志。

RAG 穿搭知识库：基于 Chroma 向量检索，覆盖洗护、尺码、色彩、面试四大领域，利用系统预设规则将检索结果无缝注入 Prompt。

多模态智能识衣：上传照片，VLM 大模型 (qwen-vl-max) 自动提取：品类、细分类、颜色、面料、适用季节，并结构化输出入库。

状态机周计划：大模型 with_structured_output 结构化输出 7 天穿搭统筹，内置“洗涤与轮换约束规则”，避免连续重复。

🏗️ 系统流程架构
```
[用户鉴权 (app_main)] ──► [注册/登录] ──► [分配隔离沙箱 (user_id)]
                                            │
       ┌────────────────────────────────────┴────────────────────────────────────┐
       ▼                                                                         ▼
[💬 穿搭问答端 (RAG + Agent)]                                            [👗 智能衣橱端]
       │                                                                         │
       ├─► 📅 生成本周穿搭计划                                                   ├─► [上传照片] ─► [VLM 智能识衣]
       │       ├─► 1. 联网查询属地未来天气                                       │
       │       ├─► 2. 检索 Chroma 获取穿搭法则                                   ├─► [手动录入表单]
       │       └─► 3. 约束算法生成 7天 JSON                                      │
       │                                                                         ├─► [CSV 批量导入/导出备份]
       ▼                                                                         ▼
[流式渲染穿搭方案 & 搭配单品卡片]                                        [保存至 Supabase 云端数据库]
                                                                         [图片上传至 Supabase Storage]
```

📂 项目目录结构
```
ai-outfit-advisor/
├── app_main.py                 # 🚀 主入口：全局路由、登录/注册页面、侧边栏管理
├── app_qa.py                   # 穿搭服务：对话流式渲染、Agent 调用、智能衣橱交互
├── app_file_uploader.py        # 知识库管理：支持 TXT 上传与纯文本粘贴、MD5 云端去重
├── rag.py                      # RAG 核心：Agent 构建、天气搜索工具、7天结构化规划
├── user_service.py             # 用户服务：密码哈希加盐验证，接驳 Supabase
├── wardrobe_service.py         # 衣橱服务：VLM 识衣，接驳 Supabase 增删改查与图片上传
├── knowledge_base.py           # 知识库引擎：Chroma 构建、seeds 自动导入、Supabase 恢复
├── vector_store_service.py     # 向量服务：隔离用户的知识库与衣橱语义检索
├── history.py                  # 会话历史：基于 Supabase PostgreSQL 的云端漫游记录
├── supabase_config.py          # ☁️ 云端配置：Supabase 客户端单例与环境秘钥解析
├── prompts.py                  # Prompt 集中营：人设、Agent 约束、输出格式控制
├── config_data.py              # 全局配置：模型名称、切分参数等
├── seeds/                      # 🌱 种子知识库目录（系统启动时自动导入其中的 .txt）
└── .env.example                # 环境变量配置模板

```
🚀 快速部署指南（新手向）

为了保障数据不丢失，本项目现已全面接入 Supabase，请按照以下步骤进行配置：

第一步、拉取代码与安装依赖

首先，克隆项目到本地并安装依赖环境：

git clone [https://github.com/sleepycat583/ai-outfit-advisor.git](https://github.com/sleepycat583/ai-outfit-advisor.git)
cd ai-outfit-advisor
pip install -r requirements.txt


第二步、配置 Supabase 云端数据库（免费）

前往 Supabase 官网 注册并创建一个新项目。

进入 SQL Editor，执行以下建表语句，初始化你的云端数据库：
```
-- 1. 用户表
CREATE TABLE users (
    id TEXT PRIMARY KEY,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    salt TEXT NOT NULL,
    created_at TEXT,
    profile TEXT DEFAULT '{}'
);
```
-- 2. 聊天记录表
CREATE TABLE chat_messages (
    session_id TEXT PRIMARY KEY,
    messages TEXT NOT NULL,
    updated_at TEXT
);
```
-- 3. 衣橱单品表
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
```
-- 4. 知识库记录表 (用于防重和恢复)
CREATE TABLE kb_documents (
    id SERIAL PRIMARY KEY,
    user_id TEXT NOT NULL,
    source TEXT NOT NULL,
    content TEXT NOT NULL,
    md5 TEXT NOT NULL,
    created_at TEXT
);


进入 Storage 菜单，创建一个名为 wardrobe-images 的 Bucket（存储桶），并将其设置为 Public（公开），以便网页端能够正常加载衣橱图片。
```
第三步、配置环境变量

将项目根目录下的 .env.example 复制并重命名为 .env。填入你在阿里云申请的 DashScope 秘钥，以及刚才创建的 Supabase 的连接信息：

# 阿里云百炼大模型 API Key
DASHSCOPE_API_KEY="sk-xxxxxxxxxxxxxxxxxxxxxxxx"

# Supabase 项目 URL 和匿名 API Key (在 Project Settings -> API 中获取)
SUPABASE_URL="[https://xxxxxxxxxxxx.supabase.co](https://xxxxxxxxxxxx.supabase.co)"
SUPABASE_KEY="eyJhbGciOiJIUzI1NiIsInR5c......"
```

第四步、启动服务

环境配置完毕后，通过 Streamlit 启动项目主入口：

streamlit run app_main.py


💡 提示： 首次启动时，终端会提示 [种子导入] 已自动导入 x 份基础穿搭知识，此时你已经可以直接体验 RAG 问答了！

🤝 开发者模式建议

如果你需要重置系统的上下文状态（例如开发调试时卡顿），可以点击侧边栏最下方的 🔄 重置系统与服务 按钮。这会清空当前应用内存状态并重新拉取云端数据，但不会让你退出登录。

📝 迭代日志 (Changelog)

V2.3 架构重构与数据隔离升级 (Current)

多用户系统：新增 UserService 与 SQLite 账号表，支持安全的注册与登录鉴权，实现完美的千人千面与数据隔离。

底层数据库迁移：衣橱数据从 wardrobe.json 整体迁移至专属的 wardrobe.db (SQLite)，通过启用 WAL 模式极大提升了高并发下的读写安全性。

数据流转增强：在衣橱界面新增了 CSV 格式的一键备份（导出）与恢复（导入）功能。

UI 统一重构：剥离原本分散的 app_qa 与 app_file_uploader，通过 app_main.py 统筹全局路由。

V2.2 真正的 AI Agent 架构

Tool Calling 调度：抛弃传统线性对话，基于 LangChain ReAct 框架整合了 DuckDuckGo（联网查天气）和本地知识库检索器。

结构化输出规划：利用大模型原生 with_structured_output 特性，单次并发生成 7 天统筹规划，极大降低 API 耗时。

全生命周期监控：实现自定义 ConsoleLoggingHandler，将 Agent 思考和调用链映射到终端。

V2.1 业务状态机升级

基于真实物理的洗涤状态机：引入细粒度的单品状态流转算法，内搭穿过进入冷却、下装轮换，100% 避免连续重复。

多维上下文动态 Agent：根据用户的具体城市和当前日期，推演未来天气，精准注入 Prompt。

V2.0 多模态与基础框架

多模态识衣入库：集成 Qwen-VL-Max，一键提取品类、材质、颜色等结构化特征。

打字机流式输出：对话界面优化，丝滑的打字机渲染体验。
