-- 天气缓存表
-- 用于持久化天气 API 查询结果，避免重复请求和降低失败率
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
COMMENT ON TABLE weather_cache IS '天气数据缓存表，24小时有效期';
COMMENT ON COLUMN weather_cache.city IS '城市名称，如"武陟"';
COMMENT ON COLUMN weather_cache.date IS '天气日期';
COMMENT ON COLUMN weather_cache.data_type IS '数据类型：now=当前天气，forecast=未来预报';
COMMENT ON COLUMN weather_cache.weather_data IS '天气结构化数据，JSON 格式存储';
