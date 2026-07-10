"""摘要性能诊断脚本。

这个脚本用于对聊天摘要链路做抽查诊断，不属于正式业务路径。

适用场景：
1. `new_summary_len` 接近 `chat_history_summary_target_chars`（当前 600）。
2. `prompt_len` 相比当前阶段性结果出现明显上升。
3. 单次摘要调用耗时稳定超过 8-10 秒，需要判断是输入增长还是模型/API波动。

功能：
1. 从 Supabase 读取指定 session 的真实聊天记录。
2. 按当前 history.py 的摘要触发规则，重建 round13/16/19/22/25/28 的摘要输入。
3. 记录实际传给 LLM 的完整 prompt、字符长度、旧摘要长度、6 条新消息长度、LLM 耗时。
4. 对 round25 的固定输入执行 5 次间隔调用，观察纯 LLM 耗时波动。

说明：
- 该脚本是独立诊断工具，不修改正式业务逻辑。
- 输出 JSON 建议作为一次性本地产物使用，不提交到 git。
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, message_to_dict, messages_from_dict
from supabase import create_client

import config_data as config
from rag import RagService


TARGET_SESSION_ID = "verify_perf_new_1ebc84b7"
TARGET_ROUNDS = {13, 16, 19, 22, 25, 28}
FIXED_INPUT_REPEAT = 5
FIXED_INPUT_SLEEP_SECONDS = 4
BASE_DIR = Path(__file__).resolve().parent.parent


def load_secrets() -> tuple[str, str]:
    """读取本地 secrets.toml 中的 Supabase 凭据。"""
    text = (BASE_DIR / ".streamlit" / "secrets.toml").read_text(encoding="utf-8")
    url = re.search(r'SUPABASE_URL\s*=\s*"([^"]+)"', text).group(1)
    key = re.search(r'SUPABASE_KEY\s*=\s*"([^"]+)"', text).group(1)
    return url, key


def stringify_messages(messages: list[BaseMessage]) -> str:
    """把消息列表转成与正式摘要逻辑一致的纯文本。"""
    lines: list[str] = []
    for msg in messages:
        if isinstance(msg, HumanMessage):
            role = "用户"
        elif isinstance(msg, AIMessage):
            role = "小衣"
        else:
            role = getattr(msg, "type", msg.__class__.__name__)
        lines.append(f"{role}：{msg.content}")
    return "\n".join(lines)


def build_summary_prompt(previous_summary: str, messages_to_summarize: list[BaseMessage]) -> str:
    """按 rag.py 当前逻辑组装摘要 prompt。"""
    return (
        "你是聊天记忆压缩器。请把“已有长期记忆”和“新增旧对话”压缩成一份稳定、可复用的长期用户画像。\n\n"
        "要求：\n"
        f"1. 输出目标是不超过 {config.chat_history_summary_target_chars} 字，必须主动压缩，不要把旧摘要和新内容简单累加。\n"
        "2. 优先保留稳定、长期有价值的信息：身材信息、所在城市、风格偏好、禁忌、常见场景、鞋包配饰偏好。\n"
        "3. 合并同类项，删除重复表达。允许舍弃一次性、低价值、已被更稳定偏好概括的细节。\n"
        "4. 不要编造对话中没有出现的信息。\n"
        "5. 使用中文、条目化输出，内容尽量按“身材/城市/风格/禁忌/场景/鞋包配饰”归类。\n"
        f"6. 即使信息很多，也要压缩到不超过 {config.chat_history_summary_target_chars} 字附近。\n\n"
        f"【已有长期记忆】\n{previous_summary or '暂无'}\n\n"
        f"【新增旧对话】\n{stringify_messages(messages_to_summarize)}\n\n"
        "请输出压缩后的长期用户画像："
    )


def load_session_row(session_id: str) -> dict[str, Any]:
    """读取目标会话的持久化行。"""
    url, key = load_secrets()
    client = create_client(url, key)
    rows = (
        client.table("chat_messages")
        .select("session_id,messages,recent_messages,summary,summary_message_count,updated_at")
        .eq("session_id", session_id)
        .limit(1)
        .execute()
        .data
    )
    if not rows:
        raise RuntimeError(f"未找到会话: {session_id}")
    return rows[0]


def deserialize_messages(raw_value: str | None) -> list[BaseMessage]:
    """把 JSON 字符串还原成 LangChain message 列表。"""
    if not raw_value:
        return []
    return messages_from_dict(json.loads(raw_value))


def round_number_from_message_count(message_count: int) -> int:
    """把消息条数换算为用户轮次。

    当前测试里每轮都是 1 条用户消息 + 1 条 AI 回复，因此一轮等于 2 条消息。
    """
    return message_count // 2


def capture_round_prompts(service: RagService, full_messages: list[BaseMessage]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """按当前摘要规则重建触发点，并在指定 round 记录 prompt 与耗时。"""
    max_recent_messages = int(config.chat_history_max_rounds) * 2
    interval_message_limit = int(config.chat_history_summary_interval_rounds) * 2

    previous_summary = ""
    summary_message_count = 0
    trigger_records: list[dict[str, Any]] = []
    fixed_input_record: dict[str, Any] | None = None

    for end in range(2, len(full_messages) + 1, 2):
        current_messages = full_messages[:end]
        recent_messages = current_messages[-max_recent_messages:] if max_recent_messages > 0 else current_messages
        overflow_end = max(0, len(current_messages) - len(recent_messages))
        remaining_overflow = current_messages[summary_message_count:overflow_end]
        if len(remaining_overflow) < interval_message_limit:
            continue

        round_no = round_number_from_message_count(end)
        prompt = build_summary_prompt(previous_summary, remaining_overflow)
        start = time.time()
        response = service.chat_model.invoke(prompt)
        elapsed = time.time() - start
        content = response.content if hasattr(response, "content") else str(response)
        new_summary = service._truncate_summary_text(str(content))

        record = {
            "round": round_no,
            "prev_summary_len": len(previous_summary),
            "new_messages_count": len(remaining_overflow),
            "new_messages_text_len": len(stringify_messages(remaining_overflow)),
            "prompt_len": len(prompt),
            "llm_s": round(elapsed, 3),
            "new_summary_len": len(new_summary),
            "prompt": prompt,
            "new_messages_preview": [message_to_dict(msg) for msg in remaining_overflow],
        }
        if round_no in TARGET_ROUNDS:
            trigger_records.append(record)
        if round_no == 25:
            fixed_input_record = {
                "previous_summary": previous_summary,
                "messages_to_summarize": remaining_overflow,
                "prompt": prompt,
                "prompt_len": len(prompt),
                "prev_summary_len": len(previous_summary),
                "new_messages_count": len(remaining_overflow),
                "new_messages_text_len": len(stringify_messages(remaining_overflow)),
            }

        previous_summary = new_summary
        summary_message_count += len(remaining_overflow)

    if fixed_input_record is None:
        raise RuntimeError("未能定位 round25 的摘要输入。")
    return trigger_records, fixed_input_record


def run_fixed_input_benchmark(service: RagService, fixed_input: dict[str, Any]) -> list[dict[str, Any]]:
    """对同一份摘要输入做 5 次间隔调用，观察纯 LLM 波动。"""
    prompt = fixed_input["prompt"]
    results: list[dict[str, Any]] = []
    for index in range(1, FIXED_INPUT_REPEAT + 1):
        start = time.time()
        error_text = ""
        summary_len = None
        try:
            response = service.chat_model.invoke(prompt)
            content = response.content if hasattr(response, "content") else str(response)
            summary_text = service._truncate_summary_text(str(content))
            summary_len = len(summary_text)
        except Exception as exc:
            error_text = repr(exc)
        elapsed = time.time() - start
        results.append(
            {
                "run": index,
                "llm_s": round(elapsed, 3),
                "summary_len": summary_len,
                "error": error_text,
                "sleep_after_s": FIXED_INPUT_SLEEP_SECONDS if index < FIXED_INPUT_REPEAT else 0,
            }
        )
        if index < FIXED_INPUT_REPEAT:
            time.sleep(FIXED_INPUT_SLEEP_SECONDS)
    return results


def main() -> None:
    row = load_session_row(TARGET_SESSION_ID)
    full_messages = deserialize_messages(row.get("messages"))
    service = RagService(user_id="diagnose_summary_perf")

    trigger_records, fixed_input = capture_round_prompts(service, full_messages)
    fixed_benchmark = run_fixed_input_benchmark(service, fixed_input)

    output = {
        "session_id": TARGET_SESSION_ID,
        "message_count": len(full_messages),
        "target_rounds": sorted(TARGET_ROUNDS),
        "trigger_records": trigger_records,
        "fixed_input": {
            "prev_summary_len": fixed_input["prev_summary_len"],
            "new_messages_count": fixed_input["new_messages_count"],
            "new_messages_text_len": fixed_input["new_messages_text_len"],
            "prompt_len": fixed_input["prompt_len"],
            "prompt": fixed_input["prompt"],
            "messages_to_summarize": [message_to_dict(msg) for msg in fixed_input["messages_to_summarize"]],
        },
        "fixed_input_benchmark": fixed_benchmark,
        "notes": {
            "rate_limit_headers": "ChatTongyi.invoke 当前调用链未暴露 HTTP 响应头；本脚本只能记录异常文本，无法直接捕获响应头。",
            "sleep_between_runs_s": FIXED_INPUT_SLEEP_SECONDS,
        },
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()