👔 AI Outfit Advisor (智能穿搭顾问)

V2.3 - 基于多模态大模型、多用户数据隔离与状态过滤算法的“智能衣橱”系统

一个面向大学生群体的智能穿搭决策与衣橱管理助手。融合 Qwen-Max 大模型、多模态视觉大模型 (Qwen-VL)、RAG 本地知识库 (Chroma) 与 Agent 联网决策 (DuckDuckGo)，以“顶尖私人穿搭主理人”人设，提供多账户隔离、图片识衣、数字衣橱 CRUD 管理，以及基于天气的 7 天不重样周计划的完整 OOTD 解决方案。

✨ 核心亮点

引擎 / 模块

核心能力

🔐 多账户与数据隔离

内置完备的注册/登录系统，基于 SQLite (users.db) 与加盐哈希保障密码安全。每个用户拥有独立的穿搭档案与衣橱数据库，实现数据100%隔离。

🧠 Agent 联网决策

动态捕获用户的所在城市，自主调用 DuckDuckGo 实时搜索未来天气，结合 LangChain 全生命周期 Callback 系统实现终端透明日志。

📚 RAG 本地知识库

基于 Chroma 向量数据库，覆盖洗护养护、尺码推荐、颜色搭配、面试等四大领域，支持 .txt 文档一键上传与 MD5 去重。

📸 多模态智能识衣

支持上传衣服照片，利用 VLM 大模型 (qwen-vl-max) 自动提取单品品类、细分颜色、面料材质、适用季节并完成结构化输出入库。

👗 状态过滤周计划

引入“洗涤限制状态机”算法，利用大模型原生 with_structured_output 特性，单次并发生成 7 天统筹规划，按天循环过滤已消耗单品，避免推荐连续重复。

💾 SQLite 持久化存储

抛弃传统的 JSON 文件，升级为 SQLite 本地数据库，通过开启 WAL 模式与防锁重试机制，完美解决高并发下衣橱数据的读写冲突。

🔄 CSV 数据管理

支持将个人衣橱一键导出为标准的 CSV 备份文件，并提供“追加”或“覆盖”双模式的 CSV 批量导入功能。

🏗️ 系统流程架构
```
[用户鉴权 (app_main)] ──► [注册/登录] ──► [进入专属空间 (user_id)]
                                            │
       ┌────────────────────────────────────┴────────────────────────────────────┐
       ▼                                                                         ▼
[💬 穿搭问答端 (RAG + Agent)]                                            [👗 智能衣橱端]
       │                                                                         │
       ├─► 📅 生成本周穿搭计划                                                   ├─► [上传照片] ─► [VLM 智能识衣]
       │       ├─► 1. 联网查询属地本周天气                                       │
       │       ├─► 2. 检索 Chroma 搭配/修饰知识库                                ├─► [手动录入表单]
       │       └─► 3. 7天状态过滤循环算法                                        │
       │                                                                         ├─► [CSV 批量导入/导出备份]
       ▼                                                                         ▼
[流式渲染穿搭方案 & 搭配单品卡片]                                        [保存至 SQLite (wardrobe.db)]

```
📂 项目结构
```
ai-outfit-advisor/
├── app_main.py                 # 🚀 主入口：鉴权路由（登录/注册）及页面分发
├── app_qa.py                   # 穿搭服务：多模态穿搭问答 & 智能衣橱管理（Streamlit UI）
├── app_file_uploader.py        # 知识库管理：.txt 文档上传与 Chroma 向量化
├── user_service.py             # 用户服务：账号注册、登录校验、密码哈希加盐与档案存储
├── wardrobe_service.py         # 衣橱服务：VLM 识衣、SQLite CRUD、CSV 导入导出
├── rag.py                      # RAG 核心：Agent 构建、天气搜索工具、7天结构化规划算法
├── history.py                  # 会话历史：并发安全的文件锁持久化读写
├── vector_store_service.py     # 向量检索服务封装 (支持独立衣橱的语义检索)
├── knowledge_base.py           # 知识库引擎：Chroma 存储 + MD5 去重
├── prompts.py                  # 集中管理系统级 Prompt (RAG, Weekly Plan, VLM 等)
├── config_data.py              # 全局配置：模型名称、切分参数、数据库路径等
├── generate_pptx.py            # 工具脚本：一键生成项目答辩 PPTX
├── requirements.txt            # Python 依赖清单
├── .env.example                # 环境变量配置模板
├── chat_history/               # 存放各用户的多轮对话历史 (JSON 文件锁管理)
├── data/
│   ├── users.db                # [核心] 用户鉴权与档案主数据库 (SQLite)
│   ├── chroma/                 # Chroma 向量库持久化目录 (包含公共知识库与个人衣橱索引)
│   └── {user_id}/              # 按照 user_id 隔离的用户私人目录
│       ├── wardrobe.db         # 用户个人专属衣橱数据库 (SQLite)
│       └── wardrobe_images/    # 用户上传的衣服压缩图片存储目录
└── *.txt                       # 穿搭知识库原始语料（如洗涤养护、面试指南等）
```

📦 快速开始

第一步、安装依赖

git clone [https://github.com/sleepycat583/ai-outfit-advisor.git](https://github.com/sleepycat583/ai-outfit-advisor.git)
cd ai-outfit-advisor
pip install -r requirements.txt


第二步、配置环境变量
将项目根目录下的 .env.example 复制并重命名为 .env，并填入你的模型 API 密钥：

DASHSCOPE_API_KEY="your-api-key-here"


第三步、启动服务

# 请必须通过主入口文件启动，以确保激活登录系统
streamlit run app_main.py


(注意：知识库管理功能已集成在登录后的侧边栏导航中，无需单独启动)

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
