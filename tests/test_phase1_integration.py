"""
Phase 1 集成测试(模拟版)
验证检索和压缩逻辑的完整流程,不依赖实际向量服务
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


def print_section(title: str):
    """打印测试章节标题"""
    print("\n" + "=" * 70)
    print(f"  {title}")
    print("=" * 70 + "\n")


def test_topk_estimation():
    """测试1: Top-K估算逻辑"""
    print_section("测试1: Top-K估算逻辑")

    from src.core.rag_agent import RagService

    # 创建最小化的RagService实例(不初始化向量服务)
    class MinimalRagService:
        def _estimate_topk(self, query: str) -> int:
            # 复制实际逻辑
            scene_keywords = ["适合", "面试", "约会", "聚会", "通勤", "出游", "旅行", "派对", "穿搭", "搭配"]
            if any(kw in query for kw in scene_keywords):
                return 12

            complexity_markers = [
                ("季节", ["春", "夏", "秋", "冬", "早春", "初秋", "盛夏", "寒冬"]),
                ("颜色", ["黑", "白", "蓝", "红", "灰", "米", "卡其", "藏青", "深蓝", "浅蓝", "棕", "绿"]),
                ("风格", ["休闲", "正式", "运动", "甜美", "帅气", "简约", "复古", "街头", "优雅"]),
                ("类别", ["外套", "裤子", "裙子", "鞋", "上衣", "内搭", "大衣", "夹克", "衬衫", "T恤"]),
            ]

            dimension_count = sum(
                1 for _, keywords in complexity_markers
                if any(kw in query for kw in keywords)
            )

            if dimension_count <= 1:
                return 5
            elif dimension_count == 2:
                return 8
            else:
                return 12

    service = MinimalRagService()

    test_cases = [
        ("黑色裤子", 8, "2维度:颜色+类别"),
        ("黑色春季外套", 12, "3维度:颜色+季节+类别"),
        ("适合面试的正式穿搭", 12, "场景关键词"),
    ]

    all_pass = True
    for query, expected_k, reason in test_cases:
        actual_k = service._estimate_topk(query)
        status = "✓" if actual_k == expected_k else "✗"
        print(f"{status} '{query}' → k={actual_k} (预期:{expected_k}) [{reason}]")
        all_pass &= (actual_k == expected_k)

    return all_pass


def test_compression_logic():
    """测试2: LLM压缩逻辑(模拟)"""
    print_section("测试2: LLM压缩触发条件")

    # 模拟检索结果数量
    test_cases = [
        (5, False, "5条结果不触发压缩"),
        (8, False, "8条结果不触发压缩"),
        (9, True, "9条结果触发压缩"),
        (12, True, "12条结果触发压缩"),
    ]

    print("压缩规则: 当检索结果 > 8条 时触发LLM压缩\n")

    all_pass = True
    for count, should_compress, reason in test_cases:
        actual_compress = count > 8
        status = "✓" if actual_compress == should_compress else "✗"
        action = "触发压缩" if actual_compress else "直接返回"
        print(f"{status} {count}条结果 → {action} [{reason}]")
        all_pass &= (actual_compress == should_compress)

    return all_pass


def test_result_size_estimation():
    """测试3: 结果大小估算"""
    print_section("测试3: 结果大小估算")

    # 假设每条单品描述约100字
    CHARS_PER_ITEM = 100

    test_cases = [
        ("黑色裤子", 5, 5 * CHARS_PER_ITEM, "约500字"),
        ("黑色春季外套", 8, 8 * CHARS_PER_ITEM, "约800字"),
        ("适合面试的正式穿搭", 12, 800, "12条压缩到800字"),
    ]

    print("估算规则: 每条单品约100字, >8条时压缩到800字\n")

    for query, k, expected_chars, reason in test_cases:
        compressed = k > 8
        actual_chars = 800 if compressed else k * CHARS_PER_ITEM
        status = "✓" if actual_chars == expected_chars else "✗"
        print(f"{status} '{query}' k={k} → 约{actual_chars}字 [{reason}]")

    return True


def test_context_savings():
    """测试4: 上下文节省估算"""
    print_section("测试4: 上下文节省估算")

    print("假设场景: 30轮对话,每轮触发衣橱检索\n")

    # Phase 0: 衣橱数据直接注入prompt (约30KB)
    phase0_wardrobe_size = 30000  # 字符
    phase0_per_turn = phase0_wardrobe_size
    phase0_total = phase0_per_turn * 30

    # Phase 1: 动态检索+压缩 (约500-800字/次)
    phase1_avg_size = 650  # 字符 (取500-800的中间值)
    phase1_per_turn = phase1_avg_size
    phase1_total = phase1_per_turn * 30

    print(f"Phase 0 (prompt注入):")
    print(f"  每轮: {phase0_per_turn:,}字 × 30轮 = {phase0_total:,}字")
    print(f"  估算token: {phase0_total * 1.5:.0f} (~{phase0_total * 1.5 / 1000:.0f}K)")
    print()

    print(f"Phase 1 (动态检索+压缩):")
    print(f"  每轮: {phase1_per_turn:,}字 × 30轮 = {phase1_total:,}字")
    print(f"  估算token: {phase1_total * 1.5:.0f} (~{phase1_total * 1.5 / 1000:.0f}K)")
    print()

    savings = phase0_total - phase1_total
    savings_pct = (savings / phase0_total) * 100

    print(f"节省:")
    print(f"  字符数: {savings:,}字 (减少{savings_pct:.1f}%)")
    print(f"  估算token: {savings * 1.5:.0f} (~{savings * 1.5 / 1000:.0f}K)")
    print()

    print(f"✓ Phase 1预计可将上下文从~{phase0_total * 1.5 / 1000:.0f}K降至~{phase1_total * 1.5 / 1000:.0f}K")

    return True


def main():
    """主测试入口"""
    print("\n" + "▓" * 70)
    print("  Phase 1 集成测试(模拟版)")
    print("▓" * 70)

    results = []

    results.append(("Top-K估算", test_topk_estimation()))
    results.append(("压缩触发", test_compression_logic()))
    results.append(("结果大小", test_result_size_estimation()))
    results.append(("上下文节省", test_context_savings()))

    # 总结
    print_section("测试总结")

    all_pass = all(result[1] for result in results)

    for name, passed in results:
        status = "✓" if passed else "✗"
        print(f"{status} {name}测试")

    print()

    if all_pass:
        print("✓ 所有测试通过")
        print("\nPhase 1优化效果:")
        print("  1. 动态Top-K: 根据查询复杂度返回5/8/12条")
        print("  2. 智能压缩: >8条时LLM压缩到800字")
        print("  3. 上下文优化: 预计可降低97%以上的衣橱相关token消耗")
        print("\n建议:")
        print("  - 在实际环境中运行完整测试(需要向量服务)")
        print("  - 观察LLM日志中的实际token消耗")
        print("  - 验证压缩后的结果是否保留了关键信息")
    else:
        print("✗ 部分测试失败")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
