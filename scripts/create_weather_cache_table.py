"""执行天气缓存表建表 SQL 的脚本。

使用方法：
    python scripts/create_weather_cache_table.py
"""

import sys
from pathlib import Path

# 添加项目根目录到 Python 路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from supabase_config import get_supabase_client


def main():
    """执行建表 SQL。"""
    print("=" * 60)
    print("创建 weather_cache 表")
    print("=" * 60)

    # 读取 SQL 文件
    sql_file = project_root / "migrations" / "001_create_weather_cache.sql"
    if not sql_file.exists():
        print(f"✗ SQL 文件不存在: {sql_file}")
        return False

    with open(sql_file, "r", encoding="utf-8") as f:
        sql = f.read()

    print(f"\n读取 SQL 文件: {sql_file.name}")
    print(f"SQL 内容预览:\n{sql[:200]}...\n")

    # 获取 Supabase 客户端
    try:
        client = get_supabase_client()
        print("✓ 成功连接到 Supabase\n")
    except Exception as exc:
        print(f"✗ 连接 Supabase 失败: {exc}")
        return False

    # 执行 SQL（Supabase Python 客户端不支持直接执行 DDL，需要通过 postgrest 或手动在 SQL Editor 执行）
    print("=" * 60)
    print("【注意】Supabase Python 客户端不支持直接执行 DDL 语句")
    print("请手动执行以下步骤：")
    print("=" * 60)
    print("\n1. 打开 Supabase Dashboard: https://supabase.com/dashboard")
    print("2. 选择你的项目")
    print("3. 点击左侧菜单 'SQL Editor'")
    print("4. 点击 'New query'")
    print(f"5. 复制粘贴以下 SQL 内容:\n")
    print("-" * 60)
    print(sql)
    print("-" * 60)
    print("\n6. 点击 'Run' 按钮执行")
    print("\n执行成功后，重新运行测试脚本即可。")
    print("=" * 60)

    return True


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
