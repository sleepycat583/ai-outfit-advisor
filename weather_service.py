"""
WeatherService: 和风天气 API 封装
负责天气数据查询和 Supabase 缓存管理
"""

import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
import requests
from supabase import Client

# 常用城市 location id 映射表
# 数据来源：和风天气官方城市列表
CITY_LOCATION_MAP = {
    # 直辖市
    "北京": "101010100",
    "上海": "101020100",
    "天津": "101030100",
    "重庆": "101040100",

    # 省会城市
    "郑州": "101180101",
    "武汉": "101200101",
    "长沙": "101250101",
    "广州": "101280101",
    "南京": "101190101",
    "杭州": "101210101",
    "济南": "101120101",
    "成都": "101270101",
    "西安": "101110101",
    "沈阳": "101070101",
    "哈尔滨": "101050101",
    "长春": "101060101",
    "石家庄": "101090101",
    "太原": "101100101",
    "呼和浩特": "101080101",
    "南昌": "101240101",
    "福州": "101230101",
    "海口": "101310101",
    "贵阳": "101260101",
    "昆明": "101290101",
    "兰州": "101160101",
    "西宁": "101150101",
    "银川": "101170101",
    "乌鲁木齐": "101130101",
    "拉萨": "101140101",
    "南宁": "101300101",

    # 热门城市
    "深圳": "101280601",
    "苏州": "101190401",
    "青岛": "101120201",
    "厦门": "101230201",
    "大连": "101070201",
    "宁波": "101210401",

    # 河南省城市（项目用户主要区域）
    "焦作": "101180500",
    "武陟": "101180506",  # 焦作市武陟县
    "洛阳": "101180901",
    "开封": "101180801",
    "安阳": "101180301",
    "新乡": "101180401",
    "许昌": "101181001",
    "平顶山": "101180201",
    "信阳": "101181501",
    "南阳": "101181301",
    "周口": "101181701",
    "商丘": "101181601",
    "驻马店": "101181401",
    "漯河": "101181101",
    "鹤壁": "101180601",
    "濮阳": "101180701",
    "三门峡": "101181201",
    "济源": "101180508",
}


