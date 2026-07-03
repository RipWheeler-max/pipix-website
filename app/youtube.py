#!/usr/bin/env python3
"""
YouTube 视频解析 + 下载 (无 cookie, 用 yt-dlp + ffmpeg)
支持链接:
  - youtube.com/watch?v=xxx
  - youtu.be/xxx
  - youtube.com/shorts/xxx
  - youtube.com/embed/xxx
"""
import re
import os
import sys
import json
import subprocess
from typing import Tuple, Optional


def extract_video_id(url: str) -> str:
    patterns = [
        r"(?:youtube\.com/watch\?v=|youtu\.be/|youtube\.com/shorts/|youtube\.com/embed/)([A-Za-z0-9_-]{11})",
        r"youtube\.com/v/([A-Za-z0-9_-]{11})",
    ]
    for p in patterns:
        m = re.search(p, url)
        if m:
            return m.group(1)
    raise ValueError(f"无法从 URL 提取 YouTube video_id: {url}")


def _dump_info(video_id: str) -> dict:
    """调 yt-dlp 取视频元信息 (JSON)."""
    result = subprocess.run(
        [
            "yt-dlp",
            "--dump-json",
            "--no-warnings",
            "--no-playlist",
            "--no-check-certificates",
            f"https://www.youtube.com/watch?v={video_id}",
        ],
        capture_output=True, text=True, timeout=60,
    )
    if result.returncode != 0:
        raise RuntimeError(f"yt-dlp 失败: {result.stderr.strip()[:200]}")
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        raise RuntimeError("yt-dlp 返回了非 JSON 输出")


def get_video_info(share_url: str) -> dict:
    """返回视频元信息 (供前端展示): {video_id, title, duration, thumbnail, channel, quality_options}"""
    video_id = extract_video_id(share_url)
    info = _dump_info(video_id)
    formats = info.get("formats", [])

    # 收集可选画质 (mp4 video stream)
    heights = sorted(set(
        f.get("height") for f in formats
        if f.get("ext") == "mp4"
        and f.get("vcodec") not in (None, "none")
        and f.get("height")
    ), reverse=True)

    return {
        "video_id": video_id,
        "title": info.get("title", "youtube_video")[:100],
        "duration": info.get("duration", 0),
        "thumbnail": info.get("thumbnail"),
        "channel": info.get("uploader") or info.get("channel"),
        "available_heights": heights[:5],  # 最多展示 5 个档
    }


def download_video(share_url: str, output_path: str, max_height: int = 720) -> dict:
    """
    下载 YouTube 视频到本地 output_path.
    max_height: 限制最高画质 (默认 720p, 平衡体积和质量)
    返回 {video_id, title, file_path, file_size, quality}
    """
    video_id = extract_video_id(share_url)
    info = _dump_info(video_id)
    title = info.get("title", "youtube_video")[:80]

    # 选格式: 优先 <=max_height 的 mp4 视频流 + m4a 音频流
    # ffmpeg 自动合并
    fmt = (
        f"bestvideo[height<={max_height}][ext=mp4]+bestaudio[ext=m4a]"
        f"/bestvideo[height<={max_height}]+bestaudio"
        f"/best[height<={max_height}][ext=mp4]"
        f"/best[ext=mp4]/best"
    )
    cmd = [
        "yt-dlp",
        "-f", fmt,
        "--merge-output-format", "mp4",
        "-o", output_path,
        "--no-playlist",
        "--no-warnings",
        "--no-check-certificates",
        f"https://www.youtube.com/watch?v={video_id}",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if result.returncode != 0:
        raise RuntimeError(f"yt-dlp 下载失败: {result.stderr.strip()[:300]}")

    # yt-dlp 可能自动加 .mp4 后缀 (如文件已存在)
    final_path = output_path
    if not os.path.exists(final_path):
        for ext in (".mp4", ".mkv", ".webm"):
            cand = output_path + ext
            if os.path.exists(cand):
                final_path = cand
                break
        else:
            raise RuntimeError("yt-dlp 报告成功但找不到输出文件")

    file_size = os.path.getsize(final_path)
    return {
        "video_id": video_id,
        "title": title,
        "file_path": final_path,
        "file_size": file_size,
        "quality": f"{max_height}p MP4",
    }


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python3 youtube.py <url> [max_height]")
        sys.exit(1)
    url = sys.argv[1]
    max_h = int(sys.argv[2]) if len(sys.argv) > 2 else 720
    info = get_video_info(url)
    print(f"video_id: {info['video_id']}")
    print(f"title:    {info['title']}")
    print(f"channel:  {info['channel']}")
    print(f"duration: {info['duration']}s")
    print(f"heights:  {info['available_heights']}")
    print()
    print(f"--- 下载 {max_h}p ---")
    r = download_video(url, f"/tmp/yt_{info['video_id']}.mp4", max_height=max_h)
    print(f"file:     {r['file_path']}")
    print(f"size:     {r['file_size']/1024:.1f} KB")
