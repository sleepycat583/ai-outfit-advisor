import base64
import os
import re
import uuid
import time
import datetime
import streamlit as st
import config_data as config
from langchain_core.callbacks import BaseCallbackHandler
from langchain_community.embeddings import DashScopeEmbeddings
from rag import RagService, ConsoleLoggingHandler, FALLBACK_MESSAGE
from user_service import UserService
from vector_store_service import VectorWardrobeService
from wardrobe_service import WardrobeService

# 强制指定阿里云 DashScope 接口不走本地代理，解决 ProxyError
if config.NO_PROXY:
    os.environ["NO_PROXY"] = config.NO_PROXY



def render_page():
    """渲染穿搭问答页面（问答 + 智能衣橱）。
    由 app_main.py 安全导入调用，也可独立运行。
    """
    def typewriter_stream(stream, delay: float = 0.02):
        """将流式输出拆分为逐字渲染，实现打字机效果。"""
        for chunk in stream:
            # chunk 通常是字符串或字符串列表
            text = chunk if isinstance(chunk, str) else str(chunk)
            for char in text:
                yield char
                time.sleep(delay)


    def get_image_base64(image_path):
        """读取本地图片文件并转换为 Base64 字符串。"""
        with open(image_path, "rb") as f:
            return base64.b64encode(f.read()).decode("utf-8")


    def build_item_flex_card(item, img_b64):
        """生成单品微缩卡片的 HTML 字符串（左图右文 Flexbox）。"""
        import html as _html

        name = _html.escape(item.get("sub_category") or item.get("category") or "单品")
        color = _html.escape(item.get("color", "未知"))
        material = _html.escape(item.get("material", "未知"))
        return f"""<div style="display: inline-flex; align-items: center; background: rgba(163, 177, 155, 0.08); padding: 8px 12px; border-radius: 10px; border: 1px solid rgba(163, 177, 155, 0.3); margin: 6px 8px 6px 0; gap: 14px;">
        <div style="background: #ffffff; border-radius: 6px; padding: 3px; box-shadow: 0 2px 5px rgba(0,0,0,0.06); display: flex; align-items: center; justify-content: center; height: 116px; min-width: 80px;">
            <img src="data:image/jpeg;base64,{img_b64}" style="height: 110px; width: auto; max-width: 90px; object-fit: contain; border-radius: 4px;">
        </div>
        <div style="display: flex; flex-direction: column; justify-content: center; min-width: 120px;">
            <span style="font-weight: bold; font-size: 15px; color: var(--text-primary); margin-bottom: 6px;">{name}</span>
            <span style="font-size: 12px; color: #777; background: rgba(0,0,0,0.04); padding: 2px 6px; border-radius: 4px; display: inline-block; width: fit-content;">🎨 {color}</span>
            <span style="font-size: 12px; color: #777; background: rgba(0,0,0,0.04); padding: 2px 6px; border-radius: 4px; display: inline-block; width: fit-content; margin-top: 4px;">🧵 {material}</span>
        </div>
    </div>"""


    def build_wardrobe_card(item, img_b64, icon):
        import html as _html

        name = _html.escape(item.get("sub_category") or item.get("category") or "单品")
        color = _html.escape(item.get("color", "未知"))
        material = _html.escape(item.get("material", "未知"))
        return f"""<div style="background: var(--bg-secondary); border-radius: 8px; border: 1px solid var(--border-color); overflow: hidden; width: 100%; box-shadow: var(--shadow-sm);">
    <div style="width: 100%; aspect-ratio: 3 / 4; max-height: 260px; background: #f5f5f5; display: flex; align-items: center; justify-content: center; overflow: hidden;">
        <img src="data:image/jpeg;base64,{img_b64}" style="max-width: 100%; max-height: 100%; object-fit: contain;">
    </div>
    <div style="padding: 6px 8px 5px;">
        <div style="font-weight: 600; font-size: 13px; color: var(--text-primary); margin-bottom: 3px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">{icon} {name}</div>
        <span style="font-size: 11px; color: #888;">🎨 {color}</span>
        <span style="font-size: 11px; color: #888; margin-left: 6px;">🧵 {material}</span>
    </div>
</div>"""

    def build_wardrobe_card_placeholder(item, icon):
        import html as _html

        name = _html.escape(item.get("sub_category") or item.get("category") or "单品")
        color = _html.escape(item.get("color", "未知"))
        material = _html.escape(item.get("material", "未知"))
        return f"""<div style="background: var(--bg-secondary); border-radius: 8px; border: 1px solid var(--border-color); overflow: hidden; width: 100%; box-shadow: var(--shadow-sm);">
    <div style="width: 100%; aspect-ratio: 3 / 4; max-height: 260px; background: rgba(163,177,155,0.06); display: flex; align-items: center; justify-content: center; font-size: 42px;">{icon}</div>
    <div style="padding: 6px 8px 5px;">
        <div style="font-weight: 600; font-size: 13px; color: var(--text-primary); margin-bottom: 3px;">{icon} {name}</div>
        <span style="font-size: 11px; color: #888;">🎨 {color}</span>
        <span style="font-size: 11px; color: #888; margin-left: 6px;">🧵 {material}</span>
    </div>
</div>"""

    def render_recommendations(item_ids, w_items):
        """在文字下方以网格形式渲染推荐单品列表。"""
        item_map = {item.get("id"): item for item in w_items}
        valid_items = []
        for iid in item_ids:
            item = item_map.get(iid)
            if not item:
                continue
            image_path = item.get("image_path", "")
            if not image_path or not os.path.exists(image_path):
                continue
            img_b64 = get_image_base64(image_path)
            valid_items.append((item, img_b64))

        if not valid_items:
            return

        with st.container(border=True):
            st.markdown("##### ✨ 推荐单品")
            cols_per_row = 3
            for row_start in range(0, len(valid_items), cols_per_row):
                row_items = valid_items[row_start:row_start + cols_per_row]
                cols = st.columns(cols_per_row)
                for col, (item, img_b64) in zip(cols, row_items):
                    with col:
                        card_html = build_item_flex_card(item, img_b64)
                        st.markdown(card_html, unsafe_allow_html=True)


    def render_message(text, w_items):
        """渲染完整消息：先渲染纯净文字，再在下方展示推荐单品网格。"""
        item_ids = re.findall(r"<item>(.*?)</item>", text)
        clean_text = re.sub(r"<item>.*?</item>", "", text).strip()
        st.markdown(clean_text)
        if item_ids:
            render_recommendations(item_ids, w_items)


    class HumanizedStatusHandler(BaseCallbackHandler):
        """拟人化状态回调：将 Agent 内部步骤翻译为有趣的用户提示语。"""

        TOOL_LABELS = {
            "weather_search": ("🌤️", "正在观测天象", "查询天气"),
            "knowledge_base_search": ("📚", "正在翻阅时尚秘籍", "检索穿搭知识"),
        }

        def __init__(self):
            self._step = 0

        def _extract_query(self, tool_input) -> str:
            if isinstance(tool_input, dict):
                for key in ("query", "input", "question"):
                    if key in tool_input:
                        return str(tool_input[key])[:60]
                return str(tool_input)[:60]
            return str(tool_input)[:60]

        def on_llm_start(self, _serialized, _prompts, **_kwargs):
            self._step += 1
            if self._step == 1:
                st.write("🤔 正在理解你的需求，构思搭配方向...")
            else:
                st.write("🤔 托腮沉思中，综合已有信息继续推敲...")

        def on_agent_action(self, action, **_kwargs):
            tool_name = action.tool
            query = self._extract_query(action.tool_input)
            emoji, verb, noun = self.TOOL_LABELS.get(
                tool_name, ("🛠️", f"正在调用 {tool_name}", "")
            )
            if noun and query:
                st.write(f"{emoji} {verb}（{noun}）：{query}")
            else:
                st.write(f"{emoji} {verb}...")

        def on_tool_end(self, _output, **_kwargs):
            st.write("✅ 信息已获取，继续优化方案...")

        def on_agent_finish(self, _finish, **_kwargs):
            st.write("✨ 灵感迸发，正在为你整理专属穿搭方案...")


    # [安全修复] st.set_page_config 移至模块 __main__ 守卫，防止被 import 时重复调用

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

    user_id = st.session_state.get("user_id")
    if not user_id:
        st.warning("请先登录")
        st.stop()

    if "message" not in st.session_state:
        st.session_state["message"] = [{"role": "assistant", "content": "你好，有什么可以帮助你？"}]

    if "vector_wardrobe" not in st.session_state:
        embedding = DashScopeEmbeddings(model=config.EMBEDDING_MODEL_NAME)
        st.session_state["vector_wardrobe"] = VectorWardrobeService(embedding, user_id=user_id)

    if "rag" not in st.session_state:
        st.session_state["rag"] = RagService(
            vector_wardrobe=st.session_state["vector_wardrobe"],
            user_id=user_id,
        )

    if "session_id" not in st.session_state:
        st.session_state["session_id"] = f"chat_session_{user_id}"

    if "wardrobe_draft" not in st.session_state:
        st.session_state["wardrobe_draft"] = None

    if "weekly_plan" not in st.session_state:
        st.session_state["weekly_plan"] = None

    with st.sidebar:
        st.header("👤 我的穿搭档案")

        user_service = UserService()
        saved_profile = user_service.get_profile(user_id)

        if "user_gender" not in st.session_state:
            st.session_state["user_gender"] = saved_profile.get("gender", "女生")
        if "user_style" not in st.session_state:
            st.session_state["user_style"] = saved_profile.get("style", "日常休闲")
        if "user_body" not in st.session_state:
            st.session_state["user_body"] = saved_profile.get("body", "")
        if "user_city" not in st.session_state:
            st.session_state["user_city"] = saved_profile.get("city", "北京")
        if "_last_saved_profile" not in st.session_state:
            st.session_state["_last_saved_profile"] = saved_profile.copy()

        gender_options = ["女生", "男生"]
        gender_labels = {"女生": "👩 女生", "男生": "👨 男生"}
        user_gender = st.selectbox(
            "选择你的性别", gender_options, key="user_gender", format_func=lambda v: gender_labels.get(v, v)
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
            key="user_style",
            format_func=lambda v: style_labels.get(v, v),
        )
        user_body = st.text_input(
            "📏 输入你的身高/体重 (选填)", key="user_body", placeholder="例如：165cm / 50kg"
        )
        user_city = st.text_input("📍 所在城市", key="user_city", placeholder="例如：上海、广州、成都")

        current_profile = {
            "gender": user_gender,
            "style": user_style,
            "body": user_body,
            "city": user_city,
        }
        if st.session_state.get("_last_saved_profile") != current_profile:
            user_service.save_profile(user_id, current_profile)
            st.session_state["_last_saved_profile"] = current_profile.copy()

        with st.expander("🛠️ 开发者模式 (调试信息)", expanded=False):
            st.text(f"Session ID: {st.session_state['session_id']}")

        st.markdown('<div class="cozy-divider"></div>', unsafe_allow_html=True)
        if st.sidebar.button("🔄 重置系统与服务", use_container_width=True):
            # 只清空应用状态，保留登录态（authenticated / user_id / username）
            for key in ("message", "session_id", "wardrobe_draft", "weekly_plan",
                        "vector_wardrobe", "rag", "editing_item_id"):
                st.session_state.pop(key, None)
            st.success("服务已重置，正在重新加载...")
            st.rerun()

        if st.sidebar.button("🗑️ 清空对话历史", use_container_width=True):
            from history import FileChatMessageHistory
            from config_data import CHAT_HISTORY_DIR

            FileChatMessageHistory(
                session_id=st.session_state["session_id"],
                storage_path=CHAT_HISTORY_DIR,
            ).clear()
            st.session_state["message"] = [{"role": "assistant", "content": "你好，有什么可以帮助你？"}]
            st.toast("对话历史已清空", icon="🗑️")
            time.sleep(0.3)
            st.rerun()

    tab_chat, tab_wardrobe = st.tabs(["💬 穿搭顾问", "👗 智能衣橱"])

    with tab_chat:
        wardrobe_service = WardrobeService(user_id=user_id, vector_wardrobe=st.session_state["vector_wardrobe"])
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
                with st.status("📅 小衣正在为您筹备一周穿搭...", expanded=True) as status:
                    user_profile = {
                        "gender": user_gender,
                        "style": user_style,
                        "body": user_body,
                        "city": user_city,
                    }
                    plan = st.session_state["rag"].generate_weekly_plan(
                        user_profile=user_profile,
                        current_date=datetime.datetime.now().strftime("%Y年%m月%d日"),
                        wardrobe_items=wardrobe_items,
                        status_container=status,
                    )
                    status.update(label="✅ 本周穿搭计划生成完毕！", state="complete", expanded=False)
                st.session_state["weekly_plan"] = plan

        weekly_plan = st.session_state.get("weekly_plan")
        if weekly_plan:
            # 动态推演未来7天日期
            today = datetime.datetime.now()
            weekdays_map = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
            tab_titles = []

            for i in range(7):
                target_date = today + datetime.timedelta(days=i)
                date_str = target_date.strftime("%m-%d")
                weekday_str = weekdays_map[target_date.weekday()]

                if i == 0:
                    tab_titles.append(f"今天 ({date_str})")
                elif i == 1:
                    tab_titles.append(f"明天 ({date_str})")
                else:
                    tab_titles.append(f"{weekday_str} ({date_str})")

            week_tabs = st.tabs(tab_titles)

            for day_tab, day_plan in zip(week_tabs, weekly_plan):
                with day_tab:
                    st.markdown(f"**场景感知：**{day_plan.get('scene', '')}")
                    st.markdown("**OOTD 灵感：**")
                    wardrobe_dict = {w_item.get('id'): w_item for w_item in wardrobe_items}
                    for item in day_plan.get("ootd", []):
                        if isinstance(item, str):
                            st.markdown(f"- {item}")
                        else:
                            desc = item.get("desc", "")
                            item_id = item.get("id", "")
                            if item_id and item_id in wardrobe_dict:
                                w_item = wardrobe_dict[item_id]
                                img_path = w_item.get("image_path")
                                if img_path and os.path.exists(img_path):
                                    img_b64 = get_image_base64(img_path)
                                    card_html = build_item_flex_card(w_item, img_b64)
                                    st.markdown(f"- {desc}<br>{card_html}", unsafe_allow_html=True)
                                else:
                                    st.markdown(f"- {desc}")
                            else:
                                st.markdown(f"- {desc}")
                    st.markdown(f"**小贴士：**{day_plan.get('tips', '')}")

        for message in st.session_state["message"]:
            if message["role"] == "assistant":
                with st.chat_message(message["role"]):
                    render_message(message["content"], wardrobe_items)
            else:
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
                with st.status("小衣正在为您精心搭配...", expanded=True) as status:
                    handler = HumanizedStatusHandler()
                    try:
                        # 格式化衣橱数据供 Agent 优先使用
                        if wardrobe_items:
                            wardrobe_lines = []
                            for item in wardrobe_items:
                                wardrobe_lines.append(
                                    f"- id:{item.get('id', '')} "
                                    f"{item.get('category', '')}/{item.get('sub_category', '')} "
                                    f"颜色:{item.get('color', '')} 材质:{item.get('material', '')} "
                                    f"适季:{item.get('season', '')}"
                                )
                            wardrobe_text = "\n".join(wardrobe_lines)
                        else:
                            wardrobe_text = "暂无已录入的单品（请先去「智能衣橱」拍照上传）"

                        response = st.session_state["rag"].invoke(
                            {
                                "input": final_prompt,
                                "gender": user_gender,
                                "style": user_style,
                                "body": user_body,
                                "city": user_city,
                                "wardrobe": wardrobe_text,
                                "current_date": datetime.datetime.now().strftime("%Y年%m月%d日"),
                            },
                            config={
                                "configurable": {"session_id": st.session_state["session_id"]},
                                "callbacks": [ConsoleLoggingHandler(), handler],
                            },
                        )
                        res = response
                        status.update(label="搭配完成！✨", state="complete", expanded=False)
                    except Exception:
                        res = FALLBACK_MESSAGE
                        status.update(label="⚠️ 小衣思考超时，请稍后再试", state="error", expanded=False)

                placeholder = st.empty()
                clean_res = re.sub(r"<item>.*?</item>", "", res)
                placeholder.write_stream(typewriter_stream([clean_res]))
                placeholder.empty()
                render_message(res, wardrobe_items)
            st.session_state["message"].append({"role": "assistant", "content": res})

    with tab_wardrobe:
        st.subheader("👗 智能衣橱")
        service = WardrobeService(user_id=user_id, vector_wardrobe=st.session_state["vector_wardrobe"])
        category_options = config.WARDROBE_CATEGORIES
        season_options = ["春", "夏", "秋", "冬"]

        tab_input1, tab_input2 = st.tabs(["📸 智能图片识别", "✍️ 手动录入单品"])

        # ===== Tab 1: 智能图片识别（原有逻辑） =====
        with tab_input1:
            uploaded_file = st.file_uploader(
                "上传衣服照片", type=["jpg", "jpeg", "png", "webp"], key="smart_upload"
            )
            if uploaded_file:
                st.image(uploaded_file, width=260)
                if st.button("🔍 智能识衣并入库"):
                    with st.spinner("正在识别衣物信息..."):
                        analysis = service.analyze_clothing_image(uploaded_file.getvalue())
                    draft_list = analysis if isinstance(analysis, list) else [analysis]
                    for item in draft_list:
                        item["uuid"] = uuid.uuid4().hex
                        item["inserted"] = False
                    st.session_state["wardrobe_draft"] = draft_list
                    st.session_state["wardrobe_draft_image"] = uploaded_file.getvalue()

            draft = st.session_state.get("wardrobe_draft")
            if draft:
                st.markdown("#### 识别结果（可手动调整）")
                draft_list = draft if isinstance(draft, list) else [draft]
                for idx, item in enumerate(draft_list):
                    if item.get("inserted"):
                        with st.expander(f"👗 识别单品 {idx+1}", expanded=False):
                            st.success("✅ 已入库")
                        continue

                    item_uuid = item["uuid"]
                    with st.expander(f"👗 识别单品 {idx+1}", expanded=True):
                        draft_category = item.get("category")
                        if draft_category in category_options:
                            category_index = category_options.index(draft_category)
                        else:
                            category_index = 0
                        category = st.selectbox(
                            "一级分类",
                            category_options,
                            index=category_index,
                            key=f"category_{item_uuid}",
                        )
                        sub_category = st.text_input(
                            "细分类别",
                            value=item.get("sub_category", ""),
                            key=f"sub_category_{item_uuid}",
                        )
                        color = st.text_input("颜色", value=item.get("color", ""), key=f"color_{item_uuid}")
                        material = st.text_input(
                            "材质",
                            value=item.get("material", ""),
                            key=f"material_{item_uuid}",
                        )
                        season_value = item.get("season", [])
                        if isinstance(season_value, str):
                            season_value = [season_value]
                        season_default = [s for s in season_value if s in season_options]
                        season = st.multiselect(
                            "适合季节",
                            season_options,
                            default=season_default,
                            key=f"season_{item_uuid}",
                        )

                        if st.button("✅ 确认加入衣橱", key=f"confirm_{item_uuid}"):
                            item_data = {
                                "category": category,
                                "sub_category": sub_category,
                                "color": color,
                                "material": material,
                                "season": season,
                            }
                            image_bytes = st.session_state.get("wardrobe_draft_image")
                            service.add_item(item_data, image_bytes=image_bytes)
                            item["inserted"] = True
                            st.success("已加入衣橱")
                            st.rerun()

        # ===== Tab 2: 手动录入表单 =====
        with tab_input2:
            with st.form("manual_add_form"):
                col1, col2 = st.columns(2)
                with col1:
                    category = st.selectbox("一级分类", category_options, key="manual_category")
                    color = st.text_input("颜色", placeholder="如：白色", key="manual_color")
                with col2:
                    sub_category = st.text_input("细分类别", placeholder="如：T恤、牛仔裤", key="manual_sub")
                    material = st.text_input("材质", placeholder="如：纯棉、羊毛", key="manual_material")
                season = st.multiselect("适合季节", season_options, key="manual_season")
                manual_image = st.file_uploader(
                    "📷 上传衣服照片（可选）",
                    type=["jpg", "jpeg", "png", "webp"],
                    key="manual_image",
                )
                submitted = st.form_submit_button("✅ 确认加入衣橱", use_container_width=True)

                if submitted:
                    if not category:
                        st.error("请至少选择一级分类")
                    else:
                        item_data = {
                            "category": category,
                            "sub_category": sub_category,
                            "color": color,
                            "material": material,
                            "season": season,
                        }
                        image_bytes = manual_image.getvalue() if manual_image else None
                        service.add_item(item_data, image_bytes=image_bytes)
                        st.toast("单品已成功加入衣橱！👗", icon="✅")
                        time.sleep(0.5)
                        st.rerun()

        # ===== 中央编辑状态 =====
        if "editing_item_id" not in st.session_state:
            st.session_state.editing_item_id = None

        # ===== 数据管理工具栏 =====
        items = service.get_all_items()

        with st.expander("💾 衣橱备份与数据管理", expanded=False):
            col_export, col_import = st.columns(2)

            with col_export:
                st.markdown("##### 📤 导出数据")
                if items:
                    csv_data = service.export_to_csv()
                    st.download_button(
                        label="📥 下载 CSV 文件",
                        data=csv_data,
                        file_name=f"wardrobe_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                        mime="text/csv",
                        use_container_width=True,
                    )
                    st.caption(f"共 {len(items)} 件单品")
                else:
                    st.caption("暂无数据可导出")

            with col_import:
                st.markdown("##### 📥 导入数据")
                with st.form("csv_upload_form", clear_on_submit=True):
                    import_mode = st.radio(
                        "导入模式",
                        ["追加到现有衣橱", "覆盖整个衣橱"],
                        horizontal=True,
                        key="import_mode",
                    )
                    uploaded_csv = st.file_uploader("上传 CSV 文件", type=["csv"], key="csv_upload")
                    submit_import = st.form_submit_button("⬆️ 确认导入数据", use_container_width=True)

                    if submit_import and uploaded_csv:
                        try:
                            csv_text = uploaded_csv.getvalue().decode("utf-8")
                            mode = "replace" if "覆盖" in import_mode else "append"
                            count = service.import_from_csv(csv_text, mode=mode)
                            st.toast(f"成功导入 {count} 件单品！👗", icon="✅")
                            time.sleep(0.5)
                            st.rerun()
                        except Exception as exc:
                            st.error(f"导入失败：{exc}")

        st.markdown("### 我的衣橱")
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
            category_order = ["外套", "内搭", "下装", "鞋履", "配饰"]

            # ===== 筛选区 =====
            unique_categories = sorted({it.get("category", "其他") for it in items})
            unique_colors = sorted({it.get("color", "") for it in items if it.get("color")})

            with st.expander("🔍 筛选衣橱单品", expanded=False):
                col_f1, col_f2 = st.columns(2)
                with col_f1:
                    filter_categories = st.multiselect(
                        "按类别筛选", options=unique_categories, key="filter_cat",
                    )
                with col_f2:
                    filter_colors = st.multiselect(
                        "按颜色筛选", options=unique_colors, key="filter_color",
                    )

            # 应用过滤
            filtered_items = items
            if filter_categories:
                filtered_items = [it for it in filtered_items if it.get("category") in filter_categories]
            if filter_colors:
                filtered_items = [it for it in filtered_items if it.get("color") in filter_colors]

            # Step 1: 按 category 分组
            grouped = {}
            for item in filtered_items:
                cat = item.get("category", "其他")
                grouped.setdefault(cat, []).append(item)

            def _render_item_detail(item, svc):
                """渲染单个单品的详情与编辑表单。全局唯一，不在循环内。"""
                item_id = item.get("id", "")
                prefix = f"edit_{item_id}"

                col_img, col_form = st.columns([1, 2])
                with col_img:
                    image_path = item.get("image_path")
                    if image_path and os.path.exists(image_path):
                        st.image(image_path, use_container_width=True)
                    else:
                        st.info("暂无照片")
                    new_image = st.file_uploader(
                        "📷 补充/更换照片", type=["jpg", "jpeg", "png", "webp"],
                        key=f"{prefix}_img_upload",
                    )

                with col_form:
                    category_options = config.WARDROBE_CATEGORIES
                    cur_cat = item.get("category", "")
                    cat_idx = category_options.index(cur_cat) if cur_cat in category_options else 0
                    new_category = st.selectbox(
                        "一级分类", category_options, index=cat_idx, key=f"{prefix}_cat"
                    )
                    new_sub = st.text_input(
                        "细分类别", value=item.get("sub_category", ""), key=f"{prefix}_sub"
                    )
                    new_color = st.text_input(
                        "颜色", value=item.get("color", ""), key=f"{prefix}_color"
                    )
                    new_material = st.text_input(
                        "材质", value=item.get("material", ""), key=f"{prefix}_mat"
                    )

                col_save, col_cancel = st.columns(2)
                with col_save:
                    if st.button("💾 保存修改", key=f"{prefix}_save", use_container_width=True):
                        update_data = {
                            "category": new_category,
                            "sub_category": new_sub,
                            "color": new_color,
                            "material": new_material,
                        }
                        if new_image is not None:
                            image_bytes = new_image.getvalue()
                            existing_path = item.get("image_path", "")
                            if existing_path and os.path.isdir(os.path.dirname(existing_path)):
                                save_path = existing_path
                            else:
                                save_path = os.path.join(svc.image_dir, f"{item_id}.jpg")
                            with open(save_path, "wb") as f:
                                f.write(image_bytes)
                            update_data["image_path"] = save_path
                        svc.update_item(item_id, update_data)
                        st.session_state.editing_item_id = None
                        st.toast("单品信息已更新！✨", icon="✅")
                        time.sleep(0.3)
                        st.rerun()
                with col_cancel:
                    if st.button("❌ 取消编辑", key=f"{prefix}_cancel", use_container_width=True):
                        st.session_state.editing_item_id = None
                        st.rerun()

                st.markdown("---")
                confirming = st.session_state.get("_confirming_delete") == item_id
                if confirming:
                    st.warning("⚠️ 确认删除？此操作不可撤销。")
                    c_confirm, c_cancel = st.columns(2)
                    with c_confirm:
                        if st.button("✅ 确认删除", key=f"{prefix}_del_confirm", use_container_width=True):
                            svc.delete_item(item_id)
                            st.session_state.editing_item_id = None
                            st.session_state._confirming_delete = None
                            st.toast("已删除！🗑️", icon="✅")
                            time.sleep(0.3)
                            st.rerun()
                    with c_cancel:
                        if st.button("❌ 取消", key=f"{prefix}_del_cancel", use_container_width=True):
                            st.session_state._confirming_delete = None
                            st.rerun()
                else:
                    if st.button("🗑️ 删除此单品", key=f"{prefix}_delete"):
                        st.session_state._confirming_delete = item_id
                        st.rerun()

            def render_category_grid(cat_items):
                """用 st.columns 渲染卡片网格，按钮与卡片同列对齐。"""
                COLS_PER_ROW = 5
                for row_start in range(0, len(cat_items), COLS_PER_ROW):
                    row_items = cat_items[row_start:row_start + COLS_PER_ROW]
                    cols = st.columns(COLS_PER_ROW)
                    for i, item in enumerate(row_items):
                        item_id = item.get("id", "")
                        icon = icon_map.get(item.get("category", ""), "👗")
                        image_path = item.get("image_path")
                        with cols[i]:
                            if image_path and os.path.exists(image_path):
                                img_b64 = get_image_base64(image_path)
                                st.markdown(build_wardrobe_card(item, img_b64, icon), unsafe_allow_html=True)
                            else:
                                st.markdown(build_wardrobe_card_placeholder(item, icon), unsafe_allow_html=True)
                            if st.button("✏️ 编辑", key=f"card_edit_{item_id}", use_container_width=True):
                                st.session_state.editing_item_id = item_id
                                st.rerun()

            # Step 2: 按类别分区，网格渲染
            for cat_name in category_order:
                cat_items = grouped.pop(cat_name, [])
                if not cat_items:
                    continue
                st.subheader(f"🏷️ {cat_name}")
                render_category_grid(cat_items)

            # 兜底：category_order 之外的分类
            for cat_name, cat_items in grouped.items():
                st.subheader(f"🏷️ {cat_name}")
                render_category_grid(cat_items)

            # ===== 中央详情/编辑表单（仅当选中某个单品时渲染，全局唯一） =====
            if st.session_state.editing_item_id is not None:
                edit_item = next((it for it in items if it.get("id") == st.session_state.editing_item_id), None)
                if edit_item:
                    st.markdown("---")
                    st.subheader("✏️ 编辑单品")
                    _render_item_detail(edit_item, service)
                else:
                    st.session_state.editing_item_id = None
                    st.rerun()


if __name__ == "__main__":
    # 仅独立运行时（streamlit run app_qa.py）才调用 set_page_config
    st.set_page_config(page_title="小衣 · AI智能穿搭顾问", page_icon="👗", layout="wide")
    render_page()
