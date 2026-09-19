"""穿搭问答 RAG 服务与 LangGraph Agent 编排逻辑。

本模块连接天气、知识库和衣橱检索工具，并将最终回答交给 Streamlit 问答页渲染。
"""

from typing import Optional

import datetime
import copy
import json
import re
import time
from dataclasses import dataclass

from pydantic import BaseModel, Field

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_core.tools import Tool
from src.repositories.chat_history import FileChatMessageHistory
from src.services.vector_store import VectorStoreService, VectorWardrobeService
from src.core.prompts import RAG_SYSTEM_PROMPT, WEEKLY_PLAN_PROMPT
from langchain_community.embeddings import DashScopeEmbeddings
from config import base as config
from langchain_community.chat_models.tongyi import ChatTongyi
from src.services.weather import WeatherService
from config.supabase import get_supabase_client


def estimate_knowledge_k(query: str) -> int:
    """根据查询类型估算知识库检索的 Top-K 数量（独立函数，供测试和生产使用）。

    规则:
    - 具体操作问题（洗涤、保养、尺码）: k=2
      示例: "羊毛衫怎么洗", "如何保养皮鞋", "尺码偏小怎么选"
    - 搭配类问题（颜色、单品组合）: k=4
      示例: "黑色和米色怎么搭配", "衬衫和裤子如何组合"
    - 宽泛概念问题（风格、原则、注意事项）: k=5
      示例: "面试穿搭注意事项", "如何提升穿搭品味", "配色原则"
    - 默认中等值: k=3

    参数:
        query: 用户查询文本

    返回:
        建议的 Top-K 数量（2-5）
    """
    # 具体操作类问题（洗涤、保养、尺码）
    specific_keywords = ["怎么洗", "如何洗", "洗涤", "如何保养", "保养", "尺码", "缩水", "褪色", "起球", "晾晒"]
    if any(kw in query for kw in specific_keywords):
        return 2

    # 宽泛概念类问题（风格、原则、注意事项）
    broad_keywords = ["注意事项", "禁忌", "原则", "技巧", "如何提升", "怎么选", "什么风格", "穿搭建议"]
    if any(kw in query for kw in broad_keywords):
        return 5

    # 搭配类问题（颜色、单品组合）
    match_keywords = ["搭配", "配色", "组合", "怎么配", "如何配"]
    if any(kw in query for kw in match_keywords):
        return 4

    # 默认中等值
    return 3


@dataclass(frozen=True)
class KnowledgeRetrievalResult:
    """知识库检索的结构化结果，供业务格式化和测试共同使用。"""

    status: str
    documents: list
    top_similarity: float | None
    requested_k: int


def get_vector_distance_metric(vector_store) -> str:
    """读取 Chroma Collection 的距离类型，避免依赖隐含默认值。

    参数:
        vector_store: LangChain Chroma 实例。

    返回:
        `cosine`、`l2` 或 `ip`。无法识别时返回 `unknown`，由调用方安全降级。
    """
    collection = getattr(vector_store, "_collection", None)
    configuration = getattr(collection, "configuration", None) or {}
    hnsw = configuration.get("hnsw") or {}
    spann = configuration.get("spann") or {}
    return str(hnsw.get("space") or spann.get("space") or "unknown").lower()


def normalize_vector_distance(distance: float, metric: str) -> float:
    """将 Chroma 原始距离归一化为 0-1 的相关度分数。

    Chroma 的 `l2` 返回平方 L2 距离；当前 DashScope 向量是单位向量，
    因此平方 L2 距离与余弦距离的关系为 `distance / 2`。未知度量不猜测，
    直接抛错，避免把错误分数静默注入回答。
    """
    distance = float(distance)
    if metric == "cosine":
        return max(0.0, min(1.0, 1.0 - distance))
    if metric == "l2":
        return max(0.0, min(1.0, 1.0 - distance / 2.0))
    if metric == "ip":
        return max(0.0, min(1.0, 1.0 - distance))
    raise ValueError(f"不支持的向量距离类型: {metric}")


def estimate_topk_for_query(query: str) -> int:
    """根据query复杂度估算需要检索的Top-K数量（独立函数，供测试和生产使用）。

    规则:
    - 简单查询(0-1维度 且 ≤5字): k=5
      示例: "外套", "裤子", "黑色", "黑色裤子"
    - 中等查询(2维度 且 6-10字): k=8
      示例: "黑色外套", "春季上衣", "休闲裤子"
    - 复杂查询(3+维度或场景或≥11字): k=12
      示例: "黑色春季外套", "适合面试的正式穿搭"

    参数:
        query: 用户查询文本

    返回:
        建议的Top-K数量(5/8/12)
    """
    # 场景类查询直接返回k=12(通常需要多件单品组合)
    scene_keywords = ["适合", "面试", "约会", "聚会", "通勤", "出游", "旅行", "派对", "穿搭", "搭配"]
    if any(kw in query for kw in scene_keywords):
        return 12

    # 统计query中的关键维度词
    complexity_markers = [
        ("季节", ["春", "夏", "秋", "冬", "早春", "初秋", "盛夏", "寒冬"]),
        ("颜色", ["黑", "白", "蓝", "红", "灰", "米", "卡其", "藏青", "深蓝", "浅蓝", "棕", "绿"]),
        ("风格", ["休闲", "正式", "运动", "甜美", "帅气", "简约", "复古", "街头", "优雅"]),
        ("类别", ["外套", "裤子", "裙子", "鞋", "上衣", "内搭", "大衣", "夹克", "衬衫", "T恤"]),
    ]

    dimension_count = sum(
        1 for _, keywords in complexity_markers
        if any(kw in query for kw in keywords)
    )

    # 基于字数和维度的k值策略
    # 规则: 字数优先级高于维度数,避免"黑色裤子"(4字2维度)被误判为k=8
    query_len = len(query)

    if query_len <= 5:
        # ≤5字无论几个维度都是简单查询
        return 5
    elif dimension_count >= 3 or query_len >= 11:
        # 3+维度或≥11字是复杂查询
        return 12
    elif dimension_count == 2:
        # 6-10字且2维度是中等查询
        return 8
    else:
        # 其他情况默认简单查询
        return 5


