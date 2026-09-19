#!/usr/bin/env python3
"""
R-004 混合检索优化测试运行脚本

运行所有 R-004 相关测试，生成测试报告。

使用方法：
    python scripts/run_r004_tests.py              # 运行所有 R-004 本地测试
    python scripts/run_r004_tests.py --quick      # 兼容旧参数，运行同一组本地测试
    python scripts/run_r004_tests.py --verbose    # 详细输出
"""

import argparse
import subprocess
import sys
from datetime import datetime
from pathlib import Path


def run_command(cmd: list[str], description: str) -> tuple[bool, str]:
    """运行命令并返回结果"""
    print(f"\n{'=' * 60}")
    print(f"🧪 {description}")
    print(f"{'=' * 60}")
    print(f"命令: {' '.join(cmd)}\n")

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=Path(__file__).parent.parent
        )

        # 打印输出
        if result.stdout:
            print(result.stdout)
        if result.stderr:
            print(result.stderr, file=sys.stderr)

        success = result.returncode == 0
        status = "✅ 通过" if success else "❌ 失败"
        print(f"\n{status}")

        return success, result.stdout + result.stderr

    except Exception as e:
        print(f"❌ 执行失败: {e}", file=sys.stderr)
        return False, str(e)


def main():
    parser = argparse.ArgumentParser(description="运行 R-004 混合检索优化测试")
    parser.add_argument("--quick", action="store_true", help="快速测试（兼容旧参数，不再额外跳过测试）")
    parser.add_argument("--verbose", "-v", action="store_true", help="详细输出")
    args = parser.parse_args()

    # 测试套件定义
    test_suites = []

    test_suites.extend([
        {
            "name": "查询解析器测试",
            "files": ["tests/test_query_parser.py"],
            "description": "验证颜色、类别、季节等字段提取"
        },
        {
            "name": "混合检索器测试",
            "files": ["tests/test_hybrid_retriever.py"],
            "description": "验证结构化过滤 + 语义排序逻辑"
        },
        {
            "name": "RAG 服务集成测试",
            "files": ["tests/test_rag_hybrid_integration.py"],
            "description": "验证 RagService 集成混合检索器"
        },
        {
            "name": "卡片渲染回归测试",
            "files": ["tests/test_r004_card_rendering.py"],
            "description": "验证 UUID 传递和前端卡片渲染"
        },
        {
            "name": "衣橱卡片契约回归测试",
            "files": ["tests/test_wardrobe_card_regression.py"],
            "description": "验证 v3 索引版本、单品 ID 和标签提取契约"
        },
    ])

    # 运行测试
    results = []
    start_time = datetime.now()

    print(f"\n{'=' * 60}")
    print(f"🚀 开始运行 R-004 测试套件")
    print(f"{'=' * 60}")
    print(f"开始时间: {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"测试套件数: {len(test_suites)}")

    for suite in test_suites:
        cmd = [
            sys.executable, "-m", "pytest",
            *suite["files"],
            "-v" if args.verbose else "-q",
            "--tb=short",
            "--color=yes"
        ]

        success, output = run_command(cmd, suite["name"])
        results.append({
            "name": suite["name"],
            "description": suite["description"],
            "success": success,
            "output": output
        })

    end_time = datetime.now()
    duration = (end_time - start_time).total_seconds()

    # 生成报告
    print(f"\n{'=' * 60}")
    print(f"📊 测试报告")
    print(f"{'=' * 60}")
    print(f"总耗时: {duration:.2f}s")
    print(f"结束时间: {end_time.strftime('%Y-%m-%d %H:%M:%S')}\n")

    passed = sum(1 for r in results if r["success"])
    failed = len(results) - passed

    print(f"测试结果: {passed}/{len(results)} 通过")
    print()

    for i, result in enumerate(results, 1):
        status = "✅ 通过" if result["success"] else "❌ 失败"
        print(f"{i}. {result['name']}: {status}")
        print(f"   {result['description']}")

    # 失败详情
    if failed > 0:
        print(f"\n{'=' * 60}")
        print(f"❌ 失败的测试详情")
        print(f"{'=' * 60}\n")

        for result in results:
            if not result["success"]:
                print(f"## {result['name']}")
                print(f"{result['output']}")
                print()

    # 退出码
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
