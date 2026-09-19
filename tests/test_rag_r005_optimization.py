"""R-005 知识库检索优化测试

测试动态 k 值、相似度过滤和证据不足判断功能。
"""

import pytest
from types import SimpleNamespace

from src.core.rag_agent import (
    RagService,
    estimate_knowledge_k,
    get_vector_distance_metric,
    normalize_vector_distance,
)


class TestDynamicKEstimation:
    """测试动态 k 值估算逻辑"""

    def test_specific_operation_queries(self):
        """具体操作问题应返回 k=2"""
        assert estimate_knowledge_k("羊毛衫怎么洗") == 2
        assert estimate_knowledge_k("如何保养皮鞋") == 2
        assert estimate_knowledge_k("尺码偏小怎么选") == 2
        assert estimate_knowledge_k("衣服缩水怎么办") == 2

    def test_matching_queries(self):
        """搭配类问题应返回 k=4"""
        assert estimate_knowledge_k("黑色和米色怎么搭配") == 4
        assert estimate_knowledge_k("衬衫和裤子如何组合") == 4
        assert estimate_knowledge_k("上衣怎么配裤子") == 4  # 具体搭配问题

    def test_broad_concept_queries(self):
        """宽泛概念问题应返回 k=5"""
        assert estimate_knowledge_k("面试穿搭注意事项") == 5
        assert estimate_knowledge_k("如何提升穿搭品味") == 5
        assert estimate_knowledge_k("穿搭禁忌有哪些") == 5
        assert estimate_knowledge_k("配色原则") == 5

    def test_default_queries(self):
        """默认问题应返回 k=3"""
        assert estimate_knowledge_k("一般问题") == 3
        assert estimate_knowledge_k("今天穿什么") == 3
        assert estimate_knowledge_k("推荐穿搭") == 3


class TestConfigurationValues:
    """测试配置值是否正确"""

    def test_config_values(self):
        """验证新配置项存在且值合理"""
        from config import base as config

        assert hasattr(config, 'knowledge_retrieval_k')
        assert hasattr(config, 'knowledge_min_similarity')
        assert hasattr(config, 'enable_knowledge_dynamic_k')
        assert hasattr(config, 'enable_knowledge_similarity_filter')

        assert isinstance(config.knowledge_retrieval_k, int)
        assert 2 <= config.knowledge_retrieval_k <= 10
        assert 0.0 <= config.knowledge_min_similarity <= 1.0
        assert 0.0 <= config.knowledge_strong_similarity <= 1.0


class TestKnowledgeEvidence:
    """使用 fake Chroma 结果验证真实过滤和证据分层。"""

    def setup_method(self):
        from config import base as config

        self.config = config
        self.original_filter = config.enable_knowledge_similarity_filter
        self.service = RagService.__new__(RagService)

    def teardown_method(self):
        self.config.enable_knowledge_similarity_filter = self.original_filter

    def test_l2_distance_is_normalized(self):
        assert normalize_vector_distance(0.8, "l2") == 0.6
        assert normalize_vector_distance(0.2, "cosine") == 0.8

    def test_unknown_metric_is_rejected(self):
        vector_store = SimpleNamespace(
            _collection=SimpleNamespace(configuration={"hnsw": {"space": "unknown"}})
        )
        assert get_vector_distance_metric(vector_store) == "unknown"
        try:
            normalize_vector_distance(0.2, "unknown")
        except ValueError:
            pass
        else:
            raise AssertionError("未知距离类型必须拒绝静默计算")

    def test_no_evidence_and_limited_evidence(self):
        doc = SimpleNamespace(page_content="面试应保持简洁", metadata={"source": "interview.txt"})
        self.service.vector_service = SimpleNamespace(
            vector_store=SimpleNamespace(
                _collection=SimpleNamespace(configuration={"hnsw": {"space": "l2"}})
            )
        )
        self.config.enable_knowledge_similarity_filter = True
        empty = self.service._classify_knowledge_results(2, [(doc, 1.2)])
        assert empty.status == "no_evidence"
        limited = self.service._classify_knowledge_results(2, [(doc, 0.9)])
        assert limited.status == "limited"

    def test_multiple_sources_can_be_sufficient(self):
        docs = [
            (SimpleNamespace(page_content="面试上装建议", metadata={"source": "interview.txt"}), 0.7),
            (SimpleNamespace(page_content="面试下装建议", metadata={"source": "interview.txt"}), 0.8),
            (SimpleNamespace(page_content="颜色建议", metadata={"source": "color.txt"}), 0.9),
        ]
        self.service.vector_service = SimpleNamespace(
            vector_store=SimpleNamespace(
                _collection=SimpleNamespace(configuration={"hnsw": {"space": "l2"}})
            )
        )
        result = self.service._classify_knowledge_results(5, docs)
        assert result.status == "sufficient"
        assert len(result.documents) == 2

    def test_single_strong_source_is_sufficient(self):
        doc = SimpleNamespace(page_content="羊毛大衣必须干洗", metadata={"source": "care.txt"})
        self.service.vector_service = SimpleNamespace(
            vector_store=SimpleNamespace(
                _collection=SimpleNamespace(configuration={"hnsw": {"space": "l2"}})
            )
        )
        result = self.service._classify_knowledge_results(2, [(doc, 0.7)])
        assert result.status == "sufficient"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
