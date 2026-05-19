import os
import uuid
import time
import streamlit as st
from rag import RagService, ConsoleLoggingHandler
import config_data as config
from recommendation_rules import build_constraints
from telemetry import append_jsonl, now_iso

REQUEST_WINDOW_SECONDS = int(config.request_window_seconds)
MAX_REQUESTS_PER_WINDOW = int(config.max_requests_per_window)
MAX_FAILURE_REASON_LENGTH = int(config.max_failure_reason_length)

# 强制指定阿里云 DashScope 接口不走本地代理，解决 ProxyError
os.environ["NO_PROXY"] = "dashscope.aliyuncs.com"


def typewriter_stream(stream, delay: float = 0.02):
    """将流式输出拆分为逐字渲染，实现打字机效果。"""
    for chunk in stream:
        # chunk 通常是字符串或字符串列表
        text = chunk if isinstance(chunk, str) else str(chunk)
        for char in text:
            yield char
            time.sleep(delay)


def fallback_response(scene: str, style: str, budget: str, body: str) -> str:
    hint = f"场景：{scene}｜风格：{style}｜预算：{budget}"
    body_tip = f"并结合体型信息（{body}）优化版型。" if body else "可补充身高体重获取更精准版型建议。"
    return (
        "⛅ 【场景与温度感知】\n"
        "我先给你一套稳妥不出错的搭配方向。\n\n"
        "✨ 【主理人 OOTD 灵感】\n"
        f"- 建议优先选择**基础款上衣** + **中性色下装** + **低饱和鞋包**，{hint}。\n"
        "- 先保证合身，再用配饰强化风格层次。\n\n"
        "💡 【小衣私藏贴士】\n"
        f"{body_tip}\n\n"
        f"{config.assistant_signature}"
    )


def is_rate_limited() -> bool:
    now = time.time()
    timestamps = st.session_state.setdefault("request_timestamps", [])
    st.session_state["request_timestamps"] = [
        t for t in timestamps if now - t <= REQUEST_WINDOW_SECONDS
    ]
    if len(st.session_state["request_timestamps"]) >= MAX_REQUESTS_PER_WINDOW:
        return True
    else:
        st.session_state["request_timestamps"].append(now)
        return False

st.set_page_config(page_title="RAG Question Answering", layout="wide")

st.title("🤖 RAG Question Answering System")

if "message" not in st.session_state:
    st.session_state["message"] = [{"role": "assistant", "content": "你好，有什么可以帮助你？"}]

if "rag" not in st.session_state:
    st.session_state["rag"] = RagService()

if "session_id" not in st.session_state:
    st.session_state["session_id"] = uuid.uuid4().hex

if "last_assistant_response" not in st.session_state:
    st.session_state["last_assistant_response"] = ""

with st.sidebar:
    st.header("👤 我的穿搭档案")
    user_gender = st.selectbox("选择你的性别", ["女生", "男生"])
    user_style = st.selectbox(
        "偏好的穿搭风格",
        ["日常休闲", "职场通勤", "甜美可爱", "运动风", "极简冷淡风"],
    )
    user_body = st.text_input(
        "输入你的身高/体重 (选填)", placeholder="例如：165cm / 50kg"
    )
    user_scene = st.selectbox(
        "主要场景",
        ["通用场景", "面试/职场", "约会", "通勤上课", "旅行出游", "运动健身"],
    )
    user_budget = st.selectbox(
        "预算档位",
        ["不限预算", "100元以内", "300元以内", "500元以内", "1000元以内", "1000元以上"],
    )

    with st.expander("🛠️ 开发者模式 (调试信息)", expanded=False):
        st.text(f"Session ID: {st.session_state['session_id']}")

    st.write("---")
    if st.sidebar.button("🔄 重置系统与服务", use_container_width=True):
        st.session_state.clear()
        st.success("服务已重置，正在重新加载...")
        st.rerun()

for message in st.session_state["message"]:
    st.chat_message(message["role"]).write(message["content"])

