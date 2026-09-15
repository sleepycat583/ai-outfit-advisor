-- 天气缓存表
CREATE TABLE IF NOT EXISTS weather_cache (
    id SERIAL PRIMARY KEY,
    city TEXT NOT NULL,           -- 城市名称
    date DATE NOT NULL,            -- 日期（YYYY-MM-DD）
    data_type TEXT NOT NULL,       -- "now" 或 "forecast"
    weather_data JSONB NOT NULL,   -- 结构化天气数据
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(city, date, data_type)  -- 唯一约束：同城市同日期同类型只存一条
);

-- 索引优化：按城市+日期查询
CREATE INDEX IF NOT EXISTS idx_weather_cache_lookup ON weather_cache(city, date, data_type);

-- 索引优化：按更新时间清理过期记录
CREATE INDEX IF NOT EXISTS idx_weather_cache_updated_at ON weather_cache(updated_at);

-- 添加注释
COMMENT ON TABLE weather_cache IS '天气数据缓存表，用于存储从和风天气 API 获取的天气数据';
COMMENT ON COLUMN weather_cache.city IS '城市名称（如"武陟"、"北京"）';
COMMENT ON COLUMN weather_cache.date IS '天气日期（YYYY-MM-DD 格式）';
COMMENT ON COLUMN weather_cache.data_type IS '数据类型："now"表示当前天气，"forecast"表示未来预报';
COMMENT ON COLUMN weather_cache.weather_data IS '结构化天气数据（JSON 格式），包含温度、天气现象、风力等字段';
COMMENT ON COLUMN weather_cache.updated_at IS '最后更新时间，用于判断缓存是否过期（24小时有效期）';
