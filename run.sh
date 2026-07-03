#!/bin/bash
# 启动皮皮虾下载网站 (用 Hermes 内置 Python venv)
set -e
cd "$(dirname "$0")"
PY=~/.hermes/hermes-agent/venv/bin/python
echo "🚀 启动服务: http://localhost:8765"
exec $PY -m uvicorn app.main:app --host 0.0.0.0 --port 8765 --reload