# R-005 知识库检索优化变更日志

## 概述

优化知识库检索策略，解决固定 k=2 导致的证据不足问题和缺少相似度阈值导致的低质量文档注入问题。

**实施日期：** 2026-09-19

## 问题分析

### 原有问题

1. **命名误导：** 配置变量名为 `similarity_threshold=2`，但实际用作返回数量而非相似度阈值
2. **固定 k 值：** 所有查询类型统一使用 k=2，无法适应不同复杂度的问题
3. **无相似度过滤：** 即使检索结果相似度很低也会被注入 Prompt
4. **无证据不足边界：** Agent 无法判断知识库是否有足够证据支撑回答

### 影响

- 具体问题（如"羊毛衫怎么洗"）可能因 k=2 过大引入噪音
- 宽泛问题（如"面试穿搭注意事项"）因 k=2 过小导致证据不足
- 低相关文档被强制返回，污染 Agent 判断
- 用户得到不基于知识库的回答，但系统无法明确告知

## 解决方案

### 1. 配置层改造

**文件：** `config/base.py`

**变更：**

```python
# 旧配置（误导性）
similarity_threshold = 2  # 检索返回匹配的文档数量

# 新配置（清晰语义）
knowledge_retrieval_k = 3  # 知识库检索返回数量（默认值）
knowledge_min_similarity = 0.50  # 知识库检索最低相似度阈值（0-1）
knowledge_strong_similarity = 0.60  # 多来源证据充分阈值（0-1）
enable_knowledge_dynamic_k = True  # 是否启用动态 k 值
enable_knowledge_similarity_filter = True  # 是否启用相似度过滤
```

**设计考量：**

- `knowledge_retrieval_k = 3`：作为中等复杂度查询的基线
- `knowledge_min_similarity = 0.50`：基于真实知识库检索结果重新标定
- `knowledge_strong_similarity = 0.60`：用于判断单一高质量来源或多来源证据是否充分
- 根据 Chroma Collection 的实际距离类型转换分数，当前 `l2` 使用 `1.0 - (distance / 2.0)`
- 两个开关允许独立控制动态 k 和相似度过滤功能

### 2. 动态 k 值估算

**文件：** `src/core/rag_agent.py`

**新增函数：** `estimate_knowledge_k(query: str) -> int`

**规则设计：**

| 查询类型 | k 值 | 关键词示例 | 典型问题 |
|---------|------|-----------|---------|
| 具体操作 | 2 | 怎么洗、如何洗、保养、尺码 | "羊毛衫怎么洗" |
| 搭配组合 | 4 | 搭配、配色、组合、怎么配 | "黑色和米色怎么搭配" |
| 宽泛概念 | 5 | 注意事项、禁忌、原则、技巧 | "面试穿搭注意事项" |
| 默认 | 3 | - | "今天穿什么" |

**实现逻辑：**

```python
def estimate_knowledge_k(query: str) -> int:
    """根据查询类型估算知识库检索的 Top-K 数量"""

    # 1. 具体操作类问题（操作步骤少，k=2 足够）
    specific_keywords = ["怎么洗", "如何洗", "洗涤", "如何保养", "保养", "尺码", "缩水", "褪色", "起球", "晾晒"]
    if any(kw in query for kw in specific_keywords):
        return 2

    # 2. 宽泛概念类问题（需要多文档支撑，k=5）
    broad_keywords = ["注意事项", "禁忌", "原则", "技巧", "如何提升", "怎么选", "什么风格", "穿搭建议"]
    if any(kw in query for kw in broad_keywords):
        return 5

    # 3. 搭配类问题（需要多个案例，k=4）
    match_keywords = ["搭配", "配色", "组合", "怎么配", "如何配"]
    if any(kw in query for kw in match_keywords):
        return 4

    # 4. 默认中等值
    return 3
```

**优先级顺序：** 具体操作 > 宽泛概念 > 搭配类 > 默认

### 3. 相似度过滤实现

**文件：** `src/core/rag_agent.py`

**新增方法：** `RagService._knowledge_base_search(query: str) -> str`

**核心流程：**

