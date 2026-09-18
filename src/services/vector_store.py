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
WARDROBE_COLLECTION_NAME = "wardrobe_items_v2"
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
        print(f"[PERF] VectorStoreService.__init__ took {time.time() - start_time:.3f}s", flush=True)

    def get_retriever(self):
        """返回向量库检索器，方便加入 Chain"""
        return self.vector_store.as_retriever(search_kwargs={"k": int(config.similarity_threshold)})


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
        """批量添加单品文本到向量库。items 为 [(item_id, text), ...] 列表。"""
        if not items:
            return
        ids, texts = zip(*items)
        self.vector_store.add_texts(
            texts=list(texts),
            metadatas=[{"item_id": iid} for iid in ids],
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

        返回值中的每条文本必须包含真实的 `id:`。这是模型生成 `<item>...</item>`
        卡片标记的唯一可靠来源；不符合当前格式的旧文档会被丢弃并记录日志。
        """
        start_time = time.time()
        docs = self.vector_store.similarity_search(query, k=k)
        print(f"[PERF] VectorWardrobeService.search took {time.time() - start_time:.3f}s", flush=True)
        valid_texts = []
        for doc in docs:
            text = str(doc.page_content or "").strip()
            metadata_item_id = str((doc.metadata or {}).get("item_id") or "").strip()
            if WARDROBE_ITEM_ID_PATTERN.search(text):
                valid_texts.append(text)
                continue

            # 旧文档可能有 metadata.item_id，但正文没有 id；补回标准前缀，
            # 让一次运行也能容忍少量历史数据，真正的全量迁移仍由 v2 collection 完成。
            if metadata_item_id:
                repaired_text = f"- id:{metadata_item_id} {text}".strip()
                valid_texts.append(repaired_text)
                print(f"[WARN] 衣橱索引文档缺少 id，已使用 metadata.item_id 修复: {metadata_item_id}", flush=True)
                continue

            print(f"[WARN] 忽略无单品 ID 的衣橱索引文档: {text[:120]}", flush=True)

        return valid_texts


if __name__ == '__main__':
    from langchain_community.embeddings import DashScopeEmbeddings
    retriever = VectorStoreService(DashScopeEmbeddings(model="text-embedding-v4")).get_retriever()
    res = retriever.invoke("我的体重180斤，尺码推荐")
    print(res)
