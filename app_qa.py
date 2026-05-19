import os
import uuid
import time
import streamlit as st
import config_data as config
from langchain_core.callbacks import BaseCallbackHandler
from rag import RagService, ConsoleLoggingHandler, FALLBACK_MESSAGE

# 强制指定阿里云 DashScope 接口不走本地代理，解决 ProxyError
if config.NO_PROXY:
    os.environ["NO_PROXY"] = config.NO_PROXY


def typewriter_stream(stream, delay: float = 0.02):
    """将流式输出拆分为逐字渲染，实现打字机效果。"""
    for chunk in stream:
        # chunk 通常是字符串或字符串列表
        text = chunk if isinstance(chunk, str) else str(chunk)
        for char in text:
            yield char
            time.sleep(delay)


class StreamlitStatusHandler(BaseCallbackHandler):
    def __init__(self, status):
        self.status = status

    def _format_tool_input(self, tool_input):
        if isinstance(tool_input, dict):
            for key in ("query", "input", "question"):
                if key in tool_input:
                    return str(tool_input[key])
            return str(tool_input)
        return str(tool_input)

    def on_agent_action(self, action, **kwargs):
        tool_name = action.tool
        query = self._format_tool_input(action.tool_input)
        if "duckduckgo" in tool_name.lower():
            message = f"🔍 正在搜索：{query}"
        elif "knowledge_base" in tool_name.lower():
            message = f"📚 正在翻阅知识库：{query}"
        else:
            message = f"🧰 正在调用工具：{tool_name}"
        self.status.update(label=message, state="running")
        self.status.write(message)

    def on_tool_end(self, output, **kwargs):
        self.status.update(label="✅ 已获取参考资料", state="running")

st.set_page_config(page_title="小衣 · AI智能穿搭顾问", page_icon="👗", layout="wide")

