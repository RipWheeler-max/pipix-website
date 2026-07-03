# 视频下载工具

> **皮皮虾无水印 + YouTube 高清视频下载** — 自部署、轻量、零依赖商业 API

一个轻量的 web 应用，支持从皮皮虾（去除水印）和 YouTube（多档画质）下载视频。纯 Python + FastAPI，单机能跑，无外部 API 费用。

## ✨ 特性

- 🦐 **皮皮虾无水印** — 优先匹配 `dr=6+dy_q` 的抖音 API 链路直链，绕过皮皮虾水印
- ▶️ **YouTube 多档画质** — 2160p / 1440p / 1080p / 720p / 480p 一键选择
- 🚀 **零外部依赖** — 不调用任何第三方付费 API（TikHub、新榜等），自解析
- 💾 **智能缓存** — 视频直链 24h 缓存，相同视频不重复解析
- 🔒 **Cookie 池** — 可选配置皮皮虾 Cookie 提高解析成功率
- 📊 **配额管理** — 每 IP 每天 5 次免费（可配置）
- 🌗 **单页前端** — Tailwind CDN，无需 npm 构建

## 🖼 截图

```
┌─────────────────────────────────────┐
│   视频下载工具                       │
│  粘贴分享链接 → 一键下载视频          │
├─────────────────────────────────────┤
│  [🦐 皮皮虾]  [▶️ YouTube]          │
│                                     │
│  [_______________________________]  │
│  [         解析          ]         │
│                                     │
│  ████░░░░░░░░░░ 1/5 已用           │
└─────────────────────────────────────┘
```

## 🚀 快速开始

### 本地运行

```bash
# 1. 克隆
git clone https://github.com/RipWheeler-max/pipix-website.git
cd pipix-website

# 2. 装依赖 (需要 Python 3.10+, ffmpeg, curl, yt-dlp)
# macOS:
brew install ffmpeg yt-dlp

# Linux:
sudo apt install ffmpeg
pip install yt-dlp

# 3. 装 Python 包
pip install -r requirements.txt

# 4. 启动
./run.sh
# 或: ~/.hermes/hermes-agent/venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8765
```

打开 http://localhost:8765

### 生产部署（推荐）

#### 方案 A：阿里云轻量 1核2G（约 50-100 元/月）

```bash
# 1. 装系统依赖
sudo apt update
sudo apt install -y python3-pip python3-venv ffmpeg nginx supervisor

# 2. 拉代码
sudo git clone https://github.com/RipWheeler-max/pipix-website.git /opt/pipix-website
cd /opt/pipix-website
python3 -m venv venv
./venv/bin/pip install -r requirements.txt
./venv/bin/pip install yt-dlp

# 3. supervisor 管进程
sudo tee /etc/supervisor/conf.d/pipix.conf <<EOF
[program:pipix]
command=/opt/pipix-website/venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8765 --workers 2
directory=/opt/pipix-website
user=www-data
autostart=true
autorestart=true
EOF

sudo supervisorctl reread
sudo supervisorctl update

# 4. nginx 反代 + HTTPS (Cloudflare 一键申请)
sudo tee /etc/nginx/sites-available/pipix <<EOF
server {
    listen 80;
    server_name your-domain.com;

    client_max_body_size 500M;
    proxy_read_timeout 300;

    location / {
        proxy_pass http://127.0.0.1:8765;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
    }
}
EOF

sudo ln -s /etc/nginx/sites-available/pipix /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```

## 📖 使用方法

1. 打开网站
2. 切换 tab：**🦐 皮皮虾** 或 **▶️ YouTube**
3. 粘贴视频分享链接
4. 点 **解析**
5. YouTube 选画质
6. 点 **下载视频**

### 链接格式

| 平台 | 链接样例 |
|---|---|
| 皮皮虾 | `https://h5.pipix.com/s/xxxxx` |
| 皮皮虾 | `https://h5.pipix.com/ppx/item/12345` |
| YouTube | `https://www.youtube.com/watch?v=xxxxx` |
| YouTube | `https://youtu.be/xxxxx` |
| YouTube | `https://www.youtube.com/shorts/xxxxx` |

## ⚙️ 配置

### 修改免费配额

编辑 `app/main.py`：

```python
FREE_DAILY_QUOTA = 5  # 每 IP 每天免费次数
```

### 添加皮皮虾 Cookie（提高成功率）

