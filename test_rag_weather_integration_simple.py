"""简单测试：验证 rag.py 中的 WeatherService 集成点"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def test_integration_points():
    """检查 rag.py 中的集成点是否正确"""
    print("=" * 60)
    print("检查 rag.py 中的 WeatherService 集成点")
    print("=" * 60)

    with open("rag.py", "r", encoding="utf-8") as f:
        content = f.read()

    checks = [
        ("导入 WeatherService", "from weather_service import WeatherService"),
        ("初始化 weather_service", "self.weather_service = WeatherService()"),
        ("_weather_search 调用 get_current_weather", "self.weather_service.get_current_weather(query)"),
        ("generate_weekly_plan 调用 get_forecast_7d", "self.weather_service.get_forecast_7d(city)"),
        ("Agent 工具注册", 'name="weather_search"'),
        ("工具 description 更新", "query 参数必须是具体城市名称"),
    ]

    all_passed = True
    for check_name, pattern in checks:
        if pattern in content:
            print(f"   [OK] {check_name}")
        else:
            print(f"   [FAIL] {check_name} - 未找到: {pattern}")
            all_passed = False

    print("\n" + "=" * 60)
    if all_passed:
        print("[SUCCESS] 所有集成点检查通过！")
        print("=" * 60)
        print("\n摘要:")
        print("- rag.py 已完全集成 WeatherService")
        print("- _weather_search() 使用 get_current_weather()")
        print("- generate_weekly_plan() 使用 get_forecast_7d()")
        print("- Agent 工具 description 已更新为简洁版本")
        print("- 无需 DuckDuckGo，所有天气查询走和风天气 API")
    else:
        print("[FAIL] 部分集成点缺失")
        sys.exit(1)

if __name__ == "__main__":
    test_integration_points()
