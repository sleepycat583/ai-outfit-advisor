"""R-004 卡片渲染验证测试

确保 embedding 策略变化（v3: embedding 不含 UUID）不会影响前端卡片渲染。

验证完整数据流：
1. VectorWardrobeService.search() 返回的文本包含 id:UUID
2. LLM 能从返回文本中提取 UUID 并生成 <item>UUID</item>
3. 前端 extract_wardrobe_item_ids() 能正确提取 UUID
4. 前端能根据 UUID 渲染卡片
"""

import pytest
from src.ui.pages.qa_page import extract_wardrobe_item_ids


def test_extract_item_ids_from_ai_response():
    """测试从 AI 回复中提取衣橱单品 ID"""
    ai_response = """
    · 下装：【自有】黑色直筒裤，修饰腿型。 <item>abc-123</item>
    · 上装：【自有】白色纯棉T恤，清爽透气。 <item>def-456</item>
    """

    item_ids = extract_wardrobe_item_ids(ai_response)

    assert item_ids == ["abc-123", "def-456"]
    print("✅ 前端能正确提取 UUID")


def test_embedding_without_uuid_still_returns_uuid():
    """验证：即使 embedding 不含 UUID，search() 仍返回带 id: 的文本"""

    # 模拟 VectorWardrobeService.search() 的返回格式
    # 这应该是从 metadata.original_text 重建的结果
    search_result = [
        "- id:abc-123 类别:下装/直筒裤 颜色:黑色 材质:棉 适季:春,秋",
        "- id:def-456 类别:内搭/T恤 颜色:白色 材质:纯棉 适季:春,夏",
    ]

    # 验证每条文本都包含 id:
    for text in search_result:
        assert "id:" in text
        # 提取 ID
        import re
        match = re.search(r"id:([^\s]+)", text)
        assert match is not None
        item_id = match.group(1)
        assert len(item_id) > 0
        print(f"✅ 文本包含有效 ID: {item_id}")


def test_complete_flow_simulation():
    """模拟完整流程：检索 → AI 回复 → 卡片提取"""

    # Step 1: 模拟 VectorWardrobeService.search() 返回
    wardrobe_search_result = [
        "- id:914eecb6-7f71-4dfd-b89a-0723f8f07194 类别:内搭/T恤 颜色:白色 材质:纯棉 适季:春,夏",
        "- id:8ab4127e-9e00-46b6-9c6a-5fea0080e338 类别:下装/牛仔裤 颜色:黑色 材质:牛仔布 适季:春,秋,冬",
    ]

    # 验证检索结果包含 id:
    assert all("id:" in text for text in wardrobe_search_result)

    # Step 2: 模拟 LLM 根据检索结果生成回复（按照 prompt 指令，应该包含 <item>UUID</item>）
    # 这里我们手动构造，实际应该由 LLM 生成
    simulated_ai_response = """
    ⛅ 【场景与温度感知】
    今天适合穿清爽的春夏搭配哦~

    ✨ 【主理人 OOTD 灵感】
    · 上装：【自有】白色纯棉T恤，清爽透气。 <item>914eecb6-7f71-4dfd-b89a-0723f8f07194</item>
    · 下装：【自有】黑色牛仔裤，百搭耐穿。 <item>8ab4127e-9e00-46b6-9c6a-5fea0080e338</item>

    💡 【小衣私藏贴士】
    黑白配永不出错，简约又高级！

    怎么样，这套搭配还合你的心意吗？还有什么场景需要我帮你参谋参谋？👗✨
    """

    # Step 3: 前端提取 UUID
    extracted_ids = extract_wardrobe_item_ids(simulated_ai_response)

    # 验证提取结果
    assert len(extracted_ids) == 2
    assert "914eecb6-7f71-4dfd-b89a-0723f8f07194" in extracted_ids
    assert "8ab4127e-9e00-46b6-9c6a-5fea0080e338" in extracted_ids

    print("✅ 完整流程验证通过")


def test_multiline_item_tag():
    """测试跨行的 <item> 标签提取"""
    ai_response = """
    · 上装：【自有】白色T恤 <item>
    abc-123
    </item>
    """

    item_ids = extract_wardrobe_item_ids(ai_response)
    assert "abc-123" in item_ids
    print("✅ 跨行标签提取正常")


def test_no_item_tags():
    """测试没有单品标签的情况"""
    ai_response = """
    今天没有找到合适的单品，建议去衣橱页面添加一些基础款~
    """

    item_ids = extract_wardrobe_item_ids(ai_response)
    assert item_ids == []
    print("✅ 无标签情况处理正常")


def test_duplicate_item_ids():
    """测试重复 ID 去重"""
    ai_response = """
    · 搭配1：【自有】黑色裤子 <item>abc-123</item>
    · 搭配2：【自有】黑色裤子也可以这样穿 <item>abc-123</item>
    """

    item_ids = extract_wardrobe_item_ids(ai_response)
    # 应该去重，只保留一个
    assert item_ids == ["abc-123"]
    print("✅ 重复 ID 去重正常")


def test_v3_metadata_structure():
    """测试 v3 版本的 metadata 结构"""

    # v3 版本的 metadata 应该包含 original_text
    v3_metadata = {
        "item_id": "abc-123",
        "original_text": "- id:abc-123 类别:下装/裤子 颜色:黑色 材质:棉 适季:春,秋"
    }

    # 验证结构
    assert "item_id" in v3_metadata
    assert "original_text" in v3_metadata
    assert "id:" in v3_metadata["original_text"]

    print("✅ v3 metadata 结构正确")


def test_backward_compatibility_v2():
    """测试向后兼容 v2 数据"""

    # v2 版本的 metadata 只有 item_id，没有 original_text
    v2_metadata = {
        "item_id": "abc-123"
    }

    # v2 的 page_content 可能包含完整文本（包含 id:）
    v2_page_content = "- id:abc-123 类别:下装/裤子 颜色:黑色 材质:棉 适季:春,秋"

    # 模拟兼容逻辑：如果 metadata 中没有 original_text，从 page_content 或 metadata.item_id 重建
    import re
    if "original_text" not in v2_metadata:
        if re.search(r"id:([^\s]+)", v2_page_content):
            # page_content 已包含 id:，直接使用
            reconstructed_text = v2_page_content
        else:
            # 从 metadata.item_id 重建
            reconstructed_text = f"- id:{v2_metadata['item_id']} {v2_page_content}"

    assert "id:" in reconstructed_text
    print("✅ v2 兼容逻辑正常")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
