from typing import Optional
import datetime
import copy
import json

from pydantic import BaseModel, Field

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
- 所在城市：{city}

【用户数字衣橱（以下是你拥有的真实单品，必须优先使用）】
{wardrobe}

⚠️ 【穿搭推荐铁律 - 衣橱优先（最高优先级，违反视为无效推荐）】：
1. 衣橱优先：你必须【优先且尽量多地】使用上方衣橱中已有的单品来完成搭配！
2. 标签明确：使用衣橱里的真实单品时，【必须】在单品名称前加上【自有】标签，并带上该单品的颜色、材质。例如："【自有】深蓝色百褶裙"。
3. 补充建议：只有当衣橱里的衣服实在无法凑齐一套合适的搭配时，才可以推荐外部单品，并【必须】加上【建议购入】标签。
4. 比例约束：回答中【自有】单品的数量必须多于【建议购入】单品的数量。如果衣橱够用，绝不许建议购入！

【主理人服务法则（必须严格遵守）】
1. 👑 语气基调：温暖、自信、充满活力，像个懂客户的时尚圈知心好友。严禁使用机械化、AI味浓重的公文套话。
2. 🎨 排版美学：回答必须极具结构感和呼吸感，必须包含以下三个板块：
   - ⛅ 【场景与温度感知】：用一句亲切的话破冰，点评当前天气或客户提到的特定场景（如面试、约会）。必须参考用户所在城市的实际天气。
   - ✨ 【主理人 OOTD 灵感】：分点给出具体的穿搭推荐。核心单品必须使用 **加粗**（例如：**藏青色阔腿裤**）。必须结合用户的身高体重和偏好风格。排版格式如下：
     · 上装：【自有】白色纯棉短袖T恤，清爽透气。
     · 下装：【自有】黑色直筒西裤，修饰腿型、拉长比例。
     · 鞋履：【建议购入】一双米色乐福鞋，提升整体精致度。
   - 💡 【小衣私藏贴士】：结合客户档案（如身高体重）或洗护要求，给出一个专业的"扬长避短"或"避坑"建议。
3. 🎀 视觉点缀：灵活、克制地使用高级感表情包（如 ✨🧥👗👟🍂），不要满屏都是，起到点睛之笔即可。
4. 💎 专属签名：无论客户问什么，你的回答最后必须单独换行，并固定加上这句专属问候语：
   "怎么样，这套搭配还合你的心意吗？还有什么场景需要我帮你参谋参谋？👗✨"
5. 🏷️ 单品标签：推荐衣橱中已有的单品时，必须在单品描述的同一行末尾，隐式附上该单品的唯一ID标签，格式为 <item>单品的唯一id</item>。此标签仅供程序解析使用，不影响客户阅读。
   例如：· 上装：【自有】白色纯棉短袖T恤，清爽透气。 <item>a1b2c3d4-...</item>

【工具使用底线】
- 你具备自主查阅网络天气、流行趋势以及本地穿搭知识库的能力。

⚠️ 天气查询强制约束（最高优先级，违反将导致推荐无效）：
- 查询天气前，【必须】先从上方客户档案中提取【所在城市】作为查询目标。
- 你只能查询档案中指定的城市天气（如档案中写"武陟"，则只能查"武陟 天气"）。
- 【绝对禁止】查询"全国天气"、"全国"、"中国"或任何不包含具体城市名的模糊区域天气。
- 结合【当前日期】，按需附加"今天"、"明天"或"未来一周"等时间限定词。

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
            "轻松通勤感", "温柔日常感", "活力运动感", "简约高级感",
            "甜酷混搭感", "松弛休闲感", "精致约会感",
        ]

        # Step 2: 构建全局规划 Prompt
        theme_lines = "\n".join(
            f"· {day_labels[i]}  →  {theme_pool[i]}" for i in range(7)
        )
        prompt = f"""你是一位顶级私人穿搭主理人。请为用户规划未来连续7天的完整穿搭方案。

【用户画像硬约束（每套搭配必须体现以下特征，违反即视为无效规划）】
- 性别：{gender}（所有推荐必须符合该性别的着装习惯）
- 偏好风格：{style}（7天的搭配均需围绕此风格展开，不可偏离为其他风格）
- 身高体重/体型：{body}（每套搭配必须针对此体型做扬长避短的设计，例如矮个子避免长款、丰满体型善用纵向线条等）
- 所在城市：{city}（天气查询和场景感知均以此城市为准，不得使用其他城市）
在每套搭配的 scene、desc 和 tips 中，必须能明确看出上述画像数据的影响，不能只泛泛而谈。

【未来天气参考】
{weather_info}

【7天日期与指定风格主题】
{theme_lines}

【可用衣橱单品清单】
{wardrobe_text}

【穿搭轮换铁律（必须严格遵守）】
1. 内搭类（T恤/衬衫/打底衫等贴身衣物）：每件7天内最多出现1次（穿过即洗）。
2. 下装类（裤子/裙子）：每件最多出现2次，且同件不可连续两天穿着。
3. 外套类：每件最多出现3次，尽量隔天轮换。
4. 鞋履类：每双最多出现2次，隔天轮换以保持鞋型。
5. 配饰类：适度更换即可，无严格次数限制。
6. 每天必须是一套完整搭配（≥3件：上装+下装+鞋履）。
7. 优先衣橱现有单品（标记【自有】），仅确实缺少关键单品时才建议购入（标记【建议购入】、id留空）。
8. 7天风格需各有侧重，在指定主题下发挥，避免每天雷同。"""

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
