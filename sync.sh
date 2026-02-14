#!/bin/bash
# ETH Phase Meter - 自动同步到 GitHub
# 用法: ./sync.sh [commit message]

set -e
REPO_DIR="/root/eth-phase-meter"
WORKSPACE="/root/.openclaw/workspace"

# 同步最新脚本
cp "$WORKSPACE/eth_phase_meter.py" "$REPO_DIR/"
cp /etc/systemd/system/eth-phase-meter.service "$REPO_DIR/" 2>/dev/null || true

cd "$REPO_DIR"

# 检查是否有变更
if git diff --quiet && git diff --cached --quiet; then
    echo "✅ 无变更，跳过同步"
    exit 0
fi

# 提交 + 推送
MSG="${1:-Auto-sync: $(date '+%Y-%m-%d %H:%M UTC')}"
git add -A
git commit -m "$MSG"
git push origin main

echo "✅ 已同步到 GitHub: https://github.com/stanleyrprose/eth-phase-meter"
