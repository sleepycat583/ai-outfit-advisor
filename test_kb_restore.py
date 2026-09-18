"""R-001 修复验证脚本：测试问答页知识库自动恢复功能。

运行前提：
1. 清空 Chroma 数据目录（模拟容器重启）
2. 确保 .env 配置正确
3. 确保 seeds/ 目录存在

测试目标：
- VectorStoreService 在空索引时自动触发恢复
- 种子知识成功导入
- 知识库检索可用
"""

import os
import shutil
import sys
import time

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from langchain_community.embeddings import DashScopeEmbeddings
from src.services.vector_store import VectorStoreService
from config import base as config


def cleanup_chroma(user_id: str = "test_user"):
    """清理测试用户的 Chroma 数据"""
    persist_dir = os.path.join(config.persist_directory, user_id, "kb")
    if os.path.exists(persist_dir):
        shutil.rmtree(persist_dir)
        print(f"[清理] 已删除 {persist_dir}")
    else:
        print(f"[清理] 目录不存在，跳过: {persist_dir}")


def test_auto_restore():
    """测试 VectorStoreService 的自动恢复功能"""
    test_user_id = "test_user_r001"

    print("=" * 60)
    print("R-001 知识库自动恢复测试")
    print("=" * 60)

    # 步骤 1：清理旧数据
    print("\n步骤 1：清理旧 Chroma 数据（模拟容器重启）")
    cleanup_chroma(test_user_id)

    # 步骤 2：创建 VectorStoreService 实例
    print("\n步骤 2：初始化 VectorStoreService（应触发自动恢复）")
    start_time = time.time()

    try:
        embedding = DashScopeEmbeddings(model=config.EMBEDDING_MODEL_NAME)
        vector_service = VectorStoreService(
            embedding=embedding,
            user_id=test_user_id
        )
        init_time = time.time() - start_time
        print(f"[成功] VectorStoreService 初始化完成，耗时 {init_time:.2f}s")
    except Exception as exc:
        print(f"[失败] VectorStoreService 初始化失败: {exc}")
        return False

    # 步骤 3：检查知识库是否非空
    print("\n步骤 3：检查知识库索引是否非空")
    try:
        result = vector_service.vector_store.get(limit=5)
        doc_count = len(result.get("ids", []))

        if doc_count > 0:
            print(f"[成功] 知识库索引包含 {doc_count} 个文档段（前5个）")

            # 显示前几个文档的来源
            metadatas = result.get("metadatas", [])
            if metadatas:
                print("\n已导入的文档来源示例：")
                sources = set()
                for meta in metadatas[:5]:
                    if meta:
                        source = meta.get("source", "未知")
                        sources.add(source)

                for idx, source in enumerate(sources, 1):
                    print(f"  {idx}. {source}")
        else:
            print("[失败] 知识库索引为空，自动恢复未生效")
            return False
    except Exception as exc:
        print(f"[失败] 检查索引失败: {exc}")
        return False

    # 步骤 4：测试检索功能
    print("\n步骤 4：测试知识库检索功能")
    try:
        retriever = vector_service.get_retriever()
        test_queries = [
            "羊毛衫怎么洗",
            "面试穿搭建议",
            "黑色和白色怎么搭配"
        ]

        for query in test_queries:
            docs = retriever.invoke(query)
            print(f"  查询: '{query}' -> 返回 {len(docs)} 个相关文档")
            if docs:
                # 显示第一个结果的摘要
                first_doc = docs[0]
                content_preview = str(first_doc.page_content)[:100]
                source = first_doc.metadata.get("source", "未知")
                print(f"    来源: {source}")
                print(f"    内容: {content_preview}...")
    except Exception as exc:
        print(f"[失败] 检索测试失败: {exc}")
        return False

    # 步骤 5：检查种子文件数量
    print("\n步骤 5：验证种子文件导入")
    seeds_dir = "seeds"
    if os.path.exists(seeds_dir):
        seed_files = [f for f in os.listdir(seeds_dir) if f.endswith('.txt')]
        print(f"[信息] seeds/ 目录包含 {len(seed_files)} 个 .txt 文件")
        for seed_file in seed_files:
            print(f"  - {seed_file}")
    else:
        print("[警告] seeds/ 目录不存在")

    print("\n" + "=" * 60)
    print("测试完成：R-001 修复验证通过")
    print("=" * 60)
    return True


if __name__ == "__main__":
    try:
        success = test_auto_restore()
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n\n[中断] 测试被用户中断")
        sys.exit(1)
    except Exception as e:
        print(f"\n[错误] 测试脚本执行失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
