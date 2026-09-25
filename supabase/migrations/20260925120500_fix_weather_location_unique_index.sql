-- 让 PostgREST upsert 可以通过 location_id,date,data_type 推断唯一索引。
DROP INDEX IF EXISTS public.weather_cache_location_date_type_key;

CREATE UNIQUE INDEX weather_cache_location_date_type_key
    ON public.weather_cache(location_id, date, data_type);