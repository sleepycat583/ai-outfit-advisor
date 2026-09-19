"""知识库与衣橱向量检索服务。

衣橱向量索引依赖 Supabase 中的原始单品数据，并向 RAG 服务提供带真实单品 ID 的检索文本。
"""

import os
import re
import time

from langchain_chroma import Chroma
from config import base as config
from config.supabase import get_supabase_client


# 衣橱索引的文本格式一旦变化，旧 Chroma 文档不会自动更新。
# 使用版本化 collection 名称，让格式升级能够触发一次安全重建，而不是继续读取旧数据。
# v3: embedding 文本不含 UUID（减少噪音），metadata 保存完整 original_text（保证返回给 LLM 的文本包含 id:）
WARDROBE_COLLECTION_NAME = "wardrobe_items_v3"
WARDROBE_ITEM_ID_PATTERN = re.compile(r"(?:^|\s)-?\s*id:([^\s]+)")


class VectorStoreService(object):
    def __init__(self, embedding, user_id: str = ""):
        """初始化知识库向量服务，并打印 Chroma 连接初始化耗时。"""
        start_time = time.time()
        self.embedding = embedding
        self.user_id = user_id

        persist_dir = os.path.join(config.persist_directory, user_id, "kb") if user_id else os.path.join(config.persist_directory, "kb")
        collection_name = f"kb_{user_id}" if user_id else "kb_default"

        os.makedirs(persist_dir, exist_ok=True)

        self.vector_store = Chroma(
            collection_name=collection_name,
            embedding_function=self.embedding,
            persist_directory=persist_dir,
        )

        # 容器重启后自动重建知识库索引
        if self._is_empty():
            self._rebuild_knowledge_base()

        print(f"[PERF] VectorStoreService.__init__ took {time.time() - start_time:.3f}s", flush=True)

    def _is_empty(self) -> bool:
        """检查知识库向量索引是否为空（容器重启检测）。"""
        try:
            result = self.vector_store.get(limit=1)
            return len(result.get("ids", [])) == 0
        except Exception:
            return True

    def _rebuild_knowledge_base(self) -> None:
        """容器重启时从种子和 Supabase 重建知识库索引。

        复用 KnowledgeBaseService 的导入逻辑，通过临时实例化触发恢复。
        KnowledgeBaseService.__init__ 会自动执行 _rebuild_index()，
        包含种子导入和 Supabase 用户文档恢复。
        """
        try:
            # 懒加载导入，避免循环依赖
            from src.services.knowledge_base import KnowledgeBaseService

            # 临时创建 KnowledgeBaseService 实例执行恢复
            # 传入相同的 user_id，确保访问同一个 collection
            # username 设为 None，恢复时不需要用户名
            KnowledgeBaseService(
                user_id=self.user_id,
                username=None
            )
            print(f"[知识库恢复] 已自动初始化知识库索引", flush=True)
        except Exception as exc:
            print(f"[WARN] 知识库自动恢复失败，将继续使用空索引: {exc}", flush=True)

    def get_retriever(self, k: int = None):
        """返回向量库检索器，支持动态 k 值。

        注意：此方法返回的 retriever 不支持相似度过滤。
        如需过滤，应在调用侧使用 similarity_search_with_score 手动过滤。

        参数:
            k: 返回数量，默认使用配置值 knowledge_retrieval_k
        """
        k = k or int(config.knowledge_retrieval_k)
        return self.vector_store.as_retriever(search_kwargs={"k": k})


