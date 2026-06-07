from typing import Optional

import datetime
import copy
import json
import re

from pydantic import BaseModel, Field

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_core.tools import Tool
from history import FileChatMessageHistory
from vector_store_service import VectorStoreService, VectorWardrobeService
from prompts import RAG_SYSTEM_PROMPT, WEEKLY_PLAN_PROMPT
from langchain_community.embeddings import DashScopeEmbeddings
import config_data as config
from langchain_community.chat_models.tongyi import ChatTongyi
from langchain_community.tools import DuckDuckGoSearchRun
from langchain.tools.retriever import create_retriever_tool


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
MAX_AGENT_RECURSION_LIMIT = 8
MAX_WEATHER_TOOL_CALLS_PER_TURN = 1
MAX_TOTAL_TOOL_CALLS_PER_TURN = 4


TOOL_EVENT_LABELS = {
    "weather_search": ("🌤️", "正在观测天象", "查询天气"),
    "knowledge_base_search": ("📚", "正在翻阅时尚秘籍", "检索穿搭知识"),
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
    def __init__(self, vector_wardrobe: Optional[VectorWardrobeService] = None, user_id: str = ""):
        self.vector_wardrobe = vector_wardrobe
        self.user_id = user_id

        self.vector_service = VectorStoreService(
            embedding=DashScopeEmbeddings(model=config.EMBEDDING_MODEL_NAME),
            user_id=user_id,
        )

        self.chat_model = ChatTongyi(model=config.chat_model_name)

        self.chain = self.__get_chain()

    def _with_current_date(self, inputs: dict) -> dict:
        if "current_date" in inputs:
            return inputs
        updated_inputs = dict(inputs)
        updated_inputs["current_date"] = datetime.datetime.now().strftime("%Y年%m月%d日")
        return updated_inputs

    def _prepare_inputs(self, inputs: dict) -> dict:
        """预处理输入：注入当前日期，并通过向量检索压缩衣橱文本。"""
        inputs = self._with_current_date(inputs)
        if self.vector_wardrobe:
            query = inputs.get("input", "")
            wardrobe_text = inputs.get("wardrobe", "")
            if query and wardrobe_text:
                top_texts = self.vector_wardrobe.search(query, k=15)
                if top_texts:
                    inputs["wardrobe"] = "\n".join(top_texts)
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
            prepared_inputs = self._prepare_inputs(inputs)
            normalized_config = self._normalize_config(config)
            session_id, history_messages = self._get_session_history(normalized_config)
            graph_inputs = self._build_graph_inputs(prepared_inputs, history_messages)

            yield {"type": "status", "label": "🤔 正在理解你的需求，构思搭配方向..."}

            last_state = None
            seen_tool_call_ids = set()
            observed_tool_calls = []
            for state in self.chain.stream(graph_inputs, config=normalized_config, stream_mode="values"):
                last_state = state
                for tool_call in self._extract_tool_calls_from_state(state):
                    call_id = tool_call.get("id") or json.dumps(tool_call, ensure_ascii=False, sort_keys=True)
                    if call_id in seen_tool_call_ids:
                        continue
                    seen_tool_call_ids.add(call_id)
                    observed_tool_calls.append(tool_call)
                    yield {"type": "status", "label": self._format_tool_event_label(tool_call)}
                    yield {"type": "status", "label": "✅ 信息已获取，继续优化方案..."}
                    if self._should_stop_streaming_for_tool_limits(observed_tool_calls):
                        yield {"type": "status", "label": "🛑 已达到工具调用上限，基于现有信息整理最终建议..."}
                        break
                else:
                    continue
                break

            yield {"type": "status", "label": "✨ 灵感迸发，正在为你整理专属穿搭方案..."}

            answer = self._extract_answer_from_state(last_state)
            try:
                FileChatMessageHistory(session_id=session_id).add_messages(
                    [HumanMessage(content=prepared_inputs.get("input", "")), AIMessage(content=answer)]
                )
            except Exception as exc:
                print(f"[WARN] 聊天历史写入不可用，已跳过持久化：{exc}", flush=True)

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
        config.setdefault("recursion_limit", MAX_AGENT_RECURSION_LIMIT)
        return config

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

    def _get_session_history(self, config: Optional[dict]) -> tuple[str, list[BaseMessage]]:
        normalized_config = self._normalize_config(config)
        session_id = normalized_config["configurable"]["session_id"]
        try:
            history = FileChatMessageHistory(session_id=session_id)
            return session_id, history.messages
        except Exception as exc:
            print(f"[WARN] 聊天历史读取不可用，已使用空历史：{exc}", flush=True)
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

    def _should_stop_streaming_for_tool_limits(self, tool_calls: list[dict]) -> bool:
        if len(tool_calls) >= MAX_TOTAL_TOOL_CALLS_PER_TURN:
            return True
        weather_calls = sum(1 for tool_call in tool_calls if tool_call.get("name") == "weather_search")
        return weather_calls >= MAX_WEATHER_TOOL_CALLS_PER_TURN

    def _sanitize_weather_search_result(self, raw_result: str, query: str) -> str:
        text = re.sub(r"\s+", " ", str(raw_result or "")).strip()
        if not text:
            return (
                "【天气查询已完成】未获取到稳定的实时天气结果。"
                "请不要再次查询天气，直接结合当前月份、用户所在城市的季节气候和具体场景完成穿搭建议。"
            )

        lines = []
        for part in re.split(r"[\n。；;]+", text):
            cleaned = part.strip()
            if len(cleaned) < 6:
                continue
            if any(keyword in cleaned.lower() for keyword in ["http", "www", "duckduckgo", "search"]):
                continue
            lines.append(cleaned)

        if not lines:
            return (
                f"【天气查询已完成】已查询：{query}。"
                "原始搜索结果噪音较大，未能提炼出稳定天气。"
                "请不要再次查询天气，直接结合当前月份、用户所在城市的季节气候和用户场景完成穿搭建议。"
            )

        summary = "；".join(lines[:4])[:500]
        return (
            f"【天气查询已完成】查询：{query}。"
            f"可用摘要：{summary}。"
            "请基于以上结果继续给出穿搭建议，不要再次调用 weather_search。"
        )

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
            FileChatMessageHistory(session_id=session_id).add_messages(
                [HumanMessage(content=inputs.get("input", "")), AIMessage(content=answer)]
            )
        except Exception as exc:
            print(f"[WARN] 聊天历史写入不可用，已跳过持久化：{exc}", flush=True)
        return answer

    def _weather_search(self, query: str) -> str:
        current_year = datetime.datetime.now().year
        current_month = datetime.datetime.now().month
        query_with_date = f"{query} {current_year}年{current_month}月"

        max_retries = 2
        for attempt in range(max_retries):
            try:
                raw_result = DuckDuckGoSearchRun().run(query_with_date)
                return self._sanitize_weather_search_result(raw_result, query_with_date)
            except Exception:
                if attempt < max_retries - 1:
                    continue
                return (
                    "【天气查询已完成】由于网络原因无法获取稳定的实时天气。"
                    "请不要再次查询天气，仅根据用户所在城市当前的普遍季节气候与具体场景，为其规划穿搭。"
                )

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
        weather_info = self._weather_search(f"{city} 未来一周 天气")
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
        """获取 LangGraph ReAct Agent。"""
        retriever = self.vector_service.get_retriever()
        create_react_agent = self._get_langgraph_factory()

        # 1. 创建工具
        search_tool = Tool(
            name="weather_search",
            description=(
                "用于查询【指定城市】的近期天气。调用此工具时，【必须】从用户档案中提取"
                "【所在城市】（例如'武陟'）构造查询参数，格式为'城市名 天气'（如'武陟 天气'）。"
                "严禁查询'全国天气'、'全国'或任何不包含具体城市名的模糊查询。"
                "搜索结果中如果包含多个日期的天气数据，只使用距离今天最近的数据，忽略超过3天前的数据。"
                "每轮问答中天气最多查询一次；只要工具返回了结果，无论结果是否完整，都不要再次调用该工具，而应直接基于已有天气信息继续回答。"
            ),
            func=self._weather_search,
        )
        retriever_tool = create_retriever_tool(
            retriever,
            "knowledge_base_search",
            "当用户询问关于服装洗涤、尺码推荐、颜色搭配等通用穿搭知识时，必须使用此工具。",
        )
        tools = [search_tool, retriever_tool]
        return create_react_agent(self.chat_model, tools)


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
