#!/usr/bin/env python3
"""
UI 验证辅助脚本

快速测试混合检索是否在 UI 中正常工作。
模拟用户查询并打印结果，无需实际打开浏览器。

使用方法：
    python scripts/test_ui_validation.py --user-id <你的用户ID>
"""

import sys
from pathlib import Path

# 添加项目根目录到 Python 路径
sys.path.insert(0, str(Path(__file__).parent.parent))

import argparse
from langchain_community.embeddings import DashScopeEmbeddings
from src.services.vector_store import VectorWardrobeService
from src.core.rag_agent import RagService
from config import base as config


def run_query(service: RagService, query: str):
    """测试单个查询"""
    print(f"\n{'=' * 60}")
    print(f"查询: {query}")
    print(f"{'=' * 60}")

    try:
        result = service._wardrobe_search(query)

        if "暂无相关单品" in result or "不可用" in result:
            print(f"❌ {result}")
            return False

        # 提取返回的单品数量
        lines = [line for line in result.split('\n') if line.strip()]
        print(f"✅ 返回 {len(lines)} 件单品")

        # 打印前 3 件
        for i, line in enumerate(lines[:3], 1):
            print(f"  {i}. {line}")

        if len(lines) > 3:
            print(f"  ... 还有 {len(lines) - 3} 件")

        return True

    except Exception as e:
        print(f"❌ 查询失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    parser = argparse.ArgumentParser(description="UI 验证辅助脚本")
    parser.add_argument("--user-id", required=True, help="用户 ID")
    args = parser.parse_args()

    print("=" * 60)
    print("🧪 UI 混合检索验证")
    print("=" * 60)
    print(f"用户 ID: {args.user_id}\n")

    # 初始化服务
    print("初始化服务...")
    try:
        embedding = DashScopeEmbeddings(model=config.EMBEDDING_MODEL_NAME)
        vector_wardrobe = VectorWardrobeService(
            embedding=embedding,
            user_id=args.user_id
        )

        service = RagService(
            vector_wardrobe=vector_wardrobe,
            user_id=args.user_id,
            enable_hybrid_retrieval=True
        )

        print("✅ 服务初始化成功\n")

    except Exception as e:
        print(f"❌ 服务初始化失败: {e}")
        import traceback
        traceback.print_exc()
        return

    # 测试查询
    test_queries = [
        ("黑色裤子", "颜色精确查询"),
        ("春季外套", "季节+类别查询"),
        ("黑色正式外套", "复合查询"),
    ]

    results = []
    for query, description in test_queries:
        print(f"\n📋 测试场景: {description}")
        success = run_query(service, query)
        results.append((description, success))

    # 生成报告
    print(f"\n{'=' * 60}")
    print("📊 验证报告")
    print(f"{'=' * 60}")

    passed = sum(1 for _, success in results if success)
    total = len(results)

    print(f"\n总计: {passed}/{total} 项通过\n")

    for description, success in results:
        status = "✅ 通过" if success else "❌ 失败"
        print(f"  {status} - {description}")

    if passed == total:
        print("\n🎉 所有测试通过！混合检索在 UI 中正常工作。")
    else:
        print("\n⚠️  部分测试失败，请检查配置或查看日志。")


if __name__ == "__main__":
    main()
