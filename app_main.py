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

# 主导航
st.sidebar.title("🧵 应用导航")
st.sidebar.write(f"👤 {st.session_state['username']}")

if "active_page" not in st.session_state:
    st.session_state["active_page"] = "qa"

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

if st.sidebar.button("🚪 退出登录", use_container_width=True):
    st.session_state.clear()
    st.rerun()

if st.session_state["active_page"] == "kb":
    app_file_uploader.render_page()
else:
    app_qa.render_page()
