# StyleAgent RAG 系统优化规划说明书

> 文档类型：开发与验证基线
>
> 适用项目：StyleAgent 衣橱推荐系统（当前仓库目录：`d:\ai-outfit-advisor`）
>
> 编写依据：当前 `main` 工作树中的源码、配置、测试脚本和数据库迁移文件
>
> 当前状态：规划阶段，本文档不代表其中所有目标能力已经实现

## 1. 文档目的

本文档用于指导后续 RAG（Retrieval-Augmented Generation，检索增强生成）开发、测试和验收，主要解决以下问题：

1. 明确当前系统真实的检索链路，避免把历史方案或文档描述误认为线上实现。
2. 明确衣橱检索、知识库检索和 LangGraph Agent 之间的边界。
3. 按优先级拆分正确性、安全性、性能和召回质量问题。
4. 为每个阶段定义实现范围、验证指标、风险和回滚方式。
5. 为后续 Chroma 到 Supabase pgvector 的可选迁移保留可验证的决策依据。

## 2. 事实基线

### 2.1 当前技术栈

当前代码实际使用的组件如下：

| 层级 | 当前实现 |
|---|---|
| 页面层 | Streamlit，入口为 `app.py` |
| Agent 编排 | `langgraph.prebuilt.create_react_agent` |
| 对话模型 | `ChatTongyi`，配置名为 `qwen3-max` |
| Embedding | `DashScopeEmbeddings`，配置模型为 `text-embedding-v4` |
| 向量库 | Chroma 本地持久化 |
| 业务数据库 | Supabase PostgreSQL |
| 图片存储 | Supabase Storage |
| 衣橱原始数据 | `wardrobe_items` |
| 知识库原始数据 | `kb_documents` |
| 对话历史 | `chat_messages` |

当前 `main` 分支没有可执行的 Supabase pgvector 检索实现，也没有显式的 HNSW 或 IVFFlat 配置。Git 历史中出现过 pgvector 相关文件，但这些文件不在当前工作树中，后续设计不能直接把它们当作线上能力。

当前仓库也没有 Chrome Extension 的 `manifest.json`、content script 或 background service worker。本文中的“Chrome 技术栈”不作为当前系统事实；如果后续确实需要浏览器扩展，需要另立集成设计。

### 2.2 关键源码位置

| 能力 | 文件 | 当前职责 |
|---|---|---|
| Agent 与工具编排 | `src/core/rag_agent.py` | 初始化模型、构造工具、驱动 LangGraph、读写历史 |
| 知识库向量服务 | `src/services/vector_store.py` | 创建支持配置 k 值的 Chroma retriever |
| 衣橱向量服务 | `src/services/vector_store.py` | 衣物向量写入、重建和相似度检索 |
| 知识库导入恢复 | `src/services/knowledge_base.py` | TXT 切分、种子导入、Supabase 恢复、MD5 去重 |
| 衣橱 CRUD | `src/services/wardrobe.py` | Supabase 数据与衣橱向量同步 |
| 问答页面 | `src/ui/pages/qa_page.py` | 初始化服务、提交用户问题、消费事件流、渲染卡片 |
| 提示词 | `src/core/prompts.py` | 衣橱优先、工具调用和回答格式约束 |
| 聊天历史 | `src/repositories/chat_history.py` | Supabase 持久化、近期消息和摘要 |
| 参数配置 | `config/base.py` | embedding 模型、chunk、Top-K 等配置 |

## 3. 当前 RAG 数据流

### 3.1 初始化链路

```text
Streamlit 用户进入问答页
        |
        v
qa_page.py 初始化 DashScope Embeddings
        |
        +--> VectorWardrobeService(user_id)
        |       |
        |       +--> 打开当前用户的本地 Chroma wardrobe collection
        |       +--> collection 为空时查询 Supabase wardrobe_items
        |       +--> 为衣物生成 embedding 并写入 Chroma
        |
        +--> RagService(user_id, vector_wardrobe)
                |
                +--> 初始化 WeatherService
                +--> 初始化 VectorStoreService
                |       |
                |       +--> 打开当前用户的知识库 Chroma collection
                |
                +--> 初始化 ChatTongyi
                +--> create_react_agent(model, tools)
```

