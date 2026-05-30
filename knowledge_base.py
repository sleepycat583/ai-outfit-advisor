"""知识库引擎（Chroma 向量库 + Supabase 内容持久化）

Streamlit Cloud 的临时文件系统会导致 Chroma 本地向量库在容器回收后丢失。
解决策略：
  - seeds/ 目录中的种子知识随代码部署，启动时自动导入
  - 用户上传的文本内容持久化到 Supabase，启动时自动重新向量化
  - MD5 去重记录存储在 Supabase，跨容器保持一致性
"""

import datetime
import glob
import hashlib
import os

from langchain_chroma import Chroma
from langchain_community.embeddings import DashScopeEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter

import config_data as config
from supabase_config import get_supabase_client

SEEDS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "seeds")


def get_string_md5(input_str: str, encoding: str = "utf-8") -> str:
    str_bytes = input_str.encode(encoding=encoding)
    md5_obj = hashlib.md5()
    md5_obj.update(str_bytes)
    return md5_obj.hexdigest()


class KnowledgeBaseService(object):
    """知识库服务：Chroma 向量检索 + Supabase 内容持久化。"""

    def __init__(self, user_id: str = ""):
        self.user_id = user_id
        self.supabase = get_supabase_client()

        persist_dir = (
            os.path.join(config.persist_directory, user_id, "kb")
            if user_id
            else os.path.join(config.persist_directory, "kb")
        )
        collection_name = f"kb_{user_id}" if user_id else "kb_default"

        os.makedirs(persist_dir, exist_ok=True)

        self.chroma = Chroma(
            collection_name=collection_name,
            embedding_function=DashScopeEmbeddings(model=config.EMBEDDING_MODEL_NAME),
            persist_directory=persist_dir,
        )
        self.collection_name = collection_name

        self.splitter = RecursiveCharacterTextSplitter(
            chunk_size=config.chunk_size,
            chunk_overlap=config.chunk_overlap,
            separators=config.separators,
            length_function=len,
        )

        self._rebuild_index()

    # ------------------------------------------------------------------
    # 索引重建
    # ------------------------------------------------------------------

    def _collection_count(self) -> int:
        try:
            result = self.chroma.get(limit=1)
            return len(result.get("ids", []))
        except Exception:
            return 0

    def _rebuild_index(self):
        """容器启动时重建向量索引。

        1. 如果索引非空，跳过（已经由之前的操作构建）
        2. 否则：导入 seeds/ + 从 Supabase 恢复用户上传内容
        """
        if self._collection_count() > 0:
            return

        # Step 1: 导入种子知识
        self._import_seeds()

        # Step 2: 从 Supabase 恢复用户上传内容
        self._restore_user_uploads()

    def _import_seeds(self):
        """导入 seeds/ 目录下的种子知识文件。每次启动时重新导入（幂等）。"""
        if not os.path.isdir(SEEDS_DIR):
            return

        seed_files = sorted(glob.glob(os.path.join(SEEDS_DIR, "*.txt")))
        if not seed_files:
            return

        imported = 0
        for filepath in seed_files:
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    content = f.read()
            except UnicodeDecodeError:
                with open(filepath, "r", encoding="gb18030") as f:
                    content = f.read()

            filename = os.path.basename(filepath)
            md5_hex = get_string_md5(content)

            # 检查是否已导入（Supabase MD5 去重）
            if self._md5_exists(md5_hex):
                continue

            if len(content) > config.max_split_char_number:
                chunks = self.splitter.split_text(content)
            else:
                chunks = [content]

            metadata = {
                "source": f"[种子] {filename}",
                "create_time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "operator": config.DEFAULT_OPERATOR,
            }

            self.chroma.add_texts(
                chunks,
                metadatas=[metadata for _ in chunks],
            )
            self._md5_save(md5_hex, f"[种子] {filename}", content)
            imported += 1

        if imported > 0:
            print(f"[种子导入] 已自动导入 {imported} 份基础穿搭知识", flush=True)

    def _restore_user_uploads(self):
        """从 Supabase 恢复用户上传的知识文档。"""
        result = (
            self.supabase.table("kb_documents")
            .select("*")
            .eq("user_id", self.user_id)
            .order("created_at", desc=False)
            .execute()
        )
        if not result.data:
            return

        restored = 0
        for row in result.data:
            content = row.get("content", "")
            source = row.get("source", "")
            if not content:
                continue

            if len(content) > config.max_split_char_number:
                chunks = self.splitter.split_text(content)
            else:
                chunks = [content]

            metadata = {
                "source": source,
                "create_time": row.get("created_at", ""),
                "operator": config.DEFAULT_OPERATOR,
            }

            self.chroma.add_texts(
                chunks,
                metadatas=[metadata for _ in chunks],
            )
            restored += 1

        if restored > 0:
            print(f"[用户恢复] 已从云端恢复 {restored} 份知识文档", flush=True)

    # ------------------------------------------------------------------
    # MD5 去重（Supabase 持久化）
    # ------------------------------------------------------------------

    def _md5_exists(self, md5_str: str) -> bool:
        result = (
            self.supabase.table("kb_documents")
            .select("id")
            .eq("user_id", self.user_id)
            .eq("md5", md5_str)
            .execute()
        )
        return bool(result.data)

    def _md5_save(self, md5_str: str, source: str, content: str) -> None:
        self.supabase.table("kb_documents").insert(
            {
                "user_id": self.user_id,
                "source": source,
                "content": content,
                "md5": md5_str,
                "created_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }
        ).execute()

    # ------------------------------------------------------------------
    # 公共 API
    # ------------------------------------------------------------------

    def upload_by_str(self, data: str, filename: str) -> str:
        md5_hex = get_string_md5(data)

        if self._md5_exists(md5_hex):
            return "[跳过]内容已经在知识库中"

        if len(data) > config.max_split_char_number:
            knowledge_chunks: list[str] = self.splitter.split_text(data)
        else:
            knowledge_chunks = [data]

        metadata = {
            "source": filename,
            "create_time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "operator": config.DEFAULT_OPERATOR,
        }

        self.chroma.add_texts(
            knowledge_chunks,
            metadatas=[metadata for _ in knowledge_chunks],
        )

        # 持久化到 Supabase，确保容器重启后可恢复
        self._md5_save(md5_hex, filename, data)

        return "[成功]内容已经成功载入向量库"

    def get_stats(self) -> dict:
        """返回知识库统计信息。"""
        result = self.chroma.get(include=["metadatas"])
        ids = result.get("ids", [])
        metadatas = result.get("metadatas", [])

        total_chunks = len(ids)

        source_map: dict[str, dict] = {}
        for meta in metadatas:
            source = meta.get("source", "未知来源") if meta else "未知来源"
            if source not in source_map:
                source_map[source] = {
                    "source": source,
                    "chunks": 0,
                    "create_time": "",
                    "operator": "",
                }
            source_map[source]["chunks"] += 1
            if meta:
                source_map[source]["create_time"] = meta.get("create_time", "")
                source_map[source]["operator"] = meta.get("operator", "")

        sources = sorted(source_map.values(), key=lambda x: x["create_time"], reverse=True)

        return {
            "total_sources": len(sources),
            "total_chunks": total_chunks,
            "sources": sources,
        }

    def delete_by_source(self, source: str) -> int:
        """删除指定来源的所有文档段。返回删除数量。"""
        result = self.chroma.get(
            where={"source": source},
            include=["metadatas"],
        )
        ids = result.get("ids", [])
        if ids:
            self.chroma.delete(ids=ids)

        # 同时从 Supabase 中删除
        self.supabase.table("kb_documents").delete().eq(
            "user_id", self.user_id
        ).eq("source", source).execute()

        return len(ids)

    def clear_all(self) -> int:
        """清空当前知识库的所有数据。返回删除数量。"""
        result = self.chroma.get()
        ids = result.get("ids", [])
        if ids:
            self.chroma.delete(ids=ids)

        # 同时清空 Supabase 中的记录
        self.supabase.table("kb_documents").delete().eq(
            "user_id", self.user_id
        ).execute()

        return len(ids)


if __name__ == "__main__":
    service = KnowledgeBaseService()
    r = service.upload_by_str("周杰伦", "testfile")
    print(r)
