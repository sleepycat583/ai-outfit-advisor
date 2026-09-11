from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

import config_data as config
import native_memory
import rag as rag_module
from native_memory import _validate_schema
from rag import RagService
from conversation_service import ConversationOwnershipError, ConversationRepository


def test_private_schema_validation_rejects_identifier_injection():
    assert _validate_schema("app_private") == "app_private"
    for value in ("app-private", "app_private;drop table users", "", "1private"):
        try:
            _validate_schema(value)
        except ValueError:
            continue
        raise AssertionError(f"schema should be rejected: {value!r}")


def test_conversation_id_is_canonical_thread_id_and_preserves_caller_config():
    service = RagService.__new__(RagService)
    service.user_id = "user-a"
    normalized = service._normalize_config(
        {"configurable": {"conversation_id": "conversation-a"}, "tags": ["test"]}
    )

    assert normalized["configurable"]["conversation_id"] == "conversation-a"
    assert normalized["configurable"]["thread_id"] == "conversation-a"
    assert normalized["configurable"]["session_id"] == "conversation-a"
    assert normalized["tags"] == ["test"]


def test_conversation_id_overrides_conflicting_caller_thread_identity():
    service = RagService.__new__(RagService)
    service.user_id = "user-a"
    normalized = service._normalize_config(
        {
            "configurable": {
                "conversation_id": "conversation-a",
                "session_id": "wrong-session",
                "thread_id": "other-users-thread",
            }
        }
    )

    assert normalized["configurable"] == {
        "conversation_id": "conversation-a",
        "session_id": "conversation-a",
        "thread_id": "conversation-a",
    }


def test_legacy_conversation_id_maps_back_to_existing_transcript_id():
    assert ConversationRepository.legacy_session_id("legacy:user-a") == "chat_session_user-a"
    assert (
        ConversationRepository.legacy_session_id("legacy:chat_session_user-a")
        == "chat_session_user-a"
    )
    assert ConversationRepository.legacy_session_id("new-conversation") == "new-conversation"


def test_native_config_requires_repository_ownership_check(monkeypatch):
    service = RagService.__new__(RagService)
    service.user_id = "user-a"
    service.checkpointer = object()
    service.conversation_repo = type(
        "Repository", (), {"ensure": lambda self, user_id, conversation_id: conversation_id}
    )()

    class Repository:
        def __init__(self):
            self.calls = []

        def ensure(self, user_id, conversation_id):
            self.calls.append((user_id, conversation_id))
            return conversation_id

    repository = Repository()
    service.conversation_repo = repository
    normalized = service._normalize_config({"configurable": {"conversation_id": "thread-a"}})

    assert normalized["configurable"]["thread_id"] == "thread-a"
    assert repository.calls == [("user-a", "thread-a")]


def test_native_config_stops_when_conversation_belongs_to_another_user():
    service = RagService.__new__(RagService)
    service.user_id = "user-a"
    service.checkpointer = object()
    service.conversation_repo = type(
        "Repository", (), {"ensure": lambda self, user_id, conversation_id: conversation_id}
    )()

    class Repository:
        def ensure(self, user_id, conversation_id):
            raise ConversationOwnershipError("conversation_id 不属于当前用户")

    service.conversation_repo = Repository()

    try:
        service._normalize_config({"configurable": {"conversation_id": "user-b-thread"}})
    except ConversationOwnershipError:
        pass
    else:
        raise AssertionError("cross-user conversation must be rejected before graph invocation")


def test_native_dual_write_flag_controls_legacy_transcript(monkeypatch):
    service = RagService.__new__(RagService)
    service.checkpointer = object()
    monkeypatch.setattr(config, "MEMORY_DUAL_WRITE", False)
    assert service._should_write_legacy() is False
    monkeypatch.setattr(config, "MEMORY_DUAL_WRITE", True)
    assert service._should_write_legacy() is True


def test_native_graph_input_does_not_replay_legacy_transcript():
    service = RagService.__new__(RagService)
    service.checkpointer = object()
    service._build_system_prompt = lambda inputs: "动态系统提示"
    history = [HumanMessage(content="旧消息")]

    first = service._build_graph_inputs({"input": "新问题"}, history, include_system=True)
    resumed = service._build_graph_inputs({"input": "再次提问"}, [], include_system=False)

    assert isinstance(first["messages"][0], SystemMessage)
    assert [m.content for m in first["messages"]] == [
        "动态系统提示",
        "以下是你们的历史对话记录：",
        "旧消息",
        "新问题",
    ]
    assert [m.content for m in resumed["messages"]] == ["再次提问"]


def test_long_term_memory_is_injected_only_with_a_fresh_system_prompt():
    service = RagService.__new__(RagService)
    service.checkpointer = object()
    service._build_system_prompt = lambda inputs: "动态系统提示"

    first = service._build_graph_inputs(
        {"input": "新问题", "long_term_memory": "- 偏好: 不穿高跟鞋"},
        [],
        include_system=True,
    )
    resumed = service._build_graph_inputs(
        {"input": "再次提问", "long_term_memory": "- 偏好: 不穿高跟鞋"},
        [],
        include_system=False,
    )

    assert "长期记忆" in first["messages"][1].content
    assert [message.content for message in resumed["messages"]] == ["再次提问"]


