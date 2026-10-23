#!/usr/bin/env bash
# 打包项目为干净压缩包（发给他人直接可跑），输出到 dist/。
# 用法: bash scripts/package.sh   （排除虚拟环境/数据库/git/测试截图/本地备份等私有内容）
set -euo pipefail
cd "$(dirname "$0")/.."

mkdir -p dist
NAME="lucky-play-$(date +%Y%m%d)"

# local-backup/（含历史备份与内部脚本）、.zcode/、.zcodeignore、music/ 均为
# 本地私有内容，绝不进分发包——与 .gitignore 口径保持一致
EXCLUDES=(
  .venv data .git __pycache__ .pytest_cache gui-test-screenshots .zcode dist
  local-backup .zcodeignore music
  .DS_Store '*.log' '*.db' '*.db-wal' '*.db-shm'
)

if command -v zip >/dev/null 2>&1; then
  # zip 分支：文件类排除项不能拼 /* 后缀（那样永远匹配不到文件）；
  # 先删旧档再打包，避免 zip 对已存在归档做"增量更新"残留已删除文件
  rm -f "dist/$NAME.zip"
  ZIP_ARGS=()
  for e in "${EXCLUDES[@]}"; do
    case "$e" in
      *'*') ZIP_ARGS+=(-x "$e") ;;   # 通配模式（*.log 等）原样传
      *)    ZIP_ARGS+=(-x "$e" "$e/*") ;;  # 目录/文件名：本体 + 目录内容
    esac
  done
  zip -r "dist/$NAME.zip" . "${ZIP_ARGS[@]}" >/dev/null
  echo "dist/$NAME.zip"
else
  TAR_EX=()
  for e in "${EXCLUDES[@]}"; do TAR_EX+=(--exclude="$e"); done
  tar czf "dist/$NAME.tar.gz" "${TAR_EX[@]}" .
  echo "dist/$NAME.tar.gz"
fi
