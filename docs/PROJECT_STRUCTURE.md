# AI Outfit Advisor - 项目结构说明

## 📁 目录结构

```
ai-outfit-advisor/
├── app.py                          # Streamlit 主入口
├── config.py                       # 配置统一导出接口
├── requirements.txt
├── .env
├── README.md
│
├── src/                            # 核心业务代码
│   ├── ui/                         # UI 层（Streamlit 页面和组件）
│   │   ├── pages/
│   │   │   ├── qa_page.py         # 问答页面
│   │   │   └── knowledge_base_page.py  # 知识库管理页面
│   │   └── components/             # 可复用 UI 组件（待扩展）
│   │
│   ├── core/                       # 核心业务逻辑
│   │   ├── rag_agent.py           # RAG 智能体（核心对话引擎）
│   │   └── prompts.py             # Prompt 模板
│   │
│   ├── services/                   # 业务服务层
│   │   ├── user.py                # 用户服务
│   │   ├── wardrobe.py            # 衣橱管理服务
│   │   ├── knowledge_base.py      # 知识库服务
│   │   ├── weather.py             # 天气服务
│   │   └── vector_store.py        # 向量存储服务
│   │
│   ├── repositories/               # 数据持久化层
│   │   └── chat_history.py        # 聊天历史存储
│   │
│   └── utils/                      # 通用工具
│       └── image_cache.py         # 图片缓存工具
│
├── config/                         # 配置模块
│   ├── base.py                    # 基础配置（模型、向量库等）
│   └── supabase.py                # Supabase 连接配置
│
├── seeds/                          # 种子数据（知识库初始数据）
├── migrations/                     # 数据库迁移脚本
├── diagnostics/                    # 性能诊断工具
├── docs/                           # 项目文档
└── tests/                          # 测试代码
```

## 🔄 模块依赖关系

### 依赖层级（从上到下）
```
UI 层 (src/ui/)
    ↓ 依赖
核心逻辑层 (src/core/)
    ↓ 依赖
业务服务层 (src/services/)
    ↓ 依赖
数据持久化层 (src/repositories/)
    ↓ 依赖
配置层 (config/)
```

### 关键依赖链路
- **app.py** → `src.ui.pages.qa_page`, `src.services.user`
- **qa_page.py** → `src.core.rag_agent`, `src.services.wardrobe`, `src.services.vector_store`
- **rag_agent.py** → `src.services.weather`, `src.repositories.chat_history`, `src.core.prompts`
- **所有服务** → `config.base`, `config.supabase`

## 🚀 启动方式

```bash
# 启动应用
streamlit run app.py

# 默认访问地址
http://localhost:8503
```

## 📝 重构变更日志

### 2026-09-16 重构完成
- ✅ 按职责划分模块（UI/Core/Services/Repositories）
- ✅ 统一配置管理（config 模块）
- ✅ 抽取可复用工具（image_cache）
- ✅ 更新所有导入路径
- ✅ 保持功能完全兼容

### 迁移映射表
| 原文件 | 新位置 |
|--------|--------|
| `app_main.py` | `app.py` |
| `app_qa.py` | `src/ui/pages/qa_page.py` |
| `app_file_uploader.py` | `src/ui/pages/knowledge_base_page.py` |
| `rag.py` | `src/core/rag_agent.py` |
| `prompts.py` | `src/core/prompts.py` |
| `user_service.py` | `src/services/user.py` |
| `wardrobe_service.py` | `src/services/wardrobe.py` |
| `knowledge_base.py` | `src/services/knowledge_base.py` |
| `weather_service.py` | `src/services/weather.py` |
| `vector_store_service.py` | `src/services/vector_store.py` |
| `history.py` | `src/repositories/chat_history.py` |
| `config_data.py` | `config/base.py` |
| `supabase_config.py` | `config/supabase.py` |

## 🎯 后续优化建议

1. **测试覆盖**：为核心服务（rag_agent, wardrobe, knowledge_base）编写单元测试
2. **依赖注入**：使用依赖注入模式管理服务实例
3. **日志系统**：统一使用 logging 模块替代 print()
4. **类型注解**：补充完整的类型提示，提升代码可维护性
5. **错误处理**：增强异常处理和用户友好的错误提示
