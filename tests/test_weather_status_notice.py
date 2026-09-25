"""天气来源提示测试，确保用户和历史记录都能看到数据可信度。"""

from src.core.rag_agent import RagService


def test_realtime_weather_notice_is_persistable():
    answer = RagService._attach_weather_notice(
        "建议穿薄外套。",
        {"status": "success", "source": "qweather", "message": ""},
    )

    assert answer.startswith("🌤️ 天气说明：本次已使用和风天气实时数据。")
    assert "建议穿薄外套" in answer


def test_degraded_weather_notice_does_not_claim_realtime_data():
    answer = RagService._attach_weather_notice(
        "建议按季节搭配。",
        {"status": "degraded", "source": "season_fallback", "message": ""},
    )

    assert "调用失败" in answer
    assert "未使用实时天气数据" in answer


def test_unrelated_answer_has_no_weather_notice():
    answer = RagService._attach_weather_notice(
        "羊毛衫建议冷水轻柔洗涤。",
        {"status": "not_called", "source": "none", "message": ""},
    )

    assert answer == "羊毛衫建议冷水轻柔洗涤。"