```python
def _knowledge_base_search(self, query: str) -> str:
    # Step 1: 动态 k 值（如果启用）
    if config.enable_knowledge_dynamic_k:
        k = estimate_knowledge_k(query)
    else:
        k = int(config.knowledge_retrieval_k)

    # Step 2: 检索并获取相似度分数
    docs_with_scores = self.vector_service.vector_store.similarity_search_with_score(query, k=k)

    # Step 3: 相似度过滤（如果启用）
    if config.enable_knowledge_similarity_filter:
        filtered_docs = []
        for doc, distance in docs_with_scores:
            similarity = normalize_vector_distance(distance, metric)
            if similarity >= config.knowledge_min_similarity:
                filtered_docs.append((doc, similarity))
    else:
        filtered_docs = docs_with_scores

    # Step 4: 证据不足判断
    if not filtered_docs:
        return "知识库中没有相关内容，建议：基于通用穿搭常识回答，并告知用户此回答不基于知识库。"

    if len(filtered_docs) == 1 and filtered_docs[0][1] < 0.75:
        return f"知识库证据有限（仅 1 条相关，相似度 {filtered_docs[0][1]:.2f}）：\n\n{doc_content}\n\n[注意：证据不足，回答时需谨慎，可补充通用常识]"

    # Step 5: 正常返回
    return "\n\n---\n\n".join([doc.page_content for doc, _ in filtered_docs])
```

**关键设计：**

- 使用 `similarity_search_with_score` 替代 `as_retriever`，获取原始分数
- 根据 Collection 实际距离类型转换分数，避免依赖 Chroma 默认配置
- 分层证据判断：
  - 无结果 → 明确告知"知识库无相关内容"
  - 1 条低质量 → 标注"证据有限"并给出警告
  - 正常情况 → 返回过滤后的文档内容

### 4. 工具注册改造

**文件：** `src/core/rag_agent.py` 方法 `__get_chain()`

**旧实现（使用 retriever）：**

```python
retriever = self.vector_service.get_retriever()
retriever_tool = create_retriever_tool(
    retriever,
    "knowledge_base_search",
    "当用户询问关于服装洗涤、尺码推荐、颜色搭配等通用穿搭知识时，必须使用此工具。",
)
```

**新实现（直接调用方法）：**

```python
knowledge_tool = Tool(
    name="knowledge_base_search",
    description="""用于检索穿搭知识库内容。适用场景：
- 服装洗涤保养（如"羊毛衫怎么洗"、"皮鞋如何保养"）
- 尺码选择建议（如"尺码偏小怎么选"、"不同品牌尺码差异"）
- 颜色搭配原则（如"黑色和米色怎么搭配"、"冷暖色调原则"）
- 场景穿搭禁忌（如"面试穿搭注意事项"、"约会穿搭建议"）

不适用场景：
- 用户衣橱单品查询（使用 wardrobe_search）
- 天气查询（使用 weather_search）
- 通用聊天（直接回答）

如果知识库无相关内容，会明确告知，此时应基于通用穿搭常识回答。
输入参数：自然语言查询
返回：相关知识库文档内容，或"证据不足"提示""",
    func=self._knowledge_base_search,
)
```

**改进点：**

- 明确列出适用和不适用场景，减少工具误用
- 在描述中说明"会明确告知证据不足"，引导 Agent 正确处理
- 移除 `create_retriever_tool` 依赖，完全自定义检索逻辑

### 5. VectorStoreService 改造

**文件：** `src/services/vector_store.py`

**旧方法：**

```python
def get_retriever(self):
    """返回向量库检索器，方便加入 Chain"""
    return self.vector_store.as_retriever(search_kwargs={"k": int(config.similarity_threshold)})
```

**新方法：**

```python
def get_retriever(self, k: int = None):
    """返回向量库检索器，支持动态 k 值。

    注意：此方法返回的 retriever 不支持相似度过滤。
    如需过滤，应在调用侧使用 similarity_search_with_score 手动过滤。

    参数:
        k: 返回数量，默认使用配置值 knowledge_retrieval_k
    """
    k = k or int(config.knowledge_retrieval_k)
    return self.vector_store.as_retriever(search_kwargs={"k": k})
```