class WeatherService:
    """和风天气服务封装"""

    def __init__(self, supabase_client: Optional[Client] = None):
        """
        初始化天气服务

        Args:
            supabase_client: Supabase 客户端实例（用于缓存）
        """
        self.api_key = self._get_api_key()
        self.api_host = "kh359hq4fh.re.qweatherapi.com"  # 专属 API Host
        self.supabase = supabase_client
        self.cache_ttl_hours = 24  # 缓存有效期 24 小时

    def _get_api_key(self) -> str:
        """从环境变量获取 API Key"""
        api_key = os.getenv("QWEATHER_API_KEY")
        if not api_key:
            raise ValueError(
                "未找到和风天气 API Key。请在 .env 文件或环境变量中设置 QWEATHER_API_KEY"
            )
        return api_key

    def get_location_id(self, city_name: str) -> Optional[str]:
        """
        将城市名转换为 location id

        Args:
            city_name: 城市名称

        Returns:
            location id，如果城市不在映射表中返回 None
        """
        # 去除可能的"市"、"县"后缀再查询
        city_clean = city_name.replace("市", "").replace("县", "").strip()
        return CITY_LOCATION_MAP.get(city_clean)

    def _read_cache(
        self, city: str, date: str, data_type: str
    ) -> Optional[Dict[str, Any]]:
        """
        从 Supabase 缓存表读取天气数据

        Args:
            city: 城市名称
            date: 日期 (YYYY-MM-DD)
            data_type: "now" 或 "forecast"

        Returns:
            缓存的天气数据，如果不存在或过期返回 None
        """
        if not self.supabase:
            return None

        try:
            # 计算过期时间
            expire_time = datetime.now() - timedelta(hours=self.cache_ttl_hours)

            response = (
                self.supabase.table("weather_cache")
                .select("weather_data, updated_at")
                .eq("city", city)
                .eq("date", date)
                .eq("data_type", data_type)
                .gte("updated_at", expire_time.isoformat())
                .execute()
            )

            if response.data and len(response.data) > 0:
                print(
                    f"[INFO] 天气缓存命中: {city} {date} {data_type}", flush=True
                )
                return response.data[0]["weather_data"]

        except Exception as e:
            print(f"[WARN] 读取天气缓存失败: {e}", flush=True)

        return None

    def _write_cache(
        self, city: str, date: str, data_type: str, weather_data: Dict[str, Any]
    ) -> None:
        """
        将天气数据写入 Supabase 缓存表

        Args:
            city: 城市名称
            date: 日期 (YYYY-MM-DD)
            data_type: "now" 或 "forecast"
            weather_data: 天气数据
        """
        if not self.supabase:
            return

        try:
            # 使用 UPSERT 语义：存在则更新，不存在则插入
            self.supabase.table("weather_cache").upsert(
                {
                    "city": city,
                    "date": date,
                    "data_type": data_type,
                    "weather_data": weather_data,
                    "updated_at": datetime.now().isoformat(),
                },
                on_conflict="city,date,data_type",
            ).execute()

            print(f"[INFO] 天气数据已缓存: {city} {date} {data_type}", flush=True)

        except Exception as e:
            print(f"[WARN] 写入天气缓存失败: {e}", flush=True)

    def get_current_weather(self, city: str) -> Dict[str, Any]:
        """
        获取当前天气（优先从缓存读取）

        Args:
            city: 城市名称

        Returns:
            结构化天气数据 dict

        Raises:
            ValueError: 城市不支持
            RuntimeError: API 请求失败
        """
        location_id = self.get_location_id(city)
        if not location_id:
            raise ValueError(f"不支持的城市: {city}。请联系管理员添加该城市。")

        today = datetime.now().strftime("%Y-%m-%d")

        # 1. 尝试从缓存读取
        cached_data = self._read_cache(city, today, "now")
        if cached_data:
            return cached_data

        # 2. 缓存未命中，请求 API
        url = f"https://{self.api_host}/v7/weather/now"
        params = {"location": location_id}
        headers = {"X-QW-Api-Key": self.api_key}

        try:
            response = requests.get(url, params=params, headers=headers, timeout=10)
            data = response.json()

            if response.status_code == 200 and data.get("code") == "200":
                now = data["now"]

                # 构造结构化数据
                weather_data = {
                    "city": city,
                    "date": today,
                    "temp": now["temp"],
                    "feels_like": now["feelsLike"],
                    "text": now["text"],
                    "wind_dir": now["windDir"],
                    "wind_scale": now["windScale"],
                    "humidity": now["humidity"],
                    "data_type": "now",
                }

                # 3. 写入缓存
                self._write_cache(city, today, "now", weather_data)

                return weather_data
            else:
                raise RuntimeError(
                    f"和风天气 API 返回错误: {data.get('code', 'unknown')}"
                )

        except requests.RequestException as e:
            raise RuntimeError(f"和风天气 API 请求失败: {e}")

    def get_forecast_7d(self, city: str) -> List[Dict[str, Any]]:
        """
        获取未来 7 天预报（优先从缓存读取）

        Args:
            city: 城市名称

        Returns:
            7 天预报数据的 list

        Raises:
            ValueError: 城市不支持
            RuntimeError: API 请求失败
        """
        location_id = self.get_location_id(city)
        if not location_id:
            raise ValueError(f"不支持的城市: {city}。请联系管理员添加该城市。")

        today = datetime.now().strftime("%Y-%m-%d")

        # 1. 尝试从缓存读取
        cached_data = self._read_cache(city, today, "forecast")
        if cached_data:
            return cached_data

        # 2. 缓存未命中，请求 API
        url = f"https://{self.api_host}/v7/weather/7d"
        params = {"location": location_id}
        headers = {"X-QW-Api-Key": self.api_key}

        try:
            response = requests.get(url, params=params, headers=headers, timeout=10)
            data = response.json()

            if response.status_code == 200 and data.get("code") == "200":
                daily = data["daily"]

                # 构造结构化数据列表
                forecast_data = []
                for day in daily:
                    forecast_data.append({
                        "city": city,
                        "date": day["fxDate"],
                        "temp_max": day["tempMax"],
                        "temp_min": day["tempMin"],
                        "text_day": day["textDay"],
                        "text_night": day["textNight"],
                        "wind_dir_day": day["windDirDay"],
                        "wind_scale_day": day["windScaleDay"],
                        "humidity": day["humidity"],
                        "precip": day["precip"],
                        "data_type": "forecast",
                    })

                # 3. 写入缓存
                self._write_cache(city, today, "forecast", forecast_data)

                return forecast_data
            else:
                raise RuntimeError(
                    f"和风天气 API 返回错误: {data.get('code', 'unknown')}"
                )

        except requests.RequestException as e:
            raise RuntimeError(f"和风天气 API 请求失败: {e}")

    def format_current_weather_text(self, weather_data: Dict[str, Any]) -> str:
        """
        将结构化天气数据格式化为供 LLM 阅读的文本

        Args:
            weather_data: get_current_weather() 返回的数据

        Returns:
            格式化后的天气描述文本
        """
        return (
            f"{weather_data['city']} 当前天气：{weather_data['text']}，"
            f"气温 {weather_data['temp']}℃（体感 {weather_data['feels_like']}℃），"
            f"{weather_data['wind_dir']}{weather_data['wind_scale']}级，"
            f"湿度 {weather_data['humidity']}%"
        )

    def format_forecast_7d_text(
        self, forecast_data: List[Dict[str, Any]]
    ) -> str:
        """
        将 7 天预报格式化为供 LLM 阅读的文本

        Args:
            forecast_data: get_forecast_7d() 返回的数据

        Returns:
            格式化后的 7 天预报文本
        """
        lines = [f"{forecast_data[0]['city']} 未来 7 天天气预报："]

        for day in forecast_data:
            lines.append(
                f"· {day['date']}: {day['text_day']}转{day['text_night']}，"
                f"{day['temp_min']}~{day['temp_max']}℃，"
                f"{day['wind_dir_day']}{day['wind_scale_day']}，"
                f"降水量 {day['precip']}mm"
            )

        return "\n".join(lines)