注意：`KnowledgeBaseService` 才负责种子知识和 Supabase `kb_documents` 的恢复；问答页直接初始化 `VectorStoreService` 时，不会自动执行 `KnowledgeBaseService._rebuild_index()`。因此新容器中直接进入问答页时，知识库可能为空。

### 3.2 普通问答链路

```text
用户输入
  + 用户画像：性别、风格、体型、城市
  + 当前日期
  + 当前会话历史
        |
        v
qa_page.py 调用 RagService.stream_events()
        |
        v
RagService._prepare_inputs()
        |
        v
读取 Supabase chat_messages 的摘要和近期消息
        |
        v
组装 LangGraph graph input
        |
        v
create_react_agent 执行模型节点
        |
        +--> knowledge_base_search
        |       |
        |       +--> DashScope 查询 embedding
        |       +--> Chroma similarity search，固定 k=2
        |       +--> 返回知识库 Document 内容
        |
        +--> wardrobe_search
        |       |
        |       +--> _estimate_topk() 计算 k=5/8/12
        |       +--> Chroma similarity_search(query, k)
        |       +--> 过滤或修复缺少 item id 的旧文档
        |       +--> 复杂查询可能调用 LLM 压缩
        |       +--> 返回带真实 id 的衣物文本
        |
        +--> weather_search（仅天气服务可用且模型决定调用时）
        |
        v
Agent 根据工具结果生成 AIMessage
        |
        v
写入 chat_messages，必要时更新摘要
        |
        v
Streamlit 清理 <item>id</item> 标签并渲染衣物卡片
```

### 3.3 衣橱写入链路

```text
用户上传图片或手工填写衣物
        |
        v
VLM 提取 category/sub_category/color/material/season
        |
        v
Supabase wardrobe_items 写入或更新
        |
        +--> VectorWardrobeService.add_items/update_items
                |
                +--> _item_to_text()
                +--> DashScope text-embedding-v4
                +--> Chroma 写入
```

当前衣橱向量文本格式为：

```text
- id:{item_id} 类别:{category}/{sub_category} 颜色:{color} 材质:{material} 适季:{season}
```

UUID 既被放入 embedding 输入文本，又被作为 metadata/Chroma id 使用。后续应从 embedding 文本中去除 UUID，保留它作为稳定主键。

## 4. 当前问题清单

### 4.1 正确性问题

#### R-001：问答页首次启动可能没有知识库内容

`KnowledgeBaseService` 在初始化时负责种子导入和 Supabase 恢复，但问答链路使用的 `VectorStoreService` 不会调用该恢复流程。容器重启、Streamlit Cloud 新实例或本地清空 Chroma 后，`knowledge_base_search` 可能返回空结果。

**影响：** 通用穿搭问题退化为模型自由生成，知识库的事实约束失效。

#### R-002：衣橱覆盖导入可能遗留旧向量 ✅ 已解决

**问题**：`WardrobeService.import_from_csv(mode=”replace”)` 会删除 Supabase 当前用户数据并批量插入新数据，但只更新新数据对应的向量，没有清理 Chroma 中已经不存在的旧 item id。

**影响：** Agent 可能推荐已经删除的衣物，前端无法渲染对应卡片。

**解决方案（2026-09-19）：**
- 在 `import_from_csv(mode=”replace”)` 中添加 Chroma collection 完全清理逻辑
- 先调用 `vector_service.delete_collection()` 删除旧 collection
- 再调用 `vector_service.create_collection()` 重建空 collection
- 最后批量插入新数据的向量
- 确保 Supabase 和 Chroma 数据完全同步

#### R-003：Top-K 规则、测试和实际行为不一致 ✅ 已解决

**问题**：当前动态 Top-K 规则按查询复杂度返回 5、8、12，但已有阶段测试文档把”黑色裤子”描述为 `k=8`，实际短查询逻辑可能返回 `k=5`。此外，复杂查询召回 12 条后又可能截断为前 6 条。

**影响：** 测试结论不能稳定代表真实运行行为，召回数量也不等于最终给模型的候选数量。

