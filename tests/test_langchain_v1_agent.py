from __future__ import annotations

import pytest

try:
    from langchain.agents import create_agent
except ImportError:
    pytest.skip(
        "LangChain v1 is required for this smoke test; run it in the locked v1 environment.",
        allow_module_level=True,
    )
from langchain_core.documents import Document
from langchain_core.language_models.fake_chat_models import FakeListChatModel, FakeMessagesListChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.retrievers import BaseRetriever
from langchain_core.tools import tool

import rag as rag_module


def test_create_agent_v1_returns_messages_state_and_streams_values():
    model = FakeListChatModel(responses=["测试回答"])
    agent = create_agent(model=model, tools=[])

    state = agent.invoke({"messages": [HumanMessage(content="你好")]})
    streamed_states = list(
        agent.stream(
            {"messages": [HumanMessage(content="你好")]},
            stream_mode="values",
        )
    )

    assert [message.content for message in state["messages"]][-1] == "测试回答"
    assert len(streamed_states) == 2
    assert streamed_states[-1]["messages"][-1].content == "测试回答"


def test_create_agent_v1_executes_a_tool_call():
    @tool
    def echo(query: str) -> str:
        """Return the query unchanged."""
        return query

    class BindableFakeChatModel(FakeMessagesListChatModel):
        def bind_tools(self, tools, **kwargs):
            return self

    model = BindableFakeChatModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "echo",
                        "args": {"query": "工具输入"},
                        "id": "call-1",
                        "type": "tool_call",
                    }
                ],
            ),
            AIMessage(content="工具完成"),
        ]
    )
    agent = create_agent(model=model, tools=[echo])

    state = agent.invoke({"messages": [HumanMessage(content="调用工具")]})

    assert state["messages"][-1].content == "工具完成"
    assert any(message.type == "tool" and message.content == "工具输入" for message in state["messages"])


def test_rag_service_builds_create_agent_chain_with_retriever_tool():
    class FakeRetriever(BaseRetriever):
        def _get_relevant_documents(self, query: str, *, run_manager=None):
            return [Document(page_content=f"检索结果:{query}")]

    class FakeVectorService:
        def get_retriever(self):
            return FakeRetriever()

    class BindableFakeChatModel(FakeMessagesListChatModel):
        def bind_tools(self, tools, **kwargs):
            return self

    service = rag_module.RagService.__new__(rag_module.RagService)
    service.vector_service = FakeVectorService()
    service.chat_model = BindableFakeChatModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "knowledge_base_search",
                        "args": {"query": "洗涤"},
                        "id": "retrieval-1",
                        "type": "tool_call",
                    }
                ],
            ),
            AIMessage(content="已完成知识库检索"),
        ]
    )

    chain = service._RagService__get_chain()
    state = chain.invoke({"messages": [HumanMessage(content="怎么洗衣服？")]})

    assert state["messages"][-1].content == "已完成知识库检索"
    assert any(
        message.type == "tool" and "检索结果:洗涤" in message.content
        for message in state["messages"]
    )
