#!/usr/bin/env python3
"""
FastAPI 主应用 — 皮皮虾无水印视频下载网站
- POST /api/parse  : 解析链接，返回 item_id / 视频直链 (前后端结合, 服务器最终中转下载)
- GET  /api/download?url=...  : 流式代理下载 (带正确 Referer, 解决防盗链)
- GET  /api/stats  : 简单统计
- GET  /          : 主页

存储: SQLite (data/pipix.db) — 下载历史、限流
缓存: 内存 dict (item_id -> 视频直链, TTL 24h), 解决重复解析
"""
import os
import re
import sys
import json
import time
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional
from urllib.parse import quote

# 确保能找到本地模块
sys.path.insert(0, str(Path(__file__).parent))

import httpx
from fastapi import FastAPI, Request, HTTPException, Query
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

from pipix import fetch_video_url as pipix_parse, get_video_title as pipix_title, USER_AGENT, REFERER
from youtube import get_video_info as yt_info, download_video as yt_download
from cookie_pool import pool

# ============== 配置 ==============
BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR.parent / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "pipix.db"

FREE_DAILY_QUOTA = 5  # 每 IP 每天免费次数
CACHE_TTL = 86400  # 视频直链缓存 24 小时
DOWNLOAD_TIMEOUT = 180
MAX_DOWNLOAD_SIZE = 500 * 1024 * 1024  # 500MB

