"""
基于Streamlit完成WEB网页上传服务

pip install streamlit
"""

import streamlit as st
import time
from knowledge_base import KnowledgeBaseService


def render_page():
    """渲染知识库管理页面（上传 TXT 文件到知识库）。
    由 app_main.py 安全导入调用，也可独立运行。
    """
    # 添加网页标题
    st.title("知识库更新服务")

    # file_uploader
    uploader_file = st.file_uploader(
        label="请上传TXT文件",
        type=['txt'],
        accept_multiple_files=False,    # False表示仅接受一个文件的上传
    )

    # session_state就是一个字典
    if "service" not in st.session_state:
        st.session_state["service"] = KnowledgeBaseService()

    if "uploaded_file_id" not in st.session_state:
        st.session_state["uploaded_file_id"] = None

    if uploader_file is not None:
        # 提取文件的信息
        file_name = uploader_file.name
        file_type = uploader_file.type
        file_size = uploader_file.size / 1024   # KB
        current_file_id = id(uploader_file)

        st.subheader(f"文件名: {file_name}")
        st.write(f"格式: {file_type} | 大小: {file_size:.2f} KB")

        # get_value -> bytes -> decode
        raw = uploader_file.getvalue()
        used_encoding = None
        for enc in ("utf-8-sig", "utf-8", "gb18030", "gbk"):
            try:
                text = raw.decode(enc)
                used_encoding = enc
                break
            except UnicodeDecodeError:
                continue
        if used_encoding is None:
            text = raw.decode("utf-8", errors="replace")
            used_encoding = "utf-8 (replace)"

        st.caption(f"检测到编码: {used_encoding}")

        if st.session_state["uploaded_file_id"] != current_file_id:
            with st.spinner("载入知识库中..."):
                time.sleep(1)
                result = st.session_state["service"].upload_by_str(text, file_name)
                st.write(result)
                st.session_state["uploaded_file_id"] = current_file_id
        else:
            st.info("此文件已上传，无需重复处理")


if __name__ == "__main__":
    render_page()
