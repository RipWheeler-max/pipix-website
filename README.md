# 视频下载工具

皮皮虾无水印 + YouTube 多档画质下载。FastAPI + 单页前端，自部署/本地运行。

## 平台支持

- 🦐 **皮皮虾** — 无水印
- ▶️ **YouTube** — 2160p / 1440p / 1080p / 720p / 480p

## 快速开始

```bash
# 系统依赖: Python 3.10+, ffmpeg, yt-dlp (macOS: brew install ffmpeg yt-dlp)
pip install -r requirements.txt
./run.sh
```

打开 http://localhost:8765

## 工作原理

链接 → 后端解析 → 返回视频下载链接 → 浏览器直接下载。皮皮虾走 HTML 直链解析，YouTube 走 `yt-dlp` + `ffmpeg` 合并视频音频流。

## 声明

- 视频版权归原作者所有，仅供个人学习交流
- 本工具与相关平台无任何关联
- 高频使用可能触发平台风控，请合理使用

## 许可

MIT
