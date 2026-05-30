import os

from langchain_chroma import Chroma
import config_data as config


class VectorStoreService(object):
    def __init__(self, embedding, user_id: str = ""):
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

    def get_retriever(self):
        """返回向量库检索器，方便加入 Chain"""
        return self.vector_store.as_retriever(search_kwargs={"k": int(config.similarity_threshold)})


class VectorWardrobeService:
    """管理衣橱单品的向量索引（独立 Chroma Collection），用于语义检索 Top-K 单品。"""

    def __init__(self, embedding, user_id: str = ""):
        self.embedding = embedding
        self.user_id = user_id
        persist_directory = os.path.join(config.persist_directory, user_id, "wardrobe") if user_id else os.path.join(config.persist_directory, "wardrobe")
        os.makedirs(persist_directory, exist_ok=True)
        self.vector_store = Chroma(
            collection_name="wardrobe_items",
            embedding_function=self.embedding,
            persist_directory=persist_directory,
        )

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
        """语义检索最相关的 Top-K 单品描述文本。"""
        docs = self.vector_store.similarity_search(query, k=k)
        return [doc.page_content for doc in docs]


if __name__ == '__main__':
    from langchain_community.embeddings import DashScopeEmbeddings
    retriever = VectorStoreService(DashScopeEmbeddings(model="text-embedding-v4")).get_retriever()
    res = retriever.invoke("我的体重180斤，尺码推荐")
    print(res)
