# LangChain Agent → LangGraph 迁移文档

> 适用项目：`ai-outfit-advisor`
>
> 目标：沉淀一份既能指导后续技术迁移、又适合在面试/答辩中讲述“架构演进”的说明文档。

---

## 1. 为什么要做这次迁移

当前项目已经具备一个较完整的 AI 应用闭环：

- 多用户登录与用户画像管理
- 基于天气与知识库的穿搭问答
- 智能衣橱管理
- 图片识衣入库
- 7 天穿搭计划生成
- 聊天历史持久化

随着能力逐渐变复杂，原先基于 **LangChain AgentExecutor** 的实现开始暴露出一些问题：

1. **执行流程不够显式**
   - 当前 Agent 的控制流封装在 `create_tool_calling_agent + AgentExecutor` 内部。
   - 对“模型什么时候调工具、调了哪个工具、结果如何回流”的可观测性不够强。

2. **状态管理分散**
   - 用户输入、历史对话、天气信息、知识库结果、衣橱检索结果，都散落在不同函数与对象里。
   - 后续如果要增加更多步骤（比如审核、纠错、二次规划），扩展成本会升高。

3. **UI 状态提示与 Agent 回调耦合较深**
   - 当前依赖 `BaseCallbackHandler` 在 Streamlit 中展示“正在查天气 / 正在翻阅知识库”。
   - 一旦 Agent 组织方式变化，UI 层的联动就容易失效。

4. **后续演进空间有限**
   - 如果想引入更清晰的状态图、节点级调试、checkpoint、人工介入、失败恢复，LangGraph 更适合。

因此，迁移到 **LangGraph** 的核心价值不是“换个库”，而是把原本隐式的 Agent 流程升级为**显式、可追踪、可扩展的状态图架构**。

---

## 2. 当前架构现状

### 2.1 当前与 LangChain Agent/Chain 直接相关的核心文件

#### `rag.py`

这是当前 Agent 主体，承担了：

- Prompt 组装
- 工具定义
- 工具调用 Agent 构建
- 对话历史绑定
- 输出提取
- 普通穿搭问答入口
- 周计划生成入口

当前使用的关键组件：

```python
RunnableWithMessageHistory
RunnableLambda
BaseCallbackHandler
Tool
ChatPromptTemplate
MessagesPlaceholder
ChatTongyi
DuckDuckGoSearchRun
create_tool_calling_agent
AgentExecutor
create_retriever_tool
```

#### `app_qa.py`

这是 RAG 的前端调用层，主要做：

- 初始化 `RagService`
- 传入用户画像、城市、衣橱文本
- 调用 `rag.invoke()`
- 渲染结果与 `<item>id</item>` 标签
- 使用 callback 在页面上展示 Agent 工作过程

#### `history.py`

当前通过 Supabase 持久化消息历史，为：

```python
RunnableWithMessageHistory(...)
```

提供上下文记忆。

#### `vector_store_service.py`

承担两类向量检索：

- 知识库检索：`VectorStoreService`
- 衣橱语义检索：`VectorWardrobeService`

#### `knowledge_base.py`

负责：

- Chroma 索引构建
- 文本切分
- 用户知识上传
- 从 Supabase 恢复知识文档

#### `prompts.py`

负责集中管理：

- `RAG_SYSTEM_PROMPT`
- `WEEKLY_PLAN_PROMPT`
- `VLM_ANALYZE_PROMPT`

---

### 2.2 当前执行链路

普通问答的链路可以概括为：

```text
app_qa.py
  ↓
RagService.invoke()
  ↓
_prepare_inputs()
  ↓
create_tool_calling_agent(...)
  ↓
AgentExecutor(...)
  ↓
RunnableWithMessageHistory(...)
  ↓
RunnableLambda(extract_output)
  ↓
返回字符串给 Streamlit UI
```

工具层包含两种能力：

1. `weather_search`
   - 通过 DuckDuckGo 查询指定城市天气