# --- 新增：快捷提问按钮 ---
preset_prompt = None
col1, col2, col3 = st.columns(3)
with col1:
    if st.button("👔 明天参加社团面试，求推荐穿搭！", use_container_width=True):
        preset_prompt = "明天参加社团面试，求推荐穿搭！"
with col2:
    if st.button("🧥 我的羽绒服弄脏了，应该怎么洗？", use_container_width=True):
        preset_prompt = "我的羽绒服弄脏了，应该怎么洗？"
with col3:
    if st.button("👗 我身高160，体重100斤，适合什么尺码？", use_container_width=True):
        preset_prompt = "我身高160，体重100斤，适合什么尺码？"

# --- 接收用户输入 ---
prompt = st.chat_input("例如：明天要去互联网公司面试实习生，我该怎么穿？")

# --- 处理逻辑 ---
final_prompt = prompt or preset_prompt

if final_prompt:
    if is_rate_limited():
        st.warning("请求过于频繁，请稍后再试（限流保护）。")
        st.stop()

    constraints = build_constraints(
        gender=user_gender,
        style=user_style,
        body=user_body,
        scene=user_scene,
        budget=user_budget,
    )

    # 在页面输出用户的提问
    st.chat_message("user").write(final_prompt)
    st.session_state["message"].append({"role": "user", "content": final_prompt})

    start_time = time.time()
    success = True
    failure_reason = ""
    with st.chat_message("assistant"):
        with st.spinner("AI思考中..."):
            try:
                stream = st.session_state["rag"].chain.stream(
                    {
                        "input": final_prompt,
                        "gender": user_gender,
                        "style": user_style,
                        "body": user_body,
                        "scene": user_scene,
                        "budget": user_budget,
                    },
                    config={
                        "configurable": {"session_id": st.session_state["session_id"]},
                        "callbacks": [ConsoleLoggingHandler()],
                    },
                )
                res = st.write_stream(typewriter_stream(stream))
            except Exception as e:
                success = False
                failure_reason = f"{type(e).__name__}: model_or_tool_call_failed"
                res = fallback_response(user_scene, user_style, user_budget, user_body)
                st.write(res)
    st.session_state["message"].append({"role": "assistant", "content": res})
    st.session_state["last_assistant_response"] = res

    latency_ms = int((time.time() - start_time) * 1000)
    append_jsonl(
        config.metrics_path,
        {
            "ts": now_iso(),
            "session_id": st.session_state["session_id"],
            "success": success,
            "latency_ms": latency_ms,
            "prompt_length": len(final_prompt),
            "scene": constraints.scene,
            "style": constraints.style,
            "budget": constraints.budget,
            "failure_reason": failure_reason[:MAX_FAILURE_REASON_LENGTH],
        },
    )

if st.session_state.get("last_assistant_response"):
    st.write("---")
    st.caption("这条建议对你有帮助吗？可收藏或反馈，帮助我持续优化。")
    col_like, col_dislike, col_fav = st.columns(3)
    if col_like.button("👍 有帮助", use_container_width=True):
        append_jsonl(
            config.feedback_path,
            {
                "ts": now_iso(),
                "session_id": st.session_state["session_id"],
                "feedback": "positive",
                "response": st.session_state["last_assistant_response"],
            },
        )
        st.success("收到你的正向反馈啦！")
    if col_dislike.button("👎 需改进", use_container_width=True):
        append_jsonl(
            config.feedback_path,
            {
                "ts": now_iso(),
                "session_id": st.session_state["session_id"],
                "feedback": "negative",
                "response": st.session_state["last_assistant_response"],
            },
        )
        st.success("收到你的改进反馈，我会继续优化。")
    if col_fav.button("⭐ 收藏这套", use_container_width=True):
        append_jsonl(
            config.favorites_path,
            {
                "ts": now_iso(),
                "session_id": st.session_state["session_id"],
                "response": st.session_state["last_assistant_response"],
            },
        )
        st.success("已收藏到本地记录。")
