"""RAG 服务混合检索集成测试"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from src.core.rag_agent import RagService


@pytest.fixture
def mock_vector_wardrobe():
    """Mock 向量衣橱服务"""
    service = Mock()
    service.search = Mock(return_value=[
        "- id:item-1 类别:下装/裤子 颜色:黑色 材质:棉 适季:春,秋",
        "- id:item-2 类别:下装/直筒裤 颜色:黑色 材质:牛仔布 适季:春,秋,冬",
    ])
    return service


@pytest.fixture
def mock_hybrid_retriever():
    """Mock 混合检索器"""
    retriever = Mock()
    retriever.search = Mock(return_value=[
        "- id:item-1 类别:下装/裤子 颜色:黑色 材质:棉 适季:春,秋",
        "- id:item-2 类别:下装/直筒裤 颜色:黑色 材质:牛仔布 适季:春,秋,冬",
    ])
    return retriever


@patch('src.core.rag_agent.VectorStoreService')
@patch('src.core.rag_agent.ChatTongyi')
@patch('src.core.rag_agent.WeatherService')
@patch('src.core.rag_agent.get_supabase_client')
def test_hybrid_retriever_enabled_by_default(
    mock_supabase, mock_weather_cls, mock_chat_cls, mock_vector_store_cls,
    mock_vector_wardrobe
):
    """测试混合检索器默认启用"""
    with patch('src.services.hybrid_wardrobe_retriever.HybridWardrobeRetriever') as MockHybridRetriever:
        mock_hybrid = Mock()
        MockHybridRetriever.return_value = mock_hybrid

        service = RagService(
            vector_wardrobe=mock_vector_wardrobe,
            user_id="test-user",
            enable_hybrid_retrieval=True
        )

        # 应该创建混合检索器
        MockHybridRetriever.assert_called_once_with(
            user_id="test-user",
            vector_service=mock_vector_wardrobe,
            enable_structural_filter=True
        )
        assert service.hybrid_retriever == mock_hybrid


@patch('src.core.rag_agent.VectorStoreService')
@patch('src.core.rag_agent.ChatTongyi')
@patch('src.core.rag_agent.WeatherService')
@patch('src.core.rag_agent.get_supabase_client')
def test_hybrid_retriever_disabled(
    mock_supabase, mock_weather_cls, mock_chat_cls, mock_vector_store_cls,
    mock_vector_wardrobe
):
    """测试禁用混合检索器"""
    service = RagService(
        vector_wardrobe=mock_vector_wardrobe,
        user_id="test-user",
        enable_hybrid_retrieval=False
    )

    # 不应该创建混合检索器
    assert service.hybrid_retriever is None


@patch('src.core.rag_agent.VectorStoreService')
@patch('src.core.rag_agent.ChatTongyi')
@patch('src.core.rag_agent.WeatherService')
@patch('src.core.rag_agent.get_supabase_client')
def test_wardrobe_search_uses_hybrid_retriever(
    mock_supabase, mock_weather_cls, mock_chat_cls, mock_vector_store_cls,
    mock_vector_wardrobe, mock_hybrid_retriever
):
    """测试 _wardrobe_search 使用混合检索器"""
    service = RagService(
        vector_wardrobe=mock_vector_wardrobe,
        user_id="test-user",
        enable_hybrid_retrieval=True
    )
    service.hybrid_retriever = mock_hybrid_retriever

    result = service._wardrobe_search("黑色裤子")

    # 应该调用混合检索器
    mock_hybrid_retriever.search.assert_called_once()
    # 不应该调用原始向量服务
    mock_vector_wardrobe.search.assert_not_called()

    assert "id:item-1" in result
    assert "id:item-2" in result


@patch('src.core.rag_agent.VectorStoreService')
@patch('src.core.rag_agent.ChatTongyi')
@patch('src.core.rag_agent.WeatherService')
@patch('src.core.rag_agent.get_supabase_client')
def test_wardrobe_search_fallback_to_vector_service(
    mock_supabase, mock_weather_cls, mock_chat_cls, mock_vector_store_cls,
    mock_vector_wardrobe
):
    """测试混合检索器不可用时回退到纯语义检索"""
    service = RagService(
        vector_wardrobe=mock_vector_wardrobe,
        user_id="test-user",
        enable_hybrid_retrieval=True
    )
    service.hybrid_retriever = None  # 模拟初始化失败

    result = service._wardrobe_search("黑色裤子")

    # 应该回退到原始向量服务
    mock_vector_wardrobe.search.assert_called_once()

    assert "id:item-1" in result


@patch('src.core.rag_agent.VectorStoreService')
@patch('src.core.rag_agent.ChatTongyi')
@patch('src.core.rag_agent.WeatherService')
@patch('src.core.rag_agent.get_supabase_client')
def test_wardrobe_search_empty_result(
    mock_supabase, mock_weather_cls, mock_chat_cls, mock_vector_store_cls,
    mock_vector_wardrobe, mock_hybrid_retriever
):
    """测试混合检索器返回空结果"""
    mock_hybrid_retriever.search = Mock(return_value=[])

    service = RagService(
        vector_wardrobe=mock_vector_wardrobe,
        user_id="test-user",
        enable_hybrid_retrieval=True
    )
    service.hybrid_retriever = mock_hybrid_retriever

    result = service._wardrobe_search("紫色裙子")

    assert "暂无相关单品" in result


@patch('src.core.rag_agent.VectorStoreService')
@patch('src.core.rag_agent.ChatTongyi')
@patch('src.core.rag_agent.WeatherService')
@patch('src.core.rag_agent.get_supabase_client')
def test_wardrobe_search_with_dynamic_topk(
    mock_supabase, mock_weather_cls, mock_chat_cls, mock_vector_store_cls,
    mock_vector_wardrobe, mock_hybrid_retriever
):
    """测试动态 Top-K 估算"""
    service = RagService(
        vector_wardrobe=mock_vector_wardrobe,
        user_id="test-user",
        enable_hybrid_retrieval=True
    )
    service.hybrid_retriever = mock_hybrid_retriever

    # 简单查询（≤5字）
    service._wardrobe_search("裤子")
    mock_hybrid_retriever.search.assert_called_with("裤子", k=5)

    # 中等查询（4字，仍然是简单查询）
    service._wardrobe_search("黑色外套")
    mock_hybrid_retriever.search.assert_called_with("黑色外套", k=5)

    # 复杂查询（场景类，10字以上）
    service._wardrobe_search("适合面试的正式穿搭")
    mock_hybrid_retriever.search.assert_called_with("适合面试的正式穿搭", k=12)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
