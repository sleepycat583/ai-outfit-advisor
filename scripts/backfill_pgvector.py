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
        source_count = len(service._get_chroma().get(include=["documents"]).get("ids", []))
        written = service.backfill_from_chroma(batch_size=args.batch_size)
        target = service._get_pgvector_store().count(source_kind="knowledge")
        report["sources"]["knowledge"] = {"source_count": source_count, "written": written, "target_count": target}
        if target < source_count:
            raise RuntimeError(f"knowledge 回填不完整: source={source_count}, target={target}")
    if args.source in {"wardrobe", "both"}:
        service = VectorWardrobeService(embedding=embedding, user_id=args.user_id)
        source_count = len(service._get_chroma().get(include=["documents"]).get("ids", []))
        written = service.backfill_from_chroma(batch_size=args.batch_size)
        target = service._get_pgvector_store().count(source_kind="wardrobe")
        report["sources"]["wardrobe"] = {"source_count": source_count, "written": written, "target_count": target}
        if target < source_count:
            raise RuntimeError(f"wardrobe 回填不完整: source={source_count}, target={target}")
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
