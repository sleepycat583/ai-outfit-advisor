import uuid
import streamlit as st
from rag import RagService

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

for message in st.session_state["message"]:
    st.chat_message(message["role"]).write(message["content"])

# 在页面底部获取用户输入
prompt = st.chat_input()

if prompt:
    # 在页面输出用户的提问
    st.chat_message("user").write(prompt)
    st.session_state["message"].append({"role": "user", "content": prompt})

    with st.chat_message("assistant"):
        with st.spinner("AI思考中..."):
            session_config = {
                "configurable": {
                    "session_id": st.session_state["session_id"],
                }
            }
            stream = st.session_state["rag"].chain.stream(
                {
                    "input": prompt,
                    "gender": user_gender,
                    "style": user_style,
                    "body": user_body,
                },
                config=session_config,
            )
            res = st.write_stream(stream)
    st.session_state["message"].append({"role": "assistant", "content": res})
