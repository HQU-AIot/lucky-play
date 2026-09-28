#!/usr/bin/env bash
# 打包项目为干净压缩包（发给他人直接可跑），输出到 dist/。
# 用法: bash scripts/package.sh   （排除虚拟环境/数据库/git/测试截图等本地内容）
set -euo pipefail
cd "$(dirname "$0")/.."

mkdir -p dist
NAME="lucky-play-$(date +%Y%m%d)"

EXCLUDES=(
  .venv data .git __pycache__ .pytest_cache gui-test-screenshots .zcode dist
  .DS_Store '*.log' '*.db' '*.db-wal' '*.db-shm'
)

if command -v zip >/dev/null 2>&1; then
  # shellcheck disable=SC2046
  zip -r "dist/$NAME.zip" . $(printf -- '-x %q/* ' "${EXCLUDES[@]}") >/dev/null
  echo "dist/$NAME.zip"
else
  TAR_EX=()
  for e in "${EXCLUDES[@]}"; do TAR_EX+=(--exclude="$e"); done
  tar czf "dist/$NAME.tar.gz" "${TAR_EX[@]}" .
  echo "dist/$NAME.tar.gz"
fi
