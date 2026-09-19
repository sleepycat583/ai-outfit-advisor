"""衣橱向量索引 v2 → v3 数据迁移脚本。

迁移内容：
- 将 embedding 文本中的 UUID 移除（减少噪音）
- 在 metadata 中保存完整 original_text（包含 id:UUID）
- 保证返回给 LLM 的文本包含 id: 前缀，确保卡片渲染

使用方法：
    python scripts/migrate_wardrobe_v2_to_v3.py --user-id <user_id>
    python scripts/migrate_wardrobe_v2_to_v3.py --all  # 迁移所有用户
"""

import os
import sys
import argparse
from pathlib import Path

# 添加项目根目录到 Python 路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from langchain_chroma import Chroma
from langchain_community.embeddings import DashScopeEmbeddings
from config import base as config
from config.supabase import get_supabase_client


def migrate_user_wardrobe(user_id: str, embedding, dry_run: bool = False):
    """迁移单个用户的衣橱向量索引从 v2 到 v3。

    Args:
        user_id: 用户 ID
        embedding: Embedding 模型实例
        dry_run: True = 只打印迁移计划，不实际执行
    """
    print(f"\n{'='*60}")
    print(f"迁移用户: {user_id}")
    print(f"{'='*60}")

    persist_dir = os.path.join(config.persist_directory, user_id, "wardrobe")

    # 检查 v2 collection 是否存在
    v2_collection_name = "wardrobe_items_v2"
    v3_collection_name = "wardrobe_items_v3"

    try:
        v2_store = Chroma(
            collection_name=v2_collection_name,
            embedding_function=embedding,
            persist_directory=persist_dir,
        )
    except Exception as exc:
        print(f"[跳过] 用户 {user_id} 没有 v2 collection: {exc}")
        return

    # 读取 v2 所有数据
    v2_data = v2_store.get()
    if not v2_data or not v2_data.get("ids"):
        print(f"[跳过] 用户 {user_id} 的 v2 collection 为空")
        return

    item_count = len(v2_data["ids"])
    print(f"[信息] v2 collection 包含 {item_count} 件单品")

    if dry_run:
        print(f"[模拟] 将创建 v3 collection 并迁移 {item_count} 件单品")
        print(f"[模拟] v2 collection 将被保留（手动删除: {persist_dir}/{v2_collection_name}）")
        return

    # 创建 v3 collection
    v3_store = Chroma(
        collection_name=v3_collection_name,
        embedding_function=embedding,
        persist_directory=persist_dir,
    )

    # 检查 v3 是否已有数据
    v3_existing = v3_store.get(limit=1)
    if v3_existing and v3_existing.get("ids"):
        print(f"[警告] v3 collection 已存在数据，将执行增量迁移（跳过已存在的 ID）")
        existing_ids = set(v3_store.get().get("ids", []))
    else:
        existing_ids = set()

    # 从 Supabase 重新读取原始数据，确保迁移数据的准确性
    supabase = get_supabase_client()
    result = (
        supabase.table("wardrobe_items")
        .select("*")
        .eq("user_id", user_id)
        .execute()
    )

    if not result.data:
        print(f"[警告] Supabase 中未找到用户 {user_id} 的衣橱数据，回退到 v2 数据")
        supabase_items = {}
    else:
        supabase_items = {row["id"]: row for row in result.data}

    # 迁移数据
    migrated_count = 0
    skipped_count = 0

    for idx, item_id in enumerate(v2_data["ids"]):
        if item_id in existing_ids:
            skipped_count += 1
            continue

        # 优先从 Supabase 重建文本（保证数据最新）
        if item_id in supabase_items:
            row = supabase_items[item_id]
            original_text = _row_to_text(row)
        else:
            # 回退：从 v2 metadata 或 page_content 重建
            metadata = v2_data["metadatas"][idx] if v2_data.get("metadatas") else {}
            page_content = v2_data["documents"][idx] if v2_data.get("documents") else ""

            if "original_text" in metadata:
                original_text = metadata["original_text"]
            elif page_content:
                # v2 的 page_content 可能已包含 id:
                original_text = page_content if page_content.startswith("- id:") else f"- id:{item_id} {page_content}"
            else:
                print(f"[警告] 无法重建单品 {item_id} 的文本，跳过")
                skipped_count += 1
                continue

        # 移除 UUID 生成 embedding 文本
        import re
        clean_text = re.sub(r"^-?\s*id:[^\s]+\s+", "", original_text.strip())

        # 添加到 v3 collection
        v3_store.add_texts(
            texts=[clean_text],
            metadatas=[{
                "item_id": item_id,
                "original_text": original_text
            }],
            ids=[item_id]
        )
        migrated_count += 1

        if (migrated_count + skipped_count) % 10 == 0:
            print(f"[进度] 已处理 {migrated_count + skipped_count}/{item_count} 件单品")

    print(f"\n[完成] 迁移统计:")
    print(f"  - 成功迁移: {migrated_count} 件")
    print(f"  - 跳过已存在: {skipped_count} 件")
    print(f"  - v2 collection 路径: {persist_dir}/{v2_collection_name}")
    print(f"  - v3 collection 路径: {persist_dir}/{v3_collection_name}")
    print(f"\n[提示] v2 collection 已保留，确认迁移无误后可手动删除")


def _row_to_text(row: dict) -> str:
    """将 Supabase wardrobe_items 行转为向量索引文本（与 vector_store.py 保持一致）。"""
    item_id = row.get("id", "")
    category = row.get("category", "")
    sub_category = row.get("sub_category", "")
    color = row.get("color", "")
    material = row.get("material", "")
    season = row.get("season", "")
    return f"- id:{item_id} 类别:{category}/{sub_category} 颜色:{color} 材质:{material} 适季:{season}"


def find_all_users() -> list[str]:
    """从本地 persist_directory 查找所有有衣橱数据的用户。"""
    persist_root = Path(config.persist_directory)
    if not persist_root.exists():
        return []

    users = []
    for user_dir in persist_root.iterdir():
        if user_dir.is_dir() and (user_dir / "wardrobe").exists():
            users.append(user_dir.name)

    return users


def main():
    parser = argparse.ArgumentParser(description="衣橱向量索引 v2 → v3 迁移工具")
    parser.add_argument("--user-id", type=str, help="指定要迁移的用户 ID")
    parser.add_argument("--all", action="store_true", help="迁移所有用户")
    parser.add_argument("--dry-run", action="store_true", help="模拟运行，不实际迁移")

    args = parser.parse_args()

    if not args.user_id and not args.all:
        parser.error("请指定 --user-id 或 --all")

    # 初始化 embedding 模型
    print("[初始化] 加载 Embedding 模型...")
    embedding = DashScopeEmbeddings(model="text-embedding-v4")

    if args.all:
        users = find_all_users()
        if not users:
            print("[错误] 未找到任何用户的衣橱数据")
            return

        print(f"[发现] 找到 {len(users)} 个用户")
        for user_id in users:
            try:
                migrate_user_wardrobe(user_id, embedding, dry_run=args.dry_run)
            except Exception as exc:
                print(f"[错误] 用户 {user_id} 迁移失败: {exc}")
                continue
    else:
        migrate_user_wardrobe(args.user_id, embedding, dry_run=args.dry_run)

    print(f"\n{'='*60}")
    print("迁移完成！")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