app = FastAPI(title="皮皮虾无水印下载", version="0.2.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============== 数据库 ==============
def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS downloads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ip TEXT NOT NULL,
            item_id TEXT NOT NULL,
            share_url TEXT NOT NULL,
            quality TEXT,
            created_at INTEGER NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_ip_time ON downloads(ip, created_at);
        CREATE INDEX IF NOT EXISTS idx_item ON downloads(item_id);
    """)
    conn.commit()
    conn.close()


def get_client_ip(request: Request) -> str:
    xff = request.headers.get("X-Forwarded-For")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def check_quota(ip: str) -> tuple[bool, int]:
    today_start = int(datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp())
    conn = sqlite3.connect(DB_PATH)
    cur = conn.execute(
        "SELECT COUNT(*) FROM downloads WHERE ip=? AND created_at>=?",
        (ip, today_start),
    )
    used = cur.fetchone()[0]
    conn.close()
    remaining = max(0, FREE_DAILY_QUOTA - used)
    return used < FREE_DAILY_QUOTA, remaining


def log_download(ip: str, item_id: str, share_url: str, quality: str):
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "INSERT INTO downloads (ip, item_id, share_url, quality, created_at) VALUES (?,?,?,?,?)",
        (ip, item_id, share_url, quality, int(time.time())),
    )
    conn.commit()
    conn.close()


def detect_platform(url: str) -> str:
    """从 URL 自动识别平台."""
    url = url.lower()
    if "pipix" in url:
        return "pipix"
    if "youtube.com" in url or "youtu.be" in url:
        return "youtube"
    return "unknown"


# ============== 视频直链缓存 (省 90% 解析, 缓存命中即跳到直链) ==============
_url_cache: dict = {}  # item_id -> {video_url, title, quality, saved_at}


def cache_get(item_id: str):
    entry = _url_cache.get(item_id)
    if not entry:
        return None
    if time.time() - entry["saved_at"] > CACHE_TTL:
        _url_cache.pop(item_id, None)
        return None
    return entry


def cache_set(item_id: str, video_url: str, title: str, quality: str):
    _url_cache[item_id] = {
        "video_url": video_url,
        "title": title,
        "quality": quality,
        "saved_at": time.time(),
    }


# ============== 路由 ==============
@app.on_event("startup")
async def startup():
    init_db()


@app.get("/", response_class=HTMLResponse)
async def index():
    html_path = BASE_DIR / "templates" / "index.html"
    return HTMLResponse(html_path.read_text(encoding="utf-8"))


@app.post("/api/parse")
async def api_parse(request: Request):
    """解析皮皮虾/YouTube 分享链接, 返回视频信息"""
    body = await request.json()
    share_url = (body.get("url") or "").strip()
    if not share_url:
        raise HTTPException(400, "请提供 url 参数")

    platform = detect_platform(share_url)
    if platform == "unknown":
        raise HTTPException(400, "不支持的链接格式，目前仅支持皮皮虾和 YouTube")

    ip = get_client_ip(request)
    allowed, remaining = check_quota(ip)
    if not allowed:
        raise HTTPException(429, f"今日免费次数已用完（{FREE_DAILY_QUOTA}次/天）")

    # ===== YouTube 路径 (用 yt_info 不下载, 让 /api/download 触发下载) =====
    if platform == "youtube":
        try:
            info = yt_info(share_url)
        except Exception as e:
            raise HTTPException(400, f"YouTube 解析失败: {e}")
        # 用 video_id 作缓存 key
        cache_set(f"yt:{info['video_id']}", share_url, info["title"], "YouTube 720p")
        log_download(ip, f"yt:{info['video_id']}", share_url, "youtube")
        safe_title = re.sub(r'[\\/:*?"<>|]', "_", info["title"])[:80] or info["video_id"]
        return JSONResponse({
            "ok": True,
            "platform": "youtube",
            "item_id": info["video_id"],
            "title": info["title"],
            "quality": f"{len(info['available_heights'])} 个画质可选 (默认 720p)",
            "thumbnail": info.get("thumbnail"),
            "channel": info.get("channel"),
            "duration": info.get("duration"),
            "available_heights": info["available_heights"],
            "filename": f"{safe_title}.mp4",
            "download_url": f"/api/download?platform=youtube&url={quote(share_url, safe='')}",
            "quota_remaining": remaining - 1,
        })

    # ===== 皮皮虾路径 =====
    ck = pool.get()
    try:
        item_id, video_url, quality = pipix_parse(share_url, cookie=ck)
        if ck:
            pool.report_success(ck["label"])
    except ValueError as e:
        if ck: pool.report_failure(ck["label"])
        raise HTTPException(400, str(e))
    except Exception as e:
        if ck: pool.report_failure(ck["label"])
        raise HTTPException(500, f"解析失败: {e}")

    title = pipix_title(share_url)
    safe_title = re.sub(r'[\\/:*?"<>|]', "_", title)[:50] or f"pipix_{item_id}"

    cache_set(item_id, video_url, title, quality)
    log_download(ip, item_id, share_url, quality)

    return JSONResponse({
        "ok": True,
        "platform": "pipix",
        "item_id": item_id,
        "title": title,
        "quality": quality,
        "filename": f"{safe_title}.mp4",
        "cached": False,
        "download_url": f"/api/download?id={item_id}&filename={safe_title}.mp4",
        "quota_remaining": remaining - 1,
    })


@app.get("/api/download")
async def api_download(
    request: Request,
    id: str = Query(None, description="皮皮虾 item_id"),
    platform: str = Query(None, description="youtube"),
    url: str = Query(None, description="视频 URL (YouTube 路径)"),
    filename: str = Query("video.mp4"),
):
    """下载视频. 皮皮虾: 流式代理; YouTube: yt-dlp + ffmpeg 合并下载"""
    safe_filename = re.sub(r'[\\/:*?"<>|]', "_", filename) or "video.mp4"
    encoded = quote(safe_filename, safe='')

    # ===== YouTube 路径 =====
    if platform == "youtube":
        if not url:
            raise HTTPException(400, "youtube 路径需要 url 参数")
        # 下载到 /tmp, 用 video_id 命名
        try:
            from youtube import extract_video_id
            vid = extract_video_id(url)
        except Exception as e:
            raise HTTPException(400, str(e))
        try:
            max_h = int(request.query_params.get("height", 720))
            if max_h < 144 or max_h > 4320:
                raise ValueError("height 超出允许范围 (144-4320)")
        except ValueError as e:
            raise HTTPException(400, f"无效的 height 参数: {e}")
        # 文件名含画质: 避免不同画质文件冲突
        output_path = f"/tmp/yt_{vid}_{max_h}p.mp4"
        # 如果已下载过 (同画质), 直接 FileResponse
        if os.path.exists(output_path):
            return FileResponse(
                output_path, media_type="video/mp4",
                filename=safe_filename,
                headers={"Cache-Control": "no-store"},
            )
        # 重新下载
        try:
            r = yt_download(url, output_path, max_height=max_h)
        except Exception as e:
            raise HTTPException(500, f"YouTube 下载失败: {e}")
        return FileResponse(
            r["file_path"], media_type="video/mp4",
            filename=safe_filename,
            headers={"Cache-Control": "no-store"},
        )

    # ===== 皮皮虾路径 (流式代理) =====
    if not id:
        raise HTTPException(400, "需要 id 或 platform 参数")
    if not re.match(r"^[A-Za-z0-9_-]+$", id):
        raise HTTPException(400, "无效的 id")

    cached = cache_get(id)
    if not cached:
        raise HTTPException(404, "视频链接已过期, 请重新解析")

    video_url = cached["video_url"]
    log_download(get_client_ip(request), id, "", cached.get("quality", ""))

    async def stream():
        async with httpx.AsyncClient(timeout=DOWNLOAD_TIMEOUT, follow_redirects=True) as client:
            async with client.stream(
                "GET", video_url,
                headers={"User-Agent": USER_AGENT, "Referer": REFERER},
            ) as resp:
                if resp.status_code != 200:
                    return
                async for chunk in resp.aiter_bytes(chunk_size=64 * 1024):
                    yield chunk

    return StreamingResponse(
        stream(),
        media_type="video/mp4",
        headers={
            "Content-Disposition": f'attachment; filename="video.mp4"; filename*=UTF-8\'\'{encoded}',
            "Cache-Control": "no-store",
        },
    )


@app.get("/api/stats")
async def api_stats():
    conn = sqlite3.connect(DB_PATH)
    total = conn.execute("SELECT COUNT(*) FROM downloads").fetchone()[0]
    today_start = int(datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp())
    today = conn.execute("SELECT COUNT(*) FROM downloads WHERE created_at>=?", (today_start,)).fetchone()[0]
    unique_items = conn.execute("SELECT COUNT(DISTINCT item_id) FROM downloads").fetchone()[0]
    conn.close()
    return {"total": total, "today": today, "unique_videos": unique_items, "cached_urls": len(_url_cache)}


@app.get("/api/quota")
async def api_quota(request: Request):
    ip = get_client_ip(request)
    allowed, remaining = check_quota(ip)
    return {"daily_limit": FREE_DAILY_QUOTA, "remaining": remaining, "is_premium": False}


# ============== Cookie 池管理 ==============
@app.post("/api/admin/cookie")
async def api_add_cookie(request: Request):
    body = await request.json()
    cookie_str = (body.get("cookie") or "").strip()
    if not cookie_str:
        raise HTTPException(400, "请提供 cookie 字符串")
    pool.add_cookie(cookie_str, label=body.get("label") or "", ua=body.get("ua") or "")
    return {"ok": True, "total": len(pool.cookies)}


@app.get("/api/admin/cookie")
async def api_pool_status():
    return pool.status()


@app.delete("/api/admin/cookie/{label}")
async def api_remove_cookie(label: str):
    pool.remove_cookie(label)
    return {"ok": True}


app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8765, log_level="info")
