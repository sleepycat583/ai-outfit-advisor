"""衣橱检索与卡片渲染契约的回归测试。

这些测试只验证本地格式处理，不访问 Supabase、Chroma 或大模型服务。
"""

from src.core.rag_agent import RagService
from src.services.vector_store import WARDROBE_COLLECTION_NAME, WARDROBE_ITEM_ID_PATTERN
from src.ui.pages.qa_page import extract_wardrobe_item_ids


def test_wardrobe_collection_uses_new_format_version():
    """旧索引不能复用，格式升级必须使用新的 collection 名称。"""
    assert WARDROBE_COLLECTION_NAME == "wardrobe_items_v3"


def test_vector_document_contract_requires_item_id():
    """标准检索文档应包含 id，旧的描述-only 文档应不匹配。"""
    assert WARDROBE_ITEM_ID_PATTERN.search("- id:abc-123 类别:外套/夹克")
    assert not WARDROBE_ITEM_ID_PATTERN.search("类别:外套 | 颜色:灰色 | 季节:春,夏,秋")


def test_rag_formatter_discards_legacy_documents():
    """RAG 层不能把没有真实 ID 的旧结果继续交给模型。"""
    service = object.__new__(RagService)
    result = service._format_wardrobe_for_llm(
        [
            "类别:外套 | 颜色:灰色 | 季节:春,夏,秋",
            "- id:abc-123 类别:外套/夹克 颜色:灰色 材质:棉 适季:春,秋",
        ]
    )
    assert result == "- id:abc-123 类别:外套/夹克 颜色:灰色 材质:棉 适季:春,秋"


def test_item_tags_support_whitespace_newlines_and_deduplicate():
    """模型偶尔会换行或重复引用单品，前端应稳定提取并去重。"""
    text = """上装 <item> abc-123 </item>\n下装 <item>\nabc-456\n</item>\n鞋履 <item>abc-123</item>"""
    assert extract_wardrobe_item_ids(text) == ["abc-123", "abc-456"]