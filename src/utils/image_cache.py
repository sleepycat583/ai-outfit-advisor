"""图片 Base64 缓存工具模块

提供图片读取、Base64 转换和缓存功能，避免同一图片在多次 rerun 中重复下载。
"""

import base64
import time

# 诊断统计：记录一次 render_page() 内图片 Base64 处理的总调用次数与耗时
_image_load_stats = {
    "count": 0,
    "total_time": 0.0,
    "network_count": 0,
    "network_time": 0.0,
    "local_count": 0,
    "local_time": 0.0,
    "cache_hit_count": 0,
    "cache_miss_count": 0,
}

# 诊断统计：记录当前 Streamlit 进程里哪些图片 URL 已经真实加载过
_image_cache_seen_paths: set[str] = set()

# 业务缓存：按 image_path 复用图片 Base64，支持单条目失效
_image_base64_cache: dict[str, str] = {}


def reset_image_load_stats() -> None:
    """重置单次页面渲染期间的图片读取统计"""
    _image_load_stats.update(
        {
            "count": 0,
            "total_time": 0.0,
            "network_count": 0,
            "network_time": 0.0,
            "local_count": 0,
            "local_time": 0.0,
            "cache_hit_count": 0,
            "cache_miss_count": 0,
        }
    )


def log_image_load_stats() -> None:
    """输出单次页面渲染期间的图片读取累计统计"""
    print(
        "[PERF] get_image_base64 总调用次数="
        f"{_image_load_stats['count']}（网络请求{_image_load_stats['network_count']}次/本地{_image_load_stats['local_count']}次），"
        f"累计耗时={_image_load_stats['total_time']:.3f}s，"
        f"网络耗时={_image_load_stats['network_time']:.3f}s，本地耗时={_image_load_stats['local_time']:.3f}s",
        flush=True,
    )
    print(
        f"[PERF] get_image_base64 缓存命中={_image_load_stats['cache_hit_count']}次，"
        f"缓存未命中(真实网络请求)={_image_load_stats['cache_miss_count']}次",
        flush=True,
    )


def _get_image_base64_cached(image_path: str) -> str:
    """读取并缓存图片 Base64 结果，避免同一 URL 在多次 rerun 中重复下载

    参数:
        image_path: 图片路径，支持 HTTP(S) URL 和本地文件路径
    返回值:
        图片内容对应的 Base64 字符串
    """
    cached = _image_base64_cache.get(image_path)
    if cached is not None:
        return cached

    if image_path.startswith("http://") or image_path.startswith("https://"):
        import urllib.request

        with urllib.request.urlopen(image_path) as resp:
            image_b64 = base64.b64encode(resp.read()).decode("utf-8")
    else:
        with open(image_path, "rb") as f:
            image_b64 = base64.b64encode(f.read()).decode("utf-8")

    _image_base64_cache[image_path] = image_b64
    _image_cache_seen_paths.add(image_path)
    return image_b64


def clear_image_base64_cache(image_path: str | None = None) -> None:
    """清理图片 Base64 缓存

    参数:
        image_path: 指定时只清理这一个图片 URL；不传时清空全部缓存

    业务规则: 衣物换图时，旧图和新图通常复用同一个公开 URL。
    这时必须把对应条目从缓存里剔除，但不应该连其他 20 多张图一起清掉。
    """
    if image_path:
        _image_base64_cache.pop(image_path, None)
        _image_cache_seen_paths.discard(image_path)
        return

    _image_base64_cache.clear()
    _image_cache_seen_paths.clear()


def get_image_base64(image_path: str) -> str:
    """读取图片并转换为 Base64，同时累计单次页面渲染内的调用统计

    业务规则: 底层真实读取交给缓存函数复用结果，外层保留调用次数和
    本轮耗时统计，便于继续验证缓存命中后的实际收益。

    参数:
        image_path: 图片路径，支持 HTTP(S) URL 和本地文件路径
    返回值:
        图片内容对应的 Base64 字符串
    """
    load_start = time.time()
    is_network = image_path.startswith("http://") or image_path.startswith("https://")
    if image_path in _image_cache_seen_paths:
        _image_load_stats["cache_hit_count"] += 1
    else:
        _image_load_stats["cache_miss_count"] += 1
    image_b64 = _get_image_base64_cached(image_path)

    elapsed = time.time() - load_start
    _image_load_stats["count"] += 1
    _image_load_stats["total_time"] += elapsed
    if is_network:
        _image_load_stats["network_count"] += 1
        _image_load_stats["network_time"] += elapsed
    else:
        _image_load_stats["local_count"] += 1
        _image_load_stats["local_time"] += elapsed
    return image_b64
