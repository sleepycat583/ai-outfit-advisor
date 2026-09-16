"""测试 RagService 与 WeatherService 的集成"""
import sys
import os

# 确保能导入项目模块
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from rag import RagService

def test_rag_weather_integration():
    """测试 RagService 是否正确初始化 WeatherService"""
    print("=" * 60)
    print("测试 RagService 与 WeatherService 集成")
    print("=" * 60)

    try:
        # 初始化 RagService（会自动初始化 WeatherService）
        print("\n1. 初始化 RagService...")
        rag = RagService(user_id="test_user")

        # 检查 weather_service 是否存在
        assert hasattr(rag, 'weather_service'), "RagService 缺少 weather_service 属性"
        print("   ✅ weather_service 属性已初始化")

        # 测试 _weather_search 方法（Agent 工具调用的入口）
        print("\n2. 测试 _weather_search() 方法...")
        result = rag._weather_search("武陟")
        print(f"   结果: {result}")
        assert isinstance(result, str), "_weather_search 应该返回字符串"
        assert "武陟" in result or "系统提示" in result, "返回结果应包含城市名或兜底文案"
        print("   ✅ _weather_search() 正常工作")

        print("\n" + "=" * 60)
        print("✅ 所有集成测试通过！")
        print("=" * 60)

    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    test_rag_weather_integration()
