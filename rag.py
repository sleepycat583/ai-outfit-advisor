from typing import Optional

import datetime
import copy
import json
import time
import uuid

from pydantic import BaseModel, Field

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    RemoveMessage,
    SystemMessage,
)

REMOVE_ALL_MESSAGES = "__remove_all__"
from langchain_core.tools import Tool, create_retriever_tool
from history import FileChatMessageHistory
from vector_store_service import VectorStoreService, VectorWardrobeService
from prompts import RAG_SYSTEM_PROMPT, WEEKLY_PLAN_PROMPT
from langchain_community.embeddings import DashScopeEmbeddings
import config_data as config
import config_data as app_config
from langchain_community.chat_models.tongyi import ChatTongyi

from native_memory import NativeMemoryRuntime, native_memory_requested
from weather_service import WeatherService
from conversation_service import ConversationRepository
from memory_store import SupabaseMemoryStore
from memory_jobs import MemoryJobRepository, make_turn_job
from supabase_config import get_supabase_client


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
}
_CHECKPOINTER_UNSET = object()


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
    def __init__(self, vector_wardrobe: Optional[VectorWardrobeService] = None, user_id: str = ""):
        """初始化 RAG 服务，并打印模型、向量库、LangGraph 组装耗时。"""
        start_time = time.time()
        self.vector_wardrobe = vector_wardrobe
        self.user_id = user_id
        self.conversation_repo = ConversationRepository(schema=config.MEMORY_PRIVATE_SCHEMA)
        self.native_memory = None
        self.checkpointer = None
        self._native_degraded_threads: set[str] = set()
        self._native_pending_removals: list[str] = []
        self._native_pending_reset_messages: list[BaseMessage] = []
        self.memory_store = None
        # 传入 Supabase 客户端以启用天气缓存功能
        self.weather_service = WeatherService(supabase_client=get_supabase_client())
        if config.LONG_TERM_MEMORY_ENABLED:
            try:
                self.memory_store = SupabaseMemoryStore(
                    user_id=user_id, schema=config.MEMORY_PRIVATE_SCHEMA
                )
                # Probe the private table once during startup so a missing
                # migration fails before an answer is served.
                self.memory_store.list_for_user(user_id, limit=1)
                print("[MEMORY] long-term BaseStore enabled", flush=True)
            except Exception as exc:
                print(f"[WARN] long-term memory unavailable; feature disabled: {exc}", flush=True)
        if native_memory_requested():
            try:
                self.native_memory = NativeMemoryRuntime.connect(user_id=user_id)
                self.checkpointer = self.native_memory.checkpointer
                print("[MEMORY] native PostgresSaver enabled", flush=True)
            except Exception as exc:
                if config.MEMORY_BACKEND == "native" and not config.MEMORY_NATIVE_FALLBACK:
                    raise
                print(f"[WARN] native PostgresSaver unavailable; using legacy memory: {exc}", flush=True)

        self.vector_service = VectorStoreService(
            embedding=DashScopeEmbeddings(model=config.EMBEDDING_MODEL_NAME),
            user_id=user_id,
        )

        self.chat_model = ChatTongyi(model=config.chat_model_name)

        self.chain = self.__get_chain()
        self.legacy_chain = self.__get_chain(checkpointer=None) if self.checkpointer is not None else self.chain
        print(f"[PERF] RagService.__init__ took {time.time() - start_time:.3f}s", flush=True)

    def _with_current_date(self, inputs: dict) -> dict:
        if "current_date" in inputs:
            return inputs
        updated_inputs = dict(inputs)
        updated_inputs["current_date"] = datetime.datetime.now().strftime("%Y年%m月%d日")
        return updated_inputs

    def _prepare_inputs(self, inputs: dict) -> dict:
        """预处理输入：注入当前日期，并通过向量检索压缩衣橱文本。"""
        start_time = time.time()
        inputs = self._with_current_date(inputs)
        if self.vector_wardrobe:
            query = inputs.get("input", "")
            wardrobe_text = inputs.get("wardrobe", "")
            if query and wardrobe_text:
                top_texts = self.vector_wardrobe.search(query, k=15)
                if top_texts:
                    inputs["wardrobe"] = "\n".join(top_texts)
        if getattr(self, "memory_store", None) is not None and self.user_id:
            try:
                memories = self.memory_store.recall(self.user_id, inputs.get("input", ""), limit=5)
                memory_lines = [
                    f"- {item.key}: {json.dumps(item.value, ensure_ascii=False)}"
                    for item in memories
                ]
                inputs["long_term_memory"] = "\n".join(memory_lines)[:1200]
            except Exception as exc:
                # Memory recall is helpful context, not a reason to reject a
                # user question during a partial rollout.
                print(f"[WARN] long-term memory recall skipped: {exc}", flush=True)
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
        prepared_inputs = None
        normalized_config = None
        try:
            total_start = time.time()
            prepared_inputs = self._prepare_inputs(inputs)
            normalized_config = self._normalize_config(config)
            session_id, history_messages = self._get_session_history(normalized_config)
            if getattr(self, "checkpointer", None) is not None and self._is_native_degraded(session_id):
                answer = self._invoke_legacy_graph(prepared_inputs, normalized_config)
                yield {"type": "status", "label": "⚠️ 原生记忆处于降级状态，使用兼容链"}
                yield {"type": "answer", "content": answer}
                return
            graph_inputs = self._build_graph_inputs(
                prepared_inputs,
                history_messages,
                include_system=True if self.checkpointer is not None else not self._native_has_checkpoint(normalized_config),
            )

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
                storage_session_id = (
                    ConversationRepository.legacy_session_id(session_id)
                    if self.checkpointer is not None
                    else session_id
                )
                if self._should_write_legacy():
                    history = FileChatMessageHistory(session_id=storage_session_id)
                    history.add_messages(
                        [HumanMessage(content=prepared_inputs.get("input", "")), AIMessage(content=answer)]
                    )
                    history.maybe_update_summary(summary_updater=self.summarize_chat_messages)
            except Exception as exc:
                print(f"[WARN] 聊天历史写入不可用，已跳过持久化：{exc}", flush=True)

            self._enqueue_memory_extraction(
                session_id, prepared_inputs.get("input", ""), answer
            )

            print(f"[PERF] RagService.stream_events total took {time.time() - total_start:.3f}s", flush=True)
            yield {"type": "answer", "content": answer}
        except Exception as exc:
            if (
                self.checkpointer is not None
                and app_config.MEMORY_NATIVE_FALLBACK
                and prepared_inputs is not None
                and normalized_config is not None
            ):
                try:
                    self._mark_native_degraded(
                        normalized_config["configurable"]["session_id"], str(exc)
                    )
                    answer = self._invoke_legacy_graph(prepared_inputs, normalized_config)
                    yield {"type": "status", "label": "⚠️ 原生记忆暂不可用，已安全回退"}
                    yield {"type": "answer", "content": answer}
                    return
                except Exception as fallback_exc:
                    print(f"[WARN] native and legacy graph fallback failed: {fallback_exc}", flush=True)
            print(f"[WARN] RagService.stream_events failed: {exc}", flush=True)
            yield {"type": "error", "content": FALLBACK_MESSAGE}

    def invoke(self, inputs: dict, config: Optional[dict] = None):
        try:
            prepared_inputs = self._prepare_inputs(inputs)
            return self._invoke_graph(prepared_inputs, config=config)
        except Exception:
            return FALLBACK_MESSAGE

    def _get_langgraph_factory(self):
        try:
            from langchain.agents import create_agent

            return create_agent
        except Exception as exc:
            raise RuntimeError(LANGGRAPH_IMPORT_ERROR_MESSAGE) from exc

    def _normalize_config(self, config: Optional[dict] = None) -> dict:
        config = dict(config or {})
        configurable = dict(config.get("configurable") or {})
        session_id = (
            configurable.get("conversation_id")
            or configurable.get("session_id")
            or configurable.get("thread_id")
        )
        if not session_id:
            if self.user_id and native_memory_requested():
                session_id = ConversationRepository.legacy_id(self.user_id)
            else:
                session_id = f"chat_session_{self.user_id}" if self.user_id else "default_session"
        if self.user_id:
            repository = getattr(
                self,
                "conversation_repo",
                ConversationRepository(schema=app_config.MEMORY_PRIVATE_SCHEMA),
            )
            requested_id = bool(
                configurable.get("conversation_id")
                or configurable.get("session_id")
                or configurable.get("thread_id")
            )
            if requested_id:
                validator = getattr(repository, "ensure_existing", None) or getattr(repository, "ensure")
            else:
                validator = getattr(repository, "ensure")
            validator(self.user_id, session_id)
        # conversation_id is the sole canonical identity.  Never preserve a
        # conflicting caller-supplied thread_id: the repository validates this
        # id before LangGraph receives it.
        configurable["thread_id"] = session_id
        configurable["session_id"] = session_id
        configurable["conversation_id"] = session_id
        config["configurable"] = configurable
        return config

    def _should_write_legacy(self) -> bool:
        """决定是否继续写旧 transcript，支持 native 灰度回滚。"""
        return getattr(self, "checkpointer", None) is None or config.MEMORY_DUAL_WRITE

    def _mark_native_degraded(self, session_id: str, error: str) -> None:
        """保留既有 checkpoint，只把失败 thread 隔离到 legacy 路径。"""
        degraded = getattr(self, "_native_degraded_threads", None)
        if degraded is None:
            degraded = set()
            self._native_degraded_threads = degraded
        degraded.add(session_id)
        try:
            repository = getattr(self, "conversation_repo", None)
            mark = getattr(repository, "mark_native_degraded", None)
            if mark is not None and self.user_id:
                mark(self.user_id, session_id, error)
        except Exception as exc:
            print(f"[WARN] native degraded marker write failed: {exc}", flush=True)

    def _is_native_degraded(self, session_id: str) -> bool:
        if session_id in getattr(self, "_native_degraded_threads", set()):
            return True
        try:
            repository = getattr(self, "conversation_repo", None)
            check = getattr(repository, "is_native_degraded", None)
            return bool(check and self.user_id and check(self.user_id, session_id))
        except Exception as exc:
            print(f"[WARN] native degraded marker lookup failed: {exc}", flush=True)
            return False

    def _enqueue_memory_extraction(self, conversation_id: str, user_text: str, answer: str) -> None:
        if (
            not app_config.MEMORY_ASYNC_EXTRACTION_ENABLED
            or not app_config.LONG_TERM_MEMORY_ENABLED
            or not self.user_id
        ):
            return
        # 每次成功回答都是独立 turn；内容相同也不能丢掉后续记忆提取任务。
        turn_id = uuid.uuid4().hex
        try:
            job = make_turn_job(
                user_id=self.user_id,
                conversation_id=conversation_id,
                turn_id=turn_id,
                messages=[HumanMessage(content=user_text), AIMessage(content=answer)],
            )
            if job is None:
                return
            repository = getattr(self, "memory_job_repository", None)
            if repository is None:
                repository = MemoryJobRepository(
                    schema=app_config.MEMORY_PRIVATE_SCHEMA,
                    queue_name=app_config.MEMORY_JOB_QUEUE_NAME,
                )
            repository.enqueue(job)
        except Exception as exc:
            print(f"[WARN] async memory extraction enqueue skipped: {exc}", flush=True)

    def _build_system_prompt(self, inputs: dict) -> str:
        prompt_inputs = {
            "current_date": inputs.get("current_date", datetime.datetime.now().strftime("%Y年%m月%d日")),
            "gender": inputs.get("gender", "未设置"),
            "style": inputs.get("style", "未设置"),
            "body": inputs.get("body", ""),
            "city": inputs.get("city", ""),
            "wardrobe": inputs.get("wardrobe", "暂无已录入的单品（请先去「智能衣橱」拍照上传）"),
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
        if getattr(self, "checkpointer", None) is not None:
            # 首次迁移的 thread 尚无 checkpoint 时导入 legacy 窗口一次；
            # 后续完全由 saver 管理，避免每轮重复追加 transcript。
            if self._native_has_messages(normalized_config):
                return session_id, []
        try:
            storage_session_id = (
                ConversationRepository.legacy_session_id(session_id)
                if getattr(self, "checkpointer", None) is not None
                else session_id
            )
            history = FileChatMessageHistory(session_id=storage_session_id)
            messages = history.get_agent_messages()
            print(f"[PERF] RagService._get_session_history took {time.time() - start_time:.3f}s", flush=True)
            return session_id, messages
        except Exception as exc:
            print(f"[WARN] 聊天历史读取不可用，已使用空历史：{exc}", flush=True)
            print(f"[PERF] RagService._get_session_history took {time.time() - start_time:.3f}s", flush=True)
            return session_id, []

    def _native_has_checkpoint(self, normalized_config: dict) -> bool:
        """判断原生 checkpoint 是否已有该 thread 的状态。

        首次调用需要写入动态系统提示；后续调用由 LangGraph checkpoint
        恢复既有消息，避免重复追加 system message。查询失败时按首次调用
        处理，让 saver 自身决定是否可以继续，且不影响 legacy 回退路径。
        """
        if getattr(self, "checkpointer", None) is None:
            return False
        try:
            return self.checkpointer.get_tuple(normalized_config) is not None
        except Exception as exc:
            print(f"[WARN] native checkpoint lookup failed; treating as new thread: {exc}", flush=True)
            return False

    def _native_has_messages(self, normalized_config: dict) -> bool:
        if getattr(self, "checkpointer", None) is None:
            return False
        try:
            checkpoint_tuple = self.checkpointer.get_tuple(normalized_config)
            if checkpoint_tuple is None:
                return False
            values = checkpoint_tuple.checkpoint.get("channel_values", {})
            messages = values.get("messages", [])
            legacy_system_messages = [
                message
                for message in messages
                if isinstance(message, SystemMessage)
                and not getattr(message, "id", None)
            ]
            if legacy_system_messages:
                self._native_pending_reset_messages = [
                    message for message in messages if not isinstance(message, SystemMessage)
                ]
            self._native_pending_removals = [
                message.id
                for message in messages
                if isinstance(message, SystemMessage)
                and getattr(message, "id", None)
                and message.id not in {"native-dynamic-system", "native-long-term-memory"}
            ]
            return bool(messages)
        except Exception as exc:
            print(f"[WARN] native message lookup failed; treating thread as empty: {exc}", flush=True)
            return False

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

    def _build_graph_inputs(
        self,
        inputs: dict,
        history_messages: list[BaseMessage],
        *,
        include_system: bool = True,
    ) -> dict:
        system_prompt = self._build_system_prompt(inputs)
        pending_removals = [RemoveMessage(id=message_id) for message_id in getattr(self, "_native_pending_removals", [])]
        self._native_pending_removals = []
        pending_reset_messages = getattr(self, "_native_pending_reset_messages", [])
        self._native_pending_reset_messages = []
        if pending_reset_messages:
            pending_removals = [RemoveMessage(id=REMOVE_ALL_MESSAGES)]
        messages = pending_removals
        if include_system:
            messages.append(SystemMessage(content=system_prompt, id="native-dynamic-system"))
        if include_system:
            long_term_memory = inputs.get("long_term_memory") or "暂无额外的长期记忆。"
            messages.append(
                SystemMessage(
                    content=(
                        "以下是用户跨会话明确保存的长期记忆，仅在与当前问题相关时使用；"
                        "如与用户当前明确说明冲突，以当前说明为准：\n"
                        f"{long_term_memory}"
                    ),
                    id="native-long-term-memory",
                )
            )
        if getattr(self, "checkpointer", None) is None or history_messages:
            messages.append(SystemMessage(content="以下是你们的历史对话记录："))
            messages.extend(history_messages)
        messages.extend(pending_reset_messages)
        messages.append(HumanMessage(content=inputs.get("input", "")))
        return {"messages": messages}

    def _invoke_graph(self, inputs: dict, config: Optional[dict] = None) -> str:
        normalized_config = self._normalize_config(config)
        session_id, history_messages = self._get_session_history(normalized_config)
        if getattr(self, "checkpointer", None) is not None and self._is_native_degraded(session_id):
            return self._invoke_legacy_graph(inputs, normalized_config)
        graph_inputs = self._build_graph_inputs(
            inputs,
            history_messages,
            include_system=True if self.checkpointer is not None else not self._native_has_checkpoint(normalized_config),
        )

        try:
            state = self.chain.invoke(graph_inputs, config=normalized_config)
        except Exception as exc:
            if self.checkpointer is None or not app_config.MEMORY_NATIVE_FALLBACK:
                raise
            self._mark_native_degraded(session_id, str(exc))
            print(f"[WARN] native graph failed; using legacy chain: {exc}", flush=True)
            return self._invoke_legacy_graph(inputs, normalized_config)
        answer = self._extract_answer_from_state(state)

        try:
            storage_session_id = (
                ConversationRepository.legacy_session_id(session_id)
                if self.checkpointer is not None
                else session_id
            )
            if self._should_write_legacy():
                history = FileChatMessageHistory(session_id=storage_session_id)
                history.add_messages(
                    [HumanMessage(content=inputs.get("input", "")), AIMessage(content=answer)]
                )
                history.maybe_update_summary(summary_updater=self.summarize_chat_messages)
        except Exception as exc:
            print(f"[WARN] 聊天历史写入不可用，已跳过持久化：{exc}", flush=True)
        self._enqueue_memory_extraction(session_id, inputs.get("input", ""), answer)
        return answer

    def _invoke_legacy_graph(self, inputs: dict, normalized_config: dict) -> str:
        """在 native checkpoint 失败时执行一次无 checkpoint 的兼容链。"""
        session_id = normalized_config["configurable"]["session_id"]
        storage_session_id = (
            ConversationRepository.legacy_session_id(session_id)
            if getattr(self, "checkpointer", None) is not None
            else session_id
        )
        try:
            history_messages = FileChatMessageHistory(session_id=storage_session_id).get_agent_messages()
        except Exception:
            history_messages = []
        graph_inputs = self._build_graph_inputs(
            inputs,
            history_messages,
            include_system=True,
        )
        legacy_chain = getattr(self, "legacy_chain", self.chain)
        state = legacy_chain.invoke(graph_inputs, config=normalized_config)
        answer = self._extract_answer_from_state(state)
        try:
            history = FileChatMessageHistory(session_id=storage_session_id)
            history.add_messages([HumanMessage(content=inputs.get("input", "")), AIMessage(content=answer)])
            history.maybe_update_summary(summary_updater=self.summarize_chat_messages)
        except Exception as exc:
            print(f"[WARN] legacy fallback history write failed: {exc}", flush=True)
        self._enqueue_memory_extraction(session_id, inputs.get("input", ""), answer)
        return answer

    def _weather_search(self, query: str) -> str:
        """查询指定城市的当前天气（Agent 工具调用入口）。

        参数:
            query: 城市名称，如"武陟"、"北京"
        返回值:
            天气描述文本，供 LLM 阅读
        """
        try:
            weather_data = self.weather_service.get_current_weather(query)

            # 如果降级返回了兜底文案字符串，直接返回
            if isinstance(weather_data, str):
                return weather_data

            # 拼接成自然语言描述
            city = weather_data.get("city", query)
            temp = weather_data.get("temp", "")
            feels_like = weather_data.get("feels_like", "")
            text = weather_data.get("text", "")
            wind_dir = weather_data.get("wind_dir", "")
            wind_scale = weather_data.get("wind_scale", "")

            return (
                f"{city} 当前天气：{text}，气温 {temp}℃"
                f"（体感 {feels_like}℃），{wind_dir}{wind_scale}"
            )
        except Exception as exc:
            # 失败降级：使用 WeatherService 内置的 fallback
            print(f"[WARN] _weather_search 失败: {exc}", flush=True)
            result = self.weather_service.get_weather_with_fallback(query, data_type="now")
            if isinstance(result, str):
                return result
            # 如果 fallback 返回了 dict，再次拼接
            return f"{query} 当前天气：{result.get('text', '未知')}"

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

        try:
            forecast_list = self.weather_service.get_forecast_7d(city)
            # 拼接成 LLM 可读的天气描述
            weather_lines = []
            for day_data in forecast_list:
                date = day_data.get("date", "")
                text_day = day_data.get("text_day", "")
                text_night = day_data.get("text_night", "")
                temp_min = day_data.get("temp_min", "")
                temp_max = day_data.get("temp_max", "")
                weather_lines.append(
                    f"· {date} {text_day}转{text_night}，{temp_min}~{temp_max}℃"
                )
            weather_info = "\n".join(weather_lines)
        except Exception as exc:
            print(f"[WARN] 周计划天气查询失败: {exc}", flush=True)
            # 降级：使用兜底文案
            season = self.weather_service._get_current_season()
            weather_info = (
                f"【系统提示】：无法获取 {city} 的未来一周天气数据（API 限流或网络异常）。"
                f"请根据当前季节（{season}）的普遍气候特征规划穿搭。"
            )

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

    def __get_chain(self, checkpointer=_CHECKPOINTER_UNSET):
        """获取 LangGraph ReAct Agent，并打印组装工具链耗时。"""
        start_time = time.time()
        retriever = self.vector_service.get_retriever()
        create_agent_factory = self._get_langgraph_factory()

        # 1. 创建工具
        search_tool = Tool(
            name="weather_search",
            description=(
                "用于查询【指定城市】的当前天气。调用此工具时，query 参数必须是具体城市名称"
                "（例如 query='武陟'），返回该城市当前的温度、天气现象、风力等信息。"
            ),
            func=self._weather_search,
        )
        retriever_tool = create_retriever_tool(
            retriever,
            "knowledge_base_search",
            "当用户询问关于服装洗涤、尺码推荐、颜色搭配等通用穿搭知识时，必须使用此工具。",
        )
        tools = [search_tool, retriever_tool]
        chain = create_agent_factory(
            model=self.chat_model,
            tools=tools,
            checkpointer=(
                getattr(self, "checkpointer", None)
                if checkpointer is _CHECKPOINTER_UNSET
                else checkpointer
            ),
            store=getattr(self, "memory_store", None),
        )
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
