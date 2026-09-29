# Lucky Play · 多形式 × 多主题抽奖系统

为 2026-09-30（国庆前一天）抽奖活动准备的可自托管抽奖站：2 种抽奖玩法 × 6 套视觉主题（含国庆主题），带概率后台、剩余奖品查询接口、谢谢参与动态概率转移。零外部资源（无 CDN/字体/图片素材），离线可用。

> 交接 / 发给别人：运行 `bash scripts/package.sh` 产出的干净压缩包直接可跑；接手须知见 `docs/HANDOVER.md`。

## 快速开始

```bash
uv sync                                   # 安装依赖（官方 PyPI：uv sync --no-config --default-index https://pypi.org/simple）
uv run uvicorn app.main:app --port 8666   # 启动
# 打开 http://127.0.0.1:8666        抽奖页
# 打开 http://127.0.0.1:8666/admin  后台
```

测试：`uv run --no-config pytest -q`

## 玩法（2 种）

| 玩法 | 说明 |
| --- | --- |
| 🎡 大转盘 | Canvas 转盘：蓄力回拉 → 爆发 → 长减速 → 过冲回摆，指针逐格弹跳 + 合成 tick 声。**奖池不含盖世小鸡手柄**（手柄仅老虎机可得） |
| 🎰 老虎机 | 三滚轮对对碰（服务端定结果）：全不同=没抽到；两同=该奖品×1；三同=该奖品×2；三同手柄=手柄+任选奖品；💎钻石代替谢谢参与上轴——两钻=中奖者现场在自选框挑一件非手柄奖品（点选→确认两步防误触，可取消重选，确认时刻才扣库存），三钻=超级大奖（除手柄外每类奖品各一，后台可开关） |

所有玩法支持**空格键**开始；结果弹窗打开时空格 = "再抽一次"，可全程一键连抽。

## 主题（6 套，页面右上角"风格"实时切换）

`festive 红金福运` / `national 国庆盛典（9·30 前夜专用：金星烟花 + 开奖倒计时）` / `neon 星空霓虹` / `macaron 云朵马卡龙` / `tech 未来科技` / `pixel 像素街机`

任一玩法 × 任一主题自由组合（12 种），选择存 localStorage。设计细节见 `docs/DESIGN.md`。

## 奖品（默认种子，后台可改）

不二家棒棒糖×53 · 奶龙手办×36 · 口袋笔记本×18 · NFC纪念卡×10 · 油画书签×8 · 鲨鱼匕首×6 · 电子爬宠×4 · 盖世小鸡手柄×1，另有谢谢参与（不限量）。

## 接口

公开：

| 接口 | 说明 |
| --- | --- |
| `GET /api/prizes` | **剩余奖品查询**：`{event, prizes:[{id,name,emoji,remaining,total}], total_remaining}` |
| `POST /api/draw` | 抽奖，body 可选 `{game:"wheel"\|"slot"}`（默认 wheel）。wheel 返回 `{result, prize, game}`；slot 另含 `prizes`（全部中奖明细，三同×2/超级大奖时多件）与 `symbols`（三轴符号，供动画对位） |
| `POST /api/slot/choose` | 双钻自选确认：`{token, prize_id}`（token 来自 slot 抽奖的 choose 回执，一次性）。此刻才扣库存并写抽奖记录；奖品刚被抽走返回 409 可换一件重选 |
| `GET /api/sample?count=7` | 按当前概率采样展示结果（无副作用、不扣库存），供概率验证脚本使用 |
| `GET /api/meta` | 活动名 / 开奖日期 / 副标 |

后台（请求头 `X-Admin-Token`；默认 `123456`，环境变量 `LUCKY_ADMIN_TOKEN` 覆盖）：

`GET /api/admin/state` · `PUT /api/admin/weights` · `PUT /api/admin/stock` · `PUT /api/admin/dynamic` · `PUT /api/admin/event` · `GET /api/admin/history?limit=` · `POST /api/admin/history/reset` · `POST /api/admin/replenish`

## 谢谢参与 · 动态概率

每个奖品有基础权重 W 与库存（总量 S、剩余 R）。**转盘与老虎机共用这套权重**（后台改一处，两个玩法同时生效）：

- **per_win 每抽一件渐移（默认）**：奖品有效权重 `W×R/S`，每抽走一件即有一份概率让给谢谢参与，抽空时恰好整体转移完；
- **depleted 抽空才整移**：剩余期间权重不变，抽空后 W 全额让给谢谢参与；
- 两种模式在奖品抽空/零库存时语义连续（权重整体让出）；关闭动态转移则抽空即退出奖池。
- 后台改权重 / 补货即时生效；补货后已转移概率自动回流（公式由库存推导，无状态漂移）。
- 老虎机另有独立配置：💎钻石权重、手柄开关、三钻超级大奖开关（后台「老虎机」区块），赔率按三轴独立口径实时展示。

默认权重：棒棒糖 30 · 奶龙 20 · 笔记本 15 · NFC卡 12 · 书签 10 · 鲨鱼匕首 8 · 电子爬宠 6 · 手柄 2 · 谢谢参与 9。

## 数据与部署

- SQLite 单文件（`data/lucky.db`，环境变量 `LUCKY_DB` 覆盖），抽奖在 `BEGIN IMMEDIATE` 事务内扣库存，并发不超卖（有测试保障）。
- 改奖品清单/默认权重：编辑 `app/store.py` 的 `DEFAULT_PRIZES` 后重启即自动补插新增奖品（幂等迁移，不动已调好的权重/库存；删除奖品需删库重建）。转盘/老虎机按奖品数自适应布局（当前 8 奖品 + 谢谢参与 = 9 项）；后台仅能改权重与库存。
- 公网部署务必设置 `LUCKY_ADMIN_TOKEN` 环境变量替换默认令牌。

### 云部署（已停用）

2026-09-29 起不再使用云服务器，仅本地运行。京东云上的服务已关闭：`lucky.service` 已 stop + disable、`loginctl disable-linger` 已关（不会开机自启），公网 8666 已不可达；服务器上的代码与数据库仍保留在 `/home/admin/lucky-play`，未删除。

如需恢复线上部署，`scripts/deploy.sh` 仍可用（SSH 别名 `jd_admin`）：

```bash
bash scripts/deploy.sh                     # 上传代码 + 装依赖 + 重启服务（可重复执行）
ssh jd_admin 'loginctl enable-linger admin && systemctl --user start lucky.service'
```

注意：公网访问需在京东云控制台安全组放行 TCP 8666；公网部署务必设置 `LUCKY_ADMIN_TOKEN` 替换默认令牌（服务器侧命令：`systemctl --user status/restart lucky.service`、`journalctl --user -u lucky.service -f`）；服务器数据库独立，恢复后先登 `/admin` 核对库存，活动前点"全部补货"。

## 测试

- `tests/test_lottery.py`：概率数学（动态转移、概率守恒、边界）。
- `tests/test_api.py`：接口集成 + **并发不超卖**（16 线程抢 1 件大奖）。
- 网页端：2 玩法 × 6 主题全组合过一遍真实浏览器测试。
