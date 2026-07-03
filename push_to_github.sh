#!/bin/bash
# GitHub 推送脚本
# 老板你在 GitHub 上先建好空 repo (https://github.com/RipWheeler-max/pipix-website)
# 然后运行这个脚本

set -e
cd "$(dirname "$0")"

# 1. 初始化 git (如果还没有)
if [ ! -d ".git" ]; then
  git init
  git branch -M main
fi

# 2. 远程仓库
git remote remove origin 2>/dev/null || true
git remote add origin https://github.com/RipWheeler-max/pipix-website.git

# 3. 提交
git add .
git commit -m "Initial commit: 皮皮虾 + YouTube 视频下载工具" || echo "Nothing to commit"

# 4. 推送
git push -u origin main

echo "✅ Done! 访问 https://github.com/RipWheeler-max/pipix-website"
