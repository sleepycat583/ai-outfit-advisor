from typing import Optional

import datetime
import copy
import json

from pydantic import BaseModel, Field

from langchain_core.runnables.history import RunnableWithMessageHistory
from langchain_core.runnables import RunnableLambda
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import BaseMessage, SystemMessage, HumanMessage
from langchain_core.tools import Tool
from history import FileChatMessageHistory
from vector_store_service import VectorStoreService, VectorWardrobeService
from prompts import RAG_SYSTEM_PROMPT, WEEKLY_PLAN_PROMPT
from langchain_community.embeddings import DashScopeEmbeddings
import config_data as config
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_community.chat_models.tongyi import ChatTongyi
from langchain_community.tools import DuckDuckGoSearchRun
from langchain.agents import create_tool_calling_agent, AgentExecutor
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


class ConsoleLoggingHandler(BaseCallbackHandler):
    _boot_logged = False

    def __init__(self):
        super().__init__()
        self._chain_depth = 0

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
        if isinstance(inputs, dict):
            user_input = inputs.get("input", inputs)
        else:
            user_input = inputs
        if isinstance(user_input, dict):
            user_input = user_input.get("input", user_input)
        if isinstance(user_input, BaseMessage):
            user_input = user_input.content
        elif isinstance(user_input, list):
            for msg in reversed(user_input):
                if isinstance(msg, BaseMessage) and msg.content:
                    user_input = msg.content
                    break
        if self._chain_depth == 1:
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
        print("✅ [回答完成] 穿搭建议已生成", flush=True)
        print("-" * 40, flush=True)


class RagService(object):
    def __init__(self, vector_wardrobe: Optional[VectorWardrobeService] = None, user_id: str = ""):
        self.vector_wardrobe = vector_wardrobe
        self.user_id = user_id

        self.vector_service = VectorStoreService(
            embedding=DashScopeEmbeddings(model=config.EMBEDDING_MODEL_NAME),
            user_id=user_id,
        )

        self.prompt_template = ChatPromptTemplate.from_messages(
            [
                ("system", RAG_SYSTEM_PROMPT),
                ("system", "以下是你们的历史对话记录："),
                MessagesPlaceholder(variable_name="history"),
                ("user", "{input}"),
                MessagesPlaceholder(variable_name="agent_scratchpad"),
            ]
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
            return self.chain.stream(self._prepare_inputs(inputs), config=config)
        except Exception:

            def _fallback():
                yield FALLBACK_MESSAGE

            return _fallback()

    def invoke(self, inputs: dict, config: Optional[dict] = None):
        try:
            return self.chain.invoke(self._prepare_inputs(inputs), config=config)
        except Exception:
            return FALLBACK_MESSAGE

    def _weather_search(self, query: str) -> str:
        current_year = datetime.datetime.now().year
        current_month = datetime.datetime.now().month
        query_with_date = f"{query} {current_year}年{current_month}月"

        max_retries = 2
        for attempt in range(max_retries):
            try:
                return DuckDuckGoSearchRun().run(query_with_date)
            except Exception:
                if attempt < max_retries - 1:
                    continue
                return (
                    "【系统提示】：由于网络原因无法获取实时天气。"
                    "请仅根据用户所在城市当前的普遍季节气候，为其规划穿搭。"
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
        gender = user_profile.get("gender", "")
        style = user_profile.get("style", "")
        body = user_profile.get("body", "")
        city = user_profile.get("city", "")

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
        """获取最终的执行链"""
        retriever = self.vector_service.get_retriever()

        def get_history(session_id: str):
            """根据 session_id 获取历史记录"""
            return FileChatMessageHistory(
                session_id=session_id,
                storage_path=config.CHAT_HISTORY_DIR,
            )

        # 1. 创建工具
        search_tool = Tool(
            name="weather_search",
            description=(
                "用于查询【指定城市】的近期天气。调用此工具时，【必须】从用户档案中提取"
                "【所在城市】（例如'武陟'）构造查询参数，格式为'城市名 天气'（如'武陟 天气'）。"
                "严禁查询'全国天气'、'全国'或任何不包含具体城市名的模糊查询。"
                "搜索结果中如果包含多个日期的天气数据，只使用距离今天最近的数据，忽略超过3天前的数据。"
            ),
            func=self._weather_search,
        )
        retriever_tool = create_retriever_tool(
            retriever,
            "knowledge_base_search",
            "当用户询问关于服装洗涤、尺码推荐、颜色搭配等通用穿搭知识时，必须使用此工具。",
        )
        tools = [search_tool, retriever_tool]

        # 2. 构建 Agent
        agent = create_tool_calling_agent(self.chat_model, tools, self.prompt_template)
        agent_executor = AgentExecutor(
            agent=agent,
            tools=tools,
            verbose=False,
        )

        # 3. 包装为支持历史记录的链
        conversation_chain = RunnableWithMessageHistory(
            agent_executor,
            get_history,
            input_messages_key="input",
            history_messages_key="history",
        )

        # 4. 提取 output，保持与上游（app_qa.py 的 typewriter_stream）的字符串兼容性
        def extract_output(data):
            if isinstance(data, dict):
                return data.get("output", "")
            return str(data)

        chain = conversation_chain | RunnableLambda(extract_output)
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
