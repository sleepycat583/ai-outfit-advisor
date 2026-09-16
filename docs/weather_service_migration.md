# 天气服务迁移指南

## 第一步：创建 Supabase 缓存表

由于 Supabase Python 客户端不支持直接执行 DDL 语句，需要手动在 Supabase Dashboard 中创建表。

### 操作步骤

1. 打开 Supabase Dashboard: https://supabase.com/dashboard
2. 选择你的项目
3. 点击左侧菜单 **SQL Editor**
4. 点击 **New query** 按钮
5. 复制 `migrations/001_create_weather_cache.sql` 的完整内容粘贴到编辑器
6. 点击 **Run** 按钮执行
7. 看到 "Success. No rows returned" 表示创建成功

### 验证表是否创建成功

在 SQL Editor 中执行：

```sql
SELECT * FROM weather_cache LIMIT 1;
```

如果没有报错（即使返回 0 行），说明表已创建成功。

## 第二步：配置和风天气 API Key

### 本地开发

在项目根目录的 `.env` 文件中添加（如果没有则创建）：

```bash
QWEATHER_API_KEY=dcc78739c0ae49c0a0a0f33be7534c2b
```

### Streamlit Cloud 部署

1. 打开 Streamlit Cloud 应用的 Settings 页面
2. 选择 **Secrets** 标签
3. 添加以下内容：

```toml
QWEATHER_API_KEY = "dcc78739c0ae49c0a0a0f33be7534c2b"
```

4. 点击 **Save** 保存

## 第三步：运行测试验证

```bash
python test_weather_service.py
```

预期输出应包含：
- ✓ 当前天气查询成功
- ✓ 未来 7 天预报成功
- ✓ 失败降级正常工作

## 城市容错说明

对于县级市或小城市（如"武陟"），如果和风天气 API 没有直接记录，系统会自动查询上级城市（如"焦作"）。

当前已配置的容错映射：
- 武陟 → 焦作
- 武陟县 → 焦作

如需添加更多城市容错，请修改 `weather_service.py` 中的 `CITY_FALLBACK_MAP`。

## 完成后

当测试全部通过后，即可提交代码并部署到 Streamlit Cloud。
