"""
知识库
"""

import os
import glob
import hashlib
import datetime
import config_data as config
from langchain_chroma import Chroma
from langchain_community.embeddings import DashScopeEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter

SEEDS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "seeds")
BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def check_md5(md5_str: str, md5_path: str):
    if not os.path.exists(md5_path):
        with open(md5_path, 'w', encoding='utf-8') as _:
            pass
        return False

    with open(md5_path, 'r', encoding='utf-8') as f:
        for line in f:
            if line.strip() == md5_str:
                return True
    return False


def save_md5(md5_str: str, md5_path: str):
    with open(md5_path, 'a', encoding="utf-8") as f:
        f.write(md5_str + '\n')


def get_string_md5(input_str: str, encoding='utf-8'):
    # 将传入的字符串转换为md5字符串

    # 将字符串转换为bytes字符数组
    str_bytes = input_str.encode(encoding=encoding)

    # 创建md5对象
    md5_obj = hashlib.md5()
    # 得到md5对象
    md5_obj.update(str_bytes)
    # 更新内容（传入的都需转换的字符数组）
    md5_hex = md5_obj.hexdigest()
    # 得到md5的十六进制字符

    return md5_hex


class KnowledgeBaseService(object):

    def __init__(self, user_id: str = ""):
        self.user_id = user_id

        persist_dir = os.path.join(config.persist_directory, user_id, "kb") if user_id else os.path.join(config.persist_directory, "kb")
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

        self._import_seeds()

    def _collection_count(self) -> int:
        """返回当前 Collection 中的文档数（安全封装，避免外部直接访问私有属性）。"""
        try:
            result = self.chroma.get(limit=1)
            return len(result.get("ids", []))
        except Exception:
            return 0

    def _import_seeds(self):
        """新用户首次使用时，自动导入 seeds/ 目录下的种子知识文件。"""
        if not os.path.isdir(SEEDS_DIR):
            return

        if self._collection_count() > 0:
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

            md5_dir = os.path.join(BASE_DIR, "data", self.user_id) if self.user_id else os.path.join(BASE_DIR, "data")
            os.makedirs(md5_dir, exist_ok=True)
            md5_path = os.path.join(md5_dir, "md5.text")

            if check_md5(md5_hex, md5_path):
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
            save_md5(md5_hex, md5_path)
            imported += 1

        if imported > 0:
            print(f"[种子导入] 已自动导入 {imported} 份基础穿搭知识", flush=True)

    def upload_by_str(self, data: str, filename: str):
        md5_hex = get_string_md5(data)

        md5_dir = os.path.join(BASE_DIR, "data", self.user_id) if self.user_id else os.path.join(BASE_DIR, "data")
        os.makedirs(md5_dir, exist_ok=True)
        md5_path = os.path.join(md5_dir, "md5.text")

        if check_md5(md5_hex, md5_path):
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

        save_md5(md5_hex, md5_path)

        return "[成功]内容已经成功载入向量库"

    def get_stats(self) -> dict:
        """返回知识库统计信息：文档数、文本段数、按来源分组的列表。"""
        result = self.chroma.get(include=["metadatas"])
        ids = result.get("ids", [])
        metadatas = result.get("metadatas", [])

        total_chunks = len(ids)

        # 按 source 分组统计
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
        return len(ids)

    def clear_all(self) -> int:
        """清空当前知识库的所有数据。返回删除数量。"""
        result = self.chroma.get()
        ids = result.get("ids", [])
        if ids:
            self.chroma.delete(ids=ids)

        # 同时清空 md5 去重记录
        md5_dir = os.path.join(BASE_DIR, "data", self.user_id) if self.user_id else os.path.join(BASE_DIR, "data")
        md5_path = os.path.join(md5_dir, "md5.text")
        if os.path.exists(md5_path):
            os.remove(md5_path)

        return len(ids)


if __name__ == '__main__':
    service = KnowledgeBaseService()
    r = service.upload_by_str("周杰伦", "testfile")
    print(r)