**解决方案（2026-09-19）：**
1. **提取独立函数**：将 `_estimate_topk()` 逻辑提取为模块级 `estimate_topk_for_query()`
2. **测试同步**：修改 `test_phase1_topk_logic.py` 直接导入并测试该函数，消除逻辑重复
3. **期望值修正**：更新测试期望值，正确反映”字数优先”规则：
   - ≤5字 → k=5（即使有2维度）
   - 6-10字且2维度 → k=8
   - 3+维度或场景或≥11字 → k=12
4. **文档更新**：修正 `phase1_test_report.md` 中关于”黑色裤子”的描述

### 4.2 检索质量问题

#### R-004：衣橱字段被完全交给 embedding 判断

颜色、类别、季节是结构化枚举字段，但当前只构造成一段文本后做向量相似度，没有精确过滤、关键词匹配或分数阈值。

**影响：** “黑色裤子”“适合面试的外套”等查询可能召回语义相近但类别不准确的单品。

#### R-005：知识库固定 `k=2` 且没有相似度阈值 ✅ 已完成并通过真实数据复验

~~配置中的 `similarity_threshold=2` 实际被当作返回数量，而不是真正的相似度阈值。~~

**影响：** ~~宽泛问题证据不足，低相关结果也可能被注入 Prompt，模型没有”证据不足”的明确边界。~~

**解决方案（已实施）：**
1. **配置重命名和新增参数**（`config/base.py`）：
   - `similarity_threshold` → `knowledge_retrieval_k`（消除误导）
   - `knowledge_min_similarity = 0.50`（基于当前真实知识库评测集的最低相似度阈值）
   - `knowledge_strong_similarity = 0.60`（多来源证据充分阈值）
   - 新增 `enable_knowledge_dynamic_k = True`（动态 k 开关）
   - 新增 `enable_knowledge_similarity_filter = True`（过滤开关）

2. **动态 k 值估算**（`src/core/rag_agent.py`）：
   - 新增 `estimate_knowledge_k(query)` 函数
   - 具体操作问题（洗涤、保养）：k=2
   - 搭配类问题（颜色、组合）：k=4
   - 宽泛概念问题（原则、注意事项）：k=5
   - 默认中等值：k=3

3. **相似度过滤**（`src/core/rag_agent.py`）：
   - 新增 `_knowledge_base_search(query)` 方法替代 `create_retriever_tool`
   - 使用 `similarity_search_with_score` 获取相似度分数
   - 根据 Chroma Collection 的实际距离类型转换分数：`cosine: 1-distance`，`l2: 1-distance/2`
   - 过滤低于 `knowledge_min_similarity` 的结果

4. **证据不足判断**：
   - 无结果时明确返回”知识库中没有相关内容”
   - 仅 1 条且相似度 <0.75 时标注”证据有限”
   - Agent 可基于此判断”证据不足”状态

5. **工具描述优化**：
   - 明确知识库适用场景（洗涤、尺码、配色、禁忌）
   - 明确不适用场景（衣橱查询、天气、通用聊天）
   - 在描述中说明”如果无相关内容会明确告知”

**验证：**
- ✅ 单元测试覆盖 4 类查询的动态 k 值逻辑
- ✅ 配置项验证通过（值合理性检查）
- ✅ 函数签名和导入验证通过
- ✅ 测试套件：`tests/test_rag_r005_optimization.py`（5/5 通过）

**效果预期：**
- 具体问题检索更精准（k=2 减少噪音）
- 宽泛问题证据更充分（k=5 增加覆盖）
- 低相关文档被过滤（相似度阈值 0.65）
- Agent 可识别”证据不足”状态，明确告知用户

#### R-006：知识库 chunk 没有 overlap 和结构元数据

当前 `chunk_size=800`、`chunk_overlap=0`，没有保存标题、章节、chunk 顺序和文档版本。

**影响：** 规则型知识跨 chunk 时容易丢失上下文，回答也难以解释来源。

### 4.3 性能问题

#### R-007：本地 Chroma 不适合作为多实例云部署的唯一向量层