class OOTDItem(BaseModel):
    desc: str = Field(description="【自有】或【建议购入】+ **单品名称** + 搭配理由")
    id: str = Field(default="", description="衣橱中该单品的精确id，建议购入时留空字符串")


class DayPlan(BaseModel):
    scene: str = Field(description="今日场景感知描述，融入天气与风格主题")
    ootd: list[OOTDItem] = Field(description="今日完整穿搭，至少3件单品")
    tips: str = Field(description="针对该套穿搭的专业贴士")


class WeeklyPlan(BaseModel):
    days: list[DayPlan] = Field(description="7天穿搭计划，从今天开始的连续7天，每天一套完整搭配")


FALLBACK_MESSAGE = "小衣当前思考超时，请稍后再试"
LANGGRAPH_IMPORT_ERROR_MESSAGE = (
    "LangGraph 依赖不可用或版本不兼容，请安装与当前 LangChain 生态兼容的 LangGraph 版本后再试。"
)


TOOL_EVENT_LABELS = {
    "weather_search": ("🌤️", "正在观测天象", "查询天气"),
    "knowledge_base_search": ("📚", "正在翻阅时尚秘籍", "检索穿搭知识"),
    "wardrobe_search": ("👗", "正在翻找衣橱", "检索衣橱单品"),
}


class ConsoleLoggingHandler(BaseCallbackHandler):
    _boot_logged = False

    def __init__(self):
        super().__init__()
        self._chain_depth = 0

    def _extract_latest_human_text(self, value):
        """从 LangChain/LangGraph 输入结构中提取最后一条用户文本，避免打印完整 messages 状态。"""
        if isinstance(value, HumanMessage):
            return value.content
        if isinstance(value, BaseMessage):
            return value.content
        if isinstance(value, dict):
            if "input" in value:
                return self._extract_latest_human_text(value["input"])
            if "messages" in value:
                return self._extract_latest_human_text(value["messages"])
            return str(value)
        if isinstance(value, list):
            for msg in reversed(value):
                if isinstance(msg, HumanMessage) and msg.content:
                    return msg.content
            for msg in reversed(value):
                if isinstance(msg, BaseMessage) and msg.content:
                    return msg.content
            return ""
        return str(value)

    def _format_tool_input(self, tool_input):
        if isinstance(tool_input, dict):
            for key in ("query", "input", "question"):
                if key in tool_input:
                    return str(tool_input[key])
            return str(tool_input)
        return str(tool_input)

    def on_chain_start(self, serialized, inputs, **kwargs):
        self._chain_depth += 1
        if self._chain_depth == 1 and not ConsoleLoggingHandler._boot_logged:
            print("🚀 [系统启动] 穿搭决策大脑已就绪", flush=True)
            ConsoleLoggingHandler._boot_logged = True
        if self._chain_depth == 1:
            user_input = self._extract_latest_human_text(inputs)
            print(f"👤 [用户输入] {user_input}", flush=True)

    def on_chain_end(self, output, **kwargs):
        if self._chain_depth > 0:
            self._chain_depth -= 1

    def on_llm_start(self, serialized, prompts, **kwargs):
        print("🧠 [模型思考] 正在生成穿搭建议...", flush=True)

    def on_agent_action(self, action, **kwargs):
        tool_input = self._format_tool_input(action.tool_input)
        print(f"🔧 [工具调用] {action.tool} | {tool_input}", flush=True)

    def on_tool_end(self, output, **kwargs):
        print(f"📄 [工具结果] {str(output)[:200]}...", flush=True)

    def on_agent_finish(self, finish, **kwargs):
        print("[DONE] 穿搭建议已生成", flush=True)
        print("-" * 40, flush=True)


