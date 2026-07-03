#!/usr/bin/env python3
"""
皮皮虾解析核心 — 改编自 Skill '无水印下载皮皮虾视频'
原版: 命令行下载文件。本版: 返回无水印视频的直链，供 FastAPI 流式代理。
"""
import re
import urllib.parse
import subprocess
from typing import Optional, Tuple


USER_AGENT = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 "
    "Mobile/15E148 Safari/604.1"
)
REFERER = "https://h5.pipix.com/"


def extract_item_id(url: str) -> str:
    """从分享链接中提取 item_id。支持 /s/xxx 和 /item/NNN 两种形式。"""
    patterns = [
        r"h5\.pipix\.com/s/([a-zA-Z0-9_-]+)",
        r"h5\.pipix\.com/ppx/item/(\d+)",
        r"item/(\d+)",
    ]
    for p in patterns:
        m = re.search(p, url)
        if m:
            return m.group(1)
    if url.isdigit():
        return url
    raise ValueError(f"无法从 URL 中提取 item_id: {url}")


def get_real_url(url: str) -> str:
    """跟随 302 重定向拿到真实 URL。"""
    try:
        proc = subprocess.run(
            [
                "curl", "-s", "-I", "-L", "--max-time", "15",
                "-H", f"User-Agent: {USER_AGENT}",
                "-H", f"Referer: {REFERER}",
                url,
            ],
            capture_output=True, text=True, timeout=20,
        )
        for line in proc.stdout.split("\n"):
            if line.lower().startswith("location:"):
                return line.split(":", 1)[1].strip()
        return url
    except Exception:
        return url


def fetch_video_url(share_url: str, cookie: Optional[dict] = None) -> Tuple[str, str, str]:
    """
    解析皮皮虾分享链接，返回 (item_id, video_url, quality_label)

    cookie: 可选 Cookie dict（来自 Cookie 池），增强反爬通过率
    优先级:
      1. dr=6 + dy_q  → 真正无水印（抖音 API 链路）
      2. dr=6 (无 dy_q) → 部分去水印
      3. dr=3 + lr=superb → 有水印（fallback）
    """
    item_id = extract_item_id(share_url)

    # /s/xxx 短链先重定向到 /item/NNN
    if "/s/" in share_url:
        real = get_real_url(f"https://h5.pipix.com/s/{item_id}/")
        m = re.search(r"/item/(\d+)", real)
        if m:
            item_id = m.group(1)

    detail_url = f"https://h5.pipix.com/ppx/item/{item_id}?app_id=1319&app=super"

    # 构造 curl headers
    headers = [
        "-H", f"User-Agent: {USER_AGENT}",
        "-H", "Accept: text/html,application/xhtml+xml",
        "-H", f"Referer: {REFERER}",
    ]
    if cookie and cookie.get("cookie"):
        headers += ["-H", f"Cookie: {cookie['cookie']}"]
    if cookie and cookie.get("ua"):
        # 替换 UA 头
        headers = [h for i, h in enumerate(headers) if not h.startswith("User-Agent:")]
        headers += ["-H", f"User-Agent: {cookie['ua']}", "-H", f"Referer: {REFERER}"]

    result = subprocess.run(
        ["curl", "-s", "--max-time", "20", "-L", *headers, detail_url],
        capture_output=True, text=True, timeout=25,
    )
    html = urllib.parse.unquote(result.stdout)

    # 提取所有 ppxvod CDN URL
    cdn_urls = re.findall(r"(https?://[^\s\"'\\]+ppxvod\.com[^\s\"'\\]+)", html)
    seen = set()
    unique_urls = []
    for u in cdn_urls:
        base = u.split("?")[0]
        if base not in seen:
            seen.add(base)
            unique_urls.append(u)

    if not unique_urls:
        raise ValueError(f"未找到任何视频链接 (item_id={item_id})，可能是视频已删除或链接错误")

    unique_urls = [u.replace("\\/", "/").replace('\\"', '"') for u in unique_urls]

    # 按优先级筛选
    no_wm = [u for u in unique_urls if "dr=6" in u and "dy_q" in u]
    dr6_only = [u for u in unique_urls if "dr=6" in u]
    has_wm = [u for u in unique_urls if "lr=superb" in u]

    if no_wm:
        # 优先 v26 节点
        v26 = [u for u in no_wm if "v26-cdn" in u]
        chosen = v26[0] if v26 else no_wm[0]
        label = "无水印"
    elif dr6_only:
        v26 = [u for u in dr6_only if "v26-cdn" in u]
        chosen = v26[0] if v26 else dr6_only[0]
        label = "部分去水印"
    elif has_wm:
        v26 = [u for u in has_wm if "v26-cdn" in u]
        chosen = v26[0] if v26 else has_wm[0]
        label = "有水印（fallback）"
    else:
        v26 = [u for u in unique_urls if "v26-cdn" in u]
        chosen = v26[0] if v26 else unique_urls[0]
        label = "未知"

    return item_id, chosen, label


def get_video_title(share_url: str) -> str:
    """尽力从页面提取视频标题，找不到返回 item_id。"""
    try:
        item_id = extract_item_id(share_url)
        if "/s/" in share_url:
            real = get_real_url(f"https://h5.pipix.com/s/{item_id}/")
            m = re.search(r"/item/(\d+)", real)
            if m:
                item_id = m.group(1)

        detail_url = f"https://h5.pipix.com/ppx/item/{item_id}?app_id=1319&app=super"
        result = subprocess.run(
            [
                "curl", "-s", "--max-time", "15", "-L",
                "-H", f"User-Agent: {USER_AGENT}",
                detail_url,
            ],
            capture_output=True, text=True, timeout=20,
        )
        html = urllib.parse.unquote(result.stdout)

        # 皮皮虾页面通常在 <title> 或 og:title 里
        m = re.search(r'<meta name="description" content="([^"]+)"', html)
        if m:
            return m.group(1)[:80]
        m = re.search(r"<title>([^<]+)</title>", html)
        if m:
            return m.group(1)[:80]
    except Exception:
        pass
    return "pipix_video"
