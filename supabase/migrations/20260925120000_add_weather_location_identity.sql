-- 为天气缓存增加稳定的和风天气 Location ID。
-- 迁移保持旧 city 唯一约束，便于旧版本应用平滑切换；新代码使用 location_id。
ALTER TABLE public.weather_cache
    ADD COLUMN IF NOT EXISTS location_id TEXT;

UPDATE public.weather_cache
SET location_id = CASE city
    WHEN '北京' THEN '101010100'
    WHEN '上海' THEN '101020100'
    WHEN '郑州' THEN '101180101'
    WHEN '焦作' THEN '101180500'
    WHEN '武陟' THEN '101180506'
    ELSE location_id
END
WHERE location_id IS NULL;

CREATE INDEX IF NOT EXISTS idx_weather_cache_location_lookup
    ON public.weather_cache(location_id, date, data_type);

CREATE UNIQUE INDEX IF NOT EXISTS weather_cache_location_date_type_key
    ON public.weather_cache(location_id, date, data_type);

COMMENT ON COLUMN public.weather_cache.location_id IS
    '和风天气 Location ID；新缓存使用该字段作为稳定地点标识';

-- users.profile 是历史上保存的 JSON 文本，只对已知城市回填，不猜测未知地点。
UPDATE public.users
SET profile = jsonb_set(
    profile::jsonb,
    '{location_id}',
    to_jsonb(CASE profile::jsonb->>'city'
        WHEN '北京' THEN '101010100'
        WHEN '北京市' THEN '101010100'
        WHEN '郑州' THEN '101180101'
        WHEN '郑州市' THEN '101180101'
        WHEN '焦作' THEN '101180500'
        WHEN '焦作市' THEN '101180500'
        WHEN '武陟' THEN '101180506'
        WHEN '武陟县' THEN '101180506'
        ELSE NULL
    END),
    true
)::text
WHERE COALESCE(profile, '{}') <> '{}'
  AND (profile::jsonb->>'city') IN (
      '北京', '北京市', '郑州', '郑州市', '焦作', '焦作市', '武陟', '武陟县'
  );