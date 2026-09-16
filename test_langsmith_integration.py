#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
LangSmith 集成测试脚本

用于验证 LangSmith 追踪功能是否正常工作。
运行此脚本后，可以在 https://smith.langchain.com/ 查看追踪记录。
"""

import os
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

def test_langsmith_connection():
    """测试 LangSmith 基础连接"""
    print("=" * 60)
    print("测试 1: LangSmith 基础连接")
    print("=" * 60)

    try:
        from langsmith import Client
        client = Client()
        print("✓ LangSmith 客户端初始化成功")
        print(f"  项目名称: {os.getenv('LANGCHAIN_PROJECT')}")
        print(f"  追踪开关: {os.getenv('LANGCHAIN_TRACING_V2')}")
        return True
    except Exception as e:
        print(f"✗ LangSmith 连接失败: {e}")
        return False


def test_langchain_tracing():
    """测试 LangChain 与 LangSmith 的集成追踪"""
    print("\n" + "=" * 60)
    print("测试 2: LangChain Agent 追踪")
    print("=" * 60)

    try:
        from langchain_community.chat_models.tongyi import ChatTongyi
        from langchain_core.messages import HumanMessage
        import config_data as config

        # 初始化模型
        model = ChatTongyi(model=config.chat_model_name)
        print(f"✓ 模型初始化成功: {config.chat_model_name}")

        # 发送测试消息
        message = HumanMessage(content="简单回复'收到'即可，这是一个测试消息")
        print("\n发送测试消息...")
        response = model.invoke([message])

        print(f"✓ 收到模型响应: {response.content[:50]}...")
        print("\n提示: 请访问 https://smith.langchain.com/ 查看此次调用的追踪记录")
        print(f"      项目名称: {os.getenv('LANGCHAIN_PROJECT')}")
        return True

    except Exception as e:
        print(f"✗ LangChain 追踪测试失败: {e}")
        return False


def test_agent_tools_tracing():
    """测试 Agent 工具调用的追踪"""
    print("\n" + "=" * 60)
    print("测试 3: Agent 工具调用追踪")
    print("=" * 60)

    try:
        from rag import RagService

        print("初始化 RagService...")
        rag_service = RagService(user_id="test_user")

        # 发送一个会触发工具调用的问题
        test_input = {
            "input": "羽绒服怎么洗涤保养？",
            "gender": "女生",
            "style": "日常休闲",
            "body": "",
            "city": "北京",
        }

        print("\n发送测试问题（会触发知识库检索）...")
        response = rag_service.invoke(test_input)

        print(f"✓ 收到 Agent 响应: {response[:80]}...")
        print("\n提示: 在 LangSmith 中可以看到:")
        print("      - Agent 的思考过程")
        print("      - 知识库检索工具的调用")
        print("      - 每个步骤的耗时和 Token 消耗")
        return True

    except Exception as e:
        print(f"✗ Agent 工具追踪测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """运行所有测试"""
    print("\n🔍 开始 LangSmith 集成测试\n")

    results = []

    # 测试 1: 基础连接
    results.append(("基础连接", test_langsmith_connection()))

    # 测试 2: LangChain 追踪
    if results[-1][1]:  # 只有连接成功才继续
        results.append(("LangChain 追踪", test_langchain_tracing()))

    # 测试 3: Agent 工具追踪（可选，较重）
    # results.append(("Agent 工具追踪", test_agent_tools_tracing()))

    # 输出总结
    print("\n" + "=" * 60)
    print("测试结果总结")
    print("=" * 60)
    for name, passed in results:
        status = "✓ 通过" if passed else "✗ 失败"
        print(f"{status} - {name}")

    all_passed = all(r[1] for r in results)
    if all_passed:
        print("\n🎉 所有测试通过！LangSmith 配置正确。")
        print(f"\n📊 访问 LangSmith 控制台: https://smith.langchain.com/")
        print(f"   项目名称: {os.getenv('LANGCHAIN_PROJECT')}")
    else:
        print("\n❌ 部分测试失败，请检查配置。")

    return all_passed


if __name__ == "__main__":
    main()