Chroma 数据位于本地文件系统，Streamlit Cloud 容器重启后依赖从 Supabase 重新生成 embedding。该过程是同步的，衣物和知识文档数量增加后会拉长首个请求延迟。

#### R-008：每个用户重复构建相同的种子知识向量

知识库 collection 按用户隔离，种子文档也被重复写入每个用户的 collection。用户数增加时，embedding 和存储成本线性重复。

#### R-009：聊天历史写入和摘要可能阻塞最终答案

`stream_events()` 在发出最终 answer 前执行聊天历史写入和可能的摘要模型调用。已有性能输出显示摘要调用可能达到秒级甚至十秒级。

### 4.4 安全和隔离问题

#### R-010：仓库没有发现 Supabase RLS 配置

当前代码依赖 `.eq("user_id", self.user_id)` 进行应用层过滤，未发现 `auth.uid()`、`CREATE POLICY` 或 `ENABLE ROW LEVEL SECURITY`。自定义用户登录和 Supabase anon key 不能自动提供数据库级租户隔离。

#### R-011：部分修改/删除查询缺少用户条件

例如衣橱删除按 `id` 删除，没有同时 `.eq("user_id", self.user_id)`。在没有 RLS 的情况下，这类接口边界风险更高。

### 4.5 工程验证问题

#### R-012：当前测试不能作为稳定 pytest 基线

测试文件中对 `sys.stdout` 的重新包装会破坏 pytest 捕获，当前执行 pytest 收集时出现 `ValueError: I/O operation on closed file`，并且没有稳定收集到测试用例。

#### R-013：没有真实检索质量评测集

目前主要验证 Top-K 估算、压缩触发和理论 token 节省，没有 Recall@K、Precision@K、MRR、空结果率、错误 item id 率和端到端延迟分位数。

## 5. 目标架构

### 5.1 目标检索分层

```text
用户问题
   |
   v
Query Understanding
   |
   +--> 结构化条件：类别、颜色、季节、用户 id、场景
   +--> 语义查询：原始问题 + 必要上下文
   |
   v
候选集生成
   |
   +--> 衣橱：结构化过滤优先，再做语义排序
   +--> 知识库：全局种子库 + 用户私有库并行召回
   |
   v
候选合并与重排
   |
   +--> 去重
   +--> 分数阈值
   +--> 业务约束校验
   +--> 保留真实 item_id/source/chunk 元数据
   |
   v
Agent 状态
   |
   +--> retrieval_context
   +--> retrieved_wardrobe_ids
   +--> retrieved_sources
   +--> tool_call_count
   +--> answer
   |
   v
回答生成、卡片渲染、异步历史持久化
```

### 5.2 LangGraph 目标状态

当前使用 `create_react_agent`，后续不立即重写全部 Agent，而是先定义统一状态，逐步将高确定性的检索流程显式化。

建议状态字段：

```python
class OutfitAgentState(TypedDict, total=False):
    user_id: str
    input: str
    profile: dict
    history: list
    query_constraints: dict
    wardrobe_candidates: list[dict]
    knowledge_candidates: list[dict]
    weather_context: dict | None
    retrieved_item_ids: list[str]
    retrieved_sources: list[dict]
    tool_call_count: int
    answer: str
    errors: list[str]
```

建议目标节点：

```text
START
  ↓
prepare_context
  ↓
classify_query
  ├── wardrobe_retrieve
  ├── knowledge_retrieve
  └── weather_retrieve（仅天气相关）
  ↓
validate_retrieval
  ↓
generate_answer
  ↓
persist_history_async
  ↓
END
```

第一阶段不要求立刻实现完整 `StateGraph`。先保留 `create_react_agent`，通过统一检索服务和事件指标验证召回质量，再决定哪些节点值得显式图化。

## 6. 分阶段实施计划

### Phase 0：建立基线和可观测性

**目标：** 在修改检索策略前，先保证测试可运行、行为可测量。

**工作项：**

1. 修复 pytest 收集问题，禁止测试模块替换全局 stdout/stderr。
2. 将 `_estimate_topk()` 的测试改为直接调用生产实现。
3. 增加统一检索日志字段：
   - `request_id`
   - `user_id_hash`
   - `retriever`
   - `query_length`
   - `k_requested`
   - `k_returned`
   - `embedding_ms`
   - `search_ms`
   - `rerank_ms`
   - `total_ms`
