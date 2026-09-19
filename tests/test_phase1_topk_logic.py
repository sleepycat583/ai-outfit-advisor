"""
Phase 1 Top-K估算逻辑单元测试
不依赖实际向量服务,仅验证k值估算算法
"""

import sys
import io
from pathlib import Path

# 修复Windows控制台编码
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# 导入生产代码中的 estimate_topk_for_query 函数
from src.core.rag_agent import estimate_topk_for_query


def print_test_case(query: str, expected_k: int):
    """打印测试用例结果"""
    actual_k = estimate_topk_for_query(query)
    status = "✓" if actual_k == expected_k else "✗"

    # 分析维度
    dimensions = []
    if any(kw in query for kw in ["春", "夏", "秋", "冬"]):
        dimensions.append("季节")
    if any(kw in query for kw in ["黑", "白", "蓝", "红", "灰"]):
        dimensions.append("颜色")
    if any(kw in query for kw in ["休闲", "正式", "运动"]):
        dimensions.append("风格")
    if any(kw in query for kw in ["外套", "裤子", "裙子", "上衣"]):
        dimensions.append("类别")
    if any(kw in query for kw in ["适合", "面试", "约会", "穿搭"]):
        dimensions.append("场景")

    dim_str = "+".join(dimensions) if dimensions else "无"

    print(f"{status} \"{query}\" (长度:{len(query)}) → k={actual_k} (预期:{expected_k}) [维度:{dim_str}]")

    if actual_k != expected_k:
        print(f"   说明: 实际k值与预期不符")

    return actual_k == expected_k


def main():
    print("\n" + "=" * 70)
    print("  Phase 1 Top-K估算逻辑测试")
    print("=" * 70 + "\n")

    all_pass = True

    # === 简单查询测试 (k=5) - ≤5字 ===
    print("[简单查询(≤5字) - 预期k=5]")
    all_pass &= print_test_case("外套", 5)  # 2字,1维度:类别
    all_pass &= print_test_case("裤子", 5)  # 2字,1维度:类别
    all_pass &= print_test_case("黑色", 5)  # 2字,1维度:颜色
    all_pass &= print_test_case("黑裤子", 5)  # 3字,2维度:颜色+类别 (字数优先)
    all_pass &= print_test_case("黑色裤子", 5)  # 4字,2维度:颜色+类别 (字数优先)
    all_pass &= print_test_case("黑色的裤子", 5)  # 5字,2维度:颜色+类别 (字数优先)
    print()

    # === 中等查询测试 (k=8) - 2维度且6-10字 ===
    print("[中等查询(2维度且6-10字) - 预期k=8]")
    all_pass &= print_test_case("有什么黑色的裤子", 8)  # 7字,2维度:颜色+类别
    all_pass &= print_test_case("推荐一件春季外套", 8)  # 7字,2维度:季节+类别
    print()

    # === 复杂查询测试 (k=12) - 3+维度或场景或≥11字 ===
    print("[复杂查询(3+维度或场景或≥11字) - 预期k=12]")
    all_pass &= print_test_case("黑色休闲裤子", 12)  # 6字,3维度:颜色+风格+类别
    all_pass &= print_test_case("黑色春季外套", 12)  # 6字,3维度:颜色+季节+类别
    all_pass &= print_test_case("休闲黑色外套", 12)  # 6字,3维度:风格+颜色+类别
    all_pass &= print_test_case("黑色春季休闲外套", 12)  # 7字,4维度
    all_pass &= print_test_case("适合面试", 12)  # 场景关键词
    all_pass &= print_test_case("适合面试的正式穿搭", 12)  # 场景+多维度
    all_pass &= print_test_case("约会穿搭", 12)  # 场景关键词
    all_pass &= print_test_case("适合通勤的鞋", 12)  # 场景关键词
    print()

    # === 总结 ===
    print("=" * 70)
    if all_pass:
        print("✓ 所有测试用例通过")
    else:
        print("✗ 部分测试用例失败,请检查k值估算逻辑")
        print("\n建议调整:")
        print("1. 确认字数优先: ≤5字返回k=5(即使有2维度)")
        print("2. 确认场景关键词优先级最高,直接返回k=12")
        print("3. 确认边界: 6-10字且2维度→k=8, 3+维度或≥11字→k=12")
    print("=" * 70)

    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())
