#!/usr/bin/env python3
"""
R-004 部署前检查脚本

在部署到生产环境前，验证所有配置和依赖是否正确。

使用方法：
    python scripts/r004_pre_deploy_check.py
"""

import sys
from pathlib import Path

# 检查结果收集
checks = []


def check_item(name: str, description: str, check_fn) -> bool:
    """执行单个检查项"""
    print(f"\n{'=' * 60}")
    print(f"检查项: {name}")
    print(f"说明: {description}")
    print(f"{'=' * 60}")

    try:
        result, message = check_fn()
        status = "✅ 通过" if result else "❌ 失败"
        print(f"{status}: {message}")

        checks.append({
            "name": name,
            "description": description,
            "success": result,
            "message": message
        })

        return result

    except Exception as e:
        print(f"❌ 检查失败: {e}")
        checks.append({
            "name": name,
            "description": description,
            "success": False,
            "message": f"检查过程出错: {e}"
        })
        return False


def check_files_exist():
    """检查关键文件是否存在"""
    required_files = [
        "src/services/query_parser.py",
        "src/services/hybrid_wardrobe_retriever.py",
        "tests/test_query_parser.py",
        "tests/test_hybrid_retriever.py",
        "tests/test_rag_hybrid_integration.py",
        "tests/test_r004_card_rendering.py",
        "tests/test_wardrobe_card_regression.py",
        "scripts/migrate_wardrobe_v2_to_v3.py",
        "scripts/toggle_hybrid_retrieval.py",
        "docs/R-004-HYBRID-RETRIEVAL.md",
        "docs/R-004-QUICKSTART.md",
        "docs/R-004-CHECKLIST.md",
    ]

    project_root = Path(__file__).parent.parent
    missing = []

    for file_path in required_files:
        full_path = project_root / file_path
        if not full_path.exists():
            missing.append(file_path)

    if missing:
        return False, f"缺失 {len(missing)} 个文件: {', '.join(missing[:3])}..."
    return True, f"所有 {len(required_files)} 个关键文件都存在"


def check_imports():
    """检查关键模块是否可导入"""
    try:
        from src.services.query_parser import QueryParser
        from src.services.hybrid_wardrobe_retriever import HybridWardrobeRetriever

        # 尝试实例化
        parser = QueryParser()
        query = parser.parse("黑色裤子")

        if not hasattr(query, "colors") or not hasattr(query, "categories"):
            return False, "QueryParser 解析结果缺少必要字段"

        return True, "关键模块导入成功，QueryParser 正常工作"

    except ImportError as e:
        return False, f"导入失败: {e}"
    except Exception as e:
        return False, f"模块测试失败: {e}"


def check_rag_service_integration():
    """检查 RagService 是否正确集成混合检索器"""
    try:
        import inspect
        from src.core.rag_agent import RagService

        # 检查 __init__ 参数
        init_signature = inspect.signature(RagService.__init__)
        params = list(init_signature.parameters.keys())

        if "enable_hybrid_retrieval" not in params:
            return False, "RagService.__init__ 缺少 enable_hybrid_retrieval 参数"

        # 检查是否有 _wardrobe_search 方法
        if not hasattr(RagService, "_wardrobe_search"):
            return False, "RagService 缺少 _wardrobe_search 方法"

        return True, "RagService 已正确集成混合检索器"

    except ImportError as e:
        return False, f"导入 RagService 失败: {e}"
    except Exception as e:
        return False, f"检查失败: {e}"