4. 建立 20-50 条人工标注查询集，覆盖颜色、类别、季节、场景、洗护和尺码。
5. 记录当前 Chroma 结果作为 baseline，不改变业务行为。

**验收标准：**

- `pytest --collect-only` 能稳定收集测试。
- 每条检索请求能输出结构化延迟和召回数量。
- 每条评测查询有人工标注的相关 item/source。

**收益：** 高。

**成本：** 低，约 0.5-2 天。

**风险：** 日志可能包含用户原始问题和敏感信息，必须默认脱敏或只记录 hash/长度。

### Phase 1：修复初始化、同步和安全边界

**目标：** 先修正确性和租户隔离，再优化召回模型。

**工作项：**

1. 抽取统一的 `ensure_knowledge_index_ready()`，问答页和知识库页共用。
2. 首次发现向量库为空时，执行种子导入和用户文档恢复。
3. 给衣橱覆盖导入增加旧 item id 清理。
4. 增加 Chroma 与 Supabase 的 item id 差集校验。
5. 所有衣橱更新和删除查询同时限制 `user_id`。
6. 设计 Supabase Auth 与现有自定义登录的迁移方案。
7. 为 `wardrobe_items`、`kb_documents`、`chat_messages` 编写并测试 RLS policy。

**验收标准：**

- 新容器直接进入问答页时，知识库能检索种子文档。
- 删除或覆盖导入后，旧 item id 不再被召回。
- 使用第二个用户身份无法读取、修改或删除第一个用户数据。
- RLS 失败时应用能给出明确错误，而不是静默返回空结果。

**收益：** 极高，解决数据正确性和安全问题。

**成本：** 中等，约 2-5 天；Auth/RLS 迁移可能更长。

**风险：** 启用 RLS 后旧 anon key 查询可能全部失败，必须先在测试项目完成迁移演练。

### Phase 2：衣橱结构化检索

**目标：** 让衣橱检索充分利用业务字段，而不是完全依赖 embedding。

**工作项：**

1. 从用户问题提取颜色、类别、季节等有限枚举条件。
2. 先按 `user_id` 和结构化条件生成候选集。
3. 对候选集做向量排序，而不是对所有衣物直接做语义搜索。
4. embedding 文本去除 UUID。
5. 返回结构化对象，不把 item id 仅编码在自然语言文本中：

```json
{
  "item_id": "真实 UUID",
  "category": "下装",
  "sub_category": "直筒裤",
  "color": "黑色",
  "material": "棉",
  "season": ["春", "秋"],
  "score": 0.82
}
```

6. 继续兼容当前 `<item>id</item>` 输出，避免一次性改动前端渲染协议。

**验收标准：**

- 结构化条件命中率高于当前 baseline。
- `黑色裤子` 的 Top-K 中错误类别比例下降。
- 所有输出 item id 都能在当前用户衣橱中找到。
- Recall@5、Precision@5 和 MRR 均与 baseline 对比记录。

**收益：** 高，直接改善推荐相关性。

**成本：** 中等，约 2-4 天。

**风险：** 中文同义词和 VLM 标注不一致会造成过滤过严。初版应允许条件解析失败时回退到语义检索。

### Phase 3：知识库召回优化

**目标：** 提高知识库证据完整性，减少低相关内容注入。

**工作项：**

1. `chunk_overlap` 从 0 调整为 80-120 字，具体值由评测集决定。
2. 保存 `source/title/section/chunk_index/document_version`。
3. 将 `similarity_threshold` 重命名为 `retrieval_k`，避免语义误导。
4. 增加最小相似度阈值或“无足够证据”状态。
5. 根据查询类型动态选择 `k=3-6`。
6. 对相邻重复 chunk 做去重或 MMR（最大边际相关性）处理。
7. 将来源元数据传入 Agent 状态，必要时在回答中保留可追溯来源。

**验收标准：**