**变更理由：**

- 保留方法兼容性（其他代码可能使用）
- 支持动态 k 值传参
- 文档说明不支持相似度过滤，引导使用新方法

## 测试验证

**测试文件：** `tests/test_rag_r005_optimization.py`

**覆盖范围：**

1. **动态 k 值逻辑测试：**
   - 具体操作问题 → k=2（4 个用例）
   - 搭配类问题 → k=4（3 个用例）
   - 宽泛概念问题 → k=5（4 个用例）
   - 默认问题 → k=3（3 个用例）

2. **配置验证测试：**
   - 新配置项存在性检查
   - 配置值合理性检查（k 值 2-10，相似度 0-1）

**测试结果：** ✅ 5/5 通过

```bash
$ python -m pytest tests/test_rag_r005_optimization.py -v
======================== 5 passed, 1 warning in 1.21s =========================
```

## 代码变更清单

### 修改文件

1. **`config/base.py`**
   - 重命名：`similarity_threshold` → `knowledge_retrieval_k`
   - 新增：`knowledge_min_similarity`
   - 新增：`enable_knowledge_dynamic_k`
   - 新增：`enable_knowledge_similarity_filter`

2. **`src/core/rag_agent.py`**
   - 新增函数：`estimate_knowledge_k(query)`
   - 新增方法：`RagService._knowledge_base_search(query)`
   - 修改方法：`RagService.__get_chain()` - 工具注册逻辑
   - 移除导入：`create_retriever_tool`

3. **`src/services/vector_store.py`**
   - 修改方法：`VectorStoreService.get_retriever()` - 支持动态 k 参数

### 新增文件

1. **`tests/test_rag_r005_optimization.py`**
   - 单元测试套件（5 个测试用例）

2. **`docs/CHANGELOG_R005.md`**
   - 本变更日志文档

### 更新文件

1. **`docs/RAG_OPTIMIZATION_PLAN.md`**
   - 标记 R-005 为已完成 ✅
   - 添加解决方案说明和验证结果

## 效果预期

### 立即效果

1. **精准度提升：**
   - 具体操作问题（k=2）减少噪音文档
   - 搭配类问题（k=4）获得足够案例
   - 宽泛概念问题（k=5）获得全面覆盖

2. **质量保障：**
   - 相似度阈值 0.65 过滤低质量结果
   - Agent 可识别"证据不足"状态
   - 用户得到明确的知识来源边界

3. **可维护性：**
   - 配置语义清晰，消除命名误导
   - 两个开关独立控制功能
   - 测试覆盖核心逻辑

### 潜在优化空间

1. **自适应阈值：** 根据查询类型动态调整相似度阈值（当前固定 0.65）
2. **多模态融合：** 结合关键词匹配和语义检索（当前仅语义）
3. **用户反馈循环：** 收集"证据不足"案例，优化 k 值规则
4. **A/B 测试：** 对比固定 k 和动态 k 的实际效果

## 回滚方案

如需回滚到旧版本：

```python
# config/base.py
similarity_threshold = 2  # 恢复旧配置名

# src/core/rag_agent.py - __get_chain()
retriever = self.vector_service.get_retriever()
retriever_tool = create_retriever_tool(
    retriever,
    "knowledge_base_search",
    "当用户询问关于服装洗涤、尺码推荐、颜色搭配等通用穿搭知识时，必须使用此工具。",
)

# 恢复 create_retriever_tool 导入
from langchain_core.tools import Tool, create_retriever_tool
```

**影响：** 回滚后将丧失动态 k 和相似度过滤功能，但不影响基础检索。

## 相关文档

- [RAG 优化总体计划](./RAG_OPTIMIZATION_PLAN.md)
- [测试套件](../tests/test_rag_r005_optimization.py)
- [配置文件](../config/base.py)
- [RAG Agent 实现](../src/core/rag_agent.py)

## 参与人员

- **实施者：** Claude Sonnet 5 (AI Assistant)
- **审查者：** 待人工审查
- **测试者：** 自动化测试套件

---

**版本：** v1.0
**最后更新：** 2026-09-19
