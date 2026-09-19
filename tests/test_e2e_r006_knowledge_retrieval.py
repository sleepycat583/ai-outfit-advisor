"""R-006 端到端集成测试：知识库检索展示新元数据"""

import pytest
from unittest.mock import Mock, patch
from src.core.rag_agent import RagService
from langchain_core.documents import Document


class TestKnowledgeRetrievalWithMetadata:
    """测试知识检索结果包含章节和位置信息"""

    @pytest.fixture
    def mock_documents(self):
        """模拟带有新元数据的检索结果"""
        return [
            (
                Document(
                    page_content="羊毛衫需要手洗，不可机洗。水温不超过30度。",
                    metadata={
                        "source": "[种子] 洗涤养护指南.txt",
                        "section_title": "羊毛制品洗涤",
                        "chunk_index": 2,
                        "total_chunks": 5,
                        "start_char": 450,
                        "end_char": 890,
                        "document_hash": "abc123",
                        "metadata_version": 3,
                    },
                ),
                0.82,
            ),
            (
                Document(
                    page_content="面试时避免穿运动鞋和T恤，建议商务休闲风。",
                    metadata={
                        "source": "[种子] 面试穿搭指南.txt",
                        "section_title": "穿搭禁忌",
                        "chunk_index": 0,
                        "total_chunks": 3,
                        "start_char": 0,
                        "end_char": 420,
                        "document_hash": "def456",
                        "metadata_version": 3,
                    },
                ),
                0.75,
            ),
        ]

    def test_format_knowledge_chunk_with_full_metadata(self, mock_documents):
        """测试完整元数据的格式化"""
        agent = RagService(user_id="test_user")
        doc, similarity = mock_documents[0]

        result = agent._format_knowledge_chunk(doc, similarity)

        assert "来源: [种子] 洗涤养护指南.txt" in result
        assert "章节: 羊毛制品洗涤" in result
        assert "片段: 3/5" in result  # chunk_index 从 0 开始，total_chunks 是总数
        assert "羊毛衫需要手洗" in result

    def test_format_knowledge_chunk_without_section(self, mock_documents):
        """测试缺失章节信息时的格式化"""
        agent = RagService(user_id="test_user")
        doc = Document(
            page_content="测试内容",
            metadata={
                "source": "测试文档.txt",
                "chunk_index": 0,
                "total_chunks": 1,
            },
        )

        result = agent._format_knowledge_chunk(doc, 0.90)

        assert "来源: 测试文档.txt" in result
        assert "章节:" not in result  # 没有章节时不显示
        assert "片段: 1/1" in result
        assert "测试内容" in result

    def test_format_knowledge_chunk_legacy_metadata(self):
        """测试旧版元数据（无新字段）的兼容性"""
        agent = RagService(user_id="test_user")
        doc = Document(
            page_content="旧版知识内容",
            metadata={
                "source": "旧文档.txt",
                "create_time": "2026-01-01",
                "metadata_version": 2,
            },
        )

        result = agent._format_knowledge_chunk(doc, 0.85)

        assert "来源: 旧文档.txt" in result
        assert "章节:" not in result
        assert "片段:" not in result
        assert "旧版知识内容" in result

    @patch("src.core.rag_agent.RagService._classify_knowledge_results")
    def test_knowledge_search_formats_multiple_chunks(
        self, mock_classify, mock_documents
    ):
        """测试多个 chunk 的检索结果格式化"""
        from src.core.rag_agent import KnowledgeRetrievalResult

        agent = RagService(user_id="test_user")

        # 模拟 vector_service.vector_store.similarity_search_with_score
        with patch.object(
            agent.vector_service.vector_store,
            "similarity_search_with_score",
            return_value=[
                (mock_documents[0][0], 0.15),  # L2 距离
                (mock_documents[1][0], 0.22),
            ],
        ):
            # 模拟分类结果为"sufficient"
            mock_classify.return_value = KnowledgeRetrievalResult(
                status="sufficient",
                documents=mock_documents,
                top_similarity=0.82,
                requested_k=2,
            )

            result = agent._knowledge_base_search("羊毛衫怎么洗")

            # 验证结果包含两个 chunk 的格式化输出
            assert "来源: [种子] 洗涤养护指南.txt" in result
            assert "章节: 羊毛制品洗涤" in result
            assert "片段: 3/5" in result

            assert "来源: [种子] 面试穿搭指南.txt" in result
            assert "章节: 穿搭禁忌" in result
            assert "片段: 1/3" in result

            # 验证分隔符
            assert "\n\n---\n\n" in result

    def test_chunk_index_display_is_one_based(self):
        """验证 chunk 索引展示为从 1 开始"""
        agent = RagService(user_id="test_user")
        doc = Document(
            page_content="内容",
            metadata={
                "source": "文档.txt",
                "chunk_index": 0,  # 内部索引从 0 开始
                "total_chunks": 2,  # 内部总数也从 0 开始计
            },
        )

        result = agent._format_knowledge_chunk(doc, 0.90)

        # 显示应该是 1/2（索引从 0 开始，总数直接使用 metadata）
        assert "片段: 1/2" in result
