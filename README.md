V2.1 — 基于多模态大模型 + 状态过滤算法的“智能衣橱”与“7天不重样”个性化穿搭推荐系统

一个面向大学生群体的智能穿搭决策与衣橱管理助手。融合 Qwen3-max、多模态大模型 (Qwen-VL)、RAG 本地知识库 (Chroma) 与 Agent 联网搜索 (DuckDuckGo)，以"顶尖私人穿搭主理人"人设，提供图片识衣、数字衣橱、盘活闲置、以及 7 天不重样周计划的完整 OOTD 解决方案。

✨ 核心亮点

引擎/模块

核心能力

🧠 Agent 联网决策

自主调用 DuckDuckGo 实时搜索天气、流行趋势，结合 LangChain 全生命周期 Callback 系统实现终端透明日志

📚 RAG 本地知识库

基于 Chroma 向量数据库，覆盖洗护养护、尺码推荐、颜色搭配三大领域，支持 .txt 文档一键上传与 MD5 去重

📸 多模态智能识衣

支持上传衣服照片，利用 VLM 大模型自动提取单品品类、细分颜色、面料材质、适用季节并完成结构化输出

👗 状态过滤周计划

引入“洗涤限制状态机”算法，按天循环过滤并剔除已消耗单品，100% 避免 7 天穿搭推荐连续重复，科学盘活闲置衣物

🛡️ 自愈解析网

独创正则表达式剥离与安全降级兜底技术，无惧多模态大模型 Markdown 格式杂音，确保系统永不崩溃

<img width="2497" height="1285" alt="image" src="https://github.com/user-attachments/assets/6c475190-21c4-42d4-9a05-5647bd56b010" />

<img width="2492" height="1287" alt="image" src="https://github.com/user-attachments/assets/5afd1b1c-692a-4a1e-a73d-d0114c1710b1" />



🏗️ 系统流程架构
```
[用户上传衣服照片] ──► [Pillow 图像压缩] ──► [VLM (qwen-vl-max)] 
                                                  │
                                                  ▼ (结构化标签)
[数字衣橱卡片] ◄── [文件锁安全写入] ◄── [正则清洗 & 兜底校验]
      │
      ├─► 📅 生成本周穿搭计划
      │       │
      │       ├─► [1. 联网查询本周天气趋势]
      │       ├─► [2. 检索色彩搭配 & 身型修饰 RAG 知识库]
      │       └─► [3. 7天状态过滤循环 (逐天扣减已穿单品)]
      ▼
[磨砂玻璃周计划卡片 & 60-30-10 黄金配色诊断]


📂 项目结构

ai-outfit-advisor/
├── app_qa.py                   # 主入口：多模态穿搭问答 & 智能衣橱管理（Streamlit UI）
├── app_file_uploader.py        # 知识库管理：.txt 文档上传与向量化
├── wardrobe_service.py         # 核心服务：图片压缩、多模态识衣、衣橱 CRUD 与正则安全解析
├── rag.py                      # RAG 核心：Agent 构建、实时天气、7天状态过滤推荐算法
├── history.py                  # 会话历史：并发安全文件持久化读写
├── vector_store_service.py     # 向量检索服务封装
├── knowledge_base.py           # 知识库引擎：Chroma + MD5 去重
├── config_data.py              # 集中配置：模型名称、切分参数、衣橱与数据库路径
├── requirements.txt            # Python 依赖清单 (新增 Pillow 依赖)
├── .env.example                # 环境变量配置模板
├── chat_history/               # [已忽略] 用户本地会话历史 (JSON)
├── data/
│   ├── chroma/                 # [已忽略] Chroma 向量库持久化目录
│   └── wardrobe.json           # [已忽略] 本地数字衣橱数据库
└── 穿搭知识库素材/              # 包含洗涤养护、大厂面试、体型避坑、颜色选择等素材 ```


📦 快速开始

安装依赖

git clone [https://github.com/sleepycat583/ai-outfit-advisor.git](https://github.com/sleepycat583/ai-outfit-advisor.git)
cd ai-outfit-advisor
pip install -r requirements.txt


配置环境变量

将项目根目录下的 .env.example 复制并重命名为 .env。

填入你的阿里云 API 密钥：

DASHSCOPE_API_KEY="your-api-key"


启动服务

# 启动主应用 (问答端 + 智能衣橱端)
streamlit run app_qa.py

# 启动知识库管理端
streamlit run app_file_uploader.py


📝 迭代日志 (Changelog)

V2.1 全新升级

| 引擎/模块 | 核心能力 (Agent + 业务状态机) |
| :--- | :--- |
| 🧠 **多维上下文动态 Agent** | 不再是盲目的天气搜索。系统会动态捕获前端用户的**城市位置**与**真实物理时间（推演未来7天）**，精准注入 Prompt，实现 100% 准确的属地化天气穿搭决策。 |
| ⚙️ **基于真实物理的洗涤状态机** | 告别粗暴的随机推荐。引入细粒度的单品状态流转算法：**内搭穿1次冷却3天、下装穿2次大洗...** AI 必须在“冷却可用池”中做搭配，完美模拟现实衣橱盘活逻辑。 |
| 📸 **多模态细粒度识衣矩阵** | 升级 VLM（Qwen-VL-Max）提示词工程，支持单张全身照**一次性拆解出上装、下装、鞋履多个实体**，配合前端多实例表单，实现数字衣橱的极速录入。 |
| 🎨 **结构化输出与沉浸式 UI** | 利用 Few-Shot 强约束 LLM 稳定输出包含单品 ID 的 JSON 结构。前端采用 Streamlit 最新的 `st.popover` 气泡交互，实现文字计划与实物图片的**所见即所得**。 |
| 🛡️ **高鲁棒性自愈解析网** | 独创正则表达式剥离与安全降级兜底技术，无惧多模态大模型 Markdown 格式杂音，确保系统永不崩溃。 |

V2.0 

多模态识衣入库：集成 qwen-vl-max 视觉理解，一键上传并录入你的专属“数字衣橱”。

7天不重样周计划：基于状态剔除算法，生成 7 天 OOTD，标注【自有/购入】，实现闲置衣物完美盘活。

高鲁棒性自愈网：在 wardrobe_service.py 引入正则拦截器，完美兼容大模型输出的 markdown JSON 干扰。

多端安全文件锁：引入 msvcrt/fcntl 读写锁，保障 wardrobe.json 数据库的高并发写入安全。

V1.2

集成 DuckDuckGo Agent 实时联网天气检索。

侧边栏用户穿搭档案（性别/风格/身高体重）动态 System Prompt 注入。

会话历史并发安全与 Streamlit 打字机流式渲染。

Made with LangChain + Streamlit + Qwen-VL + ❤️