class RagService(object):
    def __init__(
        self,
        vector_wardrobe: Optional[VectorWardrobeService] = None,
        user_id: str = "",
        enable_hybrid_retrieval: bool = True
    ):
        """初始化 RAG 服务，并打印模型、向量库、LangGraph 组装耗时。

        参数:
            vector_wardrobe: 向量衣橱服务（可选）
            user_id: 用户 ID
            enable_hybrid_retrieval: 是否启用混合检索（R-004优化，默认True）
        """
        start_time = time.time()
        self.vector_wardrobe = vector_wardrobe
        self.user_id = user_id
        self.enable_hybrid_retrieval = enable_hybrid_retrieval
        self.weather_service = WeatherService(supabase_client=get_supabase_client())

        # 初始化混合检索器（如果启用且衣橱服务可用）
        self.hybrid_retriever = None
        if enable_hybrid_retrieval and vector_wardrobe and user_id:
            try:
                from src.services.hybrid_wardrobe_retriever import HybridWardrobeRetriever
                self.hybrid_retriever = HybridWardrobeRetriever(
                    user_id=user_id,
                    vector_service=vector_wardrobe,
                    enable_structural_filter=True
                )
                print("[INFO] 混合检索器已启用（结构化过滤 + 语义排序）", flush=True)
            except Exception as exc:
                print(f"[WARN] 混合检索器初始化失败，回退到纯语义检索: {exc}", flush=True)

        self.vector_service = VectorStoreService(
            embedding=DashScopeEmbeddings(model=config.EMBEDDING_MODEL_NAME),
            user_id=user_id,
        )

        self.chat_model = ChatTongyi(model=config.chat_model_name)

        self.chain = self.__get_chain()
        print(f"[PERF] RagService.__init__ took {time.time() - start_time:.3f}s", flush=True)

    def _with_current_date(self, inputs: dict) -> dict:
        if "current_date" in inputs:
            return inputs
        updated_inputs = dict(inputs)
        updated_inputs["current_date"] = datetime.datetime.now().strftime("%Y年%m月%d日")
        return updated_inputs

    def _prepare_inputs(self, inputs: dict) -> dict:
        """预处理输入：注入当前日期。"""
        start_time = time.time()
        inputs = self._with_current_date(inputs)
        print(f"[PERF] RagService._prepare_inputs took {time.time() - start_time:.3f}s", flush=True)
        return inputs

    def stream(self, inputs: dict, config: Optional[dict] = None):
        try:
            prepared_inputs = self._prepare_inputs(inputs)
            answer = self._invoke_graph(prepared_inputs, config=config)

            def _answer_stream():
                yield answer

            return _answer_stream()
        except Exception:

            def _fallback():
                yield FALLBACK_MESSAGE

            return _fallback()

    def stream_events(self, inputs: dict, config: Optional[dict] = None):
        """以 LangGraph 事件流驱动 UI 状态展示，同时保持最终答案兼容。"""
        try:
            total_start = time.time()
            prepared_inputs = self._prepare_inputs(inputs)
            normalized_config = self._normalize_config(config)
            session_id, history_messages = self._get_session_history(normalized_config)
            graph_inputs = self._build_graph_inputs(prepared_inputs, history_messages)

            yield {"type": "status", "label": "🤔 正在理解你的需求，构思搭配方向..."}

            last_state = None
            seen_tool_call_ids = set()
            for state in self.chain.stream(graph_inputs, config=normalized_config, stream_mode="values"):
                last_state = state
                for tool_call in self._extract_tool_calls_from_state(state):
                    call_id = tool_call.get("id") or json.dumps(tool_call, ensure_ascii=False, sort_keys=True)
                    if call_id in seen_tool_call_ids:
                        continue
                    seen_tool_call_ids.add(call_id)
                    yield {"type": "status", "label": self._format_tool_event_label(tool_call)}
                    yield {"type": "status", "label": "✅ 信息已获取，继续优化方案..."}

            yield {"type": "status", "label": "✨ 灵感迸发，正在为你整理专属穿搭方案..."}

            answer = self._extract_answer_from_state(last_state)
            try:
                history = FileChatMessageHistory(session_id=session_id)
                history.add_messages(
                    [HumanMessage(content=prepared_inputs.get("input", "")), AIMessage(content=answer)]
                )
                history.maybe_update_summary(summary_updater=self.summarize_chat_messages)
            except Exception as exc:
                print(f"[WARN] 聊天历史写入不可用，已跳过持久化：{exc}", flush=True)
                import traceback
                traceback.print_exc()

            print(f"[PERF] RagService.stream_events total took {time.time() - total_start:.3f}s", flush=True)
            yield {"type": "answer", "content": answer}
        except Exception:
            yield {"type": "error", "content": FALLBACK_MESSAGE}

    def invoke(self, inputs: dict, config: Optional[dict] = None):
        try:
            prepared_inputs = self._prepare_inputs(inputs)
            return self._invoke_graph(prepared_inputs, config=config)
        except Exception:
            return FALLBACK_MESSAGE

    def _get_langgraph_factory(self):
        try:
            from langgraph.prebuilt import create_react_agent

            return create_react_agent
        except Exception as exc:
            raise RuntimeError(LANGGRAPH_IMPORT_ERROR_MESSAGE) from exc

    def _normalize_config(self, config: Optional[dict] = None) -> dict:
        config = dict(config or {})
        configurable = dict(config.get("configurable") or {})
        session_id = configurable.get("session_id") or configurable.get("thread_id")
        if not session_id:
            session_id = f"chat_session_{self.user_id}" if self.user_id else "default_session"
        configurable.setdefault("thread_id", session_id)
        configurable.setdefault("session_id", session_id)
        config["configurable"] = configurable

        # 设置递归限制防止LangGraph ReAct Agent死循环
        # 正常流程: wardrobe_search(1次) + knowledge_base_search(0-1次) + weather_search(0-1次) = 2-3次工具调用
        # 设置15次足够应对复杂场景,同时防止压缩格式或提示词问题导致的无限循环
        config.setdefault("recursion_limit", 15)

        return config

    def _coerce_history_messages(self, raw_messages) -> list[BaseMessage]:
        """把外部传入的历史消息转成 LangChain message 对象。

        为什么这么做：Streamlit 页面里已经把当前会话消息保存在 session_state。
        如果问答前还要再去 Supabase 读一遍聊天历史，就会多出一次同步网络等待。
        这里允许优先复用内存里的历史，减少问答前的阻塞时间。
        """
        if not raw_messages:
            return []

        messages: list[BaseMessage] = []
        for msg in raw_messages:
            if isinstance(msg, BaseMessage):
                messages.append(msg)
                continue
            if not isinstance(msg, dict):
                continue

            role = msg.get("role")
            content = msg.get("content", "")
            if role == "user":
                messages.append(HumanMessage(content=content))
            elif role == "assistant":
                messages.append(AIMessage(content=content))
        return messages

    def _build_system_prompt(self, inputs: dict) -> str:
        prompt_inputs = {
            "current_date": inputs.get("current_date", datetime.datetime.now().strftime("%Y年%m月%d日")),
            "gender": inputs.get("gender", "未设置"),
            "style": inputs.get("style", "未设置"),
            "body": inputs.get("body", ""),
            "city": inputs.get("city", ""),
        }
        return RAG_SYSTEM_PROMPT.format(**prompt_inputs)

    def _detect_constraint_message(self, message: BaseMessage) -> bool:
        """检测消息是否包含用户约束类表述。

        参数:
            message: 待检测的消息对象。
        返回值:
            True 表示该消息包含约束关键词，需要在摘要时优先保留。
        """
        if not isinstance(message, HumanMessage):
            return False

        content = str(message.content).lower()

        # 检测显式否定约束关键词
        for keyword in config.constraint_keywords_negative:
            if keyword in content:
                return True

        # 检测身材相关约束关键词
        for keyword in config.constraint_keywords_body:
            if keyword in content:
                return True

        return False

    def _stringify_messages_for_summary(self, messages: list[BaseMessage]) -> str:
        """把待摘要消息转成稳定的纯文本，便于交给模型压缩。

        对包含约束关键词的消息添加标注，提示模型优先保留。
        """
        lines: list[str] = []
        for msg in messages:
            if isinstance(msg, HumanMessage):
                role = "用户"
            elif isinstance(msg, AIMessage):
                role = "小衣"
            else:
                role = getattr(msg, "type", msg.__class__.__name__)

            # 为约束类消息添加显式标注
            prefix = "【用户明确约束】" if self._detect_constraint_message(msg) else ""
            lines.append(f"{prefix}{role}：{msg.content}")
        return "\n".join(lines)

    def _truncate_summary_text(self, summary_text: str) -> str:
        """对摘要做硬截断，避免模型不遵守长度要求时无限增长。"""
        cleaned_text = summary_text.strip()
        max_chars = int(config.chat_history_summary_max_chars)
        if len(cleaned_text) <= max_chars:
            return cleaned_text
        suffix = "\n（摘要因长度限制已截断）"
        allowed_length = max(0, max_chars - len(suffix))
        return cleaned_text[:allowed_length].rstrip() + suffix

    def summarize_chat_messages(self, previous_summary: str, messages_to_summarize: list[BaseMessage]) -> str:
        """生成滚动聊天摘要。

        参数:
            previous_summary: 之前已经持久化的摘要文本。
            messages_to_summarize: 本轮需要吸收入摘要的旧消息批次。
        返回值:
            合并旧摘要与本批旧消息后的新摘要文本。
        """
        if not messages_to_summarize:
            return self._truncate_summary_text(previous_summary)

        summary_prompt = (
            "你是聊天记忆压缩器。请把「已有长期记忆」和「新增旧对话」压缩成一份稳定、可复用的长期用户画像。\n\n"
            "要求：\n"
            f"1. 输出目标是不超过 {config.chat_history_summary_target_chars} 字，必须主动压缩，不要把旧摘要和新内容简单累加。\n"
            "2. 优先保留稳定、长期有价值的信息：身材信息、所在城市、风格偏好、禁忌、常见场景、鞋包配饰偏好。\n"
            "3. 合并同类项，删除重复表达。允许舍弃一次性、低价值、已被更稳定偏好概括的细节。\n"
            "4. 不要编造对话中没有出现的信息。\n"
            "5. 使用中文、条目化输出，内容尽量按「身材/城市/风格/禁忌/场景/鞋包配饰」归类。\n"
            f"6. 即使信息很多，也要压缩到不超过 {config.chat_history_summary_target_chars} 字附近。\n"
            "7. **关键规则**：对话中标注【用户明确约束】的消息（如「不穿XX」、「腿粗」等），必须完整保留到摘要的「禁忌」或「身材」分类中，不得删除或弱化表述。\n\n"
            f"【已有长期记忆】\n{previous_summary or '暂无'}\n\n"
            f"【新增旧对话】\n{self._stringify_messages_for_summary(messages_to_summarize)}\n\n"
            "请输出压缩后的长期用户画像："
        )
        response = self.chat_model.invoke(summary_prompt)
        content = response.content if hasattr(response, "content") else str(response)
        return self._truncate_summary_text(str(content))

    def _get_session_history(self, config: Optional[dict]) -> tuple[str, list[BaseMessage]]:
        """读取聊天历史，并打印 Supabase 查询耗时。"""
        start_time = time.time()
        normalized_config = self._normalize_config(config)
        session_id = normalized_config["configurable"]["session_id"]
        preloaded_history = normalized_config["configurable"].get("history_messages")
        if preloaded_history is not None:
            messages = self._coerce_history_messages(preloaded_history)
            print(
                f"[PERF] RagService._get_session_history took {time.time() - start_time:.3f}s (memory cache)",
                flush=True,
            )
            return session_id, messages
        try:
            history = FileChatMessageHistory(session_id=session_id)
            messages = history.get_agent_messages()
            print(f"[PERF] RagService._get_session_history took {time.time() - start_time:.3f}s", flush=True)
            return session_id, messages
        except Exception as exc:
            print(f"[WARN] 聊天历史读取不可用，已使用空历史：{exc}", flush=True)
            print(f"[PERF] RagService._get_session_history took {time.time() - start_time:.3f}s", flush=True)
            return session_id, []

    def _extract_answer_from_state(self, state) -> str:
        messages = []
        if isinstance(state, dict):
            messages = state.get("messages", [])
        elif isinstance(state, list):
            messages = state

        for msg in reversed(messages):
            if isinstance(msg, AIMessage):
                content = msg.content
                if isinstance(content, str):
                    return content
                if isinstance(content, list):
                    parts = []
                    for part in content:
                        if isinstance(part, dict) and part.get("type") == "text":
                            parts.append(part.get("text", ""))
                        else:
                            parts.append(str(part))
                    return "".join(parts).strip()
                return str(content)
        return FALLBACK_MESSAGE

    def _extract_tool_calls_from_state(self, state) -> list[dict]:
        messages = []
        if isinstance(state, dict):
            messages = state.get("messages", [])
        elif isinstance(state, list):
            messages = state

        tool_calls = []
        for msg in messages:
            for tool_call in getattr(msg, "tool_calls", []) or []:
                if isinstance(tool_call, dict):
                    tool_calls.append(tool_call)
        return tool_calls

    def _format_tool_event_label(self, tool_call: dict) -> str:
        tool_name = tool_call.get("name", "")
        args = tool_call.get("args") or {}
        if isinstance(args, dict):
            query = args.get("query") or args.get("input") or args.get("question") or ""
        else:
            query = str(args)
        query = str(query)[:60]
        emoji, verb, noun = TOOL_EVENT_LABELS.get(tool_name, ("🛠️", f"正在调用 {tool_name}", ""))
        if noun and query:
            return f"{emoji} {verb}（{noun}）：{query}"
        return f"{emoji} {verb}..."

    def _build_graph_inputs(self, inputs: dict, history_messages: list[BaseMessage]) -> dict:
        system_prompt = self._build_system_prompt(inputs)
        return {
            "messages": [
                SystemMessage(content=system_prompt),
                SystemMessage(content="以下是你们的历史对话记录："),
                *history_messages,
                HumanMessage(content=inputs.get("input", "")),
            ]
        }

    def _invoke_graph(self, inputs: dict, config: Optional[dict] = None) -> str:
        normalized_config = self._normalize_config(config)
        session_id, history_messages = self._get_session_history(normalized_config)
        graph_inputs = self._build_graph_inputs(inputs, history_messages)

        state = self.chain.invoke(graph_inputs, config=normalized_config)
        answer = self._extract_answer_from_state(state)

        try:
            history = FileChatMessageHistory(session_id=session_id)
            history.add_messages(
                [HumanMessage(content=inputs.get("input", "")), AIMessage(content=answer)]
            )
            history.maybe_update_summary(summary_updater=self.summarize_chat_messages)
        except Exception as exc:
            print(f"[WARN] 聊天历史写入不可用，已跳过持久化：{exc}", flush=True)
            import traceback
            traceback.print_exc()
        return answer

    def _weather_search(self, query: str) -> str:
        """
        查询城市当前天气。

        参数:
            query: 城市名称，如"武陟"、"北京"
        返回值:
            天气描述文本，供 LLM 阅读
        """
        result = self.weather_service.get_current_weather(query)

        # 降级返回了兜底文案字符串，直接返回
        if isinstance(result, str):
            return result

        # 否则拼接成可读文本
        city = result.get("city", query)
        text = result.get("text", "未知")
        temp = result.get("temp", "?")
        feels_like = result.get("feels_like", "?")
        wind_dir = result.get("wind_dir", "")
        wind_scale = result.get("wind_scale", "")

        return (
            f"{city} 当前天气：{text}，气温 {temp}℃"
            f"（体感 {feels_like}℃），{wind_dir}{wind_scale}"
        )

    def _knowledge_base_search(self, query: str) -> str:
        """知识库检索，支持动态 k 值和相似度过滤。

        优化点（R-005）:
        1. 根据查询类型动态调整 k 值（2-5）
        2. 使用 similarity_search_with_score 获取相似度分数
        3. 过滤低于阈值的结果
        4. 返回明确的"证据不足"状态

        参数:
            query: 用户的自然语言查询，如"羊毛衫怎么洗"、"面试穿搭注意事项"

        返回值:
            知识库文档内容，或明确的"证据不足"提示
        """
        try:
            # Step 1: 根据查询类型动态估算 Top-K（如果启用）
            if config.enable_knowledge_dynamic_k:
                k = estimate_knowledge_k(query)
                print(f"[INFO] 知识库检索使用动态 k={k}（查询类型推断）", flush=True)
            else:
                k = int(config.knowledge_retrieval_k)
                print(f"[INFO] 知识库检索使用固定 k={k}（配置值）", flush=True)

            # Step 2: 检索并获取相似度分数
            start_time = time.time()
            docs_with_scores = self.vector_service.vector_store.similarity_search_with_score(
                query, k=k
            )
            search_time = time.time() - start_time
            print(f"[PERF] 知识库检索耗时 {search_time:.3f}s，原始返回 {len(docs_with_scores)} 条", flush=True)

            result = self._classify_knowledge_results(k, docs_with_scores)
            if result.status == "no_evidence":
                return "知识库中没有相关内容，建议：基于通用穿搭常识回答，并告知用户此回答不基于知识库。"

            if result.status == "limited":
                doc, similarity = result.documents[0]
                formatted = self._format_knowledge_chunk(doc, similarity)
                return (
                    f"知识库证据有限（有效来源 {len(result.documents)} 个，相似度 {result.top_similarity:.2f}）：\n\n"
                    f"{formatted}\n\n"
                    "[注意：证据不足，回答时需谨慎，可补充通用常识]"
                )

            formatted_docs = [self._format_knowledge_chunk(doc, sim) for doc, sim in result.documents]
            return "\n\n---\n\n".join(formatted_docs)

        except Exception as exc:
            print(f"[WARN] 知识库检索失败：{exc}", flush=True)
            import traceback
            traceback.print_exc()
            return "知识库检索暂时不可用，建议基于通用常识回答。"

    def _format_knowledge_chunk(self, doc, similarity: float) -> str:
        """格式化单个知识 chunk，附带章节和位置信息。

        参数:
            doc: LangChain Document 对象
            similarity: 归一化后的相似度分数 (0-1)

        返回:
            格式化后的文本，包含来源、章节、内容
        """
        metadata = getattr(doc, "metadata", {}) or {}
        content = doc.page_content

        # 基础信息
        source = metadata.get("source", "未知来源")

        # 新增元数据（R-006）
        section = metadata.get("section_title", "")
        chunk_index = metadata.get("chunk_index")
        total_chunks = metadata.get("total_chunks")

        # 构建头部信息
        header_parts = [f"来源: {source}"]

        if section:
            header_parts.append(f"章节: {section}")

        if chunk_index is not None and total_chunks is not None:
            header_parts.append(f"片段: {chunk_index + 1}/{total_chunks}")

        header = " | ".join(header_parts)

        return f"{header}\n{content}"

    def _classify_knowledge_results(self, k: int, docs_with_scores: list) -> KnowledgeRetrievalResult:
        """按距离类型、阈值和知识来源判断证据强度。

        业务规则：同一来源的多个 chunk 只算一个有效来源，避免长文档切块数量
        误把单一来源包装成多份证据；过滤关闭时仍计算归一化分数，但不丢弃候选。
        """
        if not docs_with_scores:
            return KnowledgeRetrievalResult("no_evidence", [], None, k)

        vector_store = self.vector_service.vector_store
        metric = get_vector_distance_metric(vector_store)
        scored = []
        for doc, distance in docs_with_scores:
            similarity = normalize_vector_distance(distance, metric)
            print(
                f"[DEBUG] 文档相似度={similarity:.3f}（距离={float(distance):.3f}，类型={metric}）",
                flush=True,
            )
            if not config.enable_knowledge_similarity_filter or similarity >= config.knowledge_min_similarity:
                scored.append((doc, similarity))

        if not scored:
            return KnowledgeRetrievalResult("no_evidence", [], None, k)

        # 同一 source 的多个 chunk 只保留最高分，减少重复上下文。
        by_source = {}
        for doc, similarity in scored:
            source = str((getattr(doc, "metadata", None) or {}).get("source") or doc.page_content)
            current = by_source.get(source)
            if current is None or similarity > current[1]:
                by_source[source] = (doc, similarity)
        unique_docs = sorted(by_source.values(), key=lambda item: item[1], reverse=True)
        top_similarity = unique_docs[0][1]
        strong_threshold = float(config.knowledge_strong_similarity)
        # 业务规则：单一来源只要达到强匹配阈值即可作为充分证据；来源数量用于
        # 补充交叉验证，而不是把同一主题的权威文档强制判为证据有限。
        status = "sufficient" if top_similarity >= strong_threshold else "limited"
        print(
            f"[INFO] 相似度过滤后保留 {len(unique_docs)}/{len(docs_with_scores)} 个来源（阈值≥{config.knowledge_min_similarity}）",
            flush=True,
        )
        return KnowledgeRetrievalResult(status, unique_docs, top_similarity, k)


    def _estimate_topk(self, query: str) -> int:
        """根据query复杂度估算需要检索的Top-K数量。

        直接调用独立函数 estimate_topk_for_query()。
        """
        return estimate_topk_for_query(query)

    def _compress_wardrobe_results(self, query: str, items: list[str]) -> str:
        """简单高效的压缩策略:直接截断到Top-6,避免LLM压缩导致的格式破坏和死循环风险。

        原因:
        1. LLM压缩虽然理论上可行,但容易导致格式混乱,使AI无法正确识别item ID
        2. 这导致AI重复调用wardrobe_search,陷入死循环
        3. 直接Top-6是最稳定可靠的方案,对召回率影响有限

        参数:
            query: 用户原始查询(此方法中未使用,保留以兼容接口)
            items: 检索到的单品文本列表(格式: "- id:xxx 类别:xxx/xxx 颜色:xxx 材质:xxx 适季:xxx")

        返回:
            压缩到最多6条的单品描述文本(保留100%的原始ID格式)
        """
        # 直接截断到Top-6,保证格式完全不变
        return "\n".join(items[:6]) if len(items) > 6 else "\n".join(items)

    def _format_wardrobe_for_llm(self, items: list[str]) -> str:
        """为 LLM 格式化衣橱检索结果，确保 ID 格式清晰易提取。

        为什么这样做：
        - 返回的 items 格式为 "- id:XXXX 类别:..."
        - AI 需要从中提取 XXXX 部分作为卡片 ID
        - 通过添加更多视觉分隔符，帮助 AI 更准确地识别和提取 ID
        """
        if not items:
            return ""

        # 对每一行进行标准化处理，确保 ID 部分清晰可辨。
        # 这里再次校验是为了防止非 Chroma 实现或测试替身绕过 VectorWardrobeService。
        formatted_items = []
        for item in items:
            text = str(item or "").strip()
            match = re.search(r"(?:^|\s)-?\s*id:([^\s]+)", text)
            if not match:
                print(f"[WARN] 丢弃缺少真实 ID 的衣橱检索结果: {text[:120]}", flush=True)
                continue

            item_id = match.group(1).strip()
            if not item_id:
                continue
            formatted_items.append(text)

        return "\n".join(formatted_items)

    def _wardrobe_search(self, query: str) -> str:
        """在用户数字衣橱中检索相关单品。

        优化点（R-004）:
        1. 优先使用混合检索器（结构化过滤 + 语义排序）
        2. 回退到纯语义检索（兼容旧版本和异常场景）
        3. 根据query复杂度动态调整k值(5-15)
        4. 如果结果>8条,进行智能压缩以减少上下文污染
        5. 格式化返回结果，确保ID部分清晰易提取

        参数:
            query: 用户的自然语言查询，如"适合面试的外套"、"黑色裤子"
        返回值:
            衣橱单品描述文本列表，供 LLM 阅读。如果衣橱为空或检索服务不可用，返回提示文本。
        """
        if not self.vector_wardrobe:
            return "衣橱检索服务不可用，请提示用户先去「智能衣橱」录入单品。"

        try:
            # Step 1: 根据query复杂度动态估算Top-K
            k = self._estimate_topk(query)

            # Step 2: 检索（优先使用混合检索器）
            if self.hybrid_retriever:
                print(f"[INFO] 使用混合检索器（结构化过滤 + 语义排序），k={k}", flush=True)
                top_texts = self.hybrid_retriever.search(query, k=k)
            else:
                print(f"[INFO] 使用纯语义检索（混合检索器不可用），k={k}", flush=True)
                top_texts = self.vector_wardrobe.search(query, k=k)
            if not top_texts:
                return "衣橱中暂无相关单品，建议用户先去「智能衣橱」录入或推荐购入单品。"

            # 【调试日志】打印原始检索结果的前3条
            print(f"[DEBUG] wardrobe_search 原始返回（前3条）：", flush=True)
            for i, text in enumerate(top_texts[:3]):
                print(f"  [{i+1}] {text}", flush=True)

            # Step 3: 如果结果过多,智能压缩以减少上下文膨胀
            if len(top_texts) > 8:
                compressed = self._compress_wardrobe_results(query, top_texts)
            else:
                compressed = "\n".join(top_texts)

            # Step 4: 格式化结果，确保 ID 清晰；如果全部结果都是旧格式，
            # 返回明确的空结果提示，避免模型凭空编造卡片 ID。
            formatted = self._format_wardrobe_for_llm(compressed.split("\n"))
            if not formatted:
                print("[WARN] 衣橱检索结果全部缺少真实 ID，已阻止模型使用旧格式数据", flush=True)
                return "衣橱中暂无可用于卡片推荐的有效单品，请提示用户稍后重试。"

            # 【调试日志】打印最终发给 AI 的内容
            print(f"[DEBUG] wardrobe_search 最终返回给 AI：\n{formatted[:500]}", flush=True)

            return formatted
        except Exception as exc:
            print(f"[WARN] 衣橱检索失败：{exc}", flush=True)
            return "衣橱检索暂时不可用。"

    def _extract_json_content(self, content: str) -> str:
        if "```" in content:
            stripped = content.strip()
            if stripped.startswith("```"):
                stripped = stripped.strip("`")
            stripped = stripped.replace("json", "", 1).strip()
            return stripped
        return content.strip()

    def _format_wardrobe_items(self, items: list[dict]) -> str:
        lines = []
        for item in items:
            item_id = item.get("id", "")
            category = item.get("category", "")
            sub_category = item.get("sub_category", "")
            color = item.get("color", "")
            material = item.get("material", "")
            season = item.get("season", "")
            lines.append(
                f"- id:{item_id} 类别:{category}/{sub_category} 颜色:{color} 材质:{material} 适季:{season}"
            )
        return "\n".join(lines) if lines else "暂无可用单品"

    def generate_weekly_plan(
        self,
        user_profile: dict,
        current_date: str,
        wardrobe_items: list[dict],
        status_container=None,
    ) -> list[dict]:
        gender = user_profile.get("gender", "未设置")
        style = user_profile.get("style", "未设置")
        body = user_profile.get("body", "") or "未设置"
        city = user_profile.get("city", "未设置") or "未设置"

        # Step 1: 一次性获取未来一周天气
        if status_container:
            status_container.update(label="🌤️ 正在为您观测未来一周天象...")

        forecast_result = self.weather_service.get_forecast_7d(city)

        # 判断返回类型：降级文案 str 或正常数据 list
        if isinstance(forecast_result, str):
            # 降级：直接使用兜底文案
            print(f"[WARN] 周计划天气查询失败，使用降级文案", flush=True)
            weather_info = forecast_result
        else:
            # 正常：拼接成 LLM 可读的天气描述
            weather_lines = []
            for day_data in forecast_result:
                date = day_data.get("date", "")
                text_day = day_data.get("text_day", "")
                temp_max = day_data.get("temp_max", "")
                temp_min = day_data.get("temp_min", "")
                weather_lines.append(
                    f"{date} {text_day} {temp_min}~{temp_max}℃"
                )
            weather_info = "\n".join(weather_lines)

        available_items = copy.deepcopy(wardrobe_items or [])
        wardrobe_text = self._format_wardrobe_items(available_items)

        # 解析日期，生成7天标签
        try:
            current_dt = datetime.datetime.strptime(current_date, "%Y年%m月%d日")
        except ValueError:
            current_dt = datetime.datetime.now()
        weekdays = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
        day_labels = []
        for i in range(7):
            d = current_dt + datetime.timedelta(days=i)
            day_labels.append(f"{d.strftime('%m月%d日')} {weekdays[d.weekday()]}")

        theme_pool = [
            "轻松通勤感",
            "温柔日常感",
            "活力运动感",
            "简约高级感",
            "甜酷混搭感",
            "松弛休闲感",
            "精致约会感",
        ]

        # Step 2: 构建全局规划 Prompt
        theme_lines = "\n".join(f"· {day_labels[i]}  →  {theme_pool[i]}" for i in range(7))
        prompt = WEEKLY_PLAN_PROMPT.format(
            gender=gender,
            style=style,
            body=body,
            city=city,
            weather_info=weather_info,
            theme_lines=theme_lines,
            wardrobe_text=wardrobe_text,
        )

        # Step 3: 结构化输出（优先 with_structured_output，失败回退 JSON 模式）
        if status_container:
            status_container.update(label="🧠 正在结合您的数字衣橱进行全局规划...")
        try:
            structured_model = self.chat_model.with_structured_output(WeeklyPlan)
            result: WeeklyPlan = structured_model.invoke(prompt)
            return [day.model_dump() for day in result.days]
        except Exception:
            fallback_suffix = """

【输出格式要求】
仅输出一个 JSON 对象，格式如下，不要包含任何其他文字或 markdown 标记：
{
  "days": [
    {
      "scene": "今日场景感知描述",
      "ootd": [
        {"desc": "【自有】**单品名称** + 搭配理由", "id": "衣橱中的精确id"},
        {"desc": "【建议购入】**单品名称** + 理由", "id": ""}
      ],
      "tips": "穿搭小贴士"
    },
    ...共7个元素，对应上述7天...
  ]
}"""
            response = self.chat_model.invoke(prompt + fallback_suffix)
            content = response.content if hasattr(response, "content") else str(response)
            content_text = self._extract_json_content(str(content))
            data = json.loads(content_text)
            return data.get("days", data if isinstance(data, list) else [])

    def __get_chain(self):
        """获取 LangGraph ReAct Agent，并打印组装工具链耗时。"""
        start_time = time.time()
        create_react_agent = self._get_langgraph_factory()

        # 1. 知识库工具（始终注册，使用自定义方法替代 retriever）
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
        tools = [knowledge_tool]

        # 2. 天气工具（仅在服务可用时注册）
        if self.weather_service.available:
            search_tool = Tool(
                name="weather_search",
                description=(
                    "用于查询【指定城市】的当前实时天气。"
                    "输入参数：城市名称（如'武陟'、'北京'、'上海'）。"
                    "返回：该城市的实时天气状况，包括天气描述、温度、体感温度、风向风力等信息。"
                ),
                func=self._weather_search,
            )
            tools.append(search_tool)
        else:
            print(
                "[INFO] 天气工具未注册：和风天气服务不可用。"
                "Agent 将基于季节常识和用户偏好进行穿搭推荐。",
                flush=True
            )

        # 3. 衣橱工具（仅在服务可用时注册）
        if self.vector_wardrobe:
            wardrobe_tool = Tool(
                name="wardrobe_search",
                description=(
                    "在用户的数字衣橱中检索相关单品。"
                    "输入参数：自然语言查询，如'适合面试的外套'、'黑色裤子'、'春季内搭'。"
                    "返回：衣橱中符合查询条件的单品列表，包括id、类别、颜色、材质、适季等信息。"
                    "使用场景：当需要基于用户已有衣橱推荐穿搭、组合搭配、或检查是否有某类单品时，必须调用此工具。"
                ),
                func=self._wardrobe_search,
            )
            tools.append(wardrobe_tool)
        else:
            print(
                "[INFO] 衣橱工具未注册：衣橱向量服务不可用。"
                "Agent 将基于用户偏好和知识库进行穿搭推荐。",
                flush=True
            )

        chain = create_react_agent(self.chat_model, tools)
        print(f"[PERF] RagService.__get_chain took {time.time() - start_time:.3f}s", flush=True)
        return chain


if __name__ == "__main__":
    session_config = {
        "configurable": {
            "session_id": "user_001",
        }
    }
    res = RagService().invoke(
        {
            "input": "羽绒服怎么处理",
            "gender": "女生",
            "style": "日常休闲",
            "body": "",
            "current_date": "2026年05月20日",
        },
        session_config,
    )
    print(res)
