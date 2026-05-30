"""
AI 穿搭顾问 - 综合应用
"""

import streamlit as st
from user_service import UserService

# 设置页面配置 - 必须放在最前面
st.set_page_config(
    page_title="小衣 · AI智能穿搭顾问",
    page_icon="👗",
    layout="wide"
)

# --- 初始化认证状态 ---
if "authenticated" not in st.session_state:
    st.session_state["authenticated"] = False
if "user_id" not in st.session_state:
    st.session_state["user_id"] = None
if "username" not in st.session_state:
    st.session_state["username"] = None

# --- 未登录：渲染登录/注册页面 ---
if not st.session_state["authenticated"]:
    user_service = UserService()

    st.markdown("""
    <style>
    /* ===== 页面背景：与问答界面一致的暖米色 ===== */
    [data-testid="stAppViewContainer"] {
        background: #FBF9F6;
    }
    .auth-container {
        max-width: 420px;
        margin: 8vh auto 0;
        padding: 2.5rem 2rem;
        background: #FFFFFF;
        border-radius: 20px;
        box-shadow: 0 8px 32px rgba(0,0,0,0.08);
        text-align: center;
    }
    .auth-title {
        font-size: 1.8rem;
        font-weight: 700;
        color: #333;
        margin-bottom: 0.3rem;
    }
    .auth-subtitle {
        font-size: 0.9rem;
        color: #999;
        margin-bottom: 1.8rem;
    }
    @media (prefers-color-scheme: dark) {
        [data-testid="stAppViewContainer"] {
            background: #0d1117;
        }
        .auth-container {
            background: #161b22;
            box-shadow: 0 8px 32px rgba(0,0,0,0.3);
        }
        .auth-title { color: #e6edf3; }
        .auth-subtitle { color: #8b949e; }
    }
    </style>

    <div class="auth-container">
    <div class="auth-title">🧵 小衣 · AI穿搭顾问</div>
    <div class="auth-subtitle">你的私人穿搭主理人</div>
    """, unsafe_allow_html=True)

    tab_login, tab_register = st.tabs(["登录", "注册"])

    with tab_login:
        with st.form("login_form"):
            login_username = st.text_input("用户名", key="login_username")
            login_password = st.text_input("密码", type="password", key="login_password")
            submitted = st.form_submit_button("登 录", use_container_width=True)

            if submitted:
                success, result = user_service.login(login_username, login_password)
                if success:
                    st.session_state["authenticated"] = True
                    st.session_state["user_id"] = result
                    st.session_state["username"] = login_username
                    st.rerun()
                else:
                    st.error(result)

    with tab_register:
        with st.form("register_form"):
            reg_username = st.text_input("用户名", key="reg_username")
            reg_password = st.text_input("密码", type="password", key="reg_password")
            reg_password2 = st.text_input("确认密码", type="password", key="reg_password2")
            submitted = st.form_submit_button("注 册", use_container_width=True)

            if submitted:
                if reg_password != reg_password2:
                    st.error("两次输入的密码不一致")
                else:
                    success, result = user_service.register(reg_username, reg_password)
                    if success:
                        st.session_state["authenticated"] = True
                        st.session_state["user_id"] = result
                        st.session_state["username"] = reg_username
                        st.rerun()
                    else:
                        st.error(result)

    st.markdown('</div>', unsafe_allow_html=True)
    st.stop()

# --- 已登录：主应用 ---
import app_qa
import app_file_uploader
import time

# --- 初始化用户档案状态（所有页面共享）---
user_id = st.session_state["user_id"]
user_service = UserService()

if "user_gender" not in st.session_state:
    saved_profile = user_service.get_profile(user_id)
    st.session_state["user_gender"] = saved_profile.get("gender", "女生")
    st.session_state["user_style"] = saved_profile.get("style", "日常休闲")
    st.session_state["user_body"] = saved_profile.get("body", "")
    st.session_state["user_city"] = saved_profile.get("city", "")
    st.session_state["_last_saved_profile"] = saved_profile.copy()

if "active_page" not in st.session_state:
    st.session_state["active_page"] = "qa"