- 知识库问题的 Recall@K 高于 baseline。
- 无相关文档的查询不会强行注入低分内容。
- 答案中的关键规则可以追溯到 source 和 chunk。
- 文档重建后 chunk 数、embedding 成本和延迟有记录。

**收益：** 中到高。

**成本：** 中等，约 2-4 天。

**风险：** overlap 会增加向量数量和 embedding 成本，必须结合实际知识库规模评估。

### Phase 4：全局种子库与用户私有库拆分

**目标：** 避免每个用户重复构建相同的种子 embedding。

**目标数据布局：**

```text
kb_seed_global
kb_user_{user_id}
```

检索时并行查询两个库，统一合并、去重、排序。种子文档通过版本号更新，用户文档只影响自己的 collection。

**验收标准：**

- 新用户不再重复生成全部种子 embedding。
- 种子版本升级能触发可控重建。
- 用户删除操作不会影响全局种子库。
- 全局和私有知识来源在结果中可区分。

**收益：** 用户规模增长后的成本和启动延迟显著下降。

**成本：** 中等，约 2-4 天。

**风险：** 需要迁移现有用户 collection 和 `kb_documents` 元数据，必须保留回滚版本。

### Phase 5：回答链路性能和 LangGraph 状态治理

**目标：** 减少用户感知延迟，并提高 Agent 收敛性。

**工作项：**

1. 最终答案生成后立即向 UI 发出 answer 事件。
2. 聊天历史写入改为异步任务或 outbox（待处理队列表）。
3. 摘要生成移出主请求，按低频策略执行。
4. 增加最大工具调用次数和每节点超时。
5. 统计每轮 Agent 的工具调用序列。
6. 在确定性较高的检索流程稳定后，再将检索节点迁移到显式 `StateGraph`。

**验收标准：**

- answer 首字节时间和完整回答时间分别统计。
- 历史写入故障不阻塞回答显示。
- 单轮工具调用超过阈值时能够安全终止并返回降级答案。
- 长对话中上下文长度稳定，不随原始历史无限增长。

**收益：** 高，主要改善用户体验和线上稳定性。

**成本：** 中等，约 2-5 天。

**风险：** 异步持久化可能造成历史短暂延迟或丢失，需要重试、幂等键和失败告警。

### Phase 6：评估是否迁移 Supabase pgvector

**目标：** 只有当数据规模、部署稳定性或多实例需求证明必要时才迁移。

**迁移前置条件：**

1. 已有真实检索评测集和 Chroma baseline。
2. 已确认 embedding 维度、模型版本和费用。
3. 已完成 Supabase Auth/RLS 设计。
4. 已完成 Chroma 与目标库的离线结果对比。
5. 已有双写、回填、校验和回滚方案。

**索引选择原则：**

- 当前衣橱单用户数据量较小时，结构化过滤和精确排序可能比 ANN 更重要。
- 需要 ANN 且衣物频繁增删改时，优先评估 HNSW。
- 知识库规模大、批量导入明显、可以接受训练和参数调优时，再评估 IVFFlat。
- 不根据“索引名称”做选择，必须用 Recall@K、延迟和资源消耗实测决定。

**建议的 pgvector 数据字段：**

```text
id
user_id
source_type
content
metadata jsonb
embedding vector(N)
embedding_model
content_hash
schema_version
created_at
updated_at
```

**验收标准：**

- pgvector 结果与 Chroma baseline 的 Recall@K 不下降，或下降幅度有明确业务接受标准。
- p50/p95 检索延迟、embedding 成本和存储成本均有对比。
- RLS 条件下仍能获得足够召回，必要时使用 over-fetch 后过滤。
- 可以通过配置切换回 Chroma。

**收益：** 中到高，取决于实际数据规模和部署方式。

**成本：** 高，约 1-2 周。

**风险：** 迁移期间双写不一致、RLS 与 ANN 过滤导致召回不足、数据库索引维护成本增加。

## 7. 验证方案

### 7.1 测试分层

#### 单元测试

不访问网络，验证：

- 查询条件解析；
- Top-K 规则；
- item id 提取和去重；
- chunk 切分和元数据生成；
- Chroma/pgvector 结果格式归一化；
- 用户条件注入；
- RLS RPC 参数构造。

