#!/usr/bin/env bash
# 幸运抽奖一键启动：服务没起就在后台拉起，就绪后用默认浏览器打开抽奖页。
# 桌面快捷方式（~/Desktop/幸运抽奖.desktop）指向本脚本；双击图标即用。
set -u

PROJECT=/home/xll/Projects/lucky-play
UV=/usr/sbin/uv
URL="http://127.0.0.1:8666"
LOG=/tmp/lucky-play-8666.log

alive() { curl -fsS -o /dev/null --max-time 2 "$URL/api/meta"; }

# 已在运行：直接打开页面
if alive; then
  xdg-open "$URL" >/dev/null 2>&1 &
  exit 0
fi

# 没在运行：后台拉起服务（日志落 /tmp，方便排查）
cd "$PROJECT"
nohup "$UV" run --no-config uvicorn app.main:app --host 127.0.0.1 --port 8666 >"$LOG" 2>&1 &

# 等服务就绪（最多 20 秒）
for _ in $(seq 1 40); do
  if alive; then break; fi
  sleep 0.5
done

xdg-open "$URL" >/dev/null 2>&1 &
