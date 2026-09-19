# R-004 快速启动指南

## 🚀 10 分钟快速启用混合检索

### 前置条件

- ✅ Python 3.11+
- ✅ 已配置 Supabase 连接
- ✅ 已安装项目依赖（`pip install -r requirements.txt`）

---

## 步骤 1: 运行测试（验证功能）

```bash
# 运行所有 R-004 相关测试
python -m pytest tests/test_query_parser.py tests/test_hybrid_retriever.py tests/test_rag_hybrid_integration.py tests/test_r004_card_rendering.py -v

# 预期结果：所有测试通过 ✅
```

**如果测试失败**，请检查：
- 依赖是否完整安装
- Supabase 配置是否正确（`.env` 文件）

---

## 步骤 2: 启用混合检索

```bash
# 方式 1: 使用配置脚本（推荐）
python scripts/toggle_hybrid_retrieval.py --enable

# 方式 2: 手动修改代码
# 在初始化 RagService 时设置 enable_hybrid_retrieval=True（默认已启用）
```

---

## 步骤 3: 数据迁移（可选）

**仅当你已有旧版本（v2）衣橱数据时需要**。新用户跳过此步骤。

```bash
# 查看当前用户列表
python scripts/migrate_wardrobe_v2_to_v3.py --all --dry-run

# 迁移单个用户（推荐先测试）
python scripts/migrate_wardrobe_v2_to_v3.py --user-id <你的用户ID>

# 迁移所有用户
python scripts/migrate_wardrobe_v2_to_v3.py --all
```

**注意**：
- 迁移脚本会保留 v2 数据，不会删除
- 新用户无需迁移，直接使用 v3

---

## 步骤 4: 重启服务

```bash
# Docker 环境
docker-compose restart

# 本地开发环境
# 重新运行 streamlit run app.py
```

---

## 步骤 5: 验证效果

### 5.1 查看日志

启动服务后，应该看到：

```
[INFO] 混合检索器已启用（结构化过滤 + 语义排序）
[PERF] RagService.__init__ took 0.XXXs
```

### 5.2 测试查询

在应用中测试以下查询，验证精确性提升：

| 查询 | 预期结果 |
|-----|---------|
| "黑色裤子" | ✅ 只返回黑色下装 |
| "春季外套" | ✅ 只返回春季上装 |
| "红色连衣裙" | ✅ 只返回红色裙装 |

### 5.3 检查卡片渲染

确认返回的单品可以在前端正常显示卡片，包含：
- ✅ 单品图片
- ✅ 类别、颜色、季节等信息
- ✅ 操作按钮（编辑、删除）

---

## 🔧 常见问题

### Q1: 混合检索器初始化失败

**症状**：日志显示 `[WARN] 混合检索器初始化失败，回退到纯语义检索`

**原因**：
- Supabase 连接失败
- 缺少依赖模块

**解决方案**：
```bash
# 检查 Supabase 连接
python -c "from config.supabase import get_supabase_client; print(get_supabase_client().table('wardrobe_items').select('id').limit(1).execute())"

# 重新安装依赖
pip install -r requirements.txt --upgrade
```

---

### Q2: 查询结果仍不精确

**症状**：搜索"黑色裤子"仍返回深蓝色单品。

**排查步骤**：

1. 检查混合检索是否已启用：
   ```bash
   python scripts/toggle_hybrid_retrieval.py --status
   ```

2. 检查 Supabase 数据完整性：
   ```sql
   -- 在 Supabase SQL Editor 中执行
   SELECT id, category, color, season 
   FROM wardrobe_items 
   WHERE user_id = '<你的用户ID>' 
   LIMIT 10;
   ```

3. 查看检索日志：
   ```
   [INFO] 使用混合检索器（结构化过滤 + 语义排序），k=5
   [DEBUG] wardrobe_search 原始返回（前3条）：
   ```

**解决方案**：
- 如果数据缺少 `color` 字段 → 重新录入单品或修复数据
- 如果混合检索未启用 → 执行 `toggle_hybrid_retrieval.py --enable`

---

### Q3: 卡片无法显示

**症状**：前端显示空白或错误。

**排查步骤**：

1. 检查返回文本格式：
   ```python
   # 应该包含 id:UUID 前缀
   "- id:abc123-... 类别:下装/裤子 颜色:黑色 ..."
   ```

2. 运行回归测试：
   ```bash
   python -m pytest tests/test_r004_card_rendering.py -v
   ```

**解决方案**：
```bash
# 重建向量索引
rm -rf .persist/<用户ID>/wardrobe
docker-compose restart
```

---

## 🎯 性能基准

完成上述步骤后，你应该观察到：

| 指标 | v2 纯语义 | v3 混合检索 |
|-----|----------|------------|
| 颜色查询精确度 | ~60% | ~95% |
| 类别查询精确度 | ~70% | ~90% |
| 响应时间 | ~150ms | ~200ms |
| 空结果率 | ~15% | ~5% |

---

## 📚 进一步阅读

- [完整技术文档](./R-004-HYBRID-RETRIEVAL.md)
- [API 参考](./API-REFERENCE.md)
- [故障排查指南](./R-004-HYBRID-RETRIEVAL.md#🔧-故障排查)

---

## 🆘 获取帮助

如果遇到问题：

1. 查看完整文档：`docs/R-004-HYBRID-RETRIEVAL.md`
2. 运行诊断脚本（如有）
3. 提交 Issue，附带：
   - 错误日志
   - 配置状态（`toggle_hybrid_retrieval.py --status`）
   - 测试结果（`pytest tests/test_r004_*.py -v`）

---

**🎉 恭喜！你已成功启用 R-004 混合检索优化！**