`POST /api/admin/cookie`：

```bash
curl -X POST http://localhost:8765/api/admin/cookie \
  -H "Content-Type: application/json" \
  -d '{"cookie":"msToken=xxx; sessionid=yyy", "label":"my-cookie", "ua":"Mozilla/5.0 ..."}'
```

或者访问 `http://localhost:8765/api/admin/cookie` 查看池状态。

## 🔧 工作原理

### 皮皮虾解析（无水印）

```
分享链接 h5.pipix.com/s/xxx
    ↓ 跟随 302 重定向
真实链接 h5.pipix.com/ppx/item/{item_id}
    ↓ 抓 HTML (curl + User-Agent + Referer)
页面 HTML (含 video_id 和多个 ppxvod CDN URL)
    ↓ 正则提取
候选 URL 列表
    ↓ 优先级筛选
1. dr=6 + dy_q 时间戳    → 抖音 API 链路，无水印 ✅
2. dr=6 (无 dy_q)        → 部分去水印
3. dr=3 + lr=superb      → 有水印 (fallback)
    ↓
返回 CDN 直链给用户
```

详情见 [Skill 文档](~/.hermes/skills/media/无水印下载皮皮虾视频/SKILL.md) 中关于 `dr=6+dy_q` 的发现。

### YouTube 解析

```
链接 youtube.com/watch?v=xxx
    ↓ yt-dlp 拉取视频元信息
格式列表 (2160p / 1440p / 1080p / 720p / 480p 等)
    ↓ 选 bestvideo[height<=N] + bestaudio
下载视频流 (mp4) + 音频流 (m4a)
    ↓ ffmpeg 合并
最终 MP4
```

**为什么不用 ffmpeg 不行？** YouTube 的高清画质是 DASH 分流：视频流和音频流是分开的，必须合并。

### 防盗链处理

皮皮虾 CDN 检查 HTTP `Referer: https://h5.pipix.com/`，浏览器 fetch 不让设 Referer（安全限制），所以：

- **方案 A（已弃）**：纯前端 fetch → 403
- **方案 B（已弃）**：302 重定向到 CDN → 浏览器默认播放而非下载
- **方案 C（当前）**：服务端流式代理，带正确 Referer + UA，绕过防盗链

## 🏗 项目结构

```
pipix-website/
├── app/
│   ├── main.py              # FastAPI 主应用 + 平台路由
│   ├── pipix.py             # 皮皮虾解析核心
│   ├── youtube.py           # YouTube 解析 (yt-dlp + ffmpeg)
│   ├── cookie_pool.py       # 多平台 Cookie 池
│   ├── templates/
│   │   └── index.html       # 单页前端 (Tailwind CDN)
│   └── static/              # (预留静态资源)
├── data/
│   ├── pipix.db             # SQLite: 下载历史 + 配额
│   └── cookie_pool.json     # Cookie 池持久化
├── logs/                    # uvicorn 日志
├── requirements.txt
└── run.sh                   # 启动脚本
```

## 📡 API 接口

| 接口 | 方法 | 用途 |
|---|---|---|
| `/` | GET | 主页 |
| `/api/parse` | POST | 解析视频链接，返回下载信息 |
| `/api/download` | GET | 下载视频 (皮皮虾流式 / YouTube 本地) |
| `/api/quota` | GET | 查询当前 IP 配额 |
| `/api/stats` | GET | 全局统计 |
| `/api/admin/cookie` | POST/GET/DELETE | Cookie 池管理 |

## ⚠️ 注意事项

1. **皮皮虾服务可能变更**：分享页 HTML 结构、CDN 链接参数都可能更新。如果解析失败，先看下 Skill 文档。
2. **YouTube 公开视频可下**，私密/年龄限制视频需要登录 Cookie。
3. **视频版权归原作者所有**，本工具仅供学习交流使用。
4. **不要高频请求**，会被 CDN 限流。Cookie 池可分摊但不能完全规避。
5. **不内置抖音/TikTok/Twitter** — 这些平台反爬严苛，签名算法每周变，独立项目可考虑接入 `f2` 库。

## 🤝 贡献

欢迎 PR！特别欢迎：
- 修复皮皮虾 HTML 结构变化导致的解析失败
- 适配其他短视频平台（**B 站**最容易加，因为是公开 API）
- 前端 UI 改进

## 📜 许可

[MIT](LICENSE) — 随便用，不负责。