# ===== 共享侧边栏（所有页面均可见）=====
st.sidebar.title("🧵 应用导航")
st.sidebar.write(f"👤 {st.session_state['username']}")

col1, col2 = st.sidebar.columns(2)
with col1:
    if st.button("💬 穿搭问答", use_container_width=True,
                 type="primary" if st.session_state["active_page"] == "qa" else "secondary"):
        st.session_state["active_page"] = "qa"
        st.rerun()
with col2:
    if st.button("📚 知识库", use_container_width=True,
                 type="primary" if st.session_state["active_page"] == "kb" else "secondary"):
        st.session_state["active_page"] = "kb"
        st.rerun()

st.sidebar.divider()

# 穿搭档案（所有页面可见）
with st.sidebar:
    st.header("👤 我的穿搭档案")

    gender_options = ["女生", "男生"]
    gender_labels = {"女生": "👩 女生", "男生": "👨 男生"}
    user_gender = st.selectbox(
        "选择你的性别", gender_options, key="user_gender",
        format_func=lambda v: gender_labels.get(v, v),
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
        "偏好的穿搭风格", style_options, key="user_style",
        format_func=lambda v: style_labels.get(v, v),
    )
    user_body = st.text_input(
        "📏 输入你的身高/体重 (选填)", key="user_body",
        placeholder="例如：165cm / 50kg",
    )
    user_city = st.text_input(
        "📍 所在城市", key="user_city",
        placeholder="例如：上海、广州、成都",
    )

    # 自动保存档案变更
    current_profile = {
        "gender": st.session_state["user_gender"],
        "style": st.session_state["user_style"],
        "body": st.session_state["user_body"],
        "city": st.session_state["user_city"],
    }
    if st.session_state.get("_last_saved_profile") != current_profile:
        user_service.save_profile(user_id, current_profile)
        st.session_state["_last_saved_profile"] = current_profile.copy()

    with st.expander("🛠️ 开发者模式 (调试信息)", expanded=False):
        st.text(f"User ID: {user_id}")
        if "session_id" in st.session_state:
            st.text(f"Session ID: {st.session_state['session_id']}")

    st.markdown('<div class="cozy-divider"></div>', unsafe_allow_html=True)

    if st.sidebar.button("🔄 重置系统与服务", use_container_width=True):
        # 只清空应用状态，保留登录态
        for key in ("message", "session_id", "wardrobe_draft", "weekly_plan",
                    "vector_wardrobe", "rag", "editing_item_id"):
            st.session_state.pop(key, None)
        st.success("服务已重置，正在重新加载...")
        st.rerun()

    if st.sidebar.button("🗑️ 清空对话历史", use_container_width=True):
        from history import FileChatMessageHistory

        sid = st.session_state.get("session_id", f"chat_session_{user_id}")
        FileChatMessageHistory(session_id=sid).clear()
        st.session_state["message"] = [{"role": "assistant", "content": "你好，有什么可以帮助你？"}]
        st.toast("对话历史已清空", icon="🗑️")
        time.sleep(0.3)
        st.rerun()

st.sidebar.divider()

if st.sidebar.button("🚪 退出登录", use_container_width=True):
    st.session_state.clear()
    st.rerun()

# ===== 从 Supabase 恢复聊天记录（如存在）=====
if "message" not in st.session_state:
    from history import FileChatMessageHistory

    session_id = f"chat_session_{user_id}"
    try:
        history = FileChatMessageHistory(session_id=session_id)
        past_messages = history.messages
        if past_messages:
            ui_messages = []
            for msg in past_messages:
                role = "user" if msg.type == "human" else "assistant"
                ui_messages.append({"role": role, "content": msg.content})
            st.session_state["message"] = ui_messages
        else:
            st.session_state["message"] = [{"role": "assistant", "content": "你好，有什么可以帮助你？"}]
    except Exception:
        st.session_state["message"] = [{"role": "assistant", "content": "你好，有什么可以帮助你？"}]

# ===== 页面路由 =====
if st.session_state["active_page"] == "kb":
    app_file_uploader.render_page()
else:
    app_qa.render_page()
