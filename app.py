"""AI 穿搭顾问 - Streamlit 主入口

提供用户登录、问答聊天和知识库管理功能。
"""

import streamlit as st
from src.services.user import UserService
from src.ui.pages import qa_page, knowledge_base_page


def main():
    """主函数：处理用户登录和页面路由"""

    # 页面配置
    st.set_page_config(
        page_title="AI 穿搭顾问",
        page_icon="👔",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    # 初始化 session_state
    if "user_id" not in st.session_state:
        st.session_state["user_id"] = ""
    if "username" not in st.session_state:
        st.session_state["username"] = ""
    if "page" not in st.session_state:
        st.session_state["page"] = "问答聊天"

    # 侧边栏：用户登录/注册
    with st.sidebar:
        st.title("👔 AI 穿搭顾问")

        if not st.session_state.get("user_id"):
            # 未登录状态
            st.subheader("🔐 用户登录")

            tab1, tab2 = st.tabs(["登录", "注册"])

            with tab1:
                login_username = st.text_input("用户名", key="login_username")
                login_password = st.text_input("密码", type="password", key="login_password")

                if st.button("登录", use_container_width=True):
                    if login_username and login_password:
                        user_service = UserService()
                        result = user_service.login(login_username, login_password)

                        if result["success"]:
                            st.session_state["user_id"] = result["user_id"]
                            st.session_state["username"] = login_username
                            st.success(f"欢迎回来，{login_username}！")
                            st.rerun()
                        else:
                            st.error(result["message"])
                    else:
                        st.warning("请输入用户名和密码")

            with tab2:
                reg_username = st.text_input("用户名", key="reg_username")
                reg_password = st.text_input("密码", type="password", key="reg_password")
                reg_password_confirm = st.text_input("确认密码", type="password", key="reg_password_confirm")

                if st.button("注册", use_container_width=True):
                    if reg_username and reg_password and reg_password_confirm:
                        if reg_password != reg_password_confirm:
                            st.error("两次密码输入不一致")
                        else:
                            user_service = UserService()
                            result = user_service.register(reg_username, reg_password)

                            if result["success"]:
                                st.success("注册成功！请登录")
                            else:
                                st.error(result["message"])
                    else:
                        st.warning("请填写完整信息")

        else:
            # 已登录状态
            st.success(f"👤 {st.session_state['username']}")

            if st.button("退出登录", use_container_width=True):
                st.session_state["user_id"] = ""
                st.session_state["username"] = ""
                st.session_state["page"] = "问答聊天"
                st.rerun()

            st.divider()

            # 页面导航
            st.subheader("📑 功能菜单")

            if st.button("💬 问答聊天", use_container_width=True):
                st.session_state["page"] = "问答聊天"
                st.rerun()

            if st.button("📚 知识库管理", use_container_width=True):
                st.session_state["page"] = "知识库管理"
                st.rerun()

    # 主内容区：根据登录状态和选择的页面渲染内容
    if not st.session_state.get("user_id"):
        # 未登录时显示欢迎页面
        st.title("👔 欢迎使用 AI 穿搭顾问")
        st.markdown("""
        ### 功能特点

        - 💬 **智能问答**：基于 RAG 的穿搭建议，结合天气、场景和个人衣橱
        - 👔 **衣橱管理**：管理你的衣物，智能推荐搭配方案
        - 📚 **知识库**：上传时尚资讯，让 AI 学习你的风格偏好
        - 🌤️ **天气感知**：根据实时天气推荐合适的穿搭

        请在左侧登录或注册开始使用！
        """)
    else:
        # 已登录时根据选择渲染对应页面
        current_page = st.session_state.get("page", "问答聊天")

        if current_page == "问答聊天":
            qa_page.render_page()
        elif current_page == "知识库管理":
            knowledge_base_page.render_page()


if __name__ == "__main__":
    main()
