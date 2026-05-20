from typing import Optional
import datetime
import copy
import json

from langchain_core.runnables import RunnableWithMessageHistory, RunnableLambda
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import BaseMessage, SystemMessage, HumanMessage
from langchain_core.tools import Tool
from history import FileChatMessageHistory
from vector_store_service import VectorStoreService
from langchain_community.embeddings import DashScopeEmbeddings
import config_data as config
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_community.chat_models.tongyi import ChatTongyi
from langchain_community.tools import DuckDuckGoSearchRun
from langchain_classic.agents import create_tool_calling_agent, AgentExecutor
from langchain_classic.tools.retriever import create_retriever_tool


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
        print("-"*40, flush=True)


class RagService(object):
    def __init__(self):
        self.vector_service = VectorStoreService(
            embedding=DashScopeEmbeddings(model=config.EMBEDDING_MODEL_NAME)
        )

        self.prompt_template = ChatPromptTemplate.from_messages(
            [
                ("system", """你是一位名叫"小衣"的顶尖私人穿搭主理人兼时尚博主。
你拥有极高的美学素养，不仅精通服装搭配，还能精准把握天气与流行趋势。

【当前日期】
{current_date}
今天是 {current_date}，只参考最新的天气信息。

【当前客户绝密档案】
- 性别：{gender}
- 偏好风格：{style}
- 身高体重/体型：{body}

【主理人服务法则（必须严格遵守）】
1. 👑 语气基调：温暖、自信、充满活力，像个懂客户的时尚圈知心好友。严禁使用机械化、AI味浓重的公文套话。
2. 🎨 排版美学：回答必须极具结构感和呼吸感，必须包含以下三个板块：
   - ⛅ 【场景与温度感知】：用一句亲切的话破冰，点评当前天气或客户提到的特定场景（如面试、约会）。
   - ✨ 【主理人 OOTD 灵感】：分点给出具体的穿搭推荐。核心单品必须使用 **加粗**（例如：**藏青色阔腿裤**）。
   - 💡 【小衣私藏贴士】：结合客户档案（如身高体重）或洗护要求，给出一个专业的"扬长避短"或"避坑"建议。
3. 🎀 视觉点缀：灵活、克制地使用高级感表情包（如 ✨🧥👗👟🍂），不要满屏都是，起到点睛之笔即可。
4. 💎 专属签名：无论客户问什么，你的回答最后必须单独换行，并固定加上这句专属问候语：
   "怎么样，这套搭配还合你的心意吗？还有什么场景需要我帮你参谋参谋？👗✨"

【工具使用底线】
- 你具备自主查阅网络天气、流行趋势以及本地穿搭知识库的能力。
- 若需要查询天气，请优先使用当前日期，除非用户明确指定了其他日期。
- 严禁向客户暴露你在使用"搜索工具"或"检索知识库"，请将查到的信息无缝、自然地融进你的时尚建议中。"""),
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

    def stream(self, inputs: dict, config: Optional[dict] = None):
        try:
            return self.chain.stream(self._with_current_date(inputs), config=config)
        except Exception:
            def _fallback():
                yield FALLBACK_MESSAGE
            return _fallback()

    def invoke(self, inputs: dict, config: Optional[dict] = None):
        try:
            return self.chain.invoke(self._with_current_date(inputs), config=config)
        except Exception:
            return FALLBACK_MESSAGE

    def _weather_search(self, query: str) -> str:
        current_year = datetime.datetime.now().year
        current_month = datetime.datetime.now().month
        query_with_date = f"{query} {current_year}年{current_month}月"
        return DuckDuckGoSearchRun().run(query_with_date)

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
        gender: str,
        style: str,
        body: str,
        current_date: str,
        wardrobe_items: list[dict],
    ) -> list[dict]:
        weather_info = self._weather_search("未来一周 天气")
        available_items = copy.deepcopy(wardrobe_items or [])
        recent_core_ids: list[str] = []
        results: list[dict] = []
        theme_pool = [
            "轻松通勤感",
            "温柔日常感",
            "活力运动感",
            "简约高级感",
            "甜酷混搭感",
            "松弛休闲感",
            "精致约会感",
        ]

        for day_index in range(7):
            theme = theme_pool[day_index % len(theme_pool)]
            today_available = [
                item for item in available_items if item.get("id") not in recent_core_ids
            ]
            core_item = today_available[0] if today_available else None
            core_item_name = ""
            if core_item:
                core_item_name = (
                    f"{core_item.get('color', '')}{core_item.get('material', '')}"
                    f"{core_item.get('sub_category') or core_item.get('category', '')}"
                )

            prompt = (
                "你是一位专业时尚分析师与私人穿搭主理人，只能输出 JSON。\n"
                "请基于用户画像、天气与衣橱信息，给出今日穿搭计划。\n"
                "输出 JSON 结构必须包含：scene, ootd, tips。\n"
                "scene 为一句场景感知；ootd 为数组，元素是穿搭单品描述，"
                "必须标注【自有】或【建议购入】并加粗单品名；tips 为一句小贴士。\n\n"
                f"【当前日期】{current_date}\n"
                f"【未来天气】{weather_info}\n"
                f"【今日风格主题】{theme}\n"
                f"【用户画像】性别:{gender} 风格:{style} 体型:{body}\n"
                f"【今日核心单品】{core_item_name or '无'}\n"
                "【可用衣橱清单】\n"
                f"{self._format_wardrobe_items(today_available)}\n"
            )

            response = self.chat_model.invoke(
                [SystemMessage(content="仅输出 JSON，不要出现多余文本。"), HumanMessage(content=prompt)]
            )
            content = response.content if hasattr(response, "content") else str(response)
            content_text = self._extract_json_content(str(content))
            day_result = json.loads(content_text)
            results.append(day_result)

            if core_item and core_item.get("id"):
                recent_core_ids.append(core_item.get("id"))
                recent_core_ids = recent_core_ids[-2:]

        return results

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
                "用于查询天气/趋势的联网搜索工具。搜索结果中如果包含多个日期的天气数据，"
                "只使用距离今天最近的数据，忽略超过3天前的数据。"
            ),
            func=self._weather_search,
        )
        retriever_tool = create_retriever_tool(
            retriever,
            "knowledge_base_search",
            "当用户询问关于服装洗涤、尺码推荐、颜色搭配等通用穿搭知识时，必须使用此工具。"
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


if __name__ == '__main__':
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
        session_config
    )
    print(res)
