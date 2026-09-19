"""查询解析器单元测试"""

import pytest
from src.services.query_parser import QueryParser, WardrobeQuery


def test_simple_color_and_category():
    """测试简单的颜色+类别查询"""
    parser = QueryParser()
    result = parser.parse("黑色裤子")

    assert result.raw_query == "黑色裤子"
    assert "黑色" in result.colors
    assert "下装" in result.categories
    assert result.has_structural_filters()


def test_complex_query_with_scene():
    """测试复杂查询：颜色+类别+场景"""
    parser = QueryParser()
    result = parser.parse("适合面试的黑色外套")

    assert "黑色" in result.colors
    assert "外套" in result.categories
    assert "面试" in result.scenes
    assert result.style == "正式"
    assert result.has_structural_filters()


def test_season_extraction():
    """测试季节提取"""
    parser = QueryParser()
    result = parser.parse("春季外套")

    assert "外套" in result.categories
    assert "春" in result.seasons
    assert result.has_structural_filters()


def test_sub_category_matching():
    """测试子类别匹配"""
    parser = QueryParser()
    result = parser.parse("牛仔裤")

    assert "下装" in result.categories
    assert "裤子" in result.sub_categories
    assert result.has_structural_filters()


def test_multiple_colors():
    """测试多颜色识别"""
    parser = QueryParser()
    result = parser.parse("黑白配色的衬衫")

    assert "黑色" in result.colors
    assert "白色" in result.colors
    assert "内搭" in result.categories


def test_fuzzy_color_matching():
    """测试模糊颜色匹配"""
    parser = QueryParser()

    # "黑" 应该匹配到 "黑色"
    result1 = parser.parse("黑裤子")
    assert "黑色" in result1.colors

    # "深蓝" 应该匹配到 "蓝色"
    result2 = parser.parse("深蓝色外套")
    assert "蓝色" in result2.colors


def test_material_extraction():
    """测试材质提取"""
    parser = QueryParser()
    result = parser.parse("纯棉T恤")

    assert "纯棉" in result.materials or "棉" in result.materials
    assert "内搭" in result.categories


def test_style_inference():
    """测试风格推断"""
    parser = QueryParser()

    # 正式风格
    result1 = parser.parse("商务西装")
    assert result1.style == "正式"

    # 休闲风格
    result2 = parser.parse("休闲裤子")
    assert result2.style == "休闲"

    # 运动风格
    result3 = parser.parse("运动鞋")
    assert result3.style == "运动"


def test_empty_query():
    """测试空查询"""
    parser = QueryParser()
    result = parser.parse("")

    assert result.raw_query == ""
    assert not result.has_structural_filters()


def test_no_structural_filters():
    """测试无结构化条件的查询"""
    parser = QueryParser()
    result = parser.parse("有什么推荐")

    assert not result.has_structural_filters()


def test_synonym_matching():
    """测试同义词匹配"""
    parser = QueryParser()

    # "大衣" 应该匹配到 "外套"
    result1 = parser.parse("大衣")
    assert "外套" in result1.categories

    # "长裤" 应该匹配到 "裤子"
    result2 = parser.parse("长裤")
    assert "裤子" in result2.sub_categories


def test_multiple_categories():
    """测试多类别识别（罕见但可能）"""
    parser = QueryParser()
    result = parser.parse("外套和裤子")

    assert "外套" in result.categories
    assert "下装" in result.categories


def test_real_world_queries():
    """测试真实世界查询场景"""
    parser = QueryParser()

    # 场景1: 具体需求
    result1 = parser.parse("显瘦的黑色直筒裤")
    assert "黑色" in result1.colors
    assert "下装" in result1.categories
    assert "裤子" in result1.sub_categories

    # 场景2: 场景驱动
    result2 = parser.parse("约会穿的裙子")
    assert "下装" in result2.categories
    assert "裙子" in result2.sub_categories
    assert "约会" in result2.scenes
    assert result2.style == "社交"

    # 场景3: 季节需求
    result3 = parser.parse("夏天穿的白T恤")
    assert "夏" in result3.seasons
    assert "白色" in result3.colors
    assert "内搭" in result3.categories
    assert "T恤" in result3.sub_categories


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
