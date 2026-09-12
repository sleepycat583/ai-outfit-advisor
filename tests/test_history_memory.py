from __future__ import annotations

from dataclasses import dataclass

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

import history as history_module
import rag as rag_module


@dataclass
class FakeResult:
    data: list[dict]


class FakeChatMessagesTable:
    def __init__(self, rows: dict[str, dict]):
        self.rows = rows
        self.session_id = ""
        self.operation = "select"
        self.payload: dict = {}
        self.columns = "*"

    def select(self, columns: str):
        self.operation = "select"
        self.columns = columns
        return self

    def eq(self, column: str, value: str):
        assert column == "session_id"
        self.session_id = value
        return self

    def update(self, payload: dict):
        self.operation = "update"
        self.payload = payload
        return self

    def insert(self, payload: dict):
        self.operation = "insert"
        self.payload = payload
        return self

    def delete(self):
        self.operation = "delete"
        return self

    def execute(self):
        if self.operation == "select":
            row = self.rows.get(self.session_id)
            if not row:
                return FakeResult([])
            if self.columns == "*":
                return FakeResult([dict(row)])
            columns = [column.strip() for column in self.columns.split(",")]
            return FakeResult([{column: row.get(column) for column in columns}])
        if self.operation == "update":
            self.rows[self.session_id].update(self.payload)
        elif self.operation == "insert":
            self.rows[self.payload["session_id"]] = dict(self.payload)
        elif self.operation == "delete":
            self.rows.pop(self.session_id, None)
        return FakeResult([])


class FakeSupabase:
    def __init__(self):
        self.rows: dict[str, dict] = {}

    def table(self, name: str):
        assert name == "chat_messages"
        return FakeChatMessagesTable(self.rows)


def make_history(monkeypatch):
    supabase = FakeSupabase()
    monkeypatch.setattr(history_module, "get_supabase_client", lambda: supabase)
    return history_module.FileChatMessageHistory("session-1"), supabase


def test_agent_history_uses_summary_and_recent_messages(monkeypatch):
    chat_history, _ = make_history(monkeypatch)
    chat_history.add_messages([HumanMessage(content="第一轮"), AIMessage(content="回答一")])

    chat_history._fetch_row = lambda: {
        "messages": chat_history._serialize_messages([]),
        "recent_messages": chat_history._serialize_messages([HumanMessage(content="最近问题")]),
        "summary": "用户偏好极简风",
        "summary_message_count": 2,
    }

    messages = chat_history.get_agent_messages()

    assert isinstance(messages[0], SystemMessage)
    assert "用户偏好极简风" in messages[0].content
    assert isinstance(messages[1], HumanMessage)
    assert messages[1].content == "最近问题"


def test_summary_starts_after_three_overflow_rounds(monkeypatch):
    chat_history, supabase = make_history(monkeypatch)
    summarized_batch_sizes = []

    def summarize(previous_summary, messages):
        summarized_batch_sizes.append(len(messages))
        return f"摘要-{len(messages)}"

    for round_number in range(13):
        chat_history.add_messages(
            [HumanMessage(content=f"问题-{round_number}"), AIMessage(content=f"回答-{round_number}")]
        )
        chat_history.maybe_update_summary(summarize)

    row = supabase.rows["session-1"]
    assert summarized_batch_sizes == [6]
    assert row["summary"] == "摘要-6"
    assert row["summary_message_count"] == 6
    assert len(chat_history._load_json_messages(row["recent_messages"])) == 20


def test_malformed_full_history_falls_back_to_empty_list(monkeypatch):
    chat_history, supabase = make_history(monkeypatch)
    supabase.rows["session-1"] = {"messages": "not-json"}

    assert chat_history.messages == []


