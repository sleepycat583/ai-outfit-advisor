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
        .auth-container {
            background: #161b22;
            box-shadow: 0 8px 32px rgba(0,0,0,0.3);
        }
        .auth-title { color: #e6edf3; }
        .auth-subtitle { color: #8b949e; }
    }
    </style>
    """, unsafe_allow_html=True)

    st.markdown('<div class="auth-container">', unsafe_allow_html=True)
    st.markdown('<div class="auth-title">🧵 小衣 · AI穿搭顾问</div>', unsafe_allow_html=True)
    st.markdown('<div class="auth-subtitle">你的私人穿搭主理人</div>', unsafe_allow_html=True)

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

app_choice = st.sidebar.radio(
    "选择功能",
    ["📚 知识库管理", "💬 穿搭问答"],
    help="选择你要使用的功能"
)

if st.sidebar.button("🚪 退出登录", use_container_width=True):
    st.session_state.clear()
    st.rerun()

if app_choice == "📚 知识库管理":
    app_file_uploader.render_page()
else:
    app_qa.render_page()
