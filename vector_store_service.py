import os

from langchain_chroma import Chroma
import config_data as config


class VectorStoreService(object):
    def __init__(self, embedding):
        """
        :param embedding: 嵌入模型的传入
        """
        self.embedding = embedding

        persist_directory = config.persist_directory
        needs_rebuild = (not os.path.isdir(persist_directory)) or (not any(os.scandir(persist_directory)))
        if needs_rebuild:
            print("⚠️ [警告] Chroma 数据库目录缺失或为空，正在触发自愈重建", flush=True)
            os.makedirs(persist_directory, exist_ok=True)

        self.vector_store = Chroma(
            collection_name=config.collection_name,
            embedding_function=self.embedding,
            persist_directory=persist_directory,
        )

        if needs_rebuild and hasattr(self.vector_store, "persist"):
            self.vector_store.persist()

    def get_retriever(self):
        """返回向量库检索器，方便加入 Chain"""
        return self.vector_store.as_retriever(search_kwargs={"k": int(config.similarity_threshold)})


if __name__ == '__main__':
    from langchain_community.embeddings import DashScopeEmbeddings
    retriever = VectorStoreService(DashScopeEmbeddings(model="text-embedding-v4")).get_retriever()
    res = retriever.invoke("我的体重180斤，尺码推荐")
    print(res)
