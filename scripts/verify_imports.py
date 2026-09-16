#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""验证重构后所有模块导入是否正常"""
import sys
import os
import traceback

# 将项目根目录添加到 Python 路径
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

def test_import(module_path: str, description: str):
    """测试单个模块导入"""
    try:
        __import__(module_path)
        print(f"[OK] {description:40s} - {module_path}")
        return True
    except Exception as e:
        print(f"[FAIL] {description:40s} - {module_path}")
        print(f"   Error: {e}")
        traceback.print_exc()
        return False

def main():
    """运行所有导入测试"""
    print("=" * 80)
    print("Starting module import verification...")
    print("=" * 80)

    tests = [
        # Config layer
        ("config.base", "Base config"),
        ("config.supabase", "Supabase config"),
        ("config", "Config unified entry"),

        # Data layer
        ("src.repositories.chat_history", "Chat history storage"),

        # Utils layer
        ("src.utils.image_cache", "Image cache utils"),

        # Service layer
        ("src.services.vector_store", "Vector store service"),
        ("src.services.user", "User service"),
        ("src.services.weather", "Weather service"),
        ("src.services.wardrobe", "Wardrobe service"),
        ("src.services.knowledge_base", "Knowledge base service"),

        # Core logic layer
        ("src.core.prompts", "Prompt templates"),
        ("src.core.rag_agent", "RAG agent"),

        # UI layer
        ("src.ui.pages.qa_page", "QA page"),
        ("src.ui.pages.knowledge_base_page", "Knowledge base page"),
    ]

    results = []
    for module_path, description in tests:
        success = test_import(module_path, description)
        results.append((module_path, success))

    print("\n" + "=" * 80)
    print("Test results summary")
    print("=" * 80)

    success_count = sum(1 for _, success in results if success)
    total_count = len(results)

    print(f"Passed: {success_count}/{total_count}")

    if success_count == total_count:
        print("\n[SUCCESS] All modules imported successfully! Refactoring verified.")
        return 0
    else:
        print(f"\n[WARNING] {total_count - success_count} module(s) failed to import. Please check errors above.")
        return 1

if __name__ == "__main__":
    sys.exit(main())