2. `knowledge_base_search`
   - 通过 Chroma 检索本地/用户知识库

此外还有一条与 Agent 配合的“衣橱语义压缩”支线：

```text
用户提问
  ↓
VectorWardrobeService.search()
  ↓
取 Top-K 衣橱单品文本
  ↓
压缩后注入 Prompt
```

---

## 3. 当前架构的痛点

### 3.1 控制流不透明

虽然现在功能能跑通，但 Agent 的关键行为大量隐藏在 `AgentExecutor` 内部：

- 何时触发工具
- 工具调用了几轮
- 每轮输入输出是什么
- 最终答案是如何收敛的

这在开发阶段还能靠日志勉强追踪，但在架构说明、线上排障、复杂扩展时都不够直观。

### 3.2 状态缺少统一模型

当前系统里存在多种上下文：

- 用户原始输入
- 用户性别/风格/身材/城市
- 对话历史
- 天气查询结果
- 知识库召回结果
- 衣橱语义检索结果
- 最终回答

这些状态没有被统一抽象成一个显式的 state 对象，而是分散在：

- Prompt 变量
- tool 输出
- history 存储
- session_state
- RagService 内部临时变量

一旦后续增加“结果校验”“意图识别”“失败重试”“人工审核”等节点，维护成本会快速上升。

### 3.3 前端反馈依赖 Callback 机制

当前 UI 使用：

```python
BaseCallbackHandler
```

来感知 Agent 运行阶段。这种方式在 LangChain AgentExecutor 下可行，但不够稳定：

- 与具体执行器耦合深
- 事件粒度受框架内部实现影响
- 不利于迁移到显式节点流

### 3.4 周计划与普通问答复用度不高

`generate_weekly_plan()` 本质上已经是一条接近“流程编排”的逻辑：

1. 获取一周天气
2. 组织衣橱上下文
3. 构建 Prompt
4. 结构化输出
5. fallback JSON 修复

这说明项目已经不只是“单个聊天 Agent”，而是开始向**多流程 AI 编排系统**演进，更适合 LangGraph 这类图式框架。

---

## 4. 为什么选择 LangGraph

LangGraph 相比当前方案的核心优势，不在于“更高级”，而在于更适合项目当前阶段。

### 4.1 流程显式化

可以把原来的隐式 Agent 过程拆成明确节点，例如：

```text
prepare_inputs
  ↓
compress_wardrobe_context
  ↓
agent_llm
  ↓
tools
  ↓
agent_llm
  ↓
finalize_answer
```

每一步都可以被单独理解、调试、记录和复用。

### 4.2 状态统一化

可以定义统一的 `State`：

```python
class OutfitAgentState(TypedDict):
    input: str
    gender: str
    style: str
    body: str
    city: str
    wardrobe: str
    current_date: str
    messages: list
    weather_context: str
    knowledge_context: str
    final_answer: str
```

这样整个流程的上下文边界就清楚了。

### 4.3 更适合多步骤业务演进

后续如果要加：

- 输入分类
- 工具选择策略
- 结果验证
- 自动重试
- 人工审批
- 周计划独立 graph

LangGraph 都比传统 AgentExecutor 更自然。

### 4.4 更适合面试与架构讲述

从“LangChain Agent 调工具”升级到“LangGraph 状态图编排”，很容易讲出工程深度：

- 为什么要迁移
- 遇到了什么复杂度
- 如何拆解状态与节点
- 如何平衡兼容性与演进性

这类表达在面试里会比单纯讲“我用了个大模型框架”更有层次。

---

## 5. 迁移目标

这次迁移建议设定为两个层次。

### 5.1 第一阶段目标：功能等价迁移

目标：

- 不大改 UI
- 不改知识库与向量库的数据层
- 不动图片识衣与衣橱 CRUD
- 先把普通问答 Agent 从 LangChain AgentExecutor 迁移到 LangGraph

成功标准：

