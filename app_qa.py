import os
import uuid
import time
import datetime
import streamlit as st
import config_data as config
from langchain_core.callbacks import BaseCallbackHandler
from rag import RagService, ConsoleLoggingHandler, FALLBACK_MESSAGE
from wardrobe_service import WardrobeService

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

/* ===== 删除按钮 ===== */
button[aria-label="❌ 移除此单品"] {
  background: #ff5a5f !important;
  border-color: #ff5a5f !important;
  color: #ffffff !important;
}
button[aria-label="❌ 移除此单品"]:hover {
  background: #ff3b3f !important;
  border-color: #ff3b3f !important;
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

/* ===== 终极修复：强制固定并抬高底部输入框 ===== */
div[data-testid="stChatInput"] {
  position: fixed !important;
  bottom: 2rem !important;
  left: 20rem !important;
  right: 2rem !important;
  width: auto !important;
  z-index: 9999 !important;
  background-color: var(--bg-primary) !important;
  border: 1px solid var(--border-color) !important;
  border-radius: 12px !important;
  box-shadow: var(--shadow-md) !important;
  padding: 0.5rem !important;
}

@media (max-width: 991px) {
  div[data-testid="stChatInput"] {
    left: 1.5rem !important;
    right: 1.5rem !important;
    bottom: 1.5rem !important;
  }
}

[data-testid="stAppViewContainer"] > .main .block-container {
  padding-bottom: 180px !important;
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

if "wardrobe_draft" not in st.session_state:
    st.session_state["wardrobe_draft"] = None

if "weekly_plan" not in st.session_state:
    st.session_state["weekly_plan"] = None

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

tab_chat, tab_wardrobe = st.tabs(["💬 穿搭顾问", "👗 智能衣橱"])

with tab_chat:
    wardrobe_service = WardrobeService()
    wardrobe_items = wardrobe_service.get_all_items()

    st.markdown("#### 📅 本周穿搭计划")
    plan_col, hint_col = st.columns([1, 3])
    with plan_col:
        generate_plan = st.button("📅 生成本周穿搭计划", use_container_width=True)
    with hint_col:
        if not wardrobe_items:
            st.caption("快去‘智能衣橱’拍照上传你的第一件美衣吧！")

    if generate_plan:
        if not wardrobe_items:
            st.info("快去‘智能衣橱’拍照上传你的第一件美衣吧！")
        else:
            progress = st.progress(5, text="正在生成本周穿搭计划...")
            plan = st.session_state["rag"].generate_weekly_plan(
                gender=user_gender,
                style=user_style,
                body=user_body,
                current_date=datetime.datetime.now().strftime("%Y年%m月%d日"),
                wardrobe_items=wardrobe_items,
            )
            progress.progress(100, text="本周穿搭计划已生成")
            st.session_state["weekly_plan"] = plan

    weekly_plan = st.session_state.get("weekly_plan")
    if weekly_plan:
        week_tabs = st.tabs(["周一", "周二", "周三", "周四", "周五", "周六", "周日"])
        for day_tab, day_plan in zip(week_tabs, weekly_plan):
            with day_tab:
                st.markdown(f"**场景感知：**{day_plan.get('scene', '')}")
                st.markdown("**OOTD 灵感：**")
                for item in day_plan.get("ootd", []):
                    st.markdown(f"- **{item}**")
                st.markdown(f"**小贴士：**{day_plan.get('tips', '')}")

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
            status = st.status("🧵 小衣正在梳理搭配思路...", expanded=True)
            handler = StreamlitStatusHandler(status)

            try:
                stream = st.session_state["rag"].stream(
                    {
                        "input": final_prompt,
                        "gender": user_gender,
                        "style": user_style,
                        "body": user_body,
                        "current_date": datetime.datetime.now().strftime("%Y年%m月%d日"),
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

with tab_wardrobe:
    st.subheader("👗 智能衣橱")
    service = WardrobeService()

    uploaded_file = st.file_uploader("上传衣服照片", type=["jpg", "jpeg", "png", "webp"])
    if uploaded_file:
        st.image(uploaded_file, width=260)
        if st.button("🔍 智能识衣并入库"):
            with st.spinner("正在识别衣物信息..."):
                analysis = service.analyze_clothing_image(uploaded_file.getvalue())
            st.session_state["wardrobe_draft"] = analysis

    draft = st.session_state.get("wardrobe_draft")
    if draft:
        st.markdown("#### 识别结果（可手动调整）")
        category_options = config.WARDROBE_CATEGORIES
        draft_category = draft.get("category")
        if draft_category in category_options:
            category_index = category_options.index(draft_category)
        else:
            category_index = 0
        category = st.selectbox("一级分类", category_options, index=category_index)
        sub_category = st.text_input("细分类别", value=draft.get("sub_category", ""))
        color = st.text_input("颜色", value=draft.get("color", ""))
        material = st.text_input("材质", value=draft.get("material", ""))
        season_options = ["春", "夏", "秋", "冬"]
        season_value = draft.get("season", [])
        if isinstance(season_value, str):
            season_value = [season_value]
        season_default = [s for s in season_value if s in season_options]
        season = st.multiselect("适合季节", season_options, default=season_default)

        if st.button("✅ 确认加入衣橱"):
            item_data = {
                "category": category,
                "sub_category": sub_category,
                "color": color,
                "material": material,
                "season": season,
            }
            service.add_item(item_data)
            st.session_state["wardrobe_draft"] = None
            st.success("已加入衣橱")
            st.rerun()

    st.markdown("### 我的衣橱")
    items = service.get_all_items()
    if not items:
        st.info("还没有衣物记录，先上传一张照片吧。")
    else:
        icon_map = {
            "外套": "🧥",
            "内搭": "👕",
            "下装": "👖",
            "鞋履": "👟",
            "配饰": "🧢",
        }
        cols = st.columns(4)
        for index, item in enumerate(items):
            col = cols[index % 4]
            with col:
                category = item.get("category", "")
                icon = icon_map.get(category, "👗")
                title = item.get("sub_category") or category or "未命名"
                st.markdown(f"#### {icon} {title}")
                st.write(f"颜色：{item.get('color', '未知')}")
                st.write(f"材质：{item.get('material', '未知')}")
                if st.button("❌ 移除此单品", key=f"delete_{item.get('id')}"):
                    service.delete_item(item.get("id"))
                    st.rerun()
