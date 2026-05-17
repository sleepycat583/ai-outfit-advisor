import os
import uuid
import time
import streamlit as st
from rag import RagService, ConsoleLoggingHandler

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

st.set_page_config(page_title="RAG Question Answering", layout="wide")

st.title("🤖 RAG Question Answering System")

if "message" not in st.session_state:
    st.session_state["message"] = [{"role": "assistant", "content": "你好，有什么可以帮助你？"}]

if "rag" not in st.session_state:
    st.session_state["rag"] = RagService()

if "session_id" not in st.session_state:
    st.session_state["session_id"] = uuid.uuid4().hex

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
    # 在页面输出用户的提问
    st.chat_message("user").write(final_prompt)
    st.session_state["message"].append({"role": "user", "content": final_prompt})

    with st.chat_message("assistant"):
        with st.spinner("AI思考中..."):
            stream = st.session_state["rag"].chain.stream(
                {
                    "input": final_prompt,
                    "gender": user_gender,
                    "style": user_style,
                    "body": user_body,
                },
                config={
                    "configurable": {"session_id": st.session_state["session_id"]},
                    "callbacks": [ConsoleLoggingHandler()],
                },
            )
            res = st.write_stream(typewriter_stream(stream))
    st.session_state["message"].append({"role": "assistant", "content": res})
