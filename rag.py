from langchain_core.runnables import RunnableWithMessageHistory, RunnableLambda
from langchain_core.callbacks import BaseCallbackHandler
from history import FileChatMessageHistory
from vector_store_service import VectorStoreService
from langchain_community.embeddings import DashScopeEmbeddings
import config_data as config
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_community.chat_models.tongyi import ChatTongyi
from langchain_community.tools import DuckDuckGoSearchRun
from langchain_classic.agents import create_tool_calling_agent, AgentExecutor
from langchain_classic.tools.retriever import create_retriever_tool
from typing import Any
from recommendation_rules import (
    build_constraints,
    inject_constraints_prompt,
    stabilize_output,
)


class ConsoleLoggingHandler(BaseCallbackHandler):
    def on_chain_start(self, serialized, inputs, **kwargs):
        print("\n" + "🚀"*15 + " [系统启动] 开始执行穿搭决策大脑 " + "🚀"*15, flush=True)
        user_input = inputs.get("input", inputs)
        if isinstance(user_input, dict):
            user_input = user_input.get("input", user_input)
        print(f"📥 [用户提问] -> {user_input}", flush=True)

    def on_llm_start(self, serialized, prompts, **kwargs):
        print("\n" + "🧠"*15 + " [模型调用] 正在请求大语言模型决策中... " + "🧠"*15, flush=True)

    def on_agent_action(self, action, **kwargs):
        print("\n" + "🧭"*15 + f" [AI 智能决策] 激活外部工具: 【{action.tool}】 " + "🧭"*15, flush=True)
        print(f"📥 [工具参数] -> {action.tool_input}", flush=True)

    def on_tool_end(self, output, **kwargs):
        print("\n" + "⚙️"*15 + " [工具执行完毕] 获取参考资料成功 " + "⚙️"*15, flush=True)
        print(f"📤 [资料片段] -> {str(output)[:200]}...", flush=True)

    def on_agent_finish(self, finish, **kwargs):
        print("\n" + "🏁"*15 + " [思考结束] 最终穿搭方案生成完毕 " + "🏁"*15, flush=True)
        print("="*60 + "\n", flush=True)


class RagService(object):
    def __init__(self):
        self.vector_service = VectorStoreService(
            embedding=DashScopeEmbeddings(model=config.embedding_model_name)
        )

        self.prompt_template = ChatPromptTemplate.from_messages(
            [
                ("system", """你是一位名叫"小衣"的顶尖私人穿搭主理人兼时尚博主。
你拥有极高的美学素养，不仅精通服装搭配，还能精准把握天气与流行趋势。

【当前客户绝密档案】
- 性别：{gender}
- 偏好风格：{style}
- 身高体重/体型：{body}
- 核心场景：{scene}
- 预算偏好：{budget}

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
- 严禁向客户暴露你在使用"搜索工具"或"检索知识库"，请将查到的信息无缝、自然地融进你的时尚建议中。"""),
                ("system", "以下是你们的历史对话记录："),
                MessagesPlaceholder(variable_name="history"),
                ("user", "{input}"),
                MessagesPlaceholder(variable_name="agent_scratchpad"),
            ]
        )

        self.chat_model = ChatTongyi(model=config.chat_model_name)

        self.chain = self.__get_chain()

    def __get_chain(self):
        """获取最终的执行链"""
        retriever = self.vector_service.get_retriever()

        def get_history(session_id: str):
            """根据 session_id 获取历史记录"""
            return FileChatMessageHistory(
                session_id=session_id,
                storage_path=config.chat_history_path,
            )

        def apply_constraints(data: Any) -> dict[str, Any]:
            if not isinstance(data, dict):
                return {"input": str(data)}
            constraints = build_constraints(
                gender=data.get("gender", ""),
                style=data.get("style", ""),
                body=data.get("body", ""),
                scene=data.get("scene", ""),
                budget=data.get("budget", ""),
            )
            payload = dict(data)
            payload["input"] = inject_constraints_prompt(
                user_input=data.get("input", ""),
                constraints=constraints,
            )
            return payload

        # 1. 创建工具
        search_tool = DuckDuckGoSearchRun()
        retriever_tool = create_retriever_tool(
            retriever,
            "knowledge_base_search",
            "当用户询问服装洗涤、尺码推荐、颜色搭配及场景穿搭知识时，必须使用此工具。"
        )
        tools = [search_tool, retriever_tool]

        # 2. 构建 Agent
        agent = create_tool_calling_agent(self.chat_model, tools, self.prompt_template)
        agent_executor = AgentExecutor(
            agent=agent,
            tools=tools,
            verbose=True,
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
                return stabilize_output(data.get("output", ""))
            return stabilize_output(str(data))

        chain = (
            RunnableLambda(apply_constraints)
            | conversation_chain
            | RunnableLambda(extract_output)
        )
        return chain


if __name__ == '__main__':
    session_config = {
        "configurable": {
            "session_id": "user_001",
        }
    }
    res = RagService().chain.invoke(
        {
            "input": "羽绒服怎么处理",
            "gender": "女生",
            "style": "日常休闲",
            "body": "",
            "scene": "通勤",
            "budget": "300元以内",
        },
        session_config
    )
    print(res)
