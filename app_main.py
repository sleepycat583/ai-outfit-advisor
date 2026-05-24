"""
AI 穿搭顾问 - 综合应用
"""

import streamlit as st

# [安全修复] 移除 exec() 任意代码执行漏洞，改用安全的模块导入
import app_qa
import app_file_uploader

# 设置页面配置
st.set_page_config(
    page_title="小衣 · AI智能穿搭顾问",
    page_icon="👗",
    layout="wide"
)

# 主导航
st.sidebar.title("🧵 应用导航")
app_choice = st.sidebar.radio(
    "选择功能",
    ["📚 知识库管理", "💬 穿搭问答"],
    help="选择你要使用的功能"
)

if app_choice == "📚 知识库管理":
    # [安全修复] 不再使用 inline 代码或 exec()，改为调用独立的模块函数
    app_file_uploader.render_page()
else:
    # [安全修复] 不再使用 exec() 执行任意代码，改为安全的函数调用
    app_qa.render_page()
