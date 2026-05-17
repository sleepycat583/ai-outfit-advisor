from langchain_core.documents import Document
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import RunnablePassthrough, RunnableWithMessageHistory, RunnableLambda
from history import FileChatMessageHistory
from vector_store_service import VectorStoreService
from langchain_community.embeddings import DashScopeEmbeddings
import config_data as config
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_community.chat_models.tongyi import ChatTongyi

def print_prompt(prompt):
    print("="*20)
    print(prompt.to_string())
    print("="*20)

    return prompt

class RagService(object):
    def __init__(self):
        self.vector_service = VectorStoreService(
            embedding=DashScopeEmbeddings(model=config.embedding_model_name)
        )

        self.prompt_template = ChatPromptTemplate.from_messages(
            [
                ("system", """你现在是一位专为大学生服务的资深AI穿搭顾问，名叫“小衣”。
你的任务是根据用户的提问，结合我提供的【参考资料】，给出实用、时尚、得体的穿搭建议。

【当前用户档案】
- 性别：{gender}
- 偏好风格：{style}
- 体型/身高体重：{body}

【回答要求】
1. 语气必须活泼、热情，像贴心的学长/学姐，多用 emoji 🌟👕👗。
2. 务必结合【当前用户档案】进行个性化推荐。如果用户体型信息为空，你可以委婉地建议他们补充以获得更好效果。
3. 如果问题与穿搭、洗护、尺码无关，请礼貌地拒绝回答，并引导回穿搭话题。
4. 必须主要依据以下【参考资料】来回答。如果参考资料中没有相关信息，可以结合你的专业知识补充，但不要瞎编。

【参考资料】
{context}
"""),
                ("system", "以下是历史对话记录："),
                MessagesPlaceholder("history"),
                ("user", "{input}")
            ]
        )

        self.chat_model = ChatTongyi(model=config.chat_model_name)

        self.chain = self.__get_chain()

    def __get_chain(self):
        """获取最终的执行链"""
        retriever = self.vector_service.get_retriever()

        def format_document(docs: list[Document]):
            if not docs:
                return "无相关参考资料"

            formatted_str = ""
            for doc in docs:
                formatted_str += f"文档片段：{doc.page_content}\n文档来源：{doc.metadata}\n\n"

            return formatted_str

        def get_history(session_id: str):
            """根据 session_id 获取历史记录"""
            return FileChatMessageHistory(session_id=session_id, storage_path="./chat_history")

        def format_for_retriever(value: dict) -> str:
            return value["input"]

        def format_for_prompt_template(value):
            # {input, context}
            new_value = {}
            new_value["input"] = value["input"]["input"]
            new_value["context"] = value["context"]
            new_value["history"] = value["input"]["history"]
            new_value["gender"] = value["input"]["gender"]
            new_value["style"] = value["input"]["style"]
            new_value["body"] = value["input"]["body"]
            return new_value

        chain = (
            {
                "input": RunnablePassthrough(),
                "context": RunnableLambda(format_for_retriever) | retriever | format_document,
            }
            | RunnableLambda(format_for_prompt_template)
            | self.prompt_template
            | print_prompt
            | self.chat_model
            | StrOutputParser()
        )

        conversation_chain = RunnableWithMessageHistory(
            chain,
            get_history,
            input_messages_key="input",
            history_messages_key="history",
        )

        return conversation_chain


if __name__ == '__main__':
    session_config = {
        "configurable": {
            "session_id": "user_001",
        }
    }
    res = RagService().chain.invoke(
        {"input": "羽绒服怎么处理"},
        session_config
    )
    print(res)
