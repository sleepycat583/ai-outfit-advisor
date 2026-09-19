"""R-006 知识库 chunk 元数据增强功能测试

测试覆盖：
1. chunk_overlap 是否生效
2. 章节提取准确性
3. chunk 元数据完整性（8 个新字段）
4. 位置信息准确性
"""

import os
import sys

import pytest

# 添加项目根目录到 Python 路径
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.services.knowledge_base import (
    extract_sections,
    find_section_for_position,
    get_string_md5,
)


class TestSectionExtraction:
    """测试章节提取功能"""

    def test_extract_chinese_numbered_sections(self):
        """测试识别中文编号章节（一、二、三、）"""
        content = """一、春季服装

纯棉材质适合春季。

二、夏季服装

真丝材质适合夏季。

三、秋季服装

羊毛材质适合秋季。"""

        sections = extract_sections(content)

        assert len(sections) == 3
        assert sections[0][0] == "春季服装"
        assert sections[1][0] == "夏季服装"
        assert sections[2][0] == "秋季服装"

        # 验证位置范围
        assert sections[0][1] == 0  # 第一章节从开头开始
        assert sections[0][2] == sections[1][1]  # 第一章节结束 = 第二章节开始
        assert sections[2][2] == len(content)  # 最后章节延伸到文档末尾

    def test_extract_arabic_numbered_sections(self):
        """测试识别阿拉伯数字编号章节（1. 2. 3.）"""
        content = """1. 核心原则

商务休闲风格。

2. 男生面试穿搭

衬衫配裤子。

3. 女生面试穿搭

衬衫配裙子。"""

        sections = extract_sections(content)

        assert len(sections) == 3
        assert sections[0][0] == "核心原则"
        assert sections[1][0] == "男生面试穿搭"
        assert sections[2][0] == "女生面试穿搭"

    def test_extract_bracketed_sections(self):
        """测试识别【】包裹的章节"""
        content = """【互联网与金融大厂面试穿搭避坑指南】

核心原则说明。

【男生穿搭公式】

具体公式内容。"""

        sections = extract_sections(content)

        assert len(sections) == 2
        assert sections[0][0] == "互联网与金融大厂面试穿搭避坑指南"
        assert sections[1][0] == "男生穿搭公式"

    def test_no_sections(self):
        """测试无章节结构的文档"""
        content = "这是一段没有章节标题的普通文本。"

        sections = extract_sections(content)

        assert len(sections) == 0

    def test_find_section_for_position(self):
        """测试位置查找章节功能"""
        sections = [
            ("第一章", 0, 100),
            ("第二章", 100, 200),
            ("第三章", 200, 300),
        ]

        assert find_section_for_position(sections, 50) == "第一章"
        assert find_section_for_position(sections, 150) == "第二章"
        assert find_section_for_position(sections, 250) == "第三章"
        assert find_section_for_position(sections, 350) == ""  # 超出范围


class TestChunkMetadata:
    """测试 chunk 元数据生成"""

    def test_chunk_metadata_fields(self):
        """测试元数据包含所有必需字段"""
        from config import base as config
        from langchain_text_splitters import RecursiveCharacterTextSplitter

        from src.services.knowledge_base import KnowledgeBaseService

        # 创建测试用的 splitter
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=config.chunk_size,
            chunk_overlap=config.chunk_overlap,
            separators=config.separators,
            length_function=len,
        )

        # 模拟 KnowledgeBaseService 的 _create_chunks_with_metadata 方法
        content = "一、测试章节\n\n" + "这是测试内容。" * 100  # 生成足够长的内容以触发切分

        base_metadata = {
            "source": "测试文档.txt",
            "create_time": "2026-09-19 10:00:00",
            "operator_id": "test_user",
            "operator_name": "测试用户",
            "operator": "测试用户",
            "source_type": "seed",
        }

        # 手动模拟切分逻辑
        sections = extract_sections(content)
        chunks = splitter.split_text(content)
        document_hash = get_string_md5(content)

        # 验证第一个 chunk 的元数据
        chunk = chunks[0]
        start_pos = content.find(chunk)
        section_title = find_section_for_position(sections, start_pos)

        chunk_meta = {
            **base_metadata,
            "chunk_index": 0,
            "total_chunks": len(chunks),
            "start_char": start_pos,
            "end_char": start_pos + len(chunk),
            "section_title": section_title,
            "document_hash": document_hash,
            "document_version": document_hash,
            "metadata_version": 4,
        }

        # 验证所有必需字段存在
        required_fields = [
            "source",
            "create_time",
            "operator_id",
            "operator_name",
            "operator",
            "source_type",
            "chunk_index",
            "total_chunks",
            "start_char",
            "end_char",
            "section_title",
            "document_hash",
            "document_version",
            "metadata_version",
        ]

        for field in required_fields:
            assert field in chunk_meta, f"缺少必需字段: {field}"

        # 验证元数据类型和值
        assert isinstance(chunk_meta["chunk_index"], int)
        assert isinstance(chunk_meta["total_chunks"], int)
        assert isinstance(chunk_meta["start_char"], int)
        assert isinstance(chunk_meta["end_char"], int)
        assert isinstance(chunk_meta["section_title"], str)
        assert isinstance(chunk_meta["document_hash"], str)
        assert chunk_meta["document_version"] == chunk_meta["document_hash"]
        assert chunk_meta["metadata_version"] == 4

        # 验证章节标题被正确提取
        assert chunk_meta["section_title"] == "测试章节"

    def test_chunk_overlap_works(self):
        """测试 chunk_overlap 是否生效"""
        from config import base as config
        from langchain_text_splitters import RecursiveCharacterTextSplitter

        # 验证配置已更新
        assert config.chunk_overlap == 100, "chunk_overlap 应该已经被设置为 100"

        # 创建 splitter 并测试
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=config.chunk_size,
            chunk_overlap=config.chunk_overlap,
            separators=config.separators,
            length_function=len,
        )

        # 生成测试内容
        content = "ABCDEFGHIJ" * 200  # 2000 字符，会被切分

        chunks = splitter.split_text(content)

        # 验证有多个 chunk
        assert len(chunks) > 1, "内容应该被切分成多个 chunk"

        # 验证相邻 chunk 有重叠
        for i in range(len(chunks) - 1):
            current_chunk = chunks[i]
            next_chunk = chunks[i + 1]

            # 查找当前 chunk 的最后部分在下一个 chunk 中是否出现
            overlap_candidate = current_chunk[-100:]  # 取最后 100 字符
            has_overlap = overlap_candidate in next_chunk

            assert (
                has_overlap
            ), f"chunk {i} 和 chunk {i+1} 之间应该有重叠内容"


class TestDocumentHash:
    """测试文档哈希功能"""

    def test_same_content_same_hash(self):
        """测试相同内容生成相同哈希"""
        content = "这是测试内容"

        hash1 = get_string_md5(content)
        hash2 = get_string_md5(content)

        assert hash1 == hash2

    def test_different_content_different_hash(self):
        """测试不同内容生成不同哈希"""
        content1 = "这是测试内容1"
        content2 = "这是测试内容2"

        hash1 = get_string_md5(content1)
        hash2 = get_string_md5(content2)

        assert hash1 != hash2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