def test_native_checkpoint_lookup_is_fail_safe():
    class BrokenSaver:
        def get_tuple(self, config):
            raise RuntimeError("database unavailable")

    service = RagService.__new__(RagService)
    service.checkpointer = BrokenSaver()
    assert service._native_has_checkpoint({"configurable": {"thread_id": "t"}}) is False


def test_native_history_reader_restores_only_user_visible_messages(monkeypatch):
    class CheckpointTuple:
        checkpoint = {
            "channel_values": {
                "messages": [
                    SystemMessage(content="系统提示"),
                    HumanMessage(content="用户问题"),
                    AIMessage(content="助手回答"),
                ]
            }
        }

    class Runtime:
        checkpointer = type(
            "Saver",
            (),
            {"get_tuple": lambda self, config: CheckpointTuple()},
        )()

        def __init__(self):
            self.closed = False

        def close(self):
            self.closed = True

    runtime = Runtime()
    monkeypatch.setattr(native_memory.NativeMemoryRuntime, "connect", lambda: runtime)

    messages = native_memory.load_native_thread_messages("conversation-a")

    assert [message.content for message in messages] == ["用户问题", "助手回答"]
    assert runtime.closed is True


def test_native_history_reader_falls_back_only_when_storage_is_unavailable(monkeypatch):
    monkeypatch.setattr(
        native_memory.NativeMemoryRuntime,
        "connect",
        lambda: (_ for _ in ()).throw(RuntimeError("database unavailable")),
    )

    assert native_memory.load_native_thread_messages("conversation-a") is None


def test_native_failure_falls_back_once_and_persists_legacy_transcript(monkeypatch):
    writes = []

    class History:
        def __init__(self, session_id):
            assert session_id == "chat_session_user-a"

        def get_agent_messages(self):
            return []

        def add_messages(self, messages):
            writes.append(messages)

        def maybe_update_summary(self, summary_updater):
            return None

    class BrokenNativeChain:
        def invoke(self, graph_inputs, config):
            raise RuntimeError("checkpoint write failed")

    class LegacyChain:
        def invoke(self, graph_inputs, config):
            return {"messages": [AIMessage(content="回退回答")]}

    service = RagService.__new__(RagService)
    service.user_id = "user-a"
    service.checkpointer = object()
    service.conversation_repo = type(
        "Repository", (), {"ensure": lambda self, user_id, conversation_id: conversation_id}
    )()
    service.chain = BrokenNativeChain()
    service.legacy_chain = LegacyChain()
    service._get_session_history = lambda config: ("legacy:user-a", [])
    service._native_has_checkpoint = lambda config: False
    service._build_system_prompt = lambda inputs: "系统提示"
    service.summarize_chat_messages = lambda previous, messages: ""
    monkeypatch.setattr(rag_module, "FileChatMessageHistory", History)
    monkeypatch.setattr(config, "MEMORY_NATIVE_FALLBACK", True)

    answer = service._invoke_graph(
        {"input": "测试问题"},
        {"configurable": {"conversation_id": "legacy:user-a"}},
    )

    assert answer == "回退回答"
    assert len(writes) == 1
    assert [message.content for message in writes[0]] == ["测试问题", "回退回答"]


def test_native_success_without_dual_write_does_not_touch_legacy_history(monkeypatch):
    class NativeChain:
        def invoke(self, graph_inputs, config):
            return {"messages": [AIMessage(content="原生回答")]}

    class History:
        def __init__(self, session_id):
            raise AssertionError("native-only success must not create legacy history")

    service = RagService.__new__(RagService)
    service.user_id = "user-a"
    service.checkpointer = object()
    service.conversation_repo = type(
        "Repository", (), {"ensure": lambda self, user_id, conversation_id: conversation_id}
    )()
    service.chain = NativeChain()
    service._get_session_history = lambda config: ("conversation-a", [])
    service._native_has_checkpoint = lambda config: False
    service._build_system_prompt = lambda inputs: "系统提示"
    monkeypatch.setattr(rag_module, "FileChatMessageHistory", History)
    monkeypatch.setattr(config, "MEMORY_DUAL_WRITE", False)

    answer = service._invoke_graph(
        {"input": "测试问题"},
        {"configurable": {"conversation_id": "conversation-a"}},
    )

    assert answer == "原生回答"


def test_native_migration_matches_postgres_saver_current_schema():
    migration = (
        __import__("pathlib").Path(__file__).parents[1]
        / "supabase"
        / "migrations"
        / "20260911100000_native_memory_private_schema.sql"
    ).read_text(encoding="utf-8")

    assert "task_path TEXT NOT NULL DEFAULT ''" in migration
    assert "WHERE c.session_id ~ '^chat_session_[^:]+$'" in migration
    assert "'legacy:unknown'" not in migration
