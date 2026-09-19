"""查询解析器：从自然语言查询中提取结构化条件。

用于将用户的自然语言查询（如"黑色裤子"）解析为结构化条件：
- 类别：["下装"]
- 子类别：["裤子"]
- 颜色：["黑色", "黑"]
- 季节：[]
"""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class WardrobeQuery:
    """衣橱查询条件"""

    raw_query: str  # 原始查询
    categories: list[str] = field(default_factory=list)  # 类别: ["外套", "下装"]
    sub_categories: list[str] = field(default_factory=list)  # 子类别: ["裤子", "牛仔裤"]
    colors: list[str] = field(default_factory=list)  # 颜色: ["黑色", "黑"]
    seasons: list[str] = field(default_factory=list)  # 季节: ["春", "秋"]
    materials: list[str] = field(default_factory=list)  # 材质: ["棉", "牛仔"]
    scenes: list[str] = field(default_factory=list)  # 场景: ["面试", "通勤"]
    style: Optional[str] = None  # 风格: "正式", "休闲"

    def has_structural_filters(self) -> bool:
        """是否包含结构化过滤条件"""
        return bool(
            self.categories or self.sub_categories or
            self.colors or self.seasons or self.materials
        )


class QueryParser:
    """查询解析器：从自然语言中提取结构化条件

    业务规则：
    - 支持中文同义词匹配（如"裤子"、"长裤"、"牛仔裤"都映射到"裤子"）
    - 颜色支持模糊匹配（如"黑"匹配"黑色"）
    - 季节提取（春/夏/秋/冬及其同义词）
    - 场景识别（面试、约会、通勤等）
    """

    # 类别关键词映射（支持同义词）
    CATEGORY_KEYWORDS = {
        "外套": ["外套", "大衣", "夹克", "风衣", "西装", "西服", "外搭"],
        "内搭": ["内搭", "上衣", "T恤", "衬衫", "毛衣", "卫衣", "针织衫", "内衣"],
        "下装": ["下装", "裤子", "裙子", "短裤", "长裤", "裤"],
        "鞋履": ["鞋", "鞋子", "靴子", "运动鞋", "皮鞋", "高跟鞋", "鞋履"],
        "配饰": ["配饰", "包", "帽子", "围巾", "腰带", "首饰", "饰品"],
    }

    # 子类别关键词
    SUB_CATEGORY_KEYWORDS = {
        "裤子": ["裤子", "长裤", "九分裤", "牛仔裤", "直筒裤", "阔腿裤", "西裤", "休闲裤"],
        "裙子": ["裙子", "半身裙", "连衣裙", "短裙", "长裙", "A字裙", "百褶裙"],
        "T恤": ["T恤", "短袖", "圆领T恤", "V领T恤", "t恤"],
        "衬衫": ["衬衫", "衬衣", "白衬衫", "长袖衬衫"],
        "牛仔夹克": ["牛仔夹克", "牛仔外套"],
        "西装": ["西装", "西服", "正装"],
    }

    # 颜色关键词（支持模糊匹配）
    COLOR_KEYWORDS = {
        "黑色": ["黑", "黑色"],
        "白色": ["白", "白色"],
        "蓝色": ["蓝", "蓝色", "深蓝", "浅蓝", "藏青", "宝蓝"],
        "红色": ["红", "红色", "酒红", "枣红", "朱红"],
        "灰色": ["灰", "灰色", "深灰", "浅灰", "炭灰"],
        "米色": ["米", "米色", "卡其", "驼色", "杏色"],
        "绿色": ["绿", "绿色", "军绿", "墨绿", "深绿"],
        "黄色": ["黄", "黄色", "姜黄", "土黄"],
        "棕色": ["棕", "棕色", "咖啡色", "焦糖色"],
        "粉色": ["粉", "粉色", "粉红", "淡粉"],
        "紫色": ["紫", "紫色", "深紫", "浅紫"],
    }

    # 季节关键词
    SEASON_KEYWORDS = {
        "春": ["春", "春季", "春天", "早春", "初春"],
        "夏": ["夏", "夏季", "夏天", "盛夏", "炎夏"],
        "秋": ["秋", "秋季", "秋天", "初秋", "深秋"],
        "冬": ["冬", "冬季", "冬天", "寒冬", "严冬"],
    }

    # 材质关键词
    MATERIAL_KEYWORDS = [
        "棉", "纯棉", "棉质", "棉麻",
        "牛仔", "牛仔布",
        "羊毛", "毛呢",
        "丝", "真丝", "丝绸",
        "皮", "皮革", "真皮",
        "聚酯纤维", "化纤",
    ]

    # 场景关键词
    SCENE_KEYWORDS = [
        "面试", "约会", "聚会", "通勤", "出游", "旅行",
        "派对", "正式场合", "休闲", "运动", "健身", "商务"
    ]

    def parse(self, query: str) -> WardrobeQuery:
        """解析用户查询

        参数:
            query: 用户的自然语言查询，如"黑色裤子"、"适合面试的外套"

        返回:
            WardrobeQuery: 解析后的结构化查询条件
        """
        result = WardrobeQuery(raw_query=query)

        # 提取类别
        for category, keywords in self.CATEGORY_KEYWORDS.items():
            if any(kw in query for kw in keywords):
                result.categories.append(category)

        # 提取子类别
        for sub_cat, keywords in self.SUB_CATEGORY_KEYWORDS.items():
            if any(kw in query for kw in keywords):
                result.sub_categories.append(sub_cat)

        # 提取颜色
        for color, keywords in self.COLOR_KEYWORDS.items():
            if any(kw in query for kw in keywords):
                result.colors.append(color)

        # 提取季节
        for season, keywords in self.SEASON_KEYWORDS.items():
            if any(kw in query for kw in keywords):
                result.seasons.append(season)

        # 提取材质
        for material in self.MATERIAL_KEYWORDS:
            if material in query:
                result.materials.append(material)

        # 提取场景
        for scene in self.SCENE_KEYWORDS:
            if scene in query:
                result.scenes.append(scene)

        # 风格识别（简单规则）
        if any(w in query for w in ["正式", "面试", "商务", "职场"]):
            result.style = "正式"
        elif any(w in query for w in ["休闲", "日常", "轻松"]):
            result.style = "休闲"
        elif any(w in query for w in ["运动", "健身", "跑步"]):
            result.style = "运动"
        elif any(w in query for w in ["约会", "派对", "聚会"]):
            result.style = "社交"

        return result