1. `app_qa.py` 仍然可以通过 `RagService.invoke()` 调用问答
2. 模型仍然能按需调用天气工具和知识库检索工具
3. 返回结果仍然是字符串
4. `<item>id</item>` 标签仍然能被前端解析
5. 聊天历史仍然能正确读写到 Supabase

### 5.2 第二阶段目标：架构升级

目标：

- 拆出独立 graph 文件与节点模块
- 将 UI 状态展示从 callback 改为 graph 事件流
- 视情况引入 checkpoint
- 将周计划迁移为独立 graph

### 5.3 第二阶段当前落地状态（已完成部分）

截至目前，第二阶段并不是“全部完成”，而是已经落地了两个可独立回滚、可独立提交的工程步骤：

1. **衣橱读取 fallback**
   - Commit：`9da436e`
   - Message：`fix: add fallback for wardrobe item loading`
   - 目的：让 `WardrobeService.get_all_items()` 在 Supabase / 网络异常时不要直接打断页面渲染。

2. **问答 UI 改为消费 LangGraph 事件流**
   - Commit：`2df61eb`
   - Message：`feat: stream LangGraph agent events to chat UI`
   - 目的：把 `app_qa.py` 中原本依赖 `BaseCallbackHandler` 的 UI 状态展示，迁移为由 `RagService.stream_events()` 消费 LangGraph 执行事件。

这两个提交被故意拆开，而不是混在一起，原因是：

- `get_all_items()` fallback 是独立的稳定性修复；
- streaming 改动会改变用户可见的“思考中”状态流转；
- 分开提交后，一旦出现问题，更容易定位是数据读取层还是 agent 事件流层引起的。

---

## 6. 迁移范围评估

### 6.1 必改模块

#### `rag.py`

这是迁移核心。

需要替换的内容包括：

- `create_tool_calling_agent`
- `AgentExecutor`
- `RunnableWithMessageHistory`
- `RunnableLambda(extract_output)`

需要新增的内容包括：

- LangGraph state 定义
- graph 构建与编译
- graph 输出到字符串的兼容封装

#### `requirements.txt`

需要新增：

```text
langgraph
```

并建议同步整理 LangChain 相关依赖版本，避免兼容问题。

---

### 6.2 可能调整的模块

#### `app_qa.py`

如果 `RagService.invoke()` 的输入输出接口保持不变，这个文件可以少改。

主要潜在变化点：

- config 结构
- callback 逻辑
- 状态提示方式

#### `history.py`

第一阶段可以继续保留，用作历史消息读写。

第二阶段如果引入 LangGraph checkpoint，再考虑重构。

#### `prompts.py`

Prompt 内容基本可复用，但变量注入方式可能会从 `ChatPromptTemplate` 变成显式组装 `messages`。

---

### 6.3 可基本复用的模块

#### `vector_store_service.py`

Chroma 检索逻辑可以继续使用。

#### `knowledge_base.py`

知识库文档切分、入库、恢复逻辑与 Agent 编排无强耦合，可保留。

#### `wardrobe_service.py`

衣橱 CRUD 与图片识衣和迁移无直接关系，可保留。

#### `user_service.py`

用户系统无需因 LangGraph 迁移而改动。

---

## 7. 风险点与控制策略

### 风险 1：Tool Calling 兼容性

当前模型使用：

```python
ChatTongyi(model=config.chat_model_name)
```

迁移后若采用 LangGraph 的工具节点，需要先验证：

- Tongyi 是否稳定返回 tool_calls
- 工具参数格式是否兼容
- 与天气工具、检索工具结合是否正常

**控制策略：**

先做最小 POC，只验证：

- 城市天气问答
- 知识型问答

确认工具链路跑通后再扩大改造范围。

---

### 风险 2：消息历史接入方式变化

当前使用：

```python
RunnableWithMessageHistory
```

LangGraph 更偏向：

- `thread_id`
- checkpointer
- graph state

**控制策略：**

