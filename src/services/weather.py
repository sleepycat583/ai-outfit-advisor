"""
WeatherService: 和风天气 API 封装
负责天气数据查询和 Supabase 缓存管理
"""

import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
import requests
from supabase import Client
from dotenv import load_dotenv

# 加载 .env 文件
load_dotenv()

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
        self.supabase = supabase_client
        self.cache_ttl_hours = 24  # 缓存有效期 24 小时

        # 尝试获取 API Key，失败时标记为不可用
        self.api_key = self._get_api_key()
        if self.api_key:
            self.api_host = "kh359hq4fh.re.qweatherapi.com"  # 专属 API Host
            self.available = True
        else:
            self.api_host = ""
            self.available = False
            print(
                "[WARN] 和风天气服务初始化失败：未配置 API Key。"
                "天气相关功能将使用季节常识兜底，穿搭建议的准确性可能下降。"
                "请在 Streamlit Secrets 或 .env 中配置 QWEATHER_API_KEY。",
                flush=True
            )

    def _get_api_key(self) -> Optional[str]:
        """从环境变量获取 API Key，失败返回 None 而不是 raise"""
        api_key = os.getenv("QWEATHER_API_KEY")
        if not api_key:
            return None
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
        self, city: str, date: str, data_type: str, ignore_ttl: bool = False
    ) -> Optional[Dict[str, Any]]:
        """
        从 Supabase 缓存表读取天气数据

        Args:
            city: 城市名称
            date: 日期 (YYYY-MM-DD)
            data_type: "now" 或 "forecast"
            ignore_ttl: 是否忽略 TTL（用于降级场景读取过期缓存）

        Returns:
            缓存的天气数据，如果不存在或过期返回 None
        """
        if not self.supabase:
            return None

        try:
            query = (
                self.supabase.table("weather_cache")
                .select("weather_data, updated_at")
                .eq("city", city)
                .eq("date", date)
                .eq("data_type", data_type)
            )

            # 正常场景：只读未过期的
            if not ignore_ttl:
                expire_time = datetime.now() - timedelta(hours=self.cache_ttl_hours)
                query = query.gte("updated_at", expire_time.isoformat())

            response = query.execute()

            if response.data and len(response.data) > 0:
                cache_label = "过期缓存" if ignore_ttl else "缓存"
                print(
                    f"[INFO] 天气{cache_label}命中: {city} {date} {data_type}", flush=True
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

    def _get_current_season(self) -> str:
        """根据当前月份返回季节"""
        month = datetime.now().month
        if month in (3, 4, 5):
            return "春季"
        elif month in (6, 7, 8):
            return "夏季"
        elif month in (9, 10, 11):
            return "秋季"
        else:
            return "冬季"

    def _get_season_fallback_text(self, city: str, data_type: str) -> str:
        """
        生成基于季节常识的兜底文案

        Args:
            city: 城市名称
            data_type: "now" 或 "forecast"

        Returns:
            兜底文案字符串
        """
        season = self._get_current_season()
        season_hints = {
            "春季": "气温适中，早晚温差较大，建议准备薄外套",
            "夏季": "气温较高，注意防晒和透气性",
            "秋季": "气温逐渐转凉，建议叠穿搭配",
            "冬季": "气温较低，注意保暖",
        }
        hint = season_hints.get(season, "")

        if data_type == "now":
            return f"{city} 当前天气数据暂不可用（系统降级：按{season}常识推荐）。{hint}"
        else:  # forecast
            return f"{city} 未来一周天气数据暂不可用（系统降级：按{season}常识推荐）。{hint}"

    def get_current_weather(self, city: str) -> Dict[str, Any] | str:
        """
        获取当前天气（优先从缓存读取）

        Args:
            city: 城市名称

        Returns:
            成功：结构化天气数据 dict
            降级：兜底文案 str
        """
        # 降级路径 1：服务根本不可用（没 key）
        if not self.available:
            return self._get_season_fallback_text(city, "now")

        location_id = self.get_location_id(city)
        if not location_id:
            season = self._get_current_season()
            return f"{city} 不在支持城市列表中（系统降级：按{season}常识推荐）"

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
                # API 返回错误码（401/403/429/其他业务错误）
                print(f"[WARN] 和风天气 API 返回错误: code={data.get('code', 'unknown')}, status={response.status_code}", flush=True)
                # 降级路径 2：尝试读过期缓存
                expired_cache = self._read_cache(city, today, "now", ignore_ttl=True)
                if expired_cache:
                    return expired_cache
                # 降级路径 3：季节兜底
                return self._get_season_fallback_text(city, "now")

        except requests.RequestException as e:
            # 网络错误、超时
            print(f"[WARN] 和风天气 API 请求失败: {e}", flush=True)
            # 降级路径 2：尝试读过期缓存
            expired_cache = self._read_cache(city, today, "now", ignore_ttl=True)
            if expired_cache:
                return expired_cache
            # 降级路径 3：季节兜底
            return self._get_season_fallback_text(city, "now")

    def get_forecast_7d(self, city: str) -> List[Dict[str, Any]] | str:
        """
        获取未来 7 天预报（优先从缓存读取）

        Args:
            city: 城市名称

        Returns:
            成功：7 天预报数据的 list
            降级：兜底文案 str
        """
        # 降级路径 1：服务根本不可用（没 key）
        if not self.available:
            return self._get_season_fallback_text(city, "forecast")

        location_id = self.get_location_id(city)
        if not location_id:
            season = self._get_current_season()
            return f"{city} 不在支持城市列表中（系统降级：按{season}常识推荐）"

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
                # API 返回错误码
                print(f"[WARN] 和风天气 API 返回错误: code={data.get('code', 'unknown')}, status={response.status_code}", flush=True)
                # 降级路径 2：尝试读过期缓存
                expired_cache = self._read_cache(city, today, "forecast", ignore_ttl=True)
                if expired_cache:
                    return expired_cache
                # 降级路径 3：季节兜底
                return self._get_season_fallback_text(city, "forecast")

        except requests.RequestException as e:
            # 网络错误、超时
            print(f"[WARN] 和风天气 API 请求失败: {e}", flush=True)
            # 降级路径 2：尝试读过期缓存
            expired_cache = self._read_cache(city, today, "forecast", ignore_ttl=True)
            if expired_cache:
                return expired_cache
            # 降级路径 3：季节兜底
            return self._get_season_fallback_text(city, "forecast")

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