def check_vector_store_v3():
    """检查 VectorWardrobeService 是否支持 v3"""
    try:
        import inspect
        from src.services.vector_store import VectorWardrobeService, WARDROBE_COLLECTION_NAME

        if WARDROBE_COLLECTION_NAME != "wardrobe_items_v3":
            return False, f"当前 collection 名称为 {WARDROBE_COLLECTION_NAME}，不是 wardrobe_items_v3"

        # 检查当前实际使用的批量写入方法是否保存完整原始文本。
        if not hasattr(VectorWardrobeService, "add_items"):
            return False, "VectorWardrobeService 缺少 add_items 方法"
        source = inspect.getsource(VectorWardrobeService.add_items)

        # 检查是否包含 metadata.original_text 逻辑
        if "original_text" not in source:
            return False, "add_items 未包含 original_text 逻辑"

        return True, "VectorWardrobeService 已升级到 v3"

    except ImportError as e:
        return False, f"导入 VectorWardrobeService 失败: {e}"
    except Exception as e:
        return False, f"检查失败: {e}"


def check_dependencies():
    """检查必要的依赖是否安装"""
    required_packages = [
        "langchain",
        "langchain_community",
        "langchain_chroma",
        "chromadb",
        "supabase",
        "streamlit",
        "dashscope",
    ]

    missing = []

    for package in required_packages:
        try:
            __import__(package.replace("-", "_"))
        except ImportError:
            missing.append(package)

    if missing:
        return False, f"缺少依赖: {', '.join(missing)}"
    return True, f"所有 {len(required_packages)} 个依赖包已安装"


def check_env_config():
    """检查环境配置"""
    try:
        import os

        # 项目通过 config.base 的轻量加载器读取 .env，不依赖 python-dotenv。
        from config import base as _config_base  # noqa: F401

        required_env_vars = [
            "DASHSCOPE_API_KEY",
            "SUPABASE_URL",
            "SUPABASE_KEY",
        ]

        missing = []

        for var in required_env_vars:
            if not os.getenv(var):
                missing.append(var)

        if missing:
            return False, f"缺少环境变量: {', '.join(missing)}"
        return True, f"所有 {len(required_env_vars)} 个环境变量已配置"

    except Exception as e:
        return False, f"检查失败: {e}"


def main():
    print("=" * 60)
    print("🚀 R-004 部署前检查")
    print("=" * 60)
    print("\n开始执行检查...")

    # 执行所有检查
    check_item(
        "1. 文件完整性",
        "检查所有必需的代码文件和文档是否存在",
        check_files_exist
    )

    check_item(
        "2. 模块导入",
        "验证关键模块是否可以正常导入和实例化",
        check_imports
    )

    check_item(
        "3. RAG 服务集成",
        "检查 RagService 是否正确集成混合检索器",
        check_rag_service_integration
    )

    check_item(
        "4. 向量存储 v3",
        "验证 VectorWardrobeService 是否已升级到 v3",
        check_vector_store_v3
    )

    check_item(
        "5. 依赖包",
        "检查所有必需的 Python 包是否已安装",
        check_dependencies
    )

    check_item(
        "6. 环境配置",
        "验证 .env 文件中的必需环境变量",
        check_env_config
    )

    # 生成报告
    print("\n" + "=" * 60)
    print("📊 检查报告")
    print("=" * 60)

    passed = sum(1 for c in checks if c["success"])
    failed = len(checks) - passed

    print(f"\n总计: {passed}/{len(checks)} 项通过")

    if failed > 0:
        print(f"\n❌ {failed} 项检查失败：")
        for check in checks:
            if not check["success"]:
                print(f"  - {check['name']}: {check['message']}")

        print("\n建议：")
        print("1. 修复上述失败项")
        print("2. 运行测试: python scripts/run_r004_tests.py")
        print("3. 重新执行本检查脚本")

        sys.exit(1)

    else:
        print("\n✅ 所有检查通过！")
        print("\n后续步骤：")
        print("1. 运行完整测试: python scripts/run_r004_tests.py")
        print("2. 启用混合检索: python scripts/toggle_hybrid_retrieval.py --enable")
        print("3. 如有旧数据，执行迁移: python scripts/migrate_wardrobe_v2_to_v3.py")
        print("4. 重启服务")
        print('5. 验证效果（测试查询"黑色裤子"等）')

        sys.exit(0)


if __name__ == "__main__":
    main()