第一阶段先不追求原生 checkpoint，继续复用 `history.py`，在 graph 调用前后手动读写历史。

---

### 风险 3：前端状态提示丢失

当前 Streamlit 的“正在查天气 / 正在翻阅秘籍”依赖 callback。

**控制策略：**

第一阶段先保留最小可用提示；
第二阶段再把 callback 重构为 graph 事件驱动展示。

---

### 风险 4：返回值协议变化

LangGraph 通常返回 state dict，
但当前 `app_qa.py` 期望的是：

```python
res = rag.invoke(...)
# res 是 str
```

**控制策略：**

在 `RagService` 内部保留兼容层：

```python
def invoke(...):
    state = self.graph.invoke(...)
    return state["final_answer"]
```

---

### 风险 5：周计划和普通问答混改导致范围过大

`generate_weekly_plan()` 本身已经是一条独立业务流。

**控制策略：**

第一阶段只迁移普通问答 Agent；
周计划放到第二阶段，单独 graph 化。

---

## 8. 建议的目标架构

### 8.1 第一阶段：低风险目标架构

建议优先做“兼容式迁移”：

```text
app_qa.py
  ↓
RagService.invoke()
  ↓
LangGraph graph.invoke()
  ↓
返回 final_answer(str)
```

Graph 内部结构可简化为：

```text
START
  ↓
prepare_inputs
  ↓
agent_node
  ↓
tools_condition
  ├─ 有工具调用 → tools_node → agent_node
  └─ 无工具调用 → finalize_answer
  ↓
END
```

特点：

- 外部调用不变
- 内部实现从 AgentExecutor 切换为 Graph
- 成本可控
- 易于回滚

---

### 8.2 第二阶段：完整演进架构

当第一阶段稳定后，可以升级为业务显式图：

```text
START
  ↓
prepare_user_context
  ↓
compress_wardrobe_context
  ↓
decide_route
  ├─ 天气信息不足 → weather_node
  ├─ 通用知识问题 → knowledge_node
  └─ 直接回答
  ↓
generate_outfit_answer
  ↓
validate_answer
  ↓
persist_history
  ↓
END
```

这时系统就从“Agent 聊天”升级为“带业务状态的 AI 决策图”。

---

## 9. 建议迁移顺序

### 第一步：做基线留档

迁移前记录：

- 典型穿搭问答输入输出
- 天气工具调用场景
- 知识库问答场景
- `<item>id</item>` 标签效果
- 聊天历史读写情况

这样迁移后才有对照标准。

### 第二步：只改 `rag.py`

优先把：

- AgentExecutor
- RunnableWithMessageHistory

替换掉，但先不碰 UI 与数据层。

### 第三步：保留 `RagService` 兼容接口

目标是：

- `invoke()` 继续返回字符串
- `stream()` 继续给上层用
- `generate_weekly_plan()` 先保持不变

### 第四步：验证两个关键场景

至少验证：

1. 带天气的穿搭问题
2. 带知识库检索的通用问题

只要这两个场景跑通，普通问答主链路基本就稳了。

### 第五步：再处理 UI 事件

把 callback 驱动的提示改造成 graph 事件驱动。

### 第六步：最后迁移周计划

把 `generate_weekly_plan()` 独立成第二张 graph，而不是与普通问答强耦合。

---

## 10. 面试时可以怎么讲这次架构演进

下面是一套可直接复述的讲法。

### 10.1 一分钟版本

> 我做过一个智能穿搭顾问项目，最初基于 LangChain 的 AgentExecutor 实现天气查询、知识库检索和多轮问答。随着业务复杂度提升，我发现原有方案在状态管理、流程可观测性和后续扩展上比较吃力，所以计划迁移到 LangGraph。
>
> 迁移的核心不是简单换框架，而是把原本隐式的 Agent 流程显式化：把用户画像注入、衣橱语义压缩、工具调用、答案生成这些步骤抽象成状态图节点。这样后续如果要加 checkpoint、失败恢复、人工审核或者把 7 天穿搭计划也纳入统一编排，架构会更自然。
>
> 我在迁移策略上采用两阶段方式：第一阶段先保证功能等价，只迁移普通问答 Agent，保留对外接口不变；第二阶段再逐步图化更多业务流程。这种方式能兼顾工程可落地性和架构演进空间。

