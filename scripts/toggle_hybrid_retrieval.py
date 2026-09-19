"""混合检索配置开关管理脚本。

用于快速启用/禁用混合检索功能，或在出现问题时快速回滚到纯语义检索。

使用方法：
    python scripts/toggle_hybrid_retrieval.py --status          # 查看当前状态
    python scripts/toggle_hybrid_retrieval.py --enable          # 启用混合检索
    python scripts/toggle_hybrid_retrieval.py --disable         # 禁用混合检索（回退到纯语义）
    python scripts/toggle_hybrid_retrieval.py --enable --no-filter  # 启用混合检索但禁用结构化过滤
"""

import os
import sys
import argparse
from pathlib import Path

# 添加项目根目录到 Python 路径
sys.path.insert(0, str(Path(__file__).parent.parent))


def get_env_file_path() -> Path:
    """获取 .env 文件路径。"""
    return Path(__file__).parent.parent / ".env"


def read_env_config() -> dict:
    """读取 .env 文件中的配置。"""
    env_file = get_env_file_path()
    if not env_file.exists():
        return {}

    config = {}
    with open(env_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, value = line.split("=", 1)
                config[key.strip()] = value.strip()

    return config


def write_env_config(config: dict) -> None:
    """写入配置到 .env 文件，保留注释和格式。"""
    env_file = get_env_file_path()

    if not env_file.exists():
        # 创建新文件
        with open(env_file, "w", encoding="utf-8") as f:
            f.write("# R-004 混合检索配置\n")
            for key, value in config.items():
                f.write(f"{key}={value}\n")
        return

    # 读取现有内容
    lines = []
    with open(env_file, "r", encoding="utf-8") as f:
        lines = f.readlines()

    # 更新或添加配置
    updated_keys = set()
    new_lines = []

    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            new_lines.append(line)
            continue

        if "=" in stripped:
            key = stripped.split("=", 1)[0].strip()
            if key in config:
                new_lines.append(f"{key}={config[key]}\n")
                updated_keys.add(key)
            else:
                new_lines.append(line)
        else:
            new_lines.append(line)

    # 添加未更新的新配置
    if updated_keys != set(config.keys()):
        new_lines.append("\n# R-004 混合检索配置\n")
        for key, value in config.items():
            if key not in updated_keys:
                new_lines.append(f"{key}={value}\n")

    # 写回文件
    with open(env_file, "w", encoding="utf-8") as f:
        f.writelines(new_lines)


def show_status():
    """显示当前混合检索配置状态。"""
    config = read_env_config()

    enable_hybrid = config.get("ENABLE_HYBRID_RETRIEVAL", "true").lower() == "true"
    enable_filter = config.get("ENABLE_STRUCTURAL_FILTER", "true").lower() == "true"

    print("\n" + "="*60)
    print("混合检索配置状态")
    print("="*60)
    print(f"混合检索: {'✅ 启用' if enable_hybrid else '❌ 禁用'}")
    print(f"结构化过滤: {'✅ 启用' if enable_filter else '❌ 禁用'}")
    print("="*60)

    if not enable_hybrid:
        print("\n[提示] 混合检索已禁用，系统使用纯语义检索（VectorWardrobeService）")
    elif not enable_filter:
        print("\n[提示] 混合检索已启用，但结构化过滤已禁用")
        print("       当前策略：纯语义排序，不进行颜色/类别/季节过滤")
    else:
        print("\n[提示] 混合检索已启用，使用结构化过滤 + 语义排序策略")

    print()


def enable_hybrid_retrieval(enable_filter: bool = True):
    """启用混合检索。"""
    config = {
        "ENABLE_HYBRID_RETRIEVAL": "true",
        "ENABLE_STRUCTURAL_FILTER": "true" if enable_filter else "false"
    }
    write_env_config(config)

    print("\n✅ 混合检索已启用")
    if enable_filter:
        print("   策略：结构化过滤（颜色/类别/季节）+ 语义排序")
    else:
        print("   策略：纯语义排序（无结构化过滤）")
    print("\n⚠️  需要重启服务才能生效")


def disable_hybrid_retrieval():
    """禁用混合检索，回退到纯语义检索。"""
    config = {
        "ENABLE_HYBRID_RETRIEVAL": "false"
    }
    write_env_config(config)

    print("\n✅ 混合检索已禁用")
    print("   已回退到纯语义检索（VectorWardrobeService）")
    print("\n⚠️  需要重启服务才能生效")


def main():
    parser = argparse.ArgumentParser(description="混合检索配置开关管理")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--status", action="store_true", help="查看当前配置状态")
    group.add_argument("--enable", action="store_true", help="启用混合检索")
    group.add_argument("--disable", action="store_true", help="禁用混合检索（回退到纯语义）")

    parser.add_argument("--no-filter", action="store_true",
                       help="启用混合检索但禁用结构化过滤（仅用于 --enable）")

    args = parser.parse_args()

    if args.status:
        show_status()
    elif args.enable:
        enable_hybrid_retrieval(enable_filter=not args.no_filter)
    elif args.disable:
        if args.no_filter:
            parser.error("--no-filter 只能与 --enable 一起使用")
        disable_hybrid_retrieval()


if __name__ == "__main__":
    main()