def test_agent_history_bounds_legacy_rows_without_recent_columns(monkeypatch):
    chat_history, supabase = make_history(monkeypatch)
    full_messages = []
    for round_number in range(15):
        full_messages.extend(
            [
                HumanMessage(content=f"问题-{round_number}"),
                AIMessage(content=f"回答-{round_number}"),
            ]
        )
    supabase.rows["session-1"] = {
        "messages": chat_history._serialize_messages(full_messages),
        "recent_messages": "",
        "summary": "",
        "summary_message_count": 0,
    }

    messages = chat_history.get_agent_messages()

    assert len(messages) == 20
    assert messages[0].content == "问题-5"
    assert messages[-1].content == "回答-14"


def test_agent_history_bounds_oversized_recent_column(monkeypatch):
    chat_history, supabase = make_history(monkeypatch)
    recent_messages = []
    for message_number in range(30):
        recent_messages.append(HumanMessage(content=f"消息-{message_number}"))
    supabase.rows["session-1"] = {
        "messages": chat_history._serialize_messages(recent_messages),
        "recent_messages": chat_history._serialize_messages(recent_messages),
        "summary": "",
        "summary_message_count": 0,
    }

    messages = chat_history.get_agent_messages()

    assert len(messages) == 20
    assert messages[0].content == "消息-10"
    assert messages[-1].content == "消息-29"


def test_agent_history_bounds_when_persistence_read_fails(monkeypatch):
    chat_history, _ = make_history(monkeypatch)
    full_messages = []
    for message_number in range(30):
        full_messages.append(HumanMessage(content=f"消息-{message_number}"))

    def fail_fetch():
        raise RuntimeError("temporary database failure")

    chat_history._fetch_row = fail_fetch
    monkeypatch.setattr(
        history_module.FileChatMessageHistory,
        "messages",
        property(lambda _self: full_messages),
    )

    messages = chat_history.get_agent_messages()

    assert len(messages) == 20
    assert messages[0].content == "消息-10"
    assert messages[-1].content == "消息-29"


def test_add_messages_uses_legacy_payload_when_new_columns_are_unavailable(monkeypatch):
    chat_history, supabase = make_history(monkeypatch)
    existing = [HumanMessage(content="旧消息")]
    supabase.rows["session-1"] = {
        "messages": chat_history._serialize_messages(existing),
    }

    chat_history._fetch_row = lambda: (_ for _ in ()).throw(RuntimeError("missing columns"))
    chat_history.add_messages([AIMessage(content="新消息")])

    row = supabase.rows["session-1"]
    assert [m.content for m in chat_history._load_json_messages(row["messages"])] == ["旧消息", "新消息"]
    assert "recent_messages" not in row
    assert "summary" not in row


def test_summary_keeps_bounded_tail_when_recent_window_is_corrupt(monkeypatch):
    chat_history, supabase = make_history(monkeypatch)
    full_messages = []
    for message_number in range(15):
        full_messages.append(HumanMessage(content=f"消息-{message_number}"))
    supabase.rows["session-1"] = {
        "messages": chat_history._serialize_messages(full_messages),
        "recent_messages": "not-json",
        "summary": "用户偏好极简风",
        "summary_message_count": 10,
    }

    messages = chat_history.get_agent_messages()

    assert isinstance(messages[0], SystemMessage)
    assert len(messages[1:]) == 15
    assert messages[-1].content == "消息-14"


def test_rag_history_ignores_caller_supplied_messages(monkeypatch):
    class PersistedHistory:
        def __init__(self, session_id):
            assert session_id == "session-1"

        def get_agent_messages(self):
            return [HumanMessage(content="持久化历史")]

    monkeypatch.setattr(rag_module, "FileChatMessageHistory", PersistedHistory)
    service = rag_module.RagService.__new__(rag_module.RagService)
    service.user_id = "user-1"
    service.conversation_repo = type(
        "Repository", (), {"ensure_existing": lambda self, user_id, conversation_id: conversation_id}
    )()

    session_id, messages = service._get_session_history(
        {
            "configurable": {
                "session_id": "session-1",
                "history_messages": [{"role": "user", "content": "不应进入模型"}],
            }
        }
    )

    assert session_id == "session-1"
    assert [message.content for message in messages] == ["持久化历史"]
