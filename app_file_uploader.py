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
    st.title("知识库更新服务")

    # session_state 初始化
    if "service" not in st.session_state:
        user_id = st.session_state.get("user_id", "")
        st.session_state["service"] = KnowledgeBaseService(user_id=user_id)

    if "uploaded_file_id" not in st.session_state:
        st.session_state["uploaded_file_id"] = None

    if "pasted_text_id" not in st.session_state:
        st.session_state["pasted_text_id"] = None

    if "kb_stats" not in st.session_state:
        st.session_state["kb_stats"] = None

    service = st.session_state["service"]

    # ============================================================
    #  方式一：文件上传
    # ============================================================
    st.subheader("📁 上传 TXT 文件")
    uploader_file = st.file_uploader(
        label="选择本地 TXT 文件",
        type=['txt'],
        accept_multiple_files=False,
    )

    if uploader_file is not None:
        file_name = uploader_file.name
        file_type = uploader_file.type
        file_size = uploader_file.size / 1024
        current_file_id = id(uploader_file)

        st.write(f"格式: {file_type} | 大小: {file_size:.2f} KB")

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
                result = service.upload_by_str(text, file_name)
                st.write(result)
                st.session_state["uploaded_file_id"] = current_file_id
        else:
            st.info("此文件已上传，无需重复处理")

    st.divider()

    # ============================================================
    #  方式二：直接粘贴文本
    # ============================================================
    st.subheader("✏️ 粘贴文本入库")
    st.caption("无需准备文件，直接粘贴穿搭知识文本即可导入")

    with st.form("paste_form", clear_on_submit=True):
        paste_source = st.text_input(
            "知识标题",
            placeholder="例如：男士西装穿搭指南、羊毛护理方法...",
            key="paste_source",
        )
        paste_content = st.text_area(
            "粘贴文本内容",
            placeholder="将穿搭知识文本粘贴到这里...",
            height=200,
            key="paste_content",
        )
        submitted = st.form_submit_button("📥 导入知识库", use_container_width=True)

        if submitted:
            if not paste_content.strip():
                st.error("请粘贴文本内容")
            elif not paste_source.strip():
                st.error("请输入知识标题")
            else:
                current_paste_id = hash(paste_content)
                if st.session_state["pasted_text_id"] == current_paste_id:
                    st.info("此内容已导入，无需重复处理")
                else:
                    with st.spinner("载入知识库中..."):
                        result = service.upload_by_str(
                            paste_content.strip(), paste_source.strip()
                        )
                        st.write(result)
                        st.session_state["pasted_text_id"] = current_paste_id

    st.divider()

    # ============================================================
    #  知识库总览面板
    # ============================================================
    st.subheader("📊 知识库总览")

    stats = service.get_stats()

    col1, col2, col3 = st.columns(3)
    col1.metric("知识来源", f"{stats['total_sources']} 份")
    col2.metric("文本段", f"{stats['total_chunks']} 段")
    latest = stats["sources"][0]["create_time"] if stats["sources"] else "暂无"
    col3.metric("最近更新", latest)

    if stats["total_sources"] == 0:
        st.info("知识库为空。上传文件或粘贴文本开始积累知识吧。")
    else:
        if "del_confirm" not in st.session_state:
            st.session_state["del_confirm"] = None

        for item in stats["sources"]:
            source = item["source"]
            chunks = item["chunks"]
            ctime = item["create_time"]
            operator = item["operator"]

            col_left, col_right = st.columns([5, 1])
            with col_left:
                st.markdown(f"**{source}**")
                st.caption(f"{chunks} 段 · {ctime} · {operator}")
                if st.session_state["del_confirm"] == source:
                    st.warning("⚠️ 确认删除？不可撤销")
            with col_right:
                if st.session_state["del_confirm"] == source:
                    col_btn1, col_btn2 = st.columns(2)
                    with col_btn1:
                        if st.button("✅", key=f"confirm_{hash(source)}", help="确认删除"):
                            deleted = service.delete_by_source(source)
                            st.session_state["del_confirm"] = None
                            st.toast(f"已删除 {source}（{deleted} 段）", icon="🗑️")
                            time.sleep(0.3)
                            st.rerun()
                    with col_btn2:
                        if st.button("❌", key=f"cancel_{hash(source)}", help="取消"):
                            st.session_state["del_confirm"] = None
                            st.rerun()
                else:
                    if st.button("🗑️", key=f"del_{hash(source)}", help=f"删除「{source}」"):
                        st.session_state["del_confirm"] = source
                        st.rerun()

        st.divider()

        with st.expander("⚠️ 危险操作", expanded=False):
            st.warning("清空知识库将删除所有已导入的知识，包括种子数据。此操作不可撤销。")

            if "clear_confirm" not in st.session_state:
                st.session_state["clear_confirm"] = False

            if st.button("⚠️ 清空整个知识库...", key="clear_trigger", use_container_width=True):
                st.session_state["clear_confirm"] = True
                st.rerun()

            if st.session_state.get("clear_confirm"):
                col_yes, col_no = st.columns(2)
                with col_yes:
                    if st.button("✅ 确认清空", use_container_width=True):
                        deleted = service.clear_all()
                        st.session_state["clear_confirm"] = False
                        st.toast(f"已清空知识库（共 {deleted} 段）", icon="🗑️")
                        time.sleep(0.3)
                        st.rerun()
                with col_no:
                    if st.button("❌ 取消", use_container_width=True):
                        st.session_state["clear_confirm"] = False
                        st.rerun()


if __name__ == "__main__":
    st.set_page_config(page_title="小衣 · 知识库管理", page_icon="📚", layout="wide")
    render_page()