# --- 简洁温馨风 UI ---
cozy_css = """<style>
@import url('https://fonts.googleapis.com/css2?family=Nunito:wght@500;700&display=swap');

/* ===== 浅色主题变量（默认） ===== */
:root {
  --bg-primary: #FBF9F6;
  --bg-secondary: #FFFFFF;
  --bg-sidebar: #FFFFFF;
  --bg-user-bubble: #F0EAD6;
  --bg-assistant-bubble: #FFFFFF;
  --text-primary: #333333;
  --text-secondary: #777777;
  --border-color: #EAEAEA;
  --shadow-sm: 0 4px 12px rgba(0, 0, 0, 0.04);
  --shadow-md: 0 6px 16px rgba(0, 0, 0, 0.06);
  --button-bg: #FFFFFF;
  --button-hover-bg: #FAF3E8;
  --accent: #A3B19B;
  --accent-soft: #E8EDE5;
  --input-bg: #FFFFFF;
  --sidebar-border: #EAEAEA;
}

/* ===== 暗色主题变量 ===== */
@media (prefers-color-scheme: dark) {
  :root {
    --bg-primary: #0d1117;
    --bg-secondary: #161b22;
    --bg-sidebar: #0d1117;
    --bg-user-bubble: #1c2340;
    --bg-assistant-bubble: #161b22;
    --text-primary: #e6edf3;
    --text-secondary: #8b949e;
    --border-color: #30363d;
    --shadow-sm: 0 4px 12px rgba(0, 0, 0, 0.3);
    --shadow-md: 0 6px 20px rgba(0, 0, 0, 0.4);
    --button-bg: #161b22;
    --button-hover-bg: #1c2333;
    --accent: #8ba888;
    --accent-soft: #1c2820;
    --input-bg: #161b22;
    --sidebar-border: #21262d;
  }
}

/* ===== 全局背景 ===== */
html, body, [data-testid="stAppViewContainer"] {
  background: var(--bg-primary);
  color: var(--text-primary);
}

div[data-testid="stDecoration"] { display: none; }
[data-testid="stAppViewContainer"] > .main .block-container {
  padding: 0rem 2rem 2rem;
}

/* ===== 头部 ===== */
.app-header {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 12px;
  padding: 0.5rem 0 1rem;
}
.app-icon { color: var(--accent); font-size: 1.5rem; }
.app-title {
  font-family: "Nunito", sans-serif;
  font-size: 1.9rem;
  font-weight: 700;
  color: var(--text-primary);
  letter-spacing: 0.4px;
}

/* ===== 侧边栏 ===== */
[data-testid="stSidebar"] {
  background: var(--bg-sidebar);
  border-right: 1px solid var(--sidebar-border);
}
[data-testid="stSidebar"] .stMarkdown,
[data-testid="stSidebar"] label,
[data-testid="stSidebar"] .stSelectbox label,
[data-testid="stSidebar"] .stTextInput label {
  color: var(--text-primary) !important;
}
[data-testid="stSidebar"] h1,
[data-testid="stSidebar"] h2,
[data-testid="stSidebar"] h3,
[data-testid="stSidebar"] h4 {
  color: var(--text-primary) !important;
}
[data-testid="stSidebar"] [data-testid="stExpander"] summary {
  color: var(--text-secondary);
}
[data-testid="stSidebar"] [data-testid="stExpander"] .stMarkdown {
  color: var(--text-secondary) !important;
}
[data-testid="stSidebar"] .stSelectbox div[data-baseweb="select"] > div,
[data-testid="stSidebar"] .stTextInput input {
  background-color: var(--bg-secondary);
  color: var(--text-primary);
  border-color: var(--border-color);
}

/* ===== 分割线 ===== */
.cozy-divider {
  height: 1px;
  background: var(--border-color);
  margin: 0.8rem 0;
}

/* ===== 聊天输入框 ===== */
.stChatInputContainer textarea {
  background: var(--input-bg) !important;
  border: 1px solid var(--border-color) !important;
  color: var(--text-primary) !important;
}
.stChatInputContainer textarea::placeholder {
  color: var(--text-secondary) !important;
}

/* ===== 聊天消息基础 ===== */
div[data-testid="stChatMessage"] {
  background: transparent;
  padding: 0.35rem 0;
}
div[data-testid="stChatMessage"] div[data-testid="stChatMessageContent"] {
  border-radius: 18px;
  padding: 12px 16px;
  border: none;
  background: transparent;
  box-shadow: none;
  color: var(--text-primary);
  line-height: 1.6;
  letter-spacing: 0.3px;
}

/* ===== 用户消息气泡 ===== */
div[data-testid="stChatMessage"]:has(div[data-testid="stChatMessageAvatarUser"]) {
  flex-direction: row-reverse;
}
div[data-testid="stChatMessage"]:has(div[data-testid="stChatMessageAvatarUser"]) div[data-testid="stChatMessageContent"] {
  margin-left: auto;
  background: var(--bg-user-bubble);
  color: var(--text-primary);
}

/* ===== AI 消息气泡 ===== */
div[data-testid="stChatMessage"]:has(div[data-testid="stChatMessageAvatarAssistant"]) div[data-testid="stChatMessageContent"] {
  background: var(--bg-assistant-bubble);
  box-shadow: var(--shadow-sm);
}

/* ===== 快捷提问按钮 ===== */
[data-testid="stAppViewContainer"] > .main .stButton > button {
  width: 100%;
  background: var(--button-bg);
  border: 1px solid var(--border-color);
  border-radius: 16px;
  color: var(--text-primary);
  padding: 0.85rem 1rem;
  transition: transform 0.25s ease, background 0.25s ease, box-shadow 0.25s ease;
}
[data-testid="stAppViewContainer"] > .main .stButton > button:hover {
  transform: translateY(-2px);
  background: var(--button-hover-bg);
  box-shadow: var(--shadow-md);
}

/* ===== 侧边栏按钮 ===== */
[data-testid="stSidebar"] .stButton > button {
  background: var(--button-bg) !important;
  border: 1px solid var(--border-color) !important;
  color: var(--text-primary) !important;
  border-radius: 12px;
  transition: transform 0.25s ease, background 0.25s ease;
}
[data-testid="stSidebar"] .stButton > button:hover {
  background: var(--button-hover-bg) !important;
  transform: translateY(-1px);
}

/* ===== spinner 暗色适配 ===== */
[data-testid="stSpinner"] {
  border-color: var(--accent) transparent transparent transparent !important;
}

/* ===== 成功/提示消息 ===== */
div[data-testid="stNotification"] {
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  color: var(--text-primary);
}

/* ===== 滚动条暗色适配 ===== */
@media (prefers-color-scheme: dark) {
  ::-webkit-scrollbar { width: 8px; }
  ::-webkit-scrollbar-track { background: var(--bg-primary); }
  ::-webkit-scrollbar-thumb { background: #30363d; border-radius: 4px; }
  ::-webkit-scrollbar-thumb:hover { background: #484f58; }
}
</style>"""
st.markdown(cozy_css, unsafe_allow_html=True)