class VectorWardrobeService:
    """管理衣橱单品的向量索引（独立 Chroma Collection），用于语义检索 Top-K 单品。

    容器重启后自动从 Supabase wardrobe_items 表重建向量索引。

    衣橱索引使用独立版本名。这样可以避免旧版本只保存描述、不保存真实单品 ID
    时继续被检索出来，导致前端无法根据 ID 渲染卡片。
    """

    def __init__(self, embedding, user_id: str = ""):
        """初始化衣橱向量服务，并在索引为空时自动从 Supabase 重建。"""
        start_time = time.time()
        self.embedding = embedding
        self.user_id = user_id
        self.supabase = get_supabase_client()

        persist_directory = os.path.join(config.persist_directory, user_id, "wardrobe") if user_id else os.path.join(config.persist_directory, "wardrobe")
        os.makedirs(persist_directory, exist_ok=True)
        self.vector_store = Chroma(
            collection_name=WARDROBE_COLLECTION_NAME,
            embedding_function=self.embedding,
            persist_directory=persist_directory,
        )

        # 容器重启后自动重建向量索引
        if self._is_empty():
            self._rebuild_from_supabase()

        print(f"[PERF] VectorWardrobeService.__init__ took {time.time() - start_time:.3f}s", flush=True)

    def _is_empty(self) -> bool:
        """检查向量库是否为空（容器重启检测）。"""
        try:
            result = self.vector_store.get(limit=1)
            return len(result.get("ids", [])) == 0
        except Exception:
            return True

    def _rebuild_from_supabase(self) -> None:
        """从 Supabase wardrobe_items 表重建向量索引。

        容器重启后,本地 Chroma 向量库会丢失,但 Supabase 中仍保留原始单品数据。
        此方法读取用户的所有衣橱单品,重新生成 embedding 并写入 Chroma。
        """
        if not self.user_id:
            return

        try:
            result = (
                self.supabase.table("wardrobe_items")
                .select("*")
                .eq("user_id", self.user_id)
                .execute()
            )
        except Exception as exc:
            print(f"[WARN] 衣橱向量重建失败,Supabase 查询异常: {exc}", flush=True)
            return

        if not result.data:
            return

        items_to_add = []
        for row in result.data:
            item_text = self._row_to_text(row)
            items_to_add.append((row["id"], item_text))

        if items_to_add:
            self.add_items(items_to_add)
            print(f"[衣橱恢复] 已从云端重建 {len(items_to_add)} 件单品的向量索引", flush=True)

    def _row_to_text(self, row: dict) -> str:
        """将 Supabase wardrobe_items 行转为向量索引文本。

        格式与 wardrobe.py 中的 _item_to_text 保持一致。
        """
        item_id = row.get("id", "")
        category = row.get("category", "")
        sub_category = row.get("sub_category", "")
        color = row.get("color", "")
        material = row.get("material", "")
        season = row.get("season", "")
        return f"- id:{item_id} 类别:{category}/{sub_category} 颜色:{color} 材质:{material} 适季:{season}"

    def add_items(self, items: list[tuple[str, str]]) -> None:
        """批量添加单品文本到向量库。items 为 [(item_id, text), ...] 列表。

        优化点（v3）：
        - embedding 文本不包含 UUID（避免无意义噪音，提升语义相似度）
        - metadata 保存完整 original_text，用于检索时重建返回文本
        - 保证返回给 LLM 的文本包含 id:UUID，确保前端卡片渲染
        """
        if not items:
            return

        ids, texts = zip(*items)

        # 构造 embedding 文本：移除 "- id:UUID " 前缀，只保留语义相关部分
        embedding_texts = []
        for text in texts:
            # 移除 "- id:UUID " 部分，保留 "类别:xx 颜色:xx ..." 语义文本
            clean_text = re.sub(r"^-?\s*id:[^\s]+\s+", "", text.strip())
            embedding_texts.append(clean_text)

        # metadata 保存完整原始文本，用于检索时重建
        self.vector_store.add_texts(
            texts=embedding_texts,  # 用于 embedding 的文本（无UUID噪音）
            metadatas=[{
                "item_id": iid,
                "original_text": text  # 保存完整文本（包含 id:）
            } for iid, text in zip(ids, texts)],
            ids=list(ids),
        )

    def update_items(self, items: list[tuple[str, str]]) -> None:
        """批量更新单品文本。先删后加，避免 Chroma update 的 upsert 行为不一致。"""
        if not items:
            return
        ids_to_del = [iid for iid, _ in items]
        existing = self.vector_store.get(ids=ids_to_del)
        if existing and existing.get("ids"):
            self.vector_store.delete(ids=existing["ids"])
        self.add_items(items)

    def delete_items(self, item_ids: list[str]) -> None:
        if not item_ids:
            return
        existing = self.vector_store.get(ids=item_ids)
        if existing and existing.get("ids"):
            self.vector_store.delete(ids=existing["ids"])

    def search(self, query: str, k: int = 15) -> list[str]:
        """语义检索最相关的 Top-K 单品描述文本，并打印检索耗时。

        返回值中的每条文本必须包含真实的 `id:`，供 LLM 提取用于前端卡片渲染。

        v3 优化：
        - embedding 计算时不含 UUID（提升语义相似度）
        - 返回文本从 metadata.original_text 重建（包含 id:UUID）
        - 兼容旧版本数据（v2：从 metadata.item_id 重建）
        """
        start_time = time.time()
        docs = self.vector_store.similarity_search(query, k=k)
        print(f"[PERF] VectorWardrobeService.search took {time.time() - start_time:.3f}s", flush=True)

        valid_texts = []
        for doc in docs:
            metadata = doc.metadata or {}

            # v3 新版本：优先使用 original_text（已包含 id:）
            if "original_text" in metadata:
                original_text = str(metadata["original_text"]).strip()
                if original_text:
                    valid_texts.append(original_text)
                    continue

            # v2 兼容：从 metadata.item_id 重建完整文本
            metadata_item_id = str(metadata.get("item_id") or "").strip()
            if metadata_item_id:
                # page_content 是无 UUID 的语义文本（v3）或完整文本（v2）
                text = str(doc.page_content or "").strip()

                # 检查 page_content 是否已包含 id:（v2 旧数据）
                if WARDROBE_ITEM_ID_PATTERN.search(text):
                    valid_texts.append(text)
                    continue

                # v3 或缺失 id: 的情况，从 metadata.item_id 重建
                repaired_text = f"- id:{metadata_item_id} {text}"
                valid_texts.append(repaired_text)
                print(f"[WARN] 使用 metadata.item_id 重建文本: {metadata_item_id}", flush=True)
                continue

            # 兜底：尝试从 page_content 直接提取（极少数异常数据）
            text = str(doc.page_content or "").strip()
            if WARDROBE_ITEM_ID_PATTERN.search(text):
                valid_texts.append(text)
                continue

            print(f"[WARN] 忽略无单品 ID 的衣橱索引文档", flush=True)

        return valid_texts


if __name__ == '__main__':
    from langchain_community.embeddings import DashScopeEmbeddings
    retriever = VectorStoreService(DashScopeEmbeddings(model="text-embedding-v4")).get_retriever()
    res = retriever.invoke("我的体重180斤，尺码推荐")
    print(res)
