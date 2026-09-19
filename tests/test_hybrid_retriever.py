"""混合检索器单元测试"""

import pytest
from unittest.mock import Mock, MagicMock, patch
from src.services.hybrid_wardrobe_retriever import HybridWardrobeRetriever
from src.services.query_parser import WardrobeQuery


@pytest.fixture
def mock_vector_service():
    """Mock 向量检索服务"""
    service = Mock()
    service.search = Mock(return_value=[
        "- id:item-1 类别:下装/裤子 颜色:黑色 材质:棉 适季:春,秋",
        "- id:item-2 类别:下装/直筒裤 颜色:黑色 材质:牛仔布 适季:春,秋,冬",
        "- id:item-3 类别:内搭/T恤 颜色:白色 材质:纯棉 适季:春,夏",
    ])
    return service


@pytest.fixture
def mock_supabase():
    """Mock Supabase 客户端"""
    mock_client = MagicMock()

    # 模拟结构化过滤结果
    mock_table = MagicMock()
    mock_select = MagicMock()
    mock_eq = MagicMock()
    mock_in = MagicMock()
    mock_execute = MagicMock()

    mock_client.table.return_value = mock_table
    mock_table.select.return_value = mock_select
    mock_select.eq.return_value = mock_eq
    mock_eq.in_.return_value = mock_in

    # 默认返回一些候选 ID
    mock_execute.data = [
        {"id": "item-1"},
        {"id": "item-2"},
    ]
    mock_in.execute.return_value = mock_execute
    mock_eq.execute.return_value = mock_execute

    return mock_client


def test_pure_semantic_search_without_filters(mock_vector_service, mock_supabase):
    """测试无结构化条件时的纯语义检索"""
    with patch('src.services.hybrid_wardrobe_retriever.get_supabase_client', return_value=mock_supabase):
        retriever = HybridWardrobeRetriever(
            user_id="test-user",
            vector_service=mock_vector_service,
            enable_structural_filter=True
        )

        # 查询不包含结构化条件
        results = retriever.search("有什么推荐", k=5)

        # 应该调用纯语义检索
        mock_vector_service.search.assert_called_once_with("有什么推荐", k=5)
        assert len(results) == 3


def test_hybrid_search_with_color_filter(mock_vector_service, mock_supabase):
    """测试包含颜色过滤的混合检索"""
    with patch('src.services.hybrid_wardrobe_retriever.get_supabase_client', return_value=mock_supabase):
        retriever = HybridWardrobeRetriever(
            user_id="test-user",
            vector_service=mock_vector_service,
            enable_structural_filter=True
        )

        # 查询包含颜色
        results = retriever.search("黑色裤子", k=5)

        # 应该调用 Supabase 结构化过滤
        mock_supabase.table.assert_called_with("wardrobe_items")

        # 应该调用语义排序
        mock_vector_service.search.assert_called()


def test_fallback_when_structural_filter_empty(mock_vector_service, mock_supabase):
    """测试结构化过滤为空时的回退"""
    # 模拟结构化过滤返回空结果
    mock_execute = MagicMock()
    mock_execute.data = []
    mock_supabase.table().select().eq().execute.return_value = mock_execute

    with patch('src.services.hybrid_wardrobe_retriever.get_supabase_client', return_value=mock_supabase):
        retriever = HybridWardrobeRetriever(
            user_id="test-user",
            vector_service=mock_vector_service,
            enable_structural_filter=True
        )

        results = retriever.search("紫色上衣", k=5)

        # 应该回退到纯语义检索
        mock_vector_service.search.assert_called_with("紫色上衣", k=5)


def test_direct_return_when_candidates_less_than_k(mock_vector_service, mock_supabase):
    """测试候选数 ≤ k 时直接返回"""
    # 模拟只有 3 个候选
    mock_execute = MagicMock()
    mock_execute.data = [
        {"id": "item-1", "category": "下装", "sub_category": "裤子",
         "color": "黑色", "material": "棉", "season": ["春", "秋"]},
        {"id": "item-2", "category": "下装", "sub_category": "直筒裤",
         "color": "黑色", "material": "牛仔布", "season": ["春", "秋", "冬"]},
    ]

    mock_query_builder = MagicMock()
    mock_query_builder.execute.return_value = mock_execute
    mock_supabase.table().select().eq.return_value = mock_query_builder

    with patch('src.services.hybrid_wardrobe_retriever.get_supabase_client', return_value=mock_supabase):
        retriever = HybridWardrobeRetriever(
            user_id="test-user",
            vector_service=mock_vector_service,
            enable_structural_filter=True
        )

        # k=5 但只有 2 个候选
        results = retriever.search("黑色裤子", k=5)

        # 应该直接返回，不调用语义排序
        # （但会调用 _get_texts_by_ids，它会再次查询 Supabase）


def test_disable_structural_filter(mock_vector_service, mock_supabase):
    """测试关闭结构化过滤开关"""
    with patch('src.services.hybrid_wardrobe_retriever.get_supabase_client', return_value=mock_supabase):
        retriever = HybridWardrobeRetriever(
            user_id="test-user",
            vector_service=mock_vector_service,
            enable_structural_filter=False  # 关闭
        )

        results = retriever.search("黑色裤子", k=5)

        # 即使有结构化条件，也应该使用纯语义检索
        mock_vector_service.search.assert_called_once()


def test_row_to_text_format():
    """测试 Supabase 行转文本格式"""
    with patch('src.services.hybrid_wardrobe_retriever.get_supabase_client'):
        retriever = HybridWardrobeRetriever(
            user_id="test-user",
            vector_service=Mock(),
            enable_structural_filter=True
        )

        row = {
            "id": "test-id",
            "category": "下装",
            "sub_category": "裤子",
            "color": "黑色",
            "material": "棉",
            "season": ["春", "秋"]
        }

        text = retriever._row_to_text(row)

        assert "id:test-id" in text
        assert "类别:下装/裤子" in text
        assert "颜色:黑色" in text
        assert "材质:棉" in text
        assert "适季:春,秋" in text


def test_season_string_format():
    """测试季节字段为字符串格式的兼容性"""
    with patch('src.services.hybrid_wardrobe_retriever.get_supabase_client'):
        retriever = HybridWardrobeRetriever(
            user_id="test-user",
            vector_service=Mock(),
            enable_structural_filter=True
        )

        row = {
            "id": "test-id",
            "category": "下装",
            "sub_category": "裤子",
            "color": "黑色",
            "material": "棉",
            "season": "春,秋"  # 字符串格式
        }

        text = retriever._row_to_text(row)

        assert "适季:春,秋" in text


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
