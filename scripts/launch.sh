#!/usr/bin/env bash
# 幸运抽奖一键启动：服务没起就在后台拉起，就绪后用默认浏览器打开抽奖页。
# 桌面快捷方式（~/Desktop/幸运抽奖.desktop）指向本脚本；双击图标即用。
set -u

# 路径自适应：以脚本自身位置定位项目根，任何机器/任意克隆目录均可运行
PROJECT="$(cd "$(dirname "$0")/.." && pwd)"
URL="http://127.0.0.1:8666"
LOG=/tmp/lucky-play-8666.log

alive() { curl -fsS -o /dev/null --max-time 2 "$URL/api/meta"; }

# 已在运行：直接打开页面
if alive; then
  xdg-open "$URL" >/dev/null 2>&1 &
  exit 0
fi

# 没在运行：后台拉起服务（日志落 /tmp，方便排查）
cd "$PROJECT" || exit 1
if command -v uv >/dev/null 2>&1; then
  UV_BIN="$(command -v uv)"
elif [ -x "$HOME/.local/bin/uv" ]; then
  UV_BIN="$HOME/.local/bin/uv"
else
  notify-send "幸运抽奖" "未找到 uv，请先安装：https://docs.astral.sh/uv/" 2>/dev/null
  echo "未找到 uv，请先安装：https://docs.astral.sh/uv/" >&2
  exit 1
fi
nohup "$UV_BIN" run --no-config uvicorn app.main:app --host 127.0.0.1 --port 8666 >"$LOG" 2>&1 &

# 等服务就绪（最多 20 秒）；起不来就明说，不再静默打开浏览器
for _ in $(seq 1 40); do
  if alive; then break; fi
  sleep 0.5
done
if ! alive; then
  notify-send "幸运抽奖" "服务启动失败，日志见 $LOG" 2>/dev/null
  echo "服务启动失败，日志见 $LOG" >&2
  exit 1
fi

xdg-open "$URL" >/dev/null 2>&1 &