### 10.2 三分钟版本

可以按下面四段讲：

#### 1）项目背景

> 这是一个基于 Streamlit、LangChain、Qwen、Chroma、Supabase 的 AI 穿搭顾问系统，支持多用户、天气感知穿搭问答、知识库问答、智能衣橱和周计划生成。

#### 2）原架构问题

> 早期我用 LangChain 的 `create_tool_calling_agent + AgentExecutor` 很快搭起了工具调用链，但随着能力变多，发现几个问题：
> - 控制流隐藏在执行器内部，不够透明
> - 状态分散在 prompt、history、session、tool 输出里
> - UI 的状态提示强依赖 callback
> - 后续如果要加更复杂的节点编排，扩展性一般

#### 3）为什么选 LangGraph

> LangGraph 更适合做显式流程编排。我可以把系统抽象成一个状态图：输入准备、衣橱上下文压缩、模型决策、工具调用、答案收敛，每一步都可观测。这样不仅更容易排障，也更适合后续增加 checkpoint、人工审核或多个子流程 graph。

#### 4）迁移策略

> 我没有选择一次性重写，而是分两阶段：第一阶段只迁移普通问答 Agent，保留 `RagService.invoke()` 的对外接口，尽量不影响 UI 和数据层；第二阶段再把周计划、事件流展示、checkpoint 等能力逐步纳入 LangGraph 架构。这样做的好处是风险低、回滚容易、对业务影响最小。

---

## 11. 这次迁移最值得强调的工程思路

如果面试官继续追问，你可以重点强调这几个点：

### 11.1 不是为了“追新”，而是为了解决复杂度

迁移动机不是“LangGraph 更火”，而是：

- 当前系统流程越来越像状态机
- 原架构难以显式表达和扩展

### 11.2 先保兼容，再做重构

不是一上来推倒重来，而是：

- 保留 `RagService` 作为兼容层
- 保持 `app_qa.py` 调用方式不变
- 用最小改动先完成底层替换

这体现的是工程化思维，而不是纯技术炫技。

### 11.3 拆分“功能迁移”和“架构升级”

把迁移分两步：

1. 功能等价迁移
2. 架构能力升级

能有效控制风险，也方便持续交付。

### 11.4 保留业务语义而不是只迁工具

系统真正有价值的不是“调了天气工具”，而是：

- 用户画像参与决策
- 衣橱语义检索降低 prompt 负担
- 问答结果能回流到 UI 单品卡片
- 周计划有结构化输出与 fallback

迁移过程中要保住这些业务语义，而不只是把 API 调通。

---

## 12. 后续落地建议

在真实迁移过程中，第二阶段已经积累出一些比“目标架构图”更有价值的实践经验。

### 12.1 第二阶段已落地的工程经验

#### 经验 1：独立的稳定性修复要单独 commit

本次第二阶段里，`get_all_items()` fallback 被单独放在：

```text
9da436e fix: add fallback for wardrobe item loading
```

这说明在 AI 应用演进里，**数据层容错**和**Agent 编排升级**虽然都属于“第二阶段”，但风险类型完全不同。

- fallback 改动更接近传统 Web / 数据访问稳定性修复；
- streaming 改动更接近 AI 交互链路改造；
- 将两者拆开能显著降低排障成本。

#### 经验 2：`stream_events()` 比直接把 UI 绑死在 callback 上更可控

本次落地没有直接重写整个 graph，而是保留：

- `RagService.invoke()`
- `RagService.stream()`

同时新增：

- `RagService.stream_events()`

这样做的好处是：

