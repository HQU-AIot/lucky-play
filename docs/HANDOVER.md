# 交接说明（给接手/使用本项目的人）

> 生成时间 2026-09-28。项目：Lucky Play 多玩法抽奖站，为 2026-09-30（国庆前一天）活动准备。
> 读完这一份就能独立运行、管理和二次部署，不用翻其他文档。

## 1. 这是什么

- 4 种抽奖玩法（大转盘 / 九宫格 / 盲盒 / 老虎机）× 6 套视觉主题，网页抽奖站。
- 技术栈：Python FastAPI + SQLite（后端）、零构建原生 HTML/CSS/JS（前端），零外部资源、离线可用。
- 核心规则：**所有玩法都是"服务端先定结果、动画演给观众看"**，概率完全由后台控制。
- 一首 8 秒的歌《中奖概率倍儿高》贯穿全部玩法：歌里 5.0 秒处喊"停"，所有玩法恰在此刻出结果弹窗。

## 2. 拿到代码的三种方式

| 方式 | 适合 | 做法 |
| --- | --- | --- |
| 压缩包 | 发给同事直接跑 | 用打包脚本产出（见 §3），微信/网盘传 zip 即可 |
| Git 仓库 | 完整移交开发 | `git bundle create lucky-play.bundle main` 把 bundle 文件给对方，对方 `git clone lucky-play.bundle -b main lucky-play` |
| 云服务器 | ~~接手线上运营~~（已关闭） | 2026-09-29 起仅本地运行；云上服务已停止并取消自启，代码与数据库仍留在 `/home/admin/lucky-play`（恢复方法见 §5） |

## 3. 本地运行

要求：Python ≥ 3.11（Windows/Linux/macOS 均可）。

```bash
# Linux / macOS
cd lucky-play
python3 -m venv .venv
.venv/bin/pip install -i https://pypi.tuna.tsinghua.edu.cn/simple "fastapi>=0.115" "uvicorn>=0.30"
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8666

# Windows（PowerShell）
py -m venv .venv
.venv\Scripts\pip install -i https://pypi.tuna.tsinghua.edu.cn/simple "fastapi>=0.115" "uvicorn>=0.30"
.venv\Scripts\uvicorn app.main:app --host 127.0.0.1 --port 8666
```

打开 `http://127.0.0.1:8666` 抽奖页，`http://127.0.0.1:8666/admin` 后台。

## 4. 后台管理（活动运营必读）

后台地址 `/admin`，密码 **123456**（公网部署务必改，见 §6）。接手后建议按当前活动配置核对一遍：

| 配置 | 当前值 | 在后台哪里 |
| --- | --- | --- |
| 中奖音乐收刀点 | 5.0 秒（歌里"停"唱完的位置，试听可调） | 中奖音效 → 填秒数 → 试听 → 保存 |
| 谢谢参与权重 | 22.5（权重是相对值，概率=份额占比） | 奖品与概率表最后一行 |
| 动态转移 | 开启 / per_win（每抽一件，奖品概率按比例让给谢谢参与） | 动态概率下拉 |
| 奖品库存 | 满库共 136 件（棒棒糖53/奶龙36/笔记本18/NFC卡10/书签8/鲨鱼6/爬宠4/手柄1） | 每行 −/+/补满 直接改，即时生效 |

**活动前检查清单**：① 后台点"全部补货"；② 核对各奖品概率列；③ 试听收刀点（中奖时音乐停的位置）；④ 现场抽几次验证音效/画面（**空格键可开始/再抽一次，主持时一键连抽**）。

**两个容易踩的机制**（界面已有提示，这里再说一遍）：
- 谢谢参与权重设 0，概率也不为 0——动态转移会把奖品消耗掉的库存权重让给它；要它恒为 0 就关闭动态转移。
- per_win 模式下把某奖品"剩余"清零，它的权重会**全额转给谢谢参与**；想让奖品彻底退出奖池且概率不给谢谢参与，用"关闭动态转移"。

## 5. 云服务器部署（京东云，已停用）

2026-09-29 起项目仅在本地运行，云服务器上的服务已关闭：`lucky.service` 已 stop + disable、`loginctl disable-linger` 已关（不会开机自启），公网 8666 已不可达。服务器上的代码与数据库仍保留在 `/home/admin/lucky-play`，未删除。

如需恢复线上运营（SSH 别名 `jd_admin`）：

```bash
bash scripts/deploy.sh                                                    # 上传代码 + 装依赖 + 重启
ssh jd_admin 'loginctl enable-linger admin && systemctl --user start lucky.service'
```

- 公网访问需在京东云控制台**安全组放行 TCP 8666**（服务器内正常、外网不通即为此原因）。
- 服务器侧命令：`systemctl --user status/restart lucky.service`、`journalctl --user -u lucky.service -f`。
- 服务器数据库独立：本地测试数据不上传；接管后先登服务器版后台核对库存。
- 详细部署文档：`README.md`「云部署」一节。

## 6. 安全

默认密码 123456 仅限内网/可信场合。若重新公网部署务必换强密码：在服务器上编辑
`~/.config/systemd/user/lucky.service` 加一行 `Environment=LUCKY_ADMIN_TOKEN=强密码`，
然后 `systemctl --user daemon-reload && systemctl --user restart lucky.service`。

## 7. 目录地图

```
app/        FastAPI 后端（main.py 路由 / store.py 存储 / lottery.py 概率模型）
web/        前端（index.html 抽奖页、admin.html 后台、js/ 逻辑、css/ 皮肤、assets/ 音乐）
docs/       设计（DESIGN.md）、测试记录（TESTING.md）、本说明
scripts/    deploy.sh 云部署（已停用）、package.sh 打包、prob_check.py 概率验证
tests/      27 项自动化测试（uv run --no-config pytest -q 或 python -m pytest -q）
data/       SQLite 数据库（首次运行自动生成，测试数据不入库）
```

## 8. 改动前必知的三个"红线"

1. **别乱动 `RESULT_AT = 5.0`**（web/js/music.js）：这是歌里"停"的实测位置，全部玩法的出结果时刻都由它推导；改了会导致结果与音乐错位。
2. **奖品总数现为 8+谢谢参与=9 项**：转盘/九宫格/盲盒均为 9 项自适应布局；增删奖品改 `app/store.py` 的 `DEFAULT_PRIZES` 后重启即自动补插新增项（幂等迁移，不动已调好的权重/库存），删除奖品需删库重建。
3. **改前端代码后**：本地刷新即可生效（静态文件带 no-cache）；仅当恢复云部署时才需跑 `scripts/deploy.sh`。

## 9. 音乐素材版权备注

`web/assets/lucky-song.mp3` 是《中奖概率倍儿高》的翻唱版本（碎碎冰 Ice cream），仅内部活动使用，勿对外分发或商用。
