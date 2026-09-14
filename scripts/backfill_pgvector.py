"""将指定用户的本地 Chroma 索引幂等回填到私有 pgvector。

运行前必须配置服务端 ``SUPABASE_DB_URL`` 与 DashScope 密钥。脚本强制使用
Chroma 作为读取源并开启双写，完成后输出源记录数和目标记录数，便于发布前
核对；只有核对通过后才允许切换 ``VECTOR_BACKEND=pgvector``。
"""

from __future__ import annotations

import argparse
import json

import config_data as config
from langchain_community.embeddings import DashScopeEmbeddings
from supabase_config import get_database_url
from vector_store_service import VectorStoreService, VectorWardrobeService


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill Chroma vectors into private pgvector")
    parser.add_argument("--user-id", required=True)
    parser.add_argument("--source", choices=("knowledge", "wardrobe", "both"), default="both")
    parser.add_argument("--batch-size", type=int, default=64)
    args = parser.parse_args()
    if not get_database_url():
        parser.error("SUPABASE_DB_URL 未配置")
    if args.batch_size < 1:
        parser.error("batch-size 必须大于 0")

    config.VECTOR_BACKEND = "chroma"
    config.VECTOR_DUAL_WRITE = True
    embedding = DashScopeEmbeddings(model=config.EMBEDDING_MODEL_NAME)
    report: dict[str, object] = {"user_id": args.user_id, "sources": {}}
    if args.source in {"knowledge", "both"}:
        service = VectorStoreService(embedding=embedding, user_id=args.user_id)
        source_ids = service._get_chroma().get(include=["documents"]).get("ids", [])
        written = service.backfill_from_chroma(batch_size=args.batch_size, strict=True)
        target_documents = service._get_pgvector_store().list_documents(source_kind="knowledge")
        target_ids = {document["id"] for document in target_documents}
        missing_ids = sorted(set(source_ids) - target_ids)
        extra_ids = sorted(target_ids - set(source_ids))
        report["sources"]["knowledge"] = {"source_count": len(source_ids), "written": written, "target_count": len(target_documents), "missing_ids": missing_ids, "extra_ids": extra_ids}
        if missing_ids or extra_ids:
            raise RuntimeError(f"knowledge 回填集合不一致: missing={len(missing_ids)}, extra={len(extra_ids)}")
    if args.source in {"wardrobe", "both"}:
        service = VectorWardrobeService(embedding=embedding, user_id=args.user_id)
        source_result = service._get_chroma().get(include=["documents", "metadatas"])
        source_chroma_ids = source_result.get("ids", [])
        source_metadatas = source_result.get("metadatas") or [{} for _ in source_chroma_ids]
        if len(source_chroma_ids) != len(source_metadatas):
            raise RuntimeError(
                "wardrobe Chroma 源快照长度不一致: "
                f"ids={len(source_chroma_ids)}, metadatas={len(source_metadatas)}"
            )
        source_ids = [
            str((metadata or {}).get("item_id") or chroma_id)
            for chroma_id, metadata in zip(source_chroma_ids, source_metadatas)
        ]
        written = service.backfill_from_chroma(batch_size=args.batch_size, strict=True)
        target_documents = service._get_pgvector_store().list_documents(source_kind="wardrobe")
        target_ids = {document["id"] for document in target_documents}
        missing_ids = sorted(set(source_ids) - target_ids)
        extra_ids = sorted(target_ids - set(source_ids))
        report["sources"]["wardrobe"] = {"source_count": len(source_ids), "written": written, "target_count": len(target_documents), "missing_ids": missing_ids, "extra_ids": extra_ids}
        if missing_ids or extra_ids:
            raise RuntimeError(f"wardrobe 回填集合不一致: missing={len(missing_ids)}, extra={len(extra_ids)}")
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