1. 老的同步调用接口不受影响；
2. UI 可以逐步迁移到 LangGraph event stream；
3. 一旦 streaming 有问题，还能快速退回 `invoke()` 路径；
4. 对 `app_qa.py` 的影响被控制在问答区，而没有波及周计划逻辑。

#### 经验 3：不要在 streaming 改动里顺手扩 scope

在设计第二个 commit 时，曾考虑抽出 `_persist_history()`，把聊天历史写入逻辑统一封装。

这个思路本身没有问题，但它会把改动范围从：

- “UI 如何消费 graph 事件”

扩大为：

- “历史写入逻辑也一起重构”

为了控制风险，最终采用了更保守的策略：

- 保留原有历史写入行为；
- 仅在 `stream_events()` 内按现有方式写入消息；
- 先完成事件流接入，再考虑后续重构持久化封装。

这类取舍非常关键：**第二阶段的目标是降低 UI 与 callback 的耦合，而不是顺便整理所有内部辅助方法。**

### 12.2 第二阶段人工验证结果

本次已经完成了一轮登录后人工验证，结论如下：

#### 已验证通过

1. **注册 / 登录成功**
   - 使用测试账号成功进入登录后页面。

2. **登录后主界面正常**
   - 成功看到“穿搭顾问 / 智能衣橱”界面。
   - 左侧用户信息和穿搭档案正常显示。

3. **问答请求成功触发到 LangGraph 链路**
   - 发送测试问题后，终端日志出现：
     ```text
     🚀 [系统启动] 穿搭决策大脑已就绪
     👤 [用户输入] 明天参加社团面试，求推荐穿搭！
     🧠 [模型思考] 正在生成穿搭建议...
     📄 [工具结果] ...
     ```
   - 说明登录后问答链路没有断，且新的 streaming 路径已接通。

#### 当前发现的问题

本轮验证也发现了第二阶段的一个现实问题：

- 测试问题成功进入 LangGraph 流程；
- 天气工具也确实被调用并返回了结果；
- 但在可观察时间内，没有稳定收敛到最终回答。

更准确地说，当前状态不是“streaming 接不上”，而是：

> **streaming 已接上，但 agent 在天气工具结果噪音较大的情况下，存在循环过长、收敛不稳定的问题。**

这意味着第二阶段虽然完成了“UI 事件流接入”，但还没有完成“问答链路收敛性优化”。

### 12.3 下一步建议

结合当前第二阶段结果，后续更推荐优先做：

1. **优化 weather_search 的结果质量**
   - 减少 DuckDuckGo 返回大量噪音网页导致的重复推理。

2. **给 `stream_events()` 增加保护机制**
   - 例如最大事件轮数、最大工具调用轮数或超时 fallback。

3. **限制 agent 在天气工具上的反复调用**
   - 让模型在已有天气结果基础上尽快收敛，而不是持续搜索。

4. **最后再考虑显式 StateGraph / checkpoint / 周计划 graph 化**
   - 否则会在“主链路尚未收敛稳定”时继续扩大系统复杂度。

如果后续开始真实迁移，建议先做以下产出：

1. **新增一版架构图**
   - 当前 LangChain Agent 架构
   - 目标 LangGraph 架构

2. **设计统一 State**
   - 明确哪些字段属于 graph state

3. **先做最小 POC**
   - 只保留天气工具 + 知识库工具
   - 验证 Tongyi 的 tool calling

4. **保留兼容层**
   - `RagService.invoke()` / `stream()` 不变

5. **最后再处理周计划与 UI 事件**
   - 不要一开始把范围拉得过大

---

## 13. 一句话总结

这次迁移的本质，是把一个“能工作的 LangChain Agent”升级成一个“可演进、可观测、可编排的 LangGraph 状态图系统”。

从工程视角看，它体现的是：**当 AI 应用从 Demo 走向复杂业务时，架构需要从隐式调用链演进为显式状态图。**
