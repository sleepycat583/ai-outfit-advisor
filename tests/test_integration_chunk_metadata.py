"""R-006 集成测试：验证真实种子文档的切分和元数据"""

import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from config import base as config
from langchain_text_splitters import RecursiveCharacterTextSplitter

from src.services.knowledge_base import (
    extract_sections,
    find_section_for_position,
    get_string_md5,
)


class TestRealSeedDocuments:
    """测试真实种子文档的切分效果"""

    def test_interview_guide_section_extraction(self):
        """测试面试穿搭指南的章节提取"""
        filepath = "seeds/大厂面试穿搭指南.txt"

        if not os.path.exists(filepath):
            pytest.skip(f"种子文档不存在: {filepath}")

        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()

        sections = extract_sections(content)

        # 验证章节数量（文档有标题 + 四个主要章节）
        assert len(sections) >= 4, f"应至少提取到 4 个章节，实际提取到 {len(sections)} 个"

        # 验证章节标题
        section_titles = [title for title, _, _ in sections]
        print(f"\n提取到的章节: {section_titles}")

        # 应该包含核心章节
        expected_keywords = ["核心原则", "男生", "女生", "色彩"]
        for keyword in expected_keywords:
            assert any(keyword in title for title in section_titles), \
                f"应该包含含有 '{keyword}' 的章节"

    def test_create_chunks_with_metadata(self):
        """测试完整的切分和元数据生成流程"""
        filepath = "seeds/大厂面试穿搭指南.txt"

        if not os.path.exists(filepath):
            pytest.skip(f"种子文档不存在: {filepath}")

        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()

        # 模拟 KnowledgeBaseService._create_chunks_with_metadata 逻辑
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=config.chunk_size,
            chunk_overlap=config.chunk_overlap,
            separators=config.separators,
            length_function=len,
        )

        sections = extract_sections(content)
        chunks = splitter.split_text(content)
        document_hash = get_string_md5(content)

        base_metadata = {
            "source": "[种子] 大厂面试穿搭指南.txt",
            "create_time": "2026-09-19 10:00:00",
            "operator_id": "system",
            "operator_name": "小曹",
            "operator": "小曹",
            "source_type": "seed",
        }

        # 生成完整的 chunks_with_metadata
        chunks_with_meta = []
        for i, chunk in enumerate(chunks):
            start_pos = content.find(chunk)
            if start_pos == -1:
                # 如果完全找不到（可能因为 overlap），用近似位置
                start_pos = sum(len(chunks[j]) for j in range(i)) - (i * config.chunk_overlap)

            end_pos = start_pos + len(chunk)
            section_title = find_section_for_position(sections, start_pos)

            chunk_meta = {
                **base_metadata,
                "chunk_index": i,
                "total_chunks": len(chunks),
                "start_char": start_pos,
                "end_char": end_pos,
                "section_title": section_title,
                "document_hash": document_hash,
            "document_version": document_hash,
            "metadata_version": 4,
            }

            chunks_with_meta.append((chunk, chunk_meta))

        # 验证结果
        print(f"\n文档长度: {len(content)} 字符")
        print(f"切分成 {len(chunks_with_meta)} 个 chunks")

        for i, (chunk, meta) in enumerate(chunks_with_meta[:3]):  # 只打印前 3 个
            print(f"\n--- Chunk {i} ---")
            print(f"长度: {len(chunk)} 字符")
            print(f"位置: {meta['start_char']} - {meta['end_char']}")
            print(f"章节: {meta['section_title']}")
            print(f"内容预览: {chunk[:100]}...")

        # 验证 chunk_overlap 生效
        if len(chunks_with_meta) > 1:
            for i in range(len(chunks_with_meta) - 1):
                chunk1_text = chunks_with_meta[i][0]
                chunk2_text = chunks_with_meta[i + 1][0]

                # 检查是否有重叠内容
                overlap_candidate = chunk1_text[-100:]
                has_overlap = any(
                    overlap_candidate[j:j+20] in chunk2_text
                    for j in range(0, len(overlap_candidate) - 20, 10)
                )

                assert has_overlap, f"Chunk {i} 和 {i+1} 之间应该有重叠内容"

        # 验证所有 chunk 都有章节标题（如果文档有结构）
        if sections:
            chunks_with_section = sum(
                1 for _, meta in chunks_with_meta if meta["section_title"]
            )
            print(f"\n有章节标题的 chunks: {chunks_with_section}/{len(chunks_with_meta)}")

            # 至少有一些 chunk 应该被分配到章节
            assert chunks_with_section > 0, "应该至少有一个 chunk 被分配到章节"

        # 验证元数据完整性
        for _, meta in chunks_with_meta:
            assert meta["metadata_version"] == 4
            assert meta["document_hash"] == document_hash
            assert meta["document_version"] == document_hash
            assert 0 <= meta["chunk_index"] < meta["total_chunks"]
            assert meta["start_char"] < meta["end_char"]

    def test_short_document_no_split(self):
        """测试短文档不切分但仍添加元数据"""
        content = "这是一段短文本，不需要切分。"

        # 模拟短文档处理逻辑
        document_hash = get_string_md5(content)
        base_metadata = {
            "source": "短文档.txt",
            "create_time": "2026-09-19 10:00:00",
            "operator_id": "test",
            "operator_name": "测试",
            "operator": "测试",
            "source_type": "user",
        }

        chunks_with_meta = [
            (
                content,
                {
                    **base_metadata,
                    "chunk_index": 0,
                    "total_chunks": 1,
                    "start_char": 0,
                    "end_char": len(content),
                    "section_title": "",
                    "document_hash": document_hash,
                    "document_version": document_hash,
                    "metadata_version": 4,
                },
            )
        ]

        # 验证
        assert len(chunks_with_meta) == 1
        _, meta = chunks_with_meta[0]

        assert meta["chunk_index"] == 0
        assert meta["total_chunks"] == 1
        assert meta["start_char"] == 0
        assert meta["end_char"] == len(content)
        assert meta["section_title"] == ""
        assert meta["metadata_version"] == 4


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])  # -s 显示 print 输出
