"""混合衣橱检索器：结构化过滤 + 语义排序

实现 R-004 优化方案：
1. 从用户查询中提取结构化条件（颜色、类别、季节）
2. 使用 Supabase SQL WHERE 进行结构化过滤，缩小候选集
3. 对候选集进行语义排序（embedding 相似度）
4. 返回 Top-K 结果

业务规则：
- 优先使用结构化过滤（当查询包含明确的类别/颜色/季节时）
- 结构化过滤为空时自动回退到纯语义检索
- 候选集 ≤ k 时直接返回，无需语义排序
- 所有 Supabase 查询必须包含 user_id 过滤（安全性）
"""

from typing import Optional
from config.supabase import get_supabase_client
from src.services.query_parser import QueryParser, WardrobeQuery
from src.services.vector_store import VectorWardrobeService


class HybridWardrobeRetriever:
    """混合检索器：结构化过滤 + 语义排序"""

    def __init__(
        self,
        user_id: str,
        vector_service: VectorWardrobeService,
        enable_structural_filter: bool = True
    ):
        """初始化混合检索器

        参数:
            user_id: 用户 ID（必须）
            vector_service: 向量检索服务
            enable_structural_filter: 是否启用结构化过滤（配置开关）
        """
        self.user_id = user_id
        self.vector_service = vector_service
        self.enable_structural_filter = enable_structural_filter
        self.supabase = get_supabase_client()
        self.query_parser = QueryParser()

    def search(self, query: str, k: int = 5) -> list[str]:
        """混合检索

        返回:
            list[str]: 带 id: 的文本列表，格式与 VectorWardrobeService.search() 一致
            例如：["- id:uuid 类别:下装/裤子 颜色:黑色...", ...]
        """
        # Step 1: 解析查询
        parsed = self.query_parser.parse(query)
        print(f"[混合检索] 查询解析结果: 类别={parsed.categories}, 颜色={parsed.colors}, 季节={parsed.seasons}", flush=True)

        # Step 2: 决定检索策略
        if self.enable_structural_filter and parsed.has_structural_filters():
            # 结构化过滤 + 语义排序
            print(f"[混合检索] 使用结构化过滤策略", flush=True)
            return self._hybrid_search(parsed, k)
        else:
            # 纯语义检索（回退策略）
            print(f"[混合检索] 无结构化条件，使用纯语义检索", flush=True)
            return self._semantic_only_search(query, k)

    def _hybrid_search(self, parsed: WardrobeQuery, k: int) -> list[str]:
        """结构化过滤 + 语义排序"""
        # Step 1: 结构化过滤获取候选集
        candidate_ids = self._structural_filter(parsed)

        if not candidate_ids:
            # 无候选，回退到纯语义检索
            print(f"[混合检索] 结构化过滤无结果，回退到纯语义检索", flush=True)
            return self._semantic_only_search(parsed.raw_query, k)

        if len(candidate_ids) <= k:
            # 候选数 ≤ k，直接返回（无需语义排序）
            print(f"[混合检索] 候选集≤k({len(candidate_ids)}≤{k})，直接返回", flush=True)
            return self._get_texts_by_ids(candidate_ids[:k])

        # Step 2: 对候选集做语义排序
        print(f"[混合检索] 对 {len(candidate_ids)} 个候选进行语义排序，取 Top-{k}", flush=True)
        ranked = self._semantic_rerank(parsed.raw_query, candidate_ids, k)
        return ranked

    def _structural_filter(self, parsed: WardrobeQuery) -> list[str]:
        """结构化过滤：从 Supabase 获取候选集 ID

        返回:
            list[str]: 候选单品 ID 列表
        """
        query_builder = (
            self.supabase.table("wardrobe_items")
            .select("id")
            .eq("user_id", self.user_id)
        )

        # 类别过滤
        if parsed.categories:
            query_builder = query_builder.in_("category", parsed.categories)

        # 颜色过滤（支持模糊匹配）
        if parsed.colors:
            # PostgreSQL: color ILIKE '%黑%' OR color ILIKE '%白%'
            color_conditions = []
            for color in parsed.colors:
                color_conditions.append(f"color.ilike.%{color}%")
            # 拼接多个颜色条件
            query_builder = query_builder.or_(",".join(color_conditions))

        # 季节过滤（数组字段，使用 @> 包含操作符）
        # 注意：Supabase Python SDK 的 contains() 方法用于数组包含
        if parsed.seasons:
            # 匹配任一季节：season && ARRAY['春', '夏']
            # Supabase SDK: overlaps() 方法
            query_builder = query_builder.overlaps("season", parsed.seasons)

        try:
            result = query_builder.execute()
            candidate_ids = [row["id"] for row in result.data]
            print(f"[结构化过滤] 获得 {len(candidate_ids)} 个候选", flush=True)
            return candidate_ids
        except Exception as exc:
            print(f"[WARN] 结构化过滤失败: {exc}", flush=True)
            import traceback
            traceback.print_exc()
            return []

    def _semantic_rerank(self, query: str, candidate_ids: list[str], k: int) -> list[str]:
        """对候选集进行语义排序

        策略：
        1. 从向量库中检索 Top-K*2
        2. 只保留在 candidate_ids 中的结果
        3. 返回前 k 个

        返回:
            list[str]: 带 id: 的文本列表
        """
        # 从向量库检索更多结果（扩大召回范围）
        top_texts = self.vector_service.search(query, k=min(k * 3, 50))

        # 过滤：只保留候选集中的单品
        matched_texts = []
        candidate_ids_set = set(candidate_ids)

        import re
        for text in top_texts:
            match = re.search(r"id:([^\s]+)", text)
            if match:
                item_id = match.group(1)
                if item_id in candidate_ids_set:
                    matched_texts.append(text)
                    if len(matched_texts) >= k:
                        break

        print(f"[语义排序] 从 {len(top_texts)} 个向量结果中匹配到 {len(matched_texts)} 个候选", flush=True)
        return matched_texts[:k]

    def _semantic_only_search(self, query: str, k: int) -> list[str]:
        """纯语义检索（回退策略）"""
        print(f"[纯语义检索] 使用向量检索，k={k}", flush=True)
        return self.vector_service.search(query, k=k)

    def _get_texts_by_ids(self, item_ids: list[str]) -> list[str]:
        """根据 ID 列表从向量库获取文本

        当候选集很小时（≤ k），直接返回这些单品的文本，无需语义排序。

        返回:
            list[str]: 带 id: 的文本列表
        """
        if not item_ids:
            return []

        # 从 Supabase 获取完整信息并格式化为文本
        try:
            result = (
                self.supabase.table("wardrobe_items")
                .select("*")
                .eq("user_id", self.user_id)
                .in_("id", item_ids)
                .execute()
            )

            texts = []
            for row in result.data:
                text = self._row_to_text(row)
                texts.append(text)

            return texts
        except Exception as exc:
            print(f"[WARN] 根据 ID 获取文本失败: {exc}", flush=True)
            return []

    def _row_to_text(self, row: dict) -> str:
        """将 Supabase 行转为文本格式（与 vector_store.py 保持一致）"""
        item_id = row.get("id", "")
        category = row.get("category", "")
        sub_category = row.get("sub_category", "")
        color = row.get("color", "")
        material = row.get("material", "")
        season = row.get("season", "")
        # season 可能是数组或字符串
        if isinstance(season, list):
            season = ",".join(season)
        return f"- id:{item_id} 类别:{category}/{sub_category} 颜色:{color} 材质:{material} 适季:{season}"
