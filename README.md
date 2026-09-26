# Lucky Play · 多形式 × 多主题抽奖系统

为 2026-09-30（国庆前一天）抽奖活动准备的可自托管抽奖站：6 种抽奖玩法 × 6 套视觉主题（含国庆主题），带概率后台、剩余奖品查询接口、谢谢参与动态概率转移。零外部资源（无 CDN/字体/图片素材），离线可用。

## 快速开始

```bash
uv sync                                   # 安装依赖（官方 PyPI：uv sync --no-config --default-index https://pypi.org/simple）
uv run uvicorn app.main:app --port 8000   # 启动
# 打开 http://127.0.0.1:8000        抽奖页
# 打开 http://127.0.0.1:8000/admin  后台
```

测试：`uv run --no-config pytest -q`

## 玩法（6 种）

| 玩法 | 说明 |
| --- | --- |
| 🎡 大转盘 | Canvas 转盘：蓄力回拉 → 爆发 → 长减速 → 过冲回摆，指针逐格弹跳 + 合成 tick 声 |
| 🧨 九宫格 | 灯圈 3 圈起步，步进间隔渐增，精准停格 + 脉冲 |
| 🎁 盲盒 | 点选盒子，摇晃蓄力后爆开，奖品 spring 弹出 + 迷你彩带 |
| 🃏 翻牌 | 8 张暗牌选一张，虚晃两张后 3D 翻开 |
| 🎰 老虎机 | 三滚轮错峰停定、滚动模糊，落定三格亮灯 |
| 🥚 扭蛋机 | 转旋钮掉出扭蛋，摇晃后开壳，奖品 spring 弹出 |

## 主题（6 套，页面右上角"风格"实时切换）

`festive 红金福运` / `national 国庆盛典（9·30 前夜专用：金星烟花 + 开奖倒计时）` / `neon 星空霓虹` / `macaron 云朵马卡龙` / `tech 未来科技` / `pixel 像素街机`

任一玩法 × 任一主题自由组合（24 种），选择存 localStorage。设计细节见 `docs/DESIGN.md`。

## 奖品（默认种子，后台可改）

不二家棒棒糖×53 · 奶龙手办×36 · 口袋笔记本×18 · 油画书签×8 · 鲨鱼匕首×6 · 电子爬宠×4 · 盖世小鸡手柄×1，另有谢谢参与（不限量）。

## 接口

公开：

| 接口 | 说明 |
| --- | --- |
| `GET /api/prizes` | **剩余奖品查询**：`{event, prizes:[{id,name,emoji,remaining,total}], total_remaining}` |
| `POST /api/draw` | 抽奖，返回 `{result:"prize"\|"thanks", prize}`（服务端先定结果，前端动画精确到达） |
| `GET /api/sample?count=7` | 按当前概率采样展示结果（无副作用、不扣库存），供翻牌旁位展示 |
| `GET /api/meta` | 活动名 / 开奖日期 / 副标 |

后台（请求头 `X-Admin-Token`；默认 `123456`，环境变量 `LUCKY_ADMIN_TOKEN` 覆盖）：

`GET /api/admin/state` · `PUT /api/admin/weights` · `PUT /api/admin/stock` · `PUT /api/admin/dynamic` · `PUT /api/admin/event` · `GET /api/admin/history?limit=` · `POST /api/admin/history/reset` · `POST /api/admin/replenish`

## 谢谢参与 · 动态概率

每个奖品有基础权重 W 与库存（总量 S、剩余 R）：

- **per_win 每抽一件渐移（默认）**：奖品有效权重 `W×R/S`，每抽走一件即有一份概率让给谢谢参与，抽空时恰好整体转移完；
- **depleted 抽空才整移**：剩余期间权重不变，抽空后 W 全额让给谢谢参与；
- 两种模式在奖品抽空/零库存时语义连续（权重整体让出）；关闭动态转移则抽空即退出奖池。
- 后台改权重 / 补货即时生效；补货后已转移概率自动回流（公式由库存推导，无状态漂移）。

默认权重：棒棒糖 30 · 奶龙 20 · 笔记本 15 · 书签 10 · 鲨鱼匕首 8 · 电子爬宠 6 · 手柄 2 · 谢谢参与 9。

## 数据与部署

- SQLite 单文件（`data/lucky.db`，环境变量 `LUCKY_DB` 覆盖），抽奖在 `BEGIN IMMEDIATE` 事务内扣库存，并发不超卖（有测试保障）。
- 改奖品清单/默认权重：编辑 `app/store.py` 的 `DEFAULT_PRIZES` 后删除 `data/lucky.db` 重新初始化（或直接在后台改）。注意转盘与九宫格按 **8 格**布局（7 奖品 + 谢谢参与），奖品总数建议不超过 7 项；后台仅能改权重与库存，改名/增删奖品走 `DEFAULT_PRIZES` 重新初始化。
- 公网部署务必设置 `LUCKY_ADMIN_TOKEN` 环境变量替换默认令牌。

### 部署到京东云（已部署：111.228.49.184:8666）

服务器以 `admin` 用户的**用户级 systemd 服务**运行（`lucky.service`，无 sudo 依赖，`loginctl enable-linger` 已开、开机自启）：

```bash
bash scripts/deploy.sh              # 一键上传代码 + 同步依赖 + 重启服务（可重复执行）
```

服务器侧常用命令（`ssh jd_admin` 后）：

```bash
systemctl --user status lucky.service      # 看状态
journalctl --user -u lucky.service -f      # 跟日志
systemctl --user restart lucky.service     # 重启
```

注意：

1. **公网访问需在京东云控制台安全组放行 TCP 8666**（服务器内 `curl 127.0.0.1:8666` 正常而外网不通即为此原因）。
2. 公网环境建议改密码：编辑远端 `~/.config/systemd/user/lucky.service` 加一行 `Environment=LUCKY_ADMIN_TOKEN=强密码`，然后 `systemctl --user daemon-reload && systemctl --user restart lucky.service`（改后后台登录用新密码）。
3. 服务器数据库是独立的（本地测试库不上传）；部署后进 `/admin` 核对权重/库存，活动前点"全部补货"。

## 测试

- `tests/test_lottery.py`：概率数学（动态转移、概率守恒、边界）。
- `tests/test_api.py`：接口集成 + **并发不超卖**（16 线程抢 1 件大奖）。
- 网页端：6 玩法 × 6 主题全组合过一遍真实浏览器测试。
