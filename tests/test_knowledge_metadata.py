"""R-006: 知识库元数据扩展单元测试"""

import pytest
from src.services.knowledge_base import (
    extract_sections,
    find_section_for_position,
    get_string_md5,
)


def test_extract_sections_basic():
    """测试基础章节提取"""
    content = """一、第一章
内容1
二、第二章
内容2
三、第三章
内容3"""

    sections = extract_sections(content)
    assert len(sections) == 3
    assert sections[0][0] == "第一章"
    assert sections[1][0] == "第二章"
    assert sections[2][0] == "第三章"


def test_extract_sections_with_brackets():
    """测试带【】的章节提取"""
    content = """【互联网与金融大厂面试穿搭避坑指南】
一、 核心原则：Smart Casual（商务休闲风）
内容"""

    sections = extract_sections(content)
    assert len(sections) >= 1
    assert "互联网与金融大厂面试穿搭避坑指南" in sections[0][0]


def test_extract_sections_empty():
    """测试空文档"""
    sections = extract_sections("")
    assert sections == []


def test_find_section_for_position():
    """测试根据位置查找章节"""
    sections = [
        ("章节1", 0, 100),
        ("章节2", 100, 200),
        ("章节3", 200, 300),
    ]

    assert find_section_for_position(sections, 50) == "章节1"
    assert find_section_for_position(sections, 150) == "章节2"
    assert find_section_for_position(sections, 250) == "章节3"
    assert find_section_for_position(sections, 350) == ""


def test_find_section_empty():
    """测试空章节列表"""
    assert find_section_for_position([], 100) == ""


def test_get_string_md5():
    """测试 MD5 哈希生成"""
    text1 = "测试文本"
    text2 = "测试文本"
    text3 = "不同文本"

    hash1 = get_string_md5(text1)
    hash2 = get_string_md5(text2)
    hash3 = get_string_md5(text3)

    assert hash1 == hash2  # 相同内容生成相同哈希
    assert hash1 != hash3  # 不同内容生成不同哈希
    assert len(hash1) == 32  # MD5 哈希长度


def test_metadata_version_constant():
    """验证元数据版本号已升级到 3"""
    from src.services.knowledge_base import METADATA_VERSION

    assert METADATA_VERSION == 4


def test_chunk_overlap_config():
    """验证 chunk_overlap 配置已更新"""
    from config import base as config

    assert config.chunk_overlap == 100
    assert config.chunk_size == 800
