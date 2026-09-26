#!/usr/bin/env bash
# 一键部署/更新 lucky-play 到京东云服务器（ssh 别名 jd_admin，见 ~/.ssh/config）。
# 用法: 在仓库根目录执行  bash scripts/deploy.sh
# 说明: 远端以用户级 systemd 服务运行（lucky.service，端口 8666），
#       .venv/ 与 data/lucky.db 留在服务器上不被覆盖；公网访问需在
#       京东云控制台安全组放行 TCP 8666。
set -euo pipefail

HOST=jd_admin
DIR=lucky-play

echo "==> 上传代码（远端 .venv 与 data 不受影响）"
tar czf - \
  --exclude='.venv' --exclude='data' --exclude='.git' --exclude='.zcode' \
  --exclude='__pycache__' --exclude='.pytest_cache' --exclude='gui-test-screenshots' \
  --exclude='*.log' \
  . | ssh "$HOST" "mkdir -p ~/$DIR && tar xzf - -C ~/$DIR"

echo "==> 同步依赖并重启服务"
ssh "$HOST" "cd ~/$DIR \
  && .venv/bin/pip install -q -i https://pypi.tuna.tsinghua.edu.cn/simple 'fastapi>=0.115' 'uvicorn>=0.30' \
  && systemctl --user daemon-reload \
  && systemctl --user restart lucky.service && sleep 1 \
  && curl -sf http://127.0.0.1:8666/api/meta >/dev/null \
  && echo '部署完成: http://111.228.49.184:8666'"