header_html = "<div class=\"app-header\"><span class=\"app-icon\">☀️</span><div class=\"app-title\">小衣 · 你的专属穿搭顾问</div></div>"
st.markdown(header_html, unsafe_allow_html=True)

if "message" not in st.session_state:
    st.session_state["message"] = [{"role": "assistant", "content": "你好，有什么可以帮助你？"}]

if "rag" not in st.session_state:
    st.session_state["rag"] = RagService()

if "session_id" not in st.session_state:
    st.session_state["session_id"] = uuid.uuid4().hex

with st.sidebar:
    st.header("👤 我的穿搭档案")
    gender_options = ["女生", "男生"]
    gender_labels = {"女生": "👩 女生", "男生": "👨 男生"}
    user_gender = st.selectbox(
        "选择你的性别", gender_options, format_func=lambda v: gender_labels.get(v, v)
    )
    style_options = ["日常休闲", "职场通勤", "甜美可爱", "运动风", "极简冷淡风"]
    style_labels = {
        "日常休闲": "🧢 日常休闲",
        "职场通勤": "💼 职场通勤",
        "甜美可爱": "🎀 甜美可爱",
        "运动风": "🏃 运动风",
        "极简冷淡风": "🖤 极简冷淡风",
    }
    user_style = st.selectbox(
        "偏好的穿搭风格",
        style_options,
        format_func=lambda v: style_labels.get(v, v),
    )
    user_body = st.text_input(
        "📏 输入你的身高/体重 (选填)", placeholder="例如：165cm / 50kg"
    )

    with st.expander("🛠️ 开发者模式 (调试信息)", expanded=False):
        st.text(f"Session ID: {st.session_state['session_id']}")

    st.markdown('<div class="cozy-divider"></div>', unsafe_allow_html=True)
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
        with st.status("🧵 小衣正在梳理搭配思路...", expanded=True) as status:
            handler = StreamlitStatusHandler(status)
            try:
                stream = st.session_state["rag"].stream(
                    {
                        "input": final_prompt,
                        "gender": user_gender,
                        "style": user_style,
                        "body": user_body,
                    },
                    config={
                        "configurable": {"session_id": st.session_state["session_id"]},
                        "callbacks": [ConsoleLoggingHandler(), handler],
                    },
                )
                res = st.write_stream(typewriter_stream(stream))
                status.update(label="✅ 穿搭建议已生成", state="complete", expanded=False)
            except Exception:
                res = FALLBACK_MESSAGE
                status.update(label="⚠️ 小衣当前思考超时，请稍后再试", state="error", expanded=False)
                st.write(res)
    st.session_state["message"].append({"role": "assistant", "content": res})
