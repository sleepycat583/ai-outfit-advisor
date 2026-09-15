-- 天气缓存表
-- 用于缓存和风天气 API 的返回结果，有效期 24 小时
-- 缓存键: (city, date, data_type) 三元组

CREATE TABLE IF NOT EXISTS weather_cache (
    id SERIAL PRIMARY KEY,
    city TEXT NOT NULL,                -- 城市名称（如 "武陟"）
    date DATE NOT NULL,                -- 日期（YYYY-MM-DD）
    data_type TEXT NOT NULL,           -- "now" (当前天气) 或 "forecast" (预报)
    weather_data JSONB NOT NULL,       -- 结构化天气数据（存储 WeatherData dict）
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(city, date, data_type)      -- 唯一约束：同城市同日期同类型只存一条
);

-- 索引优化：按城市+日期查询（最常用的查询模式）
CREATE INDEX IF NOT EXISTS idx_weather_cache_lookup
ON weather_cache(city, date, data_type);

-- 索引优化：按更新时间清理过期记录
CREATE INDEX IF NOT EXISTS idx_weather_cache_updated_at
ON weather_cache(updated_at);

-- 注释说明
COMMENT ON TABLE weather_cache IS '和风天气 API 缓存表，有效期 24 小时';
COMMENT ON COLUMN weather_cache.city IS '城市名称';
COMMENT ON COLUMN weather_cache.date IS '日期（YYYY-MM-DD）';
COMMENT ON COLUMN weather_cache.data_type IS '数据类型：now=当前天气, forecast=未来预报';
COMMENT ON COLUMN weather_cache.weather_data IS '结构化天气数据（JSONB 格式）';
COMMENT ON COLUMN weather_cache.updated_at IS '更新时间，用于判断缓存是否过期';
