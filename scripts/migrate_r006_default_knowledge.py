"""R-006 默认知识库迁移工具。

从真实 seeds/ 原文重新切分默认知识库，写入版本化 collection，并在切换前
校验 chunk 位置、内容版本、顺序和相邻文本重叠。旧 collection 仅备份保留，
不删除 Supabase 原始文档。
"""

from __future__ import annotations

import glob
import hashlib
import os
import shutil
import sys
from datetime import datetime

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from langchain_chroma import Chroma
from langchain_community.embeddings import DashScopeEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter

from config import base as config
from src.services.knowledge_base import extract_sections, find_section_for_position


def document_version(content: str) -> str:
    """返回原始文档内容版本；内容变化会产生新的稳定版本值。"""
    return hashlib.md5(content.encode("utf-8")).hexdigest()


def build_chunks(content: str, source: str) -> list[tuple[str, dict]]:
    """按生产配置切分真实文档，并生成可追溯的 chunk 元数据。"""
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=config.chunk_size,
        chunk_overlap=config.chunk_overlap,
        separators=config.separators,
        length_function=len,
        add_start_index=True,
    )
    sections = extract_sections(content)
    version = document_version(content)
    documents = splitter.create_documents([content])
    result = []
    for index, document in enumerate(documents):
        start = int(document.metadata["start_index"])
        end = start + len(document.page_content)
        result.append(
            (
                document.page_content,
                {
                    "source": source,
                    "create_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "operator_id": "system",
                    "operator_name": config.DEFAULT_OPERATOR,
                    "operator": config.DEFAULT_OPERATOR,
                    "source_type": "seed",
                    "chunk_index": index,
                    "total_chunks": len(documents),
                    "start_char": start,
                    "end_char": end,
                    "section_title": find_section_for_position(sections, start),
                    "document_hash": version,
                    "document_version": version,
                    "metadata_version": 4,
                },
            )
        )
    return result


def validate_chunks(chunks: list[tuple[str, dict]], source_contents: dict[str, str]) -> None:
    """验证迁移结果，失败时抛出异常阻止 collection 被切换使用。"""
    grouped: dict[str, list[tuple[str, dict]]] = {}
    for text, metadata in chunks:
        source = metadata["source"]
        content = source_contents[source]
        assert metadata["metadata_version"] == 4
        assert metadata["document_version"] == metadata["document_hash"] == document_version(content)
        start, end = metadata["start_char"], metadata["end_char"]
        assert 0 <= start < end <= len(content)
        assert content[start:end] == text
        grouped.setdefault(source, []).append((text, metadata))

    for source, items in grouped.items():
        items.sort(key=lambda item: item[1]["chunk_index"])
        assert [m["chunk_index"] for _, m in items] == list(range(len(items)))
        assert all(m["total_chunks"] == len(items) for _, m in items)
        for (left, _), (right, _) in zip(items, items[1:]):
            overlap = max(
                (size for size in range(min(len(left), len(right)), 0, -1) if left[-size:] == right[:size]),
                default=0,
            )
            assert overlap > 0, f"{source} 存在无实际重叠的相邻 chunk"


def main() -> None:
    """备份旧 collection，创建新版索引并执行完整验收。"""
    root = os.path.abspath(config.persist_directory)
    old_dir = os.path.join(root, "kb")
    backup_dir = os.path.join(root, f"kb_backup_r006_{datetime.now():%Y%m%d_%H%M%S}")
    new_dir = os.path.join(root, "kb_default_r006")

    if os.path.isdir(old_dir):
        shutil.copytree(old_dir, backup_dir)
        print(f"[备份] {backup_dir}")
    if os.path.isdir(new_dir):
        shutil.rmtree(new_dir)

    source_contents = {}
    all_chunks = []
    for filepath in sorted(glob.glob(os.path.join("seeds", "*.txt"))):
        with open(filepath, "r", encoding="utf-8") as file:
            content = file.read()
        source = f"[种子] {os.path.basename(filepath)}"
        source_contents[source] = content
        all_chunks.extend(build_chunks(content, source))

    validate_chunks(all_chunks, source_contents)
    store = Chroma(
        collection_name=config.knowledge_collection_name,
        embedding_function=DashScopeEmbeddings(model=config.EMBEDDING_MODEL_NAME),
        persist_directory=new_dir,
    )
    store.add_texts(
        texts=[text for text, _ in all_chunks],
        metadatas=[metadata for _, metadata in all_chunks],
    )
    result = store.get(include=["metadatas", "documents"])
    assert len(result["ids"]) == len(all_chunks)
    assert all((metadata or {}).get("metadata_version") == 4 for metadata in result["metadatas"])
    print(f"[通过] 新 collection: {config.knowledge_collection_name}")
    print(f"[通过] chunks: {len(result['ids'])}")
    print(f"[通过] sources: {len(source_contents)}")
    print(f"[通过] backup: {backup_dir}")


if __name__ == "__main__":
    main()