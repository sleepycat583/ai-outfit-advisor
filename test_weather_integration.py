"""测试天气服务集成到 RagService 的完整流程。

使用方法:
    python test_weather_integration.py
"""

import sys
from pathlib import Path

# 添加项目根目录到 Python 路径
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from weather_service import WeatherService


def test_current_weather():
    """测试当前天气查询。"""
    print("=" * 60)
    print("测试 1: 当前天气查询")
    print("=" * 60)

    service = WeatherService()
    test_cities = ["武陟", "北京", "上海"]

    for city in test_cities:
        print(f"\n查询城市: {city}")
        try:
            weather = service.get_current_weather(city)
            if isinstance(weather, str):
                print(f"  降级响应: {weather}")
            else:
                print(f"  温度: {weather.get('temp')}℃")
                print(f"  体感: {weather.get('feels_like')}℃")
                print(f"  天气: {weather.get('text')}")
                print(f"  风力: {weather.get('wind_dir')} {weather.get('wind_scale')}")
        except Exception as exc:
            print(f"  ✗ 失败: {exc}")


def test_forecast_7d():
    """测试未来 7 天预报。"""
    print("\n" + "=" * 60)
    print("测试 2: 未来 7 天预报")
    print("=" * 60)

    service = WeatherService()
    city = "武陟"

    print(f"\n查询城市: {city}")
    try:
        forecast = service.get_forecast_7d(city)
        if isinstance(forecast, str):
            print(f"  降级响应: {forecast}")
        else:
            print(f"  获取到 {len(forecast)} 天预报:")
            for day in forecast[:3]:  # 只显示前3天
                print(f"    · {day.get('date')} {day.get('text_day')}转{day.get('text_night')}, "
                      f"{day.get('temp_min')}~{day.get('temp_max')}℃")
    except Exception as exc:
        print(f"  ✗ 失败: {exc}")


def test_cache_hit():
    """测试缓存命中。"""
    print("\n" + "=" * 60)
    print("测试 3: 缓存命中测试")
    print("=" * 60)

    service = WeatherService()
    city = "武陟"

    print(f"\n第一次请求 {city}（应该请求 API）:")
    import time
    start = time.time()
    weather1 = service.get_current_weather(city)
    time1 = time.time() - start
    print(f"  耗时: {time1:.2f}s")

    print(f"\n第二次请求 {city}（应该命中缓存）:")
    start = time.time()
    weather2 = service.get_current_weather(city)
    time2 = time.time() - start
    print(f"  耗时: {time2:.2f}s")

    if time2 < time1 * 0.5:
        print("  ✓ 缓存生效（第二次明显更快）")
    else:
        print("  ⚠ 缓存可能未生效（两次耗时相近）")


def test_rag_integration():
    """测试 RagService 集成（模拟 Agent 工具调用）。"""
    print("\n" + "=" * 60)
    print("测试 4: RagService 集成测试")
    print("=" * 60)

    try:
        from rag import RagService

        # 不初始化完整的 RagService（避免依赖 LLM），只测试 _weather_search
        print("\n模拟 Agent 工具调用:")
        service = RagService()
        result = service._weather_search("武陟")
        print(f"  返回给 LLM 的文本:\n  {result}")

        if "武陟" in result and ("℃" in result or "系统提示" in result):
            print("\n  ✓ RagService 集成成功")
        else:
            print("\n  ✗ RagService 集成异常（返回格式不符合预期）")
    except Exception as exc:
        print(f"\n  ✗ RagService 集成失败: {exc}")


if __name__ == "__main__":
    import sys
    import io
    # 修复 Windows 控制台编码问题
    if sys.platform == "win32":
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

    print("\n天气服务集成测试\n")

    try:
        test_current_weather()
        test_forecast_7d()
        test_cache_hit()
        test_rag_integration()

        print("\n" + "=" * 60)
        print("✓ 所有测试执行完毕")
        print("=" * 60)
        print("\n请检查上述输出，确认:")
        print("  1. 当前天气查询返回结构化数据")
        print("  2. 未来 7 天预报返回列表数据")
        print("  3. 第二次查询明显比第一次快（缓存生效）")
        print("  4. RagService 能正确调用 WeatherService")

    except KeyboardInterrupt:
        print("\n\n用户中断测试")
        sys.exit(1)