#### 服务级测试

使用 fake embedding、fake vector store 和 fake Supabase client，验证：

- 空知识库自动恢复；
- 衣橱新增、更新、删除、覆盖导入后的向量同步；
- 用户 A 无法读取用户 B 的候选；
- 查询失败时回退路径；
- 超时和空结果提示。

#### 集成测试

使用测试 Supabase 项目和真实 embedding API，验证：

- 真实中文查询召回；
- 迁移前后结果一致性；
- RLS policy；
- Streamlit 问答主链路；
- 容器重启后的索引恢复。

#### 评测测试

每次检索策略修改都运行固定数据集，记录：

| 指标 | 含义 |
|---|---|
| Recall@K | 相关结果是否被召回 |
| Precision@K | 返回结果中有多少是真相关 |
| MRR | 第一个相关结果出现的位置 |
| Empty rate | 无结果或无有效证据的比例 |
| Invalid item id rate | 返回不存在衣物 ID 的比例 |
| p50/p95 latency | 检索延迟分布 |
| Answer grounded rate | 回答是否使用了有效检索证据 |

### 7.2 最小评测集

衣橱查询至少包含：

```text
黑色裤子
春季外套
适合面试的正式穿搭
白色内搭
适合雨天的鞋
我不想穿裙子，推荐下装
有没有适合夏天的棉质衣服
```

知识库查询至少包含：

```text
羊毛衫怎么洗
面试穿搭有哪些禁忌
黑色和米色怎么搭配
尺码偏小应该怎么选
没有相关知识时的未知问题
```

每条查询需要人工标注：

- 相关衣物 ID 或知识来源；
- 不应召回的结果；
- 是否必须调用天气；
- 是否允许建议购入。

## 8. 发布、灰度和回滚

### 8.1 配置开关

后续检索改造应通过配置开关控制，建议至少保留：

```text
RAG_RETRIEVER_BACKEND=chroma
RAG_WARDROBE_MODE=semantic
RAG_KNOWLEDGE_MODE=private_only
RAG_ENABLE_HYBRID=false
RAG_ENABLE_ASYNC_HISTORY=false
```

实际命名可按照项目现有配置风格调整，但必须支持不改代码切换旧路径。

### 8.2 灰度顺序

```text
单元测试
  ↓
测试用户
  ↓
单用户灰度
  ↓
小比例用户
  ↓
全量切换
```

每一步都需要比较：

- 检索质量；
- 延迟；
- 空结果率；
- 错误 item id 率；
- Supabase 请求错误；
- embedding 调用量和费用。

### 8.3 回滚条件

出现以下任一情况时回滚到旧 retriever：

1. 有效 item id 错误率上升；
2. Recall@K 明显下降；
3. p95 延迟超过当前 baseline 的 1.5 倍；
4. 出现跨用户数据访问；
5. RLS 导致正常用户无法读取自己的数据；
6. 向量双写出现无法自动修复的不一致。

## 9. 当前阶段结论

当前最优先的开发顺序不是立即选择 HNSW 或 IVFFlat，而是：

```text
1. 建立可运行的测试和检索评测基线
2. 修复知识库初始化为空的问题
3. 修复衣橱向量残留和用户隔离问题
4. 采用结构化过滤 + 语义排序提升衣橱召回
5. 优化知识库 chunk、k 值和证据阈值
6. 将历史写入和摘要移出回答主路径
7. 根据真实数据决定是否迁移 Supabase pgvector
```

完成前四项后，系统才具备比较 HNSW/IVFFlat 的可靠基础。否则即使更换向量索引，也无法区分问题究竟来自索引、embedding、字段建模、数据同步还是 Agent 使用方式。

## 10. 文档维护规则

每完成一个阶段，需要同步更新本文档：

1. 将“当前事实”中的实现状态改为真实状态；
2. 记录迁移脚本和配置开关；
3. 记录 baseline 与新方案的评测数据；
4. 记录未解决风险和回滚方式；
5. 如果代码行为与本文档冲突，以可运行代码和测试结果为准，并在文档中修正描述。