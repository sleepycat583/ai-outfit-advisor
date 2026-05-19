# 👗 AI 智能穿搭顾问 · 小衣 (AI Outfit Advisor)

> **V1.2** — 基于 LangChain Agent + RAG 双引擎的个性化穿搭推荐系统

一个面向大学生群体的智能穿搭决策助手。融合**大语言模型 (Qwen3-max)**、**RAG 本地知识库 (Chroma)** 与 **Agent 联网搜索 (DuckDuckGo)**，以"顶尖私人穿搭主理人"人设，为不同性别、风格、体型的用户提供面试、约会、早八等高频场景的 OOTD 解决方案。

---

## ✨ 核心亮点

| 引擎 | 能力 |
|------|------|
| 🧠 **Agent 联网决策** | 自主调用 DuckDuckGo 实时搜索天气、流行趋势，结合 LangChain 全生命周期 Callback 系统实现终端透明日志 |
| 📚 **RAG 本地知识库** | 基于 Chroma 向量数据库，覆盖洗护养护、尺码推荐、颜色搭配三大领域，支持 `.txt` 文档一键上传与 MD5 去重 |
| 🎯 **千人千面画像** | 侧边栏"穿搭档案"支持性别、偏好风格、身高体重动态注入 System Prompt，实现真正的个性化生成 |
| 💬 **专业人设** | "小衣"以时尚主理人口吻输出：场景破冰 → OOTD 推荐 → 私藏贴士 → 专属签名，排版清晰有呼吸感 |
| 🧩 **规则稳定层** | 在模型生成前注入场景/预算/体型硬约束，并在输出后进行结构化兜底，提升一致性与可解释性 |
| 🔁 **反馈学习闭环** | 支持对回答进行点赞/点踩/收藏，本地持久化到 `data/*.jsonl` 便于后续迭代优化 |
| 📊 **量化评测埋点** | 自动记录时延、成功率、输入长度、场景/预算等关键指标，方便做 A/B 对比与答辩展示 |
| 🛡️ **工程兜底能力** | 请求限流 + 失败降级响应，提升演示稳定性与线上容错能力 |

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

### 启动

```bash
# 主应用 — AI 穿搭顾问问答
streamlit run app_qa.py

# 知识库管理 — 上传 .txt 素材
streamlit run app_file_uploader.py
```

---

## 📂 项目结构

```
ai-outfit-advisor/
├── app_qa.py                   # 主入口：AI 穿搭问答（Streamlit UI）
├── app_file_uploader.py        # 知识库管理：.txt 文档上传与向量化
├── rag.py                      # RAG 核心：Agent + Prompt + 链构建
├── history.py                  # 会话历史：文件持久化读写
├── vector_store_service.py     # 向量检索服务封装
├── recommendation_rules.py     # 规则层：硬约束注入 + 输出稳定化
├── telemetry.py                # 指标与反馈日志写入工具
├── knowledge_base.py           # 知识库引擎：Chroma + MD5 去重
├── config_data.py              # 集中配置：模型、切分参数、路径
├── requirements.txt            # Python 依赖清单
├── chat_history/               # 用户会话历史（JSON）
├── data/chroma/                # Chroma 向量库持久化目录
├── data/metrics.jsonl          # 推理时延与成功率埋点（运行后生成）
├── data/feedback.jsonl         # 用户反馈日志（运行后生成）
├── data/favorites.jsonl        # 收藏日志（运行后生成）
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

### V1.3

- **可解释约束增强** — 新增场景与预算档位输入，在请求中注入硬约束，推荐理由更可解释
- **稳定性增强** — 输出结构兜底（场景感知 / OOTD / 私藏贴士 / 专属签名）+ 异常降级回复
- **反馈闭环** — 新增“👍/👎/⭐收藏”交互，落地本地日志用于后续训练与规则优化
- **评测埋点** — 自动记录 `latency_ms`、成功率、场景和预算标签，支持比赛答辩量化展示
- **限流保护** — 默认 60 秒内最多 6 次请求，降低异常峰值风险

---

## 📈 评测建议（比赛可直接使用）

- **稳定性**：统计 `data/metrics.jsonl` 中成功率（`success=true` 占比）与 P95 延迟（`latency_ms`）
- **用户满意度**：统计 `data/feedback.jsonl` 中正向反馈占比（`feedback=positive`）
- **场景覆盖率**：按 `scene` 聚合，观察各场景请求量与反馈质量
- **预算一致性**：检查预算约束下推荐是否命中预算档位，结合人工抽样评分

---

## 🔐 隐私与合规

- **数据最小化**：仅记录完成推荐所需字段（会话ID、场景、预算、反馈结果、时延指标）
- **本地持久化**：反馈与指标默认落盘到本地 `data/*.jsonl`，不主动上传第三方平台
- **敏感信息建议**：避免在输入中提供真实身份证号、住址、联系方式等敏感个人信息

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
