"""天气服务位置解析测试，覆盖本地映射、GeoAPI 兜底和异常响应。"""

from unittest.mock import Mock, patch

from src.services.weather import WeatherService


def make_service() -> WeatherService:
    """创建带测试 API Key 的天气服务，避免测试依赖本机环境变量。"""
    with patch.dict("os.environ", {"QWEATHER_API_KEY": "test-key"}, clear=False):
        service = WeatherService()
    return service


def test_local_city_mapping_does_not_call_geo_api():
    service = make_service()

    with patch("src.services.weather.requests.get") as get:
        assert service.get_location_id("北京市") == "101010100"

    get.assert_not_called()


def test_unknown_city_uses_geo_api_and_caches_result():
    service = make_service()
    response = Mock(status_code=200)
    response.json.return_value = {
        "code": "200",
        "location": [
            {
                "id": "101320101",
                "name": "海门",
                "adm2": "南通",
                "adm1": "江苏省",
                "country": "中国",
                "rank": "35",
            }
        ],
    }

    with patch("src.services.weather.requests.get", return_value=response) as get:
        assert service.get_location_id("海门市") == "101320101"
        assert service.get_location_id("海门市") == "101320101"

    get.assert_called_once()
    assert service.location_cache["海门"]["locations"][0]["adm1"] == "江苏省"


def test_geo_api_malformed_response_returns_none():
    service = make_service()
    response = Mock(status_code=502)
    response.json.side_effect = ValueError("not json")

    with patch("src.services.weather.requests.get", return_value=response):
        assert service.get_location_id("不存在的地区") is None


def test_weather_403_sets_degraded_status_without_claiming_realtime_data():
    service = make_service()
    response = Mock(status_code=403)
    response.json.return_value = {"code": "403"}

    with patch("src.services.weather.requests.get", return_value=response):
        result = service.get_current_weather("郑州")

    assert isinstance(result, str)
    assert "暂不可用" in result
    status = service.get_last_status()
    assert status["status"] == "degraded"
    assert status["source"] == "season_fallback"
    assert "HTTP 403" in status["message"]
    assert "实时天气" in status["message"]


def test_weather_timeout_sets_degraded_status():
    service = make_service()

    with patch(
        "src.services.weather.requests.get",
        side_effect=__import__("requests").RequestException("timeout"),
    ):
        result = service.get_current_weather("郑州")

    assert isinstance(result, str)
    assert service.get_last_status()["status"] == "degraded"
