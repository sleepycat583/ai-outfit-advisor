from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage, RemoveMessage, SystemMessage

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


def test_private_schema_validation_rejects_public_and_reserved_schemas():
    for value in ("public", "pg_catalog", "information_schema", "pg_toast"):
        try:
            _validate_schema(value)
        except ValueError:
            continue
        raise AssertionError(f"reserved schema should be rejected: {value!r}")


def test_private_schema_probe_requires_schema_and_completed_migration():
    class Cursor:
        def __init__(self, rows):
            self.rows = iter(rows)
            self.sql = []

        def execute(self, statement, params=None):
            self.sql.append((statement, params))

        def fetchone(self):
            return next(self.rows)

    cursor = Cursor(
        [
            {"schema_name": "app_private"},
            {"table_name": "app_private.conversations"},
            {"table_name": "app_private.memory_migrations"},
            {"status": "completed"},
        ]
    )
    native_memory._assert_private_schema(
        cursor,
        "app_private",
        required_tables=("conversations", "memory_migrations"),
        migration_key="native_memory_private_schema",
    )
    assert all("public" not in statement.lower() for statement, _ in cursor.sql)
    assert '"app_private"."memory_migrations"' in cursor.sql[-1][0]


def test_private_schema_probe_rejects_missing_migration():
    class Cursor:
        def execute(self, statement, params=None):
            pass

        def fetchone(self):
            if not hasattr(self, "count"):
                self.count = 0
            self.count += 1
            return {"schema_name": "app_private"} if self.count == 1 else {"table_name": "x"}

    try:
        native_memory._assert_private_schema(
            Cursor(), "app_private", required_tables=("conversations",), migration_key="native"
        )
    except RuntimeError as exc:
        assert "迁移" in str(exc)
    else:
        raise AssertionError("missing migration marker must be rejected")


def test_conversation_id_is_canonical_thread_id_and_preserves_caller_config():
    service = RagService.__new__(RagService)
    service.user_id = "user-a"
    service.conversation_repo = type(
        "Repository", (), {"ensure_existing": lambda self, user_id, conversation_id: conversation_id}
    )()
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
    service.conversation_repo = type(
        "Repository", (), {"ensure_existing": lambda self, user_id, conversation_id: conversation_id}
    )()
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


def test_existing_conversation_validation_does_not_claim_unknown_thread_without_database():
    repository = ConversationRepository(schema="app_private")
    assert repository.ensure_existing("user-a", "legacy:user-a") == "legacy:user-a"
    try:
        repository.ensure_existing("user-a", "user-b-thread")
    except ConversationOwnershipError:
        pass
    else:
        raise AssertionError("unknown thread must not be claimed without a database")


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


def test_legacy_config_also_checks_conversation_ownership():
    service = RagService.__new__(RagService)
    service.user_id = "user-a"
    service.checkpointer = None

    class Repository:
        def ensure(self, user_id, conversation_id):
            raise ConversationOwnershipError("conversation_id 不属于当前用户")

    service.conversation_repo = Repository()
    try:
        service._normalize_config({"configurable": {"conversation_id": "user-b-thread"}})
    except ConversationOwnershipError:
        pass
    else:
        raise AssertionError("legacy conversation must be ownership checked too")


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
        "以下是用户跨会话明确保存的长期记忆，仅在与当前问题相关时使用；如与用户当前明确说明冲突，以当前说明为准：\n暂无额外的长期记忆。",
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


def test_native_fallback_marks_thread_degraded_without_deleting_history(monkeypatch):
    deleted = []
    service = RagService.__new__(RagService)
    service.checkpointer = object()
    service.native_memory = type("Runtime", (), {"delete_thread": lambda self, thread: deleted.append(thread)})()
    service.conversation_repo = type(
        "Repository", (), {"mark_native_degraded": lambda self, user_id, thread, error: None}
    )()
    service.user_id = "user-a"
    service._normalize_config = lambda config: config

    service._mark_native_degraded("conversation-a", "checkpoint write failed")

    assert deleted == []
    assert "conversation-a" in service._native_degraded_threads


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
    monkeypatch.setattr(
        ConversationRepository,
        "ensure_existing",
        lambda self, user_id, conversation_id: conversation_id,
    )
    monkeypatch.setattr(native_memory.NativeMemoryRuntime, "connect", lambda user_id="": runtime)
    messages = native_memory.load_native_thread_messages("conversation-a", "user-a")

    assert [message.content for message in messages] == ["用户问题", "助手回答"]
    assert runtime.closed is True


def test_native_history_reader_falls_back_only_when_storage_is_unavailable(monkeypatch):
    monkeypatch.setattr(
        ConversationRepository,
        "ensure_existing",
        lambda self, user_id, conversation_id: conversation_id,
    )
    monkeypatch.setattr(
        native_memory.NativeMemoryRuntime,
        "connect",
        lambda user_id="": (_ for _ in ()).throw(RuntimeError("database unavailable")),
    )

    assert native_memory.load_native_thread_messages("conversation-a", "user-a") is None


def test_native_checkpoint_dynamic_system_prompt_is_replaced_on_resume():
    service = RagService.__new__(RagService)
    service.checkpointer = object()
    service._build_system_prompt = lambda inputs: inputs["system"]

    first = service._build_graph_inputs({"input": "one", "system": "profile-v1"}, [], include_system=True)
    resumed = service._build_graph_inputs({"input": "two", "system": "profile-v2"}, [], include_system=True)

    assert first["messages"][0].id == resumed["messages"][0].id
    assert resumed["messages"][0].content == "profile-v2"


def test_native_checkpoint_clears_removed_long_term_memory_on_next_turn():
    service = RagService.__new__(RagService)
    service.checkpointer = object()
    service._build_system_prompt = lambda inputs: "系统提示"

    remembered = service._build_graph_inputs(
        {"input": "one", "long_term_memory": "- 禁忌: 高跟鞋"}, [], include_system=True
    )
    forgotten = service._build_graph_inputs({"input": "two"}, [], include_system=True)

    remembered_memory = [m for m in remembered["messages"] if m.id == "native-long-term-memory"]
    forgotten_memory = [m for m in forgotten["messages"] if m.id == "native-long-term-memory"]
    assert len(remembered_memory) == len(forgotten_memory) == 1
    assert "暂无" in forgotten_memory[0].content


def test_native_resume_removes_legacy_system_messages_before_current_prompt():
    service = RagService.__new__(RagService)
    service.checkpointer = type(
        "Saver",
        (),
        {
            "get_tuple": lambda self, config: type(
                "Tuple",
                (),
                {
                    "checkpoint": {
                        "channel_values": {
                            "messages": [
                                SystemMessage(content="旧动态画像"),
                                HumanMessage(content="历史问题"),
                            ]
                        }
                    }
                },
            )()
        },
    )()
    service._native_has_messages({"configurable": {"thread_id": "t"}})
    graph_inputs = service._build_graph_inputs({"input": "新问题"}, [], include_system=True)

    assert any(isinstance(message, RemoveMessage) for message in graph_inputs["messages"])
    assert all(message.content != "旧动态画像" for message in graph_inputs["messages"])


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


def test_native_migration_records_completed_private_schema_marker():
    migration = (
        __import__("pathlib").Path(__file__).parents[1]
        / "supabase"
        / "migrations"
        / "20260911100000_native_memory_private_schema.sql"
    ).read_text(encoding="utf-8")

    assert "native_memory_private_schema" in migration
    assert "'completed'" in migration
    assert "native_state" in migration
    assert "native_error" in migration
