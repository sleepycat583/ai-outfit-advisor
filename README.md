👗 AI 智能穿搭顾问 (AI Outfit Advisor)

这是一个专为大学生群体打造的个性化智能穿搭推荐助手。基于大语言模型与 RAG（检索增强生成）技术，能够根据用户的性别、偏好风格、体型特征，结合本地穿搭知识库，提供针对“早八”、“面试”、“约会”等不同场景的穿搭建议。

💡 核心亮点

千人千面: 结合用户特征（性别/体型/风格）进行个性化推荐。

场景驱动: 覆盖大学生高频场景（面试、早八、约会、运动）。

知识库增强 (RAG): 融合专业洗护、尺码指南，拒绝 AI 胡说八道。

🛠️ 技术栈

前端交互: Streamlit

AI 核心框架: LangChain

向量数据库: Chroma

大模型服务: 阿里云 DashScope (Qwen3-max 对话 + Text-Embedding-v4)

🚀 版本记录 (Changelog)

v1.0.0 (当前版本) - 基础框架与体验升级

✨ 新特性 (Features):

统一化可视化交互 (UI重构): 废弃原始割裂的双文件模式，将“知识库上传后台”与“智能问答前台”整合为单一 Web 页面 (app.py)。

用户画像控制面板: 侧边栏新增“我的穿搭档案”，支持用户自主设置性别、偏好风格、身高体重信息。

动态会话隔离: 引入 UUID 机制，彻底解决多用户/多窗口共用 Session 导致的聊天记录冲突问题。

隐式调试模式: 优化界面，将 Session ID 等技术信息折叠隐藏，提升产品可用性与美观度。

文档极速学习: 支持 .txt 格式知识库的本地解析、切分与向量化存储，具备基于 MD5 的防重复上传机制。

🚧 待办事项 (To-Do):

[ ] 将侧边栏的“用户档案”数据动态注入 RAG 的 System Prompt 中，实现真正的个性化问答。

[ ] 接入 Web Search 工具 (Agent)，使 AI 能够感知实时天气和网络流行趋势。

[ ] 在主界面增加高频问题的“一键发送”按钮。

📦 如何运行本项目

克隆仓库

git clone [https://github.com/你的用户名/ai-outfit-advisor.git](https://github.com/你的用户名/ai-outfit-advisor.git)
cd ai-outfit-advisor


安装依赖

pip install -r requirements.txt


配置环境
(说明：当前版本的大模型 API 调用可能需要在代码中配置，后续将优化为读取 .env 文件)

启动应用

streamlit run app.py